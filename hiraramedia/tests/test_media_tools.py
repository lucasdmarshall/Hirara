"""video_profile, image_compare, barcode_read and qr_generate."""

from __future__ import annotations

import asyncio
import base64
import io
import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw

from hiraramedia import tools
from hiraramedia.config import MediaConfig
from hiraramedia.tools import Toolset
from hiraramedia.video import pick_times

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")


@pytest.fixture
def ts():
    return Toolset(MediaConfig())


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """red 3s | test pattern 3s | black 2s | frozen gradient 3s | blue 3s, with a tone."""
    out = tmp_path_factory.mktemp("v") / "clip.mp4"
    graph = (
        "color=c=red:s=320x240:r=25:d=3[a];"
        "testsrc=s=320x240:r=25:d=3[b];"
        "color=c=black:s=320x240:r=25:d=2[c];"
        "color=c=green:s=320x240:r=25:d=3[d];"
        "color=c=blue:s=320x240:r=25:d=3[e];"
        "[a][b][c][d][e]concat=n=5:v=1:a=0[v]"
    )
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex", graph,
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=14",
                    "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(out)], check=True)
    return out


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_pick_times():
    filled = pick_times(10.0, [], 4)  # no cuts: spread across the clip
    assert len(filled) == 4 and filled[0] == 0.5
    assert min(b - a for a, b in zip(filled, filled[1:])) >= 2.0
    times = pick_times(100.0, [float(i) for i in range(1, 90)], 5)
    assert len(times) == 5 and times == sorted(times)


async def test_video_profile_scenes_black_frames_and_sheet(ts, clip, tmp_path):
    r = await ts.video_profile(file_path=str(clip), max_keyframes=6, output_dir=str(tmp_path),
                               include_frames=True)
    assert r["error"] is None, r["error"]
    info = r["info"]
    assert (info["width"], info["height"], info["has_audio"]) == (320, 240, True)
    assert abs(info["duration"] - 14) < 0.3
    cuts = r["scene_cuts"]
    for expected in (3.0, 6.0, 11.0):
        assert any(abs(c - expected) <= 0.5 for c in cuts), (expected, cuts)
    assert any(abs(b["start"] - 6.0) < 0.5 for b in r["black_segments"])
    assert any(f["start"] >= 8.0 for f in r["frozen_segments"])
    assert 1 <= len(r["keyframes"]) <= 6
    assert all(k["image_base64"] and k["path"] for k in r["keyframes"])
    sheet = Image.open(io.BytesIO(base64.b64decode(r["contact_sheet_base64"])))
    assert sheet.format == "JPEG" and sheet.size[0] > 240
    assert (tmp_path / "contact_sheet.jpg").exists()
    assert "shot" in r["text"]


async def test_video_errors(ts, tmp_path):
    p = tmp_path / "x.mp4"
    p.write_bytes(b"not a video")
    assert "not a readable video" in (await ts.video_profile(file_path=str(p)))["error"]
    assert "unexpected" in (await ts.video_profile(path="x"))["error"]


async def test_image_compare_finds_and_places_changes(ts, tmp_path):
    a = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(a).rectangle([20, 20, 120, 60], fill="navy")
    b = a.copy()
    d = ImageDraw.Draw(b)
    d.rectangle([300, 20, 380, 50], fill="red")      # new badge, top right
    d.rectangle([150, 250, 250, 280], fill="green")  # new button, bottom center
    (tmp_path / "a.png").write_bytes(_png(a))
    (tmp_path / "b.png").write_bytes(_png(b))
    r = await ts.image_compare(a_path=str(tmp_path / "a.png"), b_path=str(tmp_path / "b.png"),
                               output_path=str(tmp_path / "diff.png"))
    assert r["error"] is None and r["identical"] is False
    assert r["region_count"] == 2
    positions = {reg["position"] for reg in r["regions"]}
    assert positions == {"top right", "bottom center"}
    top_right = next(reg for reg in r["regions"] if reg["position"] == "top right")
    assert (top_right["x"], top_right["y"], top_right["width"], top_right["height"]) == (300, 20, 81, 31)
    assert (tmp_path / "diff.png").exists() and r["diff_image_base64"]


