#!/usr/bin/env bash
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPLICATIONS_DIR="$DATA_HOME/applications"
DESKTOP_FILE="$APPLICATIONS_DIR/io.github.qianmo.CodexPixelOffice.desktop"
ICON_FILE="$DATA_HOME/icons/hicolor/256x256/apps/codex-pixel-office.png"

rm -f "$DESKTOP_FILE" "$ICON_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

echo "Uninstalled Codex Pixel Office desktop launcher."
