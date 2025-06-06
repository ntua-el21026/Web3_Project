#!/usr/bin/env python3
"""
fix_eof.py

Recursively scan a project for “code” files (by extension), skip any paths
that match .gitignore / .eslintignore / .prettierignore—including lines that
start with ‘#’ (optionally with spaces) as ignore patterns—and make sure each
file ends with exactly one newline (no more, no fewer). Files larger than 5 MB
are skipped.

Usage:
                                                                ./fix_eof.py [--root /path/to/project] [--dry-run] [--verbose]

By default, we look for package-lock.json upward from this script’s folder to find
the project root. You can override via --root. A small ENV var cache (PROJECT_ROOT_CACHE)
is set for child processes, but note that it does not persist across separate invocations
unless you explicitly export it in your shell.
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import List

try:
    from pathspec import PathSpec
except ImportError:
    print("ERROR: You need to install the pathspec module:\n    pip install pathspec")
    sys.exit(1)

# ───────────────────────────────────────────────────────────────────────────────
# === Configuration ===
CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".html",
    ".css",
    ".scss",
    ".sql",
    ".md",
    ".sh",
    ".yaml",
    ".yml",
    ".env",
    ".xml",
    ".sol",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".java",
    ".kt",
    ".swift",
    ".dart",
    ".txt",
    ".cfg",
    ".ini",
}
IGNORE_FILES = [".gitignore", ".eslintignore", ".prettierignore"]
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
ENV_VAR = "PROJECT_ROOT_CACHE"

# Pre-compiled regex: strip any combination of CR/LF at EOF
RE_TRAILING_NEWLINES = re.compile(r"[\r\n]+$")
# ───────────────────────────────────────────────────────────────────────────────

# ───────────────────────────────────────────────────────────────────────────────
# Helper: find project root by locating package-lock.json
# ───────────────────────────────────────────────────────────────────────────────


def find_project_root(start_path: Path) -> Path:
    """
    Walk upward from start_path until we find a package-lock.json file.
    Return the containing directory. Raises FileNotFoundError if none found.
    """
    current = start_path.resolve()
    while current != current.parent:
        if (current / "package-lock.json").exists():
            return current
        current = current.parent
    raise FileNotFoundError("No package-lock.json found in any parent directory.")


# ───────────────────────────────────────────────────────────────────────────────
# Logging setup: console + shared “logs” folder in update_env
# ───────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
try:
    # Either use cached ENV var, or search upward, then store back to ENV
    env_root = os.getenv(ENV_VAR)
    if env_root and Path(env_root).exists():
        PROJECT_ROOT = Path(env_root).resolve()
    else:
        PROJECT_ROOT = find_project_root(SCRIPT_DIR)
        os.environ[ENV_VAR] = str(PROJECT_ROOT)
except FileNotFoundError as e:
    print(f"ERROR: {e}")
    sys.exit(1)

LOG_DIR = PROJECT_ROOT / "cache" / "code_maintenance" / "code_utils" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "fix_eof.log"

logger = logging.getLogger("fix_eof")
logger.setLevel(logging.INFO)

# Console handler (minimal formatting)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(ch)

# File handler (timestamps) writing into shared logs folder
fh = logging.FileHandler(LOG_PATH, mode="a", encoding="utf-8")
fh.setLevel(logging.INFO)
fh.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
)
logger.addHandler(fh)


# ───────────────────────────────────────────────────────────────────────────────
def load_combined_ignore_spec(root: Path) -> PathSpec:
    """
    Read all ignore files (IGNORE_FILES) under 'root', accumulate patterns:
                                                                    - If a line’s first non-whitespace character is '#', treat everything after
                                                                    that '#' as a literal ignore pattern.
                                                                    - Otherwise, strip inline comments (anything after an unescaped '#') and skip blank lines.
    For any pattern ending in '/', also add 'pattern/**' so that all children are ignored.
    Finally, ALWAYS ignore '.git' and '.git/**'.
    """
    patterns: List[str] = []

    for fname in IGNORE_FILES:
        ignore_path = root / fname
        if not ignore_path.exists():
            continue

        for raw_line in ignore_path.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue

            stripped = raw_line.lstrip()
            if stripped.startswith("#"):
                # Entire line is a comment → take everything after '#'
                pat = stripped[1:].strip()
                if pat:
                    patterns.append(pat)
                continue

            # Otherwise, strip inline comment
            if "#" in raw_line:
                pat = raw_line.split("#", 1)[0].rstrip()
            else:
                pat = raw_line.rstrip()
            pat = pat.strip()
            if pat:
                patterns.append(pat)

    # Always ignore .git/ directory and its contents, even if not in .gitignore
    patterns.append(".git")
    patterns.append(".git/**")

    # Build a new list so that "dirname/" → ["dirname", "dirname/**"]
    final_patterns: List[str] = []
    for pat in patterns:
        if pat.endswith("/"):
            base = pat.rstrip("/")
            final_patterns.append(base)
            final_patterns.append(f"{base}/**")
        else:
            final_patterns.append(pat)

    return PathSpec.from_lines("gitwildmatch", final_patterns)


def is_code_file(path: Path) -> bool:
    """
    Return True if 'path' has a “code” extension that we care about.
    """
    return path.suffix.lower() in CODE_EXTENSIONS


def ensure_single_final_newline(file_path: Path) -> bool:
    """
    Read the entire file. If its size ≤ MAX_FILE_SIZE and it does not already
    end with exactly one newline, rewrite it so that it ends with exactly one newline.

    Returns True if the file was fixed, False otherwise.
    """
    try:
        size = file_path.stat().st_size
    except OSError:
        return False

    if size > MAX_FILE_SIZE:
        return False

    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False

    # 1. Strip all trailing CR and LF characters
    stripped = RE_TRAILING_NEWLINES.sub("", content)

    # 2. Append exactly one '\n'
    new_content = stripped + "\n"

    # 3. If new_content differs from original, write it back
    if new_content != content:
        try:
            file_path.write_text(new_content, encoding="utf-8")
        except OSError:
            return False
        return True

    return False


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments:
                                                                    --root PATH    : override project root (skip package-lock.json search)
                                                                    --dry-run      : only show which files would be modified
                                                                    --verbose      : enable DEBUG logging (very verbose)
    """
    p = argparse.ArgumentParser(
        description="Ensure each code file ends with exactly one newline (no extras)."
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "Explicit project root. If omitted, we look upward from this script’s folder "
            "for package-lock.json."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show summary without modifying any files.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging (for troubleshooting).",
    )
    return p.parse_args()


