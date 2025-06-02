#!/usr/bin/env python3
"""
lint_and_format.py

Format and lint the repository’s Python & JS/TS sources.

Python pipeline
---------------
1. autoflake   (remove unused imports / variables)
2. autopep8    (wrap lines, minor PEP-8 tweaks)
3. black       (final, authoritative formatter)
4. flake8      (report only – E501 is ignored because Black rules)

JS / TS pipeline
----------------
eslint --fix   (via npx)

The script honours .gitignore and supports --dry-run / --verbose flags.

It must be run from the project root (detected by locating package-lock.json).
"""

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

try:
    from pathspec import PathSpec
except ImportError:
    print("ERROR: pip install pathspec")
    sys.exit(1)


# ───────────────────────── Configuration ──────────────────────────
IGNORE_FILES = [".gitignore"]
JS_EXT = (".js", ".ts", ".tsx", ".jsx")
PY_EXT = (".py",)
LINE_LENGTH = 88
FLAKE8_ARGS = [f"--max-line-length={LINE_LENGTH}", "--extend-ignore=E501"]

LOG_FORMAT = "%(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("lint_and_format")
# ──────────────────────────────────────────────────────────────────


def section(title: str) -> None:
    """Log a simple section header."""
    logger.info(f"\n[ {title} ]")


def error_exit(message: str) -> None:
    """Log an error-level message and exit with status code 1."""
    logger.error(f"ERROR: {message}")
    sys.exit(1)


def find_project_root() -> Path:
    """
    Walk up from cwd until a directory containing package-lock.json is found.
    Returns that directory Path or exits.
    """
    cur = Path.cwd()
    while cur != cur.parent:
        if (cur / "package-lock.json").is_file():
            return cur
        cur = cur.parent

    error_exit("package-lock.json not found; run this from within a project.")
    return Path.cwd()  # unreachable


def ensure_tool(name: str) -> None:
    """Abort if *name* executable is not found on PATH."""
    if shutil.which(name) is None:
        error_exit(f"Required tool '{name}' not on PATH; install it and retry.")


def load_ignore_spec(root: Path) -> PathSpec:
    """Read .gitignore-style files and build a PathSpec."""
    patterns: List[str] = []
    for fname in IGNORE_FILES:
        fp = root / fname
        if fp.exists():
            patterns.extend(fp.read_text("utf-8").splitlines())
    return PathSpec.from_lines("gitwildmatch", patterns)


def scan_for_files(root: Path, spec: PathSpec) -> Tuple[List[Path], List[Path]]:
    """
    Walk all entries under *root* with a progress bar, skipping ignored paths.
    Return two lists: (py_files, js_files).
    """
    all_entries: List[Path] = list(root.rglob("*"))
    total = len(all_entries)
    py_files: List[Path] = []
    js_files: List[Path] = []

    if total == 0:
        return py_files, js_files

    bar_length = 40
    for idx, p in enumerate(all_entries):
        percent = (idx + 1) / total
        filled = int(bar_length * percent)
        bar = "#" * filled + " " * (bar_length - filled)
        print(f"\rScanning files  : [{bar}] {percent * 100:5.1f}%", end="", flush=True)

        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        if spec.match_file(rel):
            continue
        suffix = p.suffix.lower()
        if suffix in PY_EXT:
            py_files.append(p)
        elif suffix in JS_EXT:
            js_files.append(p)

    print()  # finish scanning bar
    logger.info(f"Found {len(py_files)} Python file(s), {len(js_files)} JS/TS file(s)")
    return py_files, js_files


def run(cmd: List[str], *, abort: bool = True) -> None:
    """Run *cmd*. If abort is True, exit on failure; otherwise, ignore errors silently."""
    try:
        subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except subprocess.CalledProcessError:
        if abort:
            logger.error(f"Command failed: {' '.join(cmd)}")
            sys.exit(1)
    return


