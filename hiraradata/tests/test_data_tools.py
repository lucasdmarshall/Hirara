"""data_profile, chart_render and diagram_render."""

from __future__ import annotations

import asyncio
import base64
import json
import shutil

import openpyxl
import pytest

from hiraradata import tools
from hiraradata.config import DataConfig
from hiraradata.diagrams import mermaid_to_dot
from hiraradata.profile import classify
from hiraradata.tools import Toolset

CSV = (
    "id,name,age,joined,score,zip\n"
    "1,Ada,36,2026-01-02,9.5,02134\n"
    "2,Bob,,2026-02-03,7,10001\n"
    "3,Cy,41,2026-03-04,8.25,02134\n"
    "3,Cy,41,2026-03-04,8.25,02134\n"
    "4,Dee,250,2025-12-31,NA,94105\n"
)


@pytest.fixture
def ts():
    return Toolset(DataConfig())


def col(r, name):
    return next(c for c in r["column_profiles"] if c["name"] == name)


def test_classify():
    assert classify("12")[0] == "integer"
    assert classify("02134")[0] == "code"  # leading zero: an identifier, not a number
    assert classify("1e3")[:2] == ("float", 1000.0)
    assert classify("2026-01-02T10:00:00Z")[0] == "date"
    assert classify("NA")[0] == "null" and classify("true")[0] == "boolean"
    assert classify(None)[0] == "null" and classify(3)[0] == "integer"


async def test_profile_csv_file(ts, tmp_path):
    p = tmp_path / "people.csv"
    p.write_text(CSV)
    r = await ts.data_profile(file_path=str(p))
    assert r["error"] is None
    assert (r["rows"], r["columns"], r["duplicate_rows"]) == (5, 6, 1)
    assert col(r, "age")["type"] == "integer" and col(r, "age")["nulls"] == 1
    assert col(r, "age")["numeric"]["max"] == 250
    assert col(r, "zip")["type"] == "string" and "numeric" not in col(r, "zip")
    assert "leading zeros" in col(r, "zip")["note"]
    assert col(r, "joined")["date_range"] == ["2025-12-31", "2026-03-04"]
    assert col(r, "score")["type"] == "float"
    assert any("duplicate" in w for w in r["warnings"])
    assert r["sample_rows"][0]["name"] == "Ada"
    assert r["text"].startswith("5 rows x 6 columns (csv)")


async def test_profile_inline_records_and_json(ts):
    r = await ts.data_profile(data=[{"a": 1, "b": {"c": "x"}}, {"a": 2, "b": {"c": "y"}}])
    assert r["source"] == "inline" and [c["name"] for c in r["column_profiles"]] == ["a", "b.c"]
    r = await ts.data_profile(data=json.dumps({"items": [{"k": 1}, {"k": 1}]}))
    assert col(r, "k")["distinct"] == 1
    assert any("constant" in w for w in r["warnings"])


async def test_profile_jsonl_semicolon_xlsx(ts, tmp_path):
    (tmp_path / "x.jsonl").write_text('{"v": 1}\n{"v": 2}\n\n{"v": "oops"}\n')
    r = await ts.data_profile(file_path=str(tmp_path / "x.jsonl"))
    assert r["format"] == "jsonl" and "mixed" in col(r, "v")["type"]
    r = await ts.data_profile(data="a;b\n1;x\n2;y\n")
    assert r["delimiter"] == ";" and r["columns"] == 2
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["region", "amount"])
    for i in range(30):
        ws.append(["north" if i % 2 else "south", i * 10])
    wb.create_sheet("Other")
    wb.save(tmp_path / "s.xlsx")
    r = await ts.data_profile(file_base64=base64.b64encode((tmp_path / "s.xlsx").read_bytes()).decode(),
                              filename="s.xlsx")
    assert r["format"] == "xlsx" and r["sheet"] == "Sales" and r["sheets"] == ["Sales", "Other"]
    assert col(r, "amount")["numeric"]["median"] == 145
    r = await ts.data_profile(file_path=str(tmp_path / "s.xlsx"), sheet="Nope")
    assert "no sheet" in r["error"]


