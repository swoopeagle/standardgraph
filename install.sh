#!/usr/bin/env bash
# StandardGraph installer
# Usage: curl -fsSL https://raw.githubusercontent.com/swoopeagle/standardgraph/main/install.sh | bash

set -euo pipefail

REPO="swoopeagle/standardgraph"
DB_DIR="$HOME/.standardgraph"
DB_PATH="$DB_DIR/common_core.db"
DB_URL="https://huggingface.co/datasets/swoopeagle/standardgraph/resolve/main/common_core.db"
CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"

# ── Colours ───────────────────────────────────────────────────────────────────
bold=$(tput bold 2>/dev/null || true)
reset=$(tput sgr0 2>/dev/null || true)
green=$(tput setaf 2 2>/dev/null || true)
red=$(tput setaf 1 2>/dev/null || true)
blue=$(tput setaf 4 2>/dev/null || true)

ok()   { echo "${green}✓${reset} $*"; }
info() { echo "${blue}→${reset} $*"; }
fail() { echo "${red}✗${reset} $*"; exit 1; }

echo
echo "${bold}StandardGraph installer${reset}"
echo "146,000+ K-12 curriculum standards across 256 systems for Claude"
echo

# ── 1. Check / install uv ─────────────────────────────────────────────────────
info "Checking for uv..."
if ! command -v uv &>/dev/null; then
    info "Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Reload PATH
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
fi
UVX="$(command -v uvx 2>/dev/null || echo "")"
if [ -z "$UVX" ]; then
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
    UVX="$(command -v uvx)" || fail "uvx not found after uv install. Please restart your terminal and re-run."
fi
ok "uv found at $(command -v uv)"

# ── 2. Download database ───────────────────────────────────────────────────────
mkdir -p "$DB_DIR"
if [ -f "$DB_PATH" ]; then
    existing_size=$(du -sh "$DB_PATH" | cut -f1)
    info "Database already exists ($existing_size). Skipping download."
    info "To re-download, delete $DB_PATH and re-run this script."
else
    info "Downloading standardgraph database (~1.5 GB)..."
    if command -v curl &>/dev/null; then
        curl -L --progress-bar "$DB_URL" -o "$DB_PATH" || fail "Database download failed. Check your internet connection."
    elif command -v wget &>/dev/null; then
        wget --show-progress -q "$DB_URL" -O "$DB_PATH" || fail "Database download failed."
    else
        fail "Neither curl nor wget found. Please install one and re-run."
    fi
    ok "Database downloaded ($(du -sh "$DB_PATH" | cut -f1)) → $DB_PATH"
fi

# ── 3. Install / verify the standardgraph package ─────────────────────────────
info "Checking standardgraph package..."
if "$UVX" standardgraph --help &>/dev/null 2>&1; then
    ok "standardgraph is ready"
else
    info "Pre-caching standardgraph package with uvx..."
    # uvx will cache it on first run; no explicit install needed
    ok "standardgraph will be fetched from PyPI on first use"
fi

# ── 4. Patch Claude Desktop config ────────────────────────────────────────────
info "Configuring Claude Desktop..."

if [ ! -f "$CLAUDE_CONFIG" ]; then
    mkdir -p "$(dirname "$CLAUDE_CONFIG")"
    echo '{"mcpServers":{}}' > "$CLAUDE_CONFIG"
fi

python3 - "$CLAUDE_CONFIG" "$UVX" "$DB_PATH" <<'PYEOF'
import json, sys, os

config_path, uvx_path, db_path = sys.argv[1], sys.argv[2], sys.argv[3]

with open(config_path) as f:
    config = json.load(f)

config.setdefault("mcpServers", {})
config["mcpServers"]["standardgraph"] = {
    "command": uvx_path,
    "args": ["standardgraph"],
    "env": {"DB_PATH": db_path}
}

# Write with a backup
backup = config_path + ".bak"
if os.path.exists(config_path):
    import shutil
    shutil.copy2(config_path, backup)

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"  Config updated: {config_path}")
print(f"  Backup saved:   {backup}")
PYEOF

ok "Claude Desktop configured"

# ── 5. Done ───────────────────────────────────────────────────────────────────
echo
echo "${bold}${green}Installation complete!${reset}"
echo
echo "Next steps:"
echo "  1. Quit and reopen Claude Desktop"
echo "  2. Look for the hammer (🔨) icon in a new conversation"
echo "  3. Try: \"Search for standards on adding fractions in Grade 4\""
echo "         \"Compare how Singapore and CCSS teach algebra in Grade 7\""
echo "         \"List all available curriculum systems\""
echo
echo "Database: $DB_PATH"
echo "Config:   $CLAUDE_CONFIG"
echo
echo "Need help? https://github.com/$REPO/issues"
