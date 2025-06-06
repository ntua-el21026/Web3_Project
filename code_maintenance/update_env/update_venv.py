#!/usr/bin/env python3
"""
update_venv.py

Upgrade pip and all installed Python packages within the current virtual environment.
Automatically resolves dependency conflicts up to three passes, then logs the final
installed packages and versions to a shared “logs” folder under:
        <project_root>/cache/code_maintenance/update_env/logs/python_log.txt

Usage:
        python3 update_venv.py

Behavior:
1. Uses the virtual environment’s Python interpreter (sys.executable).
2. Ensures pip is available.
3. Upgrades pip itself.
4. Identifies all outdated packages via `pip list --outdated --format=json` and upgrades them.
5. Attempts to resolve dependency conflicts (up to 3 passes) by parsing `pip check` output.
6. Performs a final `pip check` to confirm no conflicts remain.
7. Displays a summary of installed packages with `pip list --format=columns` and appends it
        (along with all other INFO/WARNING/ERROR messages) into:
        <project_root>/cache/code_maintenance/update_env/logs/python_log.txt

Logging:
- INFO logs report progress and summary.
- WARNING logs any failed upgrade attempts for specific packages.
- ERROR logs fatal errors and exits.
- All log messages (console + file) now go into the same shared log under “logs/”.

Requirements:
- Must be run from within an activated virtual environment.
"""

import sys
import subprocess
import json
import logging
import re
from pathlib import Path
from typing import Tuple, List, Optional

# ────────────────────────────────────────────────────────────────────────────────
# Helper to find project root (the directory containing .gitignore)
# ────────────────────────────────────────────────────────────────────────────────


def find_project_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    while True:
        if (current / ".gitignore").is_file():
            return current
        if current == current.parent:
            return None
        current = current.parent


# ────────────────────────────────────────────────────────────────────────────────
# Determine “logs” folder under:
#     <project_root>/cache/code_maintenance/update_env/logs/
# ────────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
proj = find_project_root(SCRIPT_DIR)
if not proj:
    print("[ERROR] .gitignore not found; cannot locate project root.")
    sys.exit(1)

LOG_DIR = proj / "cache" / "code_maintenance" / "update_env" / "logs"
LOG_FILE = "python_log.log"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ────────────────────────────────────────────────────────────────────────────────
# Configure Logging (console + shared log file)
# ────────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("update_venv")
logger.setLevel(logging.INFO)

# Console handler (minimal formatting)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch_formatter = logging.Formatter("%(message)s")
ch.setFormatter(ch_formatter)
logger.addHandler(ch)

# File handler writes into shared logs folder in WRITE mode (truncates existing file)
fh = logging.FileHandler(LOG_DIR / LOG_FILE, mode="w", encoding="utf-8")
fh.setLevel(logging.INFO)
fh_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
)
fh.setFormatter(fh_formatter)
logger.addHandler(fh)

# Total number of high-level steps
TOTAL_STEPS = 6
BAR_LENGTH = 40


