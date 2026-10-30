//! Explicitly configured PostgreSQL/MySQL connections; no model-selected endpoints.
use crate::{number, text};
use futures_util::TryStreamExt;
use serde_json::{Value, json};
use sqlparser::{
    ast::{Query, SetExpr, Statement},
    dialect::{MySqlDialect, PostgreSqlDialect},
    parser::Parser,
};
use sqlx::{Column, Connection, Executor, Row, TypeInfo, ValueRef};
use std::time::Duration;

fn query_exports(query: &Query) -> bool {
    fn body_exports(body: &SetExpr) -> bool {
        match body {
            SetExpr::Select(select) => select.into.is_some(),
            SetExpr::SetOperation { left, right, .. } => body_exports(left) || body_exports(right),
            SetExpr::Query(query) => query_exports(query),
            _ => false,
        }
    }
    body_exports(&query.body)
        || query
            .with
            .as_ref()
            .is_some_and(|w| w.cte_tables.iter().any(|c| query_exports(&c.query)))
}

fn validate(sql: &str, pg: bool, readonly: bool) -> Result<bool, String> {
    // MySQL executes comment bodies which ordinary SQL parsers may discard.
    if !pg && (sql.contains("/*!") || sql.to_ascii_lowercase().contains("/*m!")) {
        return Err("MySQL executable comments are not allowed".into());
    }
    let statements = if pg {
        Parser::parse_sql(&PostgreSqlDialect {}, sql)
    } else {
        Parser::parse_sql(&MySqlDialect {}, sql)
    }
    .map_err(|e| format!("invalid SQL: {e}"))?;
    if statements.len() != 1 {
        return Err("exactly one SQL statement is required".into());
    }
    let is_query = matches!(statements[0], Statement::Query(_));
    if matches!(&statements[0], Statement::Query(query) if query_exports(query)) {
        return Err("SELECT INTO/export is not allowed".into());
    }
    let allowed = if readonly {
        matches!(statements[0], Statement::Query(_))
    } else {
        matches!(
            statements[0],
            Statement::Query(_)
                | Statement::Insert(_)
                | Statement::Update { .. }
                | Statement::Delete(_)
                | Statement::CreateTable(_)
                | Statement::CreateIndex(_)
                | Statement::AlterTable { .. }
                | Statement::Drop { .. }
                | Statement::Truncate { .. }
        )
    };
    if !allowed {
        return Err("statement is not allowed; transaction/session control, COPY and administrative commands are never accepted".into());
    }
    Ok(is_query)
}

// OID 0 lets PostgreSQL infer the type of a SQL NULL from its expression context.
// Binding None<String> would incorrectly force TEXT for nullable numeric columns.
struct SqlNull;
impl sqlx::Type<sqlx::Postgres> for SqlNull {
    fn type_info() -> sqlx::postgres::PgTypeInfo {
        sqlx::postgres::PgTypeInfo::with_oid(sqlx::postgres::types::Oid(0))
    }
}
impl<'q> sqlx::Encode<'q, sqlx::Postgres> for SqlNull {
    fn encode_by_ref(
        &self,
        _: &mut sqlx::postgres::PgArgumentBuffer,
    ) -> Result<sqlx::encode::IsNull, sqlx::error::BoxDynError> {
        Ok(sqlx::encode::IsNull::Yes)
    }
}
impl sqlx::Type<sqlx::MySql> for SqlNull {
    fn type_info() -> sqlx::mysql::MySqlTypeInfo {
        <Option<String> as sqlx::Type<sqlx::MySql>>::type_info()
    }
}
impl<'q> sqlx::Encode<'q, sqlx::MySql> for SqlNull {
    fn encode_by_ref(
        &self,
        _: &mut Vec<u8>,
    ) -> Result<sqlx::encode::IsNull, sqlx::error::BoxDynError> {
        Ok(sqlx::encode::IsNull::Yes)
    }
}

fn sql_error(e: sqlx::Error) -> String {
    match e {
        sqlx::Error::Database(d) => format!(
            "database error {}: {}",
            d.code().unwrap_or_default(),
            d.message()
        ),
        sqlx::Error::ColumnDecode { index, source } => {
            format!("cannot decode column {index}: {source}")
        }
        _ => "database request failed (connection, decoding or driver error)".into(),
    }
}