async def test_profile_limits_and_errors(ts, tmp_path):
    big = "n\n" + "\n".join(str(i) for i in range(1000)) + "\n"
    r = await ts.data_profile(data=big, max_rows=100)
    assert r["rows"] == 100 and r["rows_total"] == 1000 and r["truncated"]
    r = await ts.data_profile(data="[not json")
    assert r["error"] is None or "JSON" in r["error"]  # falls back to CSV text
    r = await ts.data_profile()
    assert "provide exactly one" in r["error"]
    (tmp_path / "e.csv").write_text("")
    r = await ts.data_profile(file_path=str(tmp_path / "e.csv"))
    assert "empty" in r["error"]


async def test_chart_png_svg_and_description(ts, tmp_path):
    r = await ts.chart_render(type="line", x=[1, 2, 3, 4], series=[{"name": "y", "values": [1, 4, None, 2]}],
                              title="T", output_path=str(tmp_path / "c.png"))
    assert r["error"] is None
    assert base64.b64decode(r["image_base64"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert (tmp_path / "c.png").stat().st_size == r["bytes"]
    assert "max 4 at 2" in r["text"]
    r = await ts.chart_render(type="bar", records=[{"q": "Q1", "a": 1, "b": 2}, {"q": "Q2", "a": 3, "b": 1}],
                              x_field="q", format="svg", stacked=True)
    assert r["svg"].lstrip().startswith(("<?xml", "<svg"))
    for kind in ("barh", "scatter", "area", "pie", "histogram", "box"):
        r = await ts.chart_render(type=kind, x=["a", "b", "c"], series=[{"name": "s", "values": [1, 2, 3]}])
        assert r["error"] is None, (kind, r["error"])


async def test_chart_errors(ts):
    assert "type must be" in (await ts.chart_render(type="radar", series=[{"values": [1]}]))["error"]
    assert "non-number" in (await ts.chart_render(type="line", series=[{"name": "s", "values": ["x"]}]))["error"]
    assert "provide series" in (await ts.chart_render(type="line"))["error"]


def test_mermaid_translation():
    dot = mermaid_to_dot("graph TD\nA[One] --> B & C\nB -- go --> D{Ok?}\nC === D\n")
    assert '"A" -> "B";' in dot and '"A" -> "C";' in dot
    assert '"B" -> "D" [label="go"];' in dot
    assert '"C" -> "D" [arrowhead=none, penwidth=2.5];' in dot
    assert 'shape=diamond' in dot and "rankdir=TB" in dot


needs_dot = pytest.mark.skipif(shutil.which("dot") is None, reason="graphviz not installed")


@needs_dot
async def test_diagram_dot_and_mermaid(ts):
    r = await ts.diagram_render(source="digraph { a -> b -> c }", format="svg")
    assert r["error"] is None and "<svg" in r["svg"] and r["dot"] is None
    r = await ts.diagram_render(source="flowchart LR\n A((x)) --> B([y])")
    assert r["error"] is None and r["dot"].startswith("digraph G")
    assert base64.b64decode(r["image_base64"])[:4] == b"\x89PNG"


async def test_diagram_refuses_file_reads_and_bad_input(ts):
    for src in ('digraph { a [image="/etc/passwd"] }', 'digraph { a [shapefile = "/x"] }',
                'graph { fontpath="/etc" }'):
        assert "not allowed" in (await ts.diagram_render(source=src))["error"]
    assert "only Mermaid flowcharts" in (await ts.diagram_render(source="sequenceDiagram\nA->>B: hi"))["error"]
    if shutil.which("dot"):
        assert "diagram error" in (await ts.diagram_render(source="digraph { a -> }"))["error"]


def test_contract_and_frontends():
    assert tools.TOOL_NAMES == ("data_profile", "chart_render", "diagram_render")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from hiraradata.service import app

    c = TestClient(app)
    assert [t["name"] for t in c.get("/schemas").json()["tools"]] == list(tools.TOOL_NAMES)
    r = c.post("/data_profile/upload", files={"file": ("a.csv", CSV.encode())}).json()
    assert r["rows"] == 5
    mcp = pytest.importorskip("mcp")
    del mcp
    from hiraradata import mcp_server

    listed = asyncio.run(mcp_server.server.list_tools())
    assert sorted(t.name for t in listed) == sorted(tools.TOOL_NAMES)
