# 上班鼓励器

桌面悬浮窗：按时薪实时显示今天已经赚了多少、还有多久下班。

- 钱可以换算成人民币、日元、越南盾等（实时汇率），或者换算成**能加多少升汽油**（大多伦多每日油价）
- 常驻显示明天油价是涨还是跌
- 天气：现在、下班时、明天、日出日落（加拿大环境部数据），下班要下雨会提醒带伞
- 今日签：每人每天一签，有签文、打工指数和宜忌
- 税后到手：按 2026 年安省税率估算扣税后的金额，也可以选税前或现金
- 双击切换迷你模式；右键打开设置
- **自动更新**：有新版会自己下载、重启，不用重新安装

## 安装（Windows）

1. 装 Python：到 <https://www.python.org/downloads/windows/> 下载，安装时勾选 **Add python.exe to PATH**，然后点 **Install Now**。
2. 下载本程序：点页面上方绿色的 **Code** 按钮 → **Download ZIP**，解压到一个固定的位置（比如"文档"里）。
3. 双击 **上班鼓励器.pyw** 打开，第一次会弹出设置，填好时薪和上下班时间就行。

想开机自动打开：在悬浮窗上右键 → 勾选"开机自启"。

## 安装（Mac）

1. 到 <https://www.python.org/downloads/macos/> 安装 Python，装完运行一次 Python 文件夹里的 `Install Certificates.command`。
2. 同样下载 ZIP 解压。
3. 打开"终端"，进入解压的文件夹，运行一次 `chmod +x Mac双击打开.command`。
4. 第一次在 `Mac双击打开.command` 上**右键 → 打开**，以后直接双击。

## 常见问题

- **怎么更新？** 不用管。程序每 6 小时自己检查一次，有新版就自动换上并重启；也可以右键 → "检查更新"。
- **新版有问题？** 上一个版本备份在设置文件夹里的 `旧版备份.pyw`
  （Windows：`%APPDATA%\上班鼓励器`；Mac：`~/Library/Application Support/上班鼓励器`）。
- **我的设置会被更新覆盖吗？** 不会，设置存在上面那个文件夹，和程序文件分开。

数据来源：汇率 [ExchangeRate-API](https://www.exchangerate-api.com)，油价 [CityNews / En-Pro](https://toronto.citynews.ca/toronto-gta-gas-prices/)。
