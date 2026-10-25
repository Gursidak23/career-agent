"""`career-agent` command: run the API, the worker, backups, or a health check.

  career-agent api [--prod] [--host H] [--port P]   web API (+ built UI with --prod)
  career-agent worker                               background tasks and schedules
  career-agent backup                               back up now
  career-agent health                               print system health
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="career-agent", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    api = sub.add_parser("api", help="run the web API")
    api.add_argument("--prod", action="store_true", help="no auto-reload; serve the built frontend too")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    sub.add_parser("worker", help="run background tasks and schedules")
    sub.add_parser("backup", help="back up the database and uploads now")
    sub.add_parser("health", help="print system health as JSON")
    args = parser.parse_args(argv)

    if args.command == "api":
        if args.prod:
            # Must be set before the app (and its cached settings) is imported.
            os.environ["CAREER_SERVE_FRONTEND"] = "true"
        from .config import get_settings

        if not _is_loopback(args.host) and not get_settings().api_token:
            sys.exit(
                f"Refusing to listen on {args.host} without an API token: anyone on the network could "
                "read your data and send email as you. Set CAREER_API_TOKEN in backend/.env, or use 127.0.0.1."
            )
        import uvicorn

        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=not args.prod)
    elif args.command == "worker":
        from .tasks.worker import main as worker_main

        worker_main()
    elif args.command == "backup":
        from .db import init_db
        from .system import events, state
        from .system.backup import create_backup

        init_db()
        path = create_backup()
        state.put(state.LAST_BACKUP, state.now_iso())
        events.record("backup.created", f"Backup saved: {path.name}")
        print(path)
    elif args.command == "health":
        from .db import SessionLocal, init_db
        from .routers.system import health

        init_db()
        with SessionLocal() as db:
            report = health(db)
        print(json.dumps(report, indent=2, default=str))
        sys.exit(0 if report["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
