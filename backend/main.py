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

HERE = Path(__file__).resolve().parent

# Where a virtual environment keeps its interpreter. The path differs on
# Windows, so check both rather than assuming.
VENV_PYTHON = next(
    (
        candidate
        for candidate in (HERE / ".venv" / "bin" / "python",
                          HERE / ".venv" / "Scripts" / "python.exe")
        if candidate.exists()
    ),
    None,
)


def dependencies_are_installed() -> bool:
    """True if the packages the server needs can be imported."""
    try:
        import fastapi  # noqa: F401
        import PIL      # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        return False
    return True


def explain_how_to_install() -> None:
    """Print setup instructions, for when there is no environment to fall back on."""
    print("The backend's dependencies are not installed.\n", file=sys.stderr)
    print("Set them up with:\n", file=sys.stderr)
    print("    python3 -m venv .venv", file=sys.stderr)
    print("    .venv/bin/pip install -r requirements.txt\n", file=sys.stderr)
    print("Then run this again:\n", file=sys.stderr)
    print("    python main.py", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the dominant colour API.")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port to serve on (default: 8000).")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Address to bind to (default: 127.0.0.1).")
    parser.add_argument("--no-reload", action="store_true",
                        help="Do not restart the server when a file changes.")
    args = parser.parse_args()

    if not dependencies_are_installed():
        if VENV_PYTHON is None:
            explain_how_to_install()
            return 1

        # Re-run this same script with the virtual environment's Python. execv
        # replaces the current process rather than nesting one inside another,
        # so Ctrl-C still stops the server cleanly.
        print(f"Using the virtual environment at {VENV_PYTHON.parent.parent}")
        # execv replaces this process immediately and does not flush buffered
        # output on the way out, so the line above would be lost without this.
        sys.stdout.flush()
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

    import uvicorn

    # Run from this folder so that "app.api" resolves however the script was
    # invoked -- `python main.py` or `python backend/main.py` both work.
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
