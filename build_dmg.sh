#!/bin/bash
set -e

# Configuration
APP_NAME="Bili"
SPEC_FILE="Bili.spec"
DMG_NAME="Bili.dmg"
VENV_PYTHON="/Users/ideo2004/Bili/venv/bin/python"
PYINSTALLER="/Users/ideo2004/Bili/venv/bin/pyinstaller"

echo "=== Starting Build Process for $APP_NAME ==="

# 1. Clean previous builds
echo "[1/4] Cleaning up..."
rm -rf build dist dmg_root "$DMG_NAME"

# 2. Build with PyInstaller
echo "[2/4] Building Application Bundle..."
"$PYINSTALLER" --clean --noconfirm "$SPEC_FILE"

# 3. Prepare DMG Root
echo "[3/4] Preparing DMG Structure..."
mkdir dmg_root
# IMPORTANT: Use -a to preserve symbolic links (prevents size explosion)
cp -a "dist/$APP_NAME.app" dmg_root/
ln -s /Applications dmg_root/Applications

# 4. Create DMG
echo "[4/4] Creating DMG..."
hdiutil create -volname "$APP_NAME Installer" -srcfolder dmg_root -ov -format UDZO "$DMG_NAME"

# Final Report
echo "=== Build Complete ==="
ls -lh "$DMG_NAME"
