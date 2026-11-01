use crate::{
    net::{Error, LIMIT, Net, fail},
    store::{Connection, Store},
};
use rmcp::{
    ServiceExt,
    model::{
        CallToolRequestParams, ClientConfig, Implementation, PaginatedRequestParams,
        ProtocolVersion,
    },
    transport::{
        StreamableHttpClientTransport,
        auth::{AuthorizationManager, AuthorizationRequest, AuthorizationSession},
        streamable_http_client::StreamableHttpClientTransportConfig,
    },
};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::Mutex;

#[derive(Clone)]
pub struct Runtime {
    pub net: Net,
    pub store: Store,
    pub callback: String,
    pending: Arc<Mutex<HashMap<String, Pending>>>,
    locks: Arc<Mutex<HashMap<String, Arc<Mutex<()>>>>>,
}
struct Pending {
    created: Instant,
    id: String,
    owner: String,
    session: AuthorizationSession,
}
impl Runtime {
    pub fn new(net: Net, store: Store, callback: String) -> Self {
        Self {
            net,
            store,
            callback,
            pending: Default::default(),
            locks: Default::default(),
        }
    }
    pub async fn lock(&self, id: &str) -> tokio::sync::OwnedMutexGuard<()> {
        let mut locks = self.locks.lock().await;
        // Only persisted (max 256) connections enter this map; removed locks can be reclaimed.
        locks.retain(|_, lock| Arc::strong_count(lock) > 1);
        let lock = locks
            .entry(id.into())
            .or_insert_with(|| Arc::new(Mutex::new(())))
            .clone();
        drop(locks);
        lock.lock_owned().await
    }
    async fn manager(&self, c: &Connection) -> Result<AuthorizationManager, Error> {
        self.net.guard(&c.endpoint).await?;
        let mut manager = AuthorizationManager::new_with_oauth_http_client(
            c.endpoint.as_str(),
            Arc::new(self.net.clone()),
        )
        .await
        .map_err(|_| fail("OAuth initialization failed"))?;
        manager.set_credential_store(self.store.credentials(&c.owner, &c.id));
        Ok(manager)
    }
    pub async fn authorize(&self, c: &Connection) -> Result<Value, Error> {
        let mut pending = self.pending.lock().await;
        pending.retain(|_, p| p.created.elapsed() < Duration::from_secs(600));
        if let Some(p) = pending
            .values()
            .find(|p| p.id == c.id && p.owner == c.owner)
        {
            return Ok(
                json!({"status":"authorization_required","authorization_url":p.session.get_authorization_url(),"expires_in_seconds":600-p.created.elapsed().as_secs()}),
            );
        }
        if pending.len() >= 128 {
            return Err(fail("too many pending authorizations"));
        }
        drop(pending);
        let mut manager = self.manager(c).await?;
        let metadata = manager.resolve_metadata().await.map_err(|_| {
            fail("OAuth discovery failed; provider may require a registered client")
        })?;
        manager.set_metadata(metadata.metadata);
        let mut request = AuthorizationRequest::new(&self.callback)
            .with_client_name("Hirara Connectors")
            .with_initial_scope_selection();
        if let Some(id) = &c.client_id {
            request = request.with_preregistered_client(id);
        }
        let session=AuthorizationSession::new(manager,request).await.map_err(|_|fail("OAuth client setup failed; configure a provider-approved client ID if dynamic registration is unavailable"))?;
        let url = session.get_authorization_url().to_string();
        self.net.guard(&url).await?;
        let state = url::Url::parse(&url)?
            .query_pairs()
            .find(|(k, _)| k == "state")
            .map(|(_, v)| v.into_owned())
            .ok_or_else(|| fail("OAuth state missing"))?;
        let mut pending = self.pending.lock().await;
        if pending.len() >= 128 {
            return Err(fail("too many pending authorizations"));
        }
        pending.insert(
            state,
            Pending {
                created: Instant::now(),
                id: c.id.clone(),
                owner: c.owner.clone(),
                session,
            },
        );
        Ok(
            json!({"status":"authorization_required","authorization_url":url,"expires_in_seconds":600}),
        )
    }
    pub async fn callback(
        &self,
        state: &str,
        code: &str,
        issuer: Option<&str>,
    ) -> Result<(), Error> {
        if state.len() > 4096 || code.len() > 8192 {
            return Err(fail("invalid callback"));
        }
        let p = self
            .pending
            .lock()
            .await
            .remove(state)
            .ok_or_else(|| fail("authorization expired or already used"))?;
        if p.created.elapsed() > Duration::from_secs(600) {
            return Err(fail("authorization expired"));
        }
        let _lock = self.lock(&p.id).await;
        self.store.get(&p.owner, &p.id)?;
        p.session
            .handle_callback_with_issuer(code, state, issuer)
            .await
            .map_err(|_| fail("authorization callback failed; restart authorization"))?;
        Ok(())
    }
    pub async fn use_connection(
        &self,
        owner: &str,
        id: &str,
        tool: Option<(&str, Value)>,
    ) -> Result<Value, Error> {
        let c = self.store.get(owner, id)?;
        let _lock = self.lock(id).await;
        // Recheck after waiting: disconnect may have removed it.
        let c = self.store.get(owner, &c.id)?;
        let token = match c.mode.as_str() {
            "none" | "api_key" => None,
            "bearer" => Some(
                c.bearer
                    .clone()
                    .ok_or_else(|| fail("credential setup required"))?,
            ),
            "oauth" => {
                if !c.oauth.as_ref().is_some_and(|x| x.token_response.is_some()) {
                    return self.authorize(&c).await;
                }
                let mut manager = self.manager(&c).await?;
                if !manager
                    .initialize_from_store()
                    .await
                    .map_err(|_| fail("OAuth credentials need reauthorization"))?
                {
                    return self.authorize(&c).await;
                }
                Some(manager.get_access_token().await.map_err(|_| {
                    fail("OAuth token refresh failed; reconnect to authorize again")
                })?)
            }
            _ => return Err(fail("unsupported authentication mode")),
        };
        let mut config = StreamableHttpClientTransportConfig::with_uri(c.endpoint.clone())
            .max_concurrent_requests(1);
        if c.mode == "api_key" {
            let name = http::HeaderName::from_bytes(
                c.header_name
                    .as_deref()
                    .ok_or_else(|| fail("API key header missing"))?
                    .as_bytes(),
            )?;
            let mut value = http::HeaderValue::from_str(
                c.bearer.as_deref().ok_or_else(|| fail("API key missing"))?,
            )?;
            value.set_sensitive(true);
            config.custom_headers.insert(name, value);
        }
        config.reinit_on_expired_session = false;
        config.max_sse_event_size = LIMIT;
        if let Some(token) = token {
            config = config.auth_header(token);
        }
        let transport = StreamableHttpClientTransport::with_client(self.net.clone(), config);
        let info = ClientConfig::new(
            Default::default(),
            Implementation::new("hirara-connectors", "0.3.0"),
        )
        .with_protocol_version(ProtocolVersion::V_2025_11_25);
        let client = info
            .serve(transport)
            .await
            .map_err(|_| fail("MCP connection failed; check endpoint, credentials and scopes"))?;
        // Cleanup runs even when a call times out. Calls are never automatically replayed.
        let operation = async {
            let mut tools = Vec::new();
            let mut cursor = None;
            for page in 0..20 {
                let params = cursor.map(|cursor| {
                    let mut p = PaginatedRequestParams::default();
                    p.cursor = Some(cursor);
                    p
                });
                let result = client
                    .list_tools(params)
                    .await
                    .map_err(|_| fail("MCP tool discovery failed"))?;
                tools.extend(result.tools);
                if serde_json::to_vec(&tools)?.len() > LIMIT {
                    return Err(fail("upstream tool catalog exceeds 4 MiB"));
                }
                if tools.len() > 1000 {
                    return Err(fail("upstream tool limit exceeded"));
                }
                cursor = result.next_cursor;
                if cursor.is_none() {
                    break;
                }
                if page == 19 {
                    return Err(fail("upstream pagination limit exceeded"));
                }
            }
            tools.retain(|t| {
                c.allowed_tools
                    .iter()
                    .any(|g| g == "*" || g == t.name.as_ref())
            });
            if let Some((name, arguments)) = tool {
                let definition = tools
                    .iter()
                    .find(|t| t.name == name)
                    .ok_or_else(|| fail("upstream tool is absent or not permitted"))?;
                let schema = serde_json::to_value(&definition.input_schema)?;
                if serde_json::to_vec(&schema)?.len() > 65536 {
                    return Err(fail("upstream input schema exceeds 64 KiB"));
                }
                if external_refs(&schema) {
                    return Err(fail("external schema references are not supported"));
                }
                let validator = jsonschema::validator_for(&schema)
                    .map_err(|_| fail("upstream input schema is invalid or unsupported"))?;
                if !validator.is_valid(&arguments) {
                    return Err(fail("arguments do not match the upstream input schema"));
                }
                let arguments = arguments
                    .as_object()
                    .ok_or_else(|| fail("arguments must be an object"))?
                    .clone();
                let response=client.call_tool(CallToolRequestParams::new(name.to_string()).with_arguments(arguments)).await.map_err(|_|fail("upstream call failed; outcome may be unknown; do not automatically retry writes"))?;
                let raw = serde_json::to_value(response)?;
                Ok(
                    json!({"connection_id":id,"result":raw,"error":if raw["isError"]==true {Some("upstream tool reported an error")}else{None}}),
                )
            } else {
                Ok(json!({"connection_id":id,"status":"connected","tools":tools}))
            }
        };
        let result=tokio::time::timeout(Duration::from_secs(50),operation).await.unwrap_or_else(|_|Err(fail("MCP operation timed out; outcome may be unknown; do not automatically retry writes")));
        let _ = tokio::time::timeout(Duration::from_secs(5), client.cancel()).await;
        let value = result?;
        if serde_json::to_vec(&value)?.len() > LIMIT {
            return Err(fail("connector output limit exceeded"));
        }
        Ok(value)
    }
}
fn external_refs(v: &Value) -> bool {
    match v {
        Value::Object(m) => m.iter().any(|(k, v)| {
            (k == "$ref" && v.as_str().is_some_and(|s| !s.starts_with('#'))) || external_refs(v)
        }),
        Value::Array(a) => a.iter().any(external_refs),
        _ => false,
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn schema_does_not_fetch_external_resources() {
        assert!(external_refs(
            &json!({"items":{"$ref":"http://localhost/secret"}})
        ));
        assert!(!external_refs(&json!({"$ref":"#/$defs/a"})));
    }
}

#[cfg(test)]
mod integration_tests {
    use super::*;
    use axum::{
        Form, Json, Router,
        extract::{Path, State},
        http::{HeaderMap, StatusCode},
        response::IntoResponse,
        routing::{get, post},
    };
    use std::sync::{
        Mutex as StdMutex,
        atomic::{AtomicUsize, Ordering},
    };
    #[derive(Clone)]
    struct Fake {
        base: String,
        calls: Arc<AtomicUsize>,
        refresh: Arc<AtomicUsize>,
        seen: Arc<StdMutex<Vec<String>>>,
    }
    async fn mcp(
        State(s): State<Fake>,
        headers: HeaderMap,
        Json(v): Json<Value>,
    ) -> axum::response::Response {
        let method = v["method"].as_str().unwrap_or("");
        s.seen.lock().unwrap().push(method.into());
        if headers.get("authorization").and_then(|h| h.to_str().ok()) != Some("Bearer secret")
            && headers.get("x-api-key").and_then(|h| h.to_str().ok()) != Some("secret")
        {
            return StatusCode::UNAUTHORIZED.into_response();
        }
        let result = match method {
            "initialize" => {
                json!({"protocolVersion":"2025-11-25","serverInfo":{"name":"fixture","version":"1"},"capabilities":{"tools":{}}})
            }
            "notifications/initialized" => return StatusCode::ACCEPTED.into_response(),
            "tools/list" => {
                json!({"tools":[{"name":"read","description":"fixture","inputSchema":{"type":"object","properties":{"fail":{"type":"boolean"},"uncertain":{"type":"boolean"},"sse":{"type":"boolean"}},"additionalProperties":false}},{"name":"delete","inputSchema":{"type":"object"}}]})
            }
            "tools/call" => {
                s.calls.fetch_add(1, Ordering::SeqCst);
                if v["params"]["arguments"]["uncertain"] == true {
                    return StatusCode::SERVICE_UNAVAILABLE.into_response();
                }
                json!({"content":[{"type":"text","text":"fixture result"}],"isError":v["params"]["arguments"]["fail"]==true})
            }
            _ => return StatusCode::BAD_REQUEST.into_response(),
        };
        let wire = json!({"jsonrpc":"2.0","id":v["id"],"result":result});
        let mut response = if v["params"]["arguments"]["sse"] == true {
            (
                [("content-type", "text/event-stream")],
                format!("data: {wire}\n\n"),
            )
                .into_response()
        } else {
            Json(wire).into_response()
        };
        response
            .headers_mut()
            .insert("mcp-session-id", "fixture-session".parse().unwrap());
        response
    }
    async fn metadata(State(s): State<Fake>, Path(path): Path<String>) -> Json<Value> {
        if path.starts_with("oauth-protected-resource") {
            Json(
                json!({"resource":format!("{}/mcp",s.base),"authorization_servers":[s.base],"scopes_supported":["read","offline_access"]}),
            )
        } else {
            Json(
                json!({"issuer":s.base,"authorization_endpoint":format!("{}/authorize",s.base),"token_endpoint":format!("{}/token",s.base),"response_types_supported":["code"],"grant_types_supported":["authorization_code","refresh_token"],"code_challenge_methods_supported":["S256"],"scopes_supported":["read","offline_access"]}),
            )
        }
    }
    async fn token(State(s): State<Fake>, Form(v): Form<HashMap<String, String>>) -> Json<Value> {
        assert_eq!(v.get("resource"), Some(&format!("{}/mcp", s.base)));
        match v.get("grant_type").map(String::as_str) {
            Some("authorization_code") => {
                assert!(v.contains_key("code_verifier"));
                assert_eq!(v.get("code").map(String::as_str), Some("test-code"));
            }
            Some("refresh_token") => {
                s.refresh.fetch_add(1, Ordering::SeqCst);
                assert_eq!(
                    v.get("refresh_token").map(String::as_str),
                    Some("refresh-secret")
                );
            }
            _ => panic!("unexpected OAuth grant"),
        }
        Json(
            json!({"access_token":"secret","token_type":"Bearer","refresh_token":"refresh-secret","expires_in":3600,"scope":"read offline_access"}),
        )
    }
    async fn fixture() -> (Fake, Net, tokio::task::JoinHandle<()>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let fake = Fake {
            base: format!("http://{}", listener.local_addr().unwrap()),
            calls: Default::default(),
            refresh: Default::default(),
            seen: Default::default(),
        };
        let router = Router::new()
            .route(
                "/mcp",
                post(mcp).delete(|| async { StatusCode::NO_CONTENT }),
            )
            .route("/.well-known/{*path}", get(metadata))
            .route("/token", post(token))
            .with_state(fake.clone());
        let task = tokio::spawn(async move {
            axum::serve(listener, router).await.unwrap();
        });
        let net = Net {
            client: reqwest::Client::builder().no_proxy().build().unwrap(),
            local: true,
            proxied: false,
        };
        (fake, net, task)
    }
    #[tokio::test]
    async fn real_mcp_calls_grants_errors_and_restart() {
        let (fake, net, task) = fixture().await;
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path(), &[7; 32]).unwrap();
        let c = Connection {
            id: "saved".into(),
            owner: "alice".into(),
            title: "fixture".into(),
            endpoint: format!("{}/mcp", fake.base),
            allowed_tools: vec!["read".into()],
            mode: "bearer".into(),
            header_name: None,
            bearer: Some("secret".into()),
            oauth: None,
            client_id: None,
        };
        store.put(c).unwrap();
        let runtime = Runtime::new(
            net.clone(),
            store.clone(),
            format!("{}/callback", fake.base),
        );
        assert!(runtime.use_connection("bob", "saved", None).await.is_err());
        let result = runtime
            .use_connection("alice", "saved", None)
            .await
            .unwrap();
        assert_eq!(result["tools"].as_array().unwrap().len(), 1);
        assert!(
            runtime
                .use_connection("alice", "saved", Some(("delete", json!({}))))
                .await
                .is_err()
        );
        assert!(
            runtime
                .use_connection("alice", "saved", Some(("read", json!({"unexpected":true}))))
                .await
                .is_err()
        );
        assert_eq!(fake.calls.load(Ordering::SeqCst), 0);
        let failed = runtime
            .use_connection("alice", "saved", Some(("read", json!({"fail":true}))))
            .await
            .unwrap();
        assert!(failed["error"].is_string());
        assert_eq!(failed["result"]["isError"], true);
        drop(runtime);
        drop(store);
        let store = Store::open(dir.path(), &[7; 32]).unwrap();
        let runtime = Runtime::new(net, store, "unused".into());
        let result = runtime
            .use_connection("alice", "saved", Some(("read", json!({}))))
            .await
            .unwrap();
        assert!(result["error"].is_null());
        assert_eq!(fake.calls.load(Ordering::SeqCst), 2);
        task.abort();
    }
    #[tokio::test]
    async fn api_key_sse_and_uncertain_writes_are_not_replayed() {
        let (fake, net, task) = fixture().await;
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path(), &[2; 32]).unwrap();
        let c = Connection {
            id: "key".into(),
            owner: "alice".into(),
            title: "key fixture".into(),
            endpoint: format!("{}/mcp", fake.base),
            allowed_tools: vec!["read".into()],
            mode: "api_key".into(),
            bearer: Some("secret".into()),
            header_name: Some("x-api-key".into()),
            oauth: None,
            client_id: None,
        };
        store.put(c).unwrap();
        let runtime = Runtime::new(net, store, "unused".into());
        let result = runtime
            .use_connection("alice", "key", Some(("read", json!({"sse":true}))))
            .await
            .unwrap();
        assert!(result["error"].is_null());
        assert!(
            runtime
                .use_connection("alice", "key", Some(("read", json!({"uncertain":true}))))
                .await
                .is_err()
        );
        assert_eq!(fake.calls.load(Ordering::SeqCst), 2);
        task.abort();
    }
    #[tokio::test]
    async fn oauth_pkce_callback_replay_refresh_and_restart() {
        let (fake, net, task) = fixture().await;
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path(), &[4; 32]).unwrap();
        let c = Connection {
            id: "oauth".into(),
            owner: "alice".into(),
            title: "OAuth fixture".into(),
            endpoint: format!("{}/mcp", fake.base),
            allowed_tools: vec!["read".into()],
            mode: "oauth".into(),
            header_name: None,
            bearer: None,
            oauth: None,
            client_id: Some("hirara-test".into()),
        };
        store.put(c.clone()).unwrap();
        let runtime = Runtime::new(
            net.clone(),
            store.clone(),
            format!("{}/callback", fake.base),
        );
        let flow = runtime.authorize(&c).await.unwrap();
        let url = url::Url::parse(flow["authorization_url"].as_str().unwrap()).unwrap();
        let params: HashMap<_, _> = url
            .query_pairs()
            .map(|(k, v)| (k.into_owned(), v.into_owned()))
            .collect();
        assert_eq!(params["code_challenge_method"], "S256");
        let state = &params["state"];
        assert!(
            runtime
                .callback("wrong-state", "test-code", None)
                .await
                .is_err()
        );
        runtime
            .callback(state, "test-code", Some(&fake.base))
            .await
            .unwrap();
        assert!(
            runtime
                .callback(state, "test-code", Some(&fake.base))
                .await
                .is_err()
        );
        let mut c = store.get("alice", "oauth").unwrap();
        let oauth = c.oauth.as_mut().unwrap();
        assert!(oauth.token_response.is_some());
        oauth.token_received_at = Some(0);
        store.put(c).unwrap();
        drop(runtime);
        drop(store);
        let store = Store::open(dir.path(), &[4; 32]).unwrap();
        let runtime = Runtime::new(net, store, "unused".into());
        runtime
            .use_connection("alice", "oauth", Some(("read", json!({}))))
            .await
            .unwrap();
        assert_eq!(fake.refresh.load(Ordering::SeqCst), 1);
        task.abort();
    }
}
