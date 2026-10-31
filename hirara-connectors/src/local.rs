//! Single-command local setup. No credentials are printed or returned to agents.
use crate::{
    api::State,
    net::{Error, Net, fail},
    store::random_id,
};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::{Path, PathBuf},
    process::Command,
};

pub fn data_dir() -> Result<PathBuf, Error> {
    if let Some(path) = std::env::var_os("HIRARA_CONNECTOR_LOCAL_DIR") {
        return Ok(PathBuf::from(path));
    }
    #[cfg(target_os = "windows")]
    {
        return Ok(PathBuf::from(
            std::env::var_os("LOCALAPPDATA")
                .ok_or_else(|| fail("local application data directory unavailable"))?,
        )
        .join("Hirara/connectors"));
    }
    #[cfg(target_os = "macos")]
    {
        return Ok(PathBuf::from(
            std::env::var_os("HOME").ok_or_else(|| fail("home directory unavailable"))?,
        )
        .join("Library/Application Support/Hirara/connectors"));
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        let root = std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|p| PathBuf::from(p).join(".local/share")))
            .ok_or_else(|| fail("local data directory unavailable"))?;
        Ok(root.join("hirara/connectors"))
    }
}
fn private_dir(dir: &Path) -> Result<(), Error> {
    if std::fs::symlink_metadata(dir).is_ok_and(|m| m.file_type().is_symlink()) {
        return Err(fail("local data directory must not be a symlink"));
    }
    std::fs::create_dir_all(dir)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(dir, std::fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}
fn write_private(path: &Path, bytes: &[u8]) -> Result<(), Error> {
    let mut file = tempfile::NamedTempFile::new_in(path.parent().unwrap())?;
    file.write_all(bytes)?;
    file.as_file().sync_all()?;
    file.persist(path)
        .map_err(|_| fail("cannot save local connector state"))?;
    Ok(())
}
fn discovery(dir: &Path) -> Result<Value, Error> {
    let path = dir.join("local.json");
    let metadata = std::fs::symlink_metadata(&path)?;
    if !metadata.is_file() || metadata.len() > 16384 {
        return Err(fail("invalid local discovery file"));
    }
    let data: Value = serde_json::from_slice(&std::fs::read(path)?)?;
    let url = data["url"]
        .as_str()
        .ok_or_else(|| fail("local connector URL missing"))?;
    let parsed = url::Url::parse(url)?;
    if parsed.scheme() != "http"
        || parsed.host_str() != Some("127.0.0.1")
        || parsed.port().is_none()
        || parsed.path() != "/"
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
    {
        return Err(fail("invalid local connector address"));
    }
    if !data["token"]
        .as_str()
        .is_some_and(|t| t.len() == 48 && t.bytes().all(|b| b.is_ascii_hexdigit()))
    {
        return Err(fail("invalid local connector credential"));
    }
    Ok(data)
}
async fn verify(client: &reqwest::Client, data: &Value) -> Result<(), Error> {
    let challenge = random_id();
    let url = data["url"].as_str().unwrap();
    let response = client
        .post(format!("{url}/local/proof"))
        .json(&json!({"challenge":challenge}))
        .send()
        .await?
        .error_for_status()?;
    let response: Value = serde_json::from_slice(&Net::bytes(response).await?)?;
    if !response["proof"].as_str().is_some_and(|p| {
        crate::api::equal(
            p,
            &crate::portal::proof(data["token"].as_str().unwrap(), url, &challenge),
        )
    }) {
        return Err(fail("local connector identity could not be verified"));
    }
    Ok(())
}
async fn open_session(dir: &Path, data: &Value, no_browser: bool) -> Result<(), Error> {
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(std::time::Duration::from_secs(3))
        .build()?;
    verify(&client, data).await?;
    let admin = std::fs::read_to_string(dir.join("secrets/admin-token"))?;
    let response = client
        .post(format!("{}/local/open", data["url"].as_str().unwrap()))
        .bearer_auth(admin)
        .send()
        .await?
        .error_for_status()?;
    let response: Value = serde_json::from_slice(&Net::bytes(response).await?)?;
    let url = response["url"]
        .as_str()
        .ok_or_else(|| fail("browser authorization link unavailable"))?;
    launch(dir, url, no_browser)
}
fn launch(dir: &Path, url: &str, no_browser: bool) -> Result<(), Error> {
    // The ticket stays in a private file. Browser launcher process arguments contain
    // only this filename, never the credential/ticket. URL fragments never hit HTTP logs.
    let html = format!(
        "<!doctype html><meta charset=utf-8><meta name=referrer content=no-referrer><meta http-equiv=refresh content=\"0;url={url}\"><title>Opening Hirara</title><p>Opening Hirara's local browser session.</p>"
    );
    let file = dir.join("browser-launch.html");
    write_private(&file, html.as_bytes())?;
    if no_browser {
        println!(
            "Local connector ready. Run hirara-connectors open on this computer to authorize your browser."
        );
        return Ok(());
    }
    #[cfg(target_os = "macos")]
    let mut command = Command::new("/usr/bin/open");
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut c = Command::new("rundll32");
        c.arg("url.dll,FileProtocolHandler");
        c
    };
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    let mut command = Command::new("xdg-open");
    match command
        .arg(&file)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
    {
        Ok(mut child) => {
            let path = file.clone();
            tokio::task::spawn_blocking(move || {
                if !child.wait().is_ok_and(|status| status.success()) {
                    eprintln!(
                        "Browser launch failed. Open {} privately in your browser, or run hirara-connectors open again.",
                        path.display()
                    );
                }
            });
        }
        Err(_) => eprintln!(
            "Could not launch a browser. Open {} privately in your browser; the link expires in two minutes.",
            file.display()
        ),
    }
    Ok(())
}
pub async fn run(args: &[String]) -> Result<(), Error> {
    let mut dir = data_dir()?;
    let mut no_browser = false;
    let mut trust_proxy = std::env::var("HCONNECT_TRUST_PROXY").as_deref() == Ok("true");
    let mut index = 1;
    while index < args.len() {
        match args[index].as_str() {
            "--data-dir" => {
                index += 1;
                dir = PathBuf::from(
                    args.get(index)
                        .ok_or_else(|| fail("--data-dir needs a path"))?,
                );
            }
            "--no-browser" => no_browser = true,
            "--trust-proxy" => trust_proxy = true,
            _ => return Err(fail("unknown local connector option")),
        }
        index += 1;
    }
    if !dir.is_absolute() {
        dir = std::env::current_dir()?.join(dir);
    }
    private_dir(&dir)?;
    if args[0] == "open" {
        return open_session(&dir, &discovery(&dir)?, no_browser).await;
    }
    if let Ok(data) = discovery(&dir) {
        let client = reqwest::Client::builder()
            .no_proxy()
            .timeout(std::time::Duration::from_secs(1))
            .build()?;
        if verify(&client, &data).await.is_ok() {
            return open_session(&dir, &data, no_browser).await;
        }
    }
    let proxy_present = [
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "https_proxy",
        "http_proxy",
        "all_proxy",
    ]
    .iter()
    .any(|k| std::env::var(k).is_ok_and(|v| !v.is_empty()));
    if proxy_present && !trust_proxy {
        return Err(fail(
            "A proxy is configured. If it enforces public-destination policy, use local --trust-proxy. No network policy is bypassed automatically.",
        ));
    }
    if !dir.join("secrets").exists() {
        crate::initialize(&dir.join("secrets"))?;
    }
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let url = format!("http://{}", listener.local_addr()?);
    let token = random_id();
    let state = State::local(
        &dir,
        url.clone(),
        Net::with_proxy_trust(trust_proxy)?,
        token.clone(),
    )?;
    write_private(
        &dir.join("local.json"),
        &serde_json::to_vec(&json!({"version":1,"url":url,"token":token}))?,
    )?;
    let ticket = state.browser.as_ref().unwrap().ticket();
    // The server must be listening before the browser follows the bootstrap link.
    let app = crate::api::router(state);
    let server = tokio::spawn(async move {
        axum::serve(listener, app)
            .with_graceful_shutdown(async {
                let _ = tokio::signal::ctrl_c().await;
            })
            .await
    });
    launch(&dir, &format!("{url}/local#{ticket}"), no_browser)?;
    eprintln!("Hirara connector running at {url}. The local hub discovers it automatically.");
    let result = server.await?;
    let _ = std::fs::remove_file(dir.join("local.json"));
    result?;
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn discovery_never_accepts_non_loopback_destinations() {
        let dir = tempfile::tempdir().unwrap();
        let token = "a".repeat(48);
        for url in [
            "https://evil.test",
            "http://127.0.0.1:1/path",
            "http://user@127.0.0.1:1",
            "http://localhost:1",
        ] {
            write_private(
                &dir.path().join("local.json"),
                json!({"url":url,"token":token}).to_string().as_bytes(),
            )
            .unwrap();
            assert!(discovery(dir.path()).is_err());
        }
    }
}
