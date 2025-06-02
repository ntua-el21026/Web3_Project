#!/usr/bin/env python3
import os
import subprocess
from typing import Optional
from pathlib import Path

def run(command: str, cwd: Optional[Path] = None):
    """Run a shell command, exit if it fails."""
    result = subprocess.run(command, shell=True, cwd=cwd)
    if result.returncode != 0:
        print(f"[!] Command failed: {command}")
        exit(result.returncode)

def main():
    project_root = Path(__file__).resolve().parent
    docs_dir = project_root / "docs"

    # If docs/ does not exist, initialize Sphinx
    if not docs_dir.exists():
        print("Initializing Sphinx in docs/ …")
        run(
            "sphinx-quickstart -q -p 'MyProject' -a 'Author' --sep --makefile --batchfile docs",
            cwd=project_root
        )

    conf_py = docs_dir / "conf.py"
    if conf_py.exists():
        print("Building HTML documentation …")
        run("make html", cwd=docs_dir)
        print("Documentation build complete. Output in docs/_build/html")
    else:
        print("Error: docs/conf.py not found. Ensure Sphinx initialized correctly.")

if __name__ == "__main__":
    main()

