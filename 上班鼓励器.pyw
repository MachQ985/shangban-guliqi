"""上班鼓励器：桌面悬浮窗，按时薪实时显示今天已赚多少、还有多久下班。

左键拖动；右键菜单（Mac：双指点按 / Ctrl+点击）：设置 / 开机自启 / 退出。
双击切换迷你模式。支持 Windows 和 macOS。
配置保存在：
  Windows  %APPDATA%\\上班鼓励器\\config.json
  macOS    ~/Library/Application Support/上班鼓励器/config.json
"""
import ctypes
import datetime as dt
import json
import os
import random
import sys
import tkinter as tk
from tkinter import messagebox

APP = "上班鼓励器"
VERSION = "1.10.0"  # 发布新版时改这里，同事那边自动更新
IS_MAC = sys.platform == "darwin"
HOME = os.path.expanduser("~")

if IS_MAC:
    CONF_DIR = os.path.join(HOME, "Library", "Application Support", APP)
    # 登录时启动：LaunchAgent，下次登录生效
    STARTUP_FILE = os.path.join(HOME, "Library", "LaunchAgents",
                                "local.shangban-guliqi.plist")
else:
    CONF_DIR = os.path.join(os.environ.get("APPDATA", HOME), APP)
    STARTUP_FILE = os.path.join(
        os.environ.get("APPDATA", ""),
        r"Microsoft\Windows\Start Menu\Programs\Startup", APP + ".vbs")
CONF_PATH = os.path.join(CONF_DIR, "config.json")

DEFAULT = {
    "hourly": 0.0,
    "currency": "$",
    "fx": 1,  # 显示汇率：时薪 × fx 再显示
    "start": "09:00",
    "end": "17:00",
    "lunch_min": 0,  # 午休时长（分钟），不算钱
    "workdays": [0, 1, 2, 3, 4],  # 周一=0
    "alpha": 0.92,
    "x": None,
    "y": None,
    "mini": False,
    "theme": "auto",  # auto 跟随系统 / light / dark
    "city": "on-143",  # 天气城市（加拿大环境部编号），默认多伦多
    "pet_on": True,   # 显示桌宠（导入素材后才会出现）
    "pet_zoom": 2,    # 桌宠放大倍数
    "tax_mode": "net",  # net 税后（估算）/ gross 税前 / cash 现金（不预扣）
}

# ---------- 外观（苹果风：冷白 / 深灰底，黑白灰分层，颜色只给钱、倒计时和进度） ----------
PALETTES = {
    "light": {
        "surface": "#ffffff", "ground": "#f5f5f7", "input": "#f2f2f7",
        "text": "#1d1d1f", "text2": "#6e6e73", "text3": "#86868b",
        "hairline": "#ececee", "track": "#e8e8ed", "border": "#dcdce0",
        "gold": "#b8860b", "green": "#248a3d", "bar": "#34c759", "up": "#d70015",
        "accent": "#0071e3", "on_accent": "#ffffff", "danger": "#d70015",
        "toy_blue": "#c7dff4", "toy_rose": "#f2cbd0", "toy_sage": "#cce4d5",
        "toy_amber": "#f3dfb3", "toy_lilac": "#ddd4ec",
        "jiao_flat": "#edc5a6", "jiao_red": "#b52e37", "jiao_edge": "#84232c",
        "jiao_shine": "#f2948e",
    },
    "dark": {
        "surface": "#1c1c1e", "ground": "#000000", "input": "#2c2c2e",
        "text": "#f5f5f7", "text2": "#aeaeb2", "text3": "#8e8e93",
        "hairline": "#2c2c2e", "track": "#3a3a3c", "border": "#3a3a3c",
        "gold": "#ffd60a", "green": "#30d158", "bar": "#30d158", "up": "#ff453a",
        "accent": "#0a84ff", "on_accent": "#ffffff", "danger": "#ff453a",
        "toy_blue": "#294762", "toy_rose": "#603b45", "toy_sage": "#324e43",
        "toy_amber": "#5a4a2e", "toy_lilac": "#48405e",
        "jiao_flat": "#d7ac8a", "jiao_red": "#bd3c48", "jiao_edge": "#7b2631",
        "jiao_shine": "#f29b94",
    },
}

# 字体在 Tk 启动后按本机已装字体挑（见 pick_fonts）
FONT = "Microsoft YaHei UI"   # 中文
NUM_FONT = "Segoe UI"         # 数字：Windows 11 用 Segoe UI Variable，Mac 用 SF


def pick_fonts():
    global FONT, NUM_FONT
    import tkinter.font as tkfont
    fams = set(tkfont.families())

    def first(cands, default):
        return next((f for f in cands if f in fams), default)

    sys_default = tkfont.nametofont("TkDefaultFont").actual()["family"]
    FONT = first(["PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei"], sys_default)
    NUM_FONT = first(["SF Pro Display", ".AppleSystemUIFont", "Segoe UI Variable Display",
                      "Segoe UI", "Helvetica Neue"], FONT)


def system_is_dark():
    try:
        if IS_MAC:
            import subprocess
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                 capture_output=True, text=True, timeout=2).stdout
            return "Dark" in out
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def win11_round(win, border_color):
    """Windows 11：系统圆角 + 细边框。旧系统上调用失败就算了。"""
    if IS_MAC:
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        dwm = ctypes.windll.dwmapi
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
        r, g, b = (int(border_color[i:i + 2], 16) for i in (1, 3, 5))
        color = ctypes.c_uint(r | g << 8 | b << 16)  # COLORREF 是 0x00BBGGRR
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(color), 4)
    except Exception:
        pass

CHEER_EVERY_SEC = 15  # 鼓励语多久换一句

CHEERS = {
    "before": [
        "早安，打工人！", "还没上班，再躺一会儿", "养精蓄锐，等会儿开搞",
        "今天也会是赚钱的一天", "闹钟响了，钱包在等你", "先吃早饭，再去搬砖",
        "咖啡续命，准备出发", "出门前照照镜子：今天也很值钱",
        "通勤路上也算奔向财富", "今天的目标：平安上班，准时下班",
        "没有困难的工作，只有勇敢的打工人", "打工人，打工魂，打工都是人上人",
    ],
    "early": [
        "新的一天，冲！", "开工大吉", "钱已经在路上了", "每一秒都在进账",
        "早安打工人，今天也是为自己打工", "搬砖第一步：先打开电脑",
        "先把最难的事干掉", "状态拉满，今天必胜", "老板画的饼不吃，工资照拿",
        "打工不为别的，为了下班后的快乐", "你的工位就是你的印钞机",
        "钱不会自己来，但你已经来了", "今天的你，比咖啡还提神",
        "认真干活的样子最酷", "一天之计在于晨，一月之计在发薪",
    ],
    "mid": [
        "稳住，节奏很好", "已经干掉一大截了", "喝口水，继续赚",
        "你比昨天更值钱", "站起来活动活动，颈椎也是本钱", "工资条在向你招手",
        "离发工资又近了一天", "累了就深呼吸，钱还在涨", "干活要认真，摸鱼要专业",
        "今日份努力，正在悄悄到账", "上班是为了生活，不是生活只剩上班",
        "看看窗外，休息一下眼睛", "别跟难缠的事较劲，跟钱较劲",
        "你的每一分钟都明码标价", "打工路漫漫，工资是明灯",
    ],
    "late": [
        "过半了，胜利在望", "坚持住，下班在招手", "再撑一下就自由了",
        "离下班越来越近", "下午茶时间，奖励一下自己", "今天的工资已经赚了一大半",
        "下午也要元气满满", "犯困了？想想晚饭吃什么", "把剩下的活排一排，稳稳收尾",
        "再忙也别忘了喝水", "下班后的你，已经在等你了", "工资在涨，烦恼在减",
        "今天的钱快要攒满了", "撑住，晚饭在召唤", "距离自由只差最后一段路",
    ],
    "final": [
        "最后冲刺！", "马上下班，收拾收拾", "倒计时开始了", "胜利就在眼前",
        "保存文件，准备撤退", "别接新活，稳住", "今天的工资马上到手",
        "下班的风已经在吹了", "最后几分钟，坚持就是胜利", "电脑关机的声音最好听",
        "晚饭吃什么，可以想了", "今天的你，辛苦也值得",
    ],
    "after": [
        "下班啦！今天辛苦了", "收工！钱已到手", "下班快乐，去享受生活吧",
        "今天的工作到此为止", "下班后的时间，全部属于你", "工作群消息，明天再说",
        "好好吃顿饭，奖励自己", "今天也是靠自己赚钱的一天", "回家路上的风都是甜的",
        "下班不聊工作，只聊生活", "明天的事，明天的你会搞定", "今天的你，值得一个早睡",
    ],
    "off": [
        "今天休息，好好放松", "休息日，不谈工作", "充电日，明天再战",
        "睡到自然醒，是休息日的特权", "工作是工作，生活是生活", "今天的任务：开心",
        "出去走走，晒晒太阳", "陪陪家人朋友吧", "休息好了，才能更好地搞钱",
        "放下手机里的工作群", "今天不打卡，只打卡快乐", "好好吃饭，好好睡觉",
    ],
    # 以下按天气混进上班 / 没上班时的鼓励语
    "rain": [
        "下班可能下雨，记得带伞", "外面下雨，屋里赚钱刚刚好", "雨天适合安心搬砖",
        "雨再大也挡不住发工资", "带好伞，下班不淋雨", "听着雨声赚钱，也挺好",
    ],
    "snow": [
        "下班可能下雪，路上慢点", "外面下雪，工位暖和", "雪天路滑，早点出门别着急",
        "下雪了，赚完钱回家吃火锅",
    ],
    "cold": [
        "外面冷，工位暖，钱也暖", "天冷多穿点，感冒了不划算", "冷天搬砖，热乎乎的工资",
        "出门记得戴帽子手套",
    ],
    "hot": [
        "外面热，空调房里赚钱真香", "天热多喝水", "热天心别躁，工资照样涨",
    ],
}


# ---------- 今日签：每人每天固定一签（玩法参考 nonebot_plugin_fortune 和程序员老黄历，内容自写） ----------
# (等级, 抽中权重, 打工指数范围, 签文)
FORTUNE_LEVELS = [
    ("大吉", 10, (90, 100), [
        "今日摸鱼不被发现，需求一次过", "老板夸你，工资条也在偷偷变长",
        "会议取消，咖啡免费，代码一次跑通", "今天说的话都有人听，提的方案都被采纳",
        "贵人就在隔壁工位，开口就有收获", "所有的坑今天都绕开了",
        "准时下班，路上全是绿灯", "财运亨通，连报销都秒批",
        "电子木鱼功德 +999，今日 bug 自动退散", "服务器今天比你还稳，放心摸鱼",
        "水逆已过期，好运正在加载 100%", "今日欧气爆表，建议顺手抽个卡",
        "运势已满格，系统检测到你是天选打工人", "需求文档写得清清楚楚，罕见",
        "Ctrl+S 之神庇佑，今天一个文件都不会丢", "今天的你自带 buff：说啥成啥",
    ]),
    ("中吉", 20, (75, 89), [
        "稳中有进，手头的活今天能收尾", "小有惊喜，可能有人请你喝奶茶",
        "沟通顺畅，邮件不用来回改三遍", "灵感在线，难题今天有思路",
        "领导心情不错，适合汇报进度", "忙而不乱，下班前能清空待办",
        "同事给力，配合默契", "今天的努力，月底看得见",
        "Wi-Fi 满格，网速和心情一样顺", "电脑今天不卡，开机即战斗",
        "信号良好，好消息正在路上", "打印机今天居然没卡纸",
        "今天回消息的速度刚刚好，不早不晚", "赛博财神路过，钱包有点动静",
        "进度条走得比预想快", "今天的咖啡格外提神",
    ]),
    ("小吉", 25, (60, 74), [
        "小有收获，别贪多，一件一件来", "运气一般般，但午饭会很好吃",
        "可能被临时拉去帮忙，顺手积点人情", "慢一点没关系，稳住就好",
        "今天适合整理桌面和文件夹", "会有一点小麻烦，问一句就解决",
        "平平淡淡，也是好的一天",
        "今日运势：缓存命中，省点力气", "系统提示：有一个小惊喜待领取",
        "今天的 Excel 公式一次就对", "适合清理电脑桌面，顺便清理心情",
        "电量 60%，够用，别硬撑到 1%", "随手点的外卖，意外好吃",
        "今天适合把收藏夹里的教程看一个",
    ]),
    ("吉", 25, (50, 64), [
        "按部就班，不出岔子就是胜利", "不求表现，但求不背锅",
        "日常的一天，把本职做好就行", "中规中矩，记得多喝水",
        "适合做重复的活，不容易出错", "别跟人较劲，跟进度较劲",
        "无风无浪，摸鱼也要适度",
        "运势正常运行中，未发现异常", "今日状态：在线，但别打扰",
        "能量条一半一半，午饭后自动回血", "今天适合当 NPC，按剧本走就行",
        "网速一般，耐心一般，凑合够用", "今日关键词：稳定输出",
        "不氪金也能通关的一天",
    ]),
    ("末吉", 15, (35, 49), [
        "开局不顺，下午会好起来", "小心临时需求，留点余量",
        "今天的会可能有点长，带上水杯", "容易手滑，发消息前多看一眼",
        "运势在攒，明天会更好", "低调做事，少说多听",
        "今日运势加载中……请稍候再试", "电脑可能想更新，记得先保存",
        "信号时有时无，重要的事当面说", "今天的好运在排队，前面还有 3 人",
        "小心软件卡死，Ctrl+S 按勤一点", "运势缓冲中，建议先喝口水",
    ]),
    ("凶", 5, (10, 34), [
        "今日宜装忙，忌被点名", "问题有点多，深呼吸，一个一个解决",
        "可能会被甩锅，记得留好聊天记录", "诸事不宜，准时下班就是最好的转运",
        "今天的坑有点深，多问一句再动手",
        "检测到水逆信号，建议敲电子木鱼 108 下", "运势 404，请明天再来",
        "今日不宜重启电脑，可能回不来", "系统警告：负能量过载，请立刻摸鱼降温",
        "今天的 bug 有点多，但都不是你写的", "建议开启省电模式，能躺则躺",
    ]),
]
FORTUNE_YI = [
    "准时下班", "摸鱼十分钟", "点杯奶茶", "整理桌面", "回复积压的邮件", "站起来走走",
    "主动汇报进度", "喝够八杯水", "早点吃午饭", "学点新东西", "给同事带零食", "清空待办",
    "关掉工作群提醒", "备份文件", "请教老同事", "先做最难的事", "午休小睡", "夸夸同事",
    "伸个懒腰", "早点出门", "戴耳机听首歌", "按时吃饭", "出去晒晒太阳", "写周报",
    "拒绝无效会议", "规划下周", "早睡", "记账", "提前十分钟到", "把话说清楚",
    "敲电子木鱼", "清理浏览器标签页", "开飞行模式五分钟", "清空回收站", "Ctrl+S",
    "给手机充满电", "换个桌面壁纸", "转发锦鲤", "关掉弹窗广告", "整理下载文件夹",
]
FORTUNE_JI = [
    "开会超时", "周五上线", "临时改需求", "加班", "已读不回", "背锅", "熬夜",
    "在群里抬杠", "喝第三杯咖啡", "边吃边干活", "什么都答应", "拖到最后一分钟",
    "乱改别人的文件", "当着老板摸鱼", "说“马上好”", "深夜回消息", "久坐不动",
    "冲动消费", "跟电脑较劲", "忘记保存", "点“回复全部”", "把会开成聊天", "画大饼",
    "空腹喝咖啡", "大清早开会", "硬撑不请假", "乱删文件", "忽略提醒",
    "连续干两小时不休息", "下班前接新活",
    "点开不明链接", "重启电脑", "开 50 个标签页", "手机电量低于 10%", "强制关机",
    "在工作群发表情包", "删聊天记录", "点“稍后提醒我”", "用 final_最终版_v3 命名",
    "刷短视频停不下来",
]


def fortune_for(day):
    """按“日期 + 这台电脑 + 用户名”算出今天的签：同一个人同一天永远是同一签。"""
    import getpass
    import hashlib
    import uuid
    try:
        who = f"{uuid.getnode()}|{getpass.getuser()}"
    except Exception:
        who = HOME
    seed = int.from_bytes(hashlib.sha256(f"{day.isoformat()}|{who}".encode()).digest()[:8], "big")
    rnd = random.Random(seed)
    level, _, (lo, hi), lines = rnd.choices(FORTUNE_LEVELS, weights=[x[1] for x in FORTUNE_LEVELS])[0]
    return {"level": level, "text": rnd.choice(lines), "score": rnd.randint(lo, hi),
            "yi": rnd.sample(FORTUNE_YI, 2), "ji": rnd.sample(FORTUNE_JI, 2)}


# ---------- 塔罗牌：韦特塔罗 1909 原版（Pamela Colman Smith 绘，公有领域） ----------
# 牌面图片放在仓库 tarot/ 文件夹，程序只自带牌名。第一次用时从 GitHub 下到
# %APPDATA%\上班鼓励器\tarot\；开发目录里有 tarot/ 就直接用本地的。
TAROT_MAJOR = [
    ("愚者", "The Fool"), ("魔术师", "The Magician"), ("女祭司", "The High Priestess"),
    ("皇后", "The Empress"), ("皇帝", "The Emperor"), ("教皇", "The Hierophant"),
    ("恋人", "The Lovers"), ("战车", "The Chariot"), ("力量", "Strength"),
    ("隐士", "The Hermit"), ("命运之轮", "Wheel of Fortune"), ("正义", "Justice"),
    ("倒吊人", "The Hanged Man"), ("死神", "Death"), ("节制", "Temperance"),
    ("恶魔", "The Devil"), ("高塔", "The Tower"), ("星星", "The Star"),
    ("月亮", "The Moon"), ("太阳", "The Sun"), ("审判", "Judgement"), ("世界", "The World"),
]
TAROT_SUITS = [("wand", "权杖", "Wands"), ("cups", "圣杯", "Cups"),
               ("swor", "宝剑", "Swords"), ("pent", "星币", "Pentacles")]
TAROT_RANKS = [("王牌", "Ace"), ("二", "Two"), ("三", "Three"), ("四", "Four"), ("五", "Five"),
               ("六", "Six"), ("七", "Seven"), ("八", "Eight"), ("九", "Nine"), ("十", "Ten"),
               ("侍从", "Page"), ("骑士", "Knight"), ("王后", "Queen"), ("国王", "King")]
# (图片名, 中文名, 英文名)，共 78 张；牌背图片叫 back
TAROT_CARDS = [(f"{i:02d}", zh, en) for i, (zh, en) in enumerate(TAROT_MAJOR)] + [
    (f"{k}{i + 1:02d}", szh + rzh, f"{ren} of {sen}")
    for k, szh, sen in TAROT_SUITS for i, (rzh, ren) in enumerate(TAROT_RANKS)]
TAROT_BACK = "back"
TAROT_POSITIONS = ["过去", "现在", "未来"]
TAROT_DIR = os.path.join(CONF_DIR, "tarot")
TAROT_DEV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tarot")
TAROT_DL = {"busy": False, "done": 0, "total": 0, "error": ""}  # 后台下载进度，界面线程只读


def tarot_path(key):
    """牌面图片路径（PNG，150×260）；key 是 TAROT_CARDS 里的图片名或 TAROT_BACK。"""
    dev = os.path.join(TAROT_DEV_DIR, key + ".png")
    return dev if os.path.isfile(dev) else os.path.join(TAROT_DIR, key + ".png")


def tarot_missing():
    keys = [c[0] for c in TAROT_CARDS] + [TAROT_BACK]
    return [k for k in keys if not os.path.isfile(tarot_path(k))]


def tarot_ready():
    return not tarot_missing()


def tarot_download():
    """后台线程：补齐缺的牌面（约 2 MB）。由 tarot_start_download 启动，进度看 TAROT_DL。"""
    import urllib.request
    miss = tarot_missing()
    TAROT_DL.update(done=0, total=len(miss), error="")
    try:
        os.makedirs(TAROT_DIR, exist_ok=True)
        for key in miss:
            req = urllib.request.Request(REPO_RAW + f"tarot/{key}.png", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"{key}.png 不是图片")
            dst = os.path.join(TAROT_DIR, key + ".png")
            with open(dst + ".part", "wb") as f:
                f.write(data)
            os.replace(dst + ".part", dst)
            TAROT_DL["done"] += 1
    except Exception as ex:
        TAROT_DL["error"] = f"牌面下载失败：{ex}"
    finally:
        TAROT_DL["busy"] = False


def tarot_start_download():
    import threading
    if not TAROT_DL["busy"] and tarot_missing():
        TAROT_DL["busy"] = True  # 在界面线程先占住，连点也只开一个线程
        threading.Thread(target=tarot_download, daemon=True).start()


def tarot_shuffle():
    """洗好的一副牌：[(图片名, 是否逆位), ...]，78 张，每张正逆位各一半概率。"""
    rnd = random.SystemRandom()
    deck = [(c[0], rnd.random() < 0.5) for c in TAROT_CARDS]
    rnd.shuffle(deck)
    return deck


def tarot_name(key):
    """图片名 → (中文名, 英文名)。"""
    c = next(c for c in TAROT_CARDS if c[0] == key)
    return c[1], c[2]


def tarot_prompt(question, picks):
    """picks：按 过去 / 现在 / 未来 顺序的 [(图片名, 是否逆位), ...]，生成发给 AI 的提示词。"""
    lines = ["你是一名专业的塔罗师，请帮我解读这次抽到的牌。",
             "请只根据这次的问题和抽到的牌来解读，不要结合你对我的任何记忆、之前的对话或个人信息。",
             f"我的问题是：{question.strip()}",
             "我用的是韦特塔罗，三张牌阵（过去 / 现在 / 未来），抽到的牌是："]
    for pos, (key, rev) in zip(TAROT_POSITIONS, picks):
        zh, en = tarot_name(key)
        lines.append(f"{pos}：{zh}（{en}），{'逆位' if rev else '正位'}")
    lines.append("请结合我的问题，逐张解读每张牌在对应位置上的含义，再给出整体的分析和建议。")
    return "\n".join(lines)


# 今日运势：每天一张今日牌。牌是自己凭直觉选的（洗牌照样随机），选定后记进配置 tarot_daily，
# 当天再打开直接看这张，第二天才能重抽。
def tarot_daily_get(conf, day):
    """今天已经抽过就返回 (图片名, 是否逆位)，否则 None；配置损坏或牌名不认识也当没抽。"""
    d = conf.get("tarot_daily")
    if not isinstance(d, dict) or d.get("day") != day.isoformat():
        return None
    key = d.get("card")
    if not any(c[0] == key for c in TAROT_CARDS):
        return None
    return key, bool(d.get("rev"))


def tarot_daily_set(conf, day, key, rev):
    """记下今天的牌并保存配置。"""
    conf["tarot_daily"] = {"day": day.isoformat(), "card": key, "rev": bool(rev)}
    save_conf(conf)


# 今日运势的主题：(名字, 让 AI 重点讲什么)。最后一个「自定义」= 自己写一句问题。
TAROT_TOPICS = [
    ("综合", "再分别讲今天的工作、财运、人际和身心状态"),
    ("工作", "再重点讲今天的工作：任务进展、和领导同事的配合、要留意的坑"),
    ("财运", "再重点讲今天的财运：收入、花钱、有没有意外的进账或开销"),
    ("感情", "再重点讲今天的感情：单身的桃花和相处、有伴的关系和沟通"),
    ("人际", "再重点讲今天的人际：和同事、朋友、家人的相处，适合找谁、躲着谁"),
    ("健康", "再重点讲今天的身体和精力：作息、饮食、压力，需要注意哪里"),
    ("学习", "再重点讲今天适不适合学新东西、考试或提升自己，怎么学效率高"),
    ("心情", "再重点讲今天的心情和情绪：可能的起伏、原因和怎么让自己舒服一点"),
    ("做决定", "再讲今天适不适合做重要决定，做决定时要注意什么"),
]
TAROT_CUSTOM = "自定义"
TAROT_QUESTION_MAX = 60   # 自定义问题最多几个字


def tarot_topic_get(conf):
    """上次选的主题和自定义问题（跨天保留，下次打开默认还是它）；不认识的主题回到「综合」。"""
    topic = conf.get("tarot_topic")
    names = [t[0] for t in TAROT_TOPICS] + [TAROT_CUSTOM]
    if topic not in names:
        topic = TAROT_TOPICS[0][0]
    q = conf.get("tarot_question")
    return topic, (q.strip()[:TAROT_QUESTION_MAX] if isinstance(q, str) else "")


def tarot_topic_set(conf, topic, question=""):
    """记下当前主题（自定义时连同问题）并保存配置。"""
    conf["tarot_topic"] = topic
    if topic == TAROT_CUSTOM:
        conf["tarot_question"] = (question or "").strip()[:TAROT_QUESTION_MAX]
    save_conf(conf)


def tarot_daily_prompt(day, key, rev, topic="综合", question=""):
    """今日运势的提示词：一张今日牌 + 主题（或自定义问题）。自定义但问题为空时按「综合」处理。"""
    zh, en = tarot_name(key)
    question = (question or "").strip()
    focus = dict(TAROT_TOPICS).get(topic, TAROT_TOPICS[0][1])
    lines = [
        "你是一名专业的塔罗师，请帮我解读今天的运势。",
        "请只根据这次抽到的牌来解读，不要结合你对我的任何记忆、之前的对话或个人信息。",
        f"今天是 {day.year} 年 {day.month} 月 {day.day} 日，星期{'一二三四五六日'[day.weekday()]}，我是一名上班族。",
        f"我用的是韦特塔罗，抽了一张今日牌：{zh}（{en}），{'逆位' if rev else '正位'}。",
    ]
    if topic == TAROT_CUSTOM and question:
        lines.append(f"我今天想问的是：{question}")
        lines.append("请先说明这张牌（含正逆位）的含义，再结合我的问题具体分析，"
                     "最后给我一句今天的提醒，以及今天适合做和最好避免的事各两件。")
    else:
        if topic != TAROT_TOPICS[0][0] and topic in dict(TAROT_TOPICS):
            lines.append(f"今天我最想了解的是：{topic}。")
        lines.append(f"请先说明这张牌（含正逆位）的含义，{focus}，"
                     "最后给我一句今天的提醒，以及今天适合做和最好避免的事各两件。")
    return "\n".join(lines)


# ---------- 午饭吃什么：大转盘 ----------
# 选项存在配置 lunch_options 里，每个人自己改；转到的结果记在 lunch_history，
# 之前最近 LUNCH_SKIP 次转到的不再上转盘（周末没转不占名额），免得连着吃同一样。
LUNCH_DEFAULT = ["拉面", "寿司", "麻辣烫", "汉堡", "披萨", "越南粉",
                 "韩式拌饭", "三明治", "炒饭", "饺子", "咖喱饭", "沙拉"]
LUNCH_SKIP = 2           # 之前最近两次（按天，不算今天）转到的排除；今天重转不排除今天上一次的结果
LUNCH_MAX = 20           # 转盘最多放这么多项，再多就看不清了
LUNCH_NAME_MAX = 8       # 每项最多几个字


def lunch_options(conf):
    """当前的全部选项（去空、去重、截断长度）。"""
    out = []
    for x in conf.get("lunch_options") or LUNCH_DEFAULT:
        x = str(x).strip()[:LUNCH_NAME_MAX]
        if x and x not in out:
            out.append(x)
    return out[:LUNCH_MAX] or list(LUNCH_DEFAULT)


def lunch_set_options(conf, names):
    """保存用户编辑后的选项（调用方负责 save_conf）。少于 2 项就恢复默认。"""
    conf["lunch_options"] = lunch_options({"lunch_options": names})
    if len(conf["lunch_options"]) < 2:
        conf["lunch_options"] = list(LUNCH_DEFAULT)
    return conf["lunch_options"]


def lunch_recent(conf, today=None):
    """要排除的选项：今天之前最近 LUNCH_SKIP 天的结果（每天只记一条）。"""
    today = (today or dt.date.today()).isoformat()
    past = sorted((h for h in conf.get("lunch_history", []) if h.get("day", "") < today),
                  key=lambda h: h["day"])
    return {h["pick"] for h in past[-LUNCH_SKIP:]}


def lunch_candidates(conf, today=None):
    """这次上转盘的选项：全部选项去掉最近吃过的；剩下不到 2 项就不排除。
    返回 (上转盘的, 被排除的)。"""
    opts = lunch_options(conf)
    skip = lunch_recent(conf, today)
    cand = [x for x in opts if x not in skip]
    if len(cand) < 2:
        return opts, []
    return cand, [x for x in opts if x in skip]


def lunch_spin(cands):
    """抽中第几项（等概率）。界面拿这个下标去算转盘停在哪。"""
    return random.SystemRandom().randrange(len(cands))


def lunch_record(conf, pick, today=None):
    """记下今天转到的（今天再转会覆盖），只留最近 14 条。调用方负责 save_conf。"""
    today = (today or dt.date.today()).isoformat()
    hist = [h for h in conf.get("lunch_history", []) if h.get("day") != today]
    hist.append({"day": today, "pick": pick})
    conf["lunch_history"] = hist[-14:]


def lunch_today(conf, today=None):
    """今天已经转到的午饭，没转过返回 None。"""
    today = (today or dt.date.today()).isoformat()
    return next((h["pick"] for h in conf.get("lunch_history", []) if h.get("day") == today), None)


