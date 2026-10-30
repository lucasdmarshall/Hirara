//! Pinned Gyrfalcon adapter. Models and index directories are administrator grants.
use crate::{number, text};
use gyrfalcon::{Document, Filter, Index, RetrieveOptions, Tier, Warmup};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex, OnceLock, RwLock};

type Handle = Arc<RwLock<Index>>;
type Collections = HashMap<String, Handle>;
static COLLECTIONS: OnceLock<Mutex<Collections>> = OnceLock::new();

fn collection(v: &Value, create: bool) -> Result<Handle, String> {
    let path = text(v, "collection_path")?;
    let models = text(v, "models_path")?;
    let tier = text(v, "tier")?;
    let key = json!([path, models, tier]).to_string();
    let mut handles = COLLECTIONS
        .get_or_init(Default::default)
        .lock()
        .map_err(|_| "collection manager failed")?;
    if let Some(index) = handles.get(&key) {
        return Ok(index.clone());
    }
    if handles.len() >= 32 {
        return Err("at most 32 collections may be open per process".into());
    }
    let tier = Tier::parse(tier).ok_or("tier must be lite or full")?;
    let models = Path::new(models);
    // Validate model files before creating any collection, and never download.
    let embedder = tier
        .embedder(models)
        .map_err(|e| format!("Gyrfalcon model unavailable: {e}"))?;
    let config = tier.config(models);
    if embedder.dimension() != config.dimension {
        return Err("model dimension mismatch".into());
    }
    let path = Path::new(path);
    let mut index = if !path.join("manifest.json").exists() && create {
        let mut directory = std::fs::DirBuilder::new();
        directory.recursive(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            directory.mode(0o700);
        }
        directory
            .create(path)
            .map_err(|e| format!("cannot create private collection directory: {e}"))?;
        Index::create(path, &config)
    } else {
        Index::open_with_warmup(path, &config, Warmup::None)
    }
    .map_err(|e| format!("Gyrfalcon collection unavailable: {e}"))?;
    index.set_embedder(embedder);
    index.fusion = tier.fusion();
    let handle = Arc::new(RwLock::new(index));
    handles.insert(key, handle.clone());
    Ok(handle)
}

fn pairs(v: &Value, key: &str) -> Result<Vec<(String, String)>, String> {
    let Some(value) = v.get(key).filter(|x| !x.is_null()) else {
        return Ok(Vec::new());
    };
    let object = value
        .as_object()
        .ok_or("metadata/filter must be an object")?;
    if object.len() > 32 {
        return Err("at most 32 metadata/filter keys are allowed".into());
    }
    let mut out = Vec::new();
    for (key, value) in object {
        if key.is_empty()
            || key.len() > 100
            || key.starts_with("__hirara_")
            || key.chars().any(char::is_control)
        {
            return Err("invalid or reserved metadata key".into());
        }
        let values = if let Some(a) = value.as_array() {
            a.clone()
        } else {
            vec![value.clone()]
        };
        if values.len() > 20 {
            return Err("at most 20 values per metadata/filter key".into());
        }
        for val in values {
            let s = match val {
                Value::String(s) => s,
                Value::Bool(b) => b.to_string(),
                Value::Number(n) => n.to_string(),
                _ => {
                    return Err(
                        "metadata/filter values must be strings, numbers or booleans".into(),
                    );
                }
            };
            if s.len() > 2000 || s.chars().any(char::is_control) {
                return Err("metadata value is too large or contains control characters".into());
            }
            out.push((key.clone(), s));
        }
    }
    Ok(out)
}

