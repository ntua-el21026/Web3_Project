#!/usr/bin/env python3
"""
update_all.py

Run all “update” Python scripts in sequence, searching for them under
`code_maintenance/` (recursively), pruning via .gitignore, and caching
their last-known locations so we don’t re-scan every run.

The three update scripts in order are:
1. update_global.py   (curated global npm tools)
2. update_venv.py     (upgrade pip and virtual‐env packages)
3. update_node.py     (Node.js version, core Node tools)

This script lives anywhere but will locate the project root (by finding .gitignore),
then find “code_maintenance/” under it, then find “update_env/” under that,
and finally locate each update_*.py file (consulting the cache if present).
Any paths matching .gitignore are skipped. If a cached script path no longer exists,
we re-scan and update the cache.

Logging:
- INFO logs report progress.
- ERROR logs fatal errors and exit.

Each child script now handles its own file‐logging (into
<project_root>/cache/code_maintenance/update_env/logs/<script_name>.log),
so this wrapper only prints progress to the console.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

import pathspec  # make sure `pip install pathspec` is done

# ───────────────────────────────────────────────────────────────────────────────
# Logging (console only, minimal)
# ───────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("update_all")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(ch)

# ───────────────────────────────────────────────────────────────────────────────
# Progress‐bar settings
# ───────────────────────────────────────────────────────────────────────────────
TOTAL_STEPS = 3
BAR_LENGTH = 40

# Names of the update scripts, in the exact order to run:
UPDATE_SCRIPTS = [
    "update_global.py",
    "update_venv.py",
    "update_node.py",
]

# Cache filename (relative to update_env directory)
CACHE_FILENAME = "update_all_cache.json"

# Default .gitignore file(s) to consult at project root:
DEFAULT_IGNORE_FILES = [".gitignore"]
DEFAULT_FOLDER_IGNORES = {"node_modules", ".git"}  # also skip these by name if desired
# ───────────────────────────────────────────────────────────────────────────────


def print_global_progress(step: int, description: str) -> None:
    """
    Print a simple global progress bar for TOTAL_STEPS segments.
    `step` is 1-based index of the current step.
    """
    filled = int((step / TOTAL_STEPS) * BAR_LENGTH)
    bar = "#" * filled + " " * (BAR_LENGTH - filled)
    print(
        f"\rOverall Progress: [{bar}] Step {step}/{TOTAL_STEPS} - {description}",
        end="",
        flush=True,
    )
    print()  # move to next line for detailed logs


def section(title: str) -> None:
    """Log a simple section header."""
    logger.info(f"\n[ {title} ]")


def error_exit(message: str) -> None:
    """Log an error‐level message and exit."""
    logger.error(f"ERROR: {message}")
    sys.exit(1)


def find_project_root(start_path: Path) -> Path:
    """
    Walk upward from `start_path` until we find a directory containing .gitignore.
    Returns that directory or exits if not found.
    """
    current = start_path.resolve()
    while True:
        if (current / ".gitignore").is_file():
            return current
        if current == current.parent:
            logger.error(".gitignore not found; cannot locate project root.")
            sys.exit(1)
        current = current.parent  # type: ignore


def load_gitignore_spec(root: Path) -> pathspec.PathSpec:
    """
    Read .gitignore under `root`, including commented lines.
    For each non‐blank line:
                                                                                                                                                                                                                                                                    - If it begins with '#', strip that '#' and any following spaces → pattern.
                                                                                                                                                                                                                                                                    - Otherwise, strip inline comments after an unescaped '#'.
    If a pattern ends with '/', we:
                                                                                                                                                                                                                                                                    (1) strip the trailing slash and add that as a pattern (to ignore the directory itself)
                                                                                                                                                                                                                                                                    (2) add pattern+'/**' so that everything under that directory is also ignored.

    We also always add ".git" and ".git/**", so the .git folder is never counted.
    """
    gitignore_path = root / ".gitignore"
    raw_patterns: list[str] = []

    if gitignore_path.exists():
        for raw in gitignore_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
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
                if candidate:
                    raw_patterns.append(candidate)

    # Always ignore the .git folder and its contents, even if not in .gitignore
    raw_patterns.append(".git")
    raw_patterns.append(".git/**")

    # Build a final list that transforms "dirname/" → ["dirname", "dirname/**"]
    final_patterns: list[str] = []
    for pat in raw_patterns:
        if pat.endswith("/"):
            stripped = pat.rstrip("/")
            final_patterns.append(stripped)
            final_patterns.append(stripped + "/**")
        else:
            final_patterns.append(pat)

    return pathspec.PathSpec.from_lines("gitwildmatch", final_patterns)


def locate_code_maintenance(
    root: Path, ignore_spec: pathspec.PathSpec
) -> Optional[Path]:
    """Recursively find a folder named 'code_maintenance' under `root`."""
    for p in root.rglob("code_maintenance"):
        rel = p.relative_to(root)
        if ignore_spec.match_file(str(rel)) or p.name in DEFAULT_FOLDER_IGNORES:
            continue
        if p.is_dir():
            return p.resolve()
    return None


def locate_update_env(
    code_maint: Path, ignore_spec: pathspec.PathSpec
) -> Optional[Path]:
    """Recursively find a folder named 'update_env' under `code_maint`."""
    for p in code_maint.rglob("update_env"):
        rel = p.relative_to(code_maint)
        if ignore_spec.match_file(str(rel)) or p.name in DEFAULT_FOLDER_IGNORES:
            continue
        if p.is_dir():
            return p.resolve()
    return None


def scan_for_script(
    script_name: str, base_dir: Path, ignore_spec: pathspec.PathSpec
) -> Optional[Path]:
    """
    Search recursively under `base_dir` for a file named `script_name`,
    skipping anything matching ignore_spec or DEFAULT_FOLDER_IGNORES.
    Returns the first match found, or None if not found.
    """
    for path in base_dir.rglob(script_name):
        rel = path.relative_to(base_dir)
        if (
            ignore_spec.match_file(str(rel))
            or path.parent.name in DEFAULT_FOLDER_IGNORES
        ):
            continue
        if path.is_file():
            return path.resolve()
    return None


def load_cache(cache_file: Path) -> Dict[str, str]:
    """
    Load the JSON cache (mapping script_name -> absolute-path-string)
    from `cache_file`, or return empty dict if the file doesn't exist
    or is invalid.
    """
    if not cache_file.is_file():
        return {}
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_cache(cache_file: Path, data: Dict[str, str]) -> None:
    """
    Write the given `data` (script_name -> absolute-path-string) as JSON
    into `cache_file`.
    """
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to write cache: {e}")


def main():
    # ──────────────────────────────────────────────────────────────────────────
    # 1) Determine project root by finding .gitignore upward from this script.
    # ──────────────────────────────────────────────────────────────────────────
    script_dir = Path(__file__).resolve().parent

    # ──────────────────────────────────────────────────────────────────────────
    # Dummy‐initialize so Pylance knows they're defined (will be overwritten).
    # ──────────────────────────────────────────────────────────────────────────
    project_root: Path = script_dir
    code_maintenance_dir: Path = script_dir
    update_env_dir: Path = script_dir

    # Locate project root
    project_root = find_project_root(script_dir)
    logger.info(f"Project root detected: {project_root}")

    # 2) Load ignore patterns from project root
    ignore_spec = load_gitignore_spec(project_root)

    # ──────────────────────────────────────────────────────────────────────────
    # 3) Locate code_maintenance/ under project root
    # ──────────────────────────────────────────────────────────────────────────
    cm = locate_code_maintenance(project_root, ignore_spec)
    if not cm:
        error_exit("Could not locate 'code_maintenance' under project root.")
    assert cm is not None
    code_maintenance_dir: Path = cm
    logger.info(f"Found code_maintenance at: {code_maintenance_dir}")

    # ──────────────────────────────────────────────────────────────────────────
    # 4) Locate update_env/ under code_maintenance/
    # ──────────────────────────────────────────────────────────────────────────
    ue = locate_update_env(code_maintenance_dir, ignore_spec)
    if not ue:
        error_exit("Could not locate 'update_env' under code_maintenance.")
    assert ue is not None
    update_env_dir: Path = ue
    logger.info(f"Found update_env at: {update_env_dir}")

    # ──────────────────────────────────────────────────────────────────────────
    # 5) Compute cache_dir so that it lives under:
    #       <project_root>/cache/code_maintenance/update_env/
    # ──────────────────────────────────────────────────────────────────────────
    cache_dir = project_root / "cache" / "code_maintenance" / "update_env"
    cache_file = cache_dir / CACHE_FILENAME
    cache_data: Dict[str, str] = load_cache(cache_file)

    # ──────────────────────────────────────────────────────────────────────────
    # 6) For each update script, attempt to use cached path; otherwise re-scan
    # ──────────────────────────────────────────────────────────────────────────
    resolved_paths: Dict[str, str] = {}
    for name in UPDATE_SCRIPTS:
        cached = cache_data.get(name)
        use_path: Optional[Path] = None

        if cached:
            candidate = Path(cached)
            if candidate.is_file():
                # verify candidate is still under project_root and not ignored
                try:
                    rel = candidate.relative_to(project_root)
                    if not ignore_spec.match_file(str(rel)):
                        use_path = candidate
                except Exception:
                    use_path = None

        if use_path is None:
            # re-scan under update_env_dir
            found = scan_for_script(name, update_env_dir, ignore_spec)
            if not found:
                error_exit(
                    f"Could not find required script '{name}' under {update_env_dir}"
                )
            use_path = found

        resolved_paths[name] = str(use_path)

    # 7) Save updated cache (only if changed)
    if resolved_paths != cache_data:
        save_cache(cache_file, resolved_paths)

    # ──────────────────────────────────────────────────────────────────────────
    # 8) Change directory to update_env_dir (so that each script can assume cwd)
    # ──────────────────────────────────────────────────────────────────────────
    try:
        os.chdir(update_env_dir)
    except Exception as e:
        error_exit(f"Could not change directory to '{update_env_dir}': {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # 9) Define run_script() to simply invoke each child; child scripts handle their own logs
    # ──────────────────────────────────────────────────────────────────────────
    def run_script(script_path: Path) -> None:
        """
        Execute the given Python script via the same interpreter.
        If execution fails, abort with error.
        """
        section(f"Running {script_path.name}")
        result = subprocess.run([sys.executable, str(script_path)])
        if result.returncode != 0:
            error_exit(
                f"Script {
                    script_path.name} exited with code {
                    result.returncode}."
            )

    # ──────────────────────────────────────────────────────────────────────────
    # 10) Run each script in order with a progress bar
    # ──────────────────────────────────────────────────────────────────────────
    for idx, name in enumerate(UPDATE_SCRIPTS, start=1):
        print_global_progress(idx, f"Running {name}")
        script_path = Path(resolved_paths[name])
        run_script(script_path)

    # ──────────────────────────────────────────────────────────────────────────
    # 11) All done
    # ──────────────────────────────────────────────────────────────────────────
    section("All updates completed successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_exit(f"Unhandled exception: {e}")