# ---------- 赛博圣杯（掷筊） ----------
# 两片筊杯各自随机落成“平面朝上”或“凸面朝上”：一平一凸是圣杯（1/2），
# 两平是笑杯（1/4），两凸是阴杯（1/4）。
JIAO_RESULTS = {
    "圣杯": "一平一凸，神明应允。",
    "笑杯": "两面皆平，神明笑而不答，可以换个问法再问。",
    "阴杯": "两面皆凸，神明不允，此事暂缓。",
}
JIAO_STREAK = 3  # “连续三圣杯”模式：连掷三次都是圣杯才算真正应允


def jiao_throw():
    """掷一次：返回 (左片平面朝上?, 右片平面朝上?, 结果名)。"""
    rnd = random.SystemRandom()
    a, b = rnd.random() < .5, rnd.random() < .5
    return a, b, ("圣杯" if a != b else "笑杯" if a else "阴杯")


# ---------- 版本记录：发布新版时在最上面加一条（设置 → 其他 → 更新记录，右键菜单也能打开） ----------
# (版本号, 日期, [这一版改了什么, ...])，新的在前
CHANGELOG = [
    ("1.10.0", "2026-11-12", [
        "塔罗牌新增「今日运势」：每天抽一张今日牌，生成提示词拿去问 AI 今天的运势",
        "今天抽过的牌当天会一直保留，再打开直接看；明天才能重新抽",
        "打开塔罗牌时先选：今日运势（一张牌），或者问一个问题（过去 / 现在 / 未来三张牌）",
    ]),
    ("1.9.0", "2026-11-12", [
        "桌宠素材升级到 256×256 高清：导入清晰的原图不再被压糊，显示大小不变",
        "点猫爪开关显示 / 隐藏桌宠时，加了登场 / 退场的淡入淡出动画",
    ]),
    ("1.8.1", "2026-11-10", [
        "赛博圣杯的筊杯重画：胖弯月造型，有厚度、红漆高光和贴地阴影",
        "掷杯动画更真实：抛起、空中翻转、错开落地，凸面朝上的那片会晃几下再停稳",
        "悬浮窗顶部加了猫爪开关，点一下显示 / 隐藏桌宠",
        "新增版本信息和更新记录（就是你现在看到的这个）",
    ]),
    ("1.8.0", "2026-11-10", [
        "新增「午饭吃什么」大转盘：选项可以自己改，最近两次转到的自动跳过",
        "新增「赛博圣杯」掷筊：圣杯 / 笑杯 / 阴杯，可开「连续三圣杯」模式",
        "今日签、塔罗牌、午饭、圣杯的入口排成两行",
        "设置 → 宠物 加了「复制提示词」：连同宠物照片发给 AI，就能画出整套桌宠素材",
        "塔罗提示词加了一句：让 AI 不要结合对你的记忆来解读",
    ]),
    ("1.7.0", "2026-11-10", [
        "新增塔罗牌：韦特塔罗 1909 原版 78 张，先写问题再洗牌，自己选过去 / 现在 / 未来三张",
        "翻牌后生成提示词，一键复制去问 AI 解读",
        "牌面第一次使用时自动下载（约 2 MB）",
    ]),
    ("1.6.1", "2026-11-06", [
        "今日签新增一批赛博风签文",
        "宜忌加了更多打工日常",
    ]),
    ("1.6.0", "2026-11-05", [
        "桌宠动作扩充到 50 多个：揣手、踩奶、洗脸、伸懒腰、打滚等",
        "新增互动：摸摸、连戳会生气、拖起来、双击打滚，鼠标靠近会盯着看",
        "离开电脑会犯困，回来会惊醒；快下班会兴奋",
    ]),
    ("1.5.0", "2026-11-05", [
        "新增桌宠：导入自己小猫的图片，它会趴在悬浮窗上",
        "图片自动抠图、缩成像素风；跟着天气换动作",
        "上班时长换零食，右键猫可以喂食、逗猫棒陪玩",
    ]),
    ("1.4.1", "2026-11-05", [
        "设置窗口分成收入、时间、宠物、其他几页",
    ]),
    ("1.4.0", "2026-11-05", [
        "新增税后估算：按 2026 年联邦和安省税率、CPP、EI 算到手金额",
        "可以选税后、税前或现金（不预扣）",
    ]),
    ("1.3.1", "2026-11-05", [
        "测试自动更新，没有功能变化",
    ]),
    ("1.3.0", "2026-11-05", [
        "新增今日签：每人每天一签，有签文、打工指数和宜忌",
    ]),
    ("1.2.2", "2026-11-05", [
        "日出日落改成线条小图标",
    ]),
    ("1.2.1", "2026-11-05", [
        "新增日出日落时间",
    ]),
    ("1.2.0", "2026-11-05", [
        "新增天气：现在、下班时、明天（加拿大环境部数据）",
        "下班时可能下雨会提醒带伞",
    ]),
    ("1.1.0", "2026-11-05", [
        "首次发布：按时薪实时显示今天已赚多少、还有多久下班",
        "钱可以换算成其他货币或能加多少升汽油；常驻显示明日油价涨跌",
        "迷你模式、开机自启、自动更新",
    ]),
]


# ---------- 配置 ----------
def load_conf():
    conf = dict(DEFAULT)
    try:
        with open(CONF_PATH, encoding="utf-8") as f:
            conf.update(json.load(f))
    except (OSError, ValueError):
        pass
    return conf


def save_conf(conf):
    os.makedirs(CONF_DIR, exist_ok=True)
    with open(CONF_PATH, "w", encoding="utf-8") as f:
        json.dump(conf, f, ensure_ascii=False, indent=2)


def parse_hm(s):
    s = (s or "").strip().replace("：", ":")
    if not s:
        return None
    h, m = s.split(":")
    h, m = int(h), int(m)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError
    return dt.time(h, m)


# ---------- 计算 ----------
def overlap(a1, a2, b1, b2):
    """两个时间段重叠的秒数。"""
    return max(0.0, (min(a2, b2) - max(a1, b1)).total_seconds())


def compute(conf, now):
    """返回 dict：state, earned, total, remain, progress"""
    today = now.date()
    start = dt.datetime.combine(today, parse_hm(conf["start"]))
    end = dt.datetime.combine(today, parse_hm(conf["end"]))
    span = (end - start).total_seconds()
    paid = max(0.0, span - float(conf.get("lunch_min", 0)) * 60)
    total = paid * float(conf["hourly"]) / 3600.0
    # 午休时长平摊到全天：金额匀速上涨，到下班正好是 时薪 × (上班时长 − 午休)
    r = {"total": total, "rate": total / span if span else 0.0}

    if now.weekday() not in conf["workdays"]:
        r.update(state="off", earned=0.0, remain=None, progress=0.0)
        return r

    r["progress"] = min(1.0, overlap(start, end, start, now) / span) if span else 0.0
    r["earned"] = total * r["progress"]
    if now < start:
        r.update(state="before", remain=(start - now).total_seconds())
    elif now >= end:
        r.update(state="after", remain=0, progress=1.0)
    else:
        r.update(state="work", remain=(end - now).total_seconds())
    return r


