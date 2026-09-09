"""
Find the right Python interpreter.

Both entry points -- ``main.py`` and ``cli.py`` -- need the project's
dependencies. If you run either with a Python that does not have them but a
virtual environment exists alongside, this re-runs the script using that
instead, so forgetting to activate the venv is not a problem.

This lives in its own file because it has to run *before* anything from ``app``
is imported, which rules out putting it inside the package.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Sequence

HERE = Path(__file__).resolve().parent

# Where a virtual environment keeps its interpreter. The path differs on
# Windows, so check both rather than assuming.
VENV_PYTHON = next(
    (
        candidate
        for candidate in (
            HERE / ".venv" / "bin" / "python",
            HERE / ".venv" / "Scripts" / "python.exe",
        )
        if candidate.exists()
    ),
    None,
)


def all_importable(module_names: Sequence[str]) -> bool:
    """True if every named module can be imported right now."""
    for name in module_names:
        if importlib.util.find_spec(name) is None:
            return False
    return True


def use_the_right_python(
    script: str, needs: Sequence[str] = ("PIL",), announce: bool = True
) -> None:
    """
    Re-run ``script`` with the virtual environment's Python, if it is needed.

    Args:
        script: Absolute path of the script to re-run.
        needs: The modules this particular entry point requires. They differ:
            the command-line tool only needs Pillow, while the server also needs
            FastAPI and uvicorn. Checking only the smallest set would let a
            script start and then fail partway through on a missing import.
        announce: Print a line saying which environment is being used.

    Does nothing if everything needed is already importable. Exits with
    instructions if there is no environment to fall back on.
    """
    if all_importable(needs):
        return

    if VENV_PYTHON is None:
        print("The project's dependencies are not installed.\n", file=sys.stderr)
        print("Set them up with:\n", file=sys.stderr)
        print("    python3 -m venv .venv", file=sys.stderr)
        print("    .venv/bin/pip install -r requirements.txt\n", file=sys.stderr)
        raise SystemExit(1)

    if announce:
        print(f"Using the virtual environment at {VENV_PYTHON.parent.parent}")
        # execv replaces this process immediately and does not flush buffered
        # output on the way out, so the line above would be lost without this.
        sys.stdout.flush()

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), script, *sys.argv[1:]])
