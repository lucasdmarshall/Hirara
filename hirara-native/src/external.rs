//! Fixed public APIs. Shared Python transport handles DNS pinning and byte caps.
use crate::{number, text};
use serde_json::{Value, json};

fn plain(value: &Value, cap: usize) -> String {
    let fragment = scraper::Html::parse_fragment(value.as_str().unwrap_or(""));
    fragment
        .root_element()
        .text()
        .collect::<Vec<_>>()
        .join(" ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(cap)
        .collect()
}
fn https(raw: &Value) -> Value {
    raw.as_str()
        .and_then(|s| url::Url::parse(s).ok())
        .filter(|u| u.scheme() == "https" && u.username().is_empty() && u.password().is_none())
        .map(|u| json!(u.as_str()))
        .unwrap_or(Value::Null)
}
fn coordinates(v: &Value) -> Result<(f64, f64), String> {
    let lat = v["latitude"]
        .as_f64()
        .filter(|n| n.is_finite() && (-90.0..=90.0).contains(n))
        .ok_or("latitude must be -90..90")?;
    let lon = v["longitude"]
        .as_f64()
        .filter(|n| n.is_finite() && (-180.0..=180.0).contains(n))
        .ok_or("longitude must be -180..180")?;
    Ok((lat, lon))
}
fn weather_url(v: &Value) -> Result<Value, String> {
    let (lat, lon) = coordinates(v)?;
    let days = number(v, "forecast_days", 3)?;
    if days > 7 {
        return Err("forecast_days must be 1..7".into());
    }
    let imperial = match v.get("units").and_then(Value::as_str).unwrap_or("metric") {
        "metric" => false,
        "imperial" => true,
        _ => return Err("units must be metric or imperial".into()),
    };
    let mut url = url::Url::parse("https://api.open-meteo.com/v1/forecast").unwrap();
    url.query_pairs_mut().append_pair("latitude",&lat.to_string()).append_pair("longitude",&lon.to_string())
        .append_pair("current","temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m,wind_direction_10m")
        .append_pair("daily","weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum")
        .append_pair("forecast_days",&days.to_string()).append_pair("timezone","auto")
        .append_pair("temperature_unit",if imperial {"fahrenheit"} else {"celsius"})
        .append_pair("wind_speed_unit",if imperial {"mph"} else {"kmh"})
        .append_pair("precipitation_unit",if imperial {"inch"} else {"mm"});
    Ok(json!({"url":url.as_str(),"phase":"weather","error":null}))
}

pub fn request(v: &Value) -> Result<Value, String> {
    let provider = text(v, "provider")?;
    if provider == "weather" {
        if number(v, "forecast_days", 3)? > 7
            || !matches!(
                v.get("units").and_then(Value::as_str).unwrap_or("metric"),
                "metric" | "imperial"
            )
        {
            return Err("forecast_days must be 1..7 and units metric or imperial".into());
        }
        if let Some(location) = v
            .get("location")
            .and_then(Value::as_str)
            .filter(|s| !s.trim().is_empty())
        {
            if !v["latitude"].is_null() || !v["longitude"].is_null() {
                return Err("provide location OR coordinates, not both".into());
            }
            if location.len() > 200 {
                return Err("location exceeds 200 bytes".into());
            }
            let mut url =
                url::Url::parse("https://geocoding-api.open-meteo.com/v1/search").unwrap();
            url.query_pairs_mut()
                .append_pair("name", location)
                .append_pair("count", "5")
                .append_pair("language", "en")
                .append_pair("format", "json");
            return Ok(json!({"url":url.as_str(),"phase":"geocode","error":null}));
        }
        return weather_url(v);
    }
    let mut url = match provider {
        "books" => url::Url::parse("https://www.googleapis.com/books/v1/volumes").unwrap(),
        "stackexchange" => {
            url::Url::parse("https://api.stackexchange.com/2.3/search/advanced").unwrap()
        }
        "stackexchange_answers" => {
            let ids = v["ids"].as_array().ok_or("answer IDs must be an array")?;
            if ids.is_empty() || ids.len() > 20 {
                return Err("expected 1..20 answer IDs".into());
            }
            let ids: Vec<_> = ids
                .iter()
                .map(|id| {
                    id.as_u64()
                        .filter(|n| *n > 0)
                        .map(|n| n.to_string())
                        .ok_or("invalid answer id")
                })
                .collect::<Result<_, _>>()?;
            url::Url::parse(&format!(
                "https://api.stackexchange.com/2.3/answers/{}",
                ids.join(";")
            ))
            .unwrap()
        }
        _ => return Err("unknown public API provider".into()),
    };
    let limit = number(v, "max_results", 5)?;
    if limit > 20 {
        return Err("max_results must be 1..20".into());
    }
    if provider != "stackexchange_answers" {
        let query = text(v, "query")?.trim();
        if query.is_empty() || query.len() > 1000 {
            return Err("query must contain 1..1000 bytes".into());
        }
        url.query_pairs_mut().append_pair("q", query);
    }
    if provider == "books" {
        let start = v.get("start").and_then(Value::as_u64).unwrap_or(0);
        if start > 1000 {
            return Err("start must be 0..1000".into());
        }
        url.query_pairs_mut()
            .append_pair("maxResults", &limit.to_string())
            .append_pair("startIndex", &start.to_string())
            .append_pair("printType", "books");
    } else {
        let site = v
            .get("site")
            .and_then(Value::as_str)
            .unwrap_or("stackoverflow");
        if site.is_empty()
            || site.len() > 64
            || !site
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b, b'.' | b'-'))
        {
            return Err("invalid Stack Exchange site identifier".into());
        }
        let page = number(v, "page", 1)?;
        if page > 100 {
            return Err("page must be 1..100".into());
        }
        url.query_pairs_mut()
            .append_pair("site", site)
            .append_pair("filter", "withbody")
            .append_pair("pagesize", &limit.to_string())
            .append_pair("page", &page.to_string());
        if provider == "stackexchange" {
            url.query_pairs_mut()
                .append_pair("order", "desc")
                .append_pair("sort", "relevance");
        }
    }
    Ok(json!({"url":url.as_str(),"error":null}))
}

