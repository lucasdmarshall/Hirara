import zipfile
from hirarafs.archive import archive_extract
from hirarafs.config import FsConfig
from hirarafs.reader import file_read
from hirarafs.writer import file_write


def test_archive_never_follows_predictable_temporary_symlink(tmp_path):
    root = tmp_path / 'allowed'
    root.mkdir()
    sentinel = tmp_path / 'outside'
    sentinel.write_text('unchanged')
    (root / '.demo.txt.part').symlink_to(sentinel)
    archive = root / 'test.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('demo.txt', 'safe output')
    result = archive_extract(str(archive), dest=str(root),
                             config=FsConfig(roots=(str(root),), allow_any_path=False))
    assert result['extracted_count'] == 1
    assert sentinel.read_text() == 'unchanged'
    assert (root / 'demo.txt').read_text() == 'safe output'
    assert not (root / 'demo.txt').is_symlink()


def test_request_limits_can_only_lower_server_limits(tmp_path):
    root = str(tmp_path)
    cfg = FsConfig(roots=(root,), allow_any_path=False, max_bytes=4, max_write_bytes=4)
    file = tmp_path / 'file.txt'
    file.write_text('123456789')
    assert len(file_read(str(file), max_bytes=99, config=cfg).content) == 4
    result = file_write(str(file), '123456789', max_bytes=99, config=cfg)
    assert result.error
    assert file.read_text() == '123456789'
