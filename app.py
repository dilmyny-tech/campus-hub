import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import db

app = Flask(__name__)
app.secret_key = "campus-hub-demo-secret-key-2026"
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

SECOND_HAND_CATEGORIES = ["数码", "书籍", "生活用品", "运动", "其他"]
ERRAND_CATEGORIES = ["外卖代取", "快递代拿", "其他跑腿"]

# 置顶模拟收费：¥2 / 24 小时
TOP_PRICE = 2.0
TOP_DURATION_HOURS = 24
# 跑腿服务费：按报酬的 3% 计算
ERRAND_FEE_RATE = 0.03

STATUS_LABELS = {
    "pending": "待审核",
    "approved": "已通过",
    "rejected": "已驳回",
    "taken": "已接单",
    "completed": "已完成",
    "sold": "已售出",
    "delisted": "已下架",
    "admin_removed": "管理员下架",
}


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("请先登录", "warning")
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return wrapped


def verified_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not g.user or not g.user["verified"]:
            flash("请先完成校园认证", "warning")
            return redirect(url_for("verify"))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not g.user or g.user["role"] != "admin":
            flash("需要管理员权限", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapped


@app.before_request
def load_user():
    g.user = None
    if "user_id" in session:
        conn = db.get_db()
        g.user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        conn.close()


@app.context_processor
def inject_globals():
    return {
        "current_user": g.user,
        "status_labels": STATUS_LABELS,
        "school_name": db.SCHOOL_NAME,
    }


@app.route("/")
def index():
    # 未登录用户先进入入口页，不展示信息流
    if not g.user:
        return render_template("welcome.html")
    post_type = request.args.get("type", "all")
    category = request.args.get("category", "")
    q = request.args.get("q", "").strip()

    sql = """
        SELECT p.*, u.nickname AS author_name
        FROM posts p JOIN users u ON p.user_id = u.id
        WHERE p.status = 'approved'
    """
    params = []
    if post_type == "secondhand":
        sql += " AND p.type = '二手商品'"
    elif post_type == "errand":
        sql += " AND p.type = '跑腿需求'"
    if category:
        sql += " AND p.category = ?"
        params.append(category)
    if q:
        sql += " AND (p.title LIKE ? OR p.description LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    sql += " ORDER BY p.pinned DESC, p.created_at DESC"

    conn = db.get_db()
    posts = conn.execute(sql, params).fetchall()
    conn.close()

    categories = SECOND_HAND_CATEGORIES + ERRAND_CATEGORIES
    return render_template(
        "index.html",
        posts=posts,
        post_type=post_type,
        category=category,
        q=q,
        categories=sorted(set(categories)),
        secondhand_categories=SECOND_HAND_CATEGORIES,
        errand_categories=ERRAND_CATEGORIES,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        nickname = request.form.get("nickname", "").strip()
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "")
        if not nickname or not account or not password:
            flash("请填写完整信息", "danger")
            return render_template("register.html")
        conn = db.get_db()
        existing = conn.execute("SELECT id FROM users WHERE account = ?", (account,)).fetchone()
        if existing:
            conn.close()
            flash("该账号已注册", "danger")
            return render_template("register.html")
        conn.execute(
            "INSERT INTO users (nickname, account, password_hash, created_at) VALUES (?,?,?,?)",
            (nickname, account, generate_password_hash(password), datetime.now().isoformat()),
        )
        conn.commit()
        user = conn.execute("SELECT id FROM users WHERE account = ?", (account,)).fetchone()
        conn.close()
        session["user_id"] = user["id"]
        flash("注册成功，请完成校园认证", "success")
        return redirect(url_for("verify"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "")
        conn = db.get_db()
        user = conn.execute("SELECT * FROM users WHERE account = ?", (account,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            flash("登录成功", "success")
            next_url = request.args.get("next") or request.form.get("next")
            if user["role"] == "admin":
                return redirect(next_url or url_for("admin_review"))
            return redirect(next_url or url_for("index"))
        flash("账号或密码错误", "danger")
    return render_template("login.html", next=request.args.get("next", ""))


@app.route("/logout")
def logout():
    session.clear()
    flash("已退出登录", "info")
    return redirect(url_for("index"))


@app.route("/verify", methods=["GET", "POST"])
@login_required
def verify():
    if g.user["verified"]:
        flash("您已完成校园认证", "info")
        return redirect(url_for("index"))
    if request.method == "POST":
        method = request.form.get("method")
        if method == "card":
            file = request.files.get("student_card")
            if file and file.filename:
                ext = os.path.splitext(secure_filename(file.filename))[1]
                filename = f"{uuid.uuid4().hex}{ext}"
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            verify_method = "学生证"
        elif method == "location":
            verify_method = "定位"
        else:
            flash("请选择认证方式", "danger")
            return render_template("verify.html")
        conn = db.get_db()
        conn.execute(
            "UPDATE users SET verified = 1, verify_method = ? WHERE id = ?",
            (verify_method, g.user["id"]),
        )
        conn.commit()
        conn.close()
        flash("认证成功！您现在可以发布信息和私信了", "success")
        return redirect(url_for("index"))
    return render_template("verify.html")


@app.route("/posts/<int:post_id>")
def post_detail(post_id):
    conn = db.get_db()
    post = conn.execute(
        """SELECT p.*, u.nickname AS author_name, u.id AS author_id
           FROM posts p JOIN users u ON p.user_id = u.id WHERE p.id = ?""",
        (post_id,),
    ).fetchone()
    conn.close()
    if not post:
        flash("信息不存在", "danger")
        return redirect(url_for("index"))
    if post["status"] != "approved" and (not g.user or (g.user["id"] != post["user_id"] and g.user["role"] != "admin")):
        flash("该信息暂不可见", "warning")
        return redirect(url_for("index"))
    is_owner = g.user and g.user["id"] == post["user_id"]
    contact_label = "接单" if post["type"] == "跑腿需求" else "联系卖家"
    return render_template("post_detail.html", post=post, is_owner=is_owner, contact_label=contact_label)


@app.route("/publish", methods=["GET", "POST"])
@login_required
@verified_required
def publish():
    agreed = request.args.get("agreed") == "1" or request.form.get("agreed") == "1"
    if request.method == "GET" and not agreed:
        return render_template("publish_convention.html")
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        post_type = request.form.get("type", "二手商品")
        category = request.form.get("category", "")
        price = request.form.get("price", "0")
        if not title or not description or not category:
            flash("请填写完整信息", "danger")
            return render_template("publish.html", agreed=True,
                                   secondhand_categories=SECOND_HAND_CATEGORIES,
                                   errand_categories=ERRAND_CATEGORIES)
        if db.check_banned_content(title, description):
            flash("检测到疑似违规内容，请修改后重新提交", "danger")
            return render_template("publish.html", agreed=True,
                                   secondhand_categories=SECOND_HAND_CATEGORIES,
                                   errand_categories=ERRAND_CATEGORIES,
                                   form=request.form)
        try:
            price_val = float(price)
        except ValueError:
            price_val = 0
        image = None
        file = request.files.get("image")
        if file and file.filename:
            ext = os.path.splitext(secure_filename(file.filename))[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            image = filename
        service_fee = round(price_val * ERRAND_FEE_RATE, 2) if post_type == "跑腿需求" else 0
        conn = db.get_db()
        conn.execute(
            """INSERT INTO posts (user_id, type, title, description, image, price, category, status, service_fee, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (g.user["id"], post_type, title, description, image, price_val, category, "pending", service_fee, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        flash("发布成功，等待管理员审核", "success")
        return redirect(url_for("profile"))
    return render_template("publish.html", agreed=True,
                           secondhand_categories=SECOND_HAND_CATEGORIES,
                           errand_categories=ERRAND_CATEGORIES)


@app.route("/posts/<int:post_id>/top", methods=["GET", "POST"])
@login_required
@verified_required
def top_post(post_id):
    conn = db.get_db()
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        conn.close()
        flash("信息不存在", "danger")
        return redirect(url_for("profile"))
    if post["user_id"] != g.user["id"]:
        conn.close()
        flash("只能置顶自己发布的信息", "danger")
        return redirect(url_for("profile"))
    if post["status"] != "approved":
        conn.close()
        flash("仅审核通过的信息可以置顶", "warning")
        return redirect(url_for("profile"))

    if request.method == "POST":
        now = datetime.now()
        top_until = now + timedelta(hours=TOP_DURATION_HOURS)
        conn.execute(
            "UPDATE posts SET pinned = 1, top_until = ? WHERE id = ?",
            (top_until.isoformat(), post_id),
        )
        conn.execute(
            "INSERT INTO orders (user_id, post_id, type, amount, created_at) VALUES (?,?,?,?,?)",
            (g.user["id"], post_id, "置顶", TOP_PRICE, now.isoformat()),
        )
        conn.commit()
        conn.close()
        order_no = "TOP" + now.strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4].upper()
        return render_template(
            "top_success.html", post=post, price=TOP_PRICE,
            hours=TOP_DURATION_HOURS, order_no=order_no,
        )

    conn.close()
    return render_template(
        "top_pay.html", post=post, price=TOP_PRICE, hours=TOP_DURATION_HOURS
    )


@app.route("/posts/<int:post_id>/contact")
@login_required
@verified_required
def contact_seller(post_id):
    conn = db.get_db()
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        conn.close()
        flash("该信息不可联系", "warning")
        return redirect(url_for("index"))
    if post["user_id"] == g.user["id"]:
        conn.close()
        flash("不能联系自己发布的信息", "warning")
        return redirect(url_for("post_detail", post_id=post_id))

    initiator_id = g.user["id"]
    existing = conn.execute(
        "SELECT id FROM conversations WHERE post_id = ? AND buyer_id = ?",
        (post_id, initiator_id),
    ).fetchone()

    # 已有会话的用户始终可进入聊天；否则仅“已通过”的信息可新建联系
    # （跑腿被接单后状态为 taken，其他用户无法再发起联系）
    if not existing and post["status"] != "approved":
        conn.close()
        flash("该信息不可联系", "warning")
        return redirect(url_for("index"))

    ack = conn.execute("SELECT * FROM safety_ack WHERE user_id = ?", (g.user["id"],)).fetchone()
    if request.args.get("ack") != "1" and not ack:
        conn.close()
        return render_template("safety_modal.html", post_id=post_id)

    if not ack:
        conn.execute("INSERT INTO safety_ack (user_id) VALUES (?)", (g.user["id"],))
        conn.commit()

    now = datetime.now().isoformat()
    if existing:
        conv_id = existing["id"]
    else:
        conn.execute(
            "INSERT INTO conversations (post_id, buyer_id, seller_id, last_message_at) VALUES (?,?,?,?)",
            (post_id, initiator_id, post["user_id"], now),
        )
        conv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # 跑腿需求被接单：置为已接单，自动从首页移除（二手商品不受影响）
        if post["type"] == "跑腿需求":
            conn.execute("UPDATE posts SET status = 'taken' WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("chat", conversation_id=conv_id))


@app.route("/posts/<int:post_id>/accept", methods=["GET", "POST"])
@login_required
@verified_required
def accept_errand(post_id):
    conn = db.get_db()
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        conn.close()
        flash("该信息不存在", "warning")
        return redirect(url_for("index"))
    # 该路由仅用于跑腿需求；二手商品仍走联系卖家逻辑
    if post["type"] != "跑腿需求":
        conn.close()
        return redirect(url_for("contact_seller", post_id=post_id))
    if post["user_id"] == g.user["id"]:
        conn.close()
        flash("不能接自己发布的跑腿需求", "warning")
        return redirect(url_for("post_detail", post_id=post_id))

    initiator_id = g.user["id"]
    existing = conn.execute(
        "SELECT id FROM conversations WHERE post_id = ? AND buyer_id = ?",
        (post_id, initiator_id),
    ).fetchone()
    # 已接单的本人可继续进入聊天；其他人不能再接已被接单的需求
    if not existing and post["status"] != "approved":
        conn.close()
        flash("该跑腿需求已被接单或不可接单", "warning")
        return redirect(url_for("index"))

    service_fee = post["service_fee"] or round((post["price"] or 0) * ERRAND_FEE_RATE, 2)

    if request.method == "POST":
        now = datetime.now().isoformat()
        if existing:
            conv_id = existing["id"]
        else:
            conn.execute(
                "INSERT INTO conversations (post_id, buyer_id, seller_id, last_message_at) VALUES (?,?,?,?)",
                (post_id, initiator_id, post["user_id"], now),
            )
            conv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("UPDATE posts SET status = 'taken' WHERE id = ?", (post_id,))
        # 接单确认页已完成风险确认，静默记录安全确认，避免重复弹窗
        ack = conn.execute("SELECT 1 FROM safety_ack WHERE user_id = ?", (initiator_id,)).fetchone()
        if not ack:
            conn.execute("INSERT INTO safety_ack (user_id) VALUES (?)", (initiator_id,))
        conn.commit()
        conn.close()
        return render_template(
            "accept_success.html", post=post, service_fee=service_fee, conv_id=conv_id,
        )

    conn.close()
    return render_template(
        "accept_confirm.html", post=post, service_fee=service_fee, fee_rate=ERRAND_FEE_RATE,
    )


def _owner_post_or_redirect(conn, post_id):
    """取出本人发布的帖子；非本人/不存在则返回 None。"""
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post or post["user_id"] != g.user["id"]:
        return None
    return post


@app.route("/posts/<int:post_id>/delist", methods=["POST"])
@login_required
def delist_post(post_id):
    conn = db.get_db()
    post = _owner_post_or_redirect(conn, post_id)
    if post is None:
        conn.close()
        flash("无权操作该信息", "danger")
        return redirect(url_for("profile"))
    if post["status"] in ("approved", "taken"):
        conn.execute("UPDATE posts SET status = 'delisted' WHERE id = ?", (post_id,))
        conn.commit()
        flash("已下架，可在个人中心重新上架", "info")
    conn.close()
    return redirect(url_for("profile"))


@app.route("/posts/<int:post_id>/relist", methods=["POST"])
@login_required
def relist_post(post_id):
    conn = db.get_db()
    post = _owner_post_or_redirect(conn, post_id)
    if post is None:
        conn.close()
        flash("无权操作该信息", "danger")
        return redirect(url_for("profile"))
    # 用户主动下架后的恢复，直接恢复为已通过，不重新审核
    if post["status"] == "delisted":
        conn.execute("UPDATE posts SET status = 'approved' WHERE id = ?", (post_id,))
        conn.commit()
        flash("已重新上架", "success")
    conn.close()
    return redirect(url_for("profile"))


@app.route("/posts/<int:post_id>/finish", methods=["POST"])
@login_required
def finish_post(post_id):
    conn = db.get_db()
    post = _owner_post_or_redirect(conn, post_id)
    if post is None:
        conn.close()
        flash("无权操作该信息", "danger")
        return redirect(url_for("profile"))
    # 终态，不可撤销；二手→已售出，跑腿→已完成
    if post["status"] in ("approved", "taken"):
        new_status = "sold" if post["type"] == "二手商品" else "completed"
        conn.execute("UPDATE posts SET status = ? WHERE id = ?", (new_status, post_id))
        conn.commit()
        flash("已售出" if new_status == "sold" else "已完成", "success")
    conn.close()
    return redirect(url_for("profile"))


@app.route("/messages")
@login_required
@verified_required
def messages():
    conn = db.get_db()
    uid = g.user["id"]
    convs = conn.execute(
        """SELECT c.*, p.title AS post_title, p.type AS post_type,
                  CASE WHEN c.buyer_id = ? THEN us.nickname ELSE ub.nickname END AS other_name
           FROM conversations c
           JOIN posts p ON c.post_id = p.id
           JOIN users ub ON c.buyer_id = ub.id
           JOIN users us ON c.seller_id = us.id
           WHERE c.buyer_id = ? OR c.seller_id = ?
           ORDER BY c.last_message_at DESC""",
        (uid, uid, uid),
    ).fetchall()
    result = []
    for c in convs:
        last_msg = conn.execute(
            "SELECT content FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
            (c["id"],),
        ).fetchone()
        result.append({**dict(c), "last_message": last_msg["content"] if last_msg else "暂无消息"})
    conn.close()
    return render_template("messages.html", conversations=result)


@app.route("/chat/<int:conversation_id>", methods=["GET", "POST"])
@login_required
@verified_required
def chat(conversation_id):
    conn = db.get_db()
    conv = conn.execute(
        """SELECT c.*, p.title AS post_title, p.type AS post_type,
                  ub.nickname AS buyer_name, us.nickname AS seller_name
           FROM conversations c
           JOIN posts p ON c.post_id = p.id
           JOIN users ub ON c.buyer_id = ub.id
           JOIN users us ON c.seller_id = us.id
           WHERE c.id = ?""",
        (conversation_id,),
    ).fetchone()
    if not conv or g.user["id"] not in (conv["buyer_id"], conv["seller_id"]):
        conn.close()
        flash("无权访问该会话", "danger")
        return redirect(url_for("messages"))

    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if content:
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO messages (conversation_id, sender_id, content, created_at) VALUES (?,?,?,?)",
                (conversation_id, g.user["id"], content, now),
            )
            conn.execute(
                "UPDATE conversations SET last_message_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            conn.commit()

    msgs = conn.execute(
        """SELECT m.*, u.nickname AS sender_name
           FROM messages m JOIN users u ON m.sender_id = u.id
           WHERE m.conversation_id = ? ORDER BY m.created_at ASC""",
        (conversation_id,),
    ).fetchall()
    conn.execute(
        "UPDATE messages SET is_read = 1 WHERE conversation_id = ? AND sender_id != ?",
        (conversation_id, g.user["id"]),
    )
    conn.commit()
    conn.close()

    other_name = conv["seller_name"] if g.user["id"] == conv["buyer_id"] else conv["buyer_name"]
    return render_template("chat.html", conv=conv, messages=msgs, other_name=other_name)


@app.route("/api/chat/<int:conversation_id>/messages")
@login_required
@verified_required
def api_chat_messages(conversation_id):
    conn = db.get_db()
    conv = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not conv or g.user["id"] not in (conv["buyer_id"], conv["seller_id"]):
        conn.close()
        return jsonify({"error": "forbidden"}), 403
    msgs = conn.execute(
        """SELECT m.*, u.nickname AS sender_name
           FROM messages m JOIN users u ON m.sender_id = u.id
           WHERE m.conversation_id = ? ORDER BY m.created_at ASC""",
        (conversation_id,),
    ).fetchall()
    conn.close()
    return jsonify([dict(m) for m in msgs])


@app.route("/profile")
@login_required
def profile():
    conn = db.get_db()
    posts = conn.execute(
        "SELECT * FROM posts WHERE user_id = ? ORDER BY created_at DESC",
        (g.user["id"],),
    ).fetchall()
    # 我的接单：当前用户作为接单方、且为跑腿需求的会话
    accepted = conn.execute(
        """SELECT p.id, p.title, p.price, p.service_fee, p.status,
                  c.id AS conversation_id, u.nickname AS publisher_name
           FROM conversations c
           JOIN posts p ON c.post_id = p.id
           JOIN users u ON p.user_id = u.id
           WHERE c.buyer_id = ? AND p.type = '跑腿需求'
           ORDER BY c.last_message_at DESC""",
        (g.user["id"],),
    ).fetchall()
    conn.close()
    return render_template("profile.html", posts=posts, accepted=accepted)


@app.route("/admin/review", methods=["GET", "POST"])
@login_required
@admin_required
def admin_review():
    conn = db.get_db()
    if request.method == "POST":
        post_id = request.form.get("post_id")
        action = request.form.get("action")
        if action == "approve":
            conn.execute("UPDATE posts SET status = 'approved' WHERE id = ?", (post_id,))
            flash("已通过审核", "success")
        elif action == "reject":
            conn.execute("UPDATE posts SET status = 'rejected' WHERE id = ?", (post_id,))
            flash("已驳回", "info")
        elif action == "remove":
            # 强制下架：保留数据，仅改状态，首页不再展示
            conn.execute("UPDATE posts SET status = 'admin_removed' WHERE id = ?", (post_id,))
            flash("已强制下架", "info")
        conn.commit()
    pending = conn.execute(
        """SELECT p.*, u.nickname AS author_name
           FROM posts p JOIN users u ON p.user_id = u.id
           WHERE p.status = 'pending' ORDER BY p.created_at ASC"""
    ).fetchall()
    live_posts = conn.execute(
        """SELECT p.*, u.nickname AS author_name
           FROM posts p JOIN users u ON p.user_id = u.id
           WHERE p.status IN ('approved', 'taken') ORDER BY p.created_at DESC"""
    ).fetchall()
    conn.close()
    return render_template("admin_review.html", pending=pending, live_posts=live_posts)


@app.route("/admin/words", methods=["GET", "POST"])
@login_required
@admin_required
def admin_words():
    conn = db.get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            word = request.form.get("word", "").strip()
            if word:
                try:
                    conn.execute("INSERT INTO banned_words (word) VALUES (?)", (word,))
                    conn.commit()
                    flash(f"已添加违规词：{word}", "success")
                except Exception:
                    flash("该词已存在", "warning")
        elif action == "delete":
            word_id = request.form.get("word_id")
            conn.execute("DELETE FROM banned_words WHERE id = ?", (word_id,))
            conn.commit()
            flash("已删除", "info")
    words = conn.execute("SELECT * FROM banned_words ORDER BY id").fetchall()
    conn.close()
    return render_template("admin_words.html", words=words)


@app.route("/admin/dashboard")
@login_required
@admin_required
def admin_dashboard():
    conn = db.get_db()

    def scalar(sql, params=()):
        row = conn.execute(sql, params).fetchone()
        return row[0] if row and row[0] is not None else 0

    stats = {
        "users": scalar("SELECT COUNT(*) FROM users"),
        "verified_users": scalar("SELECT COUNT(*) FROM users WHERE verified = 1"),
        "posts": scalar("SELECT COUNT(*) FROM posts"),
        "secondhand": scalar("SELECT COUNT(*) FROM posts WHERE type = '二手商品'"),
        "errand": scalar("SELECT COUNT(*) FROM posts WHERE type = '跑腿需求'"),
        "pending": scalar("SELECT COUNT(*) FROM posts WHERE status = 'pending'"),
        "approved": scalar("SELECT COUNT(*) FROM posts WHERE status = 'approved'"),
        "rejected": scalar("SELECT COUNT(*) FROM posts WHERE status = 'rejected'"),
        "top_count": scalar("SELECT COUNT(*) FROM orders WHERE type = '置顶'"),
        "top_income": scalar("SELECT SUM(amount) FROM orders WHERE type = '置顶'"),
        "fee_income": scalar("SELECT SUM(service_fee) FROM posts WHERE type = '跑腿需求' AND status = 'approved'"),
    }
    stats["total_income"] = round((stats["top_income"] or 0) + (stats["fee_income"] or 0), 2)

    # 近 7 天发布趋势
    today = datetime.now().date()
    trend = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        prefix = day.isoformat()
        count = scalar("SELECT COUNT(*) FROM posts WHERE created_at LIKE ?", (prefix + "%",))
        trend.append({"date": day.strftime("%m-%d"), "count": count})
    max_count = max((t["count"] for t in trend), default=0) or 1

    recent_orders = conn.execute(
        """SELECT o.*, u.nickname AS user_name, p.title AS post_title
           FROM orders o
           JOIN users u ON o.user_id = u.id
           LEFT JOIN posts p ON o.post_id = p.id
           ORDER BY o.created_at DESC LIMIT 10"""
    ).fetchall()
    conn.close()
    return render_template(
        "admin_dashboard.html",
        stats=stats, trend=trend, max_count=max_count, recent_orders=recent_orders,
    )


if __name__ == "__main__":
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    db.init_db()
    print("\n" + "=" * 50)
    print("  Campus Hub 校园资源流通平台")
    print("  访问地址: http://127.0.0.1:5000")
    print("=" * 50)
    print("\n演示账号（密码均为 123456）：")
    print("  管理员:   admin@campus.edu")
    print("  已认证1:  icedam@stu.edu   (冰美式续命中)")
    print("  已认证2:  luna@stu.edu     (Luna)")
    print("  已认证3:  ddlrush@stu.edu  (今天也在赶DDL)")
    print("  未认证:   chuqi@stu.edu    (初七)")
    print("=" * 50 + "\n")
    app.run(debug=True, port=5000)
