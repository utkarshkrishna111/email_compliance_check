"""
utils/venv_setup.py
-------------------
Virtual environment helpers: guard check and full setup.

Imported by main.py before any third-party imports, so this module
must use only the Python standard library.
"""

import os
import subprocess
import sys
from pathlib import Path


_REQUIRED_PACKAGES = [
    # (pip_install_name,        python_import_name)
    ("python-dotenv",           "dotenv"),
    ("pyyaml",                  "yaml"),
    ("pdfplumber",              "pdfplumber"),
    ("pandas",                  "pandas"),
    ("openpyxl",                "openpyxl"),
    ("openai>=2.26.0",          "openai"),
    ("langchain",               "langchain"),
    ("langchain-openai",        "langchain_openai"),
    ("langchain-core",          "langchain_core"),
    ("flask",                   "flask"),
    ("flask-cors",              "flask_cors"),
    ("tiktoken>=0.7.0",         "tiktoken"),
    ("colorlog",                "colorlog"),
    ("reportlab",               "reportlab"),
]


def find_venv(project_root: Path):
    """Return path to a venv folder in project_root, or None."""
    for name in (".venv", "venv", "env"):
        candidate = project_root / name
        if (candidate / "pyvenv.cfg").exists():
            return candidate
    return None


def check_venv(project_root: Path) -> None:
    """
    Exit with a clear message when not running inside any virtual environment.

    Detection (any one passing = we are in a venv, returns silently):
      1. sys.prefix != sys.base_prefix   standard venv indicator
      2. VIRTUAL_ENV env var             set by Activate.ps1 and PyCharm
      3. CONDA_PREFIX env var            conda environments
      4. Running python.exe lives inside a venv folder on disk
    """
    if sys.prefix != sys.base_prefix:
        return
    if os.environ.get("VIRTUAL_ENV"):
        return
    if os.environ.get("CONDA_PREFIX"):
        return

    running = Path(sys.executable).resolve()
    venv = find_venv(project_root)
    if venv:
        try:
            running.relative_to(venv.resolve())
            return
        except ValueError:
            pass

    sep = "=" * 62
    print(sep)
    print("  ERROR: Virtual environment is not activated.")
    print(sep)
    if venv:
        n = venv.name
        print()
        print("  Found a venv at: " + str(venv))
        print()
        print("  Activate in PowerShell:  .\\" + n + "\\Scripts\\Activate.ps1")
        print("  Activate in CMD:         " + n + "\\Scripts\\activate.bat")
        print()
        print("  Then re-run:  python main.py email_data")
        print()
        print("  Or in PyCharm: Settings -> Python Interpreter -> Add Interpreter")
        print("    -> Existing -> " + str(venv / "Scripts" / "python.exe"))
    else:
        print()
        print("  No venv found. Run setup first:")
        print("    python main.py --setup")
    print(sep)
    sys.exit(1)


def setup_venv(project_root: Path) -> None:
    """Create a venv (if one does not already exist) and install all required packages."""
    venv = find_venv(project_root)
    if venv is None:
        print("Creating virtual environment ...")
        venv = project_root / "venv"
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
        print("Created venv at: " + str(venv))
    else:
        print("Found existing venv at: " + str(venv))

    pip = venv / "Scripts" / "pip.exe"   # Windows
    if not pip.exists():
        pip = venv / "bin" / "pip"        # macOS / Linux

    print("\nInstalling required packages ...")
    for pip_name, _ in _REQUIRED_PACKAGES:
        display = pip_name.split(">")[0].split("=")[0].split("<")[0]
        print("  " + display + " ...")
        subprocess.check_call(
            [str(pip), "install", pip_name, "--quiet", "--prefer-binary"],
            stdout=subprocess.DEVNULL,
        )

    n = venv.name
    sep = "=" * 62
    print("\n" + sep)
    print("  Setup complete!")
    print(sep)
    print()
    print("  Activate the venv, then run the application:")
    print()
    print("  PowerShell:  .\\" + n + "\\Scripts\\Activate.ps1")
    print("  CMD:         " + n + "\\Scripts\\activate.bat")
    print()
    print("  Then:  python main.py")
    print(sep)
