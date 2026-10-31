//! Browser approval is a separate capability from the agent's MCP credential.
//! Use origin-scoped browser storage, not cookies (cookies are shared across ports).
use crate::{api::State as App, store::random_id};
use axum::{
    Json,
    extract::State,
    http::{HeaderMap, HeaderValue, StatusCode},
    response::{Html, IntoResponse, Response},
};
use hmac::{Hmac, Mac};
use serde_json::{Value, json};
use sha2::Sha256;
use std::{
    sync::Mutex,
    time::{Duration, Instant},
};

pub struct BrowserSession {
    proof_key: String,
    ticket: Mutex<Option<(String, Instant)>>,
    credential: Mutex<(String, Instant)>,
}
impl BrowserSession {
    pub fn new(proof_key: String) -> Self {
        Self {
            proof_key,
            ticket: Mutex::new(None),
            credential: Mutex::new((random_id(), Instant::now())),
        }
    }
    pub fn ticket(&self) -> String {
        let ticket = random_id();
        *self.ticket.lock().unwrap() = Some((ticket.clone(), Instant::now()));
        ticket
    }
    fn exchange(&self, ticket: &str) -> Option<String> {
        let mut pending = self.ticket.lock().unwrap();
        if !pending.as_ref().is_some_and(|(value, when)| {
            crate::api::equal(value, ticket) && when.elapsed() < Duration::from_secs(120)
        }) {
            return None;
        }
        pending.take();
        let mut credential = self.credential.lock().unwrap();
        *credential = (random_id(), Instant::now());
        Some(credential.0.clone())
    }
    pub fn authorized(&self, headers: &HeaderMap, origin: &str, require_origin: bool) -> bool {
        if require_origin && headers.get("origin").and_then(|v| v.to_str().ok()) != Some(origin) {
            return false;
        }
        let Some(given) = headers
            .get("authorization")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.strip_prefix("Bearer "))
        else {
            return false;
        };
        let c = self.credential.lock().unwrap();
        c.1.elapsed() < Duration::from_secs(8 * 3600) && crate::api::equal(&c.0, given)
    }
    pub fn proof(&self, origin: &str, challenge: &str) -> String {
        proof(&self.proof_key, origin, challenge)
    }
}
pub fn proof(key: &str, origin: &str, challenge: &str) -> String {
    let mut mac =
        Hmac::<Sha256>::new_from_slice(key.as_bytes()).expect("HMAC accepts any key size");
    mac.update(format!("Hirara local service v1:{origin}:{challenge}").as_bytes());
    mac.finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn deny() -> Response {
    (
        StatusCode::UNAUTHORIZED,
        Json(json!({"error":"Open Hirara's local browser session first: hirara-connectors open"})),
    )
        .into_response()
}
pub async fn home(State(state): State<App>) -> Response {
    if state.browser.is_none() {
        return StatusCode::NOT_FOUND.into_response();
    }
    page(
        "<p class=page-kicker>YOUR CONNECTIONS</p><h1>A place for your tools.</h1><p class=intro>Find a connector with your AI agent, then open its connection link here to choose what it can access.</p><p id=status class=home-state>Preparing your browser session…</p><div id=connections></div>",
    )
}
pub async fn session(
    State(state): State<App>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Response {
    if headers.get("origin").and_then(|v| v.to_str().ok()) != Some(state.public_url.as_str()) {
        return deny();
    }
    let Some(browser) = &state.browser else {
        return deny();
    };
    let Some(ticket) = body["ticket"].as_str() else {
        return deny();
    };
    let Some(token) = browser.exchange(ticket) else {
        return deny();
    };
    let mut response = Json(json!({"token":token})).into_response();
    response
        .headers_mut()
        .insert("cache-control", HeaderValue::from_static("no-store"));
    response
}
pub async fn open(State(state): State<App>, headers: HeaderMap) -> Response {
    if !state.operator(&headers) {
        return deny();
    }
    let Some(browser) = &state.browser else {
        return StatusCode::NOT_FOUND.into_response();
    };
    Json(json!({"url":format!("{}/local#{}",state.public_url,browser.ticket())})).into_response()
}
pub async fn proof_handler(State(state): State<App>, Json(body): Json<Value>) -> Response {
    let Some(browser) = &state.browser else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let Some(challenge) = body["challenge"]
        .as_str()
        .filter(|c| (32..=128).contains(&c.len()) && c.bytes().all(|b| b.is_ascii_hexdigit()))
    else {
        return StatusCode::BAD_REQUEST.into_response();
    };
    Json(json!({"proof":browser.proof(&state.public_url,challenge)})).into_response()
}
pub async fn connections(State(state): State<App>, headers: HeaderMap) -> Response {
    let Some(browser) = &state.browser else {
        return deny();
    };
    if !browser.authorized(&headers, &state.public_url, false) {
        return deny();
    }
    Json(json!({"connections":state.runtime.store.list("local").iter().map(crate::store::Connection::public).collect::<Vec<_>>()})).into_response()
}
pub fn page(content: &str) -> Response {
    let nonce = random_id();
    let html = include_str!("../ui/frame.html")
        .replace("{{STYLE}}", include_str!("../ui/portal.css"))
        .replace("{{SCRIPT}}", include_str!("../ui/portal.js"))
        .replace("{{NONCE}}", &nonce)
        .replace("{{CONTENT}}", content);
    let mut response = Html(html).into_response();
    let h = response.headers_mut();
    h.insert("cache-control", HeaderValue::from_static("no-store"));
    h.insert("referrer-policy", HeaderValue::from_static("no-referrer"));
    h.insert(
        "x-content-type-options",
        HeaderValue::from_static("nosniff"),
    );
    h.insert("content-security-policy",HeaderValue::from_str(&format!("default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; img-src 'self'; font-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")).unwrap());
    response
}

pub async fn asset(axum::extract::Path(name): axum::extract::Path<String>) -> Response {
    let (bytes, mime): (&'static [u8], &str) = match name.as_str() {
        "hirara-logo.png" => (include_bytes!("../ui/assets/hirara-logo.png"), "image/png"),
        "poppins-regular.ttf" => (
            include_bytes!("../ui/assets/poppins-regular.ttf"),
            "font/ttf",
        ),
        "poppins-medium.ttf" => (
            include_bytes!("../ui/assets/poppins-medium.ttf"),
            "font/ttf",
        ),
        "poppins-semibold.ttf" => (
            include_bytes!("../ui/assets/poppins-semibold.ttf"),
            "font/ttf",
        ),
        "poppins-license.txt" => (
            include_bytes!("../ui/assets/poppins-license.txt"),
            "text/plain; charset=utf-8",
        ),
        _ => return StatusCode::NOT_FOUND.into_response(),
    };
    let mut response = bytes.into_response();
    let headers = response.headers_mut();
    headers.insert("content-type", HeaderValue::from_str(mime).unwrap());
    headers.insert(
        "cache-control",
        HeaderValue::from_static("public, max-age=3600"),
    );
    headers.insert(
        "x-content-type-options",
        HeaderValue::from_static("nosniff"),
    );
    response
}
const SERVER: &str = r#"<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="6" rx="2"/><rect x="4" y="14" width="16" height="6" rx="2"/><path d="M8 7h.01M8 17h.01M15 7h2M15 17h2"/></svg>"#;
const PUBLIC: &str = r#"<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c5 4 5 12 0 16-5-4-5-12 0-16Z"/></svg>"#;
const LOGIN: &str = r#"<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M4 12h10m-4-4 4 4-4 4"/></svg>"#;
const TOKEN: &str = r#"<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v2"/></svg>"#;
const KEY: &str = r#"<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="8" cy="9" r="4"/><path d="m11 12 8 8m-3-3 3-3m-6 0 2-2"/></svg>"#;
const CHECK: &str = r#"<svg class="option-check" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>"#;
const CHEVRON: &str = r#"<svg class="select-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>"#;
const ARROW: &str =
    r#"<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg>"#;
pub fn result(title: &str, message: &str, link: Option<(&str, &str)>) -> String {
    let title = crate::api::escape(title);
    let message = crate::api::escape(message);
    let action = link
        .map(|(url, label)| {
            format!(
                r#"<a class="connect-button" href="{}">{}{ARROW}</a>"#,
                crate::api::escape(url),
                crate::api::escape(label)
            )
        })
        .unwrap_or_default();
    format!(
        r#"<div class="result-body"><div class="success-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg></div><p class="page-kicker">YOUR CONNECTION</p><h1>{title}</h1><p class="intro">{message}</p>{action}</div>"#
    )
}

pub fn approval(title: &str, endpoint: &str) -> Response {
    let title = crate::api::escape(title);
    let endpoint = crate::api::escape(endpoint);
    let options=[("none","Public access","No account required",PUBLIC),("oauth","Sign in with OAuth","Continue with your provider",LOGIN),("bearer","Access token","Use a personal access token",TOKEN),("api_key","API key","Use a provider API key",KEY)].into_iter().map(|(value,label,description,icon)|format!(r#"<button type="button" role="option" tabindex="-1" aria-selected="{}" data-value="{value}" class="select-option">{icon}<span class="select-copy"><span class="select-value">{label}</span><span class="select-description">{description}</span></span>{CHECK}</button>"#,value=="none")).collect::<String>();
    page(&format!(
        r#"
<p class="page-kicker">A NEW CONNECTION {ARROW}</p>
<h1>Make the connection.</h1>
<p class="intro">Give your AI agent a little more to work with.<br>Choose how you'd like to connect this server.</p>
<div class="server"><span class="server-icon">{SERVER}</span><div class="server-info"><span class="server-title">{title}</span><span class="server-address">{endpoint}</span></div><span class="protocol">MCP</span></div>
<form novalidate>
  <span class="field-label" id="auth-label">Authentication</span>
  <div class="auth-picker">
    <input type="hidden" name="mode" value="none">
    <button type="button" role="combobox" aria-haspopup="listbox" aria-expanded="false" aria-controls="auth-options" aria-labelledby="auth-label auth-value" class="select-trigger"><span class="select-icon">{PUBLIC}</span><span class="select-copy"><span class="select-value" id="auth-value">Public access</span><span class="select-description">No account required</span></span>{CHEVRON}</button>
    <div role="listbox" id="auth-options" aria-labelledby="auth-label" class="select-menu" hidden>{options}</div>
  </div>
  <div class="field" hidden><label class="field-label" for="provider-secret">Provider token or API key</label><input id="provider-secret" type="password" name="bearer" autocomplete="off" placeholder="Enter your provider credential" spellcheck="false"></div>
  <div class="field" hidden><label class="field-label" for="key-header">API key header</label><input id="key-header" name="header_name" placeholder="x-api-key" autocomplete="off" spellcheck="false"></div>
  <div class="field" hidden><label class="field-label" for="oauth-client">OAuth client ID <span class="field-hint">(optional)</span></label><input id="oauth-client" name="client_id" placeholder="Only if your provider requires one" autocomplete="off" spellcheck="false"></div>
  <div class="permissions"><p class="permissions-label">You're in control</p>
    <label class="permission-choice"><input class="check-input" type="checkbox" name="all_tools" value="yes"><span><span class="choice-title">Allow this server's tools</span><span class="choice-description">Includes tools the provider adds in the future.</span></span></label>
    <button type="button" class="disclosure" aria-expanded="false" aria-controls="tool-scope">{CHEVRON}Choose specific tools instead</button>
    <div id="tool-scope" hidden><div class="field"><label class="field-label" for="tool-names">Permitted tool names</label><input id="tool-names" name="tools" placeholder="read, search" spellcheck="false" autocomplete="off"><p class="field-hint">Use names from the provider's tool documentation.</p></div></div>
  </div>
  <button type="submit" class="connect-button"><span class="button-label">Connect</span>{ARROW}</button>
  <p class="connection-note">Hirara provides the connection, not an endorsement of this server. Connect to providers you trust.</p>
</form>"#
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tickets_are_one_time_and_not_agent_credentials() {
        let b = BrowserSession::new("agent-key".into());
        let ticket = b.ticket();
        assert!(b.exchange("wrong").is_none());
        let token = b.exchange(&ticket).unwrap();
        assert!(b.exchange(&ticket).is_none());
        assert_ne!(token, "agent-key");
        let mut h = HeaderMap::new();
        h.insert("authorization", format!("Bearer {token}").parse().unwrap());
        h.insert("origin", "http://127.0.0.1:1".parse().unwrap());
        assert!(b.authorized(&h, "http://127.0.0.1:1", true));
        assert!(!b.authorized(&h, "https://evil.test", true));
        h.insert("authorization", "Bearer agent-key".parse().unwrap());
        assert!(!b.authorized(&h, "http://127.0.0.1:1", true));
    }
    #[test]
    fn service_proofs_bind_origin_and_challenge() {
        assert_ne!(
            proof("key", "http://127.0.0.1:1", "a"),
            proof("key", "http://127.0.0.1:2", "a")
        );
        assert_ne!(proof("key", "origin", "a"), proof("wrong", "origin", "a"));
    }
}