def count_changed(files: List[Path], before: dict[Path, float]) -> int:
    """Count how many files have a modified time different from before."""
    changed = 0
    for p in files:
        try:
            if p.stat().st_mtime != before.get(p, 0):
                changed += 1
        except FileNotFoundError:
            continue
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run formatter/linter suite on project sources."
    )
    ap.add_argument("--skip-py", action="store_true", help="Skip Python pipeline")
    ap.add_argument("--skip-js", action="store_true", help="Skip JS/TS pipeline")
    ap.add_argument("--dry-run", action="store_true", help="List files only")
    ap.add_argument("--verbose", action="store_true", help="DEBUG logging")
    args = ap.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    project_root = find_project_root()
    logger.info(f"Project root: {project_root}")

    spec = load_ignore_spec(project_root)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1: Scan all entries to build py_files & js_files with a progress bar
    # ─────────────────────────────────────────────────────────────────────────
    py_files, js_files = scan_for_files(project_root, spec)

    if args.dry_run:
        logger.info("\n--- Dry-run only ---")
        if py_files:
            logger.info("Python files:")
            for p in py_files:
                logger.info(f"  {p.relative_to(project_root)}")
        if js_files:
            logger.info("JS/TS files:")
            for p in js_files:
                logger.info(f"  {p.relative_to(project_root)}")
        return

    # ─────────────────────────────────────────────────────────────────────────
    # Ensure required tools before proceeding
    # ─────────────────────────────────────────────────────────────────────────
    if not args.skip_py:
        for tool in ("autoflake", "autopep8", "black", "flake8"):
            ensure_tool(tool)
    if js_files and not args.skip_js:
        ensure_tool("npx")

    # ─────────────────────────────────────────────────────────────────────────
    # Record mtimes before formatting
    # ─────────────────────────────────────────────────────────────────────────
    before_mtimes: dict[Path, float] = {}
    if not args.skip_py:
        for p in py_files:
            try:
                before_mtimes[p] = p.stat().st_mtime
            except FileNotFoundError:
                before_mtimes[p] = 0
    if not args.skip_js:
        for p in js_files:
            try:
                before_mtimes[p] = p.stat().st_mtime
            except FileNotFoundError:
                before_mtimes[p] = 0

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2: Process Python files one by one with a progress bar
    # ─────────────────────────────────────────────────────────────────────────
    if not args.skip_py and py_files:
        section("Python pipeline")
        total_py = len(py_files)
        bar_length = 40

        # Print initial empty bar
        empty_bar = " " * bar_length
        print(f"\rFormatting Python: [{empty_bar}]   0.0%", end="", flush=True)

        for idx, p in enumerate(py_files):
            percent = (idx + 1) / total_py
            filled = int(bar_length * percent)
            bar = "#" * filled + " " * (bar_length - filled)
            print(
                f"\rFormatting Python: [{bar}] {
                    percent * 100:5.1f}%",
                end="",
                flush=True,
            )

            # Run each step on this single file
            run(
                [
                    "autoflake",
                    "--in-place",
                    "--remove-all-unused-imports",
                    "--remove-unused-variables",
                    "--expand-star-imports",
                    str(p),
                ],
                abort=False,
            )
            run(
                [
                    "autopep8",
                    "--in-place",
                    f"--max-line-length={LINE_LENGTH}",
                    "-a",
                    "-a",
                    "--experimental",
                    str(p),
                ],
                abort=False,
            )
            run(["black", "--quiet", f"--line-length={LINE_LENGTH}", str(p)])
            run(["flake8", *FLAKE8_ARGS, str(p)], abort=False)

        print()  # finish Python progress bar

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3: Process JS/TS files one by one with a progress bar
    # ─────────────────────────────────────────────────────────────────────────
    if not args.skip_js and js_files:
        section("JS/TS pipeline")
        total_js = len(js_files)
        bar_length = 40

        # Print initial empty bar
        empty_bar = " " * bar_length
        print(f"\rFormatting JS/TS : [{empty_bar}]   0.0%", end="", flush=True)

        for idx, p in enumerate(js_files):
            percent = (idx + 1) / total_js
            filled = int(bar_length * percent)
            bar = "#" * filled + " " * (bar_length - filled)
            print(
                f"\rFormatting JS/TS : [{bar}] {percent * 100: 5.1f} %",
                end="",
                flush=True,
            )

            run(["npx", "eslint", "--fix", str(p)])

        print()  # finish JS/TS progress bar

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 4: Count changed files and summarize
    # ─────────────────────────────────────────────────────────────────────────
    all_processed: List[Path] = []
    if not args.skip_py:
        all_processed += py_files
    if not args.skip_js:
        all_processed += js_files

    changed_count = count_changed(all_processed, before_mtimes)
    logger.info(f"\n{changed_count} file(s) formatted/modified.")
    logger.info("Lint/format pipeline finished.")


if __name__ == "__main__":
    main()
