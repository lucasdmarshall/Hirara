use crate::{number, text};
use serde_json::{Value, json};
use std::io::{self, Write};

/// Stop serialization before an expression's shared references expand into a
/// huge JSON allocation (for example, repeatedly projecting [@, @]).
struct LimitedJson {
    bytes: Vec<u8>,
    cap: usize,
}
impl Write for LimitedJson {
    fn write(&mut self, data: &[u8]) -> io::Result<usize> {
        if data.len() > self.cap.saturating_sub(self.bytes.len()) {
            return Err(io::Error::other("JSON result exceeds output limit"));
        }
        self.bytes.extend_from_slice(data);
        Ok(data.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn bounded_json(value: &impl serde::Serialize, cap: usize) -> Result<Vec<u8>, String> {
    let mut writer = LimitedJson {
        bytes: Vec::new(),
        cap,
    };
    serde_json::to_writer(&mut writer, value)
        .map_err(|_| "result exceeds CUTIL_MAX_OUTPUT_BYTES; narrow the query".to_string())?;
    Ok(writer.bytes)
}

/// Builtins that materialize strings need a check before allocation too.
struct BoundedFunction {
    original: Box<dyn jmespath::functions::Function>,
    cap: usize,
    join: bool,
}
impl jmespath::functions::Function for BoundedFunction {
    fn evaluate(
        &self,
        args: &[jmespath::Rcvar],
        ctx: &mut jmespath::Context<'_>,
    ) -> Result<jmespath::Rcvar, jmespath::JmespathError> {
        let oversized = if self.join && args.len() == 2 {
            if let (Some(separator), Some(items)) = (args[0].as_string(), args[1].as_array()) {
                let mut size = separator
                    .len()
                    .saturating_mul(items.len().saturating_sub(1));
                for item in items {
                    size = size.saturating_add(item.as_string().map_or(0, |s| s.len()));
                }
                size > self.cap
            } else {
                false
            }
        } else if !self.join && args.len() == 1 {
            bounded_json(&args[0], self.cap).is_err()
        } else {
            false
        };
        if oversized {
            return Err(jmespath::JmespathError::new(
                ctx.expression,
                ctx.offset,
                jmespath::ErrorReason::Runtime(jmespath::RuntimeError::InvalidType {
                    expected: "value within CUTIL_MAX_OUTPUT_BYTES".into(),
                    actual: "oversized intermediate string".into(),
                    position: 0,
                }),
            ));
        }
        self.original.evaluate(args, ctx)
    }
}

pub fn run(v: &Value) -> Result<Value, String> {
    let input = v.get("input").ok_or("input is required")?;
    let max_input = number(v, "max_input_chars", 1_000_000)? as usize;
    let serialized = input.to_string();
    if serialized.chars().count() > max_input {
        return Err("input exceeds CUTIL_MAX_INPUT_CHARS".into());
    }
    let document: Value = if let Some(s) = input.as_str() {
        serde_json::from_str(s).map_err(|e| format!("invalid JSON: {e}"))?
    } else {
        input.clone()
    };
    let expression = text(v, "expression")?;
    let max_output = number(v, "max_output_bytes", 2_000_000)? as usize;
    if expression.len() > 4096 {
        return Err("expression exceeds 4096 bytes".into());
    }
    let result = match v
        .get("syntax")
        .and_then(Value::as_str)
        .unwrap_or("jmespath")
    {
        "pointer" => {
            // serde_json accepts some malformed escapes; RFC 6901 does not.
            let bytes = expression.as_bytes();
            if (!expression.is_empty() && !expression.starts_with('/'))
                || bytes
                    .iter()
                    .enumerate()
                    .any(|(i, b)| *b == b'~' && !matches!(bytes.get(i + 1), Some(b'0' | b'1')))
            {
                return Err("invalid RFC 6901 JSON pointer".into());
            }
            document
                .pointer(expression)
                .cloned()
                .ok_or("JSON pointer does not exist")?
        }
        "jmespath" => {
            let mut runtime = jmespath::Runtime::new();
            runtime.register_builtin_functions();
            for name in ["join", "to_string"] {
                let original = runtime.deregister_function(name).unwrap();
                runtime.register_function(
                    name,
                    Box::new(BoundedFunction {
                        original,
                        cap: max_output,
                        join: name == "join",
                    }),
                );
            }
            let expr = runtime
                .compile(expression)
                .map_err(|e| format!("invalid JMESPath: {e}"))?;
            let data =
                jmespath::Variable::from_json(&document.to_string()).map_err(|e| e.to_string())?;
            let result = expr
                .search(data)
                .map_err(|e| format!("JMESPath query failed: {e}"))?;
            serde_json::from_slice(&bounded_json(&result, max_output)?)
                .map_err(|e| e.to_string())?
        }
        _ => return Err("syntax must be jmespath or pointer".into()),
    };
    bounded_json(&result, max_output)?;
    Ok(json!({"result": result, "error": null}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn query_and_pointer() {
        let doc = json!({"items":[{"price":2,"name":"a"},{"price":9,"name":"b"}], "a/b":null});
        assert_eq!(
            run(&json!({"input":doc,"expression":"items[?price > `3`].name"})).unwrap()["result"],
            json!(["b"])
        );
        assert_eq!(
            run(&json!({"input":doc,"syntax":"pointer","expression":"/a~1b"})).unwrap()["result"],
            Value::Null
        );
        assert!(run(&json!({"input":doc,"syntax":"pointer","expression":"/~2"})).is_err());
        assert!(run(&json!({"input":doc,"expression":"items","max_output_bytes":2})).is_err());
        assert!(run(&json!({"input":"\"abcdefghijklmnopqrstuvwxyz\"","expression":"[@,@] | [@,@] | [@,@]", "max_output_bytes":100})).is_err());
        assert!(run(&json!({"input":{"sep":"abcdef","items":["","","",""]},"expression":"join(sep,items)","max_output_bytes":10})).is_err());
    }
}
