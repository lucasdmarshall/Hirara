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
        "<h1>Hirara connectors</h1><p id=status>Preparing your browser session…</p><p>Return to your AI agent to search for a connector. Open its connection link here to review permissions.</p><div id=connections></div>",
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
    let html = format!(
        "<!doctype html><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><title>Hirara connectors</title><style nonce=\"{nonce}\">body{{font:16px system-ui;background:#101419;color:#e6edf3;margin:0;padding:40px 20px}}main{{max-width:660px;margin:auto;background:#192129;padding:32px;border:1px solid #34414e;border-radius:16px}}label{{display:block;margin:16px 0}}input,select,button{{font:inherit;padding:10px;border-radius:6px;max-width:95%}}input:not([type=checkbox]){{display:block;width:95%}}button{{background:#7ee787;border:0;cursor:pointer;margin-top:16px}}a{{color:#7ee787}}p{{overflow-wrap:anywhere;line-height:1.6}}#status{{color:#b8c7d6}}</style><main><div id=content>{content}</div><p id=notice role=status></p></main><script nonce=\"{nonce}\">{SCRIPT}</script>"
    );
    let mut response = Html(html).into_response();
    let h = response.headers_mut();
    h.insert("cache-control", HeaderValue::from_static("no-store"));
    h.insert("referrer-policy", HeaderValue::from_static("no-referrer"));
    h.insert(
        "x-content-type-options",
        HeaderValue::from_static("nosniff"),
    );
    h.insert("content-security-policy",HeaderValue::from_str(&format!("default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")).unwrap());
    response
}
const SCRIPT: &str = r#"(async()=>{
const notice=document.getElementById('notice');const key='hirara-browser-session';
try{
 const ticket=location.hash.slice(1);history.replaceState(null,'',location.pathname);
 if(ticket){const r=await fetch('/local/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket})});if(!r.ok)throw Error('Browser link expired. Run hirara-connectors open again.');localStorage.setItem(key,(await r.json()).token);}
 const token=localStorage.getItem(key);
 if(!token){notice.textContent='Open your browser session first: run hirara-connectors open on this computer, then reload this page.';const b=document.querySelector('button');if(b)b.disabled=true;return;}
 const form=document.querySelector('form');
 if(form){const mode=form.elements.mode;function fields(){for(const [name,show] of [['bearer',['bearer','api_key'].includes(mode.value)],['header_name',mode.value==='api_key'],['client_id',mode.value==='oauth']]){const p=form.elements[name].closest('p');if(p)p.hidden=!show;}}mode.addEventListener('change',fields);fields();form.addEventListener('submit',async(event)=>{event.preventDefault();const button=form.querySelector('button');button.disabled=true;try{const r=await fetch(location.pathname,{method:'POST',headers:{Authorization:'Bearer '+localStorage.getItem(key),'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(form))});if(!r.ok){const error=await r.json();throw Error(error.error||'Connection could not be approved.');}document.getElementById('content').innerHTML=await r.text();notice.textContent='';}catch(e){notice.textContent=e.message;button.disabled=false;}});}
 else{const r=await fetch('/local/connections',{headers:{Authorization:'Bearer '+token}});if(!r.ok){localStorage.removeItem(key);throw Error('Browser session expired. Run hirara-connectors open again.');}document.getElementById('status').textContent='Ready. Your browser can approve connections without entering an operator token.';const data=await r.json();for(const c of data.connections){const p=document.createElement('p');p.textContent=c.title+' — saved';document.getElementById('connections').append(p);}}
}catch(e){notice.textContent=e.message;}
})();"#;
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
