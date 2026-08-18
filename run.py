#!/usr/bin/env python3
"""The install, for a Python that may not be able to make its own virtualenv.

``python3 -m venv`` and ``pip install -e ".[dev]"`` do the same thing in two
lines, and nothing in the package depends on this file. It is the documented
path anyway, because on Debian and Ubuntu -- which is most readers -- those two
lines fail: ``ensurepip`` lives in a separate ``python3-venv`` package, and "go
install something first" is a poor answer to "how do I install this".

    python3 run.py              # the mocked suite -- no cloud, no credentials
    python3 run.py ladder       # force a real 429, watch the ladder recover
    python3 run.py check        # diff the declared matrix against the live API
    python3 run.py matrix       # print the whole model x option x endpoint matrix
    python3 run.py headers      # both Priority spellings against a Flex control
    python3 run.py bench        # per-step latency and what you were granted
    python3 run.py sweep        # whole traversals, forced to fail at every depth
    python3 run.py live         # the live pytest suite

Standard library only, so there is nothing to install before installing.
It builds ``.venv``, puts the package in it, and runs. Re-running skips
straight to the run.

Everything past ``run.py`` (the default) needs Google credentials, because
these demos call the real API. That part cannot be packaged away -- see
``credentials()`` below, which says so plainly instead of failing with a
stack trace.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
BIN = VENV / ("Scripts" if os.name == "nt" else "bin")
EXE = BIN / ("python.exe" if os.name == "nt" else "python")

GET_PIP = "https://bootstrap.pypa.io/get-pip.py"

#: What each word runs. ``live`` marks the ones that need credentials.
COMMANDS = {
    "test": (["-m", "pytest", "-q", "-m", "not live"], False),
    "live": (["-m", "pytest", "-q", "-m", "live"], True),
    "check": (["demo/probe_matrix.py", "--check"], True),
    "matrix": (["demo/probe_matrix.py"], True),
    "headers": (["demo/probe_priority_headers.py"], True),
    "ladder": (["demo/live_ladder.py"], True),
    "bench": (["demo/bench.py", "-n", "20"], True),
    "sweep": (["demo/bench_ladder.py", "-n", "3"], True),
}


def say(message: str) -> None:
    print(f"\033[36m::\033[0m {message}", flush=True)


def build_venv() -> None:
    """Create ``.venv`` with a working pip, on a machine that may have neither.

    ``venv`` ships with Python but ``ensurepip`` does not always: Debian and
    Ubuntu split it into a separate ``python3-venv`` package, so the obvious
    one-liner fails on exactly the systems most readers are on. Rather than
    tell them to go install something first -- the thing this script exists to
    avoid -- fall back to fetching ``get-pip.py``.
    """
    if importlib.util.find_spec("ensurepip") is not None:
        try:
            venv.EnvBuilder(with_pip=True, clear=True).create(VENV)
            return
        except (Exception, SystemExit):
            # Debian's patched venv calls sys.exit() rather than raising, and
            # SystemExit is not an Exception -- catch both or the fallback
            # below never runs on the systems that need it most.
            pass

    say("this Python has no ensurepip; bootstrapping pip instead")
    venv.EnvBuilder(with_pip=False, clear=True).create(VENV)

    import tempfile
    import urllib.request

    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "get-pip.py"
        try:
            with urllib.request.urlopen(GET_PIP, timeout=60) as response:
                script.write_bytes(response.read())
        except OSError as exc:
            sys.exit(
                f"could not download pip from {GET_PIP}: {exc}\n"
                "You are offline, or behind a proxy. Install the 'python3-venv'\n"
                "package and run this again."
            )
        subprocess.run([str(EXE), str(script), "-q"], check=True)


def ensure_env() -> None:
    """Make ``.venv`` exist and hold this package. Idempotent and quiet."""
    if (BIN / "pytest").exists() or (BIN / "pytest.exe").exists():
        return

    # UP036 calls this dead because pyproject requires 3.10. It is not: this
    # file is the one thing here that runs on a Python nobody has vetted, and
    # a version number beats a SyntaxError from somewhere in the package.
    if sys.version_info < (3, 10):  # noqa: UP036
        sys.exit(f"needs Python 3.10 or newer; this is {sys.version.split()[0]}")

    say(f"building {VENV.relative_to(ROOT)} (once)")
    build_venv()

    say("installing the package and its dependencies")
    subprocess.run(
        [str(EXE), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True
    )
    subprocess.run([str(EXE), "-m", "pip", "install", "-q", "-e", ".[dev]"], check=True)

    # This script runs everything through .venv's interpreter, so the caller's
    # shell is untouched -- and every other command in the README assumes an
    # activated one. Say so rather than leaving them to work it out.
    activate = (
        rf"{VENV.name}\Scripts\activate"
        if os.name == "nt"
        else f"source {VENV.name}/bin/activate"
    )
    say(f"to use it directly:  {activate}")


def credentials() -> None:
    """Fail early and legibly on the one prerequisite that cannot be shipped.

    These demos call the real API, which means Application Default
    Credentials. No amount of packaging removes that, so say what is missing
    and how to get it rather than surfacing a 401 from three layers down.
    """
    adc = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    missing = []
    if not adc.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        missing.append(
            "  Credentials. Run:  gcloud auth application-default login\n"
            "  (or point GOOGLE_APPLICATION_CREDENTIALS at a service-account key)"
        )
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        missing.append("  A project. Run:  export GOOGLE_CLOUD_PROJECT=your-project-id")
    if missing:
        sys.exit(
            "This one talks to the real API, and two things are missing:\n\n"
            + "\n".join(missing)
            + "\n\nEverything else here runs without them: python3 run.py"
        )


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "test"
    if name in ("-h", "--help", "help") or name not in COMMANDS:
        print(__doc__)
        return 0 if name in ("-h", "--help", "help") else 2

    argv, needs_cloud = COMMANDS[name]
    if needs_cloud:
        credentials()

    ensure_env()
    say(f"{name}: {' '.join(argv)}")
    return subprocess.run([str(EXE), *argv, *sys.argv[2:]], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
