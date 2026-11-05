#!/bin/bash
# macOS 双击启动上班鼓励器（后台运行，可以关掉这个终端窗口）
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "没找到 python3，请先到 https://www.python.org/downloads/macos/ 安装 Python"
  read -r -p "按回车关闭"
  exit 1
fi
nohup python3 "上班鼓励器.pyw" >/dev/null 2>&1 &
echo "上班鼓励器已启动，这个窗口可以关掉了"
