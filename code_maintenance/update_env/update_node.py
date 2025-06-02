#!/usr/bin/env python3
"""
update_node.py

Full Maintenance Script:

1. Locate project root by finding package.json (walking up from current directory).
2. Verify prerequisites: curl, git, jq, npm.
3. Install or update NVM to the latest tagged release.
4. Ensure shell profile sources NVM (modify ~/.bashrc, ~/.zshrc, or ~/.profile as needed).
5. Load NVM and install/use the latest LTS Node.js version.
6. Upgrade npm itself to the latest version.
7. Upgrade global npm packages (if any are outdated).
8. Print installed versions and global-package summary.
9. Upgrade direct dependencies/devDependencies in package.json:
        - Respect "overrides": force-bump those packages.
        - For others, bump if latest satisfies peerDependencies.
        - Auto-align react & react-dom minor/major versions.
        - Write changes and run `npm install --legacy-peer-deps` (fallback to `--force`), then `npm dedupe`.
10. Run `npm audit --omit=dev` and warn if vulnerabilities remain.

All output is logged to:
<script_directory>/update_log/node_log.txt

Logging:
- INFO: progress and summaries
- WARNING: non-fatal issues
- ERROR: fatal issues and exit

Usage:
Simply run this script from anywhere. It will locate package.json, cd to that directory,
then perform all maintenance steps.

Requirements:
- Python 3.7+
- Virtual environment is optional
- “bash” shell available
"""

import sys
import subprocess
import logging
import shutil
import json
import os
from pathlib import Path
from typing import Dict, Tuple, List, Optional

# ────────────────────────────────────────────────────────────────────────────────
# Configure Logging (stdout + file)
# ────────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
LOG_DIR = SCRIPT_DIR / "update_log"
LOG_PATH = LOG_DIR / "node_log.txt"

# ensure update_log exists
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

# Total number of high-level steps
TOTAL_STEPS = 10
BAR_LENGTH = 40


def print_global_progress(step: int, description: str) -> None:
    """
    Print a simple global progress bar with `TOTAL_STEPS` segments.
    `step` is 1-based index of the current step.
    """
    filled = int((step / TOTAL_STEPS) * BAR_LENGTH)
    bar = "#" * filled + " " * (BAR_LENGTH - filled)
    # \r to overwrite the same line, flush so it appears immediately.
    print(
        f"\rOverall Progress: [{bar}] Step {step}/{TOTAL_STEPS} - {description}",
        end="",
        flush=True,
    )
    # After printing, move to next line for detailed logs
    print()


def run_cmd(
    cmd: List[str],
    *,
    cwd: Optional[Path] = None,
    capture_output: bool = False,
    check: bool = False,
    use_bash_login: bool = False,
) -> Tuple[int, str, str]:
    """
    Run a subprocess command.
    - If use_bash_login=True, wrap command as: bash -lc "<cmd...>"
            so that NVM (sourced in .bashrc/.zshrc) is available.
    - capture_output: capture stdout and stderr, return as strings.
    - check: if True, CalledProcessError is raised on non-zero exit.
    Returns (returncode, stdout_str, stderr_str).
    """
    if use_bash_login:
        inner = " ".join(cmd)
        full_cmd = ["bash", "-lc", inner]
    else:
        full_cmd = cmd

    try:
        if capture_output:
            result = subprocess.run(
                full_cmd,
                cwd=str(cwd) if cwd else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=check,
            )
            return (result.returncode, result.stdout.strip(), result.stderr.strip())
        else:
            result = subprocess.run(
                full_cmd, cwd=str(cwd) if cwd else None, check=check
            )
            return (result.returncode, "", "")
    except subprocess.CalledProcessError as e:
        stdout = e.stdout.strip() if isinstance(e.stdout, str) else ""
        stderr = e.stderr.strip() if isinstance(e.stderr, str) else ""
        return (e.returncode, stdout, stderr)
    except FileNotFoundError:
        logging.error(f"Command not found: {full_cmd[0]}")
        sys.exit(1)


