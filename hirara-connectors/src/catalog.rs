//! Discovery metadata is untrusted. It never grants execution permissions.
use crate::net::{Error, Net, fail};
use scraper::{Html, Selector};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::Mutex;
const REGISTRY: &str = "https://registry.modelcontextprotocol.io/v0.1/servers";
const CURSOR: &str = "https://raw.githubusercontent.com/cursor/plugins/main";
const CLAUDE: &str = "https://claude.com/marketplace/connectors-plugins";
#[derive(Clone)]
pub struct Catalog {
    net: Net,
    cache: Arc<Mutex<HashMap<String, (Instant, Value)>>>,
}
impl Catalog {
    pub fn new(net: Net) -> Self {
        Self {
            net,
            cache: Default::default(),
        }
    }
    async fn fetch(&self, url: &str) -> Result<Value, Error> {
        if let Some((when, value)) = self.cache.lock().await.get(url)
            && when.elapsed() < Duration::from_secs(300)
        {
            return Ok(value.clone());
        }
        let value = self.net.json(url).await?;
        let mut cache = self.cache.lock().await;
        if cache.len() >= 64 {
            cache.clear();
        }
        if serde_json::to_vec(&value)?.len() <= 256 * 1024 {
            cache.insert(url.into(), (Instant::now(), value.clone()));
        }
        Ok(value)
    }
    pub async fn search(
        &self,
        source: &str,
        query: &str,
        category: Option<&str>,
        cursor: Option<&str>,
        limit: usize,
    ) -> Result<Value, Error> {
        if query.len() > 256
            || category.is_some_and(|x| x.len() > 100)
            || cursor.is_some_and(|x| x.len() > 4096)
            || !(1..=50).contains(&limit)
        {
            return Err(fail("invalid catalog query or limit"));
        }
        match source {
            "official" => {
                let mut url = url::Url::parse(REGISTRY)?;
                {
                    let mut q = url.query_pairs_mut();
                    q.append_pair("limit", &limit.to_string())
                        .append_pair("version", "latest");
                    if !query.is_empty() {
                        if query.trim().chars().count() < 3 {
                            return Err(fail(
                                "official registry queries require at least 3 characters",
                            ));
                        }
                        q.append_pair("search", query);
                    }
                    if let Some(c) = cursor {
                        q.append_pair("cursor", c);
                    }
                }
                let raw = self.fetch(url.as_str()).await?;
                let items = raw["servers"]
                    .as_array()
                    .ok_or_else(|| fail("official registry schema changed"))?
                    .iter()
                    .map(official)
                    .filter(|x| matches_category(x, category))
                    .collect::<Vec<_>>();
                Ok(
                    json!({"items":items,"next_cursor":raw["metadata"]["nextCursor"],"source":"official","category_scope":"current provider page; categories are optional publisher metadata","raw_metadata":raw["metadata"]}),
                )
            }
            "cursor" => {
                let raw = self
                    .fetch(&format!("{CURSOR}/.cursor-plugin/marketplace.json"))
                    .await?;
                let plugins = raw["plugins"]
                    .as_array()
                    .ok_or_else(|| fail("Cursor manifest schema changed"))?;
                let all: Vec<_> = plugins
                    .iter()
                    .filter(|p| p.to_string().to_lowercase().contains(&query.to_lowercase()))
                    .collect();
                let offset = offset(cursor)?;
                use futures::{StreamExt, stream};
                let ids: Vec<String> = all
                    .iter()
                    .skip(offset)
                    .take(limit)
                    .filter_map(|p| p["name"].as_str().map(String::from))
                    .collect();
                let results: Vec<_> = stream::iter(ids.into_iter().map(|id| {
                    let catalog = self.clone();
                    async move { catalog.details("cursor", &id).await }
                }))
                .buffered(4)
                .collect()
                .await;
                let mut items = Vec::new();
                let mut unavailable = 0;
                for result in results {
                    match result {
                        Ok(item) => {
                            if item["has_mcp"] == true && matches_category(&item, category) {
                                items.push(item)
                            }
                        }
                        Err(_) => unavailable += 1,
                    }
                }
                Ok(
                    json!({"items":items,"next_cursor":if offset+limit<all.len(){Some((offset+limit).to_string())}else{None},"source":"cursor","coverage":"Cursor public plugins repository; not the complete website marketplace","category_scope":"current plugin page; follow next_cursor even if this page has no MCP matches","unavailable_details":unavailable,"total_plugins_matched":all.len()}),
                )
            }
            "cursor_marketplace" => {
                let html = self.net.text("https://cursor.com/marketplace").await?;
                let cards = cursor_cards(&html)?;
                let matching: Vec<_> = cards
                    .into_iter()
                    .filter(|p| p.to_string().to_lowercase().contains(&query.to_lowercase()))
                    .collect();
                let offset = offset(cursor)?;
                let more = matching.len() > offset + limit;
                let mut items: Vec<_> = matching.into_iter().skip(offset).take(limit).collect();
                let mut unavailable = 0;
                if category.is_some() {
                    use futures::{StreamExt, stream};
                    let ids: Vec<String> = items
                        .iter()
                        .filter_map(|p| p["id"].as_str().map(String::from))
                        .collect();
                    let results: Vec<_> = stream::iter(ids.into_iter().map(|id| {
                        let catalog = self.clone();
                        async move { catalog.details("cursor_marketplace", &id).await }
                    }))
                    .buffered(4)
                    .collect()
                    .await;
                    unavailable = results.iter().filter(|r| r.is_err()).count();
                    items = results
                        .into_iter()
                        .filter_map(Result::ok)
                        .filter(|p| matches_category(p, category))
                        .collect();
                }
                Ok(
                    json!({"source":"cursor_marketplace","unavailable_details":unavailable,"items":items,"next_cursor":if more{Some((offset+limit).to_string())}else{None},"coverage":"public website listings only; includes plugins which may not contain MCP servers","category_scope":"current listing page; categories only where published"}),
                )
            }
            "claude_directory" => {
                // HTML has no promised machine API. Schema changes are explicit errors.
                let html = self.net.text(CLAUDE).await?;
                let items = claude_cards(&html)?;
                let mut items = items;
                if category.is_some() {
                    use futures::{StreamExt, stream};
                    let offset = offset(cursor)?;
                    let matching: Vec<_> = items
                        .iter()
                        .filter(|p| p.to_string().to_lowercase().contains(&query.to_lowercase()))
                        .collect();
                    let more = matching.len() > offset + limit;
                    let ids: Vec<String> = matching
                        .iter()
                        .skip(offset)
                        .take(limit)
                        .filter_map(|p| p["id"].as_str().map(String::from))
                        .collect();
                    let results: Vec<_> = stream::iter(ids.into_iter().map(|id| {
                        let catalog = self.clone();
                        async move { catalog.details("claude_directory", &id).await }
                    }))
                    .buffered(4)
                    .collect()
                    .await;
                    let unavailable = results.iter().filter(|r| r.is_err()).count();
                    items = results
                        .into_iter()
                        .filter_map(Result::ok)
                        .filter(|p| matches_category(p, category))
                        .collect();
                    return Ok(
                        json!({"items":items,"next_cursor":if more{Some((offset+limit).to_string())}else{None},"source":"claude_directory","unavailable_details":unavailable,"category_scope":"current listing page; follow next_cursor","coverage":"public HTML listings only"}),
                    );
                }
                let all: Vec<_> = items
                    .into_iter()
                    .filter(|p| {
                        p.to_string().to_lowercase().contains(&query.to_lowercase())
                            && matches_category(p, category)
                    })
                    .collect();
                let offset = offset(cursor)?;
                let page: Vec<_> = all.iter().skip(offset).take(limit).cloned().collect();
                Ok(
                    json!({"items":page,"next_cursor":if offset+limit<all.len(){Some((offset+limit).to_string())}else{None},"source":"claude_directory","coverage":"public HTML listings only; dynamically loaded/private entries may be absent","total":all.len()}),
                )
            }
            _ => Err(fail(
                "source must be official, cursor, cursor_marketplace or claude_directory",
            )),
        }
    }
    pub async fn details(&self, source: &str, id: &str) -> Result<Value, Error> {
        if id.is_empty() || id.len() > 512 {
            return Err(fail("invalid server identifier"));
        }
        match source {
            "official" => {
                let mut url = url::Url::parse(REGISTRY)?;
                url.path_segments_mut()
                    .unwrap()
                    .push(id)
                    .push("versions")
                    .push("latest");
                let raw = self.fetch(url.as_str()).await?;
                let mut item = official(&raw);
                item["metadata_url"] = json!(url.as_str());
                Ok(item)
            }
            "cursor" => {
                let catalog = self
                    .fetch(&format!("{CURSOR}/.cursor-plugin/marketplace.json"))
                    .await?;
                let entry = catalog["plugins"]
                    .as_array()
                    .and_then(|p| p.iter().find(|p| p["name"] == id))
                    .ok_or_else(|| fail("plugin not found"))?;
                let path = entry["source"]
                    .as_str()
                    .ok_or_else(|| {
                        fail("external plugin repositories require manual endpoint configuration")
                    })?
                    .trim_start_matches("./");
                if !safe_path(path) {
                    return Err(fail("unsafe plugin path"));
                }
                let base = format!("{CURSOR}/{path}");
                let plugin = self
                    .fetch(&format!("{base}/.cursor-plugin/plugin.json"))
                    .await?;
                let mcp = match &plugin["mcpServers"] {
                    Value::Object(_) => plugin["mcpServers"].clone(),
                    Value::String(file) => {
                        let file = file.trim_start_matches("./");
                        if !safe_path(file) {
                            return Err(fail("unsafe MCP manifest path"));
                        }
                        self.fetch(&format!("{base}/{file}")).await?
                    }
                    _ => json!({}),
                };
                let mut endpoints = Vec::new();
                let servers = mcp.get("mcpServers").unwrap_or(&mcp);
                if let Some(servers) = servers.as_object() {
                    for (name, config) in servers {
                        if let Some(url) = config["url"].as_str()
                            && config["type"] != "sse"
                        {
                            endpoints.push(json!({"name":name,"type":"streamable-http","url":url}));
                        }
                    }
                }
                let logo = plugin["logo"].as_str().map(|l| {
                    if l.starts_with("https://") {
                        l.to_string()
                    } else {
                        format!("{base}/{}", l.trim_start_matches("./"))
                    }
                });
                Ok(
                    json!({"id":id,"source":source,"title":plugin.get("displayName").unwrap_or(&plugin["name"]),"description":plugin["description"],"categories":plugin["category"],"tags":plugin["tags"],"icons":[{"src":logo}],"publisher":plugin["author"],"website":plugin["homepage"],"repository":plugin["repository"],"version":plugin["version"],"has_mcp":servers.as_object().is_some_and(|s|!s.is_empty()),"endpoints":endpoints,"metadata_url":format!("{base}/.cursor-plugin/plugin.json"),"raw":{"listing":entry,"plugin":plugin,"mcp":mcp}}),
                )
            }
            "cursor_marketplace" => {
                if !safe_path(id) || id.contains('/') {
                    return Err(fail("invalid Cursor marketplace slug"));
                }
                let url = format!("https://cursor.com/marketplace/{id}");
                let html = self.net.text(&url).await?;
                let mut item = cursor_page(id, &url, &html);
                let candidates: std::collections::BTreeSet<String> = item["raw"]["links"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|a| a["url"].as_str())
                    .filter_map(github_mcp_raw)
                    .take(8)
                    .collect();
                let mut endpoints = Vec::new();
                let mut manifests = Vec::new();
                let mut unavailable = 0;
                for url in candidates {
                    match self.fetch(&url).await {
                        Ok(raw) => {
                            endpoints.extend(manifest_endpoints(&raw));
                            manifests.push(json!({"metadata_url":url,"raw":raw}));
                        }
                        Err(_) => unavailable += 1,
                    }
                }
                item["endpoints"] = json!(endpoints);
                item["raw"]["mcp_sources"] = json!(manifests);
                item["unavailable_mcp_sources"] = json!(unavailable);
                Ok(item)
            }
            "claude_directory" => {
                let path = id.trim_start_matches('/');
                if !safe_path(path)
                    || !(path.starts_with("connectors/")
                        || path.starts_with("marketplace/connectors/"))
                {
                    return Err(fail("invalid Claude listing path"));
                }
                let url = format!("https://claude.com/{path}");
                let html = self.net.text(&url).await?;
                let doc = Html::parse_document(&html);
                let mut metadata = serde_json::Map::new();
                for node in doc.select(&Selector::parse("meta[property],meta[name]").unwrap()) {
                    let key = node
                        .value()
                        .attr("property")
                        .or(node.value().attr("name"))
                        .unwrap_or("");
                    if let Some(value) = node.value().attr("content") {
                        metadata.insert(key.into(), json!(value));
                    }
                }
                let structured: Vec<_> = doc
                    .select(&Selector::parse("script[type='application/ld+json']").unwrap())
                    .filter_map(|x| serde_json::from_str::<Value>(&x.inner_html()).ok())
                    .collect();
                let page_text = doc.root_element().text().collect::<Vec<_>>().join("\n");
                let endpoints:Vec<_>=page_text.split_once("Connector URL").map(|(_,tail)|tail.split_whitespace().take(6).filter(|s|s.starts_with("https://")).filter(|s|crate::net::validate_url(s).is_ok()).take(1).map(|s|json!({"type":if s.ends_with("/sse"){"sse"}else{"streamable-http"},"url":s})).collect()).unwrap_or_default();
                let links:Vec<_>=doc.select(&Selector::parse("a[href]").unwrap()).map(|a|json!({"label":a.text().collect::<Vec<_>>().join(" "),"url":a.value().attr("href")})).collect();
                let categories: Vec<_> = doc
                    .select(&Selector::parse("li").unwrap())
                    .map(|e| e.text().collect::<Vec<_>>().join(" "))
                    .filter_map(|t| {
                        t.trim()
                            .strip_prefix("Categories")
                            .map(|s| s.trim().to_string())
                    })
                    .collect();
                let images: Vec<_> = doc
                    .select(&Selector::parse("img[src]").unwrap())
                    .map(|e| json!({"src":e.value().attr("src"),"alt":e.value().attr("alt")}))
                    .collect();
                Ok(
                    json!({"id":id,"source":source,"title":metadata.get("og:title"),"description":metadata.get("og:description").or(metadata.get("description")),"images":images,"categories":categories,"endpoints":endpoints,"metadata_url":url,"raw":{"meta":metadata,"structured_data":structured,"links":links,"page_text":page_text},"connection_note":"Only a provider-documented Connector URL is proposed; user approval is still required."}),
                )
            }
            _ => Err(fail("unknown catalog source")),
        }
    }
}
fn offset(cursor: Option<&str>) -> Result<usize, Error> {
    let value = cursor
        .unwrap_or("0")
        .parse::<usize>()
        .map_err(|_| fail("invalid cursor"))?;
    if value > 1_000_000 {
        return Err(fail("cursor offset exceeds supported inventory size"));
    }
    Ok(value)
}
fn safe_path(path: &str) -> bool {
    !path.is_empty()
        && path.split('/').all(|p| {
            !p.is_empty()
                && p != "."
                && p != ".."
                && p.chars()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
        })
}
fn matches_category(value: &Value, category: Option<&str>) -> bool {
    category.is_none_or(|c| {
        value
            .get("categories")
            .is_some_and(|v| v.to_string().to_lowercase().contains(&c.to_lowercase()))
    })
}
fn official(raw: &Value) -> Value {
    let server = raw.get("server").unwrap_or(raw);
    let categories = server
        .pointer("/_meta/io.modelcontextprotocol.registry~1publisher-provided/categories")
        .cloned()
        .unwrap_or(Value::Null);
    json!({"id":server["name"],"source":"official","title":server.get("title").unwrap_or(&server["name"]),"description":server["description"],"version":server["version"],"icons":server["icons"],"categories":categories,"repository":server["repository"],"website":server["websiteUrl"],"endpoints":server.get("remotes").cloned().unwrap_or(json!([])),"packages":server["packages"],"raw":raw})
}
fn claude_cards(html: &str) -> Result<Vec<Value>, Error> {
    let doc = Html::parse_document(html);
    let mut items = std::collections::BTreeMap::new();
    for a in doc.select(&Selector::parse("a[href]").unwrap()) {
        let href = a.value().attr("href").unwrap_or("");
        let path = href
            .strip_prefix("https://claude.com/")
            .unwrap_or_else(|| href.trim_start_matches('/'));
        if !(path.starts_with("connectors/") || path.starts_with("marketplace/connectors/"))
            || !safe_path(path)
        {
            continue;
        }
        let title = a
            .text()
            .collect::<Vec<_>>()
            .join(" ")
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ");
        let icons: Vec<_> = a
            .select(&Selector::parse("img").unwrap())
            .filter_map(|i| {
                i.value()
                    .attr("src")
                    .map(|s| json!({"src":s,"alt":i.value().attr("alt")}))
            })
            .collect();
        if !title.is_empty() {
            items.insert(path.to_string(),json!({"id":path,"source":"claude_directory","title":title,"icons":icons,"metadata_url":format!("https://claude.com/{path}"),"raw":{"href":href}}));
        }
    }
    if items.is_empty() {
        return Err(fail(
            "Claude directory HTML unavailable or changed; use official registry or a custom endpoint",
        ));
    }
    Ok(items.into_values().collect())
}
fn cursor_page(id: &str, url: &str, html: &str) -> Value {
    let doc = Html::parse_document(html);
    let mut metadata = serde_json::Map::new();
    for node in doc.select(&Selector::parse("meta[property],meta[name]").unwrap()) {
        if let (Some(k), Some(v)) = (
            node.value().attr("property").or(node.value().attr("name")),
            node.value().attr("content"),
        ) {
            metadata.insert(k.into(), json!(v));
        }
    }
    let links:Vec<_>=doc.select(&Selector::parse("a[href]").unwrap()).map(|a|json!({"label":a.text().collect::<Vec<_>>().join(" "),"url":a.value().attr("href")})).collect();
    let images: Vec<_> = doc
        .select(&Selector::parse("img[src]").unwrap())
        .map(|i| json!({"src":i.value().attr("src"),"alt":i.value().attr("alt")}))
        .collect();
    let structured: Vec<_> = doc
        .select(
            &Selector::parse("script[type='application/ld+json'],script[type='application/json']")
                .unwrap(),
        )
        .filter_map(|x| serde_json::from_str::<Value>(&x.inner_html()).ok())
        .collect();
    let categories: Vec<_> = links
        .iter()
        .filter(|a| a["url"].as_str().is_some_and(|u| u.contains("category=")))
        .map(|a| a["label"].clone())
        .collect();

    json!({"id":id,"source":"cursor_marketplace","title":metadata.get("og:title"),"description":metadata.get("og:description"),"images":images,"categories":categories,"endpoints":[],"metadata_url":url,"raw":{"meta":metadata,"links":links,"structured_data":structured,"page_text":doc.root_element().text().collect::<Vec<_>>().join("\n")},"connection_note":"Only linked JSON MCP manifests are read. Skills, hooks and commands are never installed or executed. If no endpoint is published, supply a provider-documented endpoint."})
}

