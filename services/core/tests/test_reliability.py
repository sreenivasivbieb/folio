"""NFR reliability: crash-safe storage and resumable jobs (forced kill, tested)."""

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from .conftest import make_container

WRITER = textwrap.dedent("""
    import sys
    from pathlib import Path
    sys.path.insert(0, {root!r})
    from tests.conftest import make_container
    c = make_container(Path({tmp!r}))
    i = 0
    print("ready", flush=True)
    while True:
        c.knowledge.create_entity("Person", f"Person {{i}}")
        i += 1
""")


def test_forced_kill_loses_no_committed_data(tmp_path: Path):
    tests_dir = str(Path(__file__).parent)
    script = tmp_path / "writer.py"
    script.write_text(WRITER.format(root=str(Path(tests_dir).parent), tmp=str(tmp_path)))
    proc = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, cwd=tests_dir,
                            env={**os.environ, "PYTHONPATH": str(Path(tests_dir).parent)})
    assert proc.stdout.readline().strip() == b"ready"
    time.sleep(1.5)
    proc.send_signal(signal.SIGKILL)  # no cleanup, no commit of an in-flight transaction
    proc.wait()

    c = make_container(tmp_path)
    conn = c.db.reader()
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    assert entities > 0
    # Every committed entity has its complete ledger record (atomic group + events).
    groups = conn.execute("SELECT COUNT(*) FROM event_groups WHERE action = 'entity.create'").fetchone()[0]
    inserts = conn.execute("SELECT COUNT(*) FROM events WHERE tbl = 'entities' AND op = 'insert'").fetchone()[0]
    assert groups == entities == inserts


def test_interrupted_jobs_resume(tmp_path: Path, files):
    c = make_container(tmp_path)
    c.ingestion.add_root(str(files / "meeting-notes.md"))
    job = c.queue.claim()  # a worker picked it up ... and the process died
    assert job is not None and c.queue.get(job.id).status == "running"
    c.db.close()

    c2 = make_container(tmp_path)
    assert c2.queue.recover() == 1
    c2.workers.run_until_idle()
    assert c2.queue.get(job.id).status == "done"