def detect_shell_profile() -> Path:
    """
    Detect which shell profile file to update:
    - If ZSH and ~/.zshrc exists, use that
    - Else if BASH and ~/.bashrc exists, use that
    - Else if ~/.profile exists, use that
    Raises RuntimeError if none found.
    """
    home = Path.home()
    if "ZSH_VERSION" in os.environ and (home / ".zshrc").is_file():
        return home / ".zshrc"
    if "BASH_VERSION" in os.environ and (home / ".bashrc").is_file():
        return home / ".bashrc"
    if (home / ".profile").is_file():
        return home / ".profile"
    raise RuntimeError(
        "Could not detect a shell profile (e.g., .bashrc, .zshrc, or .profile)."
    )


def find_project_root() -> Path:
    """
    Walk up from current working directory until a directory containing package.json is found.
    Returns that directory Path. Exits on failure.
    """
    dir_path = Path.cwd()
    while dir_path != dir_path.parent:
        if (dir_path / "package.json").is_file():
            return dir_path
        dir_path = dir_path.parent
    logging.error("package.json not found; cannot locate project root.")
    sys.exit(1)


def verify_prerequisites() -> None:
    """
    Ensure required commands (curl, git, jq, npm) are available. Exit on missing.
    """
    required = ["curl", "git", "jq", "npm"]
    missing = []
    for exe in required:
        if shutil.which(exe) is None:
            missing.append(exe)
    if missing:
        logging.error(f"Missing prerequisites: {', '.join(missing)}")
        sys.exit(1)
    logging.info("All prerequisites found: curl, git, jq, npm.")


def install_or_update_nvm(step: int) -> None:
    """
    Step 3: Install or update NVM to the latest tagged release under ~/.nvm.
    Update shell profile to source NVM if needed.
    """
    print_global_progress(step, "Install/update NVM")
    logging.info("Installing or updating NVM...")
    home = Path.home()
    nvm_dir = home / ".nvm"
    nvm_git_url = "https://github.com/nvm-sh/nvm.git"

    # 1. Fetch latest tag
    code, out, err = run_cmd(
        [
            "git",
            "-c",
            "versionsort.suffix=-",
            "ls-remote",
            "--exit-code",
            "--refs",
            "--sort=version:refname",
            "--tags",
            nvm_git_url,
            "*.*.*",
        ],
        capture_output=True,
    )
    if code != 0 or not out:
        logging.error("Failed to detect latest NVM tag from GitHub.")
        sys.exit(1)

    latest_tag = out.splitlines()[-1].split("/")[-1]
    if not latest_tag:
        logging.error("Parsed empty NVM tag.")
        sys.exit(1)

    if not nvm_dir.is_dir():
        logging.info(f"NVM not found. Cloning {latest_tag} into {nvm_dir} …")
        code, _, err = run_cmd(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                latest_tag,
                nvm_git_url,
                str(nvm_dir),
            ]
        )
        if code != 0:
            logging.error(f"git clone failed: {err}")
            sys.exit(1)
    else:
        logging.info(f"NVM directory exists. Fetching and checking out {latest_tag} …")
        code, _, err = run_cmd(
            ["git", "fetch", "--depth", "1", "origin", latest_tag], cwd=nvm_dir
        )
        if code != 0:
            logging.error(f"git fetch failed in {nvm_dir}: {err}")
            sys.exit(1)
        code, _, err = run_cmd(["git", "checkout", latest_tag], cwd=nvm_dir)
        if code != 0:
            logging.error(f"git checkout {latest_tag} failed: {err}")
            sys.exit(1)

    # 2. Ensure shell profile sources NVM
    try:
        profile = detect_shell_profile()
    except RuntimeError as e:
        logging.error(str(e))
        sys.exit(1)

    source_line = (
        f"\n# === Load NVM ===\n"
        f'export NVM_DIR="{nvm_dir}"\n'
        f'[ -s "{nvm_dir}/nvm.sh" ] && . "{nvm_dir}/nvm.sh"  # This loads nvm\n'
    )

    profile_text = profile.read_text(encoding="utf-8", errors="ignore")
    if "NVM_DIR" not in profile_text:
        logging.info(f"Adding NVM source to {profile}")
        try:
            with profile.open("a", encoding="utf-8") as f:
                f.write(source_line)
        except Exception as e:
            logging.error(f"Failed to append to {profile}: {e}")
            sys.exit(1)
    else:
        logging.info(f"NVM source already present in {profile}")

    logging.info("NVM installation/update complete.")


