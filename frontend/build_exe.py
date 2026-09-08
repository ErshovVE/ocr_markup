"""Build a standalone frontend executable via PyInstaller.

Run from frontend/: `python build_exe.py`
Deps: pip install -r requirements-build.txt

Produces a native executable for the host OS (.exe on Windows). wrapper.py
launches `streamlit run app.py`, and app.py does `from src.i18n import ...`,
so BOTH app.py and the whole src/ package must be bundled as data.
"""
import subprocess
import sys

SEP = ";" if sys.platform == "win32" else ":"
ADD_DATA = [f"app.py{SEP}.", f"src{SEP}src"]

CMD = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "wrapper.py",
    "--hidden-import", "streamlit",
    "--copy-metadata", "streamlit",
    "--collect-submodules", "streamlit",
    "--collect-all", "streamlit",
]
for entry in ADD_DATA:
    CMD += ["--add-data", entry]

if __name__ == "__main__":
    subprocess.run(CMD, check=True)
