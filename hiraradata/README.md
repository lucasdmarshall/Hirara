<div align="center">

# HiraraData

**Data profiling, charts and diagrams for AI agents.**

Part of [Hirara](https://github.com/lucasdmarshall/Hirara). Standard library,
NumPy, matplotlib and Graphviz; no ML models, no API keys.

</div>

---

## Tools

| Tool | What it gives an agent |
|---|---|
| **`data_profile`** | One pass over a CSV / TSV / JSON / JSON Lines / Excel / Parquet table: per-column type, nulls, distinct, top values, numeric stats (quantiles, histogram, outliers), string lengths, date ranges; duplicate / ragged rows, constant and empty columns, mixed types and likely IDs as warnings; a few sample rows; a text summary |
| **`chart_render`** | Line, bar, barh, scatter, area, pie, histogram or box chart as PNG or SVG, with a text description of what was plotted |
| **`diagram_render`** | Graphviz DOT, or a Mermaid flowchart (translated to DOT), to PNG or SVG |

A million-row table does not fit in a context window and its first rows lie
about the rest. `data_profile` streams the whole file with bounded memory
(about 55k rows a second on one core) and answers the questions an agent
actually has: what is in each column, what is missing, what looks wrong.

Leading-zero digit columns (zip codes, account numbers) are reported as text,
not numbers.

### Diagram safety

Graphviz attributes that read files on the server (`image`, `shapefile`,
`fontpath`, ...) are refused, and Graphviz runs with `SERVER_NAME` and an empty
`GV_FILE_PATH` so it will not load images even if one slipped through.
Mermaid support covers flowcharts (`graph` / `flowchart`): node shapes,
labelled, dotted and thick edges, `&` fan-out and subgraphs. Use DOT for other
diagram kinds.

---

## Quick start

```bash
apt-get install graphviz                  # only diagram_render needs it
pip install -e ../hirara-core -e ".[service,mcp]"
uvicorn hiraradata.service:app --host 127.0.0.1 --port 9400
```

```bash
curl -X POST localhost:9400/data_profile -H 'content-type: application/json' \
  -d '{"file_path":"/data/sales.csv"}'

curl -X POST localhost:9400/chart_render -H 'content-type: application/json' \
  -d '{"type":"bar","x":["Q1","Q2","Q3"],"series":[{"name":"revenue","values":[12,18,15]}]}'

curl -X POST localhost:9400/diagram_render -H 'content-type: application/json' \
  -d '{"source":"flowchart LR\n A[Order] --> B{Paid?}\n B -->|yes| C[Ship]"}'
```

Upload instead of naming a path: `curl -F file=@sales.xlsx localhost:9400/data_profile/upload`.

MCP: `python -m hiraradata.mcp_server`. Docker: `docker compose up -d --build`.

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `HD_ALLOW_LOCAL_PATH` | `true` | Read files by path. Set `false` on a network-exposed service |
| `HD_ALLOW_OUTPUT_PATH` | `true` | Write `output_path`. Set `false` on a network-exposed service |
| `HD_ALLOW_URL_FETCH` | `false` | Allow `file_url` (through the SSRF guard) |
| `HD_MAX_BYTES` | `524288000` | Largest input file |
| `HD_MAX_ROWS` | `2000000` | Rows profiled per file |
| `HD_MAX_COLUMNS` | `500` | Columns profiled |
| `HD_MAX_POINTS` | `200000` | Points per chart |
| `HD_MAX_SOURCE_CHARS` | `200000` | Longest diagram source |
| `HD_MAX_OUTPUT_BYTES` | `20971520` | Largest image returned inline |
| `HD_TIMEOUT` | `60` | Seconds per Graphviz run |
| `HD_DOT` | `dot` | Graphviz binary |
| `HD_PORT` | `9400` | Compose host port |

Parquet needs `pip install "hiraradata[parquet]"` (included in the image).

---

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
