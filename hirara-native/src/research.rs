//! Fixed provider URLs; HTTP is performed by Hirara's existing pinned downloader.
use crate::{number, text};
use serde_json::{Value, json};

pub fn request(v: &Value) -> Result<Value, String> {
    let query = text(v, "query")?.trim();
    if query.is_empty() || query.len() > 4000 {
        return Err("query must contain 1 to 4000 bytes".into());
    }
    let limit = number(v, "max_results", 5)?.min(20);
    let start = v.get("start").and_then(Value::as_u64).unwrap_or(0);
    if start > 10_000 {
        return Err("start must be between 0 and 10000".into());
    }
    let provider = text(v, "provider")?;
    let mut url = url::Url::parse(match provider {
        "arxiv" => "https://export.arxiv.org/api/query",
        "pubmed" => "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        _ => return Err("unknown research provider".into()),
    })
    .unwrap();
    if provider == "arxiv" {
        url.query_pairs_mut()
            .append_pair("search_query", query)
            .append_pair("start", &start.to_string())
            .append_pair("max_results", &limit.to_string());
    } else {
        url.query_pairs_mut()
            .append_pair("db", "pubmed")
            .append_pair("term", query)
            .append_pair("retmode", "json")
            .append_pair("retstart", &start.to_string())
            .append_pair("retmax", &limit.to_string())
            .append_pair("tool", "hirara");
    }
    Ok(json!({"url":url.as_str(),"error":null}))
}

fn content(node: roxmltree::Node<'_, '_>, name: &str) -> String {
    node.children()
        .find(|n| n.is_element() && n.tag_name().name() == name)
        .map(|n| {
            n.descendants()
                .filter(|n| n.is_text())
                .filter_map(|n| n.text())
                .collect::<Vec<_>>()
                .join(" ")
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" ")
        })
        .unwrap_or_default()
}

pub fn parse(v: &Value) -> Result<Value, String> {
    let body = text(v, "body")?;
    if body.len() > 2_000_000 {
        return Err("research response exceeds 2 MB".into());
    }
    let limit = number(v, "max_results", 5)?.min(20) as usize;
    match text(v, "provider")? {
        "arxiv" => {
            // roxmltree refuses DTDs by default; no external entity resolution.
            let doc =
                roxmltree::Document::parse(body).map_err(|e| format!("invalid arXiv XML: {e}"))?;
            if doc.root_element().tag_name().name() != "feed" {
                return Err("arXiv response is not an Atom feed".into());
            }
            let total = doc
                .descendants()
                .find(|n| n.is_element() && n.tag_name().name() == "totalResults")
                .and_then(|n| n.text())
                .and_then(|s| s.parse::<u64>().ok());
            let mut results = Vec::new();
            for entry in doc
                .descendants()
                .filter(|n| n.is_element() && n.tag_name().name() == "entry")
                .take(limit)
            {
                let id = content(entry, "id");
                if id.ends_with("/errors") {
                    return Err(format!("arXiv: {}", content(entry, "summary")));
                }
                let authors = entry
                    .children()
                    .filter(|n| n.is_element() && n.tag_name().name() == "author")
                    .map(|n| content(n, "name"))
                    .collect::<Vec<_>>();
                // Return canonical arxiv.org links, never arbitrary URLs supplied by XML.
                let parsed = url::Url::parse(&id).map_err(|_| "invalid arXiv result id")?;
                if !matches!(parsed.host_str(), Some("arxiv.org" | "export.arxiv.org"))
                    || !parsed.path().starts_with("/abs/")
                {
                    return Err("invalid arXiv result URL".into());
                }
                let article_id = parsed.path().trim_start_matches("/abs/");
                results.push(json!({"id":article_id,"title":content(entry,"title"),"summary":content(entry,"summary"),"authors":authors,"published":content(entry,"published"),"updated":content(entry,"updated"),"url":format!("https://arxiv.org/abs/{article_id}"),"pdf_url":format!("https://arxiv.org/pdf/{article_id}")}));
            }
            Ok(json!({"results":results,"total":total,"error":null}))
        }
        "pubmed_ids" => {
            let data: Value =
                serde_json::from_str(body).map_err(|e| format!("invalid PubMed response: {e}"))?;
            if data.get("error").is_some() || data["esearchresult"].get("errorlist").is_some() {
                return Err("PubMed rejected the search query".into());
            }
            let ids = data["esearchresult"]["idlist"]
                .as_array()
                .ok_or("PubMed response missing idlist")?;
            let ids: Vec<&str> = ids
                .iter()
                .take(limit)
                .map(|id| {
                    id.as_str()
                        .filter(|s| !s.is_empty() && s.bytes().all(|c| c.is_ascii_digit()))
                        .ok_or("invalid PubMed id")
                })
                .collect::<Result<_, _>>()?;
            let mut url =
                url::Url::parse("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi")
                    .unwrap();
            url.query_pairs_mut()
                .append_pair("db", "pubmed")
                .append_pair("retmode", "json")
                .append_pair("id", &ids.join(","))
                .append_pair("tool", "hirara");
            Ok(
                json!({"ids":ids,"total":data["esearchresult"]["count"].as_str().and_then(|s|s.parse::<u64>().ok()),"url":url.as_str(),"error":null}),
            )
        }
        "pubmed" => {
            let data: Value =
                serde_json::from_str(body).map_err(|e| format!("invalid PubMed summary: {e}"))?;
            if data.get("error").is_some() {
                return Err("PubMed summary request failed".into());
            }
            let uids = data["result"]["uids"]
                .as_array()
                .ok_or("PubMed summary missing uids")?;
            let mut results = Vec::new();
            for uid in uids.iter().take(limit) {
                let id = uid
                    .as_str()
                    .filter(|s| !s.is_empty() && s.bytes().all(|c| c.is_ascii_digit()))
                    .ok_or("invalid PubMed id")?;
                let entry = &data["result"][id];
                if entry.get("error").is_some() {
                    return Err(format!("PubMed summary unavailable for {id}"));
                }
                let authors: Vec<&str> = entry["authors"]
                    .as_array()
                    .map(|a| a.iter().filter_map(|x| x["name"].as_str()).collect())
                    .unwrap_or_default();
                let doi = entry["articleids"]
                    .as_array()
                    .and_then(|a| a.iter().find(|x| x["idtype"] == "doi"))
                    .map(|x| x["value"].clone())
                    .unwrap_or(Value::Null);
                results.push(json!({"id":id,"title":entry["title"],"authors":authors,"published":entry["pubdate"],"journal":entry["fulljournalname"],"doi":doi,"url":format!("https://pubmed.ncbi.nlm.nih.gov/{id}/")}));
            }
            Ok(json!({"results":results,"error":null}))
        }
        _ => Err("unknown research provider".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn encodes_query_and_refuses_entities() {
        let v = request(&json!({"provider":"arxiv","query":"x&url=http://localhost"})).unwrap();
        let url = url::Url::parse(v["url"].as_str().unwrap()).unwrap();
        assert_eq!(url.host_str(), Some("export.arxiv.org"));
        assert_eq!(url.query_pairs().count(), 3);
        assert!(parse(&json!({"provider":"arxiv","body":"<!DOCTYPE foo [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><feed>&x;</feed>"})).is_err());
    }
}
