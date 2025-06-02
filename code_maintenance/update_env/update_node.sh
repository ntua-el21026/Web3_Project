#!/usr/bin/env bash
# ------------------------------------------------------------
# Install or refresh NVM, ensure latest LTS Node.js, and upgrade
# global npm libraries, with enhanced checks and logging.
# ------------------------------------------------------------

set -euo pipefail

restore_nounset() { set -u; }
disable_nounset() { set +u; }

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

detect_shell_profile() {
    if [ -n "${ZSH_VERSION-}" ] && [ -f "${HOME}/.zshrc" ]; then
        echo "${HOME}/.zshrc"
    elif [ -n "${BASH_VERSION-}" ] && [ -f "${HOME}/.bashrc" ]; then
        echo "${HOME}/.bashrc"
    elif [ -f "${HOME}/.profile" ]; then
        echo "${HOME}/.profile"
    else
        error_exit "Could not detect a shell profile to update."
    fi
}

# ─────────────────────────────────────────────────────────────
# 1. Verify prerequisites: curl, git
# ─────────────────────────────────────────────────────────────
section "Checking prerequisites"
command -v curl >/dev/null 2>&1 || error_exit "curl is required but not installed."
command -v git  >/dev/null 2>&1 || error_exit "git is required but not installed."

# ─────────────────────────────────────────────────────────────
# 2. Install or update NVM (dynamically detect latest tag)
# ─────────────────────────────────────────────────────────────
section "Installing or updating NVM"
disable_nounset          # ← suspend nounset so that NVM's internal code can run without errors
NVM_DIR="${HOME}/.nvm"

# Dynamically fetch the latest NVM tag using git ls-remote with semantic version sorting
LATEST_NVM_TAG="$(git -c 'versionsort.suffix=-' \
    ls-remote --exit-code --refs --sort='version:refname' --tags https://github.com/nvm-sh/nvm.git '*.*.*' \
    | tail -n1 \
    | awk -F/ '{print $3}')"

if [[ -z "$LATEST_NVM_TAG" ]]; then
    error_exit "Failed to detect the latest NVM tag from GitHub."
fi

NVM_GIT_URL="https://github.com/nvm-sh/nvm.git"

if [[ ! -d "$NVM_DIR" ]]; then
    printf "NVM not found. Cloning %s to %s …\n" "$LATEST_NVM_TAG" "$NVM_DIR"
    git clone --depth 1 --branch "$LATEST_NVM_TAG" "$NVM_GIT_URL" "$NVM_DIR"
else
    printf "NVM directory exists. Fetching and checking out %s …\n" "$LATEST_NVM_TAG"
    (
        cd "$NVM_DIR"
        git fetch --depth 1 origin "$LATEST_NVM_TAG"
        git checkout "$LATEST_NVM_TAG"
    )
fi

# Ensure shell profile sources nvm
PROFILE_FILE="$(detect_shell_profile)"
if ! grep -q 'NVM_DIR' "$PROFILE_FILE" 2>/dev/null; then
    printf "Adding nvm source to %s …\n" "$PROFILE_FILE"
    {
        printf '\n# Load NVM (Node Version Manager)\n'
        printf 'export NVM_DIR="%s"\n' "$NVM_DIR"
        printf '[ -s "%s/nvm.sh" ] && \. "%s/nvm.sh"  # This loads nvm\n' "$NVM_DIR" "$NVM_DIR"
    } >> "$PROFILE_FILE"
else
    printf "nvm source already present in %s\n" "$PROFILE_FILE"
fi

# Load nvm into current session (nounset still disabled)
# shellcheck source=/dev/null
source "$NVM_DIR/nvm.sh"

# ─────────────────────────────────────────────────────────────
# 3. Install or update to latest LTS Node.js
# ─────────────────────────────────────────────────────────────
section "Ensuring latest LTS Node.js"

# (nounset is still disabled here so that nvm's internal variables like PATTERN don't cause errors)

# Determine the latest LTS version label
LTS_LABEL="lts/*"
LATEST_LTS_VERSION="$(nvm ls-remote --lts | tail -1 | awk '{print $1}')"
if [[ -z "$LATEST_LTS_VERSION" ]]; then
    error_exit "Failed to detect latest LTS version via nvm."
fi

# Check current active Node version
CURRENT_NODE_VERSION="$(nvm current 2>/dev/null || true)"
if [[ "$CURRENT_NODE_VERSION" != "$LATEST_LTS_VERSION" ]]; then
    printf "Installing Node.js %s (latest LTS)…\n" "$LATEST_LTS_VERSION"
    nvm install --lts
else
    printf "Already using Node.js %s (latest LTS)\n" "$CURRENT_NODE_VERSION"
fi

# Set default alias to lts/*
nvm alias default "$LTS_LABEL"
nvm use default

# Now that all nvm commands have run, we can turn nounset back on
restore_nounset          # ← re-enable nounset for the remainder of the script

# ─────────────────────────────────────────────────────────────
# 4. Upgrade npm to the latest version
# ─────────────────────────────────────────────────────────────
section "Upgrading npm to the latest version"
if npm install -g npm@latest; then
    printf "npm successfully upgraded to %s\n" "$(npm -v)"
else
    error_exit "npm upgrade failed."
fi

# ─────────────────────────────────────────────────────────────
# 5. Upgrade any pre-existing global npm packages
# ─────────────────────────────────────────────────────────────
section "Upgrading pre-existing global npm packages"

# List outdated global packages (depth=0 excludes dependencies of globals)
OUTDATED_GLOBALS="$(npm -g outdated --parseable --depth=0 || true)"
if [[ -n "$OUTDATED_GLOBALS" ]]; then
    printf "The following global packages are outdated:\n"
    printf "%s\n" "$OUTDATED_GLOBALS" | awk -F: '{print "  • "$2" (current: "$3", latest: "$4")"}'
    printf "\nUpdating global packages …\n"
    if npm -g update; then
        printf "Global packages updated successfully.\n"
    else
        error_exit "Global npm package update failed."
    fi
else
    printf "All global packages are already at their latest versions.\n"
fi

# ─────────────────────────────────────────────────────────────
# 6. Report installed versions and summary
# ─────────────────────────────────────────────────────────────
section "Installed versions and summary"
printf "nvm  : %s\n" "$(nvm --version)"
printf "node : %s\n" "$(node -v)"
printf "npm  : %s\n" "$(npm -v)"

# List current global packages version summary (depth=0)
printf "\nGlobal packages (depth=0):\n"
npm list -g --depth=0

printf "\nEnvironment setup complete.\n"