def ensure_latest_lts_node(step: int) -> None:
    """
    Step 5: Using NVM, install or use the latest LTS Node.js version.
    """
    print_global_progress(step, "Ensure latest LTS Node.js")
    logging.info("Ensuring latest LTS Node.js via NVM…")

    code, out, err = run_cmd(
        ["nvm", "ls-remote", "--lts"], capture_output=True, use_bash_login=True
    )
    if code != 0 or not out:
        logging.error(f"Failed to list remote LTS versions: {err}")
        sys.exit(1)

    last_line = out.splitlines()[-1].strip()
    if not last_line:
        logging.error("No LTS versions found in nvm ls-remote output.")
        sys.exit(1)

    latest_lts = last_line.split()[0]
    logging.info(f"Latest LTS version detected: {latest_lts}")

    code, current_node, err = run_cmd(
        ["nvm", "current"], capture_output=True, use_bash_login=True
    )
    current_node = current_node.strip()
    if current_node != latest_lts:
        logging.info(f"Installing Node.js {latest_lts} (latest LTS)…")
        code, _, err = run_cmd(
            ["nvm", "install", "--lts"], capture_output=True, use_bash_login=True
        )
        if code != 0:
            logging.error(f"Failed to install Node.js {latest_lts}: {err}")
            sys.exit(1)
    else:
        logging.info(f"Already using Node.js {current_node} (latest LTS)")

    run_cmd(["nvm", "alias", "default", "lts/*"], use_bash_login=True)
    run_cmd(["nvm", "use", "default"], use_bash_login=True)
    logging.info("Node.js LTS setup complete.")


def upgrade_npm(step: int) -> None:
    """
    Step 6: Upgrade npm itself to the latest version globally.
    """
    print_global_progress(step, "Upgrade npm")
    logging.info("Upgrading npm to the latest version…")
    code, out, err = run_cmd(
        ["npm", "install", "-g", "npm@latest"], capture_output=True
    )
    if code != 0:
        logging.error(f"npm upgrade failed: {err}")
        sys.exit(1)
    code, npm_ver, err = run_cmd(["npm", "-v"], capture_output=True)
    if code == 0:
        logging.info(f"npm successfully upgraded to {npm_ver}")
    else:
        logging.warning(f"Could not verify npm version: {err}")


def upgrade_global_packages(step: int) -> None:
    """
    Step 7: Upgrade any outdated global npm packages (depth=0).
    """
    print_global_progress(step, "Upgrade global npm packages")
    logging.info("Checking for outdated global npm packages…")
    code, out, err = run_cmd(
        ["npm", "-g", "outdated", "--parseable", "--depth=0"], capture_output=True
    )
    outdated = out.strip().splitlines()
    if outdated and not (len(outdated) == 1 and outdated[0] == ""):
        logging.info("Outdated global packages detected:")
        for line in outdated:
            parts = line.split(":")
            if len(parts) >= 4:
                logging.info(
                    f"  • {
                        parts[1]} (current: {
                        parts[2]}, latest: {
                        parts[3]})"
                )
        logging.info("Updating global packages…")
        code, _, err = run_cmd(["npm", "-g", "update"], capture_output=True)
        if code != 0:
            logging.error(f"Global npm update failed: {err}")
            sys.exit(1)
        logging.info("Global npm packages updated successfully.")
    else:
        logging.info("All global npm packages are up to date.")


def print_installed_versions(step: int) -> None:
    """
    Step 8: Print and log installed versions of nvm, node, npm, and global packages summary.
    """
    print_global_progress(step, "Print installed versions")
    logging.info("Installed versions and global packages summary:")
    commands = [
        (["nvm", "--version"], True),
        (["node", "-v"], False),
        (["npm", "-v"], False),
        (["npm", "list", "-g", "--depth=0"], False),
    ]
    total = len(commands)
    for idx, (command, use_bash) in enumerate(commands, start=1):
        percent = idx / total
        filled = int(percent * BAR_LENGTH)
        bar = "#" * filled + " " * (BAR_LENGTH - filled)
        print(
            f"\rVerifying versions: [{bar}] {
                percent *
                100:5.1f}%  ",
            end="",
            flush=True,
        )

        if command[0] == "nvm":
            code, out, err = run_cmd(command, capture_output=True, use_bash_login=True)
        else:
            code, out, err = run_cmd(command, capture_output=True)

        if code == 0:
            for line in out.splitlines():
                logging.info(f"  {line}")
        else:
            logging.warning(f"Failed to run '{' '.join(command)}': {err}")

    print(f"\rVerifying versions: [{'#' * BAR_LENGTH}] 100.0%")
    logging.info("Finished printing installed versions.")


