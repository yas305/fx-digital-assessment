#!/usr/bin/env python3
"""
Start the backend.

    python main.py

That is the whole thing. If the dependencies are not installed in whichever
Python you ran this with, but a virtual environment exists in this folder, the
script re-runs itself using that instead -- so forgetting to activate the venv
is not a problem.

Options:
    python main.py --port 9000     serve on a different port
    python main.py --no-reload     do not restart when a file changes
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from bootstrap import use_the_right_python

HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the dominant colour API.")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port to serve on (default: 8000).")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Address to bind to (default: 127.0.0.1).")
    parser.add_argument("--no-reload", action="store_true",
                        help="Do not restart the server when a file changes.")
    args = parser.parse_args()

    # The server needs more than the command-line tool does.
    use_the_right_python(
        str(Path(__file__).resolve()), needs=("PIL", "fastapi", "uvicorn")
    )

    import uvicorn

    # uvicorn's reloader starts a fresh process that imports "app.api" by name,
    # and that process resolves it relative to the working directory. Moving
    # here first means `python main.py` and `python backend/main.py` both work.
    os.chdir(HERE)

    print()
    print(f"  Dominant Colour Finder API")
    print(f"  {'-' * 44}")
    print(f"  API      http://{args.host}:{args.port}/api/health")
    print(f"  Docs     http://{args.host}:{args.port}/docs")
    print(f"  Frontend http://localhost:5173   (run `npm run dev` in ../frontend)")
    print(f"  {'-' * 44}")
    print(f"  Ctrl-C to stop")
    print()
    # uvicorn logs to stderr, which is unbuffered; flush so this banner is not
    # reordered after it when the output is piped to a file.
    sys.stdout.flush()

    try:
        uvicorn.run(
            "app.api:app",
            host=args.host,
            port=args.port,
            reload=not args.no_reload,
        )
    except OSError as exc:
        # By far the most common cause is another copy already running.
        print(f"\nCould not start on port {args.port}: {exc}", file=sys.stderr)
        print(f"Something may already be using it. Try: python main.py --port 8001",
              file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
