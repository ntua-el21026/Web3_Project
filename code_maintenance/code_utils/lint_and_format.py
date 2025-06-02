#!/usr/bin/env python3
import subprocess
import sys
import os
from pathlib import Path

try:
    from pathspec import PathSpec
    from pathspec.patterns.gitwildmatch import GitWildMatchPattern
except ImportError:
    print("Install with: pip install pathspec")
    sys.exit(1)

# === Configuration ===
IGNORE_FILES = ['.gitignore']
JS_EXTENSIONS = ('.js', '.ts', '.tsx', '.jsx')
PY_EXTENSIONS = ('.py',)
ALL_FILES = []

def load_ignore_spec(root: Path) -> PathSpec:
    """Parse .gitignore and return a PathSpec."""
    patterns = []
    for fname in IGNORE_FILES:
        ignore_file = root / fname
        if ignore_file.exists():
            with ignore_file.open(encoding="utf-8") as f:
                patterns.extend(f.read().splitlines())
    return PathSpec.from_lines(GitWildMatchPattern, patterns)

def collect_files(root: Path, spec: PathSpec):
    """Recursively collect all .py and .js/.ts files not ignored."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if spec.match_file(str(rel)):
            continue
        if path.suffix in PY_EXTENSIONS + JS_EXTENSIONS:
            ALL_FILES.append(path)

def main():
    project_root = Path(__file__).resolve().parent
    spec = load_ignore_spec(project_root)
    collect_files(project_root, spec)

    py_files = [str(p) for p in ALL_FILES if p.suffix in PY_EXTENSIONS]
    js_files = [str(p) for p in ALL_FILES if p.suffix in JS_EXTENSIONS]

    if py_files:
        print("Running black on Python files...")
        subprocess.run(["black"] + py_files)

        print("Running flake8 on Python files...")
        subprocess.run(["flake8"] + py_files)

    if js_files:
        print("Running eslint --fix on JS/TS files...")
        subprocess.run(["npx", "eslint", "--fix"] + js_files)

    print("\nAll lint and format steps completed.")

if __name__ == "__main__":
    main()

