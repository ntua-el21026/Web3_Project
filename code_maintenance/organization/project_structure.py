#!/usr/bin/env python3
"""
project_structure.py

Generate a directory‐tree report (text + JSON), honoring .gitignore.
We always use a pure‐Python walk so that .gitignore is 100% respected.
A progress bar is shown while scanning the filesystem.

Usage:
        ./project_structure.py [--root /path/to/project]
                                                        [--outdir /output/dir]
                                                        [--show-summary-only]
                                                        [--verbose]
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pathspec  # make sure `pip install pathspec` is done

# ───────────────────────────────────────────────────────────────────────────────
DEFAULT_IGNORE_FILES = [".gitignore"]
DEFAULT_FOLDER_IGNORES = {"node_modules", ".git"}  # skip these by basename too
LOG_FORMAT = "%(levelname)s: %(message)s"
# ───────────────────────────────────────────────────────────────────────────────

# Initial console‐only logger setup
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


def find_project_root(start_path: Path, marker: str = "package-lock.json") -> Path:
    """
    Walk upward from `start_path` until a directory contains `marker`.
    Returns that directory. Raises FileNotFoundError if not found.
    """
    current = start_path.resolve()
    while current != current.parent:
        if (current / marker).exists():
            logger.debug(f"Found project root at {current} (via {marker})")
            return current
        current = current.parent
    raise FileNotFoundError(f"No {marker} found in any parent of {start_path}")


def load_gitignore_patterns(root: Path, ignore_files: List[str]) -> pathspec.PathSpec:
    """
    Read lines from each ignore file (e.g. .gitignore) under `root`. For each line:
            - Skip blank lines or those starting with '#'.
            - If a pattern ends with '/', emit two patterns:
                    1) pattern.rstrip('/')
                    2) pattern.rstrip('/') + '/**'
            so the directory itself and everything under it are ignored.
            - Otherwise, emit the pattern as-is.

    Returns a PathSpec (gitwildmatch) built from all these patterns.
    """
    all_patterns: List[str] = []

    for name in ignore_files:
        gitignore_path = root / name
        if not gitignore_path.exists():
            continue

        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            if line.endswith("/"):
                dir_pat = line.rstrip("/")
                all_patterns.append(dir_pat)
                all_patterns.append(f"{dir_pat}/**")
            else:
                all_patterns.append(line)

    if not all_patterns:
        return pathspec.PathSpec.from_lines("gitwildmatch", [])

    spec = pathspec.PathSpec.from_lines("gitwildmatch", all_patterns)
    logger.debug(
        f"Loaded {
            len(all_patterns)} ignore patterns (including ‘/**’ expansions)"
    )
    return spec


def build_tree_pythonic(
    root_dir: Path, ignore_spec: pathspec.PathSpec
) -> Dict[str, Any]:
    """
    Recursively walk `root_dir`, skipping anything matching `ignore_spec`,
    and build a nested dict that mirrors `tree -J` output:
            { "name": "<dirname>", "type": "directory", "contents": [ ... ] }
    for directories, or
            { "name": "<filename>", "type": "file" }
    for files.

    Any path (file or directory) whose relative path matches `ignore_spec` is skipped.
    """

    def node_for(path: Path) -> Optional[Dict[str, Any]]:
        rel = path.relative_to(root_dir)
        # If this path matches .gitignore or is in DEFAULT_FOLDER_IGNORES, skip it:
        if ignore_spec.match_file(str(rel)) or path.name in DEFAULT_FOLDER_IGNORES:
            return None

        entry: Dict[str, Any] = {"name": path.name}
        if path.is_dir():
            entry["type"] = "directory"
            contents: List[Dict[str, Any]] = []
            for child in sorted(
                path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            ):
                child_node = node_for(child)
                if child_node is not None:
                    contents.append(child_node)
            entry["contents"] = contents
        else:
            entry["type"] = "file"
        return entry

    root_node = node_for(root_dir)
    # If somehow the root itself is ignored, return an empty directory node
    if root_node is None:
        return {"name": root_dir.name, "type": "directory", "contents": []}
    return root_node


def count_files_and_dirs(tree_node: Dict[str, Any]) -> Tuple[int, int]:
    """
    Given a nested dict (as produced by `tree -J` or build_tree_pythonic),
    count how many nodes have "type"="file" vs "type"="directory".
    Returns (file_count, dir_count).
    """
    files = 0
    dirs = 0

    def recurse(node: Dict[str, Any]):
        nonlocal files, dirs
        t: str = node.get("type", "")
        if t == "directory":
            dirs += 1
            for child in node.get("contents", []):
                recurse(child)
        elif t == "file":
            files += 1

    recurse(tree_node)
    return files, dirs


def render_ascii_tree(node: Dict[str, Any], prefix: str = "") -> List[str]:
    """
    Given a single directory node (with keys "name", "type", and optional "contents"),
    produce a list of ASCII lines that mirror the output of `tree`.
    """
    lines: List[str] = []
    name = node["name"]
    if node["type"] == "directory":
        lines.append(f"{prefix}{name}/")
        children = node.get("contents", [])
        for idx, child in enumerate(children):
            is_last = idx == len(children) - 1
            branch = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "
            subprefix = prefix + branch
            if child["type"] == "directory":
                lines.append(f"{subprefix}{child['name']}/")
                deeper = render_ascii_tree(child, prefix + extension)
                # Skip the child's first line (its own "name/") because we just printed
                # it
                lines.extend(deeper[1:])
            else:
                lines.append(f"{subprefix}{child['name']}")
    else:
        lines.append(f"{prefix}{name}")
    return lines


def save_text_tree(text: str, path: Path) -> None:
    path.write_text(text, encoding="utf-8")
    logger.info(f"Wrote text tree to: {path}")


def save_json_tree(data: Dict[str, Any], path: Path) -> None:
    pretty = json.dumps(data, indent=2)
    path.write_text(pretty, encoding="utf-8")
    logger.info(f"Wrote JSON tree to: {path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate a directory-tree report (text + JSON) that respects .gitignore."
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "Explicit project root. If omitted, we search upward from this script’s location "
            "for `package-lock.json`."
        ),
    )
    p.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help="Where to write `project_struct.txt` and `project_struct.json`. "
        "Defaults to `<script-dir>/organization_log`.",
    )
    p.add_argument(
        "--show-summary-only",
        action="store_true",
        help="Skip saving full tree dumps and only print total folders/files.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return p.parse_args()


def main():
    args = parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    script_path = Path(__file__).resolve()
    script_dir = script_path.parent

    # 1) Determine project_root
    if args.root:
        project_root = args.root.resolve()
        logger.debug(f"Using explicit project root: {project_root}")
    else:
        try:
            project_root = find_project_root(script_path)
        except FileNotFoundError as err:
            logger.error(err)
            sys.exit(1)

    logger.info(f"Project root detected: {project_root}")

    # ─────────────────────────────────────────────────────────────────────────────
    # Configure file logging under:
    #    <project_root>/cache/code_maintenance/organization/logs/project_structure.log
    # ─────────────────────────────────────────────────────────────────────────────
    log_dir = project_root / "cache" / "code_maintenance" / "organization" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "project_structure.log"

        # If the log file already exists, truncate it (delete previous contents)
        if log_file.exists():
            log_file.write_text("", encoding="utf-8")

        fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
            )
        )
        logger.addHandler(fh)
        logger.info(f"Logging to file: {log_file}")
    except Exception as e:
        logger.error(f"Could not configure file logging: {e}")
        # Continue without file logging if it fails

    # 2) Determine output directory
    if args.outdir:
        output_dir = args.outdir.resolve()
    else:
        output_dir = script_dir / "organization_log"
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {output_dir}")

    # 3) Load .gitignore patterns
    ignore_spec = load_gitignore_patterns(project_root, DEFAULT_IGNORE_FILES)

    # ───────────────────────────────────────────────────────────────────────────
    # 4) Scan all filesystem entries with a progress bar
    # ───────────────────────────────────────────────────────────────────────────
    all_entries: List[Path] = list(project_root.rglob("*"))
    total_entries = len(all_entries)
    if total_entries == 0:
        logger.error("No files or directories found under project root.")
        sys.exit(1)

    bar_length = 40
    for idx, path in enumerate(all_entries):
        percent = (idx + 1) / total_entries
        filled = int(bar_length * percent)
        bar = "#" * filled + " " * (bar_length - filled)
        # Terminal-only progress update:
        print(f"\rScanning project : [{bar}] {percent * 100:5.1f}%", end="", flush=True)
    print()

    # 5) Build the pure-Python tree so that ignore_spec is fully respected
    pythonic_root = build_tree_pythonic(project_root, ignore_spec)

    # 5.5) Count files & dirs right away, so we can insert into the text file later
    total_files, total_dirs = count_files_and_dirs(pythonic_root)

    # ───────────────────────────────────────────────────────────────────────────
    # 6) Generate text tree (and include the totals at the bottom)
    # ───────────────────────────────────────────────────────────────────────────
    if not args.show_summary_only:
        ascii_lines = render_ascii_tree(pythonic_root, prefix="")

        # Append a blank line and then the summary at the end of the text output:
        ascii_lines.append("")  # blank line
        ascii_lines.append(
            f"Total directories: {total_dirs}, Total files: {total_files}"
        )

        txt_path = output_dir / "project_struct.txt"
        save_text_tree("\n".join(ascii_lines), txt_path)

    # ───────────────────────────────────────────────────────────────────────────
    # 7) Generate JSON tree
    # ───────────────────────────────────────────────────────────────────────────
    if not args.show_summary_only:
        json_path = output_dir / "project_struct.json"
        save_json_tree(pythonic_root, json_path)

    # ───────────────────────────────────────────────────────────────────────────
    # 8) Print summary of total folders + files (only non-ignored) to stdout + log
    # ───────────────────────────────────────────────────────────────────────────
    logger.info(f"Summary: {total_dirs} directories, {total_files} files")
    print(f"Total directories: {total_dirs}, Total files: {total_files}")


if __name__ == "__main__":
    main()
