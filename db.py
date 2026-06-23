import sqlite3
import os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "campus_hub.db")

DEFAULT_BANNED_WORDS = [
    "代考", "代课", "代写", "论文代写", "毕业论文代写",
    "刷单", "刷信誉", "违禁品", "枪支", "毒品",
]

SCHOOL_NAME = "示例大学"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT NOT NULL,
            account TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            verified INTEGER DEFAULT 0,
            verify_method TEXT,
            school TEXT DEFAULT '示例大学',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            image TEXT,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            pinned INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            last_message_at TEXT NOT NULL,
            UNIQUE(post_id, buyer_id),
            FOREIGN KEY (post_id) REFERENCES posts(id),
            FOREIGN KEY (buyer_id) REFERENCES users(id),
            FOREIGN KEY (seller_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            sender_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (sender_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS banned_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS safety_ack (
            user_id INTEGER PRIMARY KEY,
            acknowledged INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (post_id) REFERENCES posts(id)
        );
    """)

    _migrate(c)

    count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        _seed_data(c)

    conn.commit()
    conn.close()


def _migrate(c):
    """幂等迁移：为已存在的旧库补充新增列（保留现有数据）。"""
    cols = {row["name"] for row in c.execute("PRAGMA table_info(posts)").fetchall()}
    if "top_until" not in cols:
        c.execute("ALTER TABLE posts ADD COLUMN top_until TEXT")
    if "service_fee" not in cols:
        c.execute("ALTER TABLE posts ADD COLUMN service_fee REAL DEFAULT 0")


def _seed_data(c):
    now = datetime.now()
    pw = generate_password_hash("123456")

    # 用户：1 名管理员 + 16 名已认证用户 + 1 名未认证（共 18 人）
    # 昵称风格混合：中文短语 / 英文 / 数字 / 简短，贴近真实注册用户，不使用真实姓名
    users = [
        ("校园管家", "admin@campus.edu", "admin", 1, "学生证", 19),
        ("冰美式续命中", "icedam@stu.edu", "user", 1, "学生证", 18),
        ("图书馆钉子户", "libnail@stu.edu", "user", 1, "定位", 18),
        ("奶茶半糖去冰", "milktea50@stu.edu", "user", 1, "学生证", 17),
        ("Luna", "luna@stu.edu", "user", 1, "定位", 16),
        ("熬夜写论文", "nightpaper@stu.edu", "user", 1, "学生证", 16),
        ("77", "seven77@stu.edu", "user", 1, "定位", 15),
        ("晚风", "wanfeng@stu.edu", "user", 1, "学生证", 14),
        ("Echo", "echo@stu.edu", "user", 1, "定位", 13),
        ("小熊不想上课", "bearbear@stu.edu", "user", 1, "学生证", 12),
        ("Momo", "momo@stu.edu", "user", 1, "定位", 11),
        ("今天也在赶DDL", "ddlrush@stu.edu", "user", 1, "学生证", 10),
        ("橘子", "juzi@stu.edu", "user", 1, "定位", 9),
        ("Yuki", "yuki@stu.edu", "user", 1, "学生证", 8),
        ("404", "err404@stu.edu", "user", 1, "定位", 6),
        ("KK", "kk@stu.edu", "user", 1, "学生证", 5),
        ("星河", "xinghe@stu.edu", "user", 1, "定位", 3),
        ("初七", "chuqi@stu.edu", "user", 0, None, 2),
    ]
    for nickname, account, role, verified, vm, days_ago in users:
        c.execute(
            "INSERT INTO users (nickname, account, password_hash, role, verified, verify_method, created_at) VALUES (?,?,?,?,?,?,?)",
            (nickname, account, pw, role, verified, vm, (now - timedelta(days=days_ago)).isoformat()),
        )

    for word in DEFAULT_BANNED_WORDS:
        c.execute("INSERT OR IGNORE INTO banned_words (word) VALUES (?)", (word,))

    student_ids = list(range(2, 18))  # 16 名已认证学生的 id

    # 二手商品（28 条）：(标题, 描述, 价格, 分类)
    secondhand = [
        ("高等数学同济第七版上下册", "笔记很少无缺页，适合大一复习，图书馆门口面交。", 35, "书籍"),
        ("考研英语黄皮书真题全套", "历年真题加详解，标注清晰，宿舍楼下自提。", 48, "书籍"),
        ("大学英语四级真题+词汇书", "刷过一遍重点已划，备考四级够用。", 25, "书籍"),
        ("考研政治肖秀荣全套", "1000题加精讲精练加背诵手册，齐全。", 40, "书籍"),
        ("雅思真题剑桥4-18", "备考资料齐全，部分有笔记。", 70, "书籍"),
        ("考研专业课笔记打印版", "学长整理的重点笔记，已装订。", 22, "书籍"),
        ("九成新 iPad Air 带原装笔", "2023款64G，自习记笔记神器，附笔和壳，图书馆门口面交。", 2200, "数码"),
        ("索尼降噪耳机 WH-1000XM4", "图书馆自习专用，降噪很顶，含原盒。", 1100, "数码"),
        ("机械键盘红轴87键", "手感顺滑，含拔键器，白色背光。", 160, "数码"),
        ("罗技静音无线鼠标", "几乎全新，宿舍晚上用不打扰室友。", 45, "数码"),
        ("Kindle Paperwhite 电子书", "护眼墨水屏，8成新，宿舍楼下自提。", 380, "数码"),
        ("二手显示器 24寸 1080P", "办公网课够用，无亮点无划痕。", 320, "数码"),
        ("二手iPhone 12 128G", "屏幕无划痕，电池健康85%，图书馆门口面交。", 1800, "数码"),
        ("充电宝 20000mAh", "双口快充，出门一天不焦虑。", 60, "数码"),
        ("宿舍用小冰箱", "用了半年制冷正常，毕业出售，西区食堂旁面交。", 180, "生活用品"),
        ("护眼 LED 台灯三档调光", "宿舍限电可用，9成新。", 55, "生活用品"),
        ("电热水壶宿舍款", "功率合规烧水快，几乎没用。", 35, "生活用品"),
        ("冬季加厚棉被8斤", "很暖和，洗过晒过，毕业带不走。", 60, "生活用品"),
        ("全身镜宿舍可贴墙", "高清无变形，宿舍楼下自提。", 45, "生活用品"),
        ("静音小风扇桌面款", "三档风力，USB供电，午休必备。", 28, "生活用品"),
        ("斯伯丁篮球几乎全新", "正品只打过两次，体育馆旁自取。", 120, "运动"),
        ("瑜伽垫+哑铃入门套装", "健身入门一起出，加厚防滑。", 80, "运动"),
        ("跑步鞋42码穿过两次", "缓震不错，码数不合适出。", 150, "运动"),
        ("自行车通勤代步", "入门款骑行正常，车锁送，宿舍楼下自提。", 260, "其他"),
        ("吉他入门款带琴包", "练习足够，附拨片和变调夹。", 200, "其他"),
        ("蓝牙音箱便携防水", "户外宿舍都能用，音质不错。", 90, "数码"),
        ("【待审核】二手吉他效果器", "刚提交，等待管理员审核。", 300, "数码"),
        ("【已驳回】疑似违规描述演示", "该条用于演示驳回状态。", 50, "其他"),
    ]

    # 跑腿需求（20 条）：(标题, 描述, 报酬, 分类)
    errands = [
        ("菜鸟驿站代取快递", "菜鸟驿站代取，包裹送到3号宿舍楼下，报酬可议。", 8, "快递代拿"),
        ("顺丰代取到5号楼", "顺丰代取，两个中等包裹送到5栋宿舍楼下。", 7, "快递代拿"),
        ("代取食堂外卖到信息楼", "外卖代拿，12点前送到信息楼B座。", 5, "外卖代取"),
        ("帮带校门口奶茶两杯", "奶茶外卖代拿，少冰三分糖，送到5栋。", 6, "外卖代取"),
        ("图书馆占座南区靠窗", "图书馆占座，明早8点南区靠窗2小时。", 6, "其他跑腿"),
        ("教材借阅顺路归还", "教材借阅，3本书顺路还到总馆借阅处。", 5, "其他跑腿"),
        ("宿舍楼下帮送文件", "宿舍楼下帮送，一份打印文件送到对面楼。", 5, "其他跑腿"),
        ("菜鸟驿站代取大件", "菜鸟驿站代取，大件较重，送到东区宿舍楼下。", 9, "快递代拿"),
        ("顺丰代取到东区", "顺丰代取，一个小包裹送到东区宿舍楼下。", 7, "快递代拿"),
        ("外卖代拿到三教", "早餐外卖代拿，8点前送到三教门口。", 5, "外卖代取"),
        ("图书馆占座二楼自习区", "图书馆占座，明天上午二楼自习区2小时。", 6, "其他跑腿"),
        ("教材借阅帮借两本", "教材借阅，帮借两本指定教材送到宿舍楼下。", 6, "其他跑腿"),
        ("宿舍楼下帮送充电宝", "宿舍楼下帮送，充电宝送到隔壁栋楼下。", 5, "其他跑腿"),
        ("菜鸟驿站代取两件", "菜鸟驿站代取，两件包裹送到9栋楼下。", 7, "快递代拿"),
        ("外卖代拿午饭到实验楼", "外卖代拿，午饭送到实验楼一楼。", 6, "外卖代取"),
        ("顺丰代取到南区宿舍", "顺丰代取，送到南区宿舍楼下。", 7, "快递代拿"),
        ("图书馆占座靠窗座位", "图书馆占座，周末上午靠窗座位2小时。", 6, "其他跑腿"),
        ("教材借阅顺路带书", "教材借阅，顺路把借的书带到宿舍楼下。", 5, "其他跑腿"),
        ("宿舍楼下帮送雨伞", "宿舍楼下帮送，下雨帮带把伞到教学楼。", 5, "其他跑腿"),
        ("【待审核】外卖代拿夜宵到9栋", "外卖代拿，夜宵送到9栋楼下。", 8, "外卖代取"),
    ]

    # 发布时间分布（单位：天前）。平台已运营约 19 天：多数发布集中在 7~18 天前，
    # 最近 7 天为自然波动的零散新增（按天约 2/0/3/1/0/2/1，含无人发帖的日子）。
    sh_days = [
        3, 9, 14, 16, 11, 18, 6, 13, 8, 17, 10, 15, 7, 12,
        9, 18, 11, 8, 16, 13, 7, 14, 10, 17, 9, 12, 1, 4,
    ]
    er_days = [
        1, 12, 4, 15, 4, 10, 6, 13, 8, 16,
        11, 14, 9, 17, 12, 8, 15, 10, 13, 0,
    ]

    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    pin_sh = {6, 7, 20}  # 当前置顶中的二手商品索引（均为已通过：iPad、耳机、篮球）

    post_ids = {}  # (kind, idx) -> rowid

    def _insert_post(author, ptype, title, desc, price, category, status, pinned, service_fee, created):
        top_until = (now + timedelta(hours=24)).isoformat() if pinned else None
        c.execute(
            """INSERT INTO posts (user_id, type, title, description, image, price, category, status, pinned, service_fee, top_until, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (author, ptype, title, desc, None, price, category, status, pinned, service_fee, top_until, created.isoformat()),
        )
        return c.lastrowid

    for i, (title, desc, price, category) in enumerate(secondhand):
        author = student_ids[i % len(student_ids)]
        created = base - timedelta(days=sh_days[i]) + timedelta(hours=8 + (i % 13), minutes=(i * 7) % 60)
        if title.startswith("【待审核】"):
            status = "pending"
        elif title.startswith("【已驳回】"):
            status = "rejected"
        else:
            status = "approved"
        pinned = 1 if (i in pin_sh and status == "approved") else 0
        post_ids[("s", i)] = _insert_post(author, "二手商品", title, desc, price, category, status, pinned, 0, created)

    for j, (title, desc, price, category) in enumerate(errands):
        author = student_ids[(j + 5) % len(student_ids)]
        created = base - timedelta(days=er_days[j]) + timedelta(hours=9 + (j % 11), minutes=(j * 11) % 60)
        status = "pending" if title.startswith("【待审核】") else "approved"
        service_fee = round(price * 0.03, 2)
        post_ids[("e", j)] = _insert_post(author, "跑腿需求", title, desc, price, category, status, 0, service_fee, created)

    # 置顶模拟支付订单：5 笔，金额各 ¥2，下单时间分散在近半月（含已过期记录）
    top_orders = [(("s", 6), 1), (("s", 7), 4), (("s", 20), 6), (("s", 2), 9), (("s", 12), 13)]
    for n, (key, age) in enumerate(top_orders):
        if key in post_ids:
            order_time = base - timedelta(days=age) + timedelta(hours=15, minutes=(n * 17) % 60)
            c.execute(
                "INSERT INTO orders (user_id, post_id, type, amount, created_at) VALUES (?,?,?,?,?)",
                (student_ids[(n + 2) % len(student_ids)], post_ids[key], "置顶", 2.0, order_time.isoformat()),
            )


def get_banned_words():
    conn = get_db()
    words = [r["word"] for r in conn.execute("SELECT word FROM banned_words").fetchall()]
    conn.close()
    return words


def check_banned_content(title, description):
    text = (title + description).lower()
    for word in get_banned_words():
        if word.lower() in text:
            return True
    return False
