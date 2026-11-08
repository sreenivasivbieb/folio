"""NFR reliability: crash-safe storage and resumable jobs (forced kill, tested)."""

import os
import signal
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

from .conftest import make_container

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
    proc.send_signal(signal.SIGKILL)  # no cleanup, no commit of an in-flight transaction
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
