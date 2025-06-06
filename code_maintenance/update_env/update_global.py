#!/usr/bin/env python3
"""
update_global.py

Installs, upgrades, and verifies curated global npm packages.
Includes enhanced checks, reporting, and error handling.
Logs everything to both stdout and the shared log at:
    <project_root>/cache/code_maintenance/update_env/logs/global_log.log

Assumes Node.js and npm are already installed (or accessible).
"""

import sys
import subprocess
import shutil
import logging
from pathlib import Path
from typing import List, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Helper to find project root (the directory containing .gitignore)
# ──────────────────────────────────────────────────────────────────────────────


def find_project_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    while True:
        if (current / ".gitignore").is_file():
            return current
        if current == current.parent:
            return None
        current = current.parent


# ──────────────────────────────────────────────────────────────────────────────
# Determine shared log folder under:
#     <project_root>/cache/code_maintenance/update_env/logs/
# ──────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
proj = find_project_root(SCRIPT_DIR)
if not proj:
    print("[ERROR] .gitignore not found; cannot locate project root.")
    sys.exit(1)

LOG_DIR_UPDATE = proj / "cache" / "code_maintenance" / "update_env" / "logs"
LOG_DIR_UPDATE.mkdir(parents=True, exist_ok=True)

LOG_FILE = "global_log.log"
UPDATE_LOG_PATH = LOG_DIR_UPDATE / LOG_FILE

# ──────────────────────────────────────────────────────────────────────────────
# Set up logging (console + shared log file)
# ──────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("update_global")
logger.setLevel(logging.INFO)

# (1) If the log file already exists, truncate it explicitly
if UPDATE_LOG_PATH.exists():
    UPDATE_LOG_PATH.write_text("", encoding="utf-8")

# Console handler (stdout) with minimal formatting
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch_formatter = logging.Formatter("%(message)s")
ch.setFormatter(ch_formatter)
logger.addHandler(ch)

# (2) File handler opens in write mode ("w") to overwrite any existing content
fh_update = logging.FileHandler(UPDATE_LOG_PATH, mode="w", encoding="utf-8")
fh_update.setLevel(logging.INFO)
fh_update_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
)
fh_update.setFormatter(fh_update_formatter)
logger.addHandler(fh_update)


def section(title: str) -> None:
    """
    Logs a simple section header (both console and file).
    """
    logger.info(f"\n[ {title} ]")


def error_exit(message: str) -> None:
    """
    Logs an error-level message and exits with status code 1.
    """
    logger.error(f"ERROR: {message}")
    sys.exit(1)


def cli_name(pkg: str) -> str:
    """
    Map npm package name → CLI binary name (empty if none).
    """
    mapping = {
        "typescript": "tsc",
        "eslint": "eslint",
        "hardhat": "hardhat",
        "npm-check-updates": "ncu",  # `ncu` is the CLI for npm-check-updates
        "lru-cache": "",
        "glob": "",
    }
    return mapping.get(pkg, pkg)


def verify_tool(pkg: str) -> None:
    """
    Verify that the given package’s CLI is on PATH, then log its version.
    If the CLI binary is not found or version cannot be determined, log "not found / N/A".
    """
    cmd = cli_name(pkg)
    if cmd and shutil.which(cmd):
        try:
            completed = subprocess.run(
                [cmd, "--version"], capture_output=True, text=True, check=False
            )
            if completed.stdout:
                version_line = completed.stdout.splitlines()[0].strip()
            else:
                version_line = "unknown"
        except Exception:
            version_line = "unknown"
        logger.info(f"{pkg:<20} {version_line}")
    else:
        logger.info(f"{pkg:<20} not found / N/A")


