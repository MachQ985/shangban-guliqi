"""发布新版：改完 上班鼓励器.pyw 里的 VERSION 后运行这个脚本。

它会：算新文件的校验值 → 写 version.json → git 提交 → 推到 GitHub。
同事那边的悬浮窗 6 小时内（或右键"检查更新"）自动下载新版并重启。

用法：python 发布新版.py "这次改了什么"
"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_FILE = "上班鼓励器.pyw"


def git(*args):
    subprocess.run(["git", *args], cwd=HERE, check=True)


def main():
    notes = sys.argv[1] if len(sys.argv) > 1 else ""
    path = os.path.join(HERE, APP_FILE)
    data = open(path, "rb").read()
    code = data.decode("utf-8")
    compile(code, APP_FILE, "exec")  # 有语法错误就别发布
    version = re.search(r'^VERSION = "([\d.]+)"', code, re.M).group(1)

    vpath = os.path.join(HERE, "version.json")
    old = json.load(open(vpath, encoding="utf-8")) if os.path.exists(vpath) else {}
    if old.get("version") == version and old.get("sha256") != hashlib.sha256(data).hexdigest():
        sys.exit(f"文件改了但版本号还是 {version}，先把 VERSION 改大再发布")

    info = {"version": version, "file": APP_FILE,
            "sha256": hashlib.sha256(data).hexdigest(), "notes": notes}
    with open(vpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
        f.write("\n")

    git("add", "-A")
    git("commit", "-m", f"发布 v{version}" + (f"：{notes}" if notes else ""))
    git("push")
    print(f"已发布 v{version}")


if __name__ == "__main__":
    main()
