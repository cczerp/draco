#!/bin/bash
# Draco install script
# Works two ways:
#   1. curl -fsSL https://raw.githubusercontent.com/cczerp/draco/main/install.sh | bash
#   2. git clone https://github.com/cczerp/draco && bash draco/install.sh
#
# Options:
#   --user   install to ~/.local/bin instead of /usr/local/bin (no sudo needed)

set -e

USER_INSTALL=false
[[ "$1" == "--user" ]] && USER_INSTALL=true

P='\033[95m'; G='\033[92m'; Y='\033[93m'; R='\033[91m'
B='\033[1m';  D='\033[2m';  X='\033[0m'

RAW_URL="https://raw.githubusercontent.com/cczerp/draco/main/draco.py"

echo ""
echo -e "${P}${B}  ╔═══════════════════════════════╗"
echo -e "  ║  🐉  Draco  ·  install         ║"
echo -e "  ╚═══════════════════════════════╝${X}"
echo ""

# ── Locate or download draco.py ───────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-/tmp}")" 2>/dev/null && pwd || echo /tmp)"
DRACO_SRC="$SCRIPT_DIR/draco.py"

if [[ ! -f "$DRACO_SRC" ]]; then
    echo -e "${D}  Downloading draco.py from GitHub…${X}"
    DRACO_SRC="/tmp/draco.py"
    if ! curl -fsSL "$RAW_URL" -o "$DRACO_SRC"; then
        echo -e "${R}  Download failed. Check your internet connection.${X}"
        exit 1
    fi
    echo -e "  ${G}✓${X} downloaded"
fi

# ── Check Python 3 ────────────────────────────────────────────────────────────
echo -e "${D}[1/3] Checking Python 3…${X}"
if ! command -v python3 &>/dev/null; then
    echo -e "${R}  Python 3 not found.${X}"
    echo "  Install it:  sudo apt install python3   (Debian/Ubuntu)"
    echo "               sudo dnf install python3   (Fedora/RHEL)"
    echo "               brew install python         (macOS)"
    exit 1
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "      ${G}✓${X} Python $PY_VER"

# requests is auto-installed by draco itself on first run, but let's do it now
if ! python3 -c 'import requests' &>/dev/null; then
    echo -e "      ${D}installing requests…${X}"
    python3 -m pip install --quiet requests
fi
echo -e "      ${G}✓${X} requests"

# ── Install draco command ─────────────────────────────────────────────────────
echo -e "${D}[2/3] Installing draco…${X}"

if [[ "$USER_INSTALL" == true ]]; then
    BIN_DIR="$HOME/.local/bin"
    mkdir -p "$BIN_DIR"
    DRACO_BIN="$BIN_DIR/draco"
    cp "$DRACO_SRC" "$DRACO_BIN"
    chmod +x "$DRACO_BIN"
    echo -e "      ${G}✓${X} installed → $DRACO_BIN"
    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        echo -e "      ${Y}⚠  Add to your shell config:${X}"
        echo -e '         export PATH="$HOME/.local/bin:$PATH"'
        echo    "      Then: source ~/.bashrc  (or open a new terminal)"
    fi
else
    DRACO_BIN="/usr/local/bin/draco"
    if [[ "$EUID" -ne 0 ]]; then
        sudo cp "$DRACO_SRC" "$DRACO_BIN"
        sudo chmod +x "$DRACO_BIN"
    else
        cp "$DRACO_SRC" "$DRACO_BIN"
        chmod +x "$DRACO_BIN"
    fi
    echo -e "      ${G}✓${X} installed → $DRACO_BIN"
fi

# ── Check Ollama ──────────────────────────────────────────────────────────────
echo -e "${D}[3/3] Checking Ollama…${X}"
if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    MODEL_COUNT=$(curl -sf http://localhost:11434/api/tags \
        | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
    echo -e "      ${G}✓${X} Ollama running  ($MODEL_COUNT model(s) installed)"
else
    echo -e "      ${Y}⚠${X}  Ollama not detected — draco will walk you through setup on first run."
    echo ""
    echo -e "  To install Ollama now:  ${D}curl -fsSL https://ollama.com/install.sh | sh${X}"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${G}${B}✅  Done!${X}"
echo ""
echo -e "  Type ${B}draco${X} to start."
echo ""
echo -e "${D}  Usage:"
echo -e "    draco                                 # interactive session"
echo -e "    draco 'what files are on my desktop?' # one-shot prompt"
echo -e "    draco --dangerously-skip-permissions  # auto-approve all tools"
echo -e "    draco --model <name>                  # pick a model"
echo -e "    /models                               # list installed models (inside draco)"
echo -e "    /docker                               # set up Docker (inside draco)"
echo -e "    /credentials                          # add Nebius API key (inside draco)${X}"
echo ""