def fmt_dur(sec):
    sec = int(max(0, sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


# ---------- 显示成什么（时薪是加元） ----------
# (代码, 名字, 符号, 断网又没缓存时用的大概汇率)
DISPLAYS = [
    ("CAD", "加元", "$", 1),
    ("CNY", "人民币", "¥", 4.8),
    ("JPY", "日元", "¥", 113),
    ("KRW", "韩元", "₩", 960),
    ("IDR", "印尼盾", "Rp ", 13000),
    ("VND", "越南盾", "₫", 18400),
    ("GAS", "汽油（升）", "", None),
    ("custom", "自定义", None, None),
]
DISPLAY_BY_CODE = {d[0]: d for d in DISPLAYS}
DISPLAY_BY_NAME = {d[1]: d for d in DISPLAYS}


def display_code(conf):
    """老配置只有 fx / currency：按最接近的预设猜一个，猜不到就当自定义。"""
    code = conf.get("display")
    if code in DISPLAY_BY_CODE:
        return code
    fx, sym = float(conf.get("fx", 1) or 1), conf.get("currency", "$")
    if fx == 1:
        return "CAD"
    for c, _, s, approx in DISPLAYS:
        if approx and s == sym and 0.7 < fx / approx < 1.4:
            return c
    return "custom"


# ---------- 税后估算：2026 年安省员工（联邦税 + 安省税 + 健康保费 + CPP + EI） ----------
# 数字来源：CRA / 安省 2026 年公布的税率与分档（查于 2026-11），每年 1 月要更新一次
TAX_YEAR = 2026
FED_BRACKETS = [(58523, .14), (117045, .205), (181440, .26), (258482, .29), (None, .33)]
FED_BPA_MAX, FED_BPA_MIN = 16452, 14829       # 基本免税额：收入 181,440–258,482 之间逐步减少
FED_EMPLOYMENT_AMOUNT = 1501                  # 加拿大就业抵免额（2025 年 1,471 按 2% 指数化）
ON_BRACKETS = [(53891, .0505), (107785, .0915), (150000, .1116), (220000, .1216), (None, .1316)]
ON_BPA = 12989
ON_SURTAX = [(5818, .20), (7446, .36)]        # 按"安省基本税额"超过这两档的部分加收
ON_TAX_REDUCTION = 300                        # 安省低收入减税基本额（估值）
CPP_RATE, CPP_EXEMPT, CPP_YMPE = .0595, 3500, 74600
CPP2_RATE, CPP_YAMPE = .04, 85000
EI_RATE, EI_MAX_INSURABLE = .0163, 68900


def _bracket_tax(income, brackets):
    tax, lower = 0.0, 0
    for upper, rate in brackets:
        if upper is None or income <= upper:
            return tax + (income - lower) * rate
        tax += (upper - lower) * rate
        lower = upper
    return tax


def _ohp(income):
    """安省健康保费（Ontario Health Premium）。"""
    if income <= 20000:
        return 0.0
    if income <= 36000:
        return min(300, .06 * (income - 20000))
    if income <= 48000:
        return 300 + min(150, .06 * (income - 36000))
    if income <= 72000:
        return 450 + min(150, .25 * (income - 48000))
    if income <= 200000:
        return 600 + min(150, .25 * (income - 72000))
    return 750 + min(150, .25 * (income - 200000))


def annual_deductions(gross):
    """年收入 gross（全部是工资）→ 各项扣除（年）。只是估算：不算 RRSP、其他抵免和退税。"""
    cpp_base = max(0.0, min(gross, CPP_YMPE) - CPP_EXEMPT)
    cpp1 = cpp_base * CPP_RATE
    cpp2 = max(0.0, min(gross, CPP_YAMPE) - CPP_YMPE) * CPP2_RATE
    ei = min(gross, EI_MAX_INSURABLE) * EI_RATE
    # 增强部分的 CPP（5.95% 里的 1% + CPP2）从收入里扣除，基础部分（4.95%）算税收抵免
    cpp_enhanced = cpp_base * .01 + cpp2
    cpp_credit_base = cpp_base * .0495
    taxable = max(0.0, gross - cpp_enhanced)

    # 联邦
    if taxable <= FED_BRACKETS[2][0]:
        bpa = FED_BPA_MAX
    elif taxable >= FED_BRACKETS[3][0]:
        bpa = FED_BPA_MIN
    else:
        lo, hi = FED_BRACKETS[2][0], FED_BRACKETS[3][0]
        bpa = FED_BPA_MAX - (FED_BPA_MAX - FED_BPA_MIN) * (taxable - lo) / (hi - lo)
    fed_credits = (bpa + min(FED_EMPLOYMENT_AMOUNT, gross) + cpp_credit_base + ei) * FED_BRACKETS[0][1]
    fed = max(0.0, _bracket_tax(taxable, FED_BRACKETS) - fed_credits)

    # 安省
    on_basic = max(0.0, _bracket_tax(taxable, ON_BRACKETS)
                   - (ON_BPA + cpp_credit_base + ei) * ON_BRACKETS[0][1])
    surtax = sum(max(0.0, on_basic - t) * r for t, r in ON_SURTAX)
    on = on_basic + surtax
    on = max(0.0, on - max(0.0, 2 * ON_TAX_REDUCTION - on))  # 低收入减税
    ohp = _ohp(taxable)

    total = fed + on + ohp + cpp1 + cpp2 + ei
    return {"gross": gross, "fed": fed, "on": on, "ohp": ohp, "cpp": cpp1 + cpp2, "ei": ei,
            "total": total, "rate": total / gross if gross else 0.0}


def annual_gross(conf):
    """按时薪 × 每天带薪小时 × 每周工作日 × 52 周估年收入。"""
    s, e = parse_hm(conf["start"]), parse_hm(conf["end"])
    paid_h = ((e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)
              - float(conf.get("lunch_min", 0) or 0)) / 60
    return float(conf["hourly"]) * max(0.0, paid_h) * len(conf.get("workdays", [])) * 52


TAX_MODES = [("net", "税后（估算）"), ("gross", "税前"), ("cash", "现金（不预扣）")]


def tax_mode(conf):
    """老配置只有 after_tax：True → 税后，False → 税前。"""
    m = conf.get("tax_mode")
    if m in dict(TAX_MODES):
        return m
    return "net" if conf.get("after_tax", True) else "gross"


def net_factor(conf):
    """税后 / 税前 的比例；设置里选了按税前显示就是 1。"""
    if tax_mode(conf) != "net" or float(conf.get("hourly", 0) or 0) <= 0:
        return 1.0
    return 1 - annual_deductions(annual_gross(conf))["rate"]


def fmt_rate(r):
    """汇率显示：大数不要科学计数法。"""
    return f"{r:,.0f}" if r >= 1000 else f"{r:,.2f}" if r >= 10 else f"{r:,.4f}"


def split_unit(s):
    """'59.74 升' → ('59.74', '升')：中文单位要用中文字体单独显示。"""
    if s.endswith(" 升"):
        return s[:-2], "升"
    return s, ""


def fmt_money(conf, v, digits=2):
    """v 是加元。按设置换算成别的货币或汽油升数显示：钱少少的，看起来多多的。"""
    code = display_code(conf)
    if code == "GAS":
        price = gas_today()
        if price:
            return f"{v / (price / 100):,.{digits}f} 升"
        code = "CAD"  # 还没拿到油价，先按加元显示
    if code == "custom":
        return f"{conf.get('currency', '$')}{v * float(conf.get('fx', 1) or 1):,.{digits}f}"
    _, _, sym, _ = DISPLAY_BY_CODE[code]
    return f"{sym}{v * fx_rate(code):,.{digits}f}"


# ---------- 联网数据：实时汇率 + 每日油价 ----------
FX_URL = "https://open.er-api.com/v6/latest/CAD"  # 免费、不用密钥，每天更新
GAS_URL = "https://toronto.citynews.ca/toronto-gta-gas-prices/"  # En-Pro 每日油价预测
ONTARIO_GAS_CSV = "https://ontario.ca/v1/files/fuel-prices/fueltypesall.csv"  # 安省每周，备用
UA = "Mozilla/5.0 (compatible; ShangbanGuliqi/1.0)"
FX_EVERY = 6 * 3600   # 汇率几秒取一次
GAS_EVERY = 2 * 3600  # 油价几秒取一次
LIVE_PATH = os.path.join(CONF_DIR, "live.json")

LIVE = {"rates": {}, "fx_updated": "", "fx_fetched": 0,
        "gas": None, "gas_fetched": 0, "gas_error": ""}

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def load_live():
    try:
        with open(LIVE_PATH, encoding="utf-8") as f:
            LIVE.update(json.load(f))
    except (OSError, ValueError):
        pass


def save_live():
    try:
        os.makedirs(CONF_DIR, exist_ok=True)
        with open(LIVE_PATH, "w", encoding="utf-8") as f:
            json.dump(LIVE, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def http_get(url, timeout=20):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def fx_rate(code):
    if code == "CAD":
        return 1.0
    r = LIVE["rates"].get(code)
    return float(r) if r else float(DISPLAY_BY_CODE[code][3])


def fetch_fx():
    data = json.loads(http_get(FX_URL))
    if data.get("result") != "success":
        raise ValueError("汇率接口返回失败")
    LIVE["rates"] = {c: data["rates"][c] for c, *_ in DISPLAYS if c in data["rates"]}
    LIVE["fx_updated"] = data.get("time_last_update_utc", "")


def parse_citynews(html, today=None):
    """从 CityNews 页面那句话里取：哪天、涨跌多少分、均价多少分/升。

    例：prices are expected to fall 7 cent(s) at 12:01am on November 6, 2026
        to an average of 160.9 cent(s)/litre at local stations.
    """
    import re
    today = today or dt.date.today()
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&#0?38;|&amp;", "&", text)
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"expected to (.{0,160}?)(\d{2,3}(?:\.\d+)?) ?cents?(?:\(s\))? ?(?:/|a |per )litre",
                  text, re.I)
    if not m:
        raise ValueError("页面上没找到油价那句话")
    head, price = m.group(1).lower(), float(m.group(2))

    d = re.search(r"(january|february|march|april|may|june|july|august|september|"
                  r"october|november|december) (\d{1,2})(?:st|nd|rd|th)?,? ?(\d{4})?", head)
    if not d:
        raise ValueError("油价那句话里没找到日期")
    year = int(d.group(3)) if d.group(3) else today.year
    date = dt.date(year, MONTHS[d.group(1)], int(d.group(2)))
    if not d.group(3) and (date - today).days < -180:  # 12 月底说的是来年 1 月
        date = dt.date(year + 1, date.month, date.day)

    if re.search(r"unchanged|stay the same|hold steady|remain stable|no change", head):
        change = 0.0
    else:
        a = re.search(r"(\d+(?:\.\d+)?|half a|a|one) ?cents?", head)
        if not a:
            raise ValueError("油价那句话里没找到涨跌多少")
        amt = {"half a": 0.5, "a": 1.0, "one": 1.0}.get(a.group(1)) or float(a.group(1))
        if re.search(r"\b(fall|drop|decline|decrease|go down|dip|slide)", head):
            change = -amt
        elif re.search(r"\b(rise|climb|increase|go up|jump|spike)", head):
            change = amt
        else:
            raise ValueError("油价那句话里没认出是涨还是跌")
    return {"date": date.isoformat(), "price": price, "change": change, "source": "CityNews"}


def parse_ontario_csv(text):
    """备用：安省每周油价，普通汽油，多伦多东西区平均。没有明天的预测。"""
    import csv, io
    rows = list(csv.reader(io.StringIO(text)))
    head = rows[0]
    cols = [i for i, h in enumerate(head) if h.startswith("Toronto")]
    ftype = head.index("Fuel Type")
    last = [r for r in rows[1:] if len(r) > ftype and r[ftype] == "Regular Unleaded Gasoline"][-1]
    vals = [float(last[i]) for i in cols if float(last[i] or 0) > 0]
    return {"date": last[0], "price": round(sum(vals) / len(vals), 1), "change": None,
            "source": "安省每周"}


def fetch_gas():
    try:
        g = parse_citynews(http_get(GAS_URL))
        LIVE["gas_error"] = ""
    except Exception as ex:
        LIVE["gas_error"] = str(ex)[:80]
        if LIVE["gas"] and LIVE["gas"].get("source") == "CityNews":
            return  # CityNews 这次没认出来，沿用上次的
        g = parse_ontario_csv(http_get(ONTARIO_GAS_CSV, timeout=40))
    old = LIVE["gas"]
    # 新预测换日子了，把旧的那天价格记下来，今天还没到新日子时用它
    if old and old.get("date") != g["date"] and old.get("price"):
        g["prev_price"] = old["price"]
    elif old and old.get("date") == g["date"] and old.get("prev_price"):
        g["prev_price"] = old["prev_price"]
    LIVE["gas"] = g


def gas_today():
    """今天的油价（分/升）。预测日还没到时 = 预测价 − 涨跌。"""
    g = LIVE.get("gas")
    if not g or not g.get("price"):
        return None
    if g.get("change") is None or dt.date.today() >= dt.date.fromisoformat(g["date"]):
        return g["price"]
    return g.get("prev_price") or round(g["price"] - g["change"], 1)


def gas_tomorrow():
    """明天油价的涨跌：(涨跌分数, 明天均价)；没有明天的预测返回 None。"""
    g = LIVE.get("gas")
    if not g or g.get("change") is None:
        return None
    if dt.date.fromisoformat(g["date"]) != dt.date.today() + dt.timedelta(days=1):
        return None
    return g["change"], g["price"]


# ---------- 天气：加拿大环境部（政府公开数据，商用免费） ----------
WX_URL = "https://api.weather.gc.ca/collections/citypageweather-realtime/items/{}?f=json&skipGeometry=true"
WX_EVERY = 30 * 60
# 设置里可选的城市：(中文名, 环境部编号)
CITIES = [
    ("多伦多", "on-143"), ("密西沙加", "on-24"), ("布兰普顿", "on-4"), ("旺市", "on-64"),
    ("万锦", "on-85"), ("列治文山", "on-59"), ("奥克维尔", "on-79"), ("伯灵顿", "on-95"),
    ("汉密尔顿", "on-77"), ("皮克林", "on-54"), ("奥沙瓦", "on-117"), ("惠特比", "on-119"),
    ("纽马基特", "on-25"), ("卡利登", "on-32"), ("霍尔顿山", "on-68"), ("巴里", "on-151"),
    ("基奇纳-滑铁卢", "on-82"), ("圭尔夫", "on-5"), ("剑桥", "on-81"), ("圣凯瑟琳斯", "on-107"),
    ("尼亚加拉瀑布", "on-125"), ("伦敦（安省）", "on-137"), ("渥太华", "on-118"),
    ("金斯顿", "on-69"), ("彼得伯勒", "on-121"), ("温莎", "on-94"),
    ("大萨德伯里", "on-40"), ("雷湾", "on-100"),
]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def wx_kind(text):
    """英文天气 → 类别：thunder / mix / snow / rain / fog / sun / partly / cloud / other"""
    t = (text or "").lower()
    if "thunder" in t:
        return "thunder"
    if "freezing" in t or (("rain" in t or "shower" in t or "drizzle" in t)
                           and ("snow" in t or "flurr" in t)):
        return "mix"
    if "snow" in t or "flurr" in t or "ice pellet" in t:
        return "snow"
    if "rain" in t or "shower" in t or "drizzle" in t or "precipitation" in t:
        return "rain"
    if "fog" in t or "mist" in t or "haze" in t or "smoke" in t:
        return "fog"
    if "mix of sun" in t or "partly" in t or "few clouds" in t or "mainly sunny" in t \
            or "mainly clear" in t or "decreasing cloud" in t:
        return "partly"
    if "sun" in t or "clear" in t:
        return "sun"
    if "cloud" in t or "overcast" in t:
        return "cloud"
    return "other"


WX_ICON = {"thunder": "⚡", "mix": "❄", "snow": "❄", "rain": "☂", "fog": "≋",
           "sun": "☀", "partly": "⛅", "cloud": "☁", "other": "·"}


def wx_zh(text):
    """英文天气描述翻成简短中文，认不出的保留英文。"""
    t = (text or "").lower()
    maybe = "可能有" if "chance of" in t or "possibility" in t else ""
    k = wx_kind(t)
    if k == "thunder":
        z = "雷阵雨"
    elif k == "mix":
        z = "冻雨" if "freezing" in t else "雨夹雪"
    elif k == "snow":
        z = "小雪" if "flurr" in t or "light" in t else "大雪" if "heavy" in t else "雪"
    elif k == "rain":
        z = "毛毛雨" if "drizzle" in t else "阵雨" if "shower" in t else \
            "大雨" if "heavy" in t else "小雨" if "light" in t else \
            "间歇性雨" if "periods" in t else "雨"
    elif k == "fog":
        z = "霾" if "haze" in t else "烟雾" if "smoke" in t else "雾"
    elif k == "partly":
        z = "大致晴朗" if "mainly sunny" in t or "mainly clear" in t else "晴间多云"
    elif k == "sun":
        z = "晴" if "sun" in t else "晴朗"
    elif k == "cloud":
        z = "多云" if "mostly" in t or "mainly" in t or "partly" in t else "阴"
    else:
        return text or ""
    if "wind" in t and k in ("sun", "partly", "cloud"):
        z += "，有风"
    return maybe + z


def fetch_wx(city):
    p = json.loads(http_get(WX_URL.format(city), timeout=30))["properties"]
    cc = p.get("currentConditions") or {}

    def val(d):
        return (d or {}).get("value", {}).get("en")

    hourly = []
    for h in (p.get("hourlyForecastGroup") or {}).get("hourlyForecasts", []):
        when = dt.datetime.fromisoformat(h["timestamp"].replace("Z", "+00:00")).astimezone()
        hourly.append({"time": when.replace(tzinfo=None).isoformat(timespec="minutes"),
                       "t": val(h.get("temperature")), "c": (h.get("condition") or {}).get("en", ""),
                       "pop": val(h.get("lop")) or 0})
    daily = []
    for f in (p.get("forecastGroup") or {}).get("forecasts", []):
        temps = (f.get("temperatures") or {}).get("temperature") or [{}]
        daily.append({"name": f["period"]["textForecastName"]["en"],
                      "day": f["period"]["value"]["en"],
                      "t": val(temps[0]), "cls": (temps[0].get("class") or {}).get("en"),
                      "c": ((f.get("abbreviatedForecast") or {}).get("textSummary") or {}).get("en", "")})
    warns = [(w.get("description") or {}).get("en", "") if isinstance(w, dict) else str(w)
             for w in (p.get("warnings") or [])]
    now_c = (cc.get("condition") or {}).get("en") or (hourly[0]["c"] if hourly else "")
    sun = {}
    for key in ("sunrise", "sunset"):
        v = ((p.get("riseSet") or {}).get(key) or {}).get("en")
        if v:
            t = dt.datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone()
            sun[key] = t.replace(tzinfo=None).isoformat(timespec="minutes")
    LIVE["wx"] = {"city": city, "now_t": val(cc.get("temperature")), "now_c": now_c,
                  "hourly": hourly, "daily": daily, "warnings": [w for w in warns if w], **sun}


def wx_at(when):
    """某个时刻的逐小时预报（取那个整点）；不在 24 小时范围内返回 None。"""
    wx = LIVE.get("wx")
    if not wx:
        return None
    key = when.replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
    return next((h for h in wx["hourly"] if h["time"] == key), None)


def wx_day(offset):
    """今天（0）或明天（1）的 (最高, 最低, 白天天气)，拿不到的项是 None。"""
    wx = LIVE.get("wx")
    if not wx:
        return None
    day = WEEKDAYS_EN[(dt.date.today() + dt.timedelta(days=offset)).weekday()]
    hi = lo = cond = None
    for f in wx["daily"]:
        is_today = f["name"] in ("Today", "Tonight")
        if (offset == 0 and not is_today) or (offset != 0 and is_today):
            continue
        if offset != 0 and not f["day"].startswith(day):
            continue
        if "night" in f["day"].lower() or f["name"] == "Tonight":
            lo = f["t"]
        else:
            hi, cond = f["t"], f["c"]
    return None if hi is None and lo is None else (hi, lo, cond)


def live_worker(stop):
    """后台线程：按间隔取汇率和油价，失败就下次再试（不碰界面）。"""
    import time
    while not stop.is_set():
        now = time.time()
        changed = False
        if now - LIVE["fx_fetched"] > FX_EVERY:
            try:
                fetch_fx()
                LIVE["fx_fetched"] = now
                changed = True
            except Exception:
                LIVE["fx_fetched"] = now - FX_EVERY + 600  # 10 分钟后重试
        if now - LIVE["gas_fetched"] > GAS_EVERY:
            try:
                fetch_gas()
                LIVE["gas_fetched"] = now
                changed = True
            except Exception as ex:
                LIVE["gas_error"] = str(ex)[:80]
                LIVE["gas_fetched"] = now - GAS_EVERY + 600
        city = WX_CITY[0]
        wx = LIVE.get("wx") or {}
        if now - LIVE.get("wx_fetched", 0) > WX_EVERY or wx.get("city") != city:
            try:
                fetch_wx(city)
                LIVE["wx_fetched"] = now
                changed = True
            except Exception:
                LIVE["wx_fetched"] = now - WX_EVERY + 300  # 5 分钟后重试
        if changed:
            save_live()
        if now - UPD["checked"] > UPDATE_EVERY:
            UPD["checked"] = now
            check_and_update()
        stop.wait(20)


WX_CITY = ["on-143"]  # 界面线程改设置时写这里，后台线程读


# ---------- 自动更新：从 GitHub 拿新版，替换自己，重启 ----------
REPO_RAW = "https://raw.githubusercontent.com/MachQ985/shangban-guliqi/main/"
UPDATE_EVERY = 6 * 3600
UPD = {"checked": 0, "ready": None, "msg": "", "busy": False}


def vtuple(v):
    return tuple(int(x) for x in str(v).split("."))


def can_self_update():
    """开发用的那份（文件夹里有 .git）不自动覆盖；没写权限也不更新。"""
    folder = os.path.dirname(os.path.abspath(__file__))
    return not os.path.isdir(os.path.join(folder, ".git")) and os.access(folder, os.W_OK)


def check_and_update(manual=False):
    """查新版；有就下载、校验、替换。在后台线程里跑，结果放进 UPD 给界面看。"""
    import hashlib
    import urllib.parse
    if UPD["busy"] or UPD["ready"]:
        return
    UPD["busy"] = True
    try:
        info = json.loads(http_get(REPO_RAW + "version.json"))
        new = info["version"]
        if vtuple(new) <= vtuple(VERSION):
            if manual:
                UPD["msg"] = f"已经是最新版 v{VERSION}"
            return
        if not can_self_update():
            UPD["msg"] = f"有新版 v{new}，这份是开发版，不自动覆盖"
            return
        import urllib.request
        req = urllib.request.Request(REPO_RAW + urllib.parse.quote(info["file"]),
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        # 三道检查：文件完整（哈希对得上）、是能运行的 Python、版本号对得上
        if hashlib.sha256(data).hexdigest() != info["sha256"]:
            raise ValueError("下载的文件不完整")
        code = data.decode("utf-8")
        compile(code, "new.pyw", "exec")
        if f'VERSION = "{new}"' not in code:
            raise ValueError("新版文件里的版本号不对")

        me = os.path.abspath(__file__)
        os.makedirs(CONF_DIR, exist_ok=True)
        import shutil
        shutil.copy2(me, os.path.join(CONF_DIR, "旧版备份.pyw"))  # 新版有问题可以拿回来
        tmp = me + ".new"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, me)
        UPD["ready"] = new
        UPD["msg"] = f"已更新到 v{new}，马上重启"
    except Exception as ex:
        if manual:
            UPD["msg"] = f"检查更新失败：{str(ex)[:40]}"
    finally:
        UPD["busy"] = False


# ---------- 开机自启 ----------
def autostart_enabled():
    return os.path.exists(STARTUP_FILE)


def set_autostart(on):
    script = os.path.abspath(__file__)
    if not on:
        if os.path.exists(STARTUP_FILE):
            os.remove(STARTUP_FILE)
        return
    os.makedirs(os.path.dirname(STARTUP_FILE), exist_ok=True)
    if IS_MAC:
        import plistlib
        with open(STARTUP_FILE, "wb") as f:
            plistlib.dump({
                "Label": "local.shangban-guliqi",
                "ProgramArguments": [sys.executable, script],
                "RunAtLoad": True,
            }, f)
    else:
        pyw = sys.executable.replace("python.exe", "pythonw.exe")
        with open(STARTUP_FILE, "w", encoding="utf-16") as f:
            f.write(f'CreateObject("WScript.Shell").Run """{pyw}"" ""{script}""", 0\r\n')


# ---------- 桌宠：素材处理（只用 Tk，不依赖 PIL） ----------
# 平时的小动作：LOOP 循环待一会儿，ONCE 做两遍就回到平时
PET_EXTRA_LOOP = ["loaf", "look", "knead", "nap", "tailwag", "upside", "curious",
                  "liquid", "pancake", "rub"]
PET_EXTRA_ONCE = ["groom", "yawn", "stretch", "scratch", "earflick", "lickbelly",
                  "licktail", "shake", "drink", "hairball"]
PET_ONCE_WEIGHT = {"hairball": .25}           # 吐毛球少一点，其他默认 1
PET_SLEEP_POSES = ["sleep", "nap", "upsleep"]  # 睡觉时轮换的睡姿
# 互动动作：被摸、被戳、被拎起、双击、离开电脑、上班事件时用
PET_INTERACT = ["pet", "belly", "angry", "annoyed", "carried", "land", "roll", "punch",
                "drowsy", "wake", "beg", "full", "excited", "sad",
                "scared", "twitch", "upsleep", "watchl", "watchr", "swatl", "swatr"]
# 素材里缺某个动作时用谁代替（可以连环找），最后都落到 idle
PET_FALLBACK = {"click": "happy", "pet": "happy", "belly": "happy", "angry": "click",
                "annoyed": "idle", "carried": "click", "land": "idle", "roll": "play",
                "punch": "play", "drowsy": "idle", "wake": "click", "beg": "hungry",
                "full": "happy", "excited": "happy", "sad": "idle",
                "scared": "angry", "twitch": "sleep", "upsleep": "nap", "watchl": "look",
                "watchr": "look", "swatl": "play", "swatr": "play", "curious": "look",
                "rub": "pet", "appear": "wake", "disappear": "sleep"}
PET_EFFECTS = ["heart", "question", "exclaim", "anger", "note", "sweat"]  # 头顶小特效 fx_*.png
PET_STATES = ["idle", "eat", "play", "sleep", "happy", "click", "hungry", "work",
              "rain", "snow", "cold", "hot", "sunny",
              "appear", "disappear"] + PET_EXTRA_LOOP + PET_EXTRA_ONCE + PET_INTERACT
PET_STATE_NAMES = {"idle": "平时", "eat": "吃饭", "play": "玩耍", "sleep": "睡觉", "happy": "开心",
                   "click": "被戳", "hungry": "饿了", "work": "上班", "rain": "下雨", "snow": "下雪",
                   "cold": "寒冷", "hot": "炎热", "sunny": "晴天",
                   "loaf": "揣手趴着", "look": "张望", "knead": "踩奶", "groom": "舔爪洗脸",
                   "yawn": "打哈欠", "stretch": "伸懒腰", "scratch": "挠耳朵", "nap": "躺着睡",
                   "pet": "被摸头", "belly": "翻肚皮", "angry": "生气", "annoyed": "不耐烦",
                   "carried": "被拎起", "land": "落地", "roll": "打滚", "punch": "猫猫拳",
                   "drowsy": "犯困", "wake": "惊醒", "beg": "讨食", "full": "吃饱舔嘴",
                   "excited": "兴奋", "sad": "委屈",
                   "earflick": "抖耳朵", "tailwag": "摇尾巴", "upside": "四脚朝天",
                   "lickbelly": "舔肚皮", "licktail": "舔尾巴", "shake": "抖身体",
                   "hairball": "吐毛球", "scared": "害怕", "curious": "好奇", "rub": "撒娇",
                   "drink": "喝水", "liquid": "液体猫", "pancake": "猫饼", "twitch": "睡梦抽动",
                   "upsleep": "四脚朝天睡", "watchl": "往左看", "watchr": "往右看",
                   "swatl": "往左拍", "swatr": "往右拍", "appear": "登场", "disappear": "退场"}
PET_ICONS = ["snack", "freeze_dried", "can", "wand"]
PET_DIR = os.path.join(CONF_DIR, "pet")
PET_SIZE, PET_GROUND, PET_ICON = 64, 56, 32   # 显示几何的逻辑画布：帧 64×64，脚底在第 56 行；图标 32×32
PET_FX = 16                                   # 头顶特效 16×16
PET_TOP = 16                                  # 猫窗口上方多留的高度，给特效往上飘
PET_CAT_HEIGHT = 46                           # 自动处理时，平时坐姿缩放到大约这么高（相对 PET_SIZE 画布）
PET_STORE = 256                               # 动画帧实际存储分辨率，显示时再缩到 PET_SIZE×大小；越大越清晰、导入越慢（想快改回 64）
PET_SCALE = PET_STORE // PET_SIZE             # 存储相对逻辑画布的倍数
PET_KEY = "#ff00fe"                           # 读图时用这个颜色标记透明像素
PET_FPS_MS = 250

# ---------- 桌宠：给 AI 画素材用的提示词（设置 → 宠物 → 复制提示词） ----------
# (批次标题, [(文件名, 画什么), ...])；和 PET_STATES 一一对应，改动作时两边一起改
PET_AI_BATCHES = [
    ("第一批：必需和常用（先画这批就能用）", [
        ("idle", "安静地端坐，正面看着前方（最重要，后面所有图的大小和位置都以它为准）"),
        ("eat", "低头吃碗里的食物"),
        ("play", "抬起前爪扑逗猫棒"),
        ("sleep", "蜷成一团闭眼睡觉"),
        ("happy", "眯眼微笑，尾巴竖起"),
        ("click", "被戳了一下，吓一跳（只要 1 帧）"),
        ("hungry", "可怜巴巴地望着你，旁边一个空碗"),
        ("work", "趴在一台小笔记本电脑前打字"),
        ("rain", "撑着一把小伞，有雨点"),
        ("snow", "头上和身上落着雪花"),
        ("cold", "缩成一团发抖"),
        ("hot", "热得吐舌头、摊开"),
        ("sunny", "晒太阳，眯眼很舒服"),
    ]),
    ("第二批：平时的小动作（可选）", [
        ("loaf", "前爪揣在身下，趴成面包"),
        ("look", "左右张望"),
        ("knead", "前爪交替踩奶"),
        ("nap", "侧躺打盹"),
        ("tailwag", "坐着慢慢摇尾巴"),
        ("upside", "四脚朝天躺着"),
        ("curious", "歪头好奇"),
        ("liquid", "软成一摊，像液体"),
        ("pancake", "整个趴平成一张饼"),
        ("rub", "侧身蹭过来撒娇"),
        ("groom", "舔爪子洗脸"),
        ("yawn", "张大嘴打哈欠"),
        ("stretch", "前身压低伸懒腰"),
        ("scratch", "用后腿挠耳朵"),
        ("earflick", "抖一下耳朵"),
        ("lickbelly", "低头舔肚皮"),
        ("licktail", "抱着尾巴舔"),
        ("shake", "抖身体，毛炸开"),
        ("drink", "低头喝碗里的水"),
        ("hairball", "弓背吐毛球"),
    ]),
    ("第三批：互动动作（可选，缺了会用相近的动作代替）", [
        ("pet", "被摸头，眯眼享受"),
        ("belly", "翻出肚皮"),
        ("annoyed", "不耐烦，甩尾巴"),
        ("angry", "生气，耳朵向后压成飞机耳"),
        ("carried", "被拎起来，四肢悬空"),
        ("land", "落地，稍微下蹲"),
        ("roll", "在地上打滚"),
        ("punch", "挥出一记猫猫拳"),
        ("drowsy", "犯困，头一点一点"),
        ("wake", "猛地惊醒，眼睛睁大"),
        ("beg", "立起来讨食"),
        ("full", "吃饱了舔嘴"),
        ("excited", "兴奋地跳起来"),
        ("sad", "委屈，耳朵耷拉"),
        ("scared", "害怕，全身炸毛"),
        ("twitch", "睡着时爪子抽动"),
        ("upsleep", "四脚朝天睡觉"),
        ("watchl", "盯着画面左边"),
        ("watchr", "盯着画面右边"),
        ("swatl", "向左边伸爪拍"),
        ("swatr", "向右边伸爪拍"),
        ("appear", "登场：从低伏/蜷缩慢慢起身坐直，像刚出现（显示宠物时播；缺了用惊醒代替）"),
        ("disappear", "退场：从坐姿缩低、身体变小准备离开，像要消失（隐藏宠物时播；缺了用睡觉代替）"),
    ]),
]
PET_AI_ITEMS = [
    ("snack", "一小把鱼干零食"), ("freeze_dried", "一块冻干"),
    ("can", "一个打开的罐头"), ("wand", "一根带羽毛的逗猫棒"),
    ("fx_heart", "红色爱心"), ("fx_question", "问号"), ("fx_exclaim", "感叹号"),
    ("fx_anger", "生气的十字青筋符号"), ("fx_note", "音符"), ("fx_sweat", "一滴汗"),
]


def pet_ai_prompt():
    """复制给能画图的 AI（比如 ChatGPT）的整段提示词，和照片一起发。"""
    lines = [
        "你是一名像素画师。请参考我上传的宠物照片，为一个桌面小宠物程序画一整套动作素材。",
        "",
        "【第一步：先确认长相，先别画】",
        "仔细看照片，用几句话总结这只宠物的外观：种类和体型、毛色和花纹分布（哪个部位是什么颜色）、"
        "眼睛颜色、耳朵和尾巴的特点。等我确认或补充后再开始画；之后每一张都必须保持这些特征。",
        "",
        "【画风和画布：每一张都一样】",
        "- 像素风（pixel art），Q 版大头小身子，轮廓清晰，全套颜色控制在 16 色以内。",
        "- 正方形画布，纯绿色 #00FF00 背景，背景里不要有任何别的东西。",
        "- 宠物全身入画、水平居中；脚底（或身体着地的部分）始终踩在画面高度约 85% 的同一条线上，"
        "端坐时头顶在约 15% 处。",
        "- 所有动作里宠物的大小保持一致，不要因为动作不同而放大或缩小，也不要改变镜头角度。",
        "- 宠物身上不要用和背景一样的亮绿色。",
        "- 不要文字、水印、边框、地面和阴影；睡觉的“Zz”用小气泡代替。",
        "- 每张图只画一个动作的一帧。",
        "",
        "【要画的动作】",
        "按顺序画，冒号前是文件名。除非另有说明，每个动作画 2 帧（文件名 _1、_2），"
        "两帧之间只有很小的变化（呼吸起伏、眨眼、尾巴摆动、爪子换位），像简单的循环动画。",
    ]
    for title, items in PET_AI_BATCHES:
        lines += ["", title]
        lines += [f"- {key}：{what}" for key, what in items]
    lines += ["", "道具和头顶特效（各 1 张，同样绿底、像素风、居中、不用分帧，文件名不加 _1）："]
    lines += [f"- {key}：{what}" for key, what in PET_AI_ITEMS]
    lines += [
        "",
        "【交付方式】",
        "- 如果你能运行代码：每画完一批，把图片按上面的文件名存成 PNG（不要 JPG），"
        "例如 idle_1.png、idle_2.png、snack.png，打包成 zip 给我下载。",
        "- 如果不能运行代码：每次只画一张，并告诉我这张要保存成什么文件名（PNG），我说“继续”再画下一张。",
        "- 如果这只宠物不是猫，猫特有的动作（踩奶、吐毛球、液体猫等）换成这种动物相近的动作，文件名不变。",
    ]
    return "\n".join(lines)


def _pet_scan(src):
    """按文件名认动作：idle_1.png / idle.png / IDLE-2.PNG 都行。返回 ({动作: [文件…]}, {图标: 文件}, 跳过的文件)。"""
    import re
    frames, icons, skipped = {}, {}, []
    pat = re.compile(r"^([a-z_]+?)(?:[_-]?(\d+))?\.(png|gif)$", re.I)
    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        if not os.path.isfile(path):
            continue
        m = pat.match(name)
        base = m.group(1).lower() if m else ""
        if m and base.startswith("fx_") and base[3:] in PET_EFFECTS:
            icons["fx_" + base[3:]] = path
        elif m and base in PET_STATES:
            frames.setdefault(base, []).append((int(m.group(2) or 0), path))
        elif m and base in PET_ICONS:
            icons[base] = path
        elif name.lower().endswith((".png", ".gif", ".jpg", ".jpeg", ".webp")):
            why = "JPG / WEBP 读不了，请导出成 PNG" if not name.lower().endswith((".png", ".gif")) \
                else "文件名认不出是哪个动作"
            skipped.append(f"{name}（{why}）")
    return ({k: [p for _, p in sorted(v)] for k, v in frames.items()}, icons, skipped)


def _pet_read(path, limit=256):
    """读一张图 → (像素网格[行][列]=颜色或 None, 缩小倍数)。大图先整数缩小到 limit 以内。"""
    import math
    img = tk.PhotoImage(file=path)
    w, h = img.width(), img.height()
    k = max(1, math.ceil(max(w, h) / limit))
    if k > 1:
        small = tk.PhotoImage()
        small.tk.call(small, "copy", img, "-subsample", k, k)
        img = small
    rows = img.tk.splitlist(img.tk.call(img, "data", "-background", PET_KEY))
    grid = [[None if c == PET_KEY else c for c in img.tk.splitlist(r)] for r in rows]
    return grid, k


def _rgb(c):
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _pet_key_background(grid):
    """没有透明背景的图：从四条边往里“漫水”，把和边缘颜色接近、连成一片的背景抠掉。
    只抠和边缘连着的部分，猫身上的白毛不会被误抠。"""
    h, w = len(grid), len(grid[0])
    border = [grid[y][x] for y in (0, h - 1) for x in range(w)] + \
             [grid[y][x] for x in (0, w - 1) for y in range(h)]
    if any(c is None for c in border):
        return grid  # 本来就是透明背景
    from collections import Counter, deque
    key = _rgb(Counter(border).most_common(1)[0][0])
    greenish = key[1] > key[0] + 60 and key[1] > key[2] + 60
    tol = 110 if greenish else 60

    def is_bg(c):
        r, g, b = _rgb(c)
        if greenish and g > r + 40 and g > b + 40:  # 绿幕边缘的绿色溢色
            return True
        return (r - key[0]) ** 2 + (g - key[1]) ** 2 + (b - key[2]) ** 2 < tol * tol

    seen = [[False] * w for _ in range(h)]
    q = deque([(x, y) for y in (0, h - 1) for x in range(w)] +
              [(x, y) for x in (0, w - 1) for y in range(h)])
    while q:
        x, y = q.popleft()
        if seen[y][x] or grid[y][x] is None or not is_bg(grid[y][x]):
            continue
        seen[y][x] = True
        grid[y][x] = None
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx]:
                q.append((nx, ny))
    if greenish:
        # 绿幕：被身体围住的绿色（尾巴圈里、伞柄和身体之间）跟边缘不连通，也要抠掉。
        # 猫本身不会是这种亮绿色，所以全图抠；白底不这样做，免得把白毛抠掉
        for row in grid:
            for x, c in enumerate(row):
                if c is not None and is_bg(c):
                    row[x] = None
    return grid


def _pet_bbox(grid):
    ys = [y for y, row in enumerate(grid) if any(c is not None for c in row)]
    xs = [x for x in range(len(grid[0])) if any(row[x] is not None for row in grid)]
    return (min(xs), min(ys), max(xs), max(ys)) if xs and ys else None


def _pet_resample(grid, k, scale, cx, cy, size, ox, oy):
    """把源图（源像素坐标）缩放 scale 倍，源上的点 (cx, cy) 对到输出的 (ox, oy)。
    每个输出像素在源图对应的小方块里取几个点“投票”：多数透明就透明，否则取最常见的颜色。"""
    from collections import Counter
    out = [[None] * size for _ in range(size)]
    h, w = len(grid), len(grid[0])
    step = 1 / scale                       # 一个输出像素对应多少源像素
    n = max(1, min(4, int(step / k)))      # 每边取几个采样点
    for Y in range(size):
        for X in range(size):
            votes = []
            for j in range(n):
                for i in range(n):
                    sx = (X + (i + .5) / n - ox) * step + cx
                    sy = (Y + (j + .5) / n - oy) * step + cy
                    gx, gy = int(sx // k), int(sy // k)
                    votes.append(grid[gy][gx] if 0 <= gx < w and 0 <= gy < h else None)
            solid = [v for v in votes if v is not None]
            if len(solid) * 2 > len(votes):
                out[Y][X] = Counter(solid).most_common(1)[0][0]
    return out


def _pet_quantize(grids, k=16):
    """整套素材统一减到 k 种颜色（像素风的调色板），简单的 k-means。"""
    import random as _r
    pix = [_rgb(c) for g in grids for row in g for c in row if c is not None]
    uniq = list(set(pix))
    if len(uniq) <= k:
        return grids
    rnd = _r.Random(1)
    sample = rnd.sample(pix, min(len(pix), 6000))
    cents = rnd.sample(uniq, k)
    for _ in range(10):
        buckets = [[] for _ in cents]
        for p in sample:
            i = min(range(len(cents)), key=lambda j: sum((a - b) ** 2 for a, b in zip(p, cents[j])))
            buckets[i].append(p)
        cents = [tuple(sum(c) // len(b) for c in zip(*b)) if b else cents[i]
                 for i, b in enumerate(buckets)]
    cache = {}

    def near(c):
        if c not in cache:
            p = _rgb(c)
            best = min(cents, key=lambda q: sum((a - b) ** 2 for a, b in zip(p, q)))
            cache[c] = "#%02x%02x%02x" % best
        return cache[c]
    return [[[near(c) if c is not None else None for c in row] for row in g] for g in grids]


def _pet_write(grid, path):
    size = len(grid)
    img = tk.PhotoImage(width=size, height=size)  # 新建的图默认全透明
    for y, row in enumerate(grid):
        x = 0
        while x < size:  # 连续的不透明像素一次写进去
            if row[x] is None:
                x += 1
                continue
            x0 = x
            while x < size and row[x] is not None:
                x += 1
            img.put("{" + " ".join(row[x0:x]) + "}", to=(x0, y))
    img.write(path, format="png")


def import_pet_assets(src, progress=None):
    """把一个文件夹里的素材处理成标准桌宠素材，放进 PET_DIR。返回报告 dict。

    - 已经是标准规格（64×64、透明背景）的直接复制；
    - 其他任意大小的 PNG：自动去背景（透明 / 纯色背景都行）、按“平时”那张统一缩放成
      64×64 像素风、脚底对齐到第 56 行、水平居中，全套减到 16 色。
    """
    import shutil
    import tempfile
    frames, icons, skipped = _pet_scan(src)
    if "idle" not in frames:
        return {"ok": False, "error": "没找到“平时”的图（idle.png 或 idle_1.png），这张是必需的",
                "skipped": skipped}
    sizes = {}
    for p in [p for v in frames.values() for p in v] + list(icons.values()):
        im = tk.PhotoImage(file=p)
        sizes[p] = (im.width(), im.height())

    def is_std(p, s):
        if sizes[p] != (s, s):
            return False
        g, _ = _pet_read(p)
        return any(c is None for row in g for c in row)

    tmp = tempfile.mkdtemp(prefix="pet_")
    sprite_files = [p for v in frames.values() for p in v]
    std = all(is_std(p, PET_STORE) for p in sprite_files)
    out_frames = {}
    if std:  # 已经是标准规格：原样复制
        for st, paths in frames.items():
            out_frames[st] = []
            for i, p in enumerate(paths, 1):
                name = f"{st}_{i}.png"
                shutil.copy(p, os.path.join(tmp, name))
                out_frames[st].append(name)
    else:
        read = {}
        for n, p in enumerate(sprite_files, 1):
            g, k = _pet_read(p)
            read[p] = (_pet_key_background(g), k)
            if progress:
                progress(f"读取素材 {n}/{len(sprite_files)}…")
        g0, k0 = read[frames["idle"][0]]
        bb = _pet_bbox(g0)
        if not bb:
            return {"ok": False, "error": "“平时”那张图是空的，或者背景没能去掉"}
        # 按“平时”那张算缩放和位置，整套共用，动作之间不跳
        scale = PET_CAT_HEIGHT * PET_SCALE / ((bb[3] - bb[1] + 1) * k0)
        cx = (bb[0] + bb[2] + 1) / 2 * k0
        bottom = (bb[3] + 1) * k0
        grids, names = [], []
        for n, (st, paths) in enumerate(frames.items(), 1):
            for i, p in enumerate(paths, 1):
                g, k = read[p]
                grids.append(_pet_resample(g, k, scale, cx, bottom, PET_STORE,
                                           PET_STORE / 2, (PET_GROUND + 1) * PET_SCALE))
                names.append((st, f"{st}_{i}.png"))
            if progress:
                progress(f"缩成像素风 {n}/{len(frames)}…")
        if progress:
            progress("统一调色板…")
        grids = _pet_quantize(grids)
        for (st, name), g in zip(names, grids):
            _pet_write(g, os.path.join(tmp, name))
            out_frames.setdefault(st, []).append(name)

    out_icons, out_fx = {}, {}
    for ic, p in icons.items():
        name = f"{ic}.png"
        size = PET_FX if ic.startswith("fx_") else PET_ICON
        if ic.startswith("fx_"):
            out_fx[ic[3:]] = name
        if is_std(p, size):
            shutil.copy(p, os.path.join(tmp, name))
        else:
            g, k = _pet_read(p)
            g = _pet_key_background(g)
            bb = _pet_bbox(g)
            if not bb:
                continue
            s = (size - 2) / ((max(bb[2] - bb[0], bb[3] - bb[1]) + 1) * k)
            g = _pet_resample(g, k, s, (bb[0] + bb[2] + 1) / 2 * k, (bb[1] + bb[3] + 1) / 2 * k,
                              size, size / 2, size / 2)
            _pet_write(_pet_quantize([g])[0], os.path.join(tmp, name))
        if not ic.startswith("fx_"):
            out_icons[ic] = name

    name = os.path.basename(os.path.normpath(src))
    try:  # 素材自带清单（比如 Codex 做的）里写了名字就用它
        with open(os.path.join(src, "manifest.json"), encoding="utf-8") as f:
            name = json.load(f).get("name") or name
    except (OSError, ValueError):
        pass
    with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "states": out_frames, "icons": out_icons, "effects": out_fx,
                   "ground_y": PET_GROUND, "frame_duration_ms": PET_FPS_MS,
                   "processed": not std}, f, ensure_ascii=False, indent=2)
    if os.path.isdir(PET_DIR):
        shutil.rmtree(PET_DIR)
    os.makedirs(os.path.dirname(PET_DIR), exist_ok=True)
    shutil.move(tmp, PET_DIR)
    return {"ok": True, "name": name, "states": {k: len(v) for k, v in out_frames.items()},
            "icons": list(out_icons), "missing": [s for s in PET_STATES if s not in out_frames],
            "skipped": skipped, "processed": not std}


# ---------- 桌宠：喂养规则 ----------
# (编号, 名字, 每上班多少秒得一个（None = 上满一天得一个）, 加饱腹, 加心情)
PET_FOODS = [("snack", "零食", 30 * 60, 5, 5),
             ("freeze_dried", "冻干", 2 * 3600, 15, 10),
             ("can", "罐头", None, 40, 15)]
PET_WAND_COOLDOWN = 30 * 60
PET_WAND_MOOD = 20
PET_DECAY = {"full": 4, "mood": 3}  # 每小时掉多少


def user_idle_seconds():
    """用户多久没碰鼠标键盘（秒）。Windows 直接问系统；Mac 暂不支持，返回 0。"""
    if IS_MAC:
        return 0
    try:
        class LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        lii = LII()
        lii.cbSize = ctypes.sizeof(LII)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return ((ctypes.windll.kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000
    except Exception:
        pass
    return 0


class Pet:
    """趴在悬浮窗顶上的小猫：透明小窗跟着悬浮窗走，按状态播放素材动画。"""

    def __init__(self, app):
        self.app = app
        self.win = self.cv = self.img_id = self.panel = None
        self.frames, self.icons, self.effects, self.manifest = {}, {}, {}, {}
        self.state, self.idx, self.st = "idle", 0, "work"
        self.offset, self.dragging, self.near_off = (0, 0), False, False
        self.transient = []          # [(动作, 结束时间), …] 吃 / 玩 / 被戳之后依次播放
        self.ambient, self.ambient_until = "idle", 0
        self.last_save = 0
        self.data = self.app.conf.setdefault("pet", {})
        self.data.setdefault("full", 80.0)
        self.data.setdefault("mood", 80.0)
        self.data.setdefault("inv", {"snack": 0, "freeze_dried": 0, "can": 0})
        self.data.setdefault("love", 0)
        self.reload()
        self.animate()

    # ----- 素材 -----
    def zoom(self):
        return int(self.app.conf.get("pet_zoom", 2))

    def _disp(self, name, target):
        """把一帧缩放到目标显示像素；按文件实际分辨率有理缩放，所以 64 旧素材和 256 高清素材都正确。"""
        from math import gcd
        img = tk.PhotoImage(file=os.path.join(PET_DIR, name))
        src = img.width() or target
        g = gcd(target, src)
        a, b = target // g, src // g
        if a > 1:
            img = img.zoom(a)
        if b > 1:
            img = img.subsample(b)
        return img

    def set_visible(self, on, anim=True):
        """显示 / 隐藏桌宠，带淡入淡出（有 appear / disappear 素材就一起播）。连续切换时后一次优先。"""
        self.vis_gen = getattr(self, "vis_gen", 0) + 1
        gen = self.vis_gen
        if on:
            if self.win is None:
                self.reload()               # 建窗（调用方须先把 conf['pet_on'] 置 True）
            if self.win is None:
                return                       # 没素材，建不起来
            if not anim:
                self._set_alpha(1.0)
                return
            self._set_alpha(0.0)
            if "appear" in self.frames:
                self.play("appear", max(.4, len(self.frames["appear"]) * self.frame_ms() / 1000 * 2))
            else:
                self.transient = []          # 清掉可能残留的退场动作
            self._fade(gen, 0.0, 1.0, then=lambda: self.jiggle("bounce"))
        else:
            if self.win is None:
                return
            if not anim:
                self.win.destroy()
                self.win = None
                return
            dur = .5
            if "disappear" in self.frames:
                dur = max(.5, len(self.frames["disappear"]) * self.frame_ms() / 1000 * 2)
                self.play("disappear", dur)
            self._fade(gen, 1.0, 0.0, steps=max(10, int(dur / .025)),
                       then=lambda: self._finish_hide(gen))

    def _set_alpha(self, v):
        try:
            self.win.attributes("-alpha", v)
        except tk.TclError:
            pass                             # 平台不支持窗口透明度：忽略（相当于瞬间）

    def _fade(self, gen, start, end, then=None, i=0, steps=12, ms=25):
        if gen != self.vis_gen or self.win is None:   # 被新的切换取代，或窗口已没了
            if then and gen == self.vis_gen:
                then()
            return
        self._set_alpha(start + (end - start) * min(i, steps) / steps)
        if i >= steps:
            if then:
                then()
            return
        self.app.root.after(ms, self._fade, gen, start, end, then, i + 1, steps, ms)

    def _finish_hide(self, gen):
        if gen != self.vis_gen:              # 淡出途中又点了显示：保留窗口，交给那次操作
            return
        if self.win is not None:
            self.win.destroy()
            self.win = None

    def reload(self):
        """（重新）读取素材并建窗口；没导入素材或关掉了宠物就不显示。"""
        self.frames, self.icons, self.effects, self.manifest = {}, {}, {}, {}
        if self.win is not None:
            self.win.destroy()
            self.win = None
        path = os.path.join(PET_DIR, "manifest.json")
        if not self.app.conf.get("pet_on", True) or not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                self.manifest = json.load(f)
            z = self.zoom()
            for st, names in self.manifest.get("states", {}).items():
                self.frames[st] = [self._disp(n, PET_SIZE * z) for n in names]
            for ic, n in self.manifest.get("icons", {}).items():
                self.icons[ic] = tk.PhotoImage(file=os.path.join(PET_DIR, n))
            for fx, n in self.manifest.get("effects", {}).items():
                self.effects[fx] = self._disp(n, PET_FX * z)
        except Exception:
            self.frames = {}
            return
        if "idle" not in self.frames:
            return
        s = PET_SIZE * self.zoom()
        self.win = tk.Toplevel(self.app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        bg = PET_KEY
        if IS_MAC:
            try:
                self.win.attributes("-transparent", True)
                bg = "systemTransparent"
            except tk.TclError:
                pass
        else:
            self.win.attributes("-transparentcolor", PET_KEY)
        self.win.configure(bg=bg)
        self.cv = tk.Canvas(self.win, width=s, height=s + PET_TOP * self.zoom(), bg=bg,
                            highlightthickness=0, bd=0,
                            cursor="hand2")
        self.cv.pack()
        self.img_id = self.cv.create_image(0, PET_TOP * self.zoom(), anchor="nw",
                                           image=self.frames["idle"][0])
        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        self.cv.bind("<Double-Button-1>", self.on_double)
        self.cv.bind("<Motion>", self.on_hover)
        for seq in ("<Button-3>",) + (("<Button-2>", "<Control-Button-1>") if IS_MAC else ()):
            self.cv.bind(seq, lambda _e: self.open_panel())
        self.follow()

    def follow(self):
        """猫的脚踩在悬浮窗上边缘，靠右（窗口上方多留 PET_TOP 给头顶特效）。"""
        if self.win is None:
            return
        r, z = self.app.root, self.zoom()
        s = PET_SIZE * z
        dx, dy = self.offset
        x = r.winfo_x() + r.winfo_width() - s - 14 + dx
        y = r.winfo_y() - (PET_TOP + PET_GROUND + 1) * z + 3 * z + dy
        self.win.geometry(f"{s}x{s + PET_TOP * z}+{x}+{max(0, y)}")
        self.win.lift()

    def jiggle(self, kind="bounce"):
        """程序化小动作，不用画新帧：bounce 弹一下，shake 抖几下。"""
        z = self.zoom()
        seq = [(0, -3), (0, -5), (0, -3), (0, -1), (0, 0)] if kind == "bounce" else \
              [(-1, 0), (1, 0), (-1, 0), (1, 0), (-1, 0), (0, 0)]

        def step(i=0):
            if self.win is None:
                return
            self.offset = (seq[i][0] * z, seq[i][1] * z)
            self.follow()
            if i + 1 < len(seq):
                self.app.root.after(45, step, i + 1)
        step()

    def fx(self, name):
        """头顶冒一个小特效（爱心、问号、感叹号…），往上飘一会儿就消失。"""
        img = self.effects.get(name)
        if self.win is None or img is None:
            return
        z = self.zoom()
        item = self.cv.create_image((PET_SIZE // 2 + random.randint(6, 16)) * z,
                                    (PET_TOP + 12) * z, image=img, anchor="s")

        def rise(i=0):
            if self.win is None:
                return
            if i >= 12:
                self.cv.delete(item)
                return
            self.cv.move(item, 0, -z)
            self.app.root.after(80, rise, i + 1)
        self.app.root.after(80, rise)

    # ----- 状态 -----
    def decay(self):
        import time
        now = time.time()
        hours = max(0.0, (now - self.data.get("ts", now)) / 3600)
        for k, per_h in PET_DECAY.items():
            self.data[k] = max(0.0, self.data[k] - per_h * hours)
        self.data["ts"] = now

    def earn(self, r, st, conf):
        """按今天已上班的时长发吃的（和算钱用的是同一套时间）。返回新得到的东西列表。"""
        today = dt.date.today().isoformat()
        if self.data.get("day") != today:
            self.data["day"], self.data["got"] = today, {"snack": 0, "freeze_dried": 0, "can": 0}
        if st == "off":
            return []
        s, e = parse_hm(conf["start"]), parse_hm(conf["end"])
        span = (e.hour * 3600 + e.minute * 60) - (s.hour * 3600 + s.minute * 60)
        worked = r["progress"] * span
        got, inv, new = self.data["got"], self.data["inv"], []
        for key, name, every, _, _ in PET_FOODS:
            due = (1 if st == "after" else 0) if every is None else int(worked // every)
            if due > got.get(key, 0):
                n = due - got.get(key, 0)
                inv[key] = inv.get(key, 0) + n
                got[key] = due
                new.append(f"{name} ×{n}")
        return new

    def update(self, r, st, conf):
        """悬浮窗每次刷新时调用：衰减、发吃的、上班事件、定时存盘。"""
        import time
        prev, self.st = self.st, st
        self.decay()
        new = self.earn(r, st, conf)
        if new:
            if self.win is not None:
                self.app.flash(f"上班奖励：{'、'.join(new)}，右键小猫去喂它")
            self.save()
        elif time.time() - self.last_save > 60:
            self.save()
        if self.win is None:
            return
        # 上班事件联动
        self.near_off = st == "work" and r.get("remain") is not None and r["remain"] <= 300
        if prev == "work" and st == "after":          # 下班那一刻：跳起来
            self.play("excited", 3, "happy", 3)
            self.fx("note")
            self.jiggle()
        today = dt.date.today().isoformat()
        tm = gas_tomorrow()
        if tm and tm[0] < 0 and st in ("before", "work") and self.data.get("gas_cheer") != today:
            self.data["gas_cheer"] = today            # 明天油价跌：每天开心一次
            self.play("happy", 2.5)
            self.fx("note")

    def save(self):
        import time
        self.last_save = time.time()
        save_conf(self.app.conf)

    def has_food(self):
        return any(v > 0 for v in self.data["inv"].values())

    def sleep_pose_now(self, now):
        """几种睡姿轮换（蜷着、侧躺、四脚朝天），每种睡 1–3 分钟；蜷着睡时偶尔睡梦抽动。"""
        poses = [x for x in PET_SLEEP_POSES if x in self.frames] or ["sleep"]
        if now >= getattr(self, "sleep_until", 0) or getattr(self, "sleep_pose", None) not in poses:
            others = [x for x in poses if x != getattr(self, "sleep_pose", None)] or poses
            self.sleep_pose = random.choice(others)
            self.sleep_until = now + random.uniform(60, 180)
        if self.sleep_pose == "sleep" and "twitch" in self.frames and random.random() < .004:
            self.play("twitch", 1.5)               # 平均一两分钟抽一下
            return "twitch"
        return self.sleep_pose

    def pick_state(self):
        import time
        now = time.time()
        while self.transient and self.transient[0][1] <= now:
            self.transient.pop(0)
        if self.transient:
            return self.transient[0][0]

        # 你离开电脑：5 分钟犯困，10 分钟睡着；回来时惊醒、伸个懒腰
        away = user_idle_seconds()
        if away >= 300:
            self.was_away = True
            return self.sleep_pose_now(now) if away >= 600 else "drowsy"
        if getattr(self, "was_away", False) and away < 3:
            self.was_away = False
            self.fx("exclaim")
            self.play("wake", 1.2, "stretch" if "stretch" in self.frames else "idle", 1.5)
            return "wake"

        if self.data["full"] < 25:
            return "beg" if self.has_food() else "hungry"
        hour = dt.datetime.now().hour
        if self.st in ("after", "off") or hour >= 22 or hour < 6:
            return self.sleep_pose_now(now)
        watch = self.watch_cursor(now)
        if watch:
            return watch
        if now >= self.ambient_until:  # 每 12–20 秒换一个“平常状态”：天气 / 上班 / 平时 / 小动作
            wx = LIVE.get("wx") or {}
            kind, t = wx_kind(wx.get("now_c", "")), wx.get("now_t")
            weather = "snow" if kind == "snow" else "rain" if kind in ("rain", "mix", "thunder") \
                else "cold" if t is not None and t <= 0 else "hot" if t is not None and t >= 28 \
                else "sunny" if kind == "sun" and 8 <= hour < 18 else None
            if kind == "thunder" and random.random() < .4:
                weather = "scared"                 # 打雷：有时吓一跳
            loops = [x for x in PET_EXTRA_LOOP if x in self.frames
                     and (x != "rub" or self.data["love"] >= 20)]  # 亲密度 Lv.3 起才撒娇
            pool = ["idle", "idle"] + (["work", "work"] if self.st == "work" else []) + \
                   ([weather] * 3 if weather else []) + loops + \
                   (["excited"] * 4 if getattr(self, "near_off", False) else [])  # 快下班了
            self.ambient, self.ambient_until = random.choice(pool), now + random.uniform(12, 20)
            if self.ambient == "cold":
                self.jiggle("shake")
            # 有时先插一个“做一次”的小动作（舔爪、打哈欠、伸懒腰、挠耳朵），做完回到平常状态
            once = [x for x in PET_EXTRA_ONCE if x in self.frames]
            if once and random.random() < .45:
                x = random.choices(once, weights=[PET_ONCE_WEIGHT.get(o, 1) for o in once])[0]
                secs = len(self.frames[x]) * self.frame_ms() / 1000 * 2
                self.play(x, secs)
                self.ambient_until += secs
                return x
        return self.ambient

    def watch_cursor(self, now):
        """鼠标靠近：转头盯着鼠标那边；很近时偶尔伸爪拍过去。没有这组素材就不做。"""
        if not ("watchl" in self.frames or "watchr" in self.frames) or self.win is None:
            return None
        try:
            mx, my = self.app.root.winfo_pointerxy()
        except tk.TclError:
            return None
        z = self.zoom()
        cx = self.win.winfo_rootx() + PET_SIZE * z / 2
        cy = self.win.winfo_rooty() + (PET_TOP + 32) * z
        dx, dy = mx - cx, my - cy
        dist = (dx * dx + dy * dy) ** .5
        inside = abs(dx) < 22 * z and abs(dy) < 26 * z  # 鼠标在猫身上：交给摸摸 / 点击处理
        if inside or dist > 90 * z or abs(dx) < 10 * z:
            return None
        side = "l" if dx < 0 else "r"
        if dist < 45 * z and now - getattr(self, "swat_at", 0) > 6 and random.random() < .15:
            self.swat_at = now
            self.play("swat" + side, 1, "watch" + side, 1)
            return "swat" + side
        return "watch" + side

    def frame_ms(self):
        return int(self.manifest.get("frame_duration_ms", PET_FPS_MS))

    def play(self, *seq):
        """插播一串动作：play("eat", 3, "happy", 2)。"""
        import time
        t, self.transient = time.time(), []
        for st, secs in zip(seq[::2], seq[1::2]):
            t += secs
            self.transient.append((st, t))
        self.idx = 0

    def resolve(self, st):
        """素材里没有这个动作：按 PET_FALLBACK 找替身，最后用 idle。"""
        seen = set()
        while st not in self.frames and st not in seen:
            seen.add(st)
            st = PET_FALLBACK.get(st, "idle")
        return st if st in self.frames else "idle"

    def animate(self):
        if self.win is not None and self.frames:
            st = self.resolve(self.pick_state())
            if st != self.state:
                self.state, self.idx = st, 0
            fr = self.frames[st]
            self.cv.itemconfigure(self.img_id, image=fr[self.idx % len(fr)])
            self.idx += 1
        self.app.root.after(self.frame_ms(), self.animate)

    # ----- 互动 -----
    def sulking(self):
        import time
        return time.time() < self.data.get("sulk_until", 0)

    def on_press(self, e):
        self._press = (e.x_root, e.y_root)
        self.dragging = False
        self.app.drag_start(e)

    def on_drag(self, e):
        """拖着猫：悬浮窗跟着走，猫换成被拎起的样子。"""
        self.app.drag_move(e)
        px, py = getattr(self, "_press", (e.x_root, e.y_root))
        if not self.dragging and (abs(e.x_root - px) > 4 or abs(e.y_root - py) > 4):
            self.dragging = True
            self.play("carried", 3600)

    def on_release(self, e):
        import time
        if getattr(self, "skip_release", False):  # 双击的第二下松开，不再当单击
            self.skip_release = False
            return
        if self.dragging:                          # 松手：落地，弹一下
            self.dragging = False
            self.app.drag_end(e)
            self.play("land", .6, "happy", 1.2)
            self.jiggle()
            return
        now = time.time()
        self.clicks = [t for t in getattr(self, "clicks", []) if now - t < 6] + [now]
        recent = sum(1 for t in self.clicks if now - t < 3)
        if self.state in PET_SLEEP_POSES + ["twitch"]:  # 睡着被戳：吓一跳
            self.play("scared", 1, "annoyed", 1.5)
            self.fx("exclaim")
            self.jiggle("shake")
            self.data["mood"] = max(0.0, self.data["mood"] - 1)
            return
        if self.sulking():                         # 还在生气：不理你
            self.play("annoyed", 1.5)
            self.fx("anger")
            return
        if len(self.clicks) >= 7:                  # 戳太多：生气，一分钟内不理你
            self.data["mood"] = max(0.0, self.data["mood"] - 5)
            self.data["sulk_until"] = now + 60
            self.clicks = []
            self.play("angry", 3, "annoyed", 3)
            self.fx("anger")
            self.jiggle("shake")
            self.app.flash(f"{self.manifest.get('name') or '小猫'}生气了，一分钟内不理你")
            return
        if recent >= 4:                            # 戳得有点多：不耐烦
            self.play("annoyed", 2)
            self.fx("sweat")
            return
        self.data["mood"] = min(100.0, self.data["mood"] + 1)
        self.play("click", .7, "happy", 1.5)
        self.jiggle()
        self.fx(random.choice(["exclaim", "question", "heart"]))

    def on_double(self, _e):
        """双击：打滚或出猫猫拳。"""
        self.skip_release = True
        if self.sulking():
            self.fx("anger")
            return "break"
        if random.random() < .5:
            self.play("roll", 2, "happy", 1.5)
        else:
            self.play("punch", 1.2, "happy", 1.5)
            self.jiggle()
        return "break"

    def on_hover(self, e):
        """鼠标在猫身上来回划 = 摸摸：眯眼享受，摸久了翻肚皮，偶尔“偷袭”你一拳。"""
        import time
        now = time.time()
        pts = [(t, x) for t, x in getattr(self, "stroke", []) if now - t < 1.2] + [(now, e.x)]
        self.stroke = pts
        xs = [x for _, x in pts]
        turns = sum(1 for a, b, c in zip(xs, xs[1:], xs[2:]) if (b - a) * (c - b) < 0)
        travel = sum(abs(b - a) for a, b in zip(xs, xs[1:]))
        if turns < 2 or travel < 25 * self.zoom() or now - getattr(self, "pet_at", 0) < .8:
            return
        if self.sulking() or self.dragging:
            return
        first = now - getattr(self, "pet_at", 0) > 2.5
        self.pet_time = 0 if first else getattr(self, "pet_time", 0) + (now - self.pet_at)
        self.pet_at = now
        self.data["mood"] = min(100.0, self.data["mood"] + .5)
        if now - self.data.get("love_pet_at", 0) > 30:  # 摸摸加亲密度，30 秒最多一次
            self.data["love_pet_at"] = now
            self.data["love"] += 1
        if self.pet_time > 5 and random.random() < .5:
            if random.random() < .35:
                self.play("belly", 2, "punch", 1.2, "happy", 1.5)  # 翻肚皮的陷阱
            else:
                self.play("belly", 3, "happy", 1.5)
            self.pet_time = 0
        else:
            self.play("pet", 1.6, "happy", 1.2)
        if random.random() < .5:
            self.fx("heart")

    def react_fortune(self, level):
        """抽完签的反应。"""
        if level in ("大吉", "中吉"):
            self.play("excited", 3, "happy", 2)
            self.fx("heart")
            self.jiggle()
        elif level in ("凶", "末吉"):
            self.play("sad", 3, "idle", .5)
            self.fx("sweat")
        else:
            self.play("happy", 2)

    def feed(self, key):
        food = next(f for f in PET_FOODS if f[0] == key)
        inv = self.data["inv"]
        if inv.get(key, 0) <= 0:
            return
        inv[key] -= 1
        self.data["full"] = min(100.0, self.data["full"] + food[3])
        self.data["mood"] = min(100.0, self.data["mood"] + food[4])
        self.data["love"] += 1
        if "drink" in self.frames:
            self.play("eat", 3, "full", 1.5, "drink", 1.5, "happy", 2)
        else:
            self.play("eat", 3, "full", 1.5, "happy", 2)
        self.fx("heart")
        self.save()

    def wand_left(self):
        import time
        return max(0, int(self.data.get("wand_at", 0) + PET_WAND_COOLDOWN - time.time()))

    def wand(self):
        import time
        if self.wand_left():
            return
        self.data["wand_at"] = time.time()
        self.data["mood"] = min(100.0, self.data["mood"] + PET_WAND_MOOD)
        self.data["love"] += 1
        self.play("play", 4, "happy", 2)
        self.fx("note")
        self.save()

    # ----- 喂养面板 -----
    def open_panel(self):
        if self.panel is not None and self.panel.winfo_exists():
            self.panel.lift()
            return
        app, p = self.app, self.app.p
        win = tk.Toplevel(app.root, bg=p["ground"])
        self.panel = win
        win.title(self.manifest.get("name") or "我的小猫")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win_dark_titlebar(win, app.dark)
        self.panel_body = tk.Frame(win, padx=18, pady=14, bg=p["ground"])
        self.panel_body.pack(fill="both")
        self.draw_panel()
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        x = app.root.winfo_x() - win.winfo_reqwidth() - 12
        if x < 0:
            x = app.root.winfo_x() + app.root.winfo_width() + 12
        win.geometry(f"+{x}+{max(0, app.root.winfo_y() - 40)}")
        self.app.root.after(30000, self.panel_tick)

    def panel_tick(self):
        """面板开着时每 30 秒刷新一次（逗猫棒倒计时、数值衰减）。"""
        if self.panel is not None and self.panel.winfo_exists():
            self.draw_panel()
            self.app.root.after(30000, self.panel_tick)

    def draw_panel(self):
        p, d = self.app.p, self.data
        body = self.panel_body
        for w in body.winfo_children():
            w.destroy()
        S, G = dict(bg=p["surface"]), dict(bg=p["ground"])
        name = self.manifest.get("name") or "我的小猫"
        tk.Label(body, text=f"{name} · 亲密度 Lv.{d['love'] // 10 + 1}", fg=p["text3"],
                 font=(FONT, 9), **G).pack(anchor="w", padx=4, pady=(0, 6))

        card = tk.Frame(body, padx=16, pady=10, highlightthickness=1,
                        highlightbackground=p["border"], **S)
        card.pack(fill="x")
        bw = int(150 * self.app.ui_scale())
        for key, label, color in (("full", "饱腹", p["gold"]), ("mood", "心情", p["bar"])):
            row = tk.Frame(card, pady=4, **S)
            row.pack(fill="x")
            tk.Label(row, text=label, fg=p["text3"], font=(FONT, 9), **S).pack(side="left")
            tk.Label(row, text=f"{d[key]:.0f}", fg=p["text"], font=(NUM_FONT, 10, "bold"),
                     width=3, anchor="e", **S).pack(side="left", padx=(4, 10))
            bar = tk.Canvas(row, width=bw, height=6, highlightthickness=0, **S)
            bar.pack(side="left")
            bar.create_line(3, 3, bw - 3, 3, width=6, capstyle="round", fill=p["track"])
            if d[key] > 0:
                bar.create_line(3, 3, 3 + (bw - 6) * d[key] / 100, 3, width=6,
                                capstyle="round", fill=color)

        items = tk.Frame(body, padx=16, pady=4, highlightthickness=1,
                         highlightbackground=p["border"], **S)
        items.pack(fill="x", pady=(10, 0))
        rows = [(key, name, f"× {d['inv'].get(key, 0)}", d["inv"].get(key, 0) > 0, "喂",
                 lambda k=key: (self.feed(k), self.draw_panel())) for key, name, *_ in PET_FOODS]
        left = self.wand_left()
        rows.append(("wand", "逗猫棒", f"{left // 60 + 1} 分钟后能玩" if left else "可以玩",
                     not left, "玩", lambda: (self.wand(), self.draw_panel())))
        for i, (key, name, count, ok, verb, cmd) in enumerate(rows):
            if i:
                tk.Frame(items, height=1, bg=p["hairline"]).pack(fill="x")
            row = tk.Frame(items, pady=6, **S)
            row.pack(fill="x")
            if key in self.icons:
                tk.Label(row, image=self.icons[key], **S).pack(side="left", padx=(0, 8))
            tk.Label(row, text=name, fg=p["text"], font=(FONT, 10), **S).pack(side="left")
            tk.Label(row, text=count, fg=p["text3"], font=(FONT, 9), **S).pack(side="left", padx=8)
            if ok:
                PillButton(row, verb, p["accent"], p["on_accent"], cmd, p["surface"],
                           (FONT, 9)).pack(side="right")
            else:
                PillButton(row, verb, p["track"], p["text3"], lambda: None, p["surface"],
                           (FONT, 9)).pack(side="right")

        body.update_idletasks()
        nb = " "  # 不折行的空格：Tk 遇到普通空格就会在那儿折行
        tk.Label(body, text=f"上班每{nb}30{nb}分钟得{nb}1{nb}个零食，每{nb}2{nb}小时得{nb}1{nb}个冻干，"
                            f"上满一天得{nb}1{nb}个罐头。饱腹和心情会慢慢下降。",
                 fg=p["text3"], font=(FONT, 8), justify="left",
                 wraplength=max(200, items.winfo_reqwidth() - 8), **G).pack(anchor="w", padx=4,
                                                                             pady=(8, 0))


# ---------- 界面 ----------
THEMES = [("auto", "跟随系统"), ("light", "浅色"), ("dark", "深色")]


def win_hwnd(win):
    win.update_idletasks()
    return ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()


def win_dark_titlebar(win, dark):
    """Windows 10/11：标题栏跟着深浅色走（设置窗口用）。"""
    if IS_MAC:
        return
    try:
        v = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(win_hwnd(win), 20, ctypes.byref(v), 4)
    except Exception:
        pass


def sun_icon(parent, up, color, bg, scale=1.0):
    """Lucide 日出 / 日落：24×24 网格等比缩放为 18px，单色圆头线条。"""
    # Lucide sunrise / sunset — https://lucide.dev — ISC License, © Lucide Icons and Contributors.
    import math
    k = 18 / 24 * scale
    cv = tk.Canvas(parent, width=round(24 * k), height=round(24 * k),
                   bg=bg, highlightthickness=0, borderwidth=0)

    def line(*coords):
        cv.create_line(*(v * k for v in coords), fill=color, width=2 * k,
                       capstyle="round", joinstyle="round")

    line(12, 2, 12, 10)
    line(4.93, 10.93, 6.34, 12.34)
    line(2, 18, 4, 18)
    line(20, 18, 22, 18)
    line(19.07, 10.93, 17.66, 12.34)
    line(22, 22, 2, 22)
    line(8, 6, 12, 2 if up else 10, 16, 6)
    # SVG M16 18a4 4 0 0 0-8 0；采样半圆以沿用线条的圆头（Tk arc 无 capstyle）。
    arc = []
    for i in range(25):
        a = math.pi * i / 24
        arc.extend((12 + 4 * math.cos(a), 18 - 4 * math.sin(a)))
    line(*arc)
    return cv


def paw_icon(parent, bg, scale=1.0):
    """猫爪小图标（16 格网格缩放到约 14px）：一个肉垫加四个脚趾，颜色用 itemconfigure 改 tag "paw"。"""
    k = 14 / 16 * scale
    cv = tk.Canvas(parent, width=round(16 * k), height=round(16 * k),
                   bg=bg, highlightthickness=0, borderwidth=0, cursor="hand2")
    for x, y, r in ((2.6, 7.2, 1.7), (5.9, 3.6, 1.8), (10.1, 3.6, 1.8), (13.4, 7.2, 1.7)):
        cv.create_oval((x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k, outline="", tags="paw")
    cv.create_oval(4.4 * k, 7.6 * k, 11.6 * k, 14.4 * k, outline="", tags="paw")
    return cv


def has_cjk(s):
    return any("一" <= ch <= "鿿" for ch in s)


class PillButton(tk.Canvas):
    """圆角胶囊按钮（Tk 原生按钮做不出圆角）。"""

    def __init__(self, parent, text, bg, fg, command, ground, font):
        import tkinter.font as tkfont
        f = tkfont.Font(family=font[0], size=font[1], weight="bold")
        w, h = f.measure(text) + 36, f.metrics("linespace") + 14
        super().__init__(parent, width=w, height=h, bg=ground,
                         highlightthickness=0, cursor="hand2")
        self.bg, self.command = bg, command
        r = h / 2
        pts = [r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h, w - r, h, r, h, 0, h, 0, h - r, 0, r, 0, 0]
        self.shape = self.create_polygon(pts, smooth=True, fill=bg, outline="")
        self.create_text(w / 2, h / 2, text=text, fill=fg, font=f, tags=("text",))
        self.bind("<ButtonPress-1>", lambda _e: self.itemconfigure(self.shape, fill=self._dim()))
        self.bind("<ButtonRelease-1>", self._release)

    def _dim(self):  # 按下时颜色压暗一点，给即时反馈
        r, g, b = (int(self.bg[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % (int(r * .88), int(g * .88), int(b * .88))

    def _release(self, e):
        self.itemconfigure(self.shape, fill=self.bg)
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()


class TarotScrollbar(tk.Canvas):
    """牌桌专用细滚动条，自己绘制以避开 Windows 原生白色底槽。"""

    def __init__(self, parent, palette, scale, command):
        self.p, self.s, self.command = palette, scale, command
        self.first, self.last, self.drag_offset = 0.0, 1.0, None
        super().__init__(parent, width=max(8, round(10 * scale)),
                         bg=palette["ground"], highlightthickness=0, bd=0)
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Button-1>", self.press)
        self.bind("<B1-Motion>", self.drag)
        self.bind("<ButtonRelease-1>", self.release)

    def bounds(self):
        h = self.winfo_height()
        thumb = min(h, max(round(24 * self.s), h * (self.last - self.first)))
        travel = max(0, h - thumb)
        top = travel * self.first / max(1e-9, 1 - (self.last - self.first))
        return top, thumb, travel

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.draw()

    def draw(self):
        self.delete("all")
        if self.last - self.first >= 1:
            return
        top, thumb, _ = self.bounds()
        x = self.winfo_width() / 2
        width = max(3, round(4 * self.s))
        self.create_line(x, top + width / 2, x, top + thumb - width / 2,
                         width=width, capstyle="round",
                         fill=self.p["text2" if self.drag_offset is not None else "text3"])

    def press(self, event):
        top, thumb, _ = self.bounds()
        if top <= event.y <= top + thumb:
            self.drag_offset = event.y - top
            self.draw()
        else:
            self.command("scroll", -1 if event.y < top else 1, "pages")

    def drag(self, event):
        if self.drag_offset is not None:
            _, _, travel = self.bounds()
            fraction = max(0, min(1, (event.y - self.drag_offset) / max(1, travel)))
            self.command("moveto", fraction * (1 - (self.last - self.first)))

    def release(self, _event):
        self.drag_offset = None
        self.draw()


class TarotTable:
    """一张持续存在的牌桌：提问、洗牌、选择、翻牌和复制提示词。"""

    def __init__(self, app):
        self.app, self.p = app, app.p
        self.jobs, self.images, self.pixels = set(), {}, {}
        self.closed, self.state = False, "loading"
        self.selected, self.revealed, self.hover = [], set(), None
        self.question, self.deck = "", []
        self.mode, self.daily_day = None, None
        self.win = win = tk.Toplevel(app.root, bg=self.p["ground"])
        win.title("塔罗牌 · 选择模式")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda _e: self.close())
        win.bind("<Destroy>", self.destroyed, add="+")
        win.bind("<Return>", self.enter)
        win_dark_titlebar(win, app.dark)
        self.s = app.ui_scale()
        self.width = min(round(820 * self.s),
                         int(win.winfo_screenwidth() * .9) - self.px(24))
        self.w = self.width / self.s - 44
        # 小屏幕只滚动内容，不把窗口推到屏幕外；滚轮绑定只属于这一个窗口。
        self.viewport = tk.Canvas(win, bg=self.p["ground"], highlightthickness=0,
                                  width=self.width, height=round(690 * self.s))
        self.scroll = TarotScrollbar(win, self.p, self.s, self.viewport.yview)
        self.viewport.configure(yscrollcommand=self.scroll.set)
        self.viewport.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.viewport, bg=self.p["ground"],
                             padx=self.px(22), pady=self.px(18))
        self.viewport.create_window(0, 0, anchor="nw", window=self.body, width=self.width)
        self.body.bind("<Configure>", lambda _e: self.viewport.configure(
            scrollregion=self.viewport.bbox("all")))
        win.bind("<MouseWheel>", self.wheel)
        win.bind("<Button-4>", lambda _e: self.viewport.yview_scroll(-2, "units"))
        win.bind("<Button-5>", lambda _e: self.viewport.yview_scroll(2, "units"))
        self.eyebrow = self.label(self.body, "韦特塔罗", 9, "text3")
        self.eyebrow.pack(anchor="w")
        self.title = self.label(self.body, "留一点时间，给今天的自己", 20, "text", True)
        self.title.pack(anchor="w", pady=(self.px(5), self.px(4)))
        self.hint = self.label(self.body, "准备牌面后，选择今日运势或问一个问题。", 10, "text2")
        self.hint.pack(anchor="w", pady=(0, self.px(14)))
        # 第二排两端的牌底约为 446，留出描边、取整和边界的余量。
        self.cv = tk.Canvas(self.body, width=self.px(self.w), height=self.px(456),
                            bg=self.p["surface"], highlightthickness=1,
                            highlightbackground=self.p["border"], highlightcolor=self.p["border"], bd=0)
        self.cv.pack(fill="x")
        self.cv.bind("<Motion>", self.motion)
        self.cv.bind("<Leave>", lambda _e: self.set_hover(None))
        self.cv.bind("<Button-1>", self.click)
        self.controls = tk.Frame(self.body, bg=self.p["ground"])
        self.controls.pack(fill="x", pady=(self.px(14), 0))
        # 支持键盘选牌：左右移动焦点，空格选牌；焦点牌与悬停牌共享高亮。
        self.cv.configure(takefocus=True)
        self.cv.bind("<Left>", lambda _e: self.keyboard(-1))
        self.cv.bind("<Right>", lambda _e: self.keyboard(1))
        self.cv.bind("<space>", self.keyboard_pick)
        self.cv.bind("<Up>", lambda _e: self.keyboard(-1))
        self.cv.bind("<Down>", lambda _e: self.keyboard(1))
        self.cv.bind("<Tab>", self.mode_tab)
        self.cv.bind("<Shift-Tab>", self.mode_tab)
        self.cv.bind("<FocusIn>", lambda _e: self.draw_modes() if self.state == "mode" else None)
        self.poll()
        win.update_idletasks()
        self.fit()

    def px(self, n):
        return max(1, round(n * self.s))

    def label(self, parent, text, size=10, color="text", bold=False):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=self.p[color],
                        font=(FONT, size, "bold" if bold else "normal"),
                        anchor="w", justify="left", wraplength=self.px(self.w - 8))

    def button(self, text, command, primary=True):
        button = PillButton(self.controls, text,
                          self.p["accent" if primary else "track"],
                          self.p["on_accent" if primary else "text"], command,
                          self.p["ground"], (FONT, 10))
        button.configure(takefocus=True)
        button.bind("<Return>", lambda _e: (command(), "break")[1])
        button.bind("<space>", lambda _e: (command(), "break")[1])
        button.bind("<FocusIn>", lambda _e: button.itemconfigure(
            button.shape, outline=self.p["text2"], width=self.px(2)))
        button.bind("<FocusOut>", lambda _e: button.itemconfigure(button.shape, outline=""))
        return button

    def later(self, ms, callback):
        """每个回调都有登记；关窗、重开牌局时统一取消。"""
        if self.closed:
            return
        job = None

        def run():
            self.jobs.discard(job)
            if not self.closed:
                callback()
        job = self.win.after(ms, run)
        self.jobs.add(job)

    def cancel_jobs(self):
        for job in self.jobs:
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass
        self.jobs.clear()

    def destroyed(self, event):
        if event.widget == self.win:
            self.closed = True
            self.cancel_jobs()
            self.clear_topic_trace()
            self.images.clear()
            self.pixels.clear()
            if getattr(self.app, "tarot_win", None) is self.win:
                self.app.tarot_win = None

    def close(self):
        if not self.closed:
            self.closed = True
            self.cancel_jobs()
            self.clear_topic_trace()
            self.win.destroy()

    def wheel(self, event):
        self.viewport.yview_scroll((-1 if event.delta > 0 else 1) *
                                  (2 if abs(event.delta) >= 120 else 1), "units")

    def fit(self):
        # 主题页不需要牌桌；恢复时显式放在 controls 前，避免 pack 顺序颠倒。
        if self.state == "topic":
            self.cv.pack_forget()
        else:
            self.cv.pack(fill="x", before=self.controls)
        self.win.update_idletasks()
        h = min(self.body.winfo_reqheight(), int(self.win.winfo_screenheight() * .84))
        overflow = self.body.winfo_reqheight() > h
        if overflow:
            self.scroll.pack(side="right", fill="y")
        else:
            self.scroll.pack_forget()
        width = self.width + (self.scroll.winfo_reqwidth() if overflow else 0)
        x = self.app.root.winfo_x() - width - self.px(12)
        if x < 0:
            x = self.app.root.winfo_x() + self.app.root.winfo_width() + self.px(12)
        x = max(0, min(x, self.win.winfo_screenwidth() - width))
        y = max(0, min(self.app.root.winfo_y(), self.win.winfo_screenheight() - h - self.px(48)))
        self.win.geometry(f"{width}x{h}+{x}+{y}")

    def clear_topic_trace(self):
        if hasattr(self, "topic_trace"):
            self.topic_var.trace_remove("write", self.topic_trace)
            del self.topic_trace

    def clear_controls(self):
        self.clear_topic_trace()
        for child in self.controls.winfo_children():
            child.destroy()

    def text(self, x, y, text, size=10, color="text2", bold=False, **kw):
        return self.cv.create_text(x * self.s, y * self.s, text=text,
                                   fill=self.p[color],
                                   font=(FONT, size, "bold" if bold else "normal"), **kw)

    def image(self, key, width, rev=False, height=None):
        """缓存图片。整数缩小用 Tk；任意尺寸用标准库生成 PPM，无第三方依赖。"""
        w = self.px(width)
        h = self.px(height if height is not None else width * 260 / 150)
        cache = (key, rev, w, h)
        if cache in self.images:
            return self.images[cache]
        source_key = (key, rev)
        if source_key not in self.pixels:
            src = tk.PhotoImage(master=self.win, file=tarot_path(key))
            if rev:
                # Tk 8.6 photo 手册明确支持负数 subsample，两个轴同时反转即旋转 180°。
                src = src.subsample(-1, -1)
            rows = src.tk.splitlist(src.tk.call(src, "data", "-background", self.p["surface"]))
            rgb = [bytes.fromhex("".join(c[1:] for c in src.tk.splitlist(row))) for row in rows]
            self.pixels[source_key] = (src.width(), src.height(), rgb)
        sw, sh, rows = self.pixels[source_key]
        xs = [min(sw - 1, x * sw // w) * 3 for x in range(w)]
        scaled = {}
        for sy in set(y * sh // h for y in range(h)):
            row = rows[sy]
            scaled[sy] = b"".join(row[x:x + 3] for x in xs)
        data = f"P6\n{w} {h}\n255\n".encode("ascii") + b"".join(
            scaled[y * sh // h] for y in range(h))
        img = tk.PhotoImage(master=self.win, data=data, format="PPM")
        self.images[cache] = img
        return img

    def card(self, x, y, width, key=TAROT_BACK, rev=False, tags=(), height=None):
        img = self.image(key, width, rev, height)
        return self.cv.create_image(x * self.s, y * self.s, image=img, tags=tags)

    def poll(self):
        if tarot_ready():
            try:
                self.reset()
            except (tk.TclError, OSError, ValueError) as ex:
                self.error(f"牌面无法读取：{ex}")
            return
        if TAROT_DL["error"] and not TAROT_DL["busy"]:
            self.error(TAROT_DL["error"])
            return
        n = 79 - len(tarot_missing())
        self.cv.delete("all")
        self.text(self.w / 2, 196, f"正在准备牌面 {n}/79", 16, "text", True)
        self.text(self.w / 2, 230, "第一次需要下载，准备好后会自动进入牌桌。", 10)
        self.cv.create_line(60 * self.s, 270 * self.s, (self.w - 60) * self.s,
                            270 * self.s, fill=self.p["track"], width=self.px(3))
        if n:
            self.cv.create_line(60 * self.s, 270 * self.s,
                                (60 + (self.w - 120) * n / 79) * self.s, 270 * self.s,
                                fill=self.p["accent"], width=self.px(3))
        self.later(180, self.poll)

    def error(self, message):
        self.cancel_jobs()
        self.state = "error"
        self.cv.configure(height=self.px(456), cursor="arrow")
        self.cv.delete("all")
        self.text(self.w / 2, 180, "牌面还没有准备好", 17, "text", True)
        self.text(self.w / 2, 230, message, 10, "danger", width=self.px(self.w - 60))
        self.clear_controls()
        self.button("重试", self.retry).pack(side="right")
        self.fit()

    def retry(self):
        self.cancel_jobs()
        self.clear_controls()
        self.state = "loading"
        self.images.clear()
        self.pixels.clear()
        tarot_start_download()
        self.poll()

    def reset(self):
        """返回模式选择，取消上一局所有动画和复制反馈。"""
        self.cancel_jobs()
        self.state, self.selected, self.revealed, self.hover = "mode", [], set(), None
        self.mode, self.daily_day = None, None
        self.deck, self.question = [], ""
        # 删除上一局的图像缓存，防止反复抽牌积累翻牌帧。
        self.images.clear()
        self.pixels.clear()
        self.cv.configure(height=self.px(368), cursor="hand2", takefocus=True)
        self.win.title("塔罗牌 · 选择模式")
        self.eyebrow.configure(text="韦特塔罗 · 选择模式")
        self.title.configure(text="今天，想从哪一张牌开始？")
        self.hint.configure(text="每天一张今日牌，或带着一个问题，看看过去、现在与未来。")
        self.clear_controls()
        self.mode_index, self.mode_hover = 0, None
        self.draw_modes()
        self.label(self.controls, "Tab / 方向键切换 · 回车 / 空格进入", 9, "text3").pack(anchor="w")
        self.cv.focus_set()
        self.viewport.yview_moveto(0)
        self.fit()

    def mode_tab(self, _event):
        if self.state == "mode":
            return self.keyboard(1)

    def mode_hit(self, x, y):
        if 24 <= x <= self.w - 24:
            for i in range(2):
                if 24 + i * 168 <= y <= 176 + i * 168:
                    return i
        return None

    def draw_modes(self):
        if self.state != "mode":
            return
        self.cv.delete("all")
        today = tarot_daily_get(self.app.conf, dt.date.today())
        detail = (f"今天：{tarot_name(today[0])[0]} · {'逆位' if today[1] else '正位'}"
                  if today else "每天一次，亲手选出属于今天的一张牌。")
        if today:
            detail += "\n主题：" + tarot_topic_get(self.app.conf)[0]
        # 两张选项上下居中；缩略图与文字共享一张卡片，保留足够的换行空间。
        for i, (title, subtitle) in enumerate((
                ("今日运势", "一张今日牌\n" + detail),
                ("问一个问题", "过去 / 现在 / 未来\n写下心里的问题，亲手选出三张牌。"))):
            y = 24 + i * 168
            active = i == self.mode_index or i == self.mode_hover
            self.cv.create_rectangle(24 * self.s, y * self.s,
                                     (self.w - 24) * self.s, (y + 152) * self.s,
                                     fill=self.p["input" if i == self.mode_hover else "surface"],
                                     outline=self.p["accent" if active else "border"],
                                     width=self.px(2 if active else 1))
            if i == 0:
                self.card(92, y + 76, 64, today[0] if today else TAROT_BACK,
                          today[1] if today else False)
            else:
                # 轻微弧形错位，让三张牌背都露出边缘。
                for dx, dy in ((-16, 5), (16, 5), (0, -3)):
                    self.card(92 + dx, y + 76 + dy, 58)
            self.text(164, y + 30, title, 15, "text", True,
                      anchor="nw", width=self.px(self.w - 212))
            self.text(164, y + 72, subtitle, 10, anchor="nw",
                      width=self.px(self.w - 212))


    @property
    def positions(self):
        return ("今日",) if self.mode == "daily" else TAROT_POSITIONS

    def choose_mode(self, mode):
        if self.closed or self.state != "mode" or mode not in ("daily", "question"):
            return
        self.cancel_jobs()
        self.mode = mode
        self.cv.configure(cursor="arrow")
        self.eyebrow.configure(text="韦特塔罗 · " + ("今日运势" if mode == "daily" else "三张牌阵"))
        self.win.title("塔罗牌 · " + ("今日运势" if mode == "daily" else "过去 / 现在 / 未来"))
        try:
            if mode == "question":
                self.question_screen()
            else:
                day = dt.date.today()
                saved = tarot_daily_get(self.app.conf, day)
                if saved:
                    self.daily_result(day, saved)
                else:
                    self.topic_screen()
        except (tk.TclError, OSError, ValueError) as ex:
            self.error(f"牌面无法读取：{ex}")

    def daily_result(self, day, saved):
        self.cancel_jobs()
        self.daily_day = day
        self.deck, self.selected, self.revealed, self.hover = [saved], [0], {0}, None
        self.image(saved[0], min(108, self.w / 4 - 22), saved[1])
        self.result()

    def topic_screen(self):
        """今日未抽牌时先选主题，开始洗牌才保存。"""
        self.cancel_jobs()
        self.state = "topic"
        self.title.configure(text="今天，想关注哪一面？")
        self.hint.configure(text="选一个主题，或写下今天想问的问题。今日牌每天固定，主题随时能换。")
        self.cv.delete("all")
        self.cv.pack_forget()
        self.cv.configure(takefocus=False)
        self.clear_controls()
        self.topic_controls()
        self.start_btn = self.button("开始洗牌", self.start_daily)
        self.start_btn.pack(side="right", pady=(self.px(12), 0))
        self.button("返回", self.reset, False).pack(side="right", padx=self.px(10),
                                                  pady=(self.px(12), 0))
        self.topic_feedback()
        self.topic_buttons[self.topic_names.index(self.topic)].focus_set()
        self.viewport.yview_moveto(0)
        self.fit()

    def topic_controls(self):
        """选主题页和结果页共用；胶囊按窗口宽度和缩放绘制。"""
        self.topic, question = tarot_topic_get(self.app.conf)
        self.topic_names = [name for name, _ in TAROT_TOPICS] + [TAROT_CUSTOM]
        panel = tk.Frame(self.controls, bg=self.p["ground"])
        panel.pack(fill="x", pady=(0, self.px(10)))
        self.label(panel, "今日主题", 10, "text", True).pack(anchor="w")
        grid = tk.Frame(panel, bg=self.p["ground"])
        grid.pack(fill="x", pady=(self.px(6), 0))
        self.topic_buttons = []
        self.topic_keyboard = False
        for i, name in enumerate(self.topic_names):
            grid.columnconfigure(i % 5, weight=1, uniform="topic")
            button = tk.Canvas(grid, width=self.px(self.w / 5 - 8), height=self.px(32),
                               bg=self.p["ground"], highlightthickness=0,
                               takefocus=True, cursor="hand2")
            button.grid(row=i // 5, column=i % 5, sticky="ew", padx=self.px(3), pady=self.px(3))
            button.bind("<Configure>", lambda _e: self.topic_feedback())
            button.bind("<Button-1>", lambda _e, n=name: self.topic_click(n))
            for key in ("<Tab>", "<Shift-Tab>", "<ISO_Left_Tab>"):
                button.bind(key, self.topic_tab)
            for key in ("<space>", "<Return>"):
                button.bind(key, lambda _e, n=name: (self.select_topic(n), "break")[1])
            for key, step in (("<Left>", -1), ("<Right>", 1), ("<Up>", -5), ("<Down>", 5)):
                button.bind(key, lambda _e, j=i, d=step: self.topic_focus(j + d))
            button.bind("<FocusIn>", lambda _e: self.topic_feedback())
            button.bind("<FocusOut>", lambda _e: self.topic_feedback())
            self.topic_buttons.append(button)
        self.topic_input = tk.Frame(panel, bg=self.p["ground"])
        self.label(self.topic_input, f"今天想问什么？（最多 {TAROT_QUESTION_MAX} 个字）", 9, "text3").pack(anchor="w")
        self.topic_var = tk.StringVar(master=self.win, value=question)
        # 边框包住留白，Entry 本身无边框；两个页面共用同样的内边距。
        entry_box = tk.Frame(self.topic_input, bg=self.p["surface"],
                             padx=self.px(10), pady=self.px(7), highlightthickness=1,
                             highlightbackground=self.p["border"])
        entry_box.pack(fill="x", pady=(self.px(4), 0))
        self.topic_entry = tk.Entry(entry_box, textvariable=self.topic_var, font=(FONT, 11),
                                    bg=self.p["surface"], fg=self.p["text"],
                                    insertbackground=self.p["text"], relief="flat", bd=0,
                                    highlightthickness=0)
        self.topic_entry.pack(fill="x")
        self.topic_entry.bind("<FocusIn>", lambda _e: entry_box.configure(
            highlightbackground=self.p["accent"]))
        self.topic_entry.bind("<FocusOut>", lambda _e: entry_box.configure(
            highlightbackground=self.p["border"]))
        self.topic_entry.bind("<Return>", self.topic_enter)
        self.topic_trace = self.topic_var.trace_add("write", self.topic_changed)
        self.topic_feedback()

    def topic_click(self, topic):
        self.topic_keyboard = False
        self.select_topic(topic)
        return "break"

    def topic_tab(self, _event=None):
        # 保留 Tk 原生 Tab 顺序，焦点变化时重绘轻量的键盘提示。
        self.topic_keyboard = True
        self.topic_feedback()

    def topic_focus(self, index):
        self.topic_keyboard = True
        self.topic_buttons[index % len(self.topic_buttons)].focus_set()
        self.topic_feedback()
        return "break"

    def topic_enter(self, _event=None):
        if self.state == "topic":
            self.start_daily()
        return "break"

    def select_topic(self, topic, question=None):
        """点击和测试钩子共用；结果页立即保存并刷新提示词。"""
        if self.closed or self.mode != "daily" or self.state not in ("topic", "result"):
            return
        if topic not in self.topic_names:
            return
        self.topic = topic
        self.topic_buttons[self.topic_names.index(topic)].focus_set()
        if topic == TAROT_CUSTOM and question is not None:
            self.topic_var.set(str(question)[:TAROT_QUESTION_MAX])
        else:
            self.topic_changed()

    def topic_changed(self, *_):
        if self.closed or self.state not in ("topic", "result") or self.mode != "daily":
            return
        question = self.topic_var.get()
        if len(question) > TAROT_QUESTION_MAX:
            self.topic_var.set(question[:TAROT_QUESTION_MAX])
        self.topic_feedback()
        if self.state == "result":
            tarot_topic_set(self.app.conf, self.topic, self.topic_var.get())
            self.update_daily_prompt()
        self.fit()

    def topic_feedback(self):
        if self.closed or not hasattr(self, "topic_trace"):
            return
        focused = self.win.focus_get()
        for name, button in zip(self.topic_names, self.topic_buttons):
            active = name == self.topic
            bg = self.p["accent" if active else "track"]
            fg = self.p["on_accent" if active else "text"]
            w, h, r = button.winfo_width(), self.px(32), self.px(16)
            button.delete("all")
            button.create_polygon(r, 1, w-r, 1, w-1, 1, w-1, r, w-1, h-1,
                                  w-r, h-1, r, h-1, 1, h-1, 1, r, 1, 1,
                                  smooth=True, fill=bg,
                                  outline="")
            # 仅键盘导航显示淡虚线；选中胶囊始终只有 accent 填色这一种强调。
            if self.topic_keyboard and focused is button and not active:
                button.create_line(w / 2 - self.px(12), h - self.px(5),
                                   w / 2 + self.px(12), h - self.px(5),
                                   fill=self.p["text3"], width=1, dash=(2, 3))
            button.create_text(w / 2, h / 2, text=name, fill=fg, font=(FONT, 10, "bold"))
        if self.topic == TAROT_CUSTOM:
            self.topic_input.pack(fill="x", pady=(self.px(8), 0))
        else:
            self.topic_input.pack_forget()
        if self.state == "topic" and hasattr(self, "start_btn") and self.start_btn.winfo_exists():
            self.button_feedback(self.start_btn, self.topic != TAROT_CUSTOM or bool(self.topic_var.get().strip()))

    def start_daily(self):
        if self.closed or self.state != "topic":
            return
        if self.topic == TAROT_CUSTOM and not self.topic_var.get().strip():
            self.topic_entry.focus_set()
            return
        tarot_topic_set(self.app.conf, self.topic, self.topic_var.get())
        self.cv.configure(takefocus=True)
        self.start_shuffle()

    def update_daily_prompt(self):
        self.hint.configure(text=(f"{self.daily_day.month} 月 {self.daily_day.day} 日 · "
                                  f"周{'一二三四五六日'[self.daily_day.weekday()]} · "
                                  f"主题：{self.topic} · 今天已经抽过，明天再来。"))
        self.prompt = tarot_daily_prompt(self.daily_day, *self.deck[self.selected[0]],
                                         self.topic, self.topic_var.get())
        self.update_prompt_text()
        self.copy_btn.itemconfigure("text", text="复制")

    def update_prompt_text(self):
        text = self.prompt_text
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.insert("1.0", self.prompt)
        text.configure(state="disabled")
        # 实际显示行数包含窄屏和长问题的自动换行。
        text.update_idletasks()
        display_lines = (text.count("1.0", "end-1c", "displaylines") or (0,))[0] + 1
        text.configure(height=max(len(self.prompt.splitlines()), display_lines))

    def question_screen(self):
        self.state = "question"
        self.cv.configure(height=self.px(456))
        self.title.configure(text="留一点时间，给心里的问题")
        self.hint.configure(text="写下你的问题，再开始这一次抽牌。")
        self.cv.delete("all")
        cx = self.w / 2
        self.cv.create_oval((cx - 135) * self.s, 330 * self.s,
                            (cx + 135) * self.s, 348 * self.s,
                            fill=self.p["input"], outline="")
        for i in range(6):
            self.card(cx + (5 - i) * 3 - 8, 192 - i * 2, 112)
        self.text(cx, 372, "七十八张牌，一个此刻的问题。", 11)
        self.clear_controls()
        self.label(self.controls, "你想问什么？", 11, "text", True).pack(anchor="w")
        row = tk.Frame(self.controls, bg=self.p["ground"])
        row.pack(fill="x", pady=(self.px(7), 0))
        self.question_var = tk.StringVar(master=self.win)
        self.entry = tk.Entry(row, textvariable=self.question_var, font=(FONT, 11),
                              bg=self.p["surface"], fg=self.p["text"],
                              insertbackground=self.p["text"], relief="flat", bd=0,
                              highlightthickness=1, highlightbackground=self.p["border"],
                              highlightcolor=self.p["accent"])
        self.entry.pack(side="left", fill="x", expand=True, ipady=self.px(9))
        self.submit_btn = PillButton(row, "确认", self.p["track"], self.p["text3"],
                                     self.submit, self.p["ground"], (FONT, 10))
        self.submit_btn.pack(side="right", padx=(self.px(12), 0))
        self.question_var.trace_add("write", lambda *_: self.submit_feedback())
        self.entry.focus_set()
        self.viewport.yview_moveto(0)
        self.fit()

    def button_feedback(self, button, enabled):
        button.bg = self.p["accent" if enabled else "track"]
        button.itemconfigure(button.shape, fill=button.bg)
        button.itemconfigure("text", fill=self.p["on_accent" if enabled else "text3"])
        button.configure(cursor="hand2" if enabled else "arrow")

    def submit_feedback(self):
        self.button_feedback(self.submit_btn, bool(self.question_var.get().strip()))

    def enter(self, _event=None):
        if self.state == "mode":
            self.choose_mode(("daily", "question")[self.mode_index])
        elif self.state == "topic":
            self.start_daily()
        elif self.state == "question":
            self.submit()
        elif self.state == "picking":
            self.confirm()
        return "break"

    def submit(self, question=None):
        if self.state == "mode":
            self.choose_mode("question")
        if self.state != "question":
            return
        if question is not None:
            self.question_var.set(question)
        question = self.question_var.get().strip()
        if not question:
            self.entry.focus_set()
            return
        self.question = question
        self.start_shuffle()

    def start_shuffle(self):
        self.cancel_jobs()
        self.deck, self.state = tarot_shuffle(), "shuffling"
        self.cv.configure(height=self.px(456))
        self.clear_controls()
        self.title.configure(text="留一点时间，给今天的自己" if self.mode == "daily" else "让问题，慢慢落定")
        self.hint.configure(text="正在洗牌…")
        self.button("重新开始", self.reset, False).pack(side="right")
        self.fit()
        self.shuffle_frame()

    def shuffle_frame(self, frame=0):
        import math
        self.cv.delete("all")
        t = frame / 100
        # 两次散开、交叠，再收拢；最后从同一个中心铺到两排。
        spread = math.sin(math.pi * t) ** 1.2
        for i in range(12):
            a = i * math.tau / 12 + t * math.tau * 2
            x = self.w / 2 + math.cos(a) * min(180, self.w * .26) * spread
            y = 210 + math.sin(a) * 78 * spread + (i - 6) * (1 - spread) * 1.5
            self.card(x, y, 94)
        self.text(self.w / 2, 390, "把注意力，留在今天的自己身上。" if self.mode == "daily"
                  else "把注意力，留在你的问题上。", 10)
        if frame < 100:
            self.later(16, lambda: self.shuffle_frame(frame + 1))
        else:
            self.state = "dealing"
            self.deal_frame()

    def spread_xy(self, i):
        row, col = divmod(i, 39)
        width = min(48, self.w * .09)
        left = 24 + width / 2
        x = left + col * (self.w - 2 * left) / 38
        y = 302 + row * 92 + 10 * ((col - 19) / 19) ** 2
        return x, y, width

    def slot_xy(self, slot):
        return (self.w / 2 if self.mode == "daily" else self.w * (slot + 1) / 4), 132

    def slots(self):
        cw = min(108, self.w / 4 - 22)
        for j, pos in enumerate(self.positions):
            x, y = self.slot_xy(j)
            self.text(x, 22, f"{j + 1:02d}  {pos}", 10, "text2", True)
            self.cv.create_rectangle((x - cw / 2 - 4) * self.s, (y - cw * 260 / 300 - 4) * self.s,
                                     (x + cw / 2 + 4) * self.s, (y + cw * 260 / 300 + 4) * self.s,
                                     outline=self.p["border"], dash=(3, 5), tags=("slot",))
            if j >= len(self.selected):
                self.text(x, y, "待选", 10, "text3")
        return cw

    def deal_frame(self, frame=0):
        self.cv.delete("all")
        self.slots()
        t = 1 - (1 - frame / 24) ** 3
        for i in range(78):
            x, y, width = self.spread_xy(i)
            self.card(self.w / 2 + (x - self.w / 2) * t, 210 + (y - 210) * t, width)
        if frame < 24:
            self.later(16, lambda: self.deal_frame(frame + 1))
        else:
            self.state = "picking"
            self.title.configure(text="凭直觉，选出你的一张今日牌" if self.mode == "daily" else "凭直觉，选出你的三张牌")
            self.pick_controls()
            self.draw()
            self.cv.focus_set()

    def pick_controls(self):
        self.clear_controls()
        self.confirm_btn = self.button("确定", self.confirm)
        self.confirm_btn.pack(side="right")
        self.button("重新开始", self.reset, False).pack(side="right", padx=self.px(10))
        self.label(self.controls, "点已选牌可撤回", 9, "text3").pack(side="left")

    def draw(self):
        self.cv.delete("all")
        if self.mode == "daily" and self.state == "result":
            self.draw_daily_result()
            return
        cw = self.slots()
        if self.state == "picking":
            for i in range(78):
                if i not in self.selected:
                    x, y, width = self.spread_xy(i)
                    self.card(x, y, width)
            # 高亮不改变命中顺序：仍按原来露出的窄条命中，避免悬停时来回跳牌。
            if self.hover is not None and self.hover not in self.selected:
                x, y, width = self.spread_xy(self.hover)
                self.cv.create_rectangle((x - width / 2 - 3) * self.s, (y - 12 - width * 260 / 300 - 3) * self.s,
                                         (x + width / 2 + 3) * self.s, (y - 12 + width * 260 / 300 + 3) * self.s,
                                         fill=self.p["surface"], outline=self.p["accent"], width=self.px(3))
                self.card(x, y - 12, width)
            count = len(self.positions)
            self.hint.configure(text=(f"已选 {len(self.selected)}/{count} · 下一张：{self.positions[len(self.selected)]}"
                                      if len(self.selected) < count else "牌已就位。准备好后，点「确定」翻牌。"))
            self.button_feedback(self.confirm_btn, len(self.selected) == count)
        for slot, i in enumerate(self.selected):
            x, y = self.slot_xy(slot)
            key, rev = self.deck[i]
            face = slot in self.revealed
            self.card(x, y, cw, key if face else TAROT_BACK, rev if face else False)
            if face:
                self.text(x, 244, tarot_name(key)[0], 11, "text", True)
                self.text(x, 268, "逆位" if rev else "正位", 9)
            elif self.state == "picking":
                self.text(x, 244, "点击撤回", 9, "text3")

    def draw_daily_result(self):
        """今日结果横向排版，小牌与右侧牌名共用 150 高度（自定义多一行输入框，1080p 也不用滚动）。"""
        key, rev = self.deck[self.selected[0]]
        cw = min(72, self.w / 4)
        x, y = max(cw / 2 + 18, self.w / 2 - 100), 75
        tx = x + cw / 2 + 24
        self.card(x, y, cw, key, rev)
        self.text(tx, 36, "今日牌", 10, "text3", anchor="nw")
        self.text(tx, 62, tarot_name(key)[0], 16, "text", True,
                  anchor="nw", width=self.px(self.w - tx - 18))
        self.text(tx, 104, "逆位" if rev else "正位", 10, anchor="nw")

    def hit(self, x, y):
        for i in reversed(range(78)):
            if i in self.selected:
                continue
            cx, cy, width = self.spread_xy(i)
            if abs(x - cx) <= width / 2 and abs(y - cy) <= width * 260 / 300:
                return i
        return None

    def set_hover(self, i):
        if self.state == "mode":
            if self.mode_hover is not None:
                self.mode_hover = None
                self.draw_modes()
            self.cv.configure(cursor="arrow")
            return
        if i is not None and (not isinstance(i, int) or not 0 <= i < 78 or i in self.selected):
            i = None
        if self.state == "picking" and self.hover != i:
            self.hover = i
            self.cv.configure(cursor="hand2" if i is not None else "arrow")
            self.draw()

    def motion(self, event):
        if self.state == "mode":
            i = self.mode_hit(self.cv.canvasx(event.x) / self.s, self.cv.canvasy(event.y) / self.s)
            if i != self.mode_hover:
                self.mode_hover = i
                self.cv.configure(cursor="hand2" if i is not None else "arrow")
                self.draw_modes()
            return
        if self.state == "picking":
            self.set_hover(self.hit(self.cv.canvasx(event.x) / self.s,
                                   self.cv.canvasy(event.y) / self.s))

    def click(self, event):
        if self.state == "mode":
            i = self.mode_hit(self.cv.canvasx(event.x) / self.s, self.cv.canvasy(event.y) / self.s)
            if i is not None:
                self.choose_mode(("daily", "question")[i])
            return
        if self.state != "picking":
            return
        x, y = self.cv.canvasx(event.x) / self.s, self.cv.canvasy(event.y) / self.s
        cw = min(108, self.w / 4 - 22)
        for slot, i in enumerate(self.selected):
            cx, cy = self.slot_xy(slot)
            if abs(x - cx) <= cw / 2 + 8 and abs(y - cy) <= cw * 260 / 300 + 8:
                self.pick(i)
                return
        i = self.hit(x, y)
        if i is not None:
            self.pick(i)

    def keyboard(self, direction):
        if self.state == "mode":
            self.mode_index = (self.mode_index + direction) % 2
            self.mode_hover = None
            self.draw_modes()
            return "break"
        if self.state != "picking":
            return "break"
        i = self.hover if self.hover is not None else (-1 if direction > 0 else 78)
        for _ in range(78):
            i = (i + direction) % 78
            if i not in self.selected:
                self.set_hover(i)
                break
        return "break"

    def keyboard_pick(self, _event):
        if self.state == "mode":
            return self.enter()
        if self.hover is not None:
            self.pick(self.hover)
        return "break"

    def pick(self, i):
        if self.state != "picking" or not isinstance(i, int) or not 0 <= i < 78:
            return
        if i in self.selected:
            self.selected.remove(i)
        elif len(self.selected) < len(self.positions):
            self.selected.append(i)
        self.hover = None
        self.draw()

    def confirm(self):
        if self.state != "picking" or len(self.selected) != len(self.positions):
            return
        # 在开始动画之前读取三张牌；损坏图片可重试，不留下半翻开的牌局。
        try:
            cw = min(108, self.w / 4 - 22)
            for i in self.selected:
                key, rev = self.deck[i]
                self.image(key, cw, rev)
            if self.mode == "daily":
                day = dt.date.today()
                saved = tarot_daily_get(self.app.conf, day)
                if saved:
                    self.daily_result(day, saved)
                    return
                key, rev = self.deck[self.selected[0]]
                tarot_daily_set(self.app.conf, day, key, rev)
                self.daily_day = day
        except (tk.TclError, OSError, ValueError) as ex:
            self.error(f"牌面无法读取：{ex}")
            return
        self.state, self.hover = "revealing", None
        self.cv.configure(cursor="arrow")
        self.clear_controls()
        self.button("重新开始", self.reset, False).pack(side="right")
        self.title.configure(text="属于今天的一张牌，慢慢展开" if self.mode == "daily" else "过去、现在、未来，依次展开")
        self.hint.configure(text="正在翻牌…")
        self.flip()

    def flip(self, slot=0, frame=0):
        import math
        self.draw()
        x, y = self.slot_xy(slot)
        cw = min(108, self.w / 4 - 22)
        width = max(1 / self.s, cw * abs(math.cos(math.pi * frame / 20)))
        # 覆盖这一张的原图，保留牌位和其他牌；宽度收窄时高度不变。
        self.cv.create_rectangle((x - cw / 2 - 1) * self.s, (y - cw * 260 / 300 - 1) * self.s,
                                 (x + cw / 2 + 1) * self.s, (y + cw * 260 / 300 + 1) * self.s,
                                 fill=self.p["surface"], outline="")
        key, rev = self.deck[self.selected[slot]]
        self.card(x, y, width, key if frame >= 10 else TAROT_BACK,
                  rev if frame >= 10 else False, height=cw * 260 / 150)
        if frame < 20:
            self.later(16, lambda: self.flip(slot, frame + 1))
        else:
            self.revealed.add(slot)
            self.draw()
            if slot + 1 < len(self.positions):
                self.later(160, lambda: self.flip(slot + 1))
            else:
                self.later(180, self.result)

    def result(self):
        self.cancel_jobs()
        self.state = "result"
        self.draw()
        self.cv.configure(height=self.px(150 if self.mode == "daily" else 300))
        self.title.configure(text="你的今日牌，已展开" if self.mode == "daily" else "你的三张牌，已展开")
        self.hint.configure(text=(f"{self.daily_day.month} 月 {self.daily_day.day} 日 · "
                                  f"周{'一二三四五六日'[self.daily_day.weekday()]} · 今天已经抽过，明天再来。"
                                  if self.mode == "daily" else self.question))
        self.clear_controls()
        if self.mode == "daily":
            self.topic_controls()
        self.label(self.controls, "带着今日牌，去问 AI" if self.mode == "daily" else "带着问题与牌面，去问 AI",
                   11, "text", True).pack(anchor="w")
        self.prompt = (tarot_daily_prompt(self.daily_day, *self.deck[self.selected[0]],
                                           self.topic, self.topic_var.get())
                       if self.mode == "daily" else tarot_prompt(self.question, [self.deck[i] for i in self.selected]))
        area = tk.Frame(self.controls, bg=self.p["surface"], highlightthickness=1,
                        highlightbackground=self.p["border"])
        area.pack(fill="x", pady=(self.px(8), self.px(12)))
        text = tk.Text(area, height=len(self.prompt.splitlines()), width=1, wrap="word", font=(FONT, 10),
                       relief="flat", bd=0, padx=self.px(12), pady=self.px(10),
                       bg=self.p["surface"], fg=self.p["text2"],
                       selectbackground=self.p["accent"], selectforeground=self.p["on_accent"],
                       highlightthickness=0)
        text.pack(fill="x", expand=True)
        self.prompt_text = text
        self.update_prompt_text()
        self.copy_btn = self.button("复制", self.copy)
        self.copy_btn.pack(side="right")
        self.button("返回" if self.mode == "daily" else "再抽一次", self.reset, False).pack(side="right", padx=self.px(10))
        if self.mode == "daily":
            self.update_daily_prompt()
        self.viewport.yview_moveto(0)
        self.fit()

    def copy(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.prompt)
        self.copy_btn.itemconfigure("text", text="已复制")
        self.later(1400, lambda: self.copy_btn.itemconfigure("text", text="复制"))


class ToyWindow:
    """小玩具共用的窗口、屏幕边界和动画回调管理。"""

    def __init__(self, app, key, title, caption, heading):
        self.app, self.p, self.s, self.key = app, app.p, app.ui_scale(), key
        self.state, self.result, self.closed, self.jobs = "ready", None, False, set()
        self.win = win = tk.Toplevel(app.root, bg=self.p["ground"])
        setattr(app, key + "_win", win)
        win.title(title)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.close)
        win.bind("<Escape>", lambda _e: self.close())
        win.bind("<Destroy>", self.destroyed, add="+")
        win_dark_titlebar(win, app.dark)
        self.width = min(self.px(480), int(win.winfo_screenwidth() * .86))
        self.w = self.width / self.s - 40
        self.viewport = tk.Canvas(win, width=self.width, bg=self.p["ground"],
                                  bd=0, highlightthickness=0)
        self.viewport.pack(side="left", fill="both", expand=True)
        self.scroll = TarotScrollbar(win, self.p, self.s, self.viewport.yview)
        self.viewport.configure(yscrollcommand=self.scroll.set)
        self.body = tk.Frame(self.viewport, bg=self.p["ground"], padx=self.px(20), pady=self.px(18))
        self.viewport.create_window(0, 0, window=self.body, anchor="nw", width=self.width)
        self.body.bind("<Configure>", lambda _e: self.viewport.configure(
            scrollregion=self.viewport.bbox("all")))
        win.bind("<MouseWheel>", self.wheel)
        win.bind("<Button-4>", lambda _e: self.viewport.yview_scroll(-2, "units"))
        win.bind("<Button-5>", lambda _e: self.viewport.yview_scroll(2, "units"))
        self.label(self.body, caption, 9, "text3").pack(anchor="w")
        self.heading = self.label(self.body, heading, 21, "text", True)
        self.heading.pack(anchor="w", pady=(self.px(5), self.px(14)))

    def px(self, value):
        return max(1, round(value * self.s))

    def label(self, parent, text, size=10, color="text2", bold=False):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=self.p[color],
                        font=(FONT, size, "bold" if bold else "normal"), justify="left",
                        anchor="w", wraplength=self.px(self.w - 8))

    def button(self, parent, text, action, primary=True):
        button = PillButton(parent, text, self.p["accent" if primary else "track"],
                            self.p["on_accent" if primary else "text"], action,
                            parent["bg"], (FONT, 10))
        button._action = action
        return button

    def enable(self, button, enabled):
        button.command = button._action if enabled else lambda: None
        button.bg = self.p["accent" if enabled else "track"]
        button.itemconfigure(button.shape, fill=button.bg)
        button.itemconfigure("text", fill=self.p["on_accent" if enabled else "text3"])
        button.configure(cursor="hand2" if enabled else "arrow")

    def later(self, ms, action):
        if self.closed:
            return
        job = None

        def run():
            self.jobs.discard(job)
            if not self.closed:
                action()
        job = self.win.after(ms, run)
        self.jobs.add(job)

    def animate(self, duration, frame, finish):
        import time
        started = time.perf_counter()

        def step():
            t = min(1, (time.perf_counter() - started) * 1000 / duration)
            frame(t)
            if t < 1:
                self.later(16, step)
            else:
                finish()
        step()

    def cancel_jobs(self):
        for job in self.jobs:
            try:
                self.win.after_cancel(job)
            except tk.TclError:
                pass
        self.jobs.clear()

    def close(self):
        if not self.closed:
            self.closed, self.state = True, "closed"
            self.cancel_jobs()
            self.win.destroy()

    def destroyed(self, event):
        if event.widget == self.win:
            self.closed, self.state = True, "closed"
            self.cancel_jobs()
            if getattr(self.app, self.key + "_win", None) is self.win:
                setattr(self.app, self.key + "_win", None)

    def wheel(self, event):
        # 编辑框自行处理滚轮，避免同时带动整张页面。
        if isinstance(event.widget, tk.Text):
            return
        self.viewport.yview_scroll(-2 if event.delta > 0 else 2, "units")

    def fit(self):
        self.win.update_idletasks()
        h = min(self.body.winfo_reqheight(), int(self.win.winfo_screenheight() * .84))
        overflow = self.body.winfo_reqheight() > h
        if overflow:
            self.scroll.pack(side="right", fill="y")
        else:
            self.scroll.pack_forget()
        width = self.width + (self.scroll.winfo_reqwidth() if overflow else 0)
        x = self.app.root.winfo_x() - width - self.px(12)
        if x < 0:
            x = self.app.root.winfo_x() + self.app.root.winfo_width() + self.px(12)
        x = max(0, min(x, self.win.winfo_screenwidth() - width))
        y = max(0, min(self.app.root.winfo_y(), self.win.winfo_screenheight() - h - self.px(48)))
        self.win.geometry(f"{width}x{h}+{x}+{y}")
        self.viewport.yview_moveto(0)

    def snapshot(self):
        return {"state": self.state, "result": self.result}


class LunchWheel(ToyWindow):
    """随机结果只由底层决定，转盘动画负责准确停到对应扇区。"""

    def __init__(self, app):
        super().__init__(app, "lunch", "午饭吃什么", "午间休息 · 给选择放个假", "今天中午，转个主意")
        self.angle, self.winner = 0.0, None
        self.candidates, self.excluded = lunch_candidates(app.conf)
        self.result = lunch_today(app.conf)
        self.play_page = tk.Frame(self.body, bg=self.p["ground"])
        self.play_page.pack(fill="x")
        self.cv = tk.Canvas(self.play_page, width=self.px(self.w), height=self.px(370),
                            bg=self.p["surface"], highlightthickness=1,
                            highlightbackground=self.p["border"], bd=0)
        self.cv.pack(fill="x")
        self.result_label = self.label(self.play_page,
            f"今天中午：{self.result}" if self.result else "把纠结，交给这一转", 19, "text", True)
        self.result_label.pack(fill="x", pady=(self.px(14), self.px(5)))
        self.skip_label = self.label(self.play_page, "", 9, "text3")
        self.skip_label.pack(fill="x", pady=(0, self.px(14)))
        row = tk.Frame(self.play_page, bg=self.p["ground"])
        row.pack(fill="x")
        self.edit_button = self.button(row, "编辑选项", self.edit, False)
        self.edit_button.pack(side="left")
        self.spin_button = self.button(row, "转！", self.spin)
        self.spin_button.pack(side="right")
        self.edit_page = tk.Frame(self.body, bg=self.p["ground"])
        self.label(self.edit_page, f"每行一项，2–{LUNCH_MAX} 项；每项最多 {LUNCH_NAME_MAX} 个字。", 10).pack(anchor="w")
        area = tk.Frame(self.edit_page, bg=self.p["surface"], highlightthickness=1,
                        highlightbackground=self.p["border"])
        area.pack(fill="x", pady=self.px(12))
        self.editor = tk.Text(area, height=10, width=1, font=(FONT, 11), wrap="none",
                              bg=self.p["surface"], fg=self.p["text"], relief="flat", bd=0,
                              insertbackground=self.p["text"], padx=self.px(12), pady=self.px(10),
                              selectbackground=self.p["accent"], selectforeground=self.p["on_accent"])
        editor_scroll = TarotScrollbar(area, self.p, self.s, self.editor.yview)
        editor_scroll.pack(side="right", fill="y")
        self.editor.configure(yscrollcommand=editor_scroll.set)
        self.editor.pack(side="left", fill="both", expand=True)
        self.edit_hint = self.label(self.edit_page, "修改后点「保存」，才会更新转盘。", 9, "text3")
        self.edit_hint.pack(fill="x", pady=(0, self.px(12)))
        actions = tk.Frame(self.edit_page, bg=self.p["ground"])
        actions.pack(fill="x")
        self.button(actions, "恢复默认", self.restore_defaults, False).pack(side="left")
        self.button(actions, "保存", self.save_options).pack(side="right")
        self.button(actions, "取消", self.end_edit, False).pack(side="right", padx=self.px(8))
        self.win.bind("<Return>", self.enter)
        self.draw()
        self.update_skip()
        self.fit()

    def enter(self, _event):
        if self.state == "ready":
            self.spin()
            return "break"

    def update_skip(self):
        self.skip_label.configure(text=("最近吃过，今天先跳过：" + "、".join(self.excluded)
                                        if self.excluded else "每项机会相同；最近吃过的会自动跳过。"))

    def draw(self):
        import math
        cv, s = self.cv, self.s
        cv.delete("all")
        cx, cy, r = self.w / 2, 190, min(162, self.w / 2 - 18)
        step = 360 / len(self.candidates)
        colors = ("toy_blue", "toy_rose", "toy_sage", "toy_amber", "toy_lilac")
        for i, name in enumerate(self.candidates):
            a = self.angle + i * step
            cv.create_arc((cx-r)*s, (cy-r)*s, (cx+r)*s, (cy+r)*s,
                          start=a, extent=step + .1, style="pieslice", fill=self.p[colors[i % len(colors)]],
                          outline=self.p["surface"], width=self.px(1))
            mid = a + step / 2
            theta = math.radians(mid)
            radius = (25 + r) / 2 + 4  # 文字居中放在中心圆和外圈之间，长名字也不顶到边
            # 径向文字利用扇区长度；20 项和八字名称也不会挤在圆周上。
            label_angle = mid % 360
            if 90 < label_angle < 270:
                label_angle = (label_angle + 180) % 360
            cv.create_text((cx + radius * math.cos(theta))*s, (cy - radius * math.sin(theta))*s,
                           text=name, angle=label_angle, fill=self.p["text"],
                           font=(FONT, 7 if len(name) >= 7 and len(self.candidates) > 14
                                 else 8 if len(self.candidates) > 14 or len(name) >= 7 else 9, "bold"))
            if i == self.winner:
                cv.create_arc((cx-r)*s, (cy-r)*s, (cx+r)*s, (cy+r)*s,
                              start=a, extent=step, style="pieslice", outline=self.p["accent"],
                              fill="", width=self.px(3))
        cv.create_oval((cx-25)*s, (cy-25)*s, (cx+25)*s, (cy+25)*s,
                       fill=self.p["surface"], outline=self.p["border"], width=self.px(1))
        cv.create_text(cx*s, cy*s, text="午饭", font=(FONT, 9, "bold"), fill=self.p["text2"])
        # 顶部固定指针，Canvas 角度 90° 对应正上方。
        tip = cy - r + 12
        cv.create_polygon((cx-10)*s, (tip-24)*s, (cx+10)*s, (tip-24)*s, cx*s, tip*s,
                          fill=self.p["text"], outline="")

    def spin(self):
        if self.state != "ready":
            return
        self.candidates, self.excluded = lunch_candidates(self.app.conf)
        self.update_skip()
        self.state, self.winner = "spinning", None
        self.enable(self.spin_button, False)
        self.edit_button.command = lambda: None
        self.edit_button.configure(cursor="arrow")
        self.result_label.configure(text="正在转，午饭马上有着落…")
        index = lunch_spin(self.candidates)
        step = 360 / len(self.candidates)
        # 格内轻微偏移，始终留在该格中央 36% 的范围内，不会跨过分隔线。
        target = 90 - (index + .5) * step + random.uniform(-.18, .18) * step
        start = self.angle
        distance = 6 * 360 + (target - start) % 360

        def frame(t):
            self.angle = start + distance * (1 - (1-t) ** 4)
            self.draw()

        def finish():
            self.angle %= 360
            self.winner, self.result = index, self.candidates[index]
            self.state = "ready"
            lunch_record(self.app.conf, self.result)
            try:
                save_conf(self.app.conf)
                self.result_label.configure(text=f"今天中午：{self.result}")
            except OSError:
                self.result_label.configure(text=f"今天中午：{self.result}（配置未能写入）")
            self.app.refresh_lunch_entry()
            self.enable(self.spin_button, True)
            self.edit_button.command = self.edit_button._action
            self.edit_button.configure(cursor="hand2")
            self.draw()
            pet = getattr(self.app, "pet", None)
            if pet and pet.win is not None:
                pet.play("excited", 2, "happy", 1)
        self.animate(3600, frame, finish)

    def edit(self):
        if self.state != "ready":
            return
        self.state = "editing"
        self.play_page.pack_forget()
        self.heading.configure(text="把喜欢的，都放上转盘")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", "\n".join(lunch_options(self.app.conf)))
        self.edit_hint.configure(text="修改后点「保存」，才会更新转盘。", fg=self.p["text3"])
        self.edit_page.pack(fill="x")
        self.editor.focus_set()
        self.fit()

    def restore_defaults(self):
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", "\n".join(LUNCH_DEFAULT))
        self.edit_hint.configure(text="已填入默认选项；点「保存」应用。", fg=self.p["text3"])

    def save_options(self):
        names = [x.strip() for x in self.editor.get("1.0", "end-1c").splitlines() if x.strip()]
        if not 2 <= len(names) <= LUNCH_MAX:
            message = f"请填写 2–{LUNCH_MAX} 项，每行一项。"
        elif any(len(x) > LUNCH_NAME_MAX for x in names):
            message = f"每项最多 {LUNCH_NAME_MAX} 个字，请缩短名称。"
        elif len(set(names)) != len(names):
            message = "有重复的选项，请删掉重复行。"
        else:
            lunch_set_options(self.app.conf, names)
            try:
                save_conf(self.app.conf)
            except OSError:
                self.edit_hint.configure(text="配置未能写入，请重试保存。", fg=self.p["danger"])
                return
            self.end_edit()
            return
        self.edit_hint.configure(text=message, fg=self.p["danger"])

    def end_edit(self):
        self.state, self.winner, self.angle = "ready", None, 0.0
        self.candidates, self.excluded = lunch_candidates(self.app.conf)
        self.edit_page.pack_forget()
        self.play_page.pack(fill="x")
        self.heading.configure(text="今天中午，转个主意")
        self.update_skip()
        self.draw()
        self.fit()

    def snapshot(self):
        return dict(super().snapshot(), candidates=list(self.candidates), excluded=list(self.excluded),
                    winner=self.winner, angle=self.angle % 360)


class JiaoTable(ToyWindow):
    """红色月牙筊杯；只显示传统结果，不增加解读。"""

    ANIMATION_MS = 1480

    def __init__(self, app):
        super().__init__(app, "jiao", "赛博圣杯 · 掷筊", "一问一掷 · 静候杯落", "把问题，轻轻放下")
        self.faces, self.count, self.streak_mode = (True, False), 0, False
        self.question = tk.StringVar(master=self.win)
        self.label(self.body, "你想问什么？（可不填）", 10).pack(anchor="w")
        self.entry = tk.Entry(self.body, textvariable=self.question, font=(FONT, 11),
                              relief="flat", bg=self.p["surface"], fg=self.p["text"],
                              insertbackground=self.p["text"], highlightthickness=1,
                              highlightbackground=self.p["border"], highlightcolor=self.p["accent"])
        self.entry.pack(fill="x", ipady=self.px(8), pady=(self.px(6), self.px(12)))
        self.cv = tk.Canvas(self.body, width=self.px(self.w), height=self.px(300),
                            bg=self.p["surface"], bd=0, highlightthickness=1,
                            highlightbackground=self.p["border"])
        self.cv.pack(fill="x")
        self.result_label = self.label(self.body, "心有所问，掷杯听回应", 20, "text", True)
        self.result_label.pack(fill="x", pady=(self.px(14), self.px(5)))
        self.meaning = self.label(self.body, "一平一凸为圣杯，两平为笑杯，两凸为阴杯。", 10)
        self.meaning.pack(fill="x")
        self.progress = tk.Canvas(self.body, width=self.px(self.w), height=self.px(44),
                                  bg=self.p["ground"], highlightthickness=0)
        self.progress.pack(fill="x", pady=(self.px(4), self.px(8)))
        row = tk.Frame(self.body, bg=self.p["ground"])
        row.pack(fill="x")
        self.mode_var = tk.BooleanVar(master=self.win, value=False)
        self.mode_button = tk.Checkbutton(row, text="连续三圣杯", variable=self.mode_var,
            command=lambda: self.set_streak(self.mode_var.get()), font=(FONT, 10),
            bg=self.p["ground"], fg=self.p["text2"], activebackground=self.p["ground"],
            activeforeground=self.p["text"], selectcolor=self.p["input"],
            highlightthickness=0, bd=0, cursor="hand2")
        self.mode_button.pack(side="left")
        self.throw_button = self.button(row, "掷杯", self.throw)
        self.throw_button.pack(side="right")
        self.win.bind("<Return>", lambda _e: self.throw())
        self.draw()
        self.draw_progress()
        self.fit()

    def material(self, first, second, amount):
        """从已有主题颜色调出明暗层次，避免给筊杯写死另一套颜色。"""
        a, b = self.p[first], self.p[second]
        return "#" + "".join(f"{round(int(a[i:i+2], 16)*(1-amount) + int(b[i:i+2], 16)*amount):02x}"
                              for i in (1, 3, 5))

    def cup(self, x, y, flat, tilt, squash=1):
        import math
        size = min(1, self.w / 400)
        angle = math.radians(tilt)

        def points(coords, inset=1, dx=0, dy=0):
            out = []
            for px, py in coords:
                # 明暗层共同向木筊内部的同一中心收缩，不再独立错位或拉伸。
                px, py = -8 + (px + 8)*inset, 22 + (py - 22)*inset
                # 长轴是横向；绕长轴翻转时压缩纵向，长度保持不变。
                px, py = px * size, (py - 26) * .78 * squash * size
                out.extend(((x + px*math.cos(angle) - py*math.sin(angle) + dx*size)*self.s,
                            (y + px*math.sin(angle) + py*math.cos(angle) + dy*size)*self.s))
            return out

        def bezier(a, b, c, d):
            return [((1-t)**3*a[0] + 3*(1-t)**2*t*b[0] + 3*(1-t)*t*t*c[0] + t**3*d[0],
                     (1-t)**3*a[1] + 3*(1-t)**2*t*b[1] + 3*(1-t)*t*t*c[1] + t**3*d[1])
                    for t in (i/12 for i in range(12))]

        # 浅内凹、胖外弧，中段投影宽度约为长度的 37%；两端圆钝收尖。
        outline = []
        for segment in (
            ((-65, -8), (-64, -16), (-57, -14), (-50, -9)),
            ((-50, -9), (-22, 0), (22, 0), (50, -9)),
            ((50, -9), (57, -14), (64, -16), (65, -8)),
            ((65, -8), (71, 19), (43, 60), (0, 60)),
            ((0, 60), (-43, 60), (-71, 19), (-65, -8)),
        ):
            outline.extend(bezier(*segment))

        depth = (8 + 6 * squash) if flat else (6 + 4 * squash)
        # 上下边沿共用轮廓采样点，逐段封住侧壁，端头不会露出错位缺口。
        top = points(outline)
        bottom = points(outline, dx=2, dy=depth)
        self.cv.create_polygon(bottom, smooth=True,
                               fill=self.p["jiao_edge"], outline="")
        wall_color = self.material("jiao_red", "jiao_edge", .22)
        for i in range(len(outline)):
            a, b = 2*i, 2*((i+1) % len(outline))
            self.cv.create_polygon(top[a:a+2] + top[b:b+2] + bottom[b:b+2] + bottom[a:a+2],
                                   fill=wall_color, outline=wall_color, width=max(.5, self.s*.45))
        if flat:
            self.cv.create_polygon(points(outline), smooth=True,
                fill=self.p["jiao_flat"], outline=self.material("jiao_flat", "jiao_edge", .30),
                width=max(1, self.s))
            # 只有很淡的直木纹，不再用容易被看成水果纹路的同心弧线。
            for grain in (((-34, 15), (13, 15)), ((-22, 28), (34, 28)), ((-14, 40), (20, 40))):
                self.cv.create_line(points(grain), fill=self.material("jiao_flat", "jiao_edge", .10),
                                    width=max(1, self.s*.65), capstyle="round")
        else:
            # 由背光边缘到受光拱背，三层连续色块抬起中心，再覆一条短高光。
            self.cv.create_polygon(points(outline), smooth=True,
                                   fill=self.p["jiao_red"], outline="")
            self.cv.create_polygon(points(outline, inset=.86), smooth=True,
                                   fill=self.material("jiao_red", "jiao_shine", .22), outline="")
            self.cv.create_polygon(points(outline, inset=.63), smooth=True,
                                   fill=self.material("jiao_red", "jiao_shine", .40), outline="")
            if squash > .18:
                # 高光也取同一轮廓的内缩曲线，始终留在亮部内部。
                self.cv.create_line(points(outline[12:25], inset=.53),
                                    fill=self.material("jiao_shine", "jiao_flat", .18),
                                    width=self.px(2), smooth=True, capstyle="round")

    def cup_pose(self, i, flat, t=None):
        """返回杯的位置、朝向、纵向翻转比例和离地高度；不更改最终结果。"""
        import math
        direction = -1 if i == 0 else 1
        x, y, tilt = self.w*(.31 if i == 0 else .69), 190, (-12 if i == 0 else 16)
        if t is None:
            return x, y, flat, tilt, 1, 0
        elapsed = max(0, t*self.ANIMATION_MS - (40 if i else 0))
        flight = 950 if i else 900
        bounce = 140
        lift, squash, face = 0, 1, flat
        if elapsed < flight:
            u = elapsed/flight
            lift = (94 if i == 0 else 101) * math.sin(math.pi*u)**.9
            x += direction*14*math.sin(math.pi*u)
            tilt += direction*(25*math.sin(math.pi*u) + 32*math.sin(2*math.pi*u))
            previous = getattr(self, "_launch_faces", self.faces)[i]
            start = 0 if previous else math.pi
            end = (6 if i else 4)*math.pi + (0 if flat else math.pi)
            phase = start + (end-start)*(u*u*(3-2*u))
            roll = math.cos(phase)
            face, squash = roll >= 0, max(.06, abs(roll))
        elif elapsed < flight + bounce:
            u = (elapsed-flight)/bounce
            lift = (4 if flat else 7)*math.sin(math.pi*u)
        elif not flat:
            # 只有凸背会摇晃；幅度衰减三下，最后严格回到平放姿态。
            duration = self.ANIMATION_MS - (40 if i else 0) - flight - bounce
            u = min(1, (elapsed-flight-bounce)/duration)
            rock = math.sin(6*math.pi*u)*(1-u)**2
            tilt += 9*rock
            lift = 1.4*abs(rock)
        return x, y-lift, face, tilt, squash, lift

    def draw(self, t=None):
        self.cv.delete("all")
        for i, flat in enumerate(self.faces):
            x, y, face, tilt, squash, lift = self.cup_pose(i, flat, t)
            size = min(1, self.w/400)
            height = min(1, lift/101)
            # 高处的投影小而淡；落地有一层贴地暗影和两层柔和外晕。
            radius = (53-22*height)*size
            for spread, opacity in ((1.18, .055), (1, .10), (.74, .18)):
                rx, ry = radius*spread, (7-3*height)*spread*size
                color = self.material("surface", "text3", opacity*(1-.78*height))
                self.cv.create_oval((x+4-rx)*self.s, (226-ry)*self.s,
                                    (x+4+rx)*self.s, (226+ry)*self.s,
                                    fill=color, outline="")
            self.cup(x, y, face, tilt, squash)
            self.cv.create_text(self.w*(.31 if i == 0 else .69)*self.s, 263*self.s,
                text="翻转中…" if t is not None else ("平面朝上 · 切面" if flat else "凸面朝上 · 红漆"),
                font=(FONT, 9), fill=self.p["text3"])

    def draw_progress(self):
        cv, s = self.progress, self.s
        cv.delete("all")
        if not self.streak_mode:
            return
        for i in range(JIAO_STREAK):
            x = 8 + i*24
            cv.create_oval(x*s, 15*s, (x+9)*s, 24*s,
                           fill=self.p["accent" if i < self.count else "track"], outline="")
        cv.create_text(88*s, 20*s, anchor="w", text=f"连续圣杯 {self.count}/{JIAO_STREAK}",
                        font=(FONT, 9), fill=self.p["text2"])

    def set_streak(self, enabled):
        if self.state == "throwing":
            self.mode_var.set(self.streak_mode)
            return
        enabled = bool(enabled)
        self.mode_var.set(enabled)
        if enabled != self.streak_mode:
            self.streak_mode, self.count = enabled, 0
            self.result = None
            self.result_label.configure(text="连得三圣杯，方为应允" if enabled else "心有所问，掷杯听回应")
            self.meaning.configure(text="遇笑杯或阴杯，连续进度重新开始。" if enabled else
                                   "一平一凸为圣杯，两平为笑杯，两凸为阴杯。")
        self.draw_progress()
        self.fit()

    def throw(self):
        if self.state != "ready":
            return
        if self.count == JIAO_STREAK:
            self.count = 0
        self.state, self.result = "throwing", None
        self._launch_faces = self.faces
        # 一次只调用一次底层，正反面和结果来自同一组随机值。
        a, b, result = jiao_throw()
        self.faces = (a, b)
        self.entry.configure(state="disabled")
        self.mode_button.configure(state="disabled")
        self.enable(self.throw_button, False)
        self.result_label.configure(text="杯起，静候落定")
        self.meaning.configure(text="")
        self.draw_progress()

        def finish():
            self.state, self.result = "ready", result
            self.result_label.configure(text=result)
            explanation = JIAO_RESULTS[result]
            if self.streak_mode:
                self.count = self.count + 1 if result == "圣杯" else 0
                if self.count == JIAO_STREAK:
                    self.result_label.configure(text="三圣杯，神明应允")
                elif result == "圣杯":
                    explanation += f" 已连续 {self.count} 次，再掷一次。"
                else:
                    explanation += " 三圣杯未成，连续进度已清零。"
            self.meaning.configure(text=explanation)
            self.entry.configure(state="normal")
            self.mode_button.configure(state="normal")
            self.enable(self.throw_button, True)
            self.draw()
            self.draw_progress()
            self.fit()
        self.animate(self.ANIMATION_MS, lambda t: self.draw(t), finish)

    def snapshot(self):
        return dict(super().snapshot(), faces=tuple(self.faces), streak_mode=self.streak_mode,
                    streak=self.count, complete=self.count == JIAO_STREAK,
                    question=self.question.get() if not self.closed else "")


class Floater:
    def __init__(self):
        self.conf = load_conf()
        self.root = tk.Tk()
        self.root.title(APP)
        if IS_MAC:
            # Mac 上 overrideredirect 常出现不显示 / 点不动，改用原生无边框样式
            try:
                self.root.tk.call("::tk::unsupported::MacWindowStyle", "style",
                                  self.root._w, "plain", "none")
            except tk.TclError:
                self.root.overrideredirect(True)
        else:
            self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.conf["alpha"])
        pick_fonts()

        self.cheer = ""
        self.cheer_state = None
        self.cheer_tick = 0
        self.cheer_bag = []
        self.theme_tick = 0
        self.settings_win = None
        self.frame = self.mini = None

        self.dark = self.want_dark()
        self.build()
        self.place()
        self.bind_events()

        # 联网取汇率和油价放在后台线程，断网也不卡界面
        import threading
        load_live()
        WX_CITY[0] = self.conf.get("city", "on-143")
        self.stop = threading.Event()
        threading.Thread(target=live_worker, args=(self.stop,), daemon=True).start()

        self.pet = Pet(self)
        self._geom = ""

        if self.conf["hourly"] <= 0:
            self.root.after(300, self.open_settings)
        self.root.after(1500, self.announce_update)
        self.tick()

    # ---------- 外观 ----------
    def want_dark(self):
        t = self.conf.get("theme", "auto")
        return system_is_dark() if t == "auto" else t == "dark"

    @property
    def p(self):
        return PALETTES["dark" if self.dark else "light"]

    def rebuild(self):
        self.dark = self.want_dark()
        self.build()
        self.lbl_cheer.configure(text=self.cheer)

    def build(self):
        p = self.p
        for old in (self.frame, self.mini):
            if old is not None:
                old.destroy()
        self.root.configure(bg=p["surface"])
        S = dict(bg=p["surface"])

        # 完整模式
        self.frame = tk.Frame(self.root, padx=18, pady=14, **S)

        head = tk.Frame(self.frame, **S)
        head.pack(fill="x")
        self.lbl_title = tk.Label(head, text="今天已赚", fg=p["text3"], font=(FONT, 9), **S)
        self.lbl_title.pack(side="left")
        self.lbl_state = tk.Label(head, text="", fg=p["text3"], font=(FONT, 9), **S)
        self.lbl_state.pack(side="right")
        self.dot = tk.Canvas(head, width=8, height=8, highlightthickness=0, **S)
        self.dot.pack(side="right", padx=(0, 5))
        self.dot_id = self.dot.create_oval(1, 1, 7, 7, fill=p["text3"], outline="")
        # 猫爪：点一下显示 / 隐藏桌宠（和设置里的“显示宠物”是同一个开关）
        self.paw = paw_icon(head, p["surface"], self.ui_scale())
        self.paw.pack(side="right", padx=(0, 10))
        self.paw.bind("<ButtonRelease-1>", self.on_paw_click)
        self.paw.bind("<Double-Button-1>", lambda _e: "break")
        self.refresh_paw()

        money = tk.Frame(self.frame, **S)
        money.pack(fill="x", pady=(2, 0))
        self.lbl_money = tk.Label(money, text="", fg=p["gold"],
                                  font=(NUM_FONT, 26, "bold"), **S)
        self.lbl_money.pack(side="left")
        self.lbl_unit = tk.Label(money, text="", fg=p["gold"], font=(FONT, 14, "bold"), **S)
        self.lbl_unit.pack(side="left", anchor="s", pady=(0, 6), padx=(4, 0))
        self.lbl_tax = tk.Label(self.frame, text="", fg=p["text3"], font=(FONT, 9),
                                anchor="w", **S)
        self.lbl_tax.pack(fill="x", pady=(0, 8))

        # 进度条：圆头细线，底轨浅灰
        self.bar = tk.Canvas(self.frame, width=1, height=6, highlightthickness=0, **S)
        self.bar.pack(fill="x")
        self.bar_track = self.bar.create_line(3, 3, 3, 3, width=6, capstyle="round",
                                              fill=p["track"])
        self.bar_fill = self.bar.create_line(3, 3, 3, 3, width=6, capstyle="round",
                                             fill=p["bar"])

        info = tk.Frame(self.frame, **S)
        info.pack(fill="x", pady=(10, 0))
        self.lbl_k = tk.Label(info, text="", fg=p["text3"], font=(FONT, 9), **S)
        self.lbl_k.pack(side="left", anchor="s")
        self.lbl_v = tk.Label(info, text="", fg=p["text"], font=(NUM_FONT, 11, "bold"), **S)
        self.lbl_v.pack(side="left", anchor="s", padx=(6, 0))
        self.lbl_pct = tk.Label(info, text="", fg=p["text3"], font=(NUM_FONT, 9), **S)
        self.lbl_pct.pack(side="right", anchor="s")

        # 明日油价：常驻一行，跌用绿、涨用红
        gas = tk.Frame(self.frame, **S)
        gas.pack(fill="x", pady=(6, 0))
        tk.Label(gas, text="明日油价", fg=p["text3"], font=(FONT, 9), **S).pack(
            side="left", anchor="s")
        self.lbl_gas = tk.Label(gas, text="", fg=p["text3"], font=(FONT, 10, "bold"), **S)
        self.lbl_gas.pack(side="left", anchor="s", padx=(6, 0))
        self.lbl_gas_price = tk.Label(gas, text="", fg=p["text3"], font=(FONT, 9), **S)
        self.lbl_gas_price.pack(side="right", anchor="s")

        # 天气：现在 / 下班时（下班后换成今晚）/ 明天
        tk.Frame(self.frame, height=1, bg=p["hairline"]).pack(fill="x", pady=(12, 8))
        self.wx_rows, wx_frames = [], []
        for _ in range(3):
            fr = tk.Frame(self.frame, **S)
            fr.pack(fill="x", pady=(0, 3))
            wx_frames.append(fr)
            k = tk.Label(fr, text="", fg=p["text3"], font=(FONT, 9), width=5, anchor="w", **S)
            k.pack(side="left", anchor="s")
            v = tk.Label(fr, text="", fg=p["text"], font=(FONT, 10), **S)
            v.pack(side="left", anchor="s")
            r = tk.Label(fr, text="", fg=p["text3"], font=(FONT, 9), **S)
            r.pack(side="right", anchor="s")
            self.wx_rows.append((k, v, r))
        # 日出日落：线条图标 + 时间
        sun = tk.Frame(self.frame, **S)
        sun.pack(fill="x", pady=(1, 0))
        self.sun_icons, self.sun_labels = [], []
        for i, up in enumerate((True, False)):
            cv = sun_icon(sun, up, p["text2"], p["surface"], self.ui_scale())
            cv.pack(side="left", padx=(0 if i == 0 else 18, 5))
            lb = tk.Label(sun, text="", fg=p["text"], font=(NUM_FONT, 10), **S)
            lb.pack(side="left")
            self.sun_icons.append(cv)
            self.sun_labels.append(lb)

        # 四个入口分成两行，两列共享标题和操作的对齐位置，不占用天气空间。
        fb = tk.Frame(self.frame, **S)
        fb.pack(fill="x", pady=(8, 0))
        fb.grid_columnconfigure(0, weight=1, uniform="入口")
        fb.grid_columnconfigure(1, weight=1, uniform="入口")

        def entrance(row, col, title, value, callback, size=10):
            cell = tk.Frame(fb, cursor="hand2", **S)
            cell.grid(row=row, column=col, sticky="nsew", padx=(0, 10) if col == 0 else 0,
                      pady=(0, 4))
            cell.grid_columnconfigure(0, minsize=round(40 * self.ui_scale()))
            caption = tk.Label(cell, text=title, fg=p["text3"], font=(FONT, 9),
                               cursor="hand2", anchor="w", **S)
            caption.grid(row=0, column=0, sticky="nw")
            action = tk.Label(cell, text=value, fg=p["accent"], font=(FONT, size, "bold"),
                              cursor="hand2", anchor="w", justify="left",
                              wraplength=round(70 * self.ui_scale()), **S)
            action.grid(row=0, column=1, sticky="nw", padx=(4, 0))
            for widget in (cell, caption, action):
                widget.bind("<ButtonRelease-1>", callback)
                widget.bind("<Double-Button-1>", lambda _e: "break")
            return caption, action

        self.fortune_title, self.fortune_lv = entrance(0, 0, "今日签", "", self.on_fortune_click, 11)
        self.tarot_title, self.tarot_lv = entrance(0, 1, "塔罗牌", "抽牌 ›", self.on_tarot_click)
        _, self.lunch_lv = entrance(1, 0, "午饭", "转一转 ›",
                                   lambda e: self.on_toy_click(e, self.open_lunch))
        entrance(1, 1, "圣杯", "掷一掷 ›", lambda e: self.on_toy_click(e, self.open_jiao))
        self.refresh_lunch_entry()
        self.fortune_anim = False
        self.refresh_fortune()

        tk.Frame(self.frame, height=1, bg=p["hairline"]).pack(fill="x", pady=(9, 10))
        self.lbl_cheer = tk.Label(self.frame, text="", fg=p["text2"], font=(FONT, 9),
                                  anchor="w", justify="left", wraplength=250, **S)
        self.lbl_cheer.pack(fill="x")

        # 迷你模式：左边金色的钱，右边绿色的倒计时，进度条贴底边、通宽
        self.mini = tk.Frame(self.root, **S)
        row = tk.Frame(self.mini, padx=14, pady=7, **S)
        row.pack(fill="x")
        self.mini_money = tk.Label(row, text="", fg=p["gold"],
                                   font=(NUM_FONT, 15, "bold"), **S)
        self.mini_money.pack(side="left")
        self.mini_unit = tk.Label(row, text="", fg=p["gold"], font=(FONT, 10, "bold"), **S)
        self.mini_unit.pack(side="left", anchor="s", pady=(0, 3), padx=(2, 0))
        self.mini_time = tk.Label(row, text="", fg=p["green"],
                                  font=(NUM_FONT, 15, "bold"), **S)
        self.mini_time.pack(side="left", padx=(8, 0))
        self.mini_gas = tk.Label(row, text="", fg=p["text3"], font=(FONT, 10, "bold"), **S)
        self.mini_gas.pack(side="left", padx=(8, 0))
        # width=1：画布默认约 380px 宽会把窗口撑大，改成跟着文字宽度走
        self.mini_bar = tk.Canvas(self.mini, width=1, height=3, bg=p["track"],
                                  highlightthickness=0)
        self.mini_bar.pack(fill="x", side="bottom")
        self.mini_bar_fill = self.mini_bar.create_rectangle(0, 0, 0, 3, fill=p["bar"], width=0)

        self.apply_mini()
        win11_round(self.root, p["border"])

    def apply_mini(self):
        if self.conf["mini"]:
            self.frame.pack_forget()
            self.mini.pack(fill="both", expand=True)
            self.root.minsize(1, 1)
        else:
            self.mini.pack_forget()
            self.frame.pack(fill="both", expand=True)
            self.root.minsize(286, 0)
        self.root.geometry("")  # 按内容重新计算大小

    def place(self):
        self.root.update_idletasks()
        x, y = self.conf["x"], self.conf["y"]
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if x is None or y is None or not (0 <= x < sw - 40 and 0 <= y < sh - 40):
            x, y = sw - self.root.winfo_reqwidth() - 30, 80
        self.root.geometry(f"+{x}+{y}")

    def bind_events(self):
        # 绑在根窗口上，悬浮窗里所有子控件都会触发（bindtags 含顶层窗口）
        w = self.root
        w.bind("<ButtonPress-1>", self.drag_start)
        w.bind("<B1-Motion>", self.drag_move)
        w.bind("<ButtonRelease-1>", self.drag_end)
        w.bind("<Double-Button-1>", self.toggle_mini)
        w.bind("<Button-3>", self.show_menu)
        if IS_MAC:
            # Mac 的 Tk 8.6 右键是 Button-2（Tk 9 起改成 Button-3）；再加 Ctrl+点击
            w.bind("<Button-2>", self.show_menu)
            w.bind("<Control-Button-1>", self.show_menu)

        self.menu = tk.Menu(self.root, tearoff=0, font=(FONT, 10))
        self.menu.add_command(label="设置…", command=self.open_settings)
        self.menu.add_command(label="塔罗牌…", command=self.open_tarot)
        self.menu.add_command(label="午饭吃什么…", command=self.open_lunch)
        self.menu.add_command(label="赛博圣杯…", command=self.open_jiao)
        self.menu.add_command(label="迷你模式 / 完整模式", command=self.toggle_mini)
        self.autostart_var = tk.BooleanVar(value=autostart_enabled())
        self.menu.add_checkbutton(label="开机自启", variable=self.autostart_var,
                                  command=lambda: set_autostart(self.autostart_var.get()))
        self.menu.add_separator()
        self.menu.add_command(label=f"检查更新（当前 v{VERSION}）", command=self.manual_update)
        self.menu.add_command(label="更新记录…", command=self.show_changelog)
        self.menu.add_command(label="退出", command=self.quit)

    def flash(self, msg):
        """借鼓励语那一行临时显示一句话（15 秒）。"""
        self.cheer = msg
        self.lbl_cheer.configure(text=msg)
        self.cheer_tick = 0

    def manual_update(self):
        import threading
        UPD["msg"] = "正在检查更新…"
        threading.Thread(target=check_and_update, args=(True,), daemon=True).start()

    def restart(self):
        """换成新版后重启自己。"""
        import subprocess
        self.conf["x"], self.conf["y"] = self.root.winfo_x(), self.root.winfo_y()
        save_conf(self.conf)
        subprocess.Popen([sys.executable, os.path.abspath(__file__)],
                         cwd=os.path.dirname(os.path.abspath(__file__)))
        self.stop.set()
        self.root.destroy()

    def drag_start(self, e):
        self._press = (e.x_root, e.y_root)
        self._dx = e.x_root - self.root.winfo_x()
        self._dy = e.y_root - self.root.winfo_y()

    def drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")
        if getattr(self, "pet", None):
            self.pet.follow()

    def drag_end(self, _e):
        self.conf["x"], self.conf["y"] = self.root.winfo_x(), self.root.winfo_y()
        save_conf(self.conf)

    def refresh_paw(self):
        on = self.conf.get("pet_on", True)
        self.paw.itemconfigure("paw", fill=self.p["text2"] if on else self.p["track"])

    def on_paw_click(self, e):
        px, py = getattr(self, "_press", (e.x_root, e.y_root))
        if abs(e.x_root - px) > 4 or abs(e.y_root - py) > 4:
            return  # 是在拖窗口
        if not os.path.exists(os.path.join(PET_DIR, "manifest.json")):
            self.flash("还没有导入宠物素材：右键 → 设置 → 宠物 → 导入素材")
            return
        self.conf["pet_on"] = not self.conf.get("pet_on", True)
        save_conf(self.conf)
        self.pet.set_visible(self.conf["pet_on"], anim=True)
        self.refresh_paw()
        self.flash("宠物已显示" if self.conf["pet_on"] else "宠物已隐藏，点猫爪再叫它回来")

    def toggle_mini(self, _e=None):
        self.conf["mini"] = not self.conf["mini"]
        save_conf(self.conf)
        self.apply_mini()

    def show_menu(self, e):
        self.autostart_var.set(autostart_enabled())
        self.menu.tk_popup(e.x_root, e.y_root)

    def quit(self):
        self.conf["x"], self.conf["y"] = self.root.winfo_x(), self.root.winfo_y()
        save_conf(self.conf)
        self.stop.set()
        self.root.destroy()

    # ---------- 刷新 ----------
    def tick(self):
        # 跟随系统时，每 5 秒看一次系统深浅色有没有切换
        self.theme_tick += 1
        if self.theme_tick >= 25:
            self.theme_tick = 0
            if self.want_dark() != self.dark:
                self.rebuild()
        try:
            self.refresh()
        except Exception as ex:  # 配置坏了也不要崩
            self.lbl_money.configure(text="配置有误")
            self.lbl_k.configure(text=str(ex)[:40])

        # 更新消息借用鼓励语那一行显示 15 秒
        if UPD["msg"]:
            self.cheer, UPD["msg"] = UPD["msg"], ""
            self.lbl_cheer.configure(text=self.cheer)
            self.cheer_tick = 0
        # 新版已经换好：设置窗口没开着就重启（给 3 秒看到提示）
        if UPD["ready"] and not (self.settings_win and self.settings_win.winfo_exists()):
            UPD["ready_ticks"] = UPD.get("ready_ticks", 0) + 1
            if UPD["ready_ticks"] >= 15:
                self.restart()
                return
        self.root.after(200, self.tick)

    def refresh(self):
        c, p = self.conf, self.p
        r = compute(c, dt.datetime.now())
        st, prog = r["state"], r["progress"]
        # 税后：按 2026 年安省税率估出的平均扣除比例
        nf = net_factor(c)
        gross_earned = r["earned"]
        r["earned"] *= nf
        r["total"] *= nf
        if getattr(self, "pet", None):
            self.pet.update(r, st, c)
            geom = self.root.winfo_geometry()
            if geom != self._geom:
                self._geom = geom
                self.pet.follow()
        if nf < 1:
            self.lbl_title.configure(text="今天已赚（税后）")
            self.lbl_tax.configure(text=f"税前 {fmt_money(c, gross_earned)} · 扣除约 {(1 - nf) * 100:.1f}%")
        else:
            self.lbl_title.configure(text={"gross": "今天已赚（税前）", "cash": "今天已赚（现金）"}.get(
                tax_mode(c), "今天已赚"))
            self.lbl_tax.configure(text="")

        # 完整模式
        num, unit = split_unit(fmt_money(c, r["earned"]))
        self.lbl_money.configure(text=num)
        self.lbl_unit.configure(text=unit)
        w = self.bar.winfo_width()
        self.bar.coords(self.bar_track, 3, 3, max(3, w - 3), 3)
        self.bar.coords(self.bar_fill, 3, 3, 3 + max(0, w - 6) * prog, 3)
        self.bar.itemconfigure(self.bar_fill, state="normal" if prog > 0 else "hidden")

        if st == "work":
            state, k, v, pct = "上班中", "距下班", fmt_dur(r["remain"]), f"{prog * 100:.1f}%"
        elif st == "before":
            state, k, v, pct = "未上班", "距上班", fmt_dur(r["remain"]), \
                f"今天可赚 {fmt_money(c, r['total'])}"
        elif st == "after":
            state, k, v, pct = "已下班", "今天到手", fmt_money(c, r["total"]), ""
        else:
            state, k, v, pct = "休息日", "今天不上班", "", ""
        self.lbl_state.configure(text=state)
        self.dot.itemconfigure(self.dot_id, fill=p["bar"] if st == "work" else p["text3"])
        self.lbl_k.configure(text=k)
        self.lbl_v.configure(text=v, font=(FONT if has_cjk(v) else NUM_FONT, 11, "bold"))
        self.lbl_pct.configure(text=pct, font=(FONT if has_cjk(pct) else NUM_FONT, 9))

        # 迷你模式
        self.mini_money.configure(text=num)
        self.mini_unit.configure(text=unit)
        t = {"after": "已下班", "off": "休息日"}.get(st) or fmt_dur(r["remain"])
        self.mini_time.configure(text=t, font=(FONT if has_cjk(t) else NUM_FONT, 15, "bold"))
        mw = self.mini_bar.winfo_width()
        self.mini_bar.coords(self.mini_bar_fill, 0, 0, mw * prog, 3)

        # 明日油价涨跌
        tm, today_price = gas_tomorrow(), gas_today()
        if tm:
            chg, price = tm
            n = f"{abs(chg):g}"
            word, mini, color = ("不变", "油→", p["text3"]) if chg == 0 else \
                (f"↓ 跌 {n} 分", f"油↓{n}", p["green"]) if chg < 0 else \
                (f"↑ 涨 {n} 分", f"油↑{n}", p["up"])
            self.lbl_gas.configure(text=word, fg=color)
            self.lbl_gas_price.configure(text=f"{today_price:g} → {price:g} ¢/升")
            self.mini_gas.configure(text=mini, fg=color)
        else:
            self.lbl_gas.configure(text="待公布" if today_price else "获取中…", fg=p["text3"])
            self.lbl_gas_price.configure(text=f"今日 {today_price:g} ¢/升" if today_price else "")
            self.mini_gas.configure(text="")

        # 天气
        wx_tags = self.refresh_wx(c, st)
        self.refresh_fortune()
        self.refresh_lunch_entry()

        # 鼓励语：状态变了立刻换，否则每 CHEER_EVERY_SEC 秒换一句；
        # 同一组洗牌后轮流出，整组说完才会重复。上班 / 没上班时混进天气相关的句子
        if st == "work":
            bucket = "early" if prog < .25 else "mid" if prog < .5 else \
                "late" if prog < .9 else "final"
        else:
            bucket = st
        self.cheer_tick += 1
        if bucket != self.cheer_state or self.cheer_tick >= CHEER_EVERY_SEC * 5:
            if bucket != self.cheer_state or not self.cheer_bag:
                pool = list(CHEERS[bucket])
                if st in ("work", "before"):
                    for tag in wx_tags:
                        pool += CHEERS[tag]
                self.cheer_bag = [s for s in pool if s != self.cheer]
                random.shuffle(self.cheer_bag)
            self.cheer_state, self.cheer_tick = bucket, 0
            self.cheer = self.cheer_bag.pop()
            self.lbl_cheer.configure(text=self.cheer)

    def ui_scale(self):
        """画布按 DPI 缩放（Tk 的字体会自动放大，画布坐标不会）。"""
        try:
            return float(self.root.tk.call("tk", "scaling")) / (96 / 72)
        except Exception:
            return 1.0

    def show_sun(self, rise, sset):
        for cv, lb, t in zip(self.sun_icons, self.sun_labels, (rise, sset)):
            lb.configure(text=t or "")
            for item in cv.find_all():
                cv.itemconfigure(item, state="normal" if t else "hidden")

    def refresh_wx(self, c, st):
        """更新三行天气，返回要混进鼓励语的天气标签（rain / snow / cold / hot）。"""
        p, wx = self.p, LIVE.get("wx")
        rows = self.wx_rows
        if not wx or wx.get("city") != c.get("city", "on-143"):
            texts = [("天气", "获取中…", ""), ("", "", ""), ("", "", "")]
            self.show_sun(None, None)
            for (k, v, r), (a, b, d) in zip(rows, texts):
                k.configure(text=a), v.configure(text=b, fg=p["text3"]), r.configure(text=d)
            return []

        now = dt.datetime.now()

        def icon(cond, when):
            kind = wx_kind(cond)
            night = when.hour >= 18 or when.hour < 6
            return "☾" if night and kind in ("sun", "partly") else WX_ICON[kind]

        def deg(t):
            return "—" if t is None else f"{round(t)}°"

        def span(hi, lo):
            if hi is not None and lo is not None:
                return f"{round(min(hi, lo))}–{round(max(hi, lo))}°"
            return deg(hi if hi is not None else lo)

        texts, tags = [], []
        # 1. 现在
        today = wx_day(0)
        warn = "⚠ 有天气警告" if wx.get("warnings") else ""
        texts.append(("现在", f"{icon(wx['now_c'], now)} {deg(wx['now_t'])} {wx_zh(wx['now_c'])}",
                      warn or (f"今天 {span(today[0], today[1])}" if today else ""), bool(warn)))
        # 2. 下班时（还没下班）/ 今晚（已下班或休息日）
        end = dt.datetime.combine(now.date(), parse_hm(c["end"]))
        h = wx_at(end) if st in ("before", "work") else None
        if h:
            rainy = wx_kind(h["c"]) in ("rain", "mix", "thunder", "snow") or h["pop"] >= 40
            texts.append(("下班", f"{icon(h['c'], end)} {deg(h['t'])} {wx_zh(h['c'])}",
                          f"降水 {h['pop']}%" + ("，带伞" if rainy else ""), False))
            if rainy:
                tags.append("snow" if wx_kind(h["c"]) == "snow" else "rain")
        else:
            night = next((f for f in wx["daily"] if f["name"] == "Tonight"), None)
            texts.append(("今晚", f"{icon(night['c'], end.replace(hour=21))} "
                                  f"{deg(night['t'])} {wx_zh(night['c'])}" if night else "—",
                          "", False))
        # 3. 明天
        tm = wx_day(1)
        texts.append(("明天", f"{icon(tm[2], now.replace(hour=12))} {span(tm[0], tm[1])} "
                              f"{wx_zh(tm[2])}" if tm else "—", "", False))

        # 日出日落（只用今天的数据）
        rise, sset = wx.get("sunrise", ""), wx.get("sunset", "")
        if rise[:10] == sset[:10] == now.date().isoformat():
            self.show_sun(rise[11:], sset[11:])
        else:
            self.show_sun(None, None)

        for (k, v, r), (a, b, d, alert) in zip(rows, texts):
            k.configure(text=a)
            v.configure(text=b, fg=p["text"])
            r.configure(text=d, fg=p["danger"] if alert else p["text3"])

        if wx["now_t"] is not None:
            if wx["now_t"] <= -5:
                tags.append("cold")
            elif wx["now_t"] >= 28:
                tags.append("hot")
        return tags

    # ---------- 今日签 ----------
    def fortune_color(self, level):
        p = self.p
        return {"大吉": p["gold"], "中吉": p["gold"], "末吉": p["text2"], "凶": p["up"]}.get(
            level, p["text"])

    def refresh_fortune(self):
        if self.fortune_anim:
            return
        today = dt.date.today()
        if self.conf.get("fortune_day") == today.isoformat():
            lv = fortune_for(today)["level"]
            self.fortune_lv.configure(text=lv, fg=self.fortune_color(lv))
        else:
            self.fortune_lv.configure(text="点我抽签", fg=self.p["accent"])

    def on_fortune_click(self, e):
        px, py = getattr(self, "_press", (e.x_root, e.y_root))
        if abs(e.x_root - px) > 4 or abs(e.y_root - py) > 4 or self.fortune_anim:
            return  # 是在拖窗口，或者正在摇签
        today = dt.date.today()
        if self.conf.get("fortune_day") == today.isoformat():
            self.show_fortune_card()
            return
        # 摇签动画：等级名快速跳动，越来越慢，最后停在今天的签上
        self.fortune_anim = True
        names = [x[0] for x in FORTUNE_LEVELS]
        delays = [50] * 8 + [80] * 4 + [130, 180, 240]

        def step(i=0):
            if i < len(delays):
                self.fortune_lv.configure(text=random.choice(names), fg=self.p["text3"])
                self.root.after(delays[i], step, i + 1)
                return
            self.fortune_anim = False
            self.conf["fortune_day"] = today.isoformat()
            save_conf(self.conf)
            if getattr(self, "pet", None):
                self.pet.react_fortune(fortune_for(today)["level"])
            self.refresh_fortune()
            self.root.after(250, self.show_fortune_card)

        step()

    def show_fortune_card(self):
        if getattr(self, "fortune_win", None) and self.fortune_win.winfo_exists():
            self.fortune_win.lift()
            return
        p, today = self.p, dt.date.today()
        f = fortune_for(today)
        win = tk.Toplevel(self.root, bg=p["ground"])
        self.fortune_win = win
        win.title("今日签")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win_dark_titlebar(win, self.dark)
        S, G = dict(bg=p["surface"]), dict(bg=p["ground"])
        color = self.fortune_color(f["level"])

        body = tk.Frame(win, padx=20, pady=14, **G)
        body.pack(fill="both")
        tk.Label(body, text=f"{today.month} 月 {today.day} 日 · 周{'一二三四五六日'[today.weekday()]}",
                 fg=p["text3"], font=(FONT, 9), **G).pack(anchor="w", padx=4, pady=(0, 6))

        card = tk.Frame(body, padx=20, pady=16, highlightthickness=1,
                        highlightbackground=p["border"], **S)
        card.pack(fill="x")
        tk.Label(card, text=f["level"], fg=color, font=(FONT, 30, "bold"), **S).pack()
        tk.Label(card, text=f["text"], fg=p["text"], font=(FONT, 11), wraplength=int(280 * self.ui_scale()),
                 justify="center", **S).pack(pady=(2, 12))

        tk.Frame(card, height=1, bg=p["hairline"]).pack(fill="x")
        sc = tk.Frame(card, pady=10, **S)
        sc.pack(fill="x")
        tk.Label(sc, text="打工指数", fg=p["text3"], font=(FONT, 9), **S).pack(side="left")
        tk.Label(sc, text=str(f["score"]), fg=p["text"], font=(NUM_FONT, 12, "bold"),
                 **S).pack(side="left", padx=(6, 10))
        bar = tk.Canvas(sc, width=1, height=6, highlightthickness=0, **S)
        bar.pack(side="left", fill="x", expand=True)

        def draw_bar(_e=None):
            w = bar.winfo_width()
            bar.delete("all")
            bar.create_line(3, 3, max(3, w - 3), 3, width=6, capstyle="round", fill=p["track"])
            bar.create_line(3, 3, 3 + max(0, w - 6) * f["score"] / 100, 3, width=6,
                            capstyle="round", fill=color if f["level"] != "吉" else p["bar"])
        bar.bind("<Configure>", draw_bar)

        tk.Frame(card, height=1, bg=p["hairline"]).pack(fill="x")
        yj = tk.Frame(card, pady=10, **S)
        yj.pack(fill="x")
        for col, (word, items, c2) in enumerate((("宜", f["yi"], p["green"]),
                                                 ("忌", f["ji"], p["up"]))):
            fr = tk.Frame(yj, **S)
            fr.grid(row=0, column=col, sticky="nw", padx=(0, 24) if col == 0 else 0)
            tk.Label(fr, text=word, fg=c2, font=(FONT, 12, "bold"), **S).pack(anchor="w")
            for it in items:
                tk.Label(fr, text=it, fg=p["text"], font=(FONT, 10), **S).pack(anchor="w")
        yj.grid_columnconfigure(0, weight=1)
        yj.grid_columnconfigure(1, weight=1)

        foot = tk.Frame(body, pady=10, **G)
        foot.pack(fill="x")
        tk.Label(foot, text="每天一签，明天再来", fg=p["text3"], font=(FONT, 9),
                 **G).pack(side="left", padx=4)
        PillButton(foot, "好的", p["accent"], p["on_accent"], win.destroy, p["ground"],
                   (FONT, 10)).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Return>", lambda _e: win.destroy())

        # 放在悬浮窗旁边：左边放得下就放左边，否则放右边
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.root.winfo_x() - w - 12
        if x < 0:
            x = self.root.winfo_x() + self.root.winfo_width() + 12
        y = max(0, min(self.root.winfo_y(), win.winfo_screenheight() - h - 60))
        win.geometry(f"+{x}+{y}")

    # ---------- 塔罗牌 ----------
    def on_tarot_click(self, e):
        px, py = getattr(self, "_press", (e.x_root, e.y_root))
        if abs(e.x_root - px) > 4 or abs(e.y_root - py) > 4:
            return  # 是在拖窗口
        self.open_tarot()

    def open_tarot(self):
        """重复打开只唤起已有牌桌，保留这一次的选择。"""
        if getattr(self, "tarot_win", None) and self.tarot_win.winfo_exists():
            self.tarot_win.deiconify()
            self.tarot_win.lift()
            return
        tarot_start_download()
        self.tarot_table = TarotTable(self)
        self.tarot_win = self.tarot_table.win

    def tarot_submit(self, question=None):
        """截图钩子：填写问题并确认；洗牌结束后进入选牌。"""
        if getattr(self, "tarot_win", None) and self.tarot_win.winfo_exists():
            self.tarot_table.submit(question)

    def tarot_mode(self, mode):
        """截图钩子：在模式选择页进入 daily（今日运势）或 question（提问）。"""
        if getattr(self, "tarot_win", None) and self.tarot_win.winfo_exists():
            self.tarot_table.choose_mode(mode)

    def tarot_topic(self, topic, question=None):
        """截图钩子：选主题页或今日结果页选择主题，可填写自定义问题。"""
        if getattr(self, "tarot_win", None) and self.tarot_win.winfo_exists():
            self.tarot_table.select_topic(topic, question)

    def tarot_start(self):
        """截图钩子：在选主题页点「开始洗牌」；自定义问题为空时不开始。"""
        if getattr(self, "tarot_win", None) and self.tarot_win.winfo_exists():
            self.tarot_table.start_daily()

    def tarot_pick(self, i):
        """截图钩子：选铺牌中的第 i 张（从 0 开始）；再点一次撤回。"""
        if getattr(self, "tarot_win", None) and self.tarot_win.winfo_exists():
            self.tarot_table.pick(i)

    def tarot_hover(self, i):
        """截图钩子：突出第 i 张待选牌（从 0 开始）；None 清除悬停。"""
        if getattr(self, "tarot_win", None) and self.tarot_win.winfo_exists():
            self.tarot_table.set_hover(i)

    def tarot_confirm(self):
        """截图钩子：选满当前模式所需张数后翻牌（今日一张，提问三张）。"""
        if getattr(self, "tarot_win", None) and self.tarot_win.winfo_exists():
            self.tarot_table.confirm()

    # ---------- 版本信息 / 更新记录 ----------
    def show_changelog(self):
        if getattr(self, "changelog_win", None) and self.changelog_win.winfo_exists():
            self.changelog_win.lift()
            return
        p = self.p
        win = tk.Toplevel(self.root, bg=p["ground"])
        self.changelog_win = win
        win.title("更新记录")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win_dark_titlebar(win, self.dark)
        G = dict(bg=p["ground"])
        body = tk.Frame(win, padx=20, pady=16, **G)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=APP, fg=p["text3"], font=(FONT, 9), **G).pack(anchor="w")
        tk.Label(body, text=f"当前版本 v{VERSION}", fg=p["text"], font=(FONT, 16, "bold"),
                 **G).pack(anchor="w", pady=(2, 10))

        # 按字换行：按词换行时 Tk 把整串中文当一个词，圆点会单独占一行
        txt = tk.Text(body, width=46, height=22, wrap="char", relief="flat", bd=0,
                      padx=16, pady=12, bg=p["surface"], fg=p["text"], font=(FONT, 10),
                      highlightthickness=1, highlightbackground=p["border"],
                      highlightcolor=p["border"], cursor="arrow", spacing1=2, spacing3=2)
        txt.pack(fill="both", expand=True)
        txt.tag_configure("ver", font=(FONT, 11, "bold"), foreground=p["text"], spacing1=10)
        txt.tag_configure("cur", foreground=p["accent"])
        txt.tag_configure("date", font=(NUM_FONT, 9), foreground=p["text3"])
        txt.tag_configure("item", lmargin1=4, lmargin2=18, foreground=p["text2"])
        for i, (ver, day, items) in enumerate(CHANGELOG):
            tags = ("ver", "cur") if ver == VERSION else ("ver",)
            txt.insert("end", f"v{ver}", tags)
            txt.insert("end", f"   {day}" + ("  · 当前" if ver == VERSION else "") + "\n", "date")
            for it in items:
                txt.insert("end", f"•  {it}\n", "item")
        txt.configure(state="disabled")  # 只读；滚轮照常能滚

        foot = tk.Frame(body, pady=12, **G)
        foot.pack(fill="x")
        tk.Label(foot, text="新版会自动下载，右键“检查更新”可以马上更新", fg=p["text3"],
                 font=(FONT, 9), **G).pack(side="left")
        PillButton(foot, "好的", p["accent"], p["on_accent"], win.destroy, p["ground"],
                   (FONT, 10)).pack(side="right")
        win.bind("<Escape>", lambda _e: win.destroy())

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.root.winfo_x() - w - 12
        if x < 0:
            x = self.root.winfo_x() + self.root.winfo_width() + 12
        y = max(0, min(self.root.winfo_y(), win.winfo_screenheight() - h - 60))
        win.geometry(f"+{x}+{y}")

    def announce_update(self):
        """自动更新后第一次打开：在鼓励语那一行说一声更新了什么。"""
        seen = self.conf.get("seen_version")
        if seen != VERSION:
            self.conf["seen_version"] = VERSION
            save_conf(self.conf)
            if seen and vtuple(seen) < vtuple(VERSION):
                self.flash(f"已更新到 v{VERSION}，右键 → 更新记录 看看新内容")

    # ---------- 午饭转盘 / 赛博圣杯 ----------
    def on_toy_click(self, event, action):
        px, py = getattr(self, "_press", (event.x_root, event.y_root))
        if abs(event.x_root - px) <= 4 and abs(event.y_root - py) <= 4:
            action()

    def refresh_lunch_entry(self):
        pick = lunch_today(self.conf)
        # 长名字截短，入口保持一行，不把悬浮窗撑高
        self.lunch_lv.configure(text=(pick if len(pick) <= 5 else pick[:4] + "…") if pick
                                else "转一转 ›")

    def open_lunch(self):
        if getattr(self, "lunch_win", None) and self.lunch_win.winfo_exists():
            self.lunch_win.deiconify()
            self.lunch_win.lift()
            return
        self.lunch_table = LunchWheel(self)

    def lunch_spin_now(self):
        if getattr(self, "lunch_win", None) and self.lunch_win.winfo_exists():
            self.lunch_table.spin()

    def lunch_edit(self):
        if getattr(self, "lunch_win", None) and self.lunch_win.winfo_exists():
            self.lunch_table.edit()

    def open_jiao(self):
        if getattr(self, "jiao_win", None) and self.jiao_win.winfo_exists():
            self.jiao_win.deiconify()
            self.jiao_win.lift()
            return
        self.jiao_table = JiaoTable(self)

    def jiao_throw_now(self):
        if getattr(self, "jiao_win", None) and self.jiao_win.winfo_exists():
            self.jiao_table.throw()

    def jiao_set_streak(self, enabled):
        if getattr(self, "jiao_win", None) and self.jiao_win.winfo_exists():
            self.jiao_table.set_streak(enabled)

    def toy_state(self):
        """截图与断言钩子：返回两个玩具各自的状态、结果和模式进度。"""
        return {key: getattr(self, key + "_table").snapshot()
                if getattr(self, key + "_table", None) else None for key in ("lunch", "jiao")}

    # ---------- 设置窗口 ----------
    def open_settings(self):
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        c, p = self.conf, self.p
        win = tk.Toplevel(self.root, bg=p["ground"])
        self.settings_win = win
        win.title(f"{APP} - 设置")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win_dark_titlebar(win, self.dark)

        body = tk.Frame(win, bg=p["ground"], padx=20, pady=8)
        body.pack(fill="both")
        S = dict(bg=p["surface"])
        G = dict(bg=p["ground"])

        # 分页：顶部分段切换（收入 / 时间 / 其他），底部按钮固定
        PAGES = ["收入", "时间", "宠物", "其他"]
        seg = tk.Frame(body, bg=p["track"], padx=2, pady=2)
        seg.pack(pady=(6, 2))
        holder = tk.Frame(body, **G)
        holder.pack(fill="x")
        pages = {n: tk.Frame(holder, **G) for n in PAGES}
        seg_btns = {}
        page = [pages["收入"]]  # group() 往这一页里放

        def show_page(name):
            for n, fr in pages.items():
                fr.pack_forget()
                on = n == name
                seg_btns[n].configure(bg=p["surface"] if on else p["track"],
                                      fg=p["text"] if on else p["text2"],
                                      font=(FONT, 10, "bold" if on else "normal"))
            pages[name].pack(fill="both", expand=True)

        for n in PAGES:
            b = tk.Label(seg, text=n, padx=22, pady=4, cursor="hand2")
            b.pack(side="left", padx=1)
            b.bind("<Button-1>", lambda _e, n=n: show_page(n))
            seg_btns[n] = b

        def group(caption, hint=None):
            """一组设置 = 小标题 + 一块白色面板（行与行之间细线分隔）。"""
            body = page[0]
            tk.Label(body, text=caption, fg=p["text3"], font=(FONT, 9), anchor="w",
                     **G).pack(fill="x", pady=(12, 5), padx=4)
            panel = tk.Frame(body, highlightthickness=1, highlightbackground=p["border"], **S)
            panel.pack(fill="x")
            panel.hint = None
            if hint is not None:
                panel.hint = tk.Label(body, text=hint, fg=p["text3"], font=(FONT, 8),
                                      anchor="w", justify="left", wraplength=330, **G)
                panel.hint.pack(fill="x", pady=(5, 0), padx=4)
            panel.rows = 0
            return panel

        def row(panel, label):
            if panel.rows:
                tk.Frame(panel, height=1, bg=p["hairline"]).pack(fill="x", padx=(14, 0))
            panel.rows += 1
            fr = tk.Frame(panel, padx=14, pady=7, **S)
            fr.pack(fill="x")
            tk.Label(fr, text=label, fg=p["text"], font=(FONT, 10), **S).pack(side="left")
            return fr

        def entry(fr, val, width=12):
            e = tk.Entry(fr, width=width, font=(FONT, 10), justify="right", relief="flat",
                         bg=p["input"], fg=p["text"], insertbackground=p["text"],
                         highlightthickness=1, highlightbackground=p["input"],
                         highlightcolor=p["accent"])
            e.insert(0, val)
            e.pack(side="right", ipady=3)
            return e

        def option(fr, var, names, command=None):
            om = tk.OptionMenu(fr, var, *names, command=command)
            om.configure(font=(FONT, 10), width=9, relief="flat", bd=0, indicatoron=False,
                         bg=p["input"], fg=p["text"], activebackground=p["track"],
                         activeforeground=p["text"], highlightthickness=0, cursor="hand2")
            om["menu"].configure(font=(FONT, 10))
            om.pack(side="right")
            return om

        entries = {}

        # 收入
        g = group("收入", "")
        entries["hourly"] = entry(row(g, "时薪（加元）"), str(c["hourly"] or ""))
        fx_val = float(c.get("fx", 1) or 1)
        custom = {"fx": str(int(fx_val) if fx_val.is_integer() else fx_val),
                  "currency": c.get("currency", "$")}  # 自定义的值，切走再切回来还在
        display_var = tk.StringVar(value=DISPLAY_BY_CODE[display_code(c)][1])

        def set_entry(key, v, editable):
            e = entries[key]
            e.configure(state="normal")
            e.delete(0, "end")
            e.insert(0, v)
            e.configure(state="normal" if editable else "readonly")

        def pick_display(name):
            code = DISPLAY_BY_NAME[name][0]
            if code == "custom":
                set_entry("fx", custom["fx"], True)
                set_entry("currency", custom["currency"], True)
                hint = "自定义：显示金额 = 实际金额 × 汇率，不联网"
            elif code == "GAS":
                price = gas_today()
                set_entry("fx", f"{price:g} ¢/升" if price else "获取中…", False)
                set_entry("currency", "升", False)
                hint = "按大多伦多当天平均油价，把钱换算成能加多少升普通汽油；" \
                       "油价来自 CityNews（En-Pro 每日预测）"
            else:
                set_entry("fx", fmt_rate(fx_rate(code)), False)
                set_entry("currency", DISPLAY_BY_CODE[code][2], False)
                try:
                    from email.utils import parsedate_to_datetime
                    d = parsedate_to_datetime(LIVE.get("fx_updated", ""))
                    when = f"（{d.month} 月 {d.day} 日更新）"
                except Exception:
                    when = "（还没联网，先用大概值）"
                hint = f"实时汇率，1 加元 = {fmt_rate(fx_rate(code))} {name}{when}"
            g.hint.configure(text=hint)

        def remember_custom(_e=None):
            if DISPLAY_BY_NAME[display_var.get()][0] == "custom":
                custom["fx"], custom["currency"] = entries["fx"].get(), entries["currency"].get()

        option(row(g, "显示成"), display_var, [d[1] for d in DISPLAYS], pick_display)
        income_group = g
        entries["fx"] = entry(row(g, "汇率"), "")
        entries["currency"] = entry(row(g, "货币符号"), "")
        for key in ("fx", "currency"):
            entries[key].configure(readonlybackground=p["surface"])
            entries[key].bind("<KeyRelease>", remember_custom)
        pick_display(display_var.get())

        # 税：默认按税后显示（2026 年安省税率估算）
        g = group("税", "")
        tax_names = dict(TAX_MODES)
        tax_var = tk.StringVar(value=tax_names[tax_mode(c)])
        tax_group = g

        def tax_hint(_e=None):
            mode = next(k for k, n in TAX_MODES if n == tax_var.get())
            if mode == "cash":
                tax_group.hint.configure(text="现金工资发的时候没有预先扣税，所以按全额显示。"
                                              "但现金收入仍然是应税收入，每年报税时要申报")
                return
            if mode == "gross":
                tax_group.hint.configure(text="按税前全额显示，不扣税")
                return
            try:
                tmp = dict(c, hourly=float(entries["hourly"].get().replace(",", "")),
                           start=entries["start"].get(), end=entries["end"].get(),
                           lunch_min=float(entries["lunch_min"].get() or 0),
                           workdays=[d for d in range(7) if day_on[d]])
                gross = annual_gross(tmp)
                d = annual_deductions(gross)
                txt = (f"按 {TAX_YEAR} 年安省税率估算：年收入约 ${gross:,.0f}，"
                       f"扣联邦税、安省税、健康保费、CPP、EI 约 {d['rate'] * 100:.1f}%，"
                       f"到手约 ${gross - d['total']:,.0f}。不算 RRSP、其他抵免和退税")
            except Exception:
                txt = f"按 {TAX_YEAR} 年安省税率估算；填好时薪和上下班时间后显示估算结果"
            tax_group.hint.configure(text=txt)

        option(row(g, "金额显示"), tax_var, list(tax_names.values()), lambda _v: tax_hint())

        # 时间
        page[0] = pages["时间"]
        g = group("时间", "时间格式 HH:MM，例如 08:30；午休时长从工资里扣掉")
        entries["start"] = entry(row(g, "上班时间"), c["start"])
        entries["end"] = entry(row(g, "下班时间"), c["end"])
        entries["lunch_min"] = entry(row(g, "午休时长（分钟）"), str(c.get("lunch_min", 0)))

        # 工作日：胶囊开关，选中用强调蓝
        g = group("工作日")
        fr = tk.Frame(g, padx=12, pady=10, **S)
        fr.pack(fill="x")
        day_on = [d in c["workdays"] for d in range(7)]
        chips = []

        def paint(d):
            on = day_on[d]
            chips[d].configure(bg=p["accent"] if on else p["input"],
                               fg=p["on_accent"] if on else p["text2"])

        def flip(d):
            day_on[d] = not day_on[d]
            paint(d)
            tax_hint()

        for d, name in enumerate("一二三四五六日"):
            ch = tk.Label(fr, text=name, font=(FONT, 10), width=3, pady=4, cursor="hand2")
            ch.pack(side="left", padx=2, expand=True, fill="x")
            ch.bind("<Button-1>", lambda _e, d=d: flip(d))
            chips.append(ch)
            paint(d)

        # 天气
        page[0] = pages["其他"]
        g = group("天气", "天气来自加拿大环境部")
        city_names = {cid: n for n, cid in CITIES}
        city_var = tk.StringVar(value=city_names.get(c.get("city", "on-143"), "多伦多"))
        option(row(g, "城市"), city_var, [n for n, _ in CITIES])

        # 时薪、时间改了就重新估算税
        for key in ("hourly", "start", "end", "lunch_min"):
            entries[key].bind("<KeyRelease>", tax_hint, add="+")
        tax_hint()

        # 外观
        g = group("外观")
        theme_names = dict(THEMES)
        theme_var = tk.StringVar(value=theme_names.get(c.get("theme", "auto"), "跟随系统"))
        option(row(g, "深浅色"), theme_var, [n for _, n in THEMES])
        alpha = tk.Scale(row(g, "不透明度"), from_=0.3, to=1.0, resolution=0.02,
                         orient="horizontal", length=150, showvalue=False, width=8,
                         sliderlength=18, bd=0, relief="flat", sliderrelief="flat",
                         highlightthickness=0, troughcolor=p["track"], bg=p["text3"],
                         activebackground=p["accent"],
                         command=lambda v: self.root.attributes("-alpha", float(v)))
        alpha.set(c["alpha"])
        alpha.pack(side="right")

        # 版本
        g = group("版本")
        fr = row(g, f"当前版本 v{VERSION}")
        PillButton(fr, "更新记录…", p["track"], p["text"], self.show_changelog, p["surface"],
                   (FONT, 9)).pack(side="right")

        # 宠物
        page[0] = pages["宠物"]
        g = group("宠物", "")
        pet_group = g
        pet_on_var = tk.StringVar(value="显示" if c.get("pet_on", True) else "隐藏")
        option(row(g, "显示宠物"), pet_on_var, ["显示", "隐藏"])
        pet_zoom_var = tk.StringVar(value={2: "小", 3: "中", 4: "大"}.get(c.get("pet_zoom", 2), "小"))
        option(row(g, "大小"), pet_zoom_var, ["小", "中", "大"])
        fr = row(g, "素材")
        status = tk.Label(fr, text="", fg=p["text2"], font=(FONT, 9), **S)

        def pet_status():
            m = self.pet.manifest
            if m:
                n = len(m.get("states", {}))
                status.configure(text=f"已导入：{m.get('name', '')}（{n} 个动作）")
            else:
                status.configure(text="还没有导入")

        def do_import():
            from tkinter import filedialog
            src = filedialog.askdirectory(parent=win, title="选择放宠物素材的文件夹")
            if not src:
                return

            def prog(msg):
                status.configure(text=msg)
                win.update()
            prog("处理中…")
            try:
                rep = import_pet_assets(src, prog)
            except Exception as ex:
                rep = {"ok": False, "error": f"处理失败：{ex}"}
            if not rep["ok"]:
                pet_group.hint.configure(text=rep["error"], fg=p["danger"])
                pet_status()
                return
            self.pet.reload()
            pet_status()
            lines = [f"导入成功：{len(rep['states'])} 个动作"
                     + (f"，已自动处理成 {PET_STORE}×{PET_STORE} 像素风" if rep["processed"] else "")]
            if rep["missing"]:
                lines.append("缺少（用平时的样子代替）：" +
                             "、".join(PET_STATE_NAMES[s] for s in rep["missing"]))
            if rep["skipped"]:
                lines.append("跳过：" + "；".join(rep["skipped"][:4]))
            pet_group.hint.configure(text=chr(10).join(lines), fg=p["text3"])

        PillButton(fr, "导入素材…", p["accent"], p["on_accent"], do_import, p["surface"],
                   (FONT, 9)).pack(side="right")
        status.pack(side="right", padx=(0, 8))
        pet_status()

        # 没有素材：复制一段提示词，连同照片发给能画图的 AI
        fr = row(g, "AI 画素材")
        copied = tk.Label(fr, text="", fg=p["green"], font=(FONT, 9), **S)

        def copy_pet_prompt():
            win.clipboard_clear()
            win.clipboard_append(pet_ai_prompt())
            copied.configure(text="已复制")
            win.after(2000, lambda: copied.winfo_exists() and copied.configure(text=""))
        PillButton(fr, "复制提示词", p["track"], p["text"], copy_pet_prompt, p["surface"],
                   (FONT, 9)).pack(side="right")
        copied.pack(side="right", padx=(0, 8))
        pet_group.hint.configure(text=chr(10).join([
            "没有素材？点“复制提示词”，连同照片",
            "发给能画图的 AI（比如 ChatGPT）。",
            "照片 3–6 张：正面全身坐姿（最重要）、",
            "侧面全身、脸部特写、花纹明显的部位；",
            "光线自然、不加滤镜，只拍这一只。",
            "画好的 PNG 放进一个文件夹，点“导入素材…”。",
            "必需 idle_1.png，缺的动作会自动找替身；",
            "任意大小，绿底会自动抠掉、缩成像素风。",
            "互动：点它、连戳、双击、拖着走，",
            "在它身上来回划是摸摸，鼠标靠近会盯着看；",
            "右键猫打开喂食面板。"]))

        # 底部：错误提示 + 按钮
        err = tk.Label(body, text="", fg=p["danger"], font=(FONT, 9), anchor="w",
                       justify="left", wraplength=330, **G)
        err.pack(fill="x", pady=(10, 0), padx=4)

        def fail(msg, key=None):
            err.configure(text=msg)
            show_page("收入" if key in ("hourly", "fx", "currency") else "时间")
            if key:
                entries[key].focus_set()
                entries[key].select_range(0, "end")

        def num(key, default=None):
            s = entries[key].get().strip().replace(",", "")
            return float(s) if s or default is None else default

        def save():
            try:
                hourly = num("hourly")
                if hourly <= 0:
                    raise ValueError
            except ValueError:
                return fail("时薪要填一个大于 0 的数字", "hourly")
            display = DISPLAY_BY_NAME[display_var.get()][0]
            fx, currency = c.get("fx", 1), c.get("currency", "$")
            if display == "custom":
                try:
                    fx = num("fx", 1.0)
                    if fx <= 0:
                        raise ValueError
                except ValueError:
                    return fail("汇率要填一个大于 0 的数字，不换算就填 1", "fx")
                fx = int(fx) if fx.is_integer() else fx
                currency = entries["currency"].get().lstrip()  # 保留结尾空格，如 "Rp "
            try:
                s = parse_hm(entries["start"].get())
            except ValueError:
                return fail("上班时间格式不对，请用 HH:MM，例如 09:00", "start")
            try:
                e = parse_hm(entries["end"].get())
            except ValueError:
                return fail("下班时间格式不对，请用 HH:MM，例如 17:00", "end")
            if not s or not e or e <= s:
                return fail("下班时间要晚于上班时间", "end")
            span_min = (e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)
            try:
                lunch_min = num("lunch_min", 0.0)
                if not 0 <= lunch_min < span_min:
                    raise ValueError
            except ValueError:
                return fail("午休时长填分钟数，比如 30；要比上班时长短", "lunch_min")
            if not any(day_on):
                return fail("至少选一个工作日")

            pet_before = (c.get("pet_on", True), c.get("pet_zoom", 2))
            theme = next(k for k, n in THEMES if n == theme_var.get())
            theme_changed = theme != c.get("theme", "auto")
            c.update(
                hourly=hourly,
                display=display, fx=fx, currency=currency,
                tax_mode=next(k for k, n in TAX_MODES if n == tax_var.get()),
                start=s.strftime("%H:%M"), end=e.strftime("%H:%M"),
                lunch_min=int(lunch_min) if lunch_min.is_integer() else lunch_min,
                workdays=[d for d in range(7) if day_on[d]],
                alpha=float(alpha.get()),
                theme=theme,
                city=next(cid for n, cid in CITIES if n == city_var.get()),
                pet_on=pet_on_var.get() == "显示",
                pet_zoom={"小": 2, "中": 3, "大": 4}[pet_zoom_var.get()],
            )
            pet_changed = (c["pet_on"], c["pet_zoom"]) != pet_before
            save_conf(c)
            WX_CITY[0] = c["city"]
            if pet_changed:
                if c["pet_on"] != pet_before[0] and c["pet_zoom"] == pet_before[1]:
                    self.pet.set_visible(c["pet_on"], anim=True)   # 只动了显示开关：带出现/消失动画
                else:
                    self.pet.reload()                              # 改了缩放（可能同时改开关）：直接重建
                self.refresh_paw()
            self.cheer_state = None
            win.destroy()
            if theme_changed:
                self.rebuild()

        def cancel():
            self.root.attributes("-alpha", c["alpha"])
            win.destroy()

        btns = tk.Frame(body, **G)
        btns.pack(fill="x", pady=(8, 12))
        PillButton(btns, "保存", p["accent"], p["on_accent"], save, p["ground"],
                   (FONT, 10)).pack(side="right")
        PillButton(btns, "取消", p["track"], p["text"], cancel, p["ground"],
                   (FONT, 10)).pack(side="right", padx=(0, 8))
        win.protocol("WM_DELETE_WINDOW", cancel)
        win.bind("<Return>", lambda _e: save())
        win.bind("<Escape>", lambda _e: cancel())

        # 三页按最高那页定高度，切换时窗口不跳
        win.update_idletasks()
        holder.configure(width=max(f.winfo_reqwidth() for f in pages.values()),
                         height=max(f.winfo_reqheight() for f in pages.values()) + 4)
        holder.pack_propagate(False)
        show_page("收入")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        if not IS_MAC:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 高分屏下字不发虚
    except Exception:
        pass
    Floater().run()