async def test_image_compare_identical_ignore_and_sizes(ts, tmp_path):
    a = Image.new("RGB", (100, 80), "white")
    b = a.copy()
    ImageDraw.Draw(b).rectangle([5, 5, 30, 20], fill="black")
    (tmp_path / "a.png").write_bytes(_png(a))
    (tmp_path / "b.png").write_bytes(_png(b))
    same = await ts.image_compare(a_path=str(tmp_path / "a.png"), b_path=str(tmp_path / "a.png"))
    assert same["identical"] is True and same["text"] == "identical"
    ignored = await ts.image_compare(a_path=str(tmp_path / "a.png"), b_path=str(tmp_path / "b.png"),
                                     ignore=[[0, 0, 40, 30]])
    assert ignored["changed_pixels"] == 0
    (tmp_path / "c.png").write_bytes(_png(Image.new("RGB", (50, 40), "white")))
    r = await ts.image_compare(a_path=str(tmp_path / "a.png"), b_path=str(tmp_path / "c.png"))
    assert "resized" in r["size_note"]
    r = await ts.image_compare(a_path=str(tmp_path / "a.png"), b_path=str(tmp_path / "c.png"),
                               resize=False)
    assert "sizes differ" in r["error"]


def _zbar_available() -> bool:
    try:
        from pyzbar import pyzbar  # noqa: F401  — also loads the zbar shared library
    except (ImportError, OSError):
        return False
    return True


needs_zbar = pytest.mark.skipif(not _zbar_available(), reason="zbar not installed")


@needs_zbar
async def test_qr_round_trip(ts, tmp_path):
    out = tmp_path / "q.png"
    g = await ts.qr_generate(data="https://example.com/hello?x=1", output_path=str(out))
    assert g["error"] is None and g["kind"] == "url" and out.exists()
    # Place it on a larger canvas, the way it would appear in a photo.
    canvas = Image.new("RGB", (600, 400), "white")
    canvas.paste(Image.open(out), (200, 80))
    (tmp_path / "photo.png").write_bytes(_png(canvas))
    r = await ts.barcode_read(file_path=str(tmp_path / "photo.png"))
    assert r["error"] is None and r["count"] == 1
    code = r["codes"][0]
    assert code["type"] == "QRCODE" and code["data"] == "https://example.com/hello?x=1"
    assert code["kind"] == "url" and code["rect"]["x"] >= 200


async def test_qr_svg_and_errors(ts, tmp_path):
    r = await ts.qr_generate(data="WIFI:T:WPA;S:home;P:pw;;", format="svg", error_correction="H")
    assert r["svg"].lstrip().startswith("<?xml") or "<svg" in r["svg"]
    assert r["kind"] == "wifi"
    assert "error_correction" in (await ts.qr_generate(data="x", error_correction="Z"))["error"]
    assert "required" in (await ts.qr_generate(data=""))["error"]
    blank = tmp_path / "blank.png"
    blank.write_bytes(_png(Image.new("RGB", (50, 50), "white")))
    r = await ts.barcode_read(file_path=str(blank))
    assert r["count"] == 0 and r["text"] == "no barcode or QR code found"


def test_contract_and_frontends():
    assert tools.TOOL_NAMES == ("video_profile", "image_compare", "barcode_read", "qr_generate")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from hiraramedia.service import app

    c = TestClient(app)
    assert [t["name"] for t in c.get("/schemas").json()["tools"]] == list(tools.TOOL_NAMES)
    assert c.post("/qr_generate", json={"data": "hi"}).json()["error"] is None
    pytest.importorskip("mcp")
    from hiraramedia import mcp_server

    listed = asyncio.run(mcp_server.server.list_tools())
    assert sorted(t.name for t in listed) == sorted(tools.TOOL_NAMES)
