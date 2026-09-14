"""
Letting the commands in `bin/` run themselves under the project's virtual environment.

The scripts in `bin/` are executable and extensionless, so they are started by whatever `python3`
the shebang resolves to - which on this machine is the system interpreter, and the system
interpreter has none of the project's dependencies. Rather than requiring the virtual environment
to be activated first, each command re-executes itself under `.venv/bin/python`. That is what
makes them work from any directory, from cron, and from a systemd unit with a bare environment.

This lives in `utilities` and imports nothing outside the standard library, deliberately: it has
to be importable *before* the interpreter switch has happened, when none of the project's
dependencies are available yet.

The one subtlety is how "am I already in the virtual environment?" is decided. It is `sys.prefix`,
not the path of the running interpreter, because `.venv/bin/python` is a symlink to the system
python: resolving both sides makes them compare equal and the switch silently never happens. That
bug shipped once, and the reason this module exists rather than the same twelve lines pasted into
every command is that fixing it meant editing one file instead of ten.
"""

import os
import sys
from pathlib import Path

# Set across the re-exec so a switch that somehow fails to take cannot loop.
ALREADY_SWITCHED = "UBI_VENV_REEXEC"

# `utilities` sits directly under the project root, so the root is this file's grandparent.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

def run_under_venv(script_path):
    """
    Re-execute the calling script under the project's virtual environment, if it is not already.

    Does not return when it switches - `os.execv` replaces the process. When no switch is needed,
    puts the project root on `sys.path` and returns it, so the caller can import project modules
    and use the path.

    - `script_path` is the calling script's `__file__`.
    """
    venv_directory = PROJECT_ROOT / ".venv"
    venv_python = venv_directory / "bin" / "python"

    if (venv_python.exists()
            and Path(sys.prefix).resolve() != venv_directory.resolve()
            and not os.environ.get(ALREADY_SWITCHED)):
        os.environ[ALREADY_SWITCHED] = "1"
        os.execv(str(venv_python),
                 [str(venv_python), str(Path(script_path).resolve()), *sys.argv[1:]])

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    return PROJECT_ROOT
