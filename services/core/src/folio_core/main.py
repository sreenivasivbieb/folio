"""``folio-core`` command line.

    folio-core serve      run the core service (the desktop shell starts this as its sidecar)
    folio-core openapi    print the OpenAPI spec (generates the UI's TypeScript client)
    folio-core voice      toggle|start|stop push-to-talk on a running core (bind to a hotkey)
    folio-core eval       measure extraction precision/recall on the golden set
    folio-core sandbox    internal: parse one file in a resource-limited child process
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

READY_PREFIX = "FOLIO_READY "


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":  # os.kill(pid, 0) would *terminate* the process on Windows
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _exit_with_parent() -> None:
    """If the shell dies without killing us, do not linger as an orphan. Checks both our direct
    parent and FOLIO_PARENT_PID (the shell), since a launcher like `uv run` may sit in between."""
    parent = os.getppid()
    shell = int(os.environ.get("FOLIO_PARENT_PID", "0") or 0)

    def watch() -> None:
        while True:
            time.sleep(2)
            if os.getppid() != parent or (shell and not _pid_alive(shell)):
                os._exit(0)

    threading.Thread(target=watch, daemon=True, name="folio-parent-watch").start()


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api.app import create_app
    from .config import Settings
    from .container import build_container

    logging.basicConfig(level=os.environ.get("FOLIO_LOG", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    settings = Settings.from_env(
        data_dir=Path(args.data_dir) if args.data_dir else None,
        port=args.port, watch=False if args.no_watch else None,
    )
    token = settings.token or secrets.token_urlsafe(32)
    container = build_container(settings)
    app = create_app(container, token)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((settings.host, settings.port))
    sock.listen(2048)  # accept (queue) connections as soon as we announce readiness
    port = sock.getsockname()[1]

    runtime = settings.runtime_file
    runtime.write_text(json.dumps({"port": port, "token": token, "pid": os.getpid()}))
    if sys.platform != "win32":
        runtime.chmod(0o600)

    if args.exit_with_parent:
        _exit_with_parent()
    print(READY_PREFIX + json.dumps({"port": port}), flush=True)

    config = uvicorn.Config(app, log_level="warning", access_log=False)
    try:
        uvicorn.Server(config).run(sockets=[sock])
    finally:
        runtime.unlink(missing_ok=True)
    return 0


def cmd_openapi(args: argparse.Namespace) -> int:
    """Print the API spec. Needs no database: the routes are introspected, never called."""
    from types import SimpleNamespace

    from .api.app import create_app
    from .config import Settings

    stand_in = SimpleNamespace(settings=Settings())
    spec = create_app(stand_in, "x", start_background=False).openapi()  # type: ignore[arg-type]
    text = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


def cmd_voice(args: argparse.Namespace) -> int:
    import httpx

    from .config import Settings

    settings = Settings.from_env(data_dir=Path(args.data_dir) if args.data_dir else None)
    try:
        rt = json.loads(settings.runtime_file.read_text())
    except FileNotFoundError:
        print("folio core is not running", file=sys.stderr)
        return 1
    path = {"toggle": "/api/voice/toggle", "start": "/api/voice/start", "stop": "/api/voice/stop"}[args.action]
    r = httpx.post(f"http://127.0.0.1:{rt['port']}{path}", json={"target_kind": "none", "target_ids": []},
                   headers={"Authorization": f"Bearer {rt['token']}"}, timeout=60)
    print(r.text)
    return 0 if r.is_success else 1


def cmd_eval(args: argparse.Namespace) -> int:
    from .evaluation import run_eval

    golden = Path(args.golden) if args.golden else Path(__file__).resolve().parents[4] / "eval" / "golden"
    report = run_eval(golden)
    print(json.dumps(report, indent=2))
    ok = report["precision"] >= args.min_precision
    if not ok:
        print(f"precision {report['precision']:.3f} below gate {args.min_precision}", file=sys.stderr)
    return 0 if ok else 2


def cli(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["sandbox"]:  # frozen builds re-enter here for sandboxed parsing
        from .ingestion.sandbox import child_main

        return child_main(argv[1:])

    p = argparse.ArgumentParser(prog="folio-core", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the core service")
    s.add_argument("--port", type=int, default=None, help="0 = random free port (default)")
    s.add_argument("--data-dir", default=None)
    s.add_argument("--no-watch", action="store_true", help="disable folder watching")
    s.add_argument("--exit-with-parent", action="store_true")
    s.set_defaults(fn=cmd_serve)

    o = sub.add_parser("openapi", help="print the OpenAPI spec")
    o.add_argument("--out", default=None)
    o.set_defaults(fn=cmd_openapi)

    v = sub.add_parser("voice", help="control push-to-talk on a running core")
    v.add_argument("action", choices=["toggle", "start", "stop"])
    v.add_argument("--data-dir", default=None)
    v.set_defaults(fn=cmd_voice)

    e = sub.add_parser("eval", help="extraction quality on a golden set")
    e.add_argument("golden", nargs="?", default=None, help="folder of golden cases (default: repo eval/golden)")
    e.add_argument("--min-precision", type=float, default=0.0)
    e.set_defaults(fn=cmd_eval)

    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(cli())