def detect_sudo_for_npm() -> List[str]:
    """
    Detect whether we need `sudo` to run `npm install -g`.
    Returns a list: either [] (no sudo needed) or ["sudo"] (sudo is needed).
    We do a dry-run of `npm install -g npm@latest`. If it fails (due to permissions),
    we assume sudo is required.
    """
    try:
        dry_run = subprocess.run(
            ["npm", "install", "-g", "npm@latest", "--dry-run"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return [] if dry_run.returncode == 0 else ["sudo"]
    except FileNotFoundError:
        # If npm isn’t installed, prerequisites check will catch it later.
        return []


def run_simple(
    cmd: List[str],
    error_message: str,
    capture_output: bool = False,
) -> str:
    """
    Run a subprocess with the given command list.
    - If capture_output=False: prints stdout/stderr directly (inherits from parent), and exits on failure.
    - If capture_output=True: captures stdout, returns it (str), exits on failure.
    On any non-zero exit code, calls error_exit(error_message).
    """
    try:
        if capture_output:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                error_exit(error_message)
            return completed.stdout.strip()
        else:
            completed = subprocess.run(cmd, check=False)
            if completed.returncode != 0:
                error_exit(error_message)
            return ""
    except FileNotFoundError:
        error_exit(f"Command not found: {' '.join(cmd)}")
    return ""  # type: ignore[unreachable]


def main() -> None:
    # ─────────────────────────────────────────────────────────────
    # 1. Verify prerequisites: node & npm must be available
    # ─────────────────────────────────────────────────────────────
    section("Checking prerequisites")
    if not shutil.which("node"):
        error_exit("Node.js is required but not installed or not on PATH.")
    logger.info("Node.js is installed.")
    if not shutil.which("npm"):
        error_exit("npm is required but not installed or not on PATH.")
    logger.info("npm is installed.")

    # ─────────────────────────────────────────────────────────────
    # 2. Determine whether we need sudo for 'npm install -g'
    # ─────────────────────────────────────────────────────────────
    sudo_cmd = detect_sudo_for_npm()
    if sudo_cmd:
        logger.info(
            "NOTE: global npm installs will be run with sudo (prefix not writable)."
        )
    else:
        logger.info("npm global prefix is writable; no sudo needed.")

    # ─────────────────────────────────────────────────────────────
    # 3. Upgrade npm itself to latest
    # ─────────────────────────────────────────────────────────────
    section("Upgrading npm to latest")
    run_simple(
        sudo_cmd + ["npm", "install", "-g", "npm@latest"], "Failed to upgrade npm."
    )
    new_npm_version = run_simple(
        ["npm", "-v"], "Failed to retrieve npm version.", capture_output=True
    )
    logger.info(f"npm upgraded to {new_npm_version}")

    # ─────────────────────────────────────────────────────────────
    # 4. Define curated global CLI tools to install/upgrade
    # ─────────────────────────────────────────────────────────────
    curated_tools: List[str] = ["typescript", "eslint", "hardhat", "npm-check-updates"]

    section("Installing/upgrading curated global CLI tools")
    total_curated = len(curated_tools)
    bar_length = 40
    for idx, tool in enumerate(curated_tools):
        percent = (idx + 1) / total_curated
        filled = int(bar_length * percent)
        bar = "#" * filled + " " * (bar_length - filled)
        # Terminal-only progress update:
        print(
            f"\rProcessing tools: [{bar}] {percent * 100:5.1f}%  ",
            end="",
            flush=True,
        )

        logger.info(f"\n→ Installing/upgrading {tool}@latest …")
        run_simple(
            sudo_cmd + ["npm", "install", "-g", f"{tool}@latest"],
            f"Failed to install/upgrade {tool}.",
        )
        logger.info(f"  {tool} installed/upgraded.")

    # Ensure final 100% bar
    print(f"\rProcessing tools: [{'#' * bar_length}] 100.0%")
    logger.info("Finished installing/upgrading curated tools.")

    # ─────────────────────────────────────────────────────────────
    # 5. Resolve deprecated npm helpers (glob, lru-cache)
    # ─────────────────────────────────────────────────────────────
    deprecated_helpers: List[str] = ["glob", "lru-cache"]
    section("Installing npm’s deprecated helpers")
    total_deprecated = len(deprecated_helpers)
    for idx, helper in enumerate(deprecated_helpers):
        percent = (idx + 1) / total_deprecated
        filled = int(bar_length * percent)
        bar = "#" * filled + " " * (bar_length - filled)
        # Terminal-only progress update:
        print(
            f"\rProcessing helpers: [{bar}] {percent * 100:5.1f}%  ",
            end="",
            flush=True,
        )

        logger.info(f"\n→ Installing {helper}@latest …")
        run_simple(
            sudo_cmd + ["npm", "install", "-g", f"{helper}@latest"],
            f"Failed to install {helper}.",
        )
        logger.info(f"  {helper} installed.")

    # Ensure final 100% bar
    print(f"\rProcessing helpers: [{'#' * bar_length}] 100.0%")
    logger.info("Finished installing deprecated helpers.")

    # ─────────────────────────────────────────────────────────────
    # 6. Check for any other globally installed packages that are outdated
    # ─────────────────────────────────────────────────────────────
    section("Checking for outdated global packages")
    try:
        outdated_proc = subprocess.run(
            ["npm", "-g", "outdated", "--parseable", "--depth=0"],
            capture_output=True,
            text=True,
            check=False,
        )
        outdated_output = outdated_proc.stdout.strip()
    except FileNotFoundError:
        outdated_output = ""

    if outdated_output:
        logger.info("Outdated packages found:")
        for line in outdated_output.splitlines():
            fields = line.split(":")
            if len(fields) >= 4:
                name, current, latest = fields[1], fields[2], fields[3]
                logger.info(f"  • {name:<20} current: {current}, latest: {latest}")
        section("Upgrading all other global packages")
        run_simple(
            sudo_cmd + ["npm", "-g", "update"],
            "Failed to update other global packages.",
        )
        logger.info("Other global packages upgraded.")
    else:
        logger.info("No other outdated global packages.")

    # ─────────────────────────────────────────────────────────────
    # 7. Verify installation: list versions of each curated tool
    # ─────────────────────────────────────────────────────────────
    section("Verifying installed versions")
    node_version = run_simple(
        ["node", "-v"], "Failed to retrieve node version.", capture_output=True
    )
    npm_version = run_simple(
        ["npm", "-v"], "Failed to retrieve npm version.", capture_output=True
    )
    logger.info(f"node:   {node_version}")
    logger.info(f"npm :   {npm_version}")

    total_verify = len(curated_tools) + len(deprecated_helpers)
    count = 0
    for tool in curated_tools + deprecated_helpers:
        count += 1
        percent = count / total_verify
        filled = int(bar_length * percent)
        bar = "#" * filled + " " * (bar_length - filled)
        # Terminal-only progress update:
        print(f"\rVerifying tools: [{bar}] {percent * 100:5.1f}%  ", end="", flush=True)
        verify_tool(tool)
    print(f"\rVerifying tools: [{'#' * bar_length}] 100.0%")
    logger.info("Finished verifying all tools.")

    # ─────────────────────────────────────────────────────────────
    # 8. Summary of all globally installed packages (depth=0)
    # ─────────────────────────────────────────────────────────────
    section("Global npm packages (depth=0)")
    try:
        summary_proc = subprocess.run(
            ["npm", "list", "-g", "--depth=0"],
            capture_output=True,
            text=True,
            check=False,
        )
        summary = summary_proc.stdout.rstrip()
        print(summary)
        logger.info(summary)
        logger.info("Finished listing all global packages.")
    except FileNotFoundError:
        logger.error("Failed to list global npm packages.")

    # ─────────────────────────────────────────────────────────────
    # 9. Final message
    # ─────────────────────────────────────────────────────────────
    section("Global npm environment setup complete")


if __name__ == "__main__":
    main()