fn extract(v: &Value) -> Result<(String, Vec<usize>, String), String> {
    let cap = number(v, "max_input_bytes", 2_000_000)? as usize;
    if !v["path"].is_null() {
        if !v["text"].is_null() {
            return Err("provide path OR text, not both".into());
        }
        let (bytes, path) = crate::files::index_source(v)?;
        let extension = path
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let (content, pages) = match extension.as_str() {
            "pdf" => {
                let pdfium = gyrfalcon_ingest::pdf::pdfium().map_err(|e| e.to_string())?;
                let pdf = pdfium
                    .load_pdf_from_byte_slice(&bytes, None)
                    .map_err(|e| format!("cannot read PDF: {e}"))?;
                if pdf.pages().len() > 200 {
                    return Err("PDF exceeds 200 pages".into());
                }
                let mut pages = Vec::new();
                let mut size = 0;
                for page in pdf.pages().iter() {
                    let page = page.text().map_err(|e| e.to_string())?.all();
                    size += page.len();
                    if size > cap {
                        return Err("PDF text exceeds CRAG_MAX_INPUT_BYTES".into());
                    }
                    pages.push(page);
                }
                let extracted = gyrfalcon_ingest::layout::clean(&pages);
                (extracted.text, extracted.page_starts)
            }
            "html" | "htm" | "xhtml" => (
                gyrfalcon_ingest::html::to_text(&String::from_utf8_lossy(&bytes)),
                Vec::new(),
            ),
            "txt" | "text" | "md" | "markdown" | "rst" | "adoc" | "org" | "" => (
                String::from_utf8(bytes).map_err(|_| "source is not UTF-8 text")?,
                Vec::new(),
            ),
            _ => {
                return Err(
                    "unsupported source; extract Office/OCR with existing tools and pass text="
                        .into(),
                );
            }
        };
        if content.len() > cap {
            return Err("extracted text exceeds CRAG_MAX_INPUT_BYTES".into());
        }
        Ok((content, pages, path.to_string_lossy().into_owned()))
    } else {
        let content = text(v, "text")?;
        if content.len() > cap {
            return Err("text exceeds CRAG_MAX_INPUT_BYTES".into());
        }
        Ok((
            content.to_owned(),
            Vec::new(),
            v.get("source")
                .and_then(Value::as_str)
                .unwrap_or("provided text")
                .to_owned(),
        ))
    }
}

