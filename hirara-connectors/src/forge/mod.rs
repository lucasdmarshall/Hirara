mod execute;
mod mcp;
mod spec;
#[cfg(test)]
mod tests;

use crate::net::{Error, Net, fail};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use spec::Package;
use std::{
    collections::HashMap,
    io::{Read, Write},
    path::Path,
};

pub fn digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn read(path: &str) -> Result<Vec<u8>, Error> {
    let mut file = std::fs::File::open(path)?;
    if !file.metadata()?.is_file() {
        return Err(fail("a regular file is required"));
    }
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take(1024 * 1024 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 1024 * 1024 {
        return Err(fail("forge input file exceeds 1 MiB"));
    }
    Ok(bytes)
}
fn load(path: &str, pin: Option<&str>) -> Result<(Package, String), Error> {
    let bytes = read(path)?;
    let sha = digest(&bytes);
    if let Some(pin) = pin
        && pin != sha
    {
        return Err(fail(
            "package digest changed; review it again before execution",
        ));
    }
    let package: Package =
        serde_json::from_slice(&bytes).map_err(|_| fail("invalid Hirara tool package"))?;
    execute::validate(&package)?;
    crate::net::validate_url(&package.base_url)?;
    Ok((package, sha))
}
fn arguments(args: &[String]) -> Result<HashMap<&str, &str>, Error> {
    if !args.len().is_multiple_of(2) {
        return Err(fail("forge options require --name VALUE pairs"));
    }
    let mut map = HashMap::new();
    for pair in args.chunks(2) {
        if !pair[0].starts_with("--") || map.insert(pair[0].as_str(), pair[1].as_str()).is_some() {
            return Err(fail("invalid or duplicate forge option"));
        }
    }
    Ok(map)
}
fn option<'a>(map: &HashMap<&str, &'a str>, key: &str) -> Result<&'a str, Error> {
    map.get(key)
        .copied()
        .ok_or_else(|| fail(&format!("{key} is required")))
}
fn emit(value: Value) {
    println!("{}", serde_json::to_string_pretty(&value).unwrap());
}
pub async fn cli(args: &[String]) -> Result<(), Error> {
    let command = args.first().map(String::as_str).unwrap_or("help");
    if command == "help" {
        println!(
            "hirara-connectors forge build --spec api.json --name inventory --out inventory.hirara.json [--credential-env INVENTORY_TOKEN] [--base-url https://api.example.com/v1] [--operation getStock]\nhirara-connectors forge inspect --package inventory.hirara.json\nhirara-connectors forge test --package inventory.hirara.json --fixtures cases.json\nhirara-connectors forge call --package inventory.hirara.json --sha256 REVIEWED_DIGEST --tool inventory__getstock --arguments args.json\nhirara-connectors forge mcp --package inventory.hirara.json --sha256 REVIEWED_DIGEST"
        );
        return Ok(());
    }
    let options = arguments(&args[1..])?;
    let allowed = match command {
        "build" => vec![
            "--spec",
            "--name",
            "--out",
            "--credential-env",
            "--base-url",
            "--operation",
        ],
        "inspect" => vec!["--package"],
        "test" => vec!["--package", "--fixtures"],
        "call" => vec!["--package", "--sha256", "--tool", "--arguments"],
        "mcp" => vec!["--package", "--sha256"],
        _ => return Err(fail("unknown forge command; run forge help")),
    };
    if options.keys().any(|k| !allowed.contains(k)) {
        return Err(fail("unknown forge option"));
    }
    if command == "build" {
        let source = read(option(&options, "--spec")?)?;
        let package = spec::compile(
            &source,
            option(&options, "--name")?,
            options.get("--base-url").copied(),
            options.get("--credential-env").copied(),
            options.get("--operation").copied(),
        )?;
        execute::validate(&package)?;
        let bytes = serde_json::to_vec_pretty(&package)?;
        if bytes.len() > 1024 * 1024 {
            return Err(fail("generated package exceeds 1 MiB"));
        }
        let target = Path::new(option(&options, "--out")?);
        let parent = target
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        let mut file = tempfile::NamedTempFile::new_in(parent)?;
        file.write_all(&bytes)?;
        file.as_file().sync_all()?;
        file.persist_noclobber(target)
            .map_err(|_| fail("output exists or cannot be written; choose a new --out path"))?;
        emit(
            json!({"package":target,"sha256":digest(&bytes),"tools":package.tools.iter().map(|t|&t.name).collect::<Vec<_>>(),"skipped":package.skipped,"review":"Inspect the package and run fixture tests before pinning this digest for live execution. GET does not prove an API is side-effect free."}),
        );
        return Ok(());
    }
    let pin = if matches!(command, "call" | "mcp") {
        Some(option(&options, "--sha256")?)
    } else {
        None
    };
    let (package, sha) = load(option(&options, "--package")?, pin)?;
    match command {
        "inspect" => emit(json!({"sha256":sha,"package":package})),
        "test" => {
            let cases: Vec<Value> = serde_json::from_slice(&read(option(&options, "--fixtures")?)?)
                .map_err(|_| fail("fixtures must be a JSON array"))?;
            if cases.is_empty() || cases.len() > 100 {
                return Err(fail("provide 1–100 fixture cases"));
            }
            let mut passed = 0;
            for case in cases {
                let tool = package
                    .tools
                    .iter()
                    .find(|t| Some(t.name.as_str()) == case["tool"].as_str())
                    .ok_or_else(|| fail("fixture references an unknown tool"))?;
                let result = execute::plan(&package, tool, &case["arguments"]);
                if case["reject"] == true {
                    if result.is_ok() {
                        return Err(fail("fixture expected argument rejection"));
                    }
                } else {
                    let plan = result?;
                    crate::net::validate_url(plan.url.as_str())?;
                    if case["expected_url"].as_str() != Some(plan.url.as_str()) {
                        return Err(fail("fixture URL did not match the generated request plan"));
                    }
                }
                passed += 1;
            }
            emit(
                json!({"sha256":sha,"passed":passed,"network_requests":0,"credentials_read":false,"scope":"offline input validation and request planning only; not live API compatibility"}),
            );
        }
        "call" => {
            let name = option(&options, "--tool")?;
            if !execute::allowed(name) {
                return Err(fail("generated tool disabled by HIRARA_ALLOWED_TOOLS"));
            }
            let tool = package
                .tools
                .iter()
                .find(|t| t.name == name)
                .ok_or_else(|| fail("generated tool not found"))?;
            let args = serde_json::from_slice(&read(option(&options, "--arguments")?)?)
                .map_err(|_| fail("arguments must be JSON"))?;
            execute::plan(&package, tool, &args)?;
            let secret = execute::credential(tool)?;
            let net = network()?;
            let result = execute::execute(&package, name, &args, &net, secret.as_deref()).await?;
            if result.get("error").is_some() {
                return Err(fail("upstream API rejected the request"));
            }
            emit(result);
        }
        "mcp" => mcp::serve(package, network()?).await?,
        _ => unreachable!(),
    }
    Ok(())
}
fn network() -> Result<Net, Error> {
    let proxy = [
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "https_proxy",
        "http_proxy",
        "all_proxy",
    ]
    .iter()
    .any(|k| std::env::var(k).is_ok_and(|v| !v.is_empty()));
    if proxy && std::env::var("HCONNECT_TRUST_PROXY").as_deref() != Ok("true") {
        return Err(fail(
            "configured proxy must enforce destination policy; set HCONNECT_TRUST_PROXY=true only for such a proxy",
        ));
    }
    Net::new()
}
