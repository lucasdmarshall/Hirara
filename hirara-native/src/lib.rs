//! Tool logic only. Python owns tool permissions, transports and shared HTTP egress.
mod database;
mod files;
mod json_query;
mod research;

use pyo3::prelude::*;
use serde_json::{Value, json};

fn dispatch(request: Value) -> Result<Value, String> {
    let action = text(&request, "action")?;
    match action {
        "file_copy" | "file_move" | "file_rename" | "file_delete" => files::run(action, &request),
        "json_query" => json_query::run(&request),
        "research_request" => research::request(&request),
        "research_parse" => research::parse(&request),
        "database_query" | "database_schema" => database::run(action, &request),
        _ => Err("unknown native action".into()),
    }
}

pub(crate) fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{key} must be a string"))
}

pub(crate) fn number(value: &Value, key: &str, default: u64) -> Result<u64, String> {
    match value.get(key) {
        None => Ok(default),
        Some(v) => v
            .as_u64()
            .filter(|n| *n > 0)
            .ok_or_else(|| format!("{key} must be a positive integer")),
    }
}

#[pyfunction]
fn run(py: Python<'_>, request: String) -> PyResult<String> {
    // Native code never calls Python while detached. Each request is independent.
    let response = py.detach(|| {
        let result = serde_json::from_str(&request)
            .map_err(|e| e.to_string())
            .and_then(dispatch);
        match result {
            Ok(value) => value,
            Err(error) => json!({"error": error}),
        }
    });
    Ok(response.to_string())
}

#[pymodule]
fn hirara_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(run, module)?)?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
