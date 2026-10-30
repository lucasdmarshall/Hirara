import pytest
from hirarafs.config import FsConfig
from hirarafs.tools import Toolset

pytest.importorskip("hirara_native")

@pytest.mark.asyncio
async def test_lifecycle_and_policies(tmp_path, monkeypatch):
    ts = Toolset(FsConfig(roots=(str(tmp_path),), allow_any_path=False, max_write_bytes=4))
    src, dst = tmp_path/"a", tmp_path/"b"
    src.write_text("hello")
    assert "CFS_MAX_WRITE_BYTES" in (await ts.file_copy(path=str(src), dest=str(dst)))["error"]
    assert not dst.exists()
    src.write_text("hi")
    assert (await ts.file_copy(path=str(src), dest=str(dst)))["bytes_copied"] == 2
    assert (await ts.file_copy(path=str(src), dest=str(dst)))["error"]
    assert (await ts.file_copy(path=str(src), dest=str(dst), overwrite=True))["error"] is None
    assert (await ts.file_move(path=str(src), dest=str(tmp_path/"c")))["moved"]
    assert not src.exists()
    assert (await ts.file_rename(path=str(dst), name="d"))["moved"]
    renamed = tmp_path/"d"
    assert (await ts.file_delete(path=str(renamed)))["deleted"]
    assert not renamed.exists()
    monkeypatch.setenv("HIRARA_ALLOWED_TOOLS", "file_read")
    assert (await ts.file_delete(path=str(tmp_path/"c")))["error"]
    assert (tmp_path/"c").exists()

@pytest.mark.asyncio
async def test_symlinks_and_disabled_writes(tmp_path):
    root, outside = tmp_path/"root", tmp_path/"outside"
    root.mkdir(); outside.mkdir()
    secret = outside/"secret"; secret.write_text("secret")
    ts = Toolset(FsConfig(roots=(str(root),), allow_any_path=False))
    (root/"link").symlink_to(outside, target_is_directory=True)
    assert (await ts.file_delete(path=str(root/"link"/"secret")))["error"]
    assert (await ts.file_delete(path=str(secret)))["error"]
    (root/"leaf").symlink_to(secret)
    assert (await ts.file_copy(path=str(root/"leaf"), dest=str(root/"copy")))["error"]
    assert (await ts.file_rename(path=str(secret), name="../x"))["error"]
    assert secret.read_text() == "secret"
    local = root/"file"; local.write_text("data")
    readonly = Toolset(FsConfig(roots=(str(root),), allow_write=False))
    assert (await readonly.file_delete(path=str(local)))["error"]
    assert local.exists()