pub fn parse(v: &Value) -> Result<Value, String> {
    let body = text(v, "body")?;
    if body.len() > 2_000_000 {
        return Err("provider response exceeds 2 MB".into());
    }
    let data: Value = serde_json::from_str(body).map_err(|_| "invalid provider JSON")?;
    if data.get("error").is_some() && data["error"] != false || data.get("error_id").is_some() {
        return Err(format!(
            "provider rejected request: {}",
            plain(
                &data
                    .get("error_message")
                    .or_else(|| data.get("reason"))
                    .or_else(|| data.get("error").and_then(|e| e.get("message")))
                    .or_else(|| data.get("error"))
                    .cloned()
                    .unwrap_or(json!("provider error")),
                500
            )
        ));
    }
    let limit = number(v, "max_results", 5)?.min(20) as usize;
    match text(v, "provider")? {
        "books" => {
            let mut results = Vec::new();
            if let Some(items) = data.get("items") {
                for item in items
                    .as_array()
                    .ok_or("invalid Google Books items")?
                    .iter()
                    .take(limit)
                {
                    let info = &item["volumeInfo"];
                    let id = item["id"].as_str().ok_or("book result has no id")?;
                    let mut url = url::Url::parse("https://books.google.com/books").unwrap();
                    url.query_pairs_mut().append_pair("id", id);
                    results.push(json!({"id":id,"title":plain(&info["title"],1000),"authors":info["authors"],"publisher":info["publisher"],"published":info["publishedDate"],"description":plain(&info["description"],12000),"identifiers":info["industryIdentifiers"],"page_count":info["pageCount"],"language":info["language"],"url":url.as_str()}));
                }
            }
            if !data["totalItems"].is_number() {
                return Err("Google Books response missing totalItems".into());
            }
            Ok(json!({"results":results,"total":data["totalItems"],"error":null}))
        }
        "stackexchange" | "stackexchange_answers" => {
            let items = data["items"]
                .as_array()
                .ok_or("Stack Exchange response missing items")?;
            let mut results = Vec::new();
            for item in items.iter().take(limit) {
                let body = plain(&item["body"], usize::MAX);
                let body_truncated = body.chars().count() > 12000;
                let fragment = scraper::Html::parse_fragment(item["body"].as_str().unwrap_or(""));
                let selector = scraper::Selector::parse("pre").unwrap();
                let blocks: Vec<_> = fragment
                    .select(&selector)
                    .map(|node| node.text().collect::<String>())
                    .collect();
                let code_truncated =
                    blocks.len() > 5 || blocks.iter().any(|s| s.chars().count() > 2000);
                let code: Vec<String> = blocks
                    .iter()
                    .take(5)
                    .map(|s| s.chars().take(2000).collect())
                    .collect();
                results.push(json!({"question_id":item["question_id"],"answer_id":item["answer_id"],"title":plain(&item["title"],1000),"body":body.chars().take(12000).collect::<String>(),"body_truncated":body_truncated,"code_blocks":code,"code_blocks_truncated":code_truncated,"score":item["score"],"is_answered":item["is_answered"],"is_accepted":item["is_accepted"],"accepted_answer_id":item["accepted_answer_id"],"tags":item["tags"],"url":https(&item["link"]),"author":plain(&item["owner"]["display_name"],200)}));
            }
            Ok(
                json!({"results":results,"has_more":data["has_more"],"quota_remaining":data["quota_remaining"],"backoff":data["backoff"],"error":null}),
            )
        }
        "weather_geocode" => {
            let places = data["results"]
                .as_array()
                .filter(|r| !r.is_empty())
                .ok_or("location not found; provide latitude/longitude to disambiguate")?;
            let place = &places[0];
            coordinates(place)?;
            let mut next = v.clone();
            next["latitude"] = place["latitude"].clone();
            next["longitude"] = place["longitude"].clone();
            let mut result = weather_url(&next)?;
            result["location"] = json!({"name":place["name"],"country":place["country"],"admin1":place["admin1"],"latitude":place["latitude"],"longitude":place["longitude"]});
            result["alternatives"]=json!(places.iter().skip(1).take(4).map(|p|json!({"name":p["name"],"country":p["country"],"admin1":p["admin1"],"latitude":p["latitude"],"longitude":p["longitude"]})).collect::<Vec<_>>());
            Ok(result)
        }
        "weather" => {
            if !data["current"].is_object() || !data["daily"].is_object() {
                return Err("weather response missing current/daily data".into());
            }
            Ok(
                json!({"latitude":data["latitude"],"longitude":data["longitude"],"timezone":data["timezone"],"utc_offset_seconds":data["utc_offset_seconds"],"current":data["current"],"current_units":data["current_units"],"daily":data["daily"],"daily_units":data["daily_units"],"attribution":"Weather data by Open-Meteo.com; location data by GeoNames", "error":null}),
            )
        }
        _ => Err("unknown public API response".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fixed_urls_and_html() {
        let result =
            request(&json!({"provider":"books","query":"x&url=http://localhost"})).unwrap();
        let url = url::Url::parse(result["url"].as_str().unwrap()).unwrap();
        assert_eq!(url.host_str(), Some("www.googleapis.com"));
        assert_eq!(url.query_pairs().count(), 4);
        let parsed=parse(&json!({"provider":"books","body":json!({"totalItems":1,"items":[{"id":"a/b","volumeInfo":{"title":"A &amp; B","description":"<b>Book</b>"}}]}).to_string()})).unwrap();
        assert_eq!(parsed["results"][0]["title"], "A & B");
        assert_eq!(parsed["results"][0]["description"], "Book");
        assert!(request(&json!({"provider":"weather","latitude":91,"longitude":0})).is_err());
    }
}
