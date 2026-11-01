//! Deterministic, deliberately narrow OpenAPI importer. No model or code execution.
use crate::net::{Error, fail, validate_url};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashSet};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Package {
    pub format_version: u32,
    pub name: String,
    pub source_sha256: String,
    pub base_url: String,
    pub tools: Vec<Tool>,
    pub skipped: Vec<Value>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Tool {
    pub name: String,
    pub operation_id: String,
    pub description: String,
    pub method: String,
    pub path: String,
    pub parameters: Vec<Parameter>,
    pub auth: Option<Auth>,
    pub input_schema: Value,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Parameter {
    pub name: String,
    pub location: String,
    pub required: bool,
    pub schema: Value,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Auth {
    pub scheme: String,
    pub header: String,
    pub credential_env: String,
}

pub fn compile(
    source: &[u8],
    name: &str,
    base: Option<&str>,
    credential: Option<&str>,
    selected: Option<&str>,
) -> Result<Package, Error> {
    if source.len() > 1024 * 1024 {
        return Err(fail("OpenAPI document exceeds 1 MiB"));
    }
    if name.is_empty()
        || name.len() > 24
        || !name
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_')
    {
        return Err(fail(
            "package name must contain 1–24 lowercase letters, digits or underscores",
        ));
    }
    if credential.is_some_and(|s| !env_name(s)) {
        return Err(fail("invalid credential environment variable name"));
    }
    let spec: Value =
        serde_json::from_slice(source).map_err(|_| fail("expected an OpenAPI JSON document"))?;
    let version = spec["openapi"].as_str().unwrap_or("");
    if !(version.starts_with("3.0.") || version.starts_with("3.1.")) {
        return Err(fail("only OpenAPI 3.0/3.1 JSON is supported"));
    }
    let base = base
        .or_else(|| spec["servers"].as_array()?.first()?["url"].as_str())
        .ok_or_else(|| fail("a server URL or --base-url is required"))?;
    let url = validate_url(base)?;
    if url.query().is_some() || base.contains(['{', '}']) {
        return Err(fail("server URL variables and queries are not supported"));
    }
    let paths = spec["paths"]
        .as_object()
        .ok_or_else(|| fail("OpenAPI paths must be an object"))?;
    if paths.len() > 500 {
        return Err(fail("OpenAPI path limit exceeded (500)"));
    }
    let mut tools = Vec::new();
    let mut skipped = Vec::new();
    let mut names = HashSet::new();
    for (path, item) in paths {
        if item.get("$ref").is_some() {
            skipped.push(json!({"path":path,"reason":"referenced path items are unsupported"}));
            continue;
        }
        for (method, operation) in item.as_object().into_iter().flatten() {
            if ![
                "get", "post", "put", "patch", "delete", "head", "options", "trace",
            ]
            .contains(&method.as_str())
            {
                continue;
            }
            let operation_id = operation["operationId"].as_str().unwrap_or("");
            if selected.is_some_and(|s| s != operation_id) {
                continue;
            }
            let result = if method != "get" {
                Err(fail("only GET operations are generated"))
            } else {
                compile_tool(&spec, item, operation, name, path, credential)
            };
            match result {
                Ok(tool)=>{if !names.insert(tool.name.clone()){return Err(fail("generated tool name collision; choose distinct operation IDs"));}tools.push(tool);},
                Err(e)=>skipped.push(json!({"method":method,"path":path,"operation_id":operation_id,"reason":e.to_string()}))
            }
        }
    }
    if tools.len() > 100 {
        return Err(fail("tool limit exceeded (100)"));
    }
    if tools.is_empty() {
        return Err(fail(&format!(
            "no supported GET tools generated: {}",
            serde_json::to_string(&skipped)?
        )));
    }
    Ok(Package {
        format_version: 1,
        name: name.into(),
        source_sha256: super::digest(source),
        base_url: base.trim_end_matches('/').into(),
        tools,
        skipped,
    })
}
fn compile_tool(
    spec: &Value,
    item: &Value,
    op: &Value,
    package: &str,
    path: &str,
    credential: Option<&str>,
) -> Result<Tool, Error> {
    if !path.starts_with('/')
        || path.len() > 1024
        || op.get("requestBody").is_some()
        || op.get("servers").is_some()
        || item.get("servers").is_some()
    {
        return Err(fail(
            "request bodies and per-operation/path server overrides are unsupported",
        ));
    }
    let operation_id = op["operationId"]
        .as_str()
        .map(String::from)
        .unwrap_or_else(|| format!("get_{}", &super::digest(path.as_bytes())[..12]));
    let clean: String = operation_id
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_lowercase()
            } else {
                '_'
            }
        })
        .collect();
    if clean.is_empty() || clean.len() > 38 {
        return Err(fail(
            "operation ID must produce a tool suffix of at most 38 characters",
        ));
    }
    let auth = authentication(spec, op, credential)?;
    let mut parameters: BTreeMap<(String, String), Parameter> = BTreeMap::new();
    for list in [item.get("parameters"), op.get("parameters")]
        .into_iter()
        .flatten()
    {
        let list = list
            .as_array()
            .ok_or_else(|| fail("parameters must be an array"))?;
        if list.len() > 64 {
            return Err(fail("parameter limit exceeded (64)"));
        }
        for p in list {
            let p = deref(spec, p, 0)?;
            let name = p["name"]
                .as_str()
                .ok_or_else(|| fail("parameter name missing"))?;
            let location = p["in"].as_str().unwrap_or("");
            if name.is_empty()
                || name.len() > 128
                || !["path", "query", "header"].contains(&location)
                || p.get("content").is_some()
                || p.get("style").is_some_and(|s| {
                    s != if location == "query" {
                        "form"
                    } else {
                        "simple"
                    }
                })
            {
                return Err(fail(
                    "only scalar path/query/header parameters with default serialization are supported",
                ));
            }
            if location == "query" && !safe_query(name) {
                return Err(fail("credential-like query parameter denied"));
            }
            if p.get("required").is_some_and(|v| !v.is_boolean()) {
                return Err(fail("parameter required must be a boolean"));
            }
            if location == "header" && !safe_header(name) {
                return Err(fail("reserved request header parameter denied"));
            }
            if auth
                .as_ref()
                .is_some_and(|a| location == "header" && name.eq_ignore_ascii_case(&a.header))
            {
                return Err(fail("a parameter cannot override the credential header"));
            }
            let schema = deref(spec, &p["schema"], 0)?;
            if !["string", "integer", "number", "boolean"]
                .contains(&schema["type"].as_str().unwrap_or(""))
                || [
                    "allOf", "anyOf", "oneOf", "not", "$ref", "items", "nullable",
                ]
                .iter()
                .any(|k| schema.get(k).is_some())
            {
                return Err(fail("only non-null scalar parameter schemas are supported"));
            }
            let allowed = [
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
            ];
            if schema.as_object().is_none_or(|m| {
                m.keys().any(|k| {
                    !allowed.contains(&k.as_str())
                        && !["format", "default", "example", "deprecated"].contains(&k.as_str())
                })
            }) {
                return Err(fail("unsupported parameter schema keyword"));
            }
            if schema.get("format").is_some() {
                return Err(fail("formatted parameters require an explicit adapter"));
            }
            let schema: Value = Value::Object(
                schema
                    .as_object()
                    .unwrap()
                    .iter()
                    .filter(|(k, _)| allowed.contains(&k.as_str()))
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect(),
            );
            if serde_json::to_vec(&schema)?.len() > 8192 {
                return Err(fail("parameter schema too large"));
            }
            jsonschema::validator_for(&schema).map_err(|_| fail("invalid parameter schema"))?;
            let required = location == "path" || p["required"] == true;
            parameters.insert(
                (location.into(), name.into()),
                Parameter {
                    name: name.into(),
                    location: location.into(),
                    required,
                    schema,
                },
            );
        }
    }
    if parameters.len() > 64 {
        return Err(fail("parameter limit exceeded (64)"));
    }
    let parameters: Vec<_> = parameters.into_values().collect();
    let mut path_names = HashSet::new();
    for part in path.trim_start_matches('/').split('/') {
        if part.starts_with('{') && part.ends_with('}') {
            let key = &part[1..part.len() - 1];
            if !parameters
                .iter()
                .any(|p| p.location == "path" && p.name == key)
            {
                return Err(fail("path placeholder has no parameter"));
            }
            path_names.insert(key);
        } else if part.contains(['{', '}', '%', '\\', '?', '#']) || matches!(part, "." | "..") {
            return Err(fail(
                "only complete-segment path placeholders and literal paths are supported",
            ));
        }
    }
    if parameters
        .iter()
        .any(|p| p.location == "path" && !path_names.contains(p.name.as_str()))
    {
        return Err(fail("path parameter has no placeholder"));
    }
    let input_schema = input_schema(&parameters);
    let description = op["summary"]
        .as_str()
        .or_else(|| op["description"].as_str())
        .unwrap_or("Generated OpenAPI GET adapter")
        .chars()
        .take(1000)
        .collect();
    Ok(Tool {
        name: format!("{package}__{clean}"),
        operation_id,
        description,
        method: "GET".into(),
        path: path.into(),
        parameters,
        auth,
        input_schema,
    })
}
fn authentication(
    spec: &Value,
    op: &Value,
    credential: Option<&str>,
) -> Result<Option<Auth>, Error> {
    let security = op.get("security").or_else(|| spec.get("security"));
    let Some(security) = security else {
        return Ok(None);
    };
    let security = security
        .as_array()
        .ok_or_else(|| fail("security must be an array"))?;
    if security.is_empty() {
        return Ok(None);
    }
    if security.len() != 1 {
        return Err(fail(
            "alternative authentication requirements are unsupported",
        ));
    }
    let schemes = security[0]
        .as_object()
        .ok_or_else(|| fail("invalid security requirement"))?;
    if schemes.is_empty() {
        return Ok(None);
    }
    if schemes.len() != 1 {
        return Err(fail("combined authentication schemes are unsupported"));
    }
    let (name, scopes) = schemes.iter().next().unwrap();
    if scopes.as_array().is_none_or(|s| !s.is_empty()) {
        return Err(fail("OAuth scopes are unsupported by this prototype"));
    }
    let scheme = deref(spec, &spec["components"]["securitySchemes"][name], 0)?;
    let (kind, header) = if scheme["type"] == "http"
        && scheme["scheme"]
            .as_str()
            .is_some_and(|s| s.eq_ignore_ascii_case("bearer"))
    {
        ("bearer", "authorization")
    } else if scheme["type"] == "apiKey" && scheme["in"] == "header" {
        let h = scheme["name"]
            .as_str()
            .ok_or_else(|| fail("API key header missing"))?;
        if !safe_header(h) {
            return Err(fail("reserved API key header denied"));
        }
        ("api_key", h)
    } else {
        return Err(fail(
            "only HTTP bearer and header API key security schemes are supported",
        ));
    };
    Ok(Some(Auth {
        scheme: kind.into(),
        header: header.into(),
        credential_env: credential
            .ok_or_else(|| fail("authenticated operation requires --credential-env NAME"))?
            .into(),
    }))
}
fn deref<'a>(spec: &'a Value, value: &'a Value, depth: u8) -> Result<&'a Value, Error> {
    if depth > 16 {
        return Err(fail("cyclic or excessive local references"));
    }
    if let Some(reference) = value.get("$ref") {
        if value.as_object().is_none_or(|m| m.len() != 1) {
            return Err(fail("reference siblings are unsupported"));
        }
        let r = reference
            .as_str()
            .filter(|s| s.starts_with("#/components/"))
            .ok_or_else(|| fail("only local component references are supported"))?;
        return deref(
            spec,
            spec.pointer(&r[1..])
                .ok_or_else(|| fail("local reference not found"))?,
            depth + 1,
        );
    }
    Ok(value)
}
pub fn input_schema(parameters: &[Parameter]) -> Value {
    let mut properties = serde_json::Map::new();
    let mut required = Vec::new();
    for (location, group) in [("path", "path"), ("query", "query"), ("header", "headers")] {
        let mut fields = serde_json::Map::new();
        let mut needed = Vec::new();
        for p in parameters.iter().filter(|p| p.location == location) {
            fields.insert(p.name.clone(), p.schema.clone());
            if p.required {
                needed.push(p.name.clone());
            }
        }
        if !fields.is_empty() {
            if !needed.is_empty() {
                required.push(group);
            }
            properties.insert(group.into(),json!({"type":"object","properties":fields,"required":needed,"additionalProperties":false}));
        }
    }
    json!({"type":"object","properties":properties,"required":required,"additionalProperties":false})
}
pub fn env_name(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .enumerate()
            .all(|(i, c)| c == b'_' || c.is_ascii_alphabetic() || (i > 0 && c.is_ascii_digit()))
}
pub fn safe_query(value: &str) -> bool {
    ![
        "token",
        "access_token",
        "api_key",
        "apikey",
        "key",
        "authorization",
    ]
    .contains(&value.to_ascii_lowercase().as_str())
}
pub fn safe_header(value: &str) -> bool {
    let n = value.to_ascii_lowercase();
    http::HeaderName::from_bytes(n.as_bytes()).is_ok()
        && !n.starts_with("proxy-")
        && !n.starts_with("mcp-")
        && !n.starts_with("x-forwarded-")
        && !["forwarded", "x-real-ip"].contains(&n.as_str())
        && ![
            "authorization",
            "cookie",
            "host",
            "connection",
            "content-length",
            "content-type",
            "accept",
            "accept-encoding",
            "transfer-encoding",
            "upgrade",
            "te",
            "trailer",
            "origin",
            "referer",
        ]
        .contains(&n.as_str())
}