macro_rules! backend {
    ($query_fn:ident,$schema_fn:ident,$db:ty,$conn:ty,$pg:expr,$extra:ident) => {
        async fn $query_fn(v:&Value)->Result<Value,String> {
            let sql=text(v,"sql")?;
            if sql.chars().count()>number(v,"max_sql_chars",100_000)? as usize {return Err("SQL exceeds CDB_MAX_SQL_CHARS".into());}
            let ro=v["readonly"].as_bool().unwrap_or(true);
            let is_query=validate(sql,$pg,ro)?;
            let cap=number(v,"max_rows",1000)?.min(100_000) as usize;
            let mut conn=<$conn>::connect(text(v,"url")?).await.map_err(|_|"database connection failed; check server configuration and credentials")?;
            // Transaction control belongs to us. User SQL cannot SET/COMMIT its way out.
            if $pg {
                conn.execute(if ro {"BEGIN READ ONLY"} else {"BEGIN"}).await.map_err(sql_error)?;
                let timeout=number(v,"timeout_ms",30_000)?;
                conn.execute(format!("SET LOCAL statement_timeout = {timeout}").as_str()).await.map_err(sql_error)?;
            } else {
                conn.execute(if ro {"SET TRANSACTION READ ONLY"} else {"SET TRANSACTION READ WRITE"}).await.map_err(sql_error)?;
                conn.execute("START TRANSACTION").await.map_err(sql_error)?;
            }
            let mut query=sqlx::query::<$db>(sql);
            let empty=Vec::new();
            let params=match v.get("params") {None|Some(Value::Null)=>&empty,Some(Value::Array(a))=>a,_=>return Err("PostgreSQL/MySQL params must be a positional list".into())};
            for p in params {
                query=match p {
                    Value::Null=>query.bind(SqlNull),
                    Value::Bool(b)=>query.bind(*b),
                    Value::Number(n) if n.is_i64()=>query.bind(n.as_i64().unwrap()),
                    Value::Number(n)=>query.bind(n.as_f64().ok_or("invalid numeric parameter")?),
                    Value::String(s)=>query.bind(s.clone()),
                    _=>return Err("parameters must be JSON scalars".into()),
                };
            }
            let mut columns:Vec<String>=Vec::new();
            let mut rows=Vec::new();let mut bytes=0usize;let mut truncated=false;let mut affected=0u64;
            let max_bytes=number(v,"max_result_bytes",2_000_000)? as usize;
            {
                #[allow(deprecated)]
                let mut stream=query.fetch_many(&mut conn);
                while let Some(item)=stream.try_next().await.map_err(sql_error)? {
                    let row=match item {
                        sqlx::Either::Left(result)=>{affected+=result.rows_affected();continue;},
                        sqlx::Either::Right(row)=>row,
                    };
                    if columns.is_empty() {columns=row.columns().iter().map(|c|c.name().to_owned()).collect();}
                    if rows.len()>=cap {truncated=true;break;}
                    let mut values=Vec::new();
                    for i in 0..row.len() {
                        let raw=row.try_get_raw(i).map_err(sql_error)?;
                        let value=if raw.is_null(){Value::Null}
                        else if let Some(x)=$extra(&row,i) {x}
                        else if let Ok(x)=row.try_get::<bool,_>(i) {json!(x)}
                        else if let Ok(x)=row.try_get::<i64,_>(i){json!(x)}
                        else if let Ok(x)=row.try_get::<i32,_>(i){json!(x)}
                        else if let Ok(x)=row.try_get::<i16,_>(i){json!(x)}
                        else if let Ok(x)=row.try_get::<f64,_>(i){json!(x)}
                        else if let Ok(x)=row.try_get::<f32,_>(i){json!(x)}
                        else if let Ok(x)=row.try_get::<String,_>(i){json!(x)}
                        else if let Ok(x)=row.try_get::<sqlx::types::BigDecimal,_>(i){json!(x.normalized().to_string())}
                        else if let Ok(x)=row.try_get::<sqlx::types::chrono::DateTime<sqlx::types::chrono::Utc>,_>(i){json!(x.to_rfc3339())}
                        else if let Ok(x)=row.try_get::<sqlx::types::chrono::NaiveDateTime,_>(i){json!(x.to_string())}
                        else if let Ok(x)=row.try_get::<sqlx::types::chrono::NaiveDate,_>(i){json!(x.to_string())}
                        else if let Ok(x)=row.try_get::<sqlx::types::chrono::NaiveTime,_>(i){json!(x.to_string())}
                        else if let Ok(x)=row.try_get::<sqlx::types::Json<Value>,_>(i){x.0}
                        else if let Ok(x)=row.try_get::<Vec<u8>,_>(i){use base64::Engine;json!({"__type__":"bytes","base64":base64::engine::general_purpose::STANDARD.encode(x)})}
                        else {return Err(format!("unsupported result type: {}; CAST the column to text",row.columns()[i].type_info().name()));};
                        bytes+=value.to_string().len();values.push(value);
                    }
                    if bytes>max_bytes {truncated=true;break;}
                    rows.push(values);
                }
            }
            // A truncated RETURNING result must not silently roll back successful writes.
            // execute COMMIT also drains any remaining wire results, under the outer deadline.
            conn.execute(if ro {"ROLLBACK"} else {"COMMIT"}).await.map_err(sql_error)?;
            if columns.is_empty() && is_query {
                columns=conn.describe(sql).await.map_err(sql_error)?.columns().iter().map(|c|c.name().to_owned()).collect();
            }
            let _=conn.close().await;
            Ok(json!({"columns":columns,"row_count":if columns.is_empty() {affected as usize} else {rows.len()},"rows":rows,"truncated":truncated,"readonly":ro,"error":null}))
        }

        async fn $schema_fn(v:&Value)->Result<Value,String> {
            let mut conn=<$conn>::connect(text(v,"url")?).await.map_err(|_|"database connection failed; check server configuration and credentials")?;
            let text_value=|row:&<$db as sqlx::Database>::Row,i:usize|->Result<String,String> {
                match row.try_get::<String,_>(i) {
                    Ok(s)=>Ok(s),
                    Err(_)=>String::from_utf8(row.try_get::<Vec<u8>,_>(i).map_err(sql_error)?).map_err(|_|"invalid UTF-8 in schema metadata".into()),
                }
            };
            let cap=number(v,"max_tables",1000)?.min(10_000) as usize;
            let current=if $pg {"current_schema()"} else {"DATABASE()"};
            let views=if v["include_views"]==false {" AND table_type = 'BASE TABLE'"} else {""};
            let objects=sqlx::query::<$db>(&format!("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = {current}{views} ORDER BY table_name LIMIT {}",cap+1)).fetch_all(&mut conn).await.map_err(sql_error)?;
            let mut tables=Vec::new();let mut truncated=false;
            let filter=v.get("table").and_then(Value::as_str).filter(|s|!s.is_empty());
            // Filter in SQL to find a named table even beyond the first page.
            let objects=if let Some(name)=filter {
                sqlx::query::<$db>(&format!("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = {current} AND table_name = {}",if $pg {"$1"} else {"?"})).bind(name).fetch_all(&mut conn).await.map_err(sql_error)?
            } else {objects};
            for row in objects {
                let name=text_value(&row,0)?;
                let kind=text_value(&row,1)?;
                if kind=="VIEW" && v["include_views"]==false {continue;}
                if tables.len()>=cap {truncated=true;break;}
                let marker=if $pg {"$1"} else {"?"};
                let cols=sqlx::query::<$db>(&format!("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema = {current} AND table_name = {marker} ORDER BY ordinal_position")).bind(&name).fetch_all(&mut conn).await.map_err(sql_error)?;
                let mut columns=Vec::new();
                for col in cols {
                    let default=if col.try_get_raw(3).map_err(sql_error)?.is_null() {Value::Null} else {json!(text_value(&col,3)?)};
                    columns.push(json!({"name":text_value(&col,0)?,"type":text_value(&col,1)?,"notnull":text_value(&col,2)?=="NO","pk":0,"default":default}));
                }
                let mut item=json!({"name":name,"type":if kind=="VIEW" {"view"} else {"table"},"columns":columns});
                let keys=sqlx::query::<$db>(&format!("SELECT k.column_name FROM information_schema.table_constraints t JOIN information_schema.key_column_usage k ON t.constraint_name=k.constraint_name AND t.table_schema=k.table_schema AND t.table_name=k.table_name WHERE t.table_schema={current} AND t.table_name={marker} AND t.constraint_type='PRIMARY KEY' ORDER BY k.ordinal_position")).bind(&name).fetch_all(&mut conn).await.map_err(sql_error)?;
                for (position,key) in keys.into_iter().enumerate() {
                    let key_name=text_value(&key,0)?;
                    for col in item["columns"].as_array_mut().unwrap() {if col["name"]==key_name {col["pk"]=json!(position+1);}}
                }
                if v["include_indexes"]==true {
                    let sql=if $pg {"SELECT indexname, indexdef FROM pg_indexes WHERE schemaname=current_schema() AND tablename=$1 ORDER BY indexname"} else {"SELECT DISTINCT index_name, CAST(non_unique AS CHAR) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name=? ORDER BY index_name"};
                    let indexes=sqlx::query::<$db>(sql).bind(&name).fetch_all(&mut conn).await.map_err(sql_error)?;
                    let mut out=Vec::new();
                    for idx in indexes {out.push(json!({"name":text_value(&idx,0)?,"definition":text_value(&idx,1)?}));}
                    item["indexes"]=json!(out);
                }
                if v["include_foreign_keys"]==true {
                    let sql=if $pg {"SELECT k.column_name,c.table_name,c.column_name FROM information_schema.key_column_usage k JOIN information_schema.referential_constraints r ON k.constraint_name=r.constraint_name AND k.constraint_schema=r.constraint_schema JOIN information_schema.key_column_usage c ON c.constraint_name=r.unique_constraint_name AND c.constraint_schema=r.unique_constraint_schema AND c.ordinal_position=k.position_in_unique_constraint WHERE k.table_schema=current_schema() AND k.table_name=$1"} else {"SELECT column_name, referenced_table_name, referenced_column_name FROM information_schema.key_column_usage WHERE table_schema=DATABASE() AND table_name=? AND referenced_table_name IS NOT NULL"};
                    let keys=sqlx::query::<$db>(sql).bind(&name).fetch_all(&mut conn).await.map_err(sql_error)?;
                    let mut out=Vec::new();for key in keys {out.push(json!({"from":text_value(&key,0)?,"table":text_value(&key,1)?,"to":text_value(&key,2)?}));}
                    item["foreign_keys"]=json!(out);
                }
                // PostgreSQL has no SHOW CREATE TABLE equivalent. Avoid fabricated DDL.
                if v["include_sql"]==true {item["sql"]=Value::Null;}
                tables.push(item);
            }
            let _=conn.close().await;
            if filter.is_some() && tables.is_empty() {return Err("table not found".into());}
            Ok(json!({"table_count":tables.len(),"tables":tables,"truncated":truncated,"error":null}))
        }
    }
}

