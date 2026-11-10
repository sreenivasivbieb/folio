"""Dumping files into Folio: move/copy into its own storage, duplicates, trash, restore, export."""

from pathlib import Path

from folio_core.store import repo

from .conftest import drain


def _vault_files(c):
    return [s for s in repo.list_sources(c.kdb) if c.vault.is_vault_path(Path(s.path))]


def test_move_leaves_one_copy_and_copy_keeps_original(container, tmp_path):
    a = tmp_path / "in" / "notes.md"
    a.parent.mkdir()
    a.write_text("# Kites\nNotes about kites.")
    b = tmp_path / "keep.txt"
    b.write_text("copied, not moved")
    container.vault.import_paths([str(a.parent)], "move")
    container.vault.import_paths([str(b)], "copy")
    drain(container)
    assert not a.exists() and not a.parent.exists()  # moved; emptied folder removed
    assert b.exists()  # copied: original stays
    files = _vault_files(container)
    assert {Path(s.path).name for s in files} == {"notes.md", "keep.txt"}
    assert all(s.status.value == "indexed" for s in files)
    assert container.search.search("kites")


def test_duplicates_are_skipped_and_original_left_alone(container, tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("same bytes")
    g = tmp_path / "y.txt"
    g.write_text("same bytes")
    container.vault.import_paths([str(f)], "move")
    stats = container.vault.import_paths([str(g)], "move")
    assert stats["duplicates"] == 1 and g.exists()


def test_trash_restore_delete_and_export(container, tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("vault document about otters")
    container.vault.import_paths([str(f)], "move")
    drain(container)
    sid = _vault_files(container)[0].id
    container.vault.trash(sid)
    assert repo.get_source(container.kdb, sid).status.value == "trashed"
    assert not container.search.search("otters")
    container.vault.restore(sid)
    drain(container)
    assert container.search.search("otters")
    out = tmp_path / "out"
    out.mkdir()
    target = container.vault.export(sid, str(out), "move")
    assert Path(target).read_text() == "vault document about otters"
    assert repo.get_source(container.kdb, sid).status.value == "forgotten"


def test_cannot_import_folios_own_storage(container):
    import pytest

    from folio_core.domain.errors import InvalidInput

    with pytest.raises(InvalidInput):
        container.vault.import_paths([str(container.settings.data_dir)], "copy")


def test_startup_rescan_sees_vault_files(container, tmp_path):
    f = tmp_path / "clip.txt"
    f.write_text("waiting file")
    container.vault.import_paths([str(f)], "move")
    drain(container)
    root = container.vault.root()
    walked = list(container.ingestion._iter_files(root))
    assert [p.name for p in walked] == ["clip.txt"]  # the vault lives inside Folio's data folder
    stored = _vault_files(container)[0]
    Path(stored.path).unlink()
    container.ingestion.rescan_all()
    drain(container)
    assert repo.get_source(container.kdb, stored.id).status.value == "missing"


def test_queued_indexing_never_revives_a_trashed_file(container, tmp_path):
    f = tmp_path / "late.txt"
    f.write_text("otters and kites")
    container.vault.import_paths([str(f)], "move")  # its index job is queued, not run yet
    sid = _vault_files(container)[0].id
    container.vault.trash(sid)
    drain(container)  # the stale job runs now
    assert repo.get_source(container.kdb, sid).status.value == "trashed"
    assert not container.search.search("otters")


def test_failed_copy_leaves_no_partial_file(container, tmp_path, monkeypatch):
    import shutil

    f = tmp_path / "big.txt"
    f.write_text("data")

    def disk_full(src, dst, *a, **k):
        Path(dst).write_text("partial")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shutil, "copy2", disk_full)
    stats = container.vault.import_paths([str(f)], "copy")
    assert stats["failed"] == 1 and f.exists()
    assert not [p for p in container.vault.dir.rglob("*") if p.is_file()]


def test_moved_data_folder_does_not_duplicate_files(container, tmp_path):
    import shutil

    from .conftest import make_container

    f = tmp_path / "keep.txt"
    f.write_text("vault content about kites")
    container.vault.import_paths([str(f)], "move")
    drain(container)
    sid = _vault_files(container)[0].id
    container.vault.trash(sid)
    container.vault.restore(sid)
    drain(container)
    container.kdb._writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # a consistent copy on disk
    container.index._writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    moved = tmp_path / "moved"
    shutil.copytree(container.settings.data_dir, moved / "data")  # e.g. a new FOLIO_DATA_DIR
    c2 = make_container(moved)
    c2.start(background_scan=False)
    try:
        c2.ingestion.rescan_all()
        drain(c2)
        files = [s for s in repo.list_sources(c2.kdb) if s.status.value not in ("forgotten", "removed")]
        assert len(files) == 1 and c2.vault.is_vault_path(Path(files[0].path))
        c2.vault.trash(files[0].id)  # trash/restore work at the new location
        c2.vault.restore(files[0].id)
    finally:
        c2.workers.stop()


def test_smart_ignore_skips_junk_and_counts_it(container, tmp_path):
    proj = tmp_path / "solar"
    for rel in ("docs/architecture.md", "data/readings.csv.txt", "notes.txt",
                "node_modules/react/index.js", "node_modules/react/README.md", ".git/config",
                "build/out.txt", "dist/bundle.js", "target/debug/app", "venv/lib/x.py",
                ".vscode/settings.json", "package-lock.json", "uv.lock", "tool.exe", "lib/libfoo.so.6",
                "app.pyc", "disk.iso", ".DS_Store", "Thumbs.db"):
        f = proj / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"content of {rel}")  # unique, so the duplicate check does not interfere
    assert container.vault.preview([str(proj)]) == {"files": 3, "skipped": 16}
    stats = container.vault.import_paths([str(proj)], "copy")
    assert stats["imported"] == 3 and stats["skipped"] == 16
    names = sorted(Path(s.path).name for s in _vault_files(container))
    assert names == ["architecture.md", "notes.txt", "readings.csv.txt"]


def test_a_dropped_binary_is_skipped_not_imported(container, tmp_path):
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"MZ")
    assert container.vault.preview([str(exe)]) == {"files": 0, "skipped": 1}