pub fn run(action: &str, v: &Value) -> Result<Value, String> {
    if action == "document_close" {
        let path = text(v, "collection_path")?;
        let mut handles = COLLECTIONS
            .get_or_init(Default::default)
            .lock()
            .map_err(|_| "collection manager failed")?;
        let keys: Vec<_> = handles
            .keys()
            .filter(|key| serde_json::from_str::<Value>(key).is_ok_and(|a| a[0] == path))
            .cloned()
            .collect();
        for key in keys {
            if let Some(handle) = handles.remove(&key) {
                let mut index = handle.write().map_err(|_| "collection lock failed")?;
                index.flush().map_err(|e| e.to_string())?;
                index.wait_until_merge_idle();
                index.reap_now();
            }
        }
        return Ok(json!({"error":null}));
    }
    if action != "document_search" && v["allow_write"] != true {
        return Err("document mutations disabled (CRAG_ALLOW_WRITE=false)".into());
    }
    match action {
        "document_index" => {
            let (content, pages, source) = extract(v)?;
            if content.trim().is_empty() {
                return Err("document contains no searchable text".into());
            }
            if v["path"].is_null() && v["doc_id"].as_str().is_none() {
                return Err("doc_id is required when indexing text".into());
            }
            let id = v
                .get("doc_id")
                .and_then(Value::as_str)
                .unwrap_or(&source)
                .to_owned();
            if id.is_empty() || id.len() > 1024 || source.len() > 4096 {
                return Err("invalid document id or source".into());
            }
            let mut metadata = pairs(v, "metadata")?;
            metadata.push(("__hirara_source".into(), source));
            if !pages.is_empty() {
                metadata.push(("__hirara_pages".into(), json!(pages).to_string()));
            }
            let handle = collection(v, true)?;
            let mut index = handle.write().map_err(|_| "collection lock failed")?;
            let report = index
                .update_document(Document::body(&id, content).with_metadata(metadata))
                .map_err(|e| e.to_string())?;
            Ok(json!({"doc_id":id,"chunks":report.chunk_ids.len(),"error":null}))
        }
        "document_remove" => {
            let id = text(v, "doc_id")?;
            if id.is_empty() || id.len() > 1024 {
                return Err("invalid document id".into());
            }
            let handle = collection(v, false)?;
            let mut index = handle.write().map_err(|_| "collection lock failed")?;
            let report = index.delete_document(id).map_err(|e| e.to_string())?;
            Ok(json!({"doc_id":id,"removed_chunks":report.deleted_chunks,"error":null}))
        }
        "document_search" => {
            let query = text(v, "query")?;
            if query.trim().is_empty() || query.len() > 4000 {
                return Err("query must contain 1..4000 bytes".into());
            }
            let limit = number(v, "max_results", 5)?;
            if limit > 20 {
                return Err("max_results must be 1..20".into());
            }
            let mut filter = Filter::new();
            let mut groups: HashMap<String, Vec<String>> = HashMap::new();
            for (key, val) in pairs(v, "filter")? {
                groups.entry(key).or_default().push(val);
            }
            for (key, vals) in groups {
                filter = filter.any(key, vals);
            }
            // An empty value-list is a match-nothing condition, not no filtering.
            if v["filter"].as_object().is_some_and(|f| {
                f.values()
                    .any(|val| val.as_array().is_some_and(Vec::is_empty))
            }) {
                return Ok(json!({"results":[],"error":null}));
            }
            let handle = collection(v, false)?;
            let index = handle.read().map_err(|_| "collection lock failed")?;
            let hits = index
                .retrieve_filtered(
                    query,
                    RetrieveOptions {
                        rerank: false,
                        limit: limit as usize,
                    },
                    Some(&filter),
                )
                .map_err(|e| e.to_string())?;
            let mut results = Vec::new();
            for hit in hits.hits {
                let source = hit
                    .metadata
                    .iter()
                    .find(|(k, _)| k == "__hirara_source")
                    .map(|(_, v)| v.clone());
                let pages = hit
                    .metadata
                    .iter()
                    .find(|(k, _)| k == "__hirara_pages")
                    .and_then(|(_, v)| serde_json::from_str::<Vec<u64>>(v).ok());
                let page = pages
                    .as_ref()
                    .map(|p| p.partition_point(|start| *start <= hit.byte_start));
                let page_end = pages
                    .map(|p| p.partition_point(|start| *start <= hit.byte_end.saturating_sub(1)));
                let mut metadata = serde_json::Map::new();
                for (key, value) in &hit.metadata {
                    if key.starts_with("__hirara_") {
                        continue;
                    }
                    match metadata.get_mut(key) {
                        None => {
                            metadata.insert(key.clone(), json!(value));
                        }
                        Some(Value::Array(a)) => a.push(json!(value)),
                        Some(old) => *old = json!([old.clone(), value]),
                    }
                }
                results.push(json!({"doc_id":hit.doc_id,"chunk_id":hit.chunk_id,"text":hit.body,"score":hit.score,"source":source,"page":page,"page_end":page_end,"start":hit.byte_start,"end":hit.byte_end,"metadata":metadata}));
            }
            Ok(json!({"results":results,"error":null}))
        }
        _ => Err("unknown document operation".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn real_gyrfalcon_semantic_lifecycle() {
        let dir = tempfile::tempdir().unwrap();
        let models = dir.path().join("model");
        std::fs::create_dir(&models).unwrap();
        let mut header =
            json!({"embeddings":{"dtype":"F32","shape":[4,8],"data_offsets":[0,128]}}).to_string();
        while !(8 + header.len()).is_multiple_of(8) {
            header.push(' ');
        }
        let mut data = (header.len() as u64).to_le_bytes().to_vec();
        data.extend(header.bytes());
        for row in [
            [0.0f32; 8],
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        ] {
            for x in row {
                data.extend(x.to_le_bytes());
            }
        }
        std::fs::write(models.join("model.safetensors"), data).unwrap();
        let tokenizer = json!({"version":"1.0","truncation":null,"padding":null,"added_tokens":[],"normalizer":{"type":"Lowercase"},"pre_tokenizer":{"type":"Whitespace"},"post_processor":null,"decoder":null,"model":{"type":"WordLevel","vocab":{"[UNK]":0,"car":1,"automobile":2,"banana":3},"unk_token":"[UNK]"}});
        std::fs::write(models.join("tokenizer.json"), tokenizer.to_string()).unwrap();
        let mut v = json!({"collection_path":dir.path().join("index"),"models_path":models,"tier":"lite","allow_write":true,"text":"automobile","doc_id":"a","metadata":{"topic":"cars"}});
        assert_eq!(run("document_index", &v).unwrap()["chunks"], 1);
        v["doc_id"] = json!("b");
        v["text"] = json!("banana");
        v["metadata"] = json!({"topic":"fruit"});
        run("document_index", &v).unwrap();
        run("document_close", &v).unwrap();
        v["query"] = json!("car");
        assert_eq!(
            run("document_search", &v).unwrap()["results"][0]["doc_id"],
            "a"
        );
        v["filter"] = json!({"topic":"fruit"});
        assert_eq!(
            run("document_search", &v).unwrap()["results"][0]["doc_id"],
            "b"
        );
        v["doc_id"] = json!("a");
        run("document_remove", &v).unwrap();
        v["filter"] = json!({"topic":"cars"});
        assert!(
            run("document_search", &v).unwrap()["results"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        run("document_close", &v).unwrap();
    }
}