fn extra_pg(_row: &sqlx::postgres::PgRow, _i: usize) -> Option<Value> {
    None
}
fn extra_mysql(row: &sqlx::mysql::MySqlRow, i: usize) -> Option<Value> {
    let kind = row.columns()[i].type_info().name();
    // MySQL bool's decoder accepts every integer type; decode numbers first.
    if kind == "BOOLEAN" {
        return row.try_get::<bool, _>(i).ok().map(|v| json!(v));
    }
    if kind.ends_with("UNSIGNED") {
        return row.try_get::<u64, _>(i).ok().map(|v| json!(v));
    }
    if matches!(
        kind,
        "TINYINT" | "SMALLINT" | "MEDIUMINT" | "INT" | "BIGINT"
    ) {
        return row.try_get::<i64, _>(i).ok().map(|v| json!(v));
    }
    None
}

backend!(
    pg_query,
    pg_schema,
    sqlx::Postgres,
    sqlx::PgConnection,
    true,
    extra_pg
);
backend!(
    mysql_query,
    mysql_schema,
    sqlx::MySql,
    sqlx::MySqlConnection,
    false,
    extra_mysql
);

pub fn run(action: &str, v: &Value) -> Result<Value, String> {
    let url = url::Url::parse(text(v, "url")?).map_err(|_| "invalid database URL")?;
    let scheme = url.scheme();
    if !matches!(scheme, "postgres" | "postgresql" | "mysql") {
        return Err("unsupported database scheme".into());
    }
    let deadline = number(v, "timeout_ms", 30_000)?.min(300_000);
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| e.to_string())?;
    runtime.block_on(async {
        tokio::time::timeout(Duration::from_millis(deadline), async {
            match (scheme, action) {
                ("mysql", "database_query") => mysql_query(v).await,
                ("mysql", _) => mysql_schema(v).await,
                (_, "database_query") => pg_query(v).await,
                _ => pg_schema(v).await,
            }
        })
        .await
        .map_err(|_| "database deadline exceeded; write outcome may be unknown".to_string())?
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn no_policy_escape() {
        for pg in [true, false] {
            assert!(validate("SELECT ';' AS x", pg, true).is_ok());
            for sql in [
                "SELECT 1; DELETE FROM x",
                "COMMIT",
                "SET TRANSACTION READ WRITE",
                "COPY x TO '/tmp/x'",
                "DELETE FROM x",
            ] {
                assert!(validate(sql, pg, true).is_err(), "{sql}");
            }
            assert!(validate("INSERT INTO x VALUES (1)", pg, false).is_ok());
            assert!(validate("SET SESSION TRANSACTION READ WRITE", pg, false).is_err());
        }
        assert!(validate("SELECT 1 /*! INTO OUTFILE '/tmp/export' */", false, true).is_err());
        assert!(validate("SELECT 1 INTO OUTFILE '/tmp/export'", false, true).is_err());
        assert!(validate("SELECT 1 INTO exported", true, true).is_err());
    }
}
