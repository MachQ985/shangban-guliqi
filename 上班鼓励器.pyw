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
VERSION = "1.6.1"  # 发布新版时改这里，同事那边自动更新
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
    },
    "dark": {
        "surface": "#1c1c1e", "ground": "#000000", "input": "#2c2c2e",
        "text": "#f5f5f7", "text2": "#aeaeb2", "text3": "#8e8e93",
        "hairline": "#2c2c2e", "track": "#3a3a3c", "border": "#3a3a3c",
        "gold": "#ffd60a", "green": "#30d158", "bar": "#30d158", "up": "#ff453a",
        "accent": "#0a84ff", "on_accent": "#ffffff", "danger": "#ff453a",
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
                "rub": "pet"}
PET_EFFECTS = ["heart", "question", "exclaim", "anger", "note", "sweat"]  # 头顶小特效 fx_*.png
PET_STATES = ["idle", "eat", "play", "sleep", "happy", "click", "hungry", "work",
              "rain", "snow", "cold", "hot", "sunny"] + PET_EXTRA_LOOP + PET_EXTRA_ONCE + PET_INTERACT
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
                   "swatl": "往左拍", "swatr": "往右拍"}
PET_ICONS = ["snack", "freeze_dried", "can", "wand"]
PET_DIR = os.path.join(CONF_DIR, "pet")
PET_SIZE, PET_GROUND, PET_ICON = 64, 56, 32   # 帧 64×64，脚底在第 56 行；图标 32×32
PET_FX = 16                                   # 头顶特效 16×16
PET_TOP = 16                                  # 猫窗口上方多留的高度，给特效往上飘
PET_CAT_HEIGHT = 46                           # 自动处理时，平时坐姿缩放到大约这么高
PET_KEY = "#ff00fe"                           # 读图时用这个颜色标记透明像素
PET_FPS_MS = 250


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
    std = all(is_std(p, PET_SIZE) for p in sprite_files)
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
        scale = PET_CAT_HEIGHT / ((bb[3] - bb[1] + 1) * k0)
        cx = (bb[0] + bb[2] + 1) / 2 * k0
        bottom = (bb[3] + 1) * k0
        grids, names = [], []
        for n, (st, paths) in enumerate(frames.items(), 1):
            for i, p in enumerate(paths, 1):
                g, k = read[p]
                grids.append(_pet_resample(g, k, scale, cx, bottom, PET_SIZE,
                                           PET_SIZE / 2, PET_GROUND + 1))
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
                self.frames[st] = [tk.PhotoImage(file=os.path.join(PET_DIR, n)).zoom(z) for n in names]
            for ic, n in self.manifest.get("icons", {}).items():
                self.icons[ic] = tk.PhotoImage(file=os.path.join(PET_DIR, n))
            for fx, n in self.manifest.get("effects", {}).items():
                self.effects[fx] = tk.PhotoImage(file=os.path.join(PET_DIR, n)).zoom(z)
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
        self.create_text(w / 2, h / 2, text=text, fill=fg, font=f)
        self.bind("<ButtonPress-1>", lambda _e: self.itemconfigure(self.shape, fill=self._dim()))
        self.bind("<ButtonRelease-1>", self._release)

    def _dim(self):  # 按下时颜色压暗一点，给即时反馈
        r, g, b = (int(self.bg[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % (int(r * .88), int(g * .88), int(b * .88))

    def _release(self, e):
        self.itemconfigure(self.shape, fill=self.bg)
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()


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

        # 今日签：贴在“明天”和日出日落两行的右边
        fb = tk.Frame(self.frame, **S)
        fb.place(in_=wx_frames[2], relx=1.0, rely=0.0, anchor="ne")
        self.fortune_title = tk.Label(fb, text="今日签", fg=p["text3"], font=(FONT, 9),
                                      cursor="hand2", **S)
        self.fortune_title.pack(anchor="e")
        self.fortune_lv = tk.Label(fb, text="", fg=p["accent"], font=(FONT, 11, "bold"),
                                   cursor="hand2", **S)
        self.fortune_lv.pack(anchor="e")
        for w in (fb, self.fortune_title, self.fortune_lv):
            w.bind("<ButtonRelease-1>", self.on_fortune_click)
            w.bind("<Double-Button-1>", lambda _e: "break")  # 双击这里不切换迷你模式
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
        self.menu.add_command(label="迷你模式 / 完整模式", command=self.toggle_mini)
        self.autostart_var = tk.BooleanVar(value=autostart_enabled())
        self.menu.add_checkbutton(label="开机自启", variable=self.autostart_var,
                                  command=lambda: set_autostart(self.autostart_var.get()))
        self.menu.add_separator()
        self.menu.add_command(label=f"检查更新（当前 v{VERSION}）", command=self.manual_update)
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
                     + ("，已自动处理成 64×64 像素风" if rep["processed"] else "")]
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
        pet_group.hint.configure(text=chr(10).join([
            "选一个放 PNG 图片的文件夹，按动作给文件命名：",
            "必需：idle_1.png（平时）",
            "常用：eat、play、sleep、happy、hungry、work…",
            "完整的 50 多个动作名见 GitHub 首页“做自己的小猫”",
            "多帧动画：idle_1、idle_2、idle_3…，缺的动作自动找替身",
            "任意大小都行；透明或纯绿色背景最好，",
            "会自动抠图、缩成像素风并对齐。",
            "互动：点它、连戳、双击、拖着走、在它身上来回划（摸摸），",
            "鼠标靠近它会盯着看；右键猫打开喂食面板。"]))

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
                self.pet.reload()
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
