"""Build a standalone frontend executable via PyInstaller.

Run from frontend/: `python build_exe.py`
Deps: pip install -r requirements-build.txt

Wraps the command in pyinst_command.txt so it doesn't need to be retyped by
hand; produces a native executable for the host OS (.exe on Windows).
"""
import subprocess
import sys

ADD_DATA = "app.py;." if sys.platform == "win32" else "app.py:."

CMD = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--add-data", ADD_DATA,
    "wrapper.py",
    "--hidden-import", "streamlit",
    "--copy-metadata", "streamlit",
    "--collect-submodules", "streamlit",
    "--collect-all", "streamlit",
]

if __name__ == "__main__":
    subprocess.run(CMD, check=True)
