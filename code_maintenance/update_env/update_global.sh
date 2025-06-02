#!/usr/bin/env bash
# ------------------------------------------------------------
# Installs, upgrades, and verifies curated global npm packages.
# Includes enhanced checks, reporting, and error handling.
# Assumes Node.js and npm are already installed.
# ------------------------------------------------------------

set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────
section() {
	printf "\n==============================\n%s\n==============================\n" "$1"
}

error_exit() {
	printf "\n[Error] %s\n" "$1" >&2
	exit 1
}

# Map package → actual CLI command (or blank if none)
cli_name() {
	case "$1" in
		typescript) echo "tsc"   ;;
		lru-cache)  echo ""     ;;  # no CLI; skip verification
		*)          echo "$1"   ;;
	esac
}

verify_tool() {
	local pkg="$1"
	local cmd
	cmd="$(cli_name "$pkg")"

	if [[ -n "$cmd" && $(command -v "$cmd") ]]; then
		# Grab the first line of "cmd --version"
		local ver="$("$cmd" --version 2>/dev/null | head -1)"
		printf "%-12s %s\n" "$pkg:" "$ver"
	else
		printf "%-12s not found / N/A\n" "$pkg:"
	fi
}

# ─────────────────────────────────────────────────────────────
# 1. Verify prerequisites: node and npm must be available
# ─────────────────────────────────────────────────────────────
section "Checking prerequisites"
command -v node >/dev/null 2>&1 || error_exit "Node.js is required but not installed."
command -v npm  >/dev/null 2>&1 || error_exit "npm is required but not installed."

# ─────────────────────────────────────────────────────────────
# 2. Upgrade npm itself
# ─────────────────────────────────────────────────────────────
section "Upgrading npm to latest"
if npm install -g npm@latest; then
	printf "npm upgraded to %s\n" "$(npm -v)"
else
	error_exit "Failed to upgrade npm."
fi

# ─────────────────────────────────────────────────────────────
# 3. Define curated global CLI tools to install/upgrade
# ─────────────────────────────────────────────────────────────
CURATED_TOOLS=(
	typescript
	eslint
	hardhat
	npm-check-updates
)

# ─────────────────────────────────────────────────────────────
# 4. Install or upgrade curated tools (always install latest)
# ─────────────────────────────────────────────────────────────
section "Installing or upgrading curated global CLI tools"
for tool in "${CURATED_TOOLS[@]}"; do
	printf "→ Installing/upgrading %s@latest\n" "$tool"
	if npm install -g "$tool@latest"; then
		:
	else
		error_exit "Failed to install/upgrade $tool."
	fi
done

# ─────────────────────────────────────────────────────────────
# 5. Resolve deprecated npm helpers (glob, lru-cache)
# ─────────────────────────────────────────────────────────────
section "Installing npm’s deprecated helpers"
DEPRECATED_HELPERS=(
	glob
	lru-cache
)
for helper in "${DEPRECATED_HELPERS[@]}"; do
	printf "→ Installing %s@latest\n" "$helper"
	if npm install -g "$helper@latest"; then
		:
	else
		error_exit "Failed to install $helper."
	fi
done

# ─────────────────────────────────────────────────────────────
# 6. Check for any other globally installed packages that are outdated
# ─────────────────────────────────────────────────────────────
section "Checking for other outdated global packages"
OUTDATED_GLOBALS="$(npm -g outdated --parseable --depth=0 || true)"
if [[ -n "$OUTDATED_GLOBALS" ]]; then
	printf "The following global packages are outdated:\n"
	printf "%s\n" "$OUTDATED_GLOBALS" | awk -F: '{print "  • "$2" (current: "$3", latest: "$4")"}'
	section "Upgrading all other global packages"
	if npm -g update; then
		printf "Other global packages upgraded successfully.\n"
	else
		error_exit "Failed to update other global packages."
	fi
else
	printf "No other global packages require an upgrade.\n"
fi

# ─────────────────────────────────────────────────────────────
# 7. Verify installation: list versions of each curated tool
# ─────────────────────────────────────────────────────────────
section "Verifying installed versions"

# Node and npm versions
printf "node : %s\n" "$(node -v)"
printf "npm  : %s\n" "$(npm -v)"

# Curated tools versions (if installed)
for tool in "${CURATED_TOOLS[@]}"; do
	verify_tool "$tool"
done

# Deprecated helpers versions
for helper in "${DEPRECATED_HELPERS[@]}"; do
	verify_tool "$helper"
done

# ─────────────────────────────────────────────────────────────
# 8. Summary of all globally installed packages (depth=0)
# ─────────────────────────────────────────────────────────────
section "Global npm packages summary (depth=0)"
npm list -g --depth=0

# ─────────────────────────────────────────────────────────────
# 9. Final message
# ─────────────────────────────────────────────────────────────
section "Global npm environment setup is complete."

