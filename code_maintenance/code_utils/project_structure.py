#!/usr/bin/env python3
"""
project_structure.py

Generate a directory‐tree report (text + JSON), honoring .gitignore. If `tree`
is installed, use `tree -a -I <patterns> (-J)`; otherwise fall back to a pure‐Python walk.
A progress bar is shown while scanning the filesystem.

Usage:
        ./project_structure.py [--root /path/to/project] [--outdir /output/dir] [--show-summary-only] [--verbose]
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pathspec  # make sure `pip install pathspec` is done

# ───────────────────────────────────────────────────────────────────────────────
DEFAULT_IGNORE_FILES = [".gitignore"]
DEFAULT_FOLDER_IGNORES = {"node_modules", ".git"}
LOG_FORMAT = "%(levelname)s: %(message)s"
# ───────────────────────────────────────────────────────────────────────────────

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
    Read all lines from each ignore file (e.g. .gitignore) under `root`, filter out
    comments and blank lines, and build a PathSpec for matching. Returns a PathSpec.
    """
    all_patterns: List[str] = []

    for name in ignore_files:
        gitignore_path = root / name
        if not gitignore_path.exists():
            continue

        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        for raw in lines:
            line = raw.strip()
            # skip blank or comment
            if not line or line.startswith("#"):
                continue
            all_patterns.append(line)

    if not all_patterns:
        return pathspec.PathSpec.from_lines("gitwildmatch", [])

    spec = pathspec.PathSpec.from_lines("gitwildmatch", all_patterns)
    logger.debug(f"Loaded {len(all_patterns)} ignore patterns from {ignore_files}")
    return spec


def has_tree_command() -> bool:
    """
    Returns True if an external `tree` command is on PATH. We check via `which tree`.
    """
    try:
        return (
            subprocess.run(
                ["which", "tree"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            ).returncode
            == 0
        )
    except Exception:
        return False


def run_tree_command(
    project_root: Path, ignore_spec: pathspec.PathSpec, as_json: bool = False
) -> Optional[str]:
    """
    Invoke `tree -a -I <patterns>` (plus `-J` if as_json=True) in project_root.
    Returns stdout as a string on success, or None if `tree` is not available or fails.
    """
    if not has_tree_command():
        return None

    # Build a “-I” argument out of folder ignores + each basename in .gitignore
    basenames = set(DEFAULT_FOLDER_IGNORES)

    # pathspec keeps its internal patterns in something like tuples (scheme, rawpattern, …)
    # We only need the raw string. So we gather each raw string’s basename.
    for p in getattr(ignore_spec, "patterns", []):  # type: ignore[attr-defined]
        pat: str
        if isinstance(p, tuple):
            # p might be ('gitwildmatch', 'dist/*.py', …)
            pat = p[1]
        else:
            pat = str(p)
        base = Path(pat).name
        if base:
            basenames.add(base)

    ignore_arg = "|".join(sorted(basenames))
    cmd: List[str] = ["tree", "-a", "-I", ignore_arg]
    if as_json:
        cmd.append("-J")

    try:
        proc = subprocess.run(
            cmd, cwd=str(project_root), capture_output=True, text=True, check=True
        )
        return proc.stdout
    except subprocess.CalledProcessError as err:
        logger.error(f"'tree' command failed (exit {err.returncode})")
        return None


def build_tree_pythonic(
    root_dir: Path, ignore_spec: pathspec.PathSpec
) -> Dict[str, Any]:
    """
    Recursively walk `root_dir`, skip anything matching `ignore_spec`,
    and build a nested dict similar to `tree -J`’s output:
    { "name": "<dirname>", "type": "directory", "contents": [ ... ] }
    or if a file:
    { "name": "<filename>", "type": "file" }

    Return the root node as a Dict[str, Any].
    """

    def node_for(path: Path) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"name": path.name}

        if path.is_dir():
            entry["type"] = "directory"
            contents: List[Dict[str, Any]] = []

            for child in sorted(
                path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            ):
                rel = child.relative_to(root_dir)
                if ignore_spec.match_file(str(rel)):
                    continue
                contents.append(node_for(child))

            entry["contents"] = contents
        else:
            entry["type"] = "file"

        return entry

    return node_for(root_dir)


def count_files_and_dirs(tree_node: Dict[str, Any]) -> Tuple[int, int]:
    """
    Given a nested dict (as produced by `tree -J` or build_tree_pythonic),
    recursively count how many nodes have "type"="file" and how many have "type"="directory".
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
    produce a list of ASCII lines that mirror an ASCII 'tree' output. Example:
    project_root/
    ├── file1.py
    ├── subdir/
    │   └── file2.txt
    └── README.md
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
        help="Where to write `project_struct.txt` and `project_struct.json`. Defaults to `<script-dir>/maintain_log`.",
    )
    p.add_argument(
        "--show-summary-only",
        action="store_true",
        help="Skip saving full tree dumps; only print total folders/files.",
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

    # 2) Determine output directory
    if args.outdir:
        output_dir = args.outdir.resolve()
    else:
        output_dir = script_dir / "maintain_log"
    output_dir.mkdir(parents=True, exist_ok=True)

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
        print(f"\rScanning project : [{bar}] {percent * 100:5.1f}%", end="", flush=True)
    print()

    # After scanning, proceed with external tree or fallback
    # ───────────────────────────────────────────────────────────────────────────
    # 5) Generate a textual tree (preferring external `tree` if available)
    # ───────────────────────────────────────────────────────────────────────────
    text_tree_output: Optional[str] = run_tree_command(
        project_root, ignore_spec, as_json=False
    )

    if text_tree_output is not None and not args.show_summary_only:
        txt_path = output_dir / "project_struct.txt"
        save_text_tree(text_tree_output, txt_path)
    else:
        # Fallback to pure‐Python ASCII tree
        logger.debug(
            "External `tree` not found or summary-only was requested. Falling back to Pythonic ASCII."
        )
        pythonic = build_tree_pythonic(project_root, ignore_spec)
        ascii_lines = render_ascii_tree(pythonic, prefix="")
        if not args.show_summary_only:
            txt_path = output_dir / "project_struct.txt"
            save_text_tree("\n".join(ascii_lines), txt_path)

    # ───────────────────────────────────────────────────────────────────────────
    # 6) Generate a JSON tree (prefer `tree -J`, else Pythonic fallback)
    # ───────────────────────────────────────────────────────────────────────────
    json_output_str: Optional[str] = run_tree_command(
        project_root, ignore_spec, as_json=True
    )
    if json_output_str is not None:
        try:
            parsed_list = json.loads(json_output_str)
            if isinstance(parsed_list, list) and parsed_list:
                root_node = parsed_list[0]
            else:
                logger.warning(
                    "Unexpected JSON structure from `tree -J`—using fallback."
                )
                root_node = build_tree_pythonic(project_root, ignore_spec)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse JSON from `tree -J`. Using Pythonic fallback."
            )
            root_node = build_tree_pythonic(project_root, ignore_spec)
    else:
        logger.debug("External `tree -J` not found. Using Pythonic fallback for JSON.")
        root_node = build_tree_pythonic(project_root, ignore_spec)

    if not args.show_summary_only:
        json_path = output_dir / "project_struct.json"
        save_json_tree(root_node, json_path)

    # ───────────────────────────────────────────────────────────────────────────
    # 7) Print summary of total folders + files
    # ───────────────────────────────────────────────────────────────────────────
    total_files, total_dirs = count_files_and_dirs(root_node)
    logger.info(f"Summary: {total_dirs} directories, {total_files} files")


if __name__ == "__main__":
    main()
