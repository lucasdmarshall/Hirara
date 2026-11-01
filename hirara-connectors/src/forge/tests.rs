use super::*;
fn source() -> Vec<u8> {
    include_bytes!("../../../examples/forge/inventory.openapi.json").to_vec()
}
fn package() -> Package {
    spec::compile(&source(), "inventory", None, Some("INVENTORY_TOKEN"), None).unwrap()
}
#[test]
fn compile_and_validate() {
    let p = package();
    execute::validate(&p).unwrap();
    assert_eq!(p.tools.len(), 1);
    assert_eq!(p.skipped.len(), 1);
    assert_eq!(
        serde_json::to_vec(&p).unwrap(),
        serde_json::to_vec(&package()).unwrap()
    );
    let plan = execute::plan(
        &p,
        &p.tools[0],
        &json!({"path":{"sku":"A B"},"query":{"warehouse":"east"}}),
    )
    .unwrap();
    assert_eq!(
        plan.url.as_str(),
        "https://api.example.com/v1/stock/A%20B?warehouse=east"
    );
}
#[test]
fn unsafe_arguments_and_packages_fail() {
    let mut p = package();
    let t = &p.tools[0];
    for args in [
        json!({}),
        json!({"path":{"sku":"../x"}}),
        json!({"path":{"sku":"%2f"}}),
        json!({"path":{"sku":"ok"},"token":"secret"}),
        json!({"path":{"sku":12}}),
        json!({"path":{"sku":"ok"},"headers":{"Authorization":"evil"}}),
    ] {
        assert!(execute::plan(&p, t, &args).is_err());
    }
    p.tools[0].method = "POST".into();
    assert!(execute::validate(&p).is_err());
    assert!(!spec::safe_header("X-Forwarded-Host"));
    for base in [
        "http://example.com",
        "https://127.0.0.1",
        "https://169.254.169.254",
    ] {
        assert!(spec::compile(&source(), "inventory", Some(base), Some("TOKEN"), None).is_err());
    }
}
#[test]
fn auth_and_refs_fail_closed() {
    assert!(spec::compile(&source(), "inventory", None, None, None).is_err());
    let mut s: Value = serde_json::from_slice(&source()).unwrap();
    s["components"]["securitySchemes"]["bearer"] =
        json!({"type":"apiKey","in":"query","name":"key"});
    assert!(
        spec::compile(
            &serde_json::to_vec(&s).unwrap(),
            "inventory",
            None,
            Some("TOKEN"),
            None
        )
        .is_err()
    );
    s = serde_json::from_slice(&source()).unwrap();
    s["paths"]["/stock/{sku}"]["get"]["parameters"][0] = json!({"$ref":"https://evil.example/p"});
    assert!(
        spec::compile(
            &serde_json::to_vec(&s).unwrap(),
            "inventory",
            None,
            Some("TOKEN"),
            None
        )
        .is_err()
    );
}
#[test]
fn pinned_package_detects_edits() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("package.json");
    let bytes = serde_json::to_vec(&package()).unwrap();
    std::fs::write(&path, &bytes).unwrap();
    let pin = digest(&bytes);
    assert!(load(path.to_str().unwrap(), Some(&pin)).is_ok());
    std::fs::write(&path, b"{}").unwrap();
    assert!(load(path.to_str().unwrap(), Some(&pin)).is_err());
}
#[tokio::test]
async fn http_execution_redacts_credentials_and_does_not_follow_redirects() {
    use axum::{Router, response::IntoResponse, routing::get};
    let app = Router::new()
        .route(
            "/stock/{sku}",
            get(
                |headers: axum::http::HeaderMap,
                 axum::extract::Path(sku): axum::extract::Path<String>| async move {
                    assert_eq!(headers["authorization"], "Bearer fixture-secret");
                    match sku.as_str() {
                        "redirect" => (
                            axum::http::StatusCode::FOUND,
                            [("location", "/never")],
                            "secret error body",
                        )
                            .into_response(),
                        "unauthorized" => {
                            (axum::http::StatusCode::UNAUTHORIZED, "fixture-secret").into_response()
                        }
                        _ => axum::Json(json!({"echo":"Bearer fixture-secret"})).into_response(),
                    }
                },
            ),
        )
        .route(
            "/never",
            get(|| async {
                panic!("redirect must not be followed");
                #[allow(unreachable_code)]
                ""
            }),
        );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let task = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    let mut p = package();
    p.base_url = format!("http://{addr}");
    let net = Net {
        client: reqwest::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .unwrap(),
        proxied: false,
        local: true,
    };
    for (sku, status) in [("ok", 200), ("redirect", 302), ("unauthorized", 401)] {
        let result = execute::execute(
            &p,
            &p.tools[0].name,
            &json!({"path":{"sku":sku}}),
            &net,
            Some("fixture-secret"),
        )
        .await
        .unwrap();
        assert_eq!(result["upstream_status"], status);
        assert!(!result.to_string().contains("fixture-secret"));
        if status == 200 {
            assert_eq!(result["data"]["echo"], "Bearer [REDACTED]");
        } else {
            assert!(result.get("error").is_some());
        }
    }
    task.abort();
}

#[test]
fn header_api_key_and_public_overrides_are_explicit() {
    let mut source: Value = serde_json::from_slice(&source()).unwrap();
    source["components"]["securitySchemes"]["bearer"] =
        json!({"type":"apiKey","in":"header","name":"x-inventory-key"});
    let bytes = serde_json::to_vec(&source).unwrap();
    let package = spec::compile(&bytes, "inventory", None, Some("TOKEN"), None).unwrap();
    assert_eq!(
        package.tools[0].auth.as_ref().unwrap().header,
        "x-inventory-key"
    );
    source["paths"]["/stock/{sku}"]["get"]["security"] = json!([]);
    let package = spec::compile(
        &serde_json::to_vec(&source).unwrap(),
        "inventory",
        None,
        None,
        None,
    )
    .unwrap();
    assert!(package.tools[0].auth.is_none());
    source["paths"]["/stock/{sku}"]["get"]["parameters"]
        .as_array_mut()
        .unwrap()
        .push(json!({"name":"Authorization","in":"header","schema":{"type":"string"}}));
    assert!(
        spec::compile(
            &serde_json::to_vec(&source).unwrap(),
            "inventory",
            None,
            None,
            None
        )
        .is_err()
    );
}

#[test]
fn loaded_package_cannot_expand_schema_or_override_auth() {
    let mut p = package();
    p.tools[0].parameters[0].schema["$ref"] = json!("https://evil.example/schema");
    p.tools[0].input_schema = spec::input_schema(&p.tools[0].parameters);
    assert!(execute::validate(&p).is_err());
    let mut p = package();
    p.tools[0].auth.as_mut().unwrap().scheme = "api_key".into();
    p.tools[0].auth.as_mut().unwrap().header = "Host".into();
    assert!(execute::validate(&p).is_err());
}
