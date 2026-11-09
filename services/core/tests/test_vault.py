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
