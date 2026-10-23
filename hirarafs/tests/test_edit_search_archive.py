"""file_edit, file_search, file_list, archive_list and archive_extract."""

from __future__ import annotations

import io
import os
import tarfile
import zipfile

import pytest

from hirarafs.config import FsConfig
from hirarafs.tools import Toolset


@pytest.fixture
def root(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def main():\n    return 1\n\nprint(main())\n")
    (tmp_path / "src" / "util.py").write_text("X = 1\nY = 2\nX = 3\n")
    (tmp_path / "README.md").write_text("# Demo\nTODO: write docs\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("TODO hidden in deps\n")
    (tmp_path / ".hidden").write_text("TODO secret\n")
    (tmp_path / "blob.bin").write_bytes(b"\0\1TODO\2")
    return tmp_path


@pytest.fixture
def ts(root):
    return Toolset(FsConfig(roots=(str(root),), allow_any_path=False))


# --- file_edit ---------------------------------------------------------------

async def test_edit_replaces_unique_string_with_diff(ts, root):
    r = await ts.file_edit(path=str(root / "src/app.py"), old_string="return 1",
                           new_string="return 2")
    assert r["error"] is None
    assert r["replacements"] == 1 and r["edits"][0]["first_line"] == 2
    assert "-    return 1" in r["diff"] and "+    return 2" in r["diff"]
    assert (root / "src/app.py").read_text() == "def main():\n    return 2\n\nprint(main())\n"


async def test_edit_refuses_ambiguous_and_missing(ts, root):
    before = (root / "src/util.py").read_text()
    r = await ts.file_edit(path=str(root / "src/util.py"), old_string="X =", new_string="Z =")
    assert "occurs 2 times" in r["error"]
    r = await ts.file_edit(path=str(root / "src/util.py"), old_string="nope", new_string="x")
    assert "not found" in r["error"]
    assert (root / "src/util.py").read_text() == before


async def test_edit_replace_all_and_atomic_batch(ts, root):
    p = str(root / "src/util.py")
    r = await ts.file_edit(path=p, old_string="X =", new_string="Z =", replace_all=True)
    assert r["replacements"] == 2
    before = (root / "src/util.py").read_text()
    r = await ts.file_edit(path=p, edits=[{"old": "Y = 2", "new": "Y = 9"},
                                          {"old": "missing", "new": "x"}])
    assert "edits[1]" in r["error"]
    assert (root / "src/util.py").read_text() == before  # first edit not applied


async def test_edit_dry_run_and_crlf(ts, root):
    p = root / "win.txt"
    p.write_bytes(b"a\r\nb\r\nc\r\n")
    r = await ts.file_edit(path=str(p), old_string="a\nb", new_string="A\nB", dry_run=True)
    assert r["error"] is None and r["dry_run"] is True
    assert p.read_bytes() == b"a\r\nb\r\nc\r\n"
    await ts.file_edit(path=str(p), old_string="a\nb", new_string="A\nB")
    assert p.read_bytes() == b"A\r\nB\r\nc\r\n"


async def test_edit_keeps_mode_and_respects_gates(ts, root, tmp_path_factory):
    p = root / "run.sh"
    p.write_text("echo hi\n")
    os.chmod(p, 0o755)
    await ts.file_edit(path=str(p), old_string="hi", new_string="bye")
    assert os.stat(p).st_mode & 0o777 == 0o755
    outside = tmp_path_factory.mktemp("outside") / "x.txt"
    outside.write_text("hello")
    r = await ts.file_edit(path=str(outside), old_string="hello", new_string="x")
    assert "outside allowed roots" in r["error"]
    ro = Toolset(FsConfig(roots=(str(root),), allow_any_path=False, allow_write=False))
    r = await ro.file_edit(path=str(p), old_string="bye", new_string="x")
    assert "disabled" in r["error"]
    r = await ts.file_edit(path=str(root / "blob.bin"), old_string="TODO", new_string="x")
    assert "binary" in r["error"]
    (root / "latin.txt").write_bytes("café".encode("latin-1"))
    r = await ts.file_edit(path=str(root / "latin.txt"), old_string="caf", new_string="x")
    assert "not utf-8" in r["error"]


# --- file_search / file_list ---------------------------------------------------

async def test_search_skips_noise(ts, root):
    r = await ts.file_search(pattern="todo")
    assert r["error"] is None
    assert [(m["path"], m["line"]) for m in r["matches"]] == [("README.md", 2)]
    r = await ts.file_search(pattern="todo", include_hidden=True)
    assert {m["path"] for m in r["matches"]} == {"README.md", ".hidden"}


async def test_search_glob_context_and_literal(ts, root):
    r = await ts.file_search(pattern="X = ", glob="*.py", context=1, regex=False)
    assert [m["line"] for m in r["matches"]] == [1, 3]
    assert r["matches"][1]["before"] == ["Y = 2"]
    r = await ts.file_search(pattern="(", regex=True)
    assert "invalid regex" in r["error"]
    r = await ts.file_search(pattern="main", path=str(root / "src/app.py"))
    assert r["count"] == 2


async def test_list_flat_recursive_and_pattern(ts, root):
    r = await ts.file_list()
    names = [e["path"] for e in r["entries"]]
    assert names == ["README.md", "blob.bin", "node_modules/", "src/"]
    r = await ts.file_list(recursive=True, pattern="*.py")
    assert [e["path"] for e in r["entries"]] == ["src/app.py", "src/util.py"]
    assert all(e["size"] > 0 for e in r["entries"])


async def test_list_does_not_follow_links_out(ts, root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere")
    (outside / "secret.txt").write_text("x")
    (root / "link").symlink_to(outside)
    r = await ts.file_list(recursive=True)
    assert not any("secret" in e["path"] or e["path"].startswith("link") for e in r["entries"])
    r = await ts.file_list(path=str(outside))
    assert "outside allowed roots" in r["error"]


# --- archives ------------------------------------------------------------------

def _zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return path


async def test_archive_list_flags_unsafe(ts, root):
    _zip(root / "a.zip", [("ok.txt", "hi"), ("../evil.txt", "x"), ("/abs.txt", "y")])
    r = await ts.archive_list(path=str(root / "a.zip"))
    assert r["error"] is None and r["format"] == "zip" and r["count"] == 3
    assert r["unsafe_entries"] == 2


async def test_extract_zip_blocks_slip(ts, root):
    _zip(root / "a.zip", [("dir/ok.txt", "hi"), ("../evil.txt", "x"), ("/abs.txt", "y")])
    out = root / "out"
    out.mkdir()
    r = await ts.archive_extract(path=str(root / "a.zip"), dest=str(out))
    assert r["error"] is None
    assert (out / "dir/ok.txt").read_text() == "hi"
    assert not (root / "evil.txt").exists()
    assert {s["reason"] for s in r["skipped"]} == {"path escapes the destination (..)", "absolute path"}
    r = await ts.archive_extract(path=str(root / "a.zip"), dest=str(out))
    assert any("exists" in s["reason"] for s in r["skipped"])


async def test_extract_tar_skips_links_and_symlinked_dirs(ts, root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("target")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = str(outside)
        tf.addfile(info)
        data = b"pwned"
        info = tarfile.TarInfo("trap/new/file.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
        info = tarfile.TarInfo("good.txt")
        info.size = 2
        tf.addfile(info, io.BytesIO(b"ok"))
    (root / "a.tgz").write_bytes(buf.getvalue())
    out = root / "out"
    out.mkdir()
    (out / "trap").symlink_to(outside)  # pre-existing symlinked dir in dest
    r = await ts.archive_extract(path=str(root / "a.tgz"), dest=str(out))
    assert r["error"] is None
    assert (out / "good.txt").read_text() == "ok"
    assert list(outside.iterdir()) == []  # nothing created through the link
    reasons = {s["name"]: s["reason"] for s in r["skipped"]}
    assert reasons["link"].startswith("symlink")
    assert "symlink" in reasons["trap/new/file.txt"]


async def test_extract_stops_bombs(root):
    _zip(root / "bomb.zip", [("big.bin", b"\0" * 2_000_000)])
    out = root / "out"
    out.mkdir()
    small = Toolset(FsConfig(roots=(str(root),), allow_any_path=False, max_extract_bytes=100_000))
    r = await small.archive_extract(path=str(root / "bomb.zip"), dest=str(out))
    assert "CFS_MAX_EXTRACT_BYTES" in r["error"]
    assert list(out.iterdir()) == []


async def test_extract_members_and_not_archive(ts, root):
    _zip(root / "a.zip", [("one.txt", "1"), ("two.txt", "2")])
    out = root / "out"
    out.mkdir()
    r = await ts.archive_extract(path=str(root / "a.zip"), dest=str(out), members=["two.txt", "nine"])
    assert [e["name"] for e in r["extracted"]] == ["two.txt"]
    assert {"name": "nine", "reason": "not in archive"} in r["skipped"]
    r = await ts.archive_list(path=str(root / "README.md"))
    assert "not a zip or tar" in r["error"]
