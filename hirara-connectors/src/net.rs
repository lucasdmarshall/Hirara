//! One egress policy for catalogs, MCP and OAuth. Never follow redirects with credentials.
use futures::{StreamExt, stream::BoxStream};
use http::{HeaderName, HeaderValue};
use rmcp::{
    model::ClientJsonRpcMessage,
    transport::{
        auth::{OAuthHttpClient, OAuthHttpClientFuture, OAuthHttpRequest},
        streamable_http_client::{
            StreamableHttpClient, StreamableHttpError as TransportError, StreamableHttpPostResponse,
        },
    },
};
use sse_stream::{Sse, SseStream};
use std::{
    collections::HashMap,
    net::{IpAddr, SocketAddr},
    sync::Arc,
    time::Duration,
};
use url::Url;

pub const LIMIT: usize = 4 * 1024 * 1024;
pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub fn fail(s: &str) -> Error {
    std::io::Error::other(s).into()
}

pub fn public_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v) => {
            let [a, b, c, _] = v.octets();
            !(matches!(a, 0 | 10 | 127 | 224..=255)
                || (a == 100 && (64..=127).contains(&b))
                || (a == 169 && b == 254)
                || (a == 172 && (16..=31).contains(&b))
                || (a == 192 && (b == 0 || b == 168 || (b == 88 && c == 99)))
                || (a == 198 && (b == 18 || b == 19 || (b == 51 && c == 100)))
                || (a == 203 && b == 0 && c == 113))
        }
        IpAddr::V6(v) => {
            let s = v.segments();
            (s[0] & 0xe000) == 0x2000
                && !(s[0] == 0x2001 && (s[1] < 0x200 || s[1] == 0xdb8))
                && s[0] != 0x2002
                && !(s[0] == 0x3fff && s[1] < 0x1000)
        }
    }
}
pub fn validate_url(s: &str) -> Result<Url, Error> {
    let u = Url::parse(s)?;
    if s.len() > 4096
        || u.scheme() != "https"
        || !u.username().is_empty()
        || u.password().is_some()
        || u.fragment().is_some()
        || u.query_pairs().any(|(k, _)| {
            [
                "token",
                "access_token",
                "api_key",
                "apikey",
                "key",
                "authorization",
            ]
            .contains(&k.to_ascii_lowercase().as_str())
        })
        || u.host_str().is_none()
    {
        return Err(fail(
            "a public HTTPS URL without credentials or fragment is required",
        ));
    }
    let host = u.host_str().unwrap().trim_matches(['[', ']']);
    if host.eq_ignore_ascii_case("localhost")
        || host.ends_with(".localhost")
        || host.ends_with(".local")
        || host.ends_with(".internal")
        || host == "metadata.google.internal"
    {
        return Err(fail("private destination denied"));
    }
    if let Ok(ip) = host.parse::<IpAddr>()
        && !public_ip(ip)
    {
        return Err(fail("private destination denied"));
    }
    Ok(u)
}
#[derive(Debug)]
struct Resolver {
    proxies: std::collections::HashSet<String>,
}
impl reqwest::dns::Resolve for Resolver {
    fn resolve(&self, name: reqwest::dns::Name) -> reqwest::dns::Resolving {
        let proxy = self.proxies.contains(name.as_str());
        Box::pin(async move {
            let addresses: Vec<SocketAddr> =
                tokio::net::lookup_host((name.as_str(), 0)).await?.collect();
            if addresses.is_empty() || (!proxy && addresses.iter().any(|s| !public_ip(s.ip()))) {
                return Err(fail("private DNS answer denied"));
            }
            Ok(Box::new(addresses.into_iter()) as reqwest::dns::Addrs)
        })
    }
}
#[derive(Clone)]
pub struct Net {
    pub client: reqwest::Client,
    pub proxied: bool,
    #[cfg(test)]
    pub local: bool,
}
impl Net {
    pub fn new() -> Result<Self, Error> {
        Self::with_proxy_trust(std::env::var("HCONNECT_TRUST_PROXY").as_deref() == Ok("true"))
    }
    pub fn with_proxy_trust(trust: bool) -> Result<Self, Error> {
        let proxy = if trust {
            ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"]
                .iter()
                .filter_map(|k| std::env::var(k).ok())
                .find(|s| !s.is_empty())
        } else {
            None
        };
        let proxies = [
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "ALL_PROXY",
            "https_proxy",
            "http_proxy",
            "all_proxy",
        ]
        .iter()
        .filter_map(|k| std::env::var(k).ok())
        .filter_map(|s| Url::parse(&s).ok())
        .filter_map(|u| u.host_str().map(String::from))
        .collect();
        let mut builder = reqwest::Client::builder()
            .dns_resolver(Arc::new(Resolver { proxies }))
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(40))
            .user_agent("Hirara-Connectors/0.2.1");
        // An explicitly trusted proxy is mandatory for every external HTTPS request.
        // No NO_PROXY/direct fallback can evade the proxy's destination/DNS policy.
        if let Some(proxy) = &proxy {
            builder = builder.proxy(reqwest::Proxy::https(proxy)?.no_proxy(None));
        }
        Ok(Self {
            client: builder.build()?,
            proxied: proxy.is_some(),
            #[cfg(test)]
            local: false,
        })
    }

    pub async fn guard(&self, url: &str) -> Result<(), Error> {
        #[cfg(test)]
        if self.local && Url::parse(url)?.host_str() == Some("127.0.0.1") {
            return Ok(());
        }
        let u = validate_url(url)?;
        if self.proxied {
            return Ok(());
        }
        let addresses: Vec<_> = tokio::net::lookup_host((
            u.host_str().unwrap().trim_matches(['[', ']']),
            u.port_or_known_default().unwrap(),
        ))
        .await?
        .collect();
        if addresses.is_empty() || addresses.iter().any(|s| !public_ip(s.ip())) {
            return Err(fail("private DNS answer denied"));
        }
        Ok(())
    }
    pub async fn bytes(response: reqwest::Response) -> Result<Vec<u8>, Error> {
        if response.content_length().is_some_and(|n| n > LIMIT as u64) {
            return Err(fail("response exceeds 4 MiB"));
        }
        let mut stream = response.bytes_stream();
        let mut out = Vec::new();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk?;
            if out.len() + chunk.len() > LIMIT {
                return Err(fail("response exceeds 4 MiB"));
            }
            out.extend_from_slice(&chunk);
        }
        Ok(out)
    }
    pub async fn json(&self, url: &str) -> Result<serde_json::Value, Error> {
        self.guard(url).await?;
        let response = self.client.get(url).send().await?;
        if !response.status().is_success() {
            return Err(fail("catalog unavailable"));
        }
        Ok(serde_json::from_slice(&Self::bytes(response).await?)?)
    }
    pub async fn text(&self, url: &str) -> Result<String, Error> {
        self.guard(url).await?;
        let response = self.client.get(url).send().await?;
        if !response.status().is_success() {
            return Err(fail("catalog unavailable"));
        }
        Ok(String::from_utf8(Self::bytes(response).await?)?)
    }
    fn stream(response: reqwest::Response) -> BoxStream<'static, Result<Sse, sse_stream::Error>> {
        // Bound the entire stream, so even a single unterminated event is bounded.
        let mut size = 0usize;
        let stream = response
            .bytes_stream()
            .map(move |chunk| -> Result<_, std::io::Error> {
                let chunk = chunk.map_err(|_| std::io::Error::other("stream read failed"))?;
                size = size.saturating_add(chunk.len());
                if size > LIMIT {
                    return Err(std::io::Error::other("SSE stream exceeds 4 MiB"));
                }
                Ok(chunk)
            });
        SseStream::from_bytes_stream(stream).boxed()
    }
    async fn request(
        &self,
        method: reqwest::Method,
        url: &str,
        session: Option<&str>,
        token: Option<String>,
        headers: HashMap<HeaderName, HeaderValue>,
    ) -> Result<reqwest::RequestBuilder, Error> {
        self.guard(url).await?;
        let mut b = self
            .client
            .request(method, url)
            .header("accept", "application/json, text/event-stream");
        if let Some(s) = session {
            b = b.header("mcp-session-id", s);
        }
        if let Some(t) = token {
            b = b.bearer_auth(t);
        }
        for (k, v) in headers {
            if k == http::header::AUTHORIZATION
                || k == http::header::HOST
                || k == http::header::COOKIE
            {
                return Err(fail("reserved header denied"));
            }
            b = b.header(k, v);
        }
        Ok(b)
    }
}
impl OAuthHttpClient for Net {
    fn execute(&self, operation: OAuthHttpRequest) -> OAuthHttpClientFuture<'_> {
        Box::pin(async move {
            let (parts, body) = operation.request.into_parts();
            let url = parts.uri.to_string();
            self.guard(&url).await?;
            let response = self
                .client
                .request(parts.method, &url)
                .headers(parts.headers)
                .body(body)
                .send()
                .await?;
            let status = response.status();
            let headers = response.headers().clone();
            let body = Self::bytes(response).await?;
            let mut result = http::Response::builder().status(status).body(body)?;
            *result.headers_mut() = headers;
            Ok(result)
        })
    }
}
// Do not leak upstream response bodies, URLs or credentials in transport errors.
type TE = TransportError<std::io::Error>;
fn transport_error(_: impl std::fmt::Display) -> TE {
    TransportError::Client(std::io::Error::other(
        "upstream transport failed; check credentials, scopes and endpoint",
    ))
}
impl StreamableHttpClient for Net {
    type Error = std::io::Error;
    async fn post_message(
        &self,
        uri: Arc<str>,
        message: ClientJsonRpcMessage,
        session: Option<Arc<str>>,
        token: Option<String>,
        headers: HashMap<HeaderName, HeaderValue>,
    ) -> Result<StreamableHttpPostResponse, TE> {
        let response = self
            .request(
                reqwest::Method::POST,
                &uri,
                session.as_deref(),
                token,
                headers,
            )
            .await
            .map_err(transport_error)?
            .json(&message)
            .send()
            .await
            .map_err(transport_error)?;
        let status = response.status();
        if status == reqwest::StatusCode::NOT_FOUND && session.is_some() {
            return Err(TransportError::SessionExpired);
        }
        if !status.is_success() {
            return Err(transport_error(status));
        }
        let sid = response
            .headers()
            .get("mcp-session-id")
            .and_then(|x| x.to_str().ok())
            .map(String::from);
        if status == reqwest::StatusCode::ACCEPTED || status == reqwest::StatusCode::NO_CONTENT {
            return Ok(StreamableHttpPostResponse::Accepted);
        }
        let ct = response
            .headers()
            .get("content-type")
            .and_then(|x| x.to_str().ok())
            .unwrap_or("");
        if ct.starts_with("text/event-stream") {
            return Ok(StreamableHttpPostResponse::Sse(Self::stream(response), sid));
        }
        let bytes = Self::bytes(response).await.map_err(transport_error)?;
        if bytes.is_empty() && !matches!(message, ClientJsonRpcMessage::Request(_)) {
            return Ok(StreamableHttpPostResponse::Accepted);
        }
        Ok(StreamableHttpPostResponse::Json(
            serde_json::from_slice(&bytes).map_err(transport_error)?,
            sid,
        ))
    }
    async fn delete_session(
        &self,
        uri: Arc<str>,
        session: Arc<str>,
        token: Option<String>,
        headers: HashMap<HeaderName, HeaderValue>,
    ) -> Result<(), TE> {
        let response = self
            .request(
                reqwest::Method::DELETE,
                &uri,
                Some(&session),
                token,
                headers,
            )
            .await
            .map_err(transport_error)?
            .send()
            .await
            .map_err(transport_error)?;
        if response.status().is_success() || response.status() == reqwest::StatusCode::NOT_FOUND {
            Ok(())
        } else {
            Err(TransportError::ServerDoesNotSupportDeleteSession)
        }
    }
    async fn get_stream(
        &self,
        uri: Arc<str>,
        session: Option<Arc<str>>,
        last: Option<String>,
        token: Option<String>,
        headers: HashMap<HeaderName, HeaderValue>,
    ) -> Result<BoxStream<'static, Result<Sse, sse_stream::Error>>, TE> {
        let mut request = self
            .request(
                reqwest::Method::GET,
                &uri,
                session.as_deref(),
                token,
                headers,
            )
            .await
            .map_err(transport_error)?;
        if let Some(last) = last {
            request = request.header("last-event-id", last);
        }
        let response = request.send().await.map_err(transport_error)?;
        if response.status() == reqwest::StatusCode::METHOD_NOT_ALLOWED {
            return Err(TransportError::ServerDoesNotSupportSse);
        }
        if !response.status().is_success() {
            return Err(transport_error(response.status()));
        }
        Ok(Self::stream(response))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn body_and_unterminated_sse_limits() {
        let response = reqwest::Response::from(http::Response::new(vec![b'a'; LIMIT + 1]));
        assert!(Net::bytes(response).await.is_err());
        let response = reqwest::Response::from(http::Response::new(vec![b'a'; LIMIT + 1]));
        let mut stream = Net::stream(response);
        assert!(stream.next().await.unwrap().is_err());
    }

    #[test]
    fn reject_private_and_credentials() {
        for u in [
            "http://example.com",
            "https://127.0.0.1",
            "https://2130706433",
            "https://[::1]",
            "https://[::ffff:127.0.0.1]",
            "https://100.100.100.200",
            "https://user:pass@example.com",
            "https://metadata.google.internal",
            "https://example.com/#token",
        ] {
            assert!(validate_url(u).is_err(), "{u}");
        }
        assert!(validate_url("https://example.com/mcp").is_ok());
    }
}
