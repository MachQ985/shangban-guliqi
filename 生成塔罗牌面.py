"""生成塔罗牌面：从 Wikimedia Commons 下载韦特塔罗 1909 原版扫描图，统一裁边后写进 tarot/。

用法：python 生成塔罗牌面.py
  1. 原图下载到 tarot-原图/（不进 git，约 20 MB）；已下载的跳过。
     Commons 会限速（HTTP 429），脚本会等一分钟再试。一直被限速的话，
     可以在浏览器里下载，按 00.jpg、cups01.jpg、back.jpg 这样命名放进 tarot-原图/ 再运行。
  2. 每张找到印刷黑框，只保留框内（含黑框），框外留白统一换成同一种纸色、同样宽度，
     缩成 270×468、256 色 PNG 写进 tarot/。
需要 Pillow（只是生成用；上班鼓励器本身不依赖它）。

改了牌面后，要把 上班鼓励器.pyw 里 TAROT_DIR 的目录名改一下（如 tarot2 → tarot3），
同事那边才会重新下载，否则他们一直用已下载的旧图。
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageStat

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "tarot-原图")
DST = os.path.join(HERE, "tarot")
CATEGORY = "Category:Rider-Waite tarot deck (Roses & Lilies)"
UA = "tarot-asset-fetch/1.0"
W, H, PAD = 270, 468, .045   # 和程序里 150:260 同比例；四边留白 = 牌宽 4.5%
RATIO = 1.804                # 黑框高宽比，全套 78 张的中位数
SUITS = {"Wands": "wand", "Cups": "cups", "Swords": "swor", "Pentacles": "pent"}


def http(url):
    """带限速重试的下载：Commons 返回 429 就等一分钟再试。"""
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            print("  被限速，等 60 秒…")
            time.sleep(60)


def download():
    """Commons 分类里的文件名 → 程序里的牌名（00、cups01、back…），缺的才下载。"""
    api = ("https://commons.wikimedia.org/w/api.php?action=query&generator=categorymembers"
           f"&gcmtitle={urllib.parse.quote(CATEGORY)}&gcmtype=file&gcmlimit=500"
           "&prop=imageinfo&iiprop=url&format=json")
    os.makedirs(SRC, exist_ok=True)
    for p in json.loads(http(api))["query"]["pages"].values():
        title, url = p["title"], p["imageinfo"][0]["url"]
        m = re.match(r"File:RWS1909 - (\d\d) ", title) or re.match(r"File:RWS1909 - (\w+) (\d\d)\.", title)
        if "Roses and Lilies cropped" in title:
            key = "back"
        elif m and m.lastindex == 1:
            key = m.group(1)
        elif m:
            key = SUITS[m.group(1)] + m.group(2)
        else:
            continue
        path = os.path.join(SRC, key + ".jpg")
        if not os.path.exists(path):
            print("下载", key)
            data = http(url)
            with open(path + ".part", "wb") as f:
                f.write(data)
            os.replace(path + ".part", path)   # 下到一半中断不会留下坏文件
            time.sleep(10)


def frame(im, fix=True):
    """找印刷黑框，返回 (x0, y0, x1, y1)。牌背没有黑框，找的是图案边缘。"""
    g = im.convert("L")
    w, h = g.size
    px = g.load()
    ys, xs = range(h // 4, 3 * h // 4, 4), range(w // 4, 3 * w // 4, 4)
    cols = [sum(px[x, y] for y in ys) / len(ys) for x in range(w)]
    rows = [sum(px[x, y] for x in xs) / len(xs) for y in range(h)]

    def edge(v, idx):
        vals = [v[i] for i in idx]
        vals[:3] = [vals[3]] * 3  # 扫描图最外 3px 常有暗边（扫描仪的边），不算；离边最近的黑框也在第 4px 以后

        def first(thr):
            # 从外往里第一条暗线，且要同时满足：
            # - 连续 2px 都暗：扫描图边上偶有 1px 的暗杂线（如牌背最底一行），黑框都有好几 px 厚
            # - 外侧 10px 内没有白底（>238）：纸边阴影也暗，但它外面紧挨着扫描白底，黑框外面是纸
            return next((k for k, x in enumerate(vals[:-1]) if x < thr and vals[k + 1] < thr
                         and max(vals[max(0, k - 10):k + 1]) <= 238), None)
        hit = first(120)  # 黑框整行平均约 40~85，纸边阴影约 93~97
        return hit if hit is not None else first(min(vals) + (max(vals) - min(vals)) * .4)

    l, r = edge(cols, range(w // 6)), edge(cols, range(w - 1, w - 1 - w // 6, -1))
    t, b = edge(rows, range(h // 6)), edge(rows, range(h - 1, h - 1 - h // 6, -1))
    l, r = (l if l is not None else r), (r if r is not None else l)
    t, b = (t if t is not None else b), (b if b is not None else t)
    assert None not in (l, r, t, b), "四边都找不到黑框"
    x0, y0, x1, y1 = l, t, w - r, h - b
    if fix and abs((y1 - y0) / (x1 - x0) / RATIO - 1) > .06:
        # 某一侧黑框印得太淡没认出来（如圣杯国王右边）：留白偏大的那侧按全套牌的标准高宽比反推
        we = round((y1 - y0) / RATIO)
        x0, x1 = (x1 - we, x1) if l > r else (x0, x0 + we)
    return x0, y0, x1, y1


def paper_of(im):
    """黑框外侧那圈纸的颜色（取框上方一条）。"""
    x0, y0, x1, y1 = frame(im)
    return ImageStat.Stat(im.crop((x0, max(0, y0 - 6), x1, max(1, y0 - 2)))).median


def build(src, dst, paper):
    im = Image.open(src).convert("RGB")
    x0, y0, x1, y1 = frame(im)
    pad = round((x1 - x0) * PAD)
    out = Image.new("RGB", (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), paper)
    out.paste(im.crop((x0, y0, x1, y1)), (pad, pad))
    out.resize((W, H), Image.LANCZOS).quantize(256, method=Image.Quantize.MEDIANCUT).save(dst, optimize=True)


def main():
    download()
    files = sorted(f for f in os.listdir(SRC) if f.endswith(".jpg"))
    if len(files) != 79:
        sys.exit(f"原图应有 79 张（78 张牌 + 牌背），现在只有 {len(files)} 张")
    papers = [paper_of(Image.open(os.path.join(SRC, f)).convert("RGB")) for f in files if f != "back.jpg"]
    paper = tuple(sorted(p[i] for p in papers)[len(papers) // 2] for i in range(3))  # 全套取中位数，每张都用这个色
    for f in files:
        build(os.path.join(SRC, f), os.path.join(DST, f[:-4] + ".png"), paper)
    print(f"已生成 {len(files)} 张牌面到 tarot/，统一纸色 {paper}")


if __name__ == "__main__":
    main()