def bump_dependencies(project_root: Path, step: int) -> None:
    """
    Step 9: Upgrade direct dependencies/devDependencies in package.json under project_root:
    - Respect "overrides" field: force-bump those packages to ^latest.
    - For other deps, bump if latest satisfies peerDependencies.
    - Auto-align react & react-dom minor/major if mismatched.
    - If changes made, write back and run npm install; else remove temp.
    """
    print_global_progress(step, "Bump dependencies")
    logging.info("Upgrading direct dependencies/devDependencies in package.json…")
    pkg_json_path = project_root / "package.json"
    try:
        with pkg_json_path.open("r", encoding="utf-8") as f:
            pkg_data = json.load(f)
    except Exception as e:
        logging.error(f"Failed to read package.json: {e}")
        sys.exit(1)

    overrides = set(pkg_data.get("overrides", {}).keys())
    dependencies = pkg_data.get("dependencies", {})
    dev_dependencies = pkg_data.get("devDependencies", {})

    all_pkgs = set(dependencies.keys()) | set(dev_dependencies.keys())
    if not all_pkgs:
        logging.info("No direct dependencies or devDependencies found.")
        return

    temp_path = project_root / "package.json.tmp"
    try:
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(pkg_data, f, indent=2)
    except Exception as e:
        logging.error(f"Failed to create temporary package.json: {e}")
        sys.exit(1)

    changed = False
    pkg_list = sorted(all_pkgs)
    total_pkgs = len(pkg_list)
    for idx, pkg in enumerate(pkg_list, start=1):
        percent = idx / total_pkgs
        filled = int(percent * BAR_LENGTH)
        bar = "#" * filled + " " * (BAR_LENGTH - filled)
        print(
            f"\rUpgrading deps:    [{bar}] {
                percent *
                100:5.1f}%  ",
            end="",
            flush=True,
        )

        with temp_path.open("r", encoding="utf-8") as f:
            tmp_data = json.load(f)
        tmp_deps = tmp_data.get("dependencies", {})
        tmp_devdeps = tmp_data.get("devDependencies", {})

        cur_spec = tmp_deps.get(pkg) or tmp_devdeps.get(pkg)
        if not cur_spec:
            continue

        code, latest_ver, err = run_cmd(
            ["npm", "view", pkg, "version"], capture_output=True
        )
        if code != 0 or not latest_ver:
            logging.warning(f"Could not fetch latest version for {pkg}: {err}")
            continue

        if pkg in overrides:
            logging.info(f"{pkg:30s} override → {latest_ver}")
            if pkg in tmp_deps:
                tmp_deps[pkg] = f"^{latest_ver}"
            else:
                tmp_devdeps[pkg] = f"^{latest_ver}"
            tmp_data["dependencies"] = tmp_deps
            tmp_data["devDependencies"] = tmp_devdeps
            changed = True
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(tmp_data, f, indent=2)
            continue

        semver_cmd = ["npx", "semver", "-r", cur_spec, latest_ver]
        code, _, _ = run_cmd(semver_cmd, capture_output=True)
        if code == 0:
            continue

        code, peer_json, err = run_cmd(
            ["npm", "view", f"{pkg} @{latest_ver} ", "peerDependencies", "--json"],
            capture_output=True,
        )
        peers: Dict[str, str] = {}
        if code == 0 and peer_json and peer_json not in ("null", ""):
            try:
                peers = json.loads(peer_json)
            except json.JSONDecodeError:
                logging.warning(f"Invalid peerDependencies JSON for {pkg}@{latest_ver}")
                peers = {}

        ok_peers = True
        for pd_pkg, pd_range in peers.items():
            inst_ver = tmp_deps.get(pd_pkg) or tmp_devdeps.get(pd_pkg)
            if not inst_ver:
                continue
            code, _, _ = run_cmd(
                ["npx", "semver", "-r", pd_range, inst_ver], capture_output=True
            )
            if code != 0:
                ok_peers = False
                break

        if ok_peers:
            logging.info(f"{pkg:30s} candidate → {latest_ver}")
            if pkg in tmp_deps:
                tmp_deps[pkg] = f"^{latest_ver}"
            else:
                tmp_devdeps[pkg] = f"^{latest_ver}"
            tmp_data["dependencies"] = tmp_deps
            tmp_data["devDependencies"] = tmp_devdeps
            changed = True
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(tmp_data, f, indent=2)

    print(f"\rUpgrading deps:    [{'#' * BAR_LENGTH}] 100.0%")
    # Auto-align react & react-dom if mismatch
    with temp_path.open("r", encoding="utf-8") as f:
        tmp_data = json.load(f)
    tmp_deps = tmp_data.get("dependencies", {})
    tmp_devdeps = tmp_data.get("devDependencies", {})

    r_act = tmp_deps.get("react") or tmp_devdeps.get("react")
    r_dom = tmp_deps.get("react-dom") or tmp_devdeps.get("react-dom")

    def minor_major(version: str) -> str:
        parts = version.lstrip("^~").split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else version

    if r_act and r_dom and minor_major(r_act) != minor_major(r_dom):
        target = r_act if minor_major(r_act) < minor_major(r_dom) else r_dom
        logging.info(f"react/react-dom mismatch → aligning both to {target}")
        if "react" in tmp_deps:
            tmp_deps["react"] = target
        else:
            tmp_devdeps["react"] = target
        if "react-dom" in tmp_deps:
            tmp_deps["react-dom"] = target
        else:
            tmp_devdeps["react-dom"] = target
        tmp_data["dependencies"] = tmp_deps
        tmp_data["devDependencies"] = tmp_devdeps
        changed = True
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(tmp_data, f, indent=2)

    if changed:
        try:
            shutil.move(str(temp_path), str(pkg_json_path))
        except Exception as e:
            logging.error(f"Failed to replace package.json: {e}")
            sys.exit(1)
        logging.info("package.json updated with bumped dependencies.")
        logging.info("Installing updated dependencies…")
        code, _, err = run_cmd(
            ["npm", "install", "--legacy-peer-deps"], cwd=project_root
        )
        if code != 0:
            logging.warning(
                f"npm install --legacy-peer-deps failed: {err}. Trying --force…"
            )
            code, _, err = run_cmd(["npm", "install", "--force"], cwd=project_root)
            if code != 0:
                logging.error(f"npm install --force failed: {err}")
                sys.exit(1)
        code, _, err = run_cmd(["npm", "dedupe"], cwd=project_root)
        if code != 0:
            logging.warning(f"npm dedupe failed: {err}")
    else:
        try:
            temp_path.unlink()
        except Exception:
            pass
        logging.info("No compatible dependency upgrades found.")

    logging.info("Dependency bump step complete.")


