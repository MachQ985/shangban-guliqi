#!/bin/bash
# 在 Mac 上生成无需打开终端的启动应用；源码目录须和应用放在一起。
set -eu
cd "$(dirname "$0")"
APP="上班鼓励器.app/Contents"
mkdir -p "$APP/MacOS"
mkdir -p "$APP/Resources"
cp assets/AppIcon.icns "$APP/Resources/AppIcon.icns"
clang mac-launcher.c -o "$APP/MacOS/launch"
cat > "$APP/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>launch</string>
<key>CFBundleIdentifier</key><string>local.shangban-guliqi.launcher</string>
<key>CFBundleName</key><string>上班鼓励器</string>
<key>CFBundleIconFile</key><string>AppIcon.icns</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1.0</string>
<key>LSUIElement</key><true/>
</dict></plist>
PLIST
echo "已生成 上班鼓励器.app。请将它保留在当前源码目录中，双击即可启动。"
