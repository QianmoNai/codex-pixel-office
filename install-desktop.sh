#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPLICATIONS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
DESKTOP_FILE="$APPLICATIONS_DIR/io.github.qianmo.CodexPixelOffice.desktop"
ICON_FILE="$ICON_DIR/codex-pixel-office.png"

mkdir -p "$APPLICATIONS_DIR" "$ICON_DIR"
install -m 0644 "$ROOT_DIR/static/assets/app-icon.png" "$ICON_FILE"

ESCAPED_ROOT=${ROOT_DIR//\\/\\\\}
ESCAPED_ROOT=${ESCAPED_ROOT//&/\\&}
ESCAPED_ROOT=${ESCAPED_ROOT//|/\\|}
sed "s|@APP_DIR@|$ESCAPED_ROOT|g" \
  "$ROOT_DIR/packaging/io.github.qianmo.CodexPixelOffice.desktop.in" \
  > "$DESKTOP_FILE"
chmod 0644 "$DESKTOP_FILE"

if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$DESKTOP_FILE"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Installed Codex Pixel Office in the application menu."
echo "Desktop entry: $DESKTOP_FILE"