fn cursor_cards(html: &str) -> Result<Vec<Value>, Error> {
    let doc = Html::parse_document(html);
    let mut items = std::collections::BTreeMap::new();
    for a in doc.select(&Selector::parse("a[href]").unwrap()) {
        let href = a.value().attr("href").unwrap_or("");
        let path = href.strip_prefix("https://cursor.com").unwrap_or(href);
        let Some(id) = path.strip_prefix("/marketplace/") else {
            continue;
        };
        if !safe_path(id) || id.contains('/') {
            continue;
        }
        let title = a
            .text()
            .collect::<Vec<_>>()
            .join(" ")
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ");
        let icons: Vec<_> = a
            .select(&Selector::parse("img[src]").unwrap())
            .map(|e| json!({"src":e.value().attr("src"),"alt":e.value().attr("alt")}))
            .collect();
        if !title.is_empty() {
            items.insert(id.to_string(),json!({"id":id,"source":"cursor_marketplace","title":title,"icons":icons,"metadata_url":format!("https://cursor.com/marketplace/{id}"),"requires_details":true,"raw":{"href":href}}));
        }
    }
    if items.is_empty() {
        return Err(fail(
            "Cursor marketplace HTML unavailable or changed; use cursor repository or official registry",
        ));
    }
    Ok(items.into_values().collect())
}

