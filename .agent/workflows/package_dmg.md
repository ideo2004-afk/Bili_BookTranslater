---
description: Package the Bili application into a DMG file for macOS distribution.
---

This workflow executes the established packaging process using PyInstaller and hdiutil, as defined in `build_dmg.sh` and `Bili.spec`.

1. Run the build script
   // turbo
   ```bash
   sh build_dmg.sh
   ```

2. The output DMG will be located at `Bili.dmg`. Verify it exists and check its size (should be around 70-80MB).