def main():
    args = parse_args()

    # Adjust logger level if verbose requested
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    # Determine project root (again, in case --root was used)
    script_dir = Path(__file__).resolve().parent
    if args.root is not None:
        project_root = args.root.resolve()
    else:
        try:
            project_root = PROJECT_ROOT
        except NameError:
            try:
                project_root = find_project_root(script_dir)
            except FileNotFoundError as e:
                logger.error(f"ERROR: {e}")
                sys.exit(1)

    logger.info(f"[ Project root: {project_root} ]")

    ignore_spec = load_combined_ignore_spec(project_root)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1: Scanning all filesystem entries under project_root
    # But prune ignored directories so we don't descend into them
    # Show a progress bar while building the list of code files.
    # Do NOT log each bar update—only print to the terminal.
    # ─────────────────────────────────────────────────────────────────────────
    code_files: List[Path] = []

    # First pass: count how many entries we will examine (excluding pruned subtrees)
    total_entries = 0
    stack = [(project_root, list(project_root.iterdir()))]
    while stack:
        parent, children = stack.pop()
        for child in children:
            rel_child = child.relative_to(project_root)
            if ignore_spec.match_file(str(rel_child)):
                continue
            total_entries += 1
            if child.is_dir():
                stack.append((child, list(child.iterdir())))

    collected = 0
    if total_entries > 0:
        logger.info("INFO: Scanning entries (pruning ignored directories)...")
        stack = [(project_root, list(project_root.iterdir()))]
        bar_length = 40
        while stack:
            parent, children = stack.pop()
            for child in children:
                rel_child = child.relative_to(project_root)
                if ignore_spec.match_file(str(rel_child)):
                    continue

                # Update scanning progress bar in terminal only:
                collected += 1
                percent = collected / total_entries
                filled = int(bar_length * percent)
                bar = "#" * filled + " " * (bar_length - filled)
                print(
                    f"\rScanning entries: [{bar}] {
                        percent * 100:5.1f}%",
                    end="",
                    flush=True,
                )

                if child.is_dir():
                    stack.append((child, list(child.iterdir())))
                elif child.is_file() and is_code_file(child):
                    code_files.append(child)

        print()  # Finish scanning progress bar

    logger.info(f"INFO: Found {len(code_files)} code file(s) to check.")

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2: Fixing each code file
    # Show a progress bar while applying ensure_single_final_newline()
    # Do NOT log each bar update—only print to the terminal.
    # ─────────────────────────────────────────────────────────────────────────
    fixed_count = 0
    total_files = len(code_files)

    if total_files == 0:
        logger.info("INFO: No code files to process.")
    else:
        logger.info("INFO: Fixing EOF on code files...")
        bar_length = 40

        # Print initial “0%” bar in terminal only
        empty_bar = " " * bar_length
        print(f"\rProcessing files : [{empty_bar}]   0.0%", end="", flush=True)

        for idx, file_path in enumerate(code_files):
            percent = (idx + 1) / total_files
            filled = int(bar_length * percent)
            bar = "#" * filled + " " * (bar_length - filled)
            print(
                f"\rProcessing files : [{bar}] {percent * 100:5.1f}%",
                end="",
                flush=True,
            )

            if not args.dry_run and ensure_single_final_newline(file_path):
                fixed_count += 1

        print()  # Finish fixing progress bar

        logger.info(f"\n[ Scanned {total_files} files; fixed {fixed_count} files ]")
        if args.dry_run:
            logger.info("[ Dry-run mode: no files were modified ]")


if __name__ == "__main__":
    main()
