#!/usr/bin/env bash
# ------------------------------------------------------------
# Upgrade pip and all installed Python packages to their latest
# compatible versions. Automatically resolves dependency conflicts.
# Requires: python3 (or override via $PY), pip, and jq.
# ------------------------------------------------------------

set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────
section() {
    printf "\n==============================\n%s\n==============================\n" "$1"
}

error_exit() {
    printf "\n[Error] %s\n" "$1" >&2
    exit 1
}

# ─────────────────────────────────────────────────────────────
# 1. Determine Python interpreter and verify prerequisites
# ─────────────────────────────────────────────────────────────
PY=${PY:-python3}
command -v "$PY" >/dev/null 2>&1 || error_exit "\"$PY\" not found. Please install Python 3."
command -v jq   >/dev/null 2>&1 || {
    printf "jq not found. Attempting to install jq...\n"
    sudo apt-get update -y
    sudo apt-get install -y jq || error_exit "Failed to install jq"
}

# Determine pip command for this interpreter
PIP="$PY -m pip"
command -v "$PY" >/dev/null 2>&1 || error_exit "\"$PY\" pip module not available."

# ─────────────────────────────────────────────────────────────
# 2. Upgrade pip itself to the latest version
# ─────────────────────────────────────────────────────────────
section "Upgrading pip itself"
if $PIP install --quiet --upgrade pip; then
    printf "pip upgraded to %s\n" "$($PY -m pip --version | awk '{print $2}')"
else
    error_exit "pip upgrade failed."
fi

# ─────────────────────────────────────────────────────────────
# 3. List all outdated packages in JSON, extract names
# ─────────────────────────────────────────────────────────────
section "Checking for outdated packages"
OUT_JSON="$($PIP list --outdated --format=json)" || error_exit "Failed to list outdated packages."

# If no packages are outdated, skip upgrade
if [[ "$OUT_JSON" == "[]" ]]; then
    printf "All Python packages are already up to date.\n"
else
    # Extract package names from JSON; upgrade in batches of 10
    OUT_PKGS=( $(echo "$OUT_JSON" | jq -r '.[].name') )
    printf "Outdated packages detected (%d):\n" "${#OUT_PKGS[@]}"
    for pkg in "${OUT_PKGS[@]}"; do
        printf "  • %s\n" "$pkg"
    done

    section "Upgrading outdated packages"
    # Batch installation to avoid extremely long lines
    printf "%s\n" "${OUT_PKGS[@]}" | xargs -r -n10 $PIP install --upgrade
fi

# ─────────────────────────────────────────────────────────────
# 4. Resolve dependency conflicts automatically (up to 6 passes)
# ─────────────────────────────────────────────────────────────
section "Resolving dependency conflicts"
for pass in {1..6}; do
    PROBLEMS="$($PY -m pip check 2>&1 | grep 'has requirement' || true)"
    if [[ -z "$PROBLEMS" ]]; then
        printf "No dependency conflicts detected (pass %d).\n" "$pass"
        break
    fi

    printf "Conflict-resolve pass %d:\n" "$pass"
    # Parse each line for the required package to upgrade
    while IFS= read -r line; do
        # Example line: packageA 1.x has requirement packageB>=2, but packageB 1.y is installed
        req="$(sed -E 's/.*has requirement ([^,]+), but.*/\1/' <<<"$line")"
        if [[ -n "$req" ]]; then
            printf "  → Upgrading conflicting dependency: %s\n" "$req"
            $PIP install --upgrade "$req" || printf "    [Warning] Failed to upgrade %s\n" "$req"
        fi
    done <<<"$PROBLEMS"

    # After attempts, re-check in next pass
    if [[ $pass -eq 6 ]]; then
        error_exit "Unable to fully resolve dependency conflicts after 6 passes."
    fi
done

# ─────────────────────────────────────────────────────────────
# 5. Final verification
# ─────────────────────────────────────────────────────────────
section "Final pip check"
if $PY -m pip check >/dev/null 2>&1; then
    printf "Environment is clean. No dependency conflicts remain.\n"
else
    error_exit "Dependency conflicts remain. Please review manually."
fi

section "Installed package summary"
$PIP list --format=columns

printf "\nPython environment upgrade complete.\n"

