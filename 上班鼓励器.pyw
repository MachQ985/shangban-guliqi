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
VERSION = "1.4.1"  # 发布新版时改这里，同事那边自动更新
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
    ]),
    ("中吉", 20, (75, 89), [
        "稳中有进，手头的活今天能收尾", "小有惊喜，可能有人请你喝奶茶",
        "沟通顺畅，邮件不用来回改三遍", "灵感在线，难题今天有思路",
        "领导心情不错，适合汇报进度", "忙而不乱，下班前能清空待办",
        "同事给力，配合默契", "今天的努力，月底看得见",
    ]),
    ("小吉", 25, (60, 74), [
        "小有收获，别贪多，一件一件来", "运气一般般，但午饭会很好吃",
        "可能被临时拉去帮忙，顺手积点人情", "慢一点没关系，稳住就好",
        "今天适合整理桌面和文件夹", "会有一点小麻烦，问一句就解决",
        "平平淡淡，也是好的一天",
    ]),
    ("吉", 25, (50, 64), [
        "按部就班，不出岔子就是胜利", "不求表现，但求不背锅",
        "日常的一天，把本职做好就行", "中规中矩，记得多喝水",
        "适合做重复的活，不容易出错", "别跟人较劲，跟进度较劲",
        "无风无浪，摸鱼也要适度",
    ]),
    ("末吉", 15, (35, 49), [
        "开局不顺，下午会好起来", "小心临时需求，留点余量",
        "今天的会可能有点长，带上水杯", "容易手滑，发消息前多看一眼",
        "运势在攒，明天会更好", "低调做事，少说多听",
    ]),
    ("凶", 5, (10, 34), [
        "今日宜装忙，忌被点名", "问题有点多，深呼吸，一个一个解决",
        "可能会被甩锅，记得留好聊天记录", "诸事不宜，准时下班就是最好的转运",
        "今天的坑有点深，多问一句再动手",
    ]),
]
FORTUNE_YI = [
    "准时下班", "摸鱼十分钟", "点杯奶茶", "整理桌面", "回复积压的邮件", "站起来走走",
    "主动汇报进度", "喝够八杯水", "早点吃午饭", "学点新东西", "给同事带零食", "清空待办",
    "关掉工作群提醒", "备份文件", "请教老同事", "先做最难的事", "午休小睡", "夸夸同事",
    "伸个懒腰", "早点出门", "戴耳机听首歌", "按时吃饭", "出去晒晒太阳", "写周报",
    "拒绝无效会议", "规划下周", "早睡", "记账", "提前十分钟到", "把话说清楚",
]
FORTUNE_JI = [
    "开会超时", "周五上线", "临时改需求", "加班", "已读不回", "背锅", "熬夜",
    "在群里抬杠", "喝第三杯咖啡", "边吃边干活", "什么都答应", "拖到最后一分钟",
    "乱改别人的文件", "当着老板摸鱼", "说“马上好”", "深夜回消息", "久坐不动",
    "冲动消费", "跟电脑较劲", "忘记保存", "点“回复全部”", "把会开成聊天", "画大饼",
    "空腹喝咖啡", "大清早开会", "硬撑不请假", "乱删文件", "忽略提醒",
    "连续干两小时不休息", "下班前接新活",
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
        PAGES = ["收入", "时间", "其他"]
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
            )
            save_conf(c)
            WX_CITY[0] = c["city"]
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