def print_global_progress(step: int, description: str) -> None:
    """
    Print a simple global progress bar with `TOTAL_STEPS` segments.
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


def run_subprocess(
    cmd: List[str],
    *,
    capture_output: bool = False,
    check: bool = False,
) -> Tuple[int, str, str]:
    """
    Run a subprocess command. Always returns (returncode, stdout, stderr) as strings.
    If capture_output=False, stdout and stderr will be empty strings.
    """
    try:
        if capture_output:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=check,
            )
            return (result.returncode, result.stdout.strip(), result.stderr.strip())
        else:
            result = subprocess.run(cmd, check=check)
            return (result.returncode, "", "")
    except subprocess.CalledProcessError as e:
        std_out = ""
        std_err = ""
        if hasattr(e, "stdout") and e.stdout is not None:
            std_out = (
                e.stdout.decode("utf-8", errors="ignore").strip()
                if isinstance(e.stdout, bytes)
                else str(e.stdout).strip()
            )
        if hasattr(e, "stderr") and e.stderr is not None:
            std_err = (
                e.stderr.decode("utf-8", errors="ignore").strip()
                if isinstance(e.stderr, bytes)
                else str(e.stderr).strip()
            )
        return (e.returncode, std_out, std_err)
    except FileNotFoundError:
        logger.error(f"Command not found: {' '.join(cmd)}")
        sys.exit(1)


def ensure_pip(python_exe: str) -> None:
    """Step 1: Verify that 'python -m pip' is available."""
    print_global_progress(1, "Verifying pip availability")
    logger.info("Verifying pip availability...")
    cmd = [python_exe, "-m", "pip", "--version"]
    code, out, err = run_subprocess(cmd, capture_output=True)
    if code != 0:
        logger.error(f"pip module not available: {err}")
        sys.exit(1)
    logger.info(f"Using pip: {out}")


def upgrade_pip(python_exe: str) -> None:
    """Step 2: Upgrade pip to the latest version."""
    print_global_progress(2, "Upgrading pip")
    logger.info("Upgrading pip itself...")
    cmd = [python_exe, "-m", "pip", "install", "--quiet", "--upgrade", "pip"]
    code, out, err = run_subprocess(cmd, capture_output=True)
    if code != 0:
        logger.error(f"pip upgrade failed: {err}")
        sys.exit(1)

    # Retrieve new pip version
    cmd_version = [python_exe, "-m", "pip", "--version"]
    code2, out2, err2 = run_subprocess(cmd_version, capture_output=True)
    if code2 == 0:
        parts = out2.split()
        if len(parts) >= 2:
            new_ver = parts[1]
            logger.info(f"pip upgraded to {new_ver}")
        else:
            logger.warning(f"Unexpected pip --version format: '{out2}'")
    else:
        logger.warning(f"Unable to retrieve new pip version: {err2}")


def list_outdated_packages(python_exe: str) -> List[str]:
    """
    Step 3a: Return a list of package names that are outdated.
    Uses `pip list --outdated --format=json` and parses JSON output.
    """
    print_global_progress(3, "Checking outdated packages")
    logger.info("Checking for outdated packages...")
    cmd = [python_exe, "-m", "pip", "list", "--outdated", "--format=json"]
    code, out, err = run_subprocess(cmd, capture_output=True)
    if code != 0:
        logger.error(f"Failed to list outdated packages: {err}")
        sys.exit(1)

    try:
        outdated = json.loads(out)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {e}")
        sys.exit(1)

    pkg_names: List[str] = []
    if isinstance(outdated, list):
        for pkg in outdated:
            name = pkg.get("name")
            if isinstance(name, str):
                pkg_names.append(name)

    if not pkg_names:
        logger.info("All Python packages are already up to date.")
    else:
        logger.info(
            f"Outdated packages detected ({len(pkg_names)}): {', '.join(pkg_names)}"
        )
    return pkg_names


def upgrade_packages(python_exe: str, packages: List[str]) -> None:
    """Step 3b: Upgrade the given list of packages via pip in batches of 10."""
    if not packages:
        return

    logger.info("Upgrading outdated packages...")
    batch_size = 10
    total_batches = (len(packages) + batch_size - 1) // batch_size
    for i in range(total_batches):
        batch = packages[i * batch_size : (i + 1) * batch_size]
        percent = (i + 1) / total_batches
        filled = int(percent * BAR_LENGTH)
        bar = "#" * filled + " " * (BAR_LENGTH - filled)
        print(
            f"\rUpgrading packages: [{bar}] {percent * 100:5.1f}%",
            end="",
            flush=True,
        )

        logger.info(f"  - Upgrading: {', '.join(batch)}")
        cmd = [python_exe, "-m", "pip", "install", "--quiet", "--upgrade"] + batch
        code, _, err = run_subprocess(cmd, capture_output=True)
        if code != 0:
            logger.warning(f"Failed to upgrade batch [{', '.join(batch)}]: {err}")

    # finish package-upgrade sub-bar
    print(f"\rUpgrading packages: [{'#' * BAR_LENGTH}] 100.0%")


def resolve_conflicts(python_exe: str, max_passes: int = 3) -> bool:
    """
    Step 4: Resolve dependency conflicts by parsing `pip check` output.
    For lines like:
    "packageA 1.x has requirement packageB<4.0.0,>=3.18.0, but you have packageB 3.19.0"
    we extract "packageB<4.0.0,>=3.18.0" and attempt to upgrade that requirement.
    """
    print_global_progress(4, "Resolving conflicts")
    conflict_pattern = re.compile(r".*has requirement (.+?), but .+", re.IGNORECASE)

    for attempt in range(1, max_passes + 1):
        logger.info(f"Dependency resolution pass {attempt}...")
        cmd = [python_exe, "-m", "pip", "check"]
        code, out, _ = run_subprocess(cmd, capture_output=True)

        if code == 0:
            logger.info(f"No dependency conflicts detected (pass {attempt}).")
            return True

        conflicts: List[str] = []
        for line in out.splitlines():
            match = conflict_pattern.match(line)
            if match:
                conflicts.append(match.group(1))

        if not conflicts:
            logger.error(
                f"Unexpected pip check output (no 'has requirement' lines):\n{out}"
            )
            return False

        for req in conflicts:
            logger.info(f"  - Upgrading conflicting requirement: {req}")
            cmd_upgrade = [
                python_exe,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--upgrade",
                req,
            ]
            code2, _, err2 = run_subprocess(cmd_upgrade, capture_output=True)
            if code2 != 0:
                logger.warning(f"Failed to upgrade {req}: {err2}")

        if attempt == max_passes:
            logger.error(
                "Unable to fully resolve dependency conflicts after maximum passes."
            )
            return False

    return False


def final_check(python_exe: str) -> bool:
    """Step 5: Perform a final `pip check` to confirm no conflicts remain."""
    print_global_progress(5, "Performing final pip check")
    logger.info("Performing final pip check...")
    cmd = [python_exe, "-m", "pip", "check"]
    code, out, _ = run_subprocess(cmd, capture_output=True)
    if code == 0:
        logger.info("Environment is clean. No dependency conflicts remain.")
        return True
    else:
        logger.error("Dependency conflicts remain—see details below:")
        logger.error(out)
        return False


def show_installed_packages(python_exe: str) -> None:
    """
    Step 6: Display installed packages in columns and append the same output
    to the shared log file under:
    <project_root>/cache/code_maintenance/update_env/logs/python_log.txt
    """
    print_global_progress(6, "Listing installed packages")
    logger.info("Installed package summary:")
    cmd = [python_exe, "-m", "pip", "list", "--format=columns"]
    _, out, _ = run_subprocess(cmd, capture_output=True)

    # Print to console
    print(out)

    # Append summary to the shared log file
    try:
        with (LOG_DIR / LOG_FILE).open("a", encoding="utf-8") as f:
            f.write("\n" + out + "\n")
        logger.info(f"Final package list appended to {LOG_DIR / LOG_FILE}")
    except Exception as e:
        logger.error(f"Failed to write package list to '{LOG_DIR / LOG_FILE}': {e}")


def main() -> None:
    python_exe = sys.executable
    logger.info(f"Using Python interpreter: {python_exe}")

    # Step 1: Verify pip
    ensure_pip(python_exe)

    # Step 2: Upgrade pip itself
    upgrade_pip(python_exe)

    # Step 3: List and upgrade outdated packages
    outdated_pkgs = list_outdated_packages(python_exe)
    if outdated_pkgs:
        upgrade_packages(python_exe, outdated_pkgs)

    # Step 4: Resolve dependency conflicts (up to 3 passes)
    if not resolve_conflicts(python_exe, max_passes=3):
        sys.exit(1)

    # Step 5: Final pip check
    if not final_check(python_exe):
        sys.exit(1)

    # Step 6: Show installed package summary and append to shared log
    show_installed_packages(python_exe)

    logger.info("Python environment upgrade complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)
