use super::spec::{Package, Tool, env_name, input_schema, safe_header, safe_query};
use crate::net::{Error, Net, fail};
use serde_json::{Value, json};

pub fn allowed(name: &str) -> bool {
    std::env::var("HIRARA_ALLOWED_TOOLS")
        .ok()
        .is_none_or(|s| s.split(',').any(|v| v.trim() == name))
}
pub fn validate(package: &Package) -> Result<(), Error> {
    if package.format_version != 1
        || package.tools.is_empty()
        || package.tools.len() > 100
        || package.name.is_empty()
        || package.name.len() > 24
    {
        return Err(fail("invalid generated package"));
    }
    let mut names = std::collections::HashSet::new();
    for tool in &package.tools {
        if tool.method != "GET"
            || tool.name.len() > 64
            || !tool
                .name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_')
            || !names.insert(&tool.name)
            || !tool.path.starts_with('/')
            || tool.path.len() > 1024
            || tool.parameters.len() > 64
        {
            return Err(fail("invalid GET tool definition"));
        }
        if tool.input_schema != input_schema(&tool.parameters) {
            return Err(fail(
                "package input schema does not match its parameter definitions",
            ));
        }
        let mut params = std::collections::HashSet::new();
        for p in &tool.parameters {
            if !["path", "query", "header"].contains(&p.location.as_str())
                || p.name.is_empty()
                || p.name.len() > 128
                || !params.insert((
                    p.location.clone(),
                    if p.location == "header" {
                        p.name.to_ascii_lowercase()
                    } else {
                        p.name.clone()
                    },
                ))
                || !["string", "integer", "number", "boolean"]
                    .contains(&p.schema["type"].as_str().unwrap_or(""))
                || (p.location == "query" && !safe_query(&p.name))
                || (p.location == "path" && !p.required)
                || p.schema.as_object().is_none_or(|schema| {
                    schema.keys().any(|k| {
                        ![
                            "type",
                            "enum",
                            "minimum",
                            "maximum",
                            "exclusiveMinimum",
                            "exclusiveMaximum",
                            "minLength",
                            "maxLength",
                            "pattern",
                            "description",
                        ]
                        .contains(&k.as_str())
                    })
                })
                || contains_ref(&p.schema)
                || serde_json::to_vec(&p.schema)?.len() > 8192
            {
                return Err(fail("invalid package parameter"));
            }
            if p.location == "header" && !safe_header(&p.name) {
                return Err(fail("reserved package header denied"));
            }
            jsonschema::validator_for(&p.schema)
                .map_err(|_| fail("invalid package parameter schema"))?;
        }
        if let Some(auth) = &tool.auth
            && (!env_name(&auth.credential_env)
                || !match auth.scheme.as_str() {
                    "bearer" => auth.header.eq_ignore_ascii_case("authorization"),
                    "api_key" => safe_header(&auth.header),
                    _ => false,
                }
                || tool
                    .parameters
                    .iter()
                    .any(|p| p.location == "header" && p.name.eq_ignore_ascii_case(&auth.header)))
        {
            return Err(fail("invalid package credential binding"));
        }
    }
    Ok(())
}
fn contains_ref(v: &Value) -> bool {
    match v {
        Value::Object(m) => m
            .iter()
            .any(|(k, v)| k == "$ref" || k == "$dynamicRef" || contains_ref(v)),
        Value::Array(a) => a.iter().any(contains_ref),
        _ => false,
    }
}
pub struct Plan {
    pub url: url::Url,
    pub headers: Vec<(String, String)>,
}
pub fn plan(package: &Package, tool: &Tool, args: &Value) -> Result<Plan, Error> {
    if serde_json::to_vec(args)?.len() > 65536 {
        return Err(fail("tool arguments exceed 64 KiB"));
    }
    let validator = jsonschema::validator_for(&tool.input_schema)
        .map_err(|_| fail("invalid tool input schema"))?;
    if !validator.is_valid(args) {
        return Err(fail("arguments do not match the generated input schema"));
    }
    let mut url =
        url::Url::parse(&package.base_url).map_err(|_| fail("invalid package server URL"))?;
    if url.query().is_some()
        || url.fragment().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err(fail("invalid package server URL"));
    }
    {
        let mut segments = url
            .path_segments_mut()
            .map_err(|_| fail("invalid package base path"))?;
        segments.pop_if_empty();
        for segment in tool.path.trim_start_matches('/').split('/') {
            let value = if segment.starts_with('{') && segment.ends_with('}') {
                scalar(&args["path"][&segment[1..segment.len() - 1]])?
            } else {
                if segment.contains(['{', '}']) {
                    return Err(fail("unsupported path template"));
                }
                segment.to_string()
            };
            if value.contains(['/', '\\', '%', '?', '#'])
                || matches!(value.as_str(), "." | "..")
                || value.len() > 2048
            {
                return Err(fail("unsafe path parameter or segment"));
            }
            segments.push(&value);
        }
    }
    let mut headers = Vec::new();
    for p in &tool.parameters {
        let group = match p.location.as_str() {
            "path" => continue,
            "query" => "query",
            _ => "headers",
        };
        let Some(value) = args.get(group).and_then(|v| v.get(&p.name)) else {
            continue;
        };
        let value = scalar(value)?;
        if value.len() > 8192 {
            return Err(fail("parameter value exceeds limit"));
        }
        if p.location == "query" {
            url.query_pairs_mut().append_pair(&p.name, &value);
        } else {
            http::HeaderValue::from_str(&value).map_err(|_| fail("invalid header parameter"))?;
            headers.push((p.name.clone(), value));
        }
    }
    Ok(Plan { url, headers })
}
fn scalar(value: &Value) -> Result<String, Error> {
    match value {
        Value::String(s) => Ok(s.clone()),
        Value::Number(_) | Value::Bool(_) => Ok(value.to_string()),
        _ => Err(fail("expected a scalar parameter")),
    }
}
pub fn credential(tool: &Tool) -> Result<Option<String>, Error> {
    tool.auth
        .as_ref()
        .map(|auth| {
            std::env::var(&auth.credential_env)
                .map_err(|_| fail("credential environment binding is unavailable"))
        })
        .transpose()
}
pub async fn execute(
    package: &Package,
    name: &str,
    args: &Value,
    net: &Net,
    secret: Option<&str>,
) -> Result<Value, Error> {
    validate(package)?;
    if !allowed(name) {
        return Err(fail("generated tool disabled by HIRARA_ALLOWED_TOOLS"));
    }
    let tool = package
        .tools
        .iter()
        .find(|t| t.name == name)
        .ok_or_else(|| fail("generated tool not found"))?;
    let plan = plan(package, tool, args)?;
    net.guard(plan.url.as_str()).await?;
    let mut request = net
        .client
        .get(plan.url)
        .header("accept", "application/json");
    for (key, value) in plan.headers {
        request = request.header(key, value);
    }
    if let Some(auth) = &tool.auth {
        let secret = secret
            .filter(|v| !v.is_empty() && v.len() <= 16384 && !v.contains(['\r', '\n']))
            .ok_or_else(|| fail("a valid provider credential is required"))?;
        let value = if auth.scheme == "bearer" {
            format!("Bearer {secret}")
        } else {
            secret.to_string()
        };
        let mut header =
            http::HeaderValue::from_str(&value).map_err(|_| fail("invalid provider credential"))?;
        header.set_sensitive(true);
        request = request.header(&auth.header, header);
    }
    let response = request.send().await.map_err(|_| {
        fail("generated API request failed; credentials and request URLs are redacted")
    })?;
    let status = response.status().as_u16();
    if !(200..300).contains(&status) {
        return Ok(
            json!({"tool":name,"error":"upstream API rejected the request","upstream_status":status}),
        );
    }
    if status == 204 {
        return Ok(json!({"tool":name,"upstream_status":status,"data":null}));
    }
    let content_type = response
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .split(';')
        .next()
        .unwrap_or("")
        .to_ascii_lowercase();
    if content_type != "application/json" && !content_type.ends_with("+json") {
        return Err(fail("prototype adapters require a JSON response"));
    }
    let body = Net::bytes(response)
        .await
        .map_err(|_| fail("generated API response failed or exceeded 4 MiB"))?;
    let mut data: Value =
        serde_json::from_slice(&body).map_err(|_| fail("upstream returned invalid JSON"))?;
    if tool.auth.is_some()
        && let Some(secret) = secret
    {
        redact(&mut data, secret);
    }
    Ok(json!({"tool":name,"upstream_status":status,"data":data}))
}
fn redact(value: &mut Value, secret: &str) {
    match value {
        Value::String(s) => *s = s.replace(secret, "[REDACTED]"),
        Value::Array(values) => {
            for v in values {
                redact(v, secret);
            }
        }
        Value::Object(map) => {
            let old = std::mem::take(map);
            for (key, mut v) in old {
                redact(&mut v, secret);
                map.insert(key.replace(secret, "[REDACTED]"), v);
            }
        }
        _ => {
            let rendered = value.to_string();
            if rendered == secret {
                *value = json!("[REDACTED]");
            }
        }
    }
}
