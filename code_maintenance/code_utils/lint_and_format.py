#!/usr/bin/env python3
"""
lint_and_format.py

Format and lint the repository’s Python & JS/TS sources, writing INFO-level output
both to the terminal and to a shared log file at:
    <project_root>/cache/code_maintenance/code_utils/logs/lint_and_format.log

Python pipeline
---------------
1. autoflake   (remove unused imports / variables)
2. autopep8    (wrap lines, minor PEP-8 tweaks)
3. black       (final, authoritative formatter)
4. flake8      (report only – E501 is ignored because Black handles line length)

JS / TS pipeline
----------------
eslint --fix   (via npx)

This script honours .gitignore patterns, supports:
    --skip-py   : skip the Python pipeline
    --skip-js   : skip the JS/TS pipeline
    --dry-run   : list candidate files without modifying
    --verbose   : enable DEBUG-level logging

Must be run from the project root (detected by locating package-lock.json).
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

logger = logging.getLogger("lint_and_format")
logger.setLevel(logging.INFO)


def setup_logging(project_root: Path) -> None:
    """
    Configure console and file logging.
    Log file is located at:
        <project_root>/cache/code_maintenance/code_utils/logs/lint_and_format.log

    We explicitly truncate any existing log before attaching the FileHandler.
    """
    log_dir = project_root / "cache" / "code_maintenance" / "code_utils" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "lint_and_format.log"

    # If the log file already exists, truncate it (clear previous contents)
    if log_file.exists():
        log_file.write_text("", encoding="utf-8")

    # Console handler (minimal formatting)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    # File handler (mode="w" also truncates, but we've already cleared it above)
    fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"
        )
    )
    logger.addHandler(fh)


def section(title: str) -> None:
    """Log a simple section header."""
    logger.info(f"[ {title} ]")


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
    """
    Read .gitignore-style files and build a PathSpec.
    For each non-blank line:
      - If line starts with '#', strip that '#' and any following spaces → pattern.
      - Otherwise, strip inline comments (anything after an unescaped '#').
    For any pattern ending in '/', also add 'pattern/**' so all children are ignored.
    Always ignore '.git' and '.git/**'.
    """
    raw_patterns: List[str] = []
    for fname in IGNORE_FILES:
        fp = root / fname
        if fp.exists():
            for raw in fp.read_text("utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    candidate = line.lstrip("#").strip()
                    if candidate:
                        raw_patterns.append(candidate)
                else:
                    if "#" in raw:
                        candidate = raw.split("#", 1)[0].rstrip()
                    else:
                        candidate = raw.rstrip()
                    candidate = candidate.strip()
                    if candidate:
                        raw_patterns.append(candidate)

    # Always ignore the .git directory and its contents
    raw_patterns.append(".git/")
    raw_patterns.append(".git")

    final_patterns: List[str] = []
    for pat in raw_patterns:
        if pat.endswith("/"):
            base = pat.rstrip("/")
            final_patterns.append(base)
            final_patterns.append(f"{base}/**")
        else:
            final_patterns.append(pat)

    return PathSpec.from_lines("gitwildmatch", final_patterns)


def scan_for_files(root: Path, spec: PathSpec) -> Tuple[List[Path], List[Path]]:
    """
    Walk all entries under *root* with pruning of ignored directories, skipping ignored paths.
    Returns two lists: (py_files, js_files), and displays a progress bar while scanning.
    """
    # First, count how many entries will actually be visited (excluding pruned subtrees)
    total_entries = 0
    stack: List[Tuple[Path, List[Path]]] = [(root, list(root.iterdir()))]
    while stack:
        parent, children = stack.pop()
        for child in children:
            rel = child.relative_to(root)
            if spec.match_file(str(rel)):
                continue
            total_entries += 1
            if child.is_dir():
                stack.append((child, list(child.iterdir())))

    py_files: List[Path] = []
    js_files: List[Path] = []
    if total_entries == 0:
        return py_files, js_files

    scanned = 0
    bar_length = 40
    stack = [(root, list(root.iterdir()))]
    logger.info("INFO: Scanning files (pruning ignored directories)...")
    while stack:
        parent, children = stack.pop()
        for child in children:
            rel = child.relative_to(root)
            if spec.match_file(str(rel)):
                continue

            scanned += 1
            percent = scanned / total_entries
            filled = int(bar_length * percent)
            bar = "#" * filled + " " * (bar_length - filled)
            # Terminal-only progress update:
            print(
                f"\rScanning files  : [{bar}] {percent * 100:5.1f}%",
                end="",
                flush=True,
            )

            if child.is_dir():
                stack.append((child, list(child.iterdir())))
            elif child.is_file():
                suffix = child.suffix.lower()
                if suffix in PY_EXT:
                    py_files.append(child)
                elif suffix in JS_EXT:
                    js_files.append(child)

    print()  # finish scanning bar
    logger.info(
        f"INFO: Found {
            len(py_files)} Python file(s), {
            len(js_files)} JS/TS file(s)"
    )
    return py_files, js_files


def run(cmd: List[str], *, abort: bool = True) -> None:
    """
    Run *cmd*. If abort is True, exit on failure; otherwise, ignore errors silently.
    """
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


def count_changed(files: List[Path], before: dict[Path, float]) -> int:
    """
    Count how many files have a modified time different from before.
    """
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

    project_root = find_project_root()
    setup_logging(project_root)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    logger.info(f"INFO: Project root: {project_root}")
    spec = load_ignore_spec(project_root)
    py_files, js_files = scan_for_files(project_root, spec)

    if args.dry_run:
        logger.info("INFO: --- Dry-run only ---")
        if py_files:
            logger.info("INFO: Python files:")
            for p in py_files:
                logger.info(f"  {p.relative_to(project_root)}")
        if js_files:
            logger.info("INFO: JS/TS files:")
            for p in js_files:
                logger.info(f"  {p.relative_to(project_root)}")
        return

    # Ensure required tools before proceeding
    if not args.skip_py:
        for tool in ("autoflake", "autopep8", "black", "flake8"):
            ensure_tool(tool)
    if js_files and not args.skip_js:
        ensure_tool("npx")

    # Record mtimes before formatting
    before_mtimes: dict[Path, float] = {}
    for p in py_files + js_files:
        try:
            before_mtimes[p] = p.stat().st_mtime
        except FileNotFoundError:
            before_mtimes[p] = 0

    # Phase 2: Process Python files with a progress bar
    if not args.skip_py and py_files:
        section("Python pipeline")
        total_py = len(py_files)
        bar_length = 40
        print(f"\rFormatting Python: [{' ' * bar_length}]   0.0%", end="", flush=True)

        for idx, p in enumerate(py_files):
            percent = (idx + 1) / total_py
            filled = int(bar_length * percent)
            bar = "#" * filled + " " * (bar_length - filled)
            # Terminal-only progress update:
            print(
                f"\rFormatting Python: [{bar}] {percent * 100:5.1f}%",
                end="",
                flush=True,
            )

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

    # Phase 3: Process JS/TS files with a progress bar
    if not args.skip_js and js_files:
        section("JS/TS pipeline")
        total_js = len(js_files)
        bar_length = 40
        print(f"\rFormatting JS/TS : [{' ' * bar_length}]   0.0%", end="", flush=True)

        for idx, p in enumerate(js_files):
            percent = (idx + 1) / total_js
            filled = int(bar_length * percent)
            bar = "#" * filled + " " * (bar_length - filled)
            # Terminal-only progress update:
            print(
                f"\rFormatting JS/TS : [{bar}] {percent * 100:5.1f}%",
                end="",
                flush=True,
            )
            run(["npx", "eslint", "--fix", str(p)])

        print()  # finish JS/TS progress bar

    # Phase 4: Count changed files and summarize
    all_processed: List[Path] = []
    if not args.skip_py:
        all_processed += py_files
    if not args.skip_js:
        all_processed += js_files

    changed_count = count_changed(all_processed, before_mtimes)
    logger.info(f"INFO: {changed_count} file(s) formatted/modified.")
    logger.info("INFO: Lint/format pipeline finished.")


if __name__ == "__main__":
    main()
