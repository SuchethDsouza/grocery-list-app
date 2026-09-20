import os
import secrets
from datetime import datetime, timedelta
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify

# Load variables from a .env file in the project root, if one exists.
# This works no matter how the app is started (Run button, Debug button,
# or a plain terminal) — unlike PyCharm Run Configuration env vars, which
# only apply when launched that exact way.
load_dotenv()
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key-change-in-production")


def _database_uri():
    """Use hosted Postgres in production, local SQLite in development.

    Render/Neon supply DATABASE_URL. If it isn't set (i.e. you're running
    locally), fall back to the SQLite file so nothing about local dev changes.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///" + os.path.join(basedir, "grocery.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


app.config["SQLALCHEMY_DATABASE_URI"] = _database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Neon (and most serverless Postgres) suspend the database when idle, which
# silently kills pooled connections. pool_pre_ping tests a connection before
# handing it out so the first request after an idle period doesn't 500.
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql://"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

# Cookie hardening for a publicly hosted app. SESSION_COOKIE_SECURE requires
# HTTPS to work at all — forcing it on unconditionally would silently break
# login during local development over plain http://127.0.0.1:5000. Render
# (and DATABASE_URL being set) is our signal that we're actually deployed.
IS_PRODUCTION = bool(os.environ.get("DATABASE_URL", "").strip())
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Mail config — Brevo transactional email API over HTTPS (port 443).
# NOT SMTP: Render's free tier blocks outbound traffic on ports 25/465/587
# entirely, so smtplib can never connect there. Brevo's API is a normal
# HTTPS POST, so it works the same whether this runs locally or on Render.
app.config["BREVO_API_KEY"] = os.environ.get("BREVO_API_KEY", "")
app.config["BREVO_SENDER_EMAIL"] = os.environ.get("BREVO_SENDER_EMAIL", "")
app.config["BREVO_SENDER_NAME"] = os.environ.get("BREVO_SENDER_NAME", "Pantry List")

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please sign in to see your pantry."
login_manager.login_message_category = "info"

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    whatsapp_number = db.Column(db.String(20), nullable=True)  # E.164 format e.g. 91XXXXXXXXXX
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reset_token = db.Column(db.String(64), nullable=True, index=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)

    lists = db.relationship("GroceryList", backref="owner", lazy=True,
                             cascade="all, delete-orphan")
    custom_items = db.relationship("Item", backref="added_by", lazy=True)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    icon = db.Column(db.String(10), nullable=False, default="\U0001F6D2")  # emoji glyph
    sort_order = db.Column(db.Integer, default=0)

    items = db.relationship("Item", backref="category", lazy=True)


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    default_unit = db.Column(db.String(20), nullable=False, default="pcs")
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # null = shared/master item

    __table_args__ = (
        db.UniqueConstraint("name", "category_id", "user_id", name="uq_item_per_owner"),
    )


class HiddenItem(db.Model):
    """A shared/master item a given household has chosen to hide from their own
    view. Never affects the item for any other household."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id", "item_id", name="uq_hidden_per_user"),
    )


class GroceryList(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="draft")  # draft | sent
    sent_via = db.Column(db.String(20), nullable=True)   # whatsapp | email | both
    recipient = db.Column(db.String(120), nullable=True)

    entries = db.relationship("ListEntry", backref="grocery_list", lazy=True,
                               cascade="all, delete-orphan")


class ListEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey("grocery_list.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id"), nullable=False)
    quantity = db.Column(db.String(20), nullable=False, default="1")
    note = db.Column(db.String(140), nullable=True)

    item = db.relationship("Item")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def _send_plain_email(to, subject, body):
    """Send a plain-text email via Brevo's HTTPS API.
    Returns (ok: bool, error_message: str | None) — NEVER raises, so a
    calling route can always return valid JSON instead of crashing into
    an HTML error page (which is what happened with smtplib timeouts)."""
    api_key = app.config["BREVO_API_KEY"]
    sender_email = app.config["BREVO_SENDER_EMAIL"]

    if not api_key or not sender_email:
        return False, (
            "Email sending isn't configured yet. Set BREVO_API_KEY and "
            "BREVO_SENDER_EMAIL environment variables (see README) to enable this."
        )

    payload = {
        "sender": {"name": app.config["BREVO_SENDER_NAME"], "email": sender_email},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": body,
    }

    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=10,  # fail fast rather than let the request hang
        )
    except requests.exceptions.RequestException as exc:
        return False, f"Could not reach the email service: {exc}"

    if resp.status_code in (200, 201):
        return True, None

    try:
        err = resp.json().get("message", resp.text)
    except ValueError:
        err = resp.text
    return False, f"Email service error ({resp.status_code}): {err}"


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        whatsapp_number = request.form.get("whatsapp_number", "").strip()

        errors = []
        if len(name) < 2:
            errors.append("Name must be at least 2 characters.")
        if "@" not in email or "." not in email.split("@")[-1]:
            errors.append("Enter a valid email address.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if whatsapp_number and not whatsapp_number.isdigit():
            errors.append("WhatsApp number should contain digits only, with country code (e.g. 91XXXXXXXXXX).")
        if User.query.filter_by(email=email).first():
            errors.append("An account with this email already exists.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("signup.html", form=request.form)

        user = User(name=name, email=email, whatsapp_number=whatsapp_number or None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash(f"Welcome, {name}! Your pantry is ready.", "success")
        return redirect(url_for("dashboard"))

    return render_template("signup.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=remember)
            return redirect(request.args.get("next") or url_for("dashboard"))

        flash("Incorrect email or password.", "error")
        return render_template("login.html", email=email)

    return render_template("login.html", email="")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()

        # Always show the same message whether or not the account exists,
        # so this form can't be used to discover which emails are registered.
        generic_msg = "If that email has an account, a reset link is on its way."

        if user:
            if not app.config["BREVO_API_KEY"] or not app.config["BREVO_SENDER_EMAIL"]:
                flash("Email sending isn't configured yet. Set BREVO_API_KEY and BREVO_SENDER_EMAIL "
                      "environment variables (see README) to enable password resets.", "error")
                return render_template("forgot_password.html")

            user.reset_token = secrets.token_urlsafe(32)
            user.reset_token_expires = datetime.utcnow() + timedelta(minutes=30)
            db.session.commit()

            reset_url = url_for("reset_password", token=user.reset_token, _external=True)
            # Result intentionally not surfaced here — this route always shows the
            # same generic message below, so a failed send doesn't leak whether
            # the account exists. (Check Render logs if resets seem to silently fail.)
            _send_plain_email(
                to=user.email,
                subject="Reset your Pantry List password",
                body=f"Hi {user.name},\n\n"
                     f"Tap the link below to set a new password. It expires in 30 minutes.\n\n"
                     f"{reset_url}\n\n"
                     f"If you didn't request this, you can ignore this email.",
            )

        flash(generic_msg, "info")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    user = User.query.filter_by(reset_token=token).first()
    token_valid = bool(user and user.reset_token_expires and user.reset_token_expires > datetime.utcnow())

    if not token_valid:
        flash("That reset link is invalid or has expired. Request a new one below.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("reset_password.html", token=token)

        user.set_password(password)
        user.reset_token = None
        user.reset_token_expires = None
        db.session.commit()
        flash("Password updated — sign in with your new password.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out. See you next time!", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Core app routes
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    categories = Category.query.order_by(Category.sort_order).all()
    hidden_ids = {h.item_id for h in HiddenItem.query.filter_by(user_id=current_user.id).all()}

    # shared master items + this user's own custom items, minus anything they've hidden
    items_by_category = {}
    for cat in categories:
        cat_items = Item.query.filter(
            Item.category_id == cat.id,
            db.or_(Item.user_id == None, Item.user_id == current_user.id)  # noqa: E711
        ).order_by(Item.name).all()
        items_by_category[cat.id] = [i for i in cat_items if i.id not in hidden_ids]

    draft = GroceryList.query.filter_by(user_id=current_user.id, status="draft").first()
    draft_entries = draft.entries if draft else []
    draft_item_ids = {e.item_id for e in draft_entries}
    draft_quantities = {e.item_id: e.quantity for e in draft_entries}

    # Frequently added: items that appear most often across this user's sent lists.
    freq_rows = (
        db.session.query(Item, db.func.count(ListEntry.id).label("uses"))
        .join(ListEntry, ListEntry.item_id == Item.id)
        .join(GroceryList, GroceryList.id == ListEntry.list_id)
        .filter(GroceryList.user_id == current_user.id, GroceryList.status == "sent")
        .group_by(Item.id)
        .order_by(db.desc("uses"))
        .limit(6)
        .all()
    )
    frequently_added = [row[0] for row in freq_rows if row[0].id not in hidden_ids]

    return render_template(
        "dashboard.html",
        categories=categories,
        items_by_category=items_by_category,
        draft_entries=draft_entries,
        draft_item_ids=draft_item_ids,
        draft_quantities=draft_quantities,
        frequently_added=frequently_added,
    )


@app.route("/item/add", methods=["POST"])
@login_required
def add_item():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    category_id = data.get("category_id")
    unit = (data.get("unit") or "pcs").strip() or "pcs"

    if len(name) < 2:
        return jsonify({"ok": False, "error": "Item name must be at least 2 characters."}), 400
    if not category_id or not Category.query.get(category_id):
        return jsonify({"ok": False, "error": "Choose a valid category."}), 400

    existing = Item.query.filter(
        db.func.lower(Item.name) == name.lower(),
        Item.category_id == category_id,
        db.or_(Item.user_id == None, Item.user_id == current_user.id)  # noqa: E711
    ).first()
    if existing:
        return jsonify({"ok": False, "error": f'"{name}" is already in your list of items.'}), 400

    item = Item(name=name, category_id=category_id, default_unit=unit, user_id=current_user.id)
    db.session.add(item)
    db.session.flush()

    quantity = str(data.get("quantity") or "1").strip() or "1"

    draft = GroceryList.query.filter_by(user_id=current_user.id, status="draft").first()
    if not draft:
        draft = GroceryList(user_id=current_user.id, status="draft")
        db.session.add(draft)
        db.session.flush()
    db.session.add(ListEntry(list_id=draft.id, item_id=item.id, quantity=quantity))
    db.session.commit()

    return jsonify({
        "ok": True,
        "item": {"id": item.id, "name": item.name, "unit": item.default_unit,
                  "category_id": item.category_id, "quantity": quantity}
    })


@app.route("/item/delete/<int:item_id>", methods=["POST"])
@login_required
def delete_item(item_id):
    item = Item.query.get(item_id)

    # Only the household that created a custom item may delete it — shared/master
    # catalog items (user_id is None) are never deletable this way.
    if not item or item.user_id != current_user.id:
        return jsonify({"ok": False, "error": "Item not found."}), 404

    used_in_sent_list = (
        db.session.query(ListEntry.id)
        .join(GroceryList, ListEntry.list_id == GroceryList.id)
        .filter(ListEntry.item_id == item.id, GroceryList.status == "sent")
        .first()
    )
    if used_in_sent_list:
        return jsonify({"ok": False, "error": "Can't delete — this item appears in your sent history."}), 400

    # Safe to drop: not on any current or past sent list. Clear it from any
    # draft first (SQLite here won't enforce the FK for us), then delete it.
    ListEntry.query.filter_by(item_id=item.id).delete()
    db.session.delete(item)
    db.session.commit()

    return jsonify({"ok": True})


@app.route("/item/hide/<int:item_id>", methods=["POST"])
@login_required
def hide_item(item_id):
    item = Item.query.get(item_id)
    if not item:
        return jsonify({"ok": False, "error": "Item not found."}), 404

    already = HiddenItem.query.filter_by(user_id=current_user.id, item_id=item.id).first()
    if not already:
        db.session.add(HiddenItem(user_id=current_user.id, item_id=item.id))

    # Also drop it from today's draft, if it's there — no point leaving a hidden
    # item sitting on the active list where you can no longer see or edit it.
    draft = GroceryList.query.filter_by(user_id=current_user.id, status="draft").first()
    if draft:
        ListEntry.query.filter_by(list_id=draft.id, item_id=item.id).delete()

    db.session.commit()
    return jsonify({"ok": True})


@app.route("/item/unhide/<int:item_id>", methods=["POST"])
@login_required
def unhide_item(item_id):
    HiddenItem.query.filter_by(user_id=current_user.id, item_id=item_id).delete()
    db.session.commit()
    flash("Item restored to your list.", "success")
    return redirect(url_for("history"))


@app.route("/list/toggle", methods=["POST"])
@login_required
def toggle_list_item():
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    quantity = str(data.get("quantity") or "1").strip()
    note = (data.get("note") or "").strip()[:140]

    item = Item.query.get(item_id)
    if not item:
        return jsonify({"ok": False, "error": "Item not found."}), 404
    if not quantity or quantity == "0":
        quantity = "1"

    draft = GroceryList.query.filter_by(user_id=current_user.id, status="draft").first()
    if not draft:
        draft = GroceryList(user_id=current_user.id, status="draft")
        db.session.add(draft)
        db.session.flush()

    entry = ListEntry.query.filter_by(list_id=draft.id, item_id=item.id).first()
    if entry:
        db.session.delete(entry)
        db.session.commit()
        return jsonify({"ok": True, "selected": False})
    else:
        entry = ListEntry(list_id=draft.id, item_id=item.id, quantity=quantity, note=note)
        db.session.add(entry)
        db.session.commit()
        return jsonify({"ok": True, "selected": True})


@app.route("/list/update-quantity", methods=["POST"])
@login_required
def update_quantity():
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    action = data.get("action")  # "increment" | "decrement"

    draft = GroceryList.query.filter_by(user_id=current_user.id, status="draft").first()
    if not draft:
        return jsonify({"ok": False, "error": "Your list is empty."}), 404

    entry = ListEntry.query.filter_by(list_id=draft.id, item_id=item_id).first()
    if not entry:
        return jsonify({"ok": False, "error": "That item isn't on your list."}), 404

    try:
        current_qty = float(entry.quantity)
    except (TypeError, ValueError):
        current_qty = 1

    # Whole-unit items (kg, L, pack, etc.) step by 1; keep it simple and predictable.
    step = 1
    if action == "increment":
        current_qty += step
    elif action == "decrement":
        current_qty -= step
    else:
        return jsonify({"ok": False, "error": "Unknown action."}), 400

    if current_qty <= 0:
        db.session.delete(entry)
        db.session.commit()
        return jsonify({"ok": True, "removed": True})

    entry.quantity = str(int(current_qty)) if current_qty == int(current_qty) else str(current_qty)
    db.session.commit()
    return jsonify({"ok": True, "removed": False, "quantity": entry.quantity})


@app.route("/list/clear", methods=["POST"])
@login_required
def clear_list():
    draft = GroceryList.query.filter_by(user_id=current_user.id, status="draft").first()
    if draft:
        db.session.delete(draft)
        db.session.commit()
    return jsonify({"ok": True})


def _format_list_text(draft):
    lines = [f"\U0001F6D2 Grocery list from {current_user.name} ({datetime.now().strftime('%d %b, %I:%M %p')})", ""]
    for entry in draft.entries:
        note = f" — {entry.note}" if entry.note else ""
        lines.append(f"• {entry.item.name} ({entry.quantity} {entry.item.default_unit}){note}")
    lines.append("")
    lines.append("Sent via Pantry List")
    return "\n".join(lines)


@app.route("/list/whatsapp-link", methods=["POST"])
@login_required
def whatsapp_link():
    data = request.get_json(silent=True) or {}
    number = (data.get("number") or current_user.whatsapp_number or "").strip()
    if not number.isdigit() or len(number) < 8:
        return jsonify({"ok": False, "error": "Enter a valid WhatsApp number with country code, digits only."}), 400

    draft = GroceryList.query.filter_by(user_id=current_user.id, status="draft").first()
    if not draft or not draft.entries:
        return jsonify({"ok": False, "error": "Your list is empty — select a few items first."}), 400

    text = _format_list_text(draft)
    link = f"https://wa.me/{number}?text={quote(text)}"

    draft.status = "sent"
    draft.sent_via = "whatsapp"
    draft.recipient = number
    db.session.commit()

    return jsonify({"ok": True, "link": link})


@app.route("/list/send-email", methods=["POST"])
@login_required
def send_email():
    data = request.get_json(silent=True) or {}
    recipient = (data.get("email") or "").strip().lower()

    if "@" not in recipient or "." not in recipient.split("@")[-1]:
        return jsonify({"ok": False, "error": "Enter a valid email address."}), 400

    draft = GroceryList.query.filter_by(user_id=current_user.id, status="draft").first()
    if not draft or not draft.entries:
        return jsonify({"ok": False, "error": "Your list is empty — select a few items first."}), 400

    text = _format_list_text(draft)

    ok, error = _send_plain_email(
        to=recipient,
        subject=f"Grocery list from {current_user.name}",
        body=text,
    )
    if not ok:
        return jsonify({"ok": False, "error": error}), 502

    draft.status = "sent"
    draft.sent_via = "email"
    draft.recipient = recipient
    db.session.commit()

    return jsonify({"ok": True})


@app.route("/history")
@login_required
def history():
    lists = GroceryList.query.filter_by(user_id=current_user.id, status="sent") \
        .order_by(GroceryList.created_at.desc()).all()
    hidden_items = (
        db.session.query(Item)
        .join(HiddenItem, HiddenItem.item_id == Item.id)
        .filter(HiddenItem.user_id == current_user.id)
        .order_by(Item.name)
        .all()
    )
    return render_template("history.html", lists=lists, hidden_items=hidden_items)


@app.route("/history/reuse/<int:list_id>", methods=["POST"])
@login_required
def reuse_list(list_id):
    old_list = GroceryList.query.filter_by(id=list_id, user_id=current_user.id, status="sent").first()
    if not old_list:
        flash("That list could not be found.", "error")
        return redirect(url_for("history"))

    draft = GroceryList.query.filter_by(user_id=current_user.id, status="draft").first()
    if draft:
        ListEntry.query.filter_by(list_id=draft.id).delete()
    else:
        draft = GroceryList(user_id=current_user.id, status="draft")
        db.session.add(draft)
        db.session.flush()

    for entry in old_list.entries:
        db.session.add(ListEntry(list_id=draft.id, item_id=entry.item_id, quantity=entry.quantity, note=entry.note))

    db.session.commit()
    flash("List loaded into Today's List — review and send when ready.", "success")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# CLI helper: seed the master item list
# ---------------------------------------------------------------------------

def seed_data():
    if Category.query.first():
        return  # already seeded

    catalog = {
        ("Vegetables", "\U0001F955", 1): [
            ("Onion", "kg"), ("Tomato", "kg"), ("Potato", "kg"), ("Garlic", "g"),
            ("Ginger", "g"), ("Green Chilli", "g"), ("Carrot", "kg"), ("Beans", "kg"),
            ("Capsicum", "pcs"), ("Coriander Leaves", "bunch"), ("Curry Leaves", "bunch"),
        ],
        ("Fruits", "\U0001F34C", 2): [
            ("Banana", "dozen"), ("Apple", "kg"), ("Orange", "kg"), ("Lemon", "pcs"),
        ],
        ("Dairy", "\U0001F95B", 3): [
            ("Milk", "L"), ("Curd", "pack"), ("Butter", "pack"), ("Paneer", "g"),
            ("Cheese", "pack"),
        ],
        ("Grains & Staples", "\U0001F33E", 4): [
            ("Rice", "kg"), ("Wheat Flour", "kg"), ("Toor Dal", "kg"), ("Moong Dal", "kg"),
            ("Sugar", "kg"), ("Salt", "kg"), ("Cooking Oil", "L"),
        ],
        ("Spices", "\U0001F336", 5): [
            ("Turmeric Powder", "g"), ("Chilli Powder", "g"), ("Coriander Powder", "g"),
            ("Garam Masala", "g"), ("Mustard Seeds", "g"), ("Cumin Seeds", "g"),
        ],
        ("Bakery & Snacks", "\U0001F35E", 6): [
            ("Bread", "pack"), ("Biscuits", "pack"), ("Eggs", "dozen"),
        ],
        ("Household", "\U0001F9FA", 7): [
            ("Dish Soap", "bottle"), ("Detergent", "kg"), ("Tea Powder", "pack"),
            ("Coffee Powder", "pack"),
        ],
    }

    for (cat_name, icon, order), items in catalog.items():
        cat = Category(name=cat_name, icon=icon, sort_order=order)
        db.session.add(cat)
        db.session.flush()
        for item_name, unit in items:
            db.session.add(Item(name=item_name, default_unit=unit, category_id=cat.id, user_id=None))

    db.session.commit()
    print("Seeded categories and master item list.")


with app.app_context():
    db.create_all()
    seed_data()


if __name__ == "__main__":
    # Local development only. On Render, gunicorn imports `app` directly and
    # this block never runs — so debug mode can't leak into production.
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