def final_audit(project_root: Path, step: int) -> None:
    """
    Step 10: Run `npm audit --omit=dev`. Warn if non-zero exit.
    """
    print_global_progress(step, "Final npm audit")
    logging.info("Running final npm audit (omit dev dependencies)…")
    code, out, err = run_cmd(["npm", "audit", "--omit=dev"], cwd=project_root)
    if code != 0:
        logging.warning("[ npm audit reported issues: ]")
        for line in out.splitlines():
            logging.warning(f"  {line}")


def main():
    # Step 1: Locate project root
    print_global_progress(1, "Locate project root")
    project_root = find_project_root()
    logging.info(f"Project root detected: {project_root}")

    # Step 2: Verify prerequisites
    print_global_progress(2, "Verify prerequisites")
    verify_prerequisites()

    # Step 3: Install/update NVM
    install_or_update_nvm(3)

    # Step 4: Ensure latest LTS Node.js
    ensure_latest_lts_node(4)

    # Step 5: Upgrade npm itself
    upgrade_npm(5)

    # Step 6: Upgrade global packages
    upgrade_global_packages(6)

    # Step 7: Print installed versions & summary
    print_installed_versions(7)

    # Step 8: Bump direct dependencies
    bump_dependencies(project_root, 8)

    # Step 9: Final npm audit
    final_audit(project_root, 9)

    # Step 10: Mark completion (fill bar fully)
    print_global_progress(10, "All steps completed")
    logging.info("All steps completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error(f"Unhandled exception: {e}")
        sys.exit(1)