fn github_mcp_raw(value: &str) -> Option<String> {
    let u = url::Url::parse(value).ok()?;
    if u.scheme() != "https"
        || u.host_str() != Some("github.com")
        || !u.username().is_empty()
        || u.password().is_some()
        || u.query().is_some()
    {
        return None;
    }
    let p: Vec<_> = u.path_segments()?.collect();
    if p.len() < 5
        || p[2] != "blob"
        || !p.last()?.ends_with("mcp.json")
        || !p.iter().all(|s| safe_path(s) && !s.contains('/'))
    {
        return None;
    }
    Some(format!(
        "https://raw.githubusercontent.com/{}/{}/{}/{}",
        p[0],
        p[1],
        p[3],
        p[4..].join("/")
    ))
}
fn manifest_endpoints(raw: &Value) -> Vec<Value> {
    let configs = raw.get("mcpServers").unwrap_or(raw);
    configs.as_object().into_iter().flat_map(|m|m.iter()).filter_map(|(name,c)|c["url"].as_str().map(|url|json!({"name":name,"type":if c["type"]=="sse"{"sse"}else{"streamable-http"},"url":url}))).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn preserve_metadata_and_missing_fields() {
        let r = json!({"server":{"name":"io.example/demo","remotes":[{"type":"streamable-http","url":"https://example.com/mcp"}],"_meta":{"unknown":{"future":true}}}});
        let p = official(&r);
        assert_eq!(p["raw"], r);
        assert!(p["icons"].is_null());
        assert!(p["categories"].is_null());
    }
    #[test]
    fn html_catalog_no_fake_entries() {
        assert!(claude_cards("<html>login</html>").is_err());
        let cards = claude_cards(
            "<a href='/connectors/notion'><img src='https://example.com/logo.png'>Notion</a>",
        )
        .unwrap();
        assert_eq!(cards.len(), 1);
        assert_eq!(cards[0]["title"], "Notion");
    }
    #[test]
    fn cursor_html_and_linked_manifests_are_metadata_only() {
        let html = "<a href='/marketplace/notion'><img src='https://example.com/logo.png'>Notion</a><a href='https://evil.test/marketplace/evil'>evil</a>";
        let cards = cursor_cards(html).unwrap();
        assert_eq!(cards.len(), 1);
        assert_eq!(cards[0]["icons"][0]["src"], "https://example.com/logo.png");
        assert!(cursor_cards("<html>sign in</html>").is_err());
        assert_eq!(
            github_mcp_raw("https://github.com/vendor/plugin/blob/abc123/mcp.json").as_deref(),
            Some("https://raw.githubusercontent.com/vendor/plugin/abc123/mcp.json")
        );
        for url in [
            "https://evil.test/vendor/repo/blob/main/mcp.json",
            "https://github.com/vendor/repo/blob/main/run.sh",
            "https://user:pass@github.com/vendor/repo/blob/main/mcp.json",
        ] {
            assert!(github_mcp_raw(url).is_none());
        }
        let raw = json!({"mcpServers":{"remote":{"type":"http","url":"https://example.com/mcp"},"local":{"command":"do-not-execute","args":["anything"]}}});
        let endpoints = manifest_endpoints(&raw);
        assert_eq!(endpoints.len(), 1);
        assert_eq!(endpoints[0]["url"], "https://example.com/mcp");
    }
    #[test]
    fn cursors_cannot_overflow_pagination() {
        assert!(offset(Some(&usize::MAX.to_string())).is_err());
        assert!(offset(Some("-1")).is_err());
        assert_eq!(offset(Some("50")).unwrap(), 50);
    }

    #[test]
    fn reject_paths() {
        for path in [
            "../secret",
            "a/../b",
            "a?token=1",
            "https://evil.test/mcp",
            "a//b",
        ] {
            assert!(!safe_path(path));
        }
    }
}
