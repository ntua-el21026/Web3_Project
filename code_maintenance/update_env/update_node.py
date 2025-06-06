#!/usr/bin/env python3
"""
update_node.py

Automates Node.js project maintenance with peer-dependency reconciliation.

• Ensures latest NVM / LTS Node / npm.
• Optionally upgrades global npm packages.
• For every root dependency:
                                                                                                                                                                                                                                                                1. Gather peer-dependency ranges (`npm ls --depth=1`).
                                                                                                                                                                                                                                                                2. Pick the newest published version that satisfies root + peers;
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                if impossible, pick newest version satisfying peers only.
                                                                                                                                                                                                                                                                3. Log a candidate line:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                CANDIDATE → <pkg> <old> -> ^<new>  [UPGRADE|DOWNGRADE peer-deps|SAME|CONFLICT]
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                — These lines go into the shared log file (not to the console).
                                                                                                                                                                                                                                                                4. Only UPGRADE / DOWNGRADE changes modify package.json.
• Writes package.json, runs `npm install`, dedupes, audits.

All INFO‐level logs (including candidate lines) now merge into:
                                                                                                                                <project_root>/cache/code_maintenance/update_env/logs/node_log.log

Console only shows WARNING+ and the progress bar.

"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


# ────────────────────────────────────────────────────────────────────────────────
# Helpers to locate project root
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
# Determine shared “logs” folder under:
#     <project_root>/cache/code_maintenance/update_env/logs/
# ────────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
proj = find_project_root(SCRIPT_DIR)
if not proj:
    print("[ERROR] .gitignore not found; cannot locate project root.")
    sys.exit(1)

LOG_DIR = proj / "cache" / "code_maintenance" / "update_env" / "logs"
LOG_PATH = LOG_DIR / "node_log.log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
# Clear previous contents
LOG_PATH.write_text("")

# ────────────────────────────────────────────────────────────────────────────────
# Configure Logging: all INFO+ to shared log file, WARNING+ to console
# ────────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

file_h = logging.FileHandler(LOG_PATH, encoding="utf-8")
file_h.setLevel(logging.INFO)
file_h.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
)
logger.addHandler(file_h)

console_h = logging.StreamHandler(sys.stdout)
console_h.setLevel(logging.WARNING)
console_h.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(console_h)

TOTAL_STEPS = 10
BAR_LEN = 40

# ────────────────────────────────────────────────────────────────────────────────
# Packaging helpers
# ────────────────────────────────────────────────────────────────────────────────
try:
    from packaging import version as P  # type: ignore
    from packaging.version import InvalidVersion
except ImportError:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "packaging"], check=True
    )
    from packaging import version as P  # type: ignore
    from packaging.version import InvalidVersion


def try_parse(v: str) -> Optional[P.Version]:
    try:
        return P.parse(v)
    except InvalidVersion:
        return None


def safe_gt(a: str, b: str) -> bool:
    va, vb = try_parse(a), try_parse(b)
    return bool(va and vb and va > vb)


# ────────────────────────────────────────────────────────────────────────────────
# Progress bar helper
# ────────────────────────────────────────────────────────────────────────────────
def bar(step: int, label: str) -> None:
    pct = step / TOTAL_STEPS
    sys.stdout.write(
        f"\r[{'#' * int(pct * BAR_LEN):<{BAR_LEN}}] {step}/{TOTAL_STEPS} {label:<25}"
    )
    sys.stdout.flush()
    if step == TOTAL_STEPS:
        sys.stdout.write("\n")
        sys.stdout.flush()


# ────────────────────────────────────────────────────────────────────────────────
# Shell helper
# ────────────────────────────────────────────────────────────────────────────────
def run(
    cmd: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    capture: bool = False,
    bash: bool = False,
    timeout: int = 120,
) -> Tuple[int, str, str]:
    full = ["bash", "-lc", " ".join(cmd)] if bash else list(cmd)
    try:
        res = subprocess.run(
            full,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
            timeout=timeout,
        )
        return res.returncode, (res.stdout or "").strip(), (res.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "TimeoutExpired"
    except FileNotFoundError:
        return 127, "", "CommandNotFound"


# ────────────────────────────────────────────────────────────────────────────────
# Misc helpers
# ────────────────────────────────────────────────────────────────────────────────
def need(*tools: str) -> None:
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        logger.error("Missing: " + ", ".join(missing))
        sys.exit(1)


def root_dir() -> Path:
    cur = Path.cwd()
    while cur != cur.parent:
        if (cur / "package.json").is_file():
            return cur
        cur = cur.parent
    logger.error("package.json not found")
    sys.exit(1)


# ────────────────────────────────────────────────────────────────────────────────
# Semver CLI helper
# ────────────────────────────────────────────────────────────────────────────────
def ensure_semver() -> bool:
    if shutil.which("semver"):
        return True
    run(["npm", "install", "-g", "semver"], capture=True)
    return shutil.which("semver") is not None


SEMVER_OK = ensure_semver()


def semver_ok(range_: str, vers: str) -> bool:
    if SEMVER_OK:
        return run(["semver", "-r", range_, vers], capture=True)[0] == 0
    return run(["npx", "-y", "semver", "-r", range_, vers], capture=True)[0] == 0


# ────────────────────────────────────────────────────────────────────────────────
# Version selection
# ────────────────────────────────────────────────────────────────────────────────
def highest_satisfying(all_versions: List[str], ranges: List[str]) -> Optional[str]:
    pool = [v for v in all_versions if (p := try_parse(v)) and not p.is_prerelease]
    for v in sorted(pool, key=P.parse, reverse=True):
        if all(semver_ok(r, v) for r in ranges):
            return v
    return None


# ────────────────────────────────────────────────────────────────────────────────
# NVM / Node / npm setup
# ────────────────────────────────────────────────────────────────────────────────
def ensure_nvm(step: int) -> None:
    bar(step, "NVM")
    home = Path.home()
    repo = "https://github.com/nvm-sh/nvm.git"
    nvm_dir = home / ".nvm"
    rc, tags, _ = run(
        [
            "git",
            "-c",
            "versionsort.suffix=-",
            "ls-remote",
            "--refs",
            "--sort=version:refname",
            "--tags",
            repo,
            "*.*.*",
        ],
        capture=True,
    )
    if rc or not tags:
        logger.error("Cannot fetch NVM tags")
        sys.exit(1)
    latest = tags.splitlines()[-1].split("/")[-1]
    if not nvm_dir.is_dir():
        run(["git", "clone", "--depth", "1", "--branch", latest, repo, str(nvm_dir)])
    else:
        run(["git", "fetch", "--depth", "1", "origin", latest], cwd=nvm_dir)
        run(["git", "checkout", latest], cwd=nvm_dir)
    logger.info(f"NVM ready ({latest})")


def ensure_lts(step: int) -> None:
    bar(step, "Node LTS")
    rc, out, _ = run(["nvm", "ls-remote", "--lts"], capture=True, bash=True)
    if rc:
        logger.error("nvm ls-remote failed")
        sys.exit(1)
    latest = re.findall(r"v\d+\.\d+\.\d+", re.sub(r"\x1B\[[0-9;]*m", "", out))[-1]
    if run(["nvm", "current"], capture=True, bash=True)[1].strip() != latest:
        run(["nvm", "install", "--lts"], bash=True)
    run(["nvm", "alias", "default", "lts/*"], bash=True)
    run(["nvm", "use", "default"], bash=True)
    logger.info(f"Node {latest} active")


def upgrade_npm(step: int) -> None:
    bar(step, "npm")
    run(["npm", "install", "-g", "npm@latest"])
    logger.info("npm upgraded")


def upgrade_global(step: int) -> None:
    bar(step, "npm -g")
    rc, out, _ = run(
        ["npm", "-g", "outdated", "--parseable", "--depth=0"], capture=True
    )
    if not rc and out.strip():
        run(["npm", "-g", "update"])
        logger.info("Global packages updated")
    else:
        logger.info("Global packages already up-to-date")


def versions(step: int) -> None:
    bar(step, "versions")
    for cmd in ("nvm --version", "node -v", "npm -v"):
        run(cmd.split(), capture=True, bash=("nvm" in cmd))
    logger.info("Version snapshot logged")


# ────────────────────────────────────────────────────────────────────────────────
# Dependency reconciliation
# ────────────────────────────────────────────────────────────────────────────────
def bump_deps(root: Path, step: int) -> None:
    bar(step, "deps ↑")

    pkg_file = root / "package.json"
    pkg_data = json.loads(pkg_file.read_text())
    deps, dev_deps = pkg_data.get("dependencies", {}), pkg_data.get(
        "devDependencies", {}
    )

    # Peer ranges from installed tree
    rc, ls_json, _ = run(
        ["npm", "ls", "--json", "--depth=1"], cwd=root, capture=True, timeout=300
    )
    peer: Dict[str, List[str]] = {}
    if not rc and ls_json:
        try:
            tree = json.loads(ls_json)
            for child in tree.get("dependencies", {}).values():
                for k, rng in child.get("peerDependencies", {}).items():
                    peer.setdefault(k, []).append(rng)
        except Exception:
            pass

    changed = 0
    all_roots = sorted(set(deps) | set(dev_deps))
    for pkg_name in all_roots:
        root_spec = deps.get(pkg_name) or dev_deps.get(pkg_name)
        ranges = [root_spec] + peer.get(pkg_name, [])

        # Fetch versions
        rc, js, _ = run(
            ["npm", "view", pkg_name, "versions", "--json"], capture=True, timeout=90
        )
        if rc or not js:
            continue
        try:
            all_versions: List[str] = json.loads(js)
        except Exception:
            continue

        best = highest_satisfying(all_versions, ranges)  # root + peers
        if best is None and peer.get(pkg_name):  # fallback: peers only
            best = highest_satisfying(all_versions, peer[pkg_name])

        if best is None:
            logger.info(f"CANDIDATE → {pkg_name:30} {root_spec:15} -> -- [CONFLICT]")
            continue

        new_spec = f"^{best}"
        current_version = re.sub(r"^[^0-9]*", "", root_spec)

        # Determine status
        if try_parse(best) == try_parse(current_version):
            action = "SAME"
        else:
            action = (
                "UPGRADE" if safe_gt(best, current_version) else "DOWNGRADE peer-deps"
            )

        logger.info(
            f"CANDIDATE → {pkg_name:30} {root_spec:15} -> {new_spec}  [{action}]"
        )

        # Only modify package.json for upgrade/downgrade
        if action != "SAME":
            container = deps if pkg_name in deps else dev_deps
            container[pkg_name] = new_spec
            changed += 1

    if changed:
        pkg_file.write_text(json.dumps(pkg_data, indent=2) + "\n")
        if run(["npm", "install", "--legacy-peer-deps"], cwd=root)[0]:
            if run(["npm", "install", "--force"], cwd=root)[0]:
                logger.error("npm install failed")
                sys.exit(1)
        run(["npm", "dedupe"], cwd=root)
        logger.info(f"Dependency upgrade complete ({changed} packages)")
    else:
        logger.info("No dependency changes needed")


def audit(step: int, root: Path) -> None:
    bar(step, "npm audit")
    if run(["npm", "audit", "--omit=dev"], cwd=root)[0]:
        logger.warning("npm audit issues")


# ────────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────────
def main() -> None:
    bar(1, "locate root")
    root = root_dir()
    logger.info(f"Project root: {root}")

    bar(2, "prereq")
    need("git", "curl", "jq", "npm")

    ensure_nvm(3)
    ensure_lts(4)
    upgrade_npm(5)
    upgrade_global(6)
    versions(7)
    bump_deps(root, 8)
    audit(9, root)

    bar(10, "done")
    logger.info("Update complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.error(f"Unhandled exception: {exc}")
        sys.exit(1)
