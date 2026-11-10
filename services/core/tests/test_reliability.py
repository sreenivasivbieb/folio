"""NFR reliability: crash-safe storage and resumable jobs (forced kill, tested)."""

import os
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

from .conftest import drain, make_container

WRITER = textwrap.dedent("""
    import sys
    from pathlib import Path
    sys.path.insert(0, {root!r})
    from tests.conftest import make_container
    c = make_container(Path({tmp!r}), db_name={db!r})
    i = 0
    print("ready", flush=True)
    while True:
        c.knowledge.create_entity("Person", f"Person {{i}}")
        i += 1
""")


def test_forced_kill_loses_no_committed_data(tmp_path: Path):
    db = f"folio_test_kill_{uuid.uuid4().hex[:8]}"
    tests_dir = Path(__file__).parent
    script = tmp_path / "writer.py"
    script.write_text(WRITER.format(root=str(tests_dir.parent), tmp=str(tmp_path), db=db))
    proc = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, cwd=tests_dir,
                            env={**os.environ, "PYTHONPATH": str(tests_dir.parent)})
    assert proc.stdout.readline().strip() == b"ready"
    time.sleep(1.5)
    proc.kill()  # SIGKILL on Linux, TerminateProcess on Windows: no cleanup, no commit in flight
    proc.wait()

    c = make_container(tmp_path, db_name=db)  # dropped again by the fixture
    entities = c.kdb["entities"].count_documents({})
    assert entities > 0
    # Every committed entity has its complete ledger record (atomic group + event); the
    # transaction that was in flight at the kill left nothing behind.
    groups = c.kdb["event_groups"].count_documents({"action": "entity.create"})
    inserts = c.kdb["events"].count_documents({"coll": "entities", "op": "insert"})
    assert groups == entities == inserts


def test_interrupted_jobs_resume(tmp_path: Path, files):
    c = make_container(tmp_path)
    c.ingestion.add_root(str(files / "meeting-notes.md"))
    job = c.queue.claim()  # a worker picked it up ... and the process died
    assert job is not None and c.queue.get(job.id).status == "running"
    c.index.close()

    c2 = make_container(tmp_path, db_name=c.kdb.name)
    assert c2.queue.recover() == 1
    c2.workers.run_until_idle()
    assert c2.queue.get(job.id).status == "done"


def test_scans_never_starve_indexing(container, files):
    """A running folder scan occupies only the scan lane; content jobs are still claimable."""
    q = container.queue
    q.enqueue("scan_root", {"root_id": "a"}, dedupe_key="scan:a", priority=20)
    q.enqueue("scan_root", {"root_id": "b"}, dedupe_key="scan:b", priority=20)
    q.enqueue("index_source", {"source_id": "s"}, dedupe_key="index:s", priority=0)
    assert q.claim(("scan_root",)).kind == "scan_root"
    assert q.claim(None, ("scan_root",)).kind == "index_source"  # not the second scan


def test_nested_roots_are_scanned_once(container, files):
    from folio_core.store import repo

    sub = files / "nested"
    sub.mkdir()
    (sub / "inner.txt").write_text("inner notes about kites")
    container.ingestion.add_root(str(files))
    inner = container.ingestion.add_root(str(sub))
    outer = next(r for r in container.ingestion.roots() if r.id != inner.id)
    walked = list(container.ingestion._iter_files(outer))
    assert sub / "inner.txt" not in walked
    drain(container)
    src = repo.source_by_path(container.kdb, str((sub / "inner.txt").resolve()))
    assert src is not None and src.root_id == inner.id


def test_old_finished_jobs_are_pruned_but_failures_kept(container):
    q = container.queue
    done = q.enqueue("index_source", {"source_id": "a"}, dedupe_key="index:a")
    failed = q.enqueue("index_source", {"source_id": "b"}, dedupe_key="index:b")
    with container.index.write() as conn:
        conn.execute("UPDATE jobs SET status='done', updated_at='2020-01-01T00:00:00.000+00:00' WHERE id=?", (done,))
        conn.execute("UPDATE jobs SET status='failed', updated_at='2020-01-01T00:00:00.000+00:00' WHERE id=?", (failed,))
    assert q.prune() == 1
    assert q.get(done) is None and q.get(failed) is not None
