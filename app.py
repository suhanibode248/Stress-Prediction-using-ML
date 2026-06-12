"""
NeuroScan — Flask backend v4
Key fix: Claude Vision now correctly separates EMOTIONAL STATE from PHYSIOLOGICAL STRESS.
Laughing/happy = low face_score. Angry/fearful = high face_score.
"""
import os, base64, anthropic, json, re
from datetime import datetime, timedelta
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session, flash)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bcrypt
import ssl
from sqlalchemy.pool import NullPool
from model import calculate_stress
from dotenv import load_dotenv

load_dotenv()

# ── App setup ─────────────────────────────────────────────────────────────
app = Flask(__name__)
# ── DB URL: use Postgres on Vercel (DATABASE_URL), fallback to SQLite locally ──
db_url = os.environ.get("DATABASE_URL", "sqlite:///neuroscan.db")
# Vercel/Supabase/Neon give "postgres://" or "postgresql://" — pg8000 needs "postgresql+pg8000://"
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+pg8000://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+pg8000://", 1)

# pg8000 doesn't understand "?sslmode=require" (psycopg2-style) — strip it.
# SSL is configured separately below via connect_args/ssl_context.
if "?" in db_url:
    base_url, query = db_url.split("?", 1)
    # Drop sslmode and channel_binding params (psycopg2/libpq specific, pg8000 chokes on them)
    params = [p for p in query.split("&") if not p.startswith(("sslmode=", "channel_binding="))]
    db_url = base_url + ("?" + "&".join(params) if params else "")

app.config.update(
    SECRET_KEY               = os.environ.get("SECRET_KEY", "neuroscan-dev-change-me"),
    SQLALCHEMY_DATABASE_URI  = db_url,
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    PERMANENT_SESSION_LIFETIME = timedelta(days=7),
    SESSION_COOKIE_SECURE    = os.environ.get("VERCEL") is not None,
    SESSION_COOKIE_SAMESITE  = "Lax",
)

# ── pg8000 + hosted Postgres (Neon/Supabase) SSL & pooling config ──────────
# Serverless functions are short-lived — disable SQLAlchemy's own pooling
# (NullPool) and let pg8000 negotiate SSL via an explicit SSLContext, since
# pg8000 doesn't accept the libpq-style "?sslmode=require" query param.
if "pg8000" in db_url:
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "poolclass": NullPool,
        "connect_args": {
            "ssl_context": ssl_ctx,
        },
    }

db            = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ── Rate limiter: use Upstash Redis on Vercel, memory locally ──────────────
redis_url = os.environ.get("UPSTASH_REDIS_URL") or os.environ.get("REDIS_URL")
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["300 per day", "60 per hour"],
    storage_uri=redis_url if redis_url else "memory://",
)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))


# ── DB Models ─────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(100), nullable=False)
    email         = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    baseline      = db.Column(db.Float, default=0.0)
    sessions      = db.relationship("ScanSession", backref="user", lazy=True)

    def set_password(self, pw: str):
        self.password_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

    def check_password(self, pw: str) -> bool:
        return bcrypt.checkpw(pw.encode(), self.password_hash.encode())

    @property
    def initials(self):
        parts = self.name.strip().split()
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


class ScanSession(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    started_at    = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at      = db.Column(db.DateTime)
    avg_stress    = db.Column(db.Float, default=0.0)
    peak_stress   = db.Column(db.Float, default=0.0)
    readings      = db.Column(db.Integer, default=0)
    readings_json = db.Column(db.Text, default="[]")


class Reading(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("scan_session.id"))
    user_id    = db.Column(db.Integer, db.ForeignKey("user.id"))
    timestamp  = db.Column(db.DateTime, default=datetime.utcnow)
    stress     = db.Column(db.Float)
    focus      = db.Column(db.Float)
    fatigue    = db.Column(db.Float)
    anxiety    = db.Column(db.Float)
    face_score = db.Column(db.Float)
    blink      = db.Column(db.Float)
    voice      = db.Column(db.Float)
    emotion    = db.Column(db.String(50))
    level      = db.Column(db.String(50))


@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))


# ── Face Analysis — lightweight fallback (no OpenCV, Vercel-friendly) ─────
def analyze_face_cv(image_data: str) -> float:
    """
    Fallback when Claude Vision is disabled/unavailable.
    No heavy CV dependencies — just returns a neutral baseline.
    Claude Vision should be the primary path (use_claude=True).
    """
    return 50.0


# ── Face Analysis — Claude Vision (FIXED prompt) ──────────────────────────
CLAUDE_VISION_PROMPT = """You are a biometric stress analysis AI. Your job is to estimate PHYSIOLOGICAL STRESS from facial cues — NOT emotional expression.

CRITICAL RULES:
1. Laughing, smiling, joy = LOW stress (face_score 5-20). Happy people are NOT stressed.
2. Neutral relaxed face = LOW-MEDIUM stress (face_score 15-35).
3. Frowning, brow furrowing, jaw tension, tight lips = MEDIUM stress (face_score 40-65).
4. Visible distress, fear, crying, panic, extreme anger = HIGH stress (face_score 70-95).
5. Forced smile with tense eyes/brow = MEDIUM stress (face_score 35-55).

STRESS INDICATORS to look for (physiological, not emotional):
- Brow furrowing / corrugator muscle activation
- Jaw clenching / masseter tension
- Eye strain / squinting
- Pursed or tight lips
- Pale or flushed skin tone
- Visible neck/shoulder tension

EMOTION vs STRESS separation:
- emotion field = the PRIMARY emotion displayed (happy, sad, angry, fearful, surprised, disgusted, neutral, laughing)
- face_score = the physiological STRESS level (independent of emotion — a laughing person has low stress)
- tension = overall muscle tension (low/medium/high)

Analyze this face and return ONLY valid JSON (no markdown, no explanation):
{"face_score": <0-100>, "emotion": "<primary emotion>", "tension": "<low|medium|high>", "confidence": <0-100>, "stress_indicators": ["<list of observed stress signs, empty array if none>"], "emotional_valence": "<positive|neutral|negative>"}

If no face is visible: {"face_score": 50, "emotion": "unknown", "tension": "medium", "confidence": 20, "stress_indicators": [], "emotional_valence": "neutral"}"""


def analyze_face_claude(image_data: str) -> dict:
    try:
        b64 = image_data.split(",")[1] if "," in image_data else image_data
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=400,
            messages=[{"role": "user", "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}
                },
                {
                    "type": "text",
                    "text": CLAUDE_VISION_PROMPT
                }
            ]}]
        )
        text = re.sub(r"```json|```", "", msg.content[0].text.strip()).strip()
        result = json.loads(text)

        # Safety clamp: if emotion is happy/laughing but face_score is high, correct it
        emotion = result.get("emotion", "neutral").lower()
        face_score = result.get("face_score", 50)
        valence = result.get("emotional_valence", "neutral")

        POSITIVE_EMOTIONS = {"happy", "laughing", "amused", "joyful", "excited", "content", "smiling"}
        if emotion in POSITIVE_EMOTIONS and face_score > 30:
            # Cap stress at 30 for genuinely positive emotions unless tension says otherwise
            tension = result.get("tension", "low")
            if tension == "low":
                result["face_score"] = min(face_score, 20)
            elif tension == "medium":
                result["face_score"] = min(face_score, 35)
            # high tension + happy = forced smile, keep as-is

        print(f"[Claude Vision] emotion={emotion} face_score={result['face_score']} tension={result.get('tension')} indicators={result.get('stress_indicators', [])}")
        return result

    except Exception as e:
        print(f"[Claude Vision ERROR] {e}")
        return {
            "face_score": 50, "emotion": "unknown",
            "tension": "medium", "confidence": 50,
            "stress_indicators": [], "emotional_valence": "neutral"
        }


# ── Routes ────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    """Debug endpoint — check DB connectivity and env vars without exposing secrets."""
    status = {"app": "ok"}
    try:
        db.session.execute(db.text("SELECT 1"))
        status["database"] = "ok"
    except Exception as e:
        status["database"] = f"ERROR: {str(e)}"
    status["database_url_set"] = bool(os.environ.get("DATABASE_URL"))
    status["anthropic_key_set"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    status["secret_key_set"] = bool(os.environ.get("SECRET_KEY"))
    status["redis_set"] = bool(os.environ.get("UPSTASH_REDIS_URL") or os.environ.get("REDIS_URL"))
    return jsonify(status)


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        try:
            data  = request.get_json(force=True) or {}
            email = data.get("email", "").strip().lower()
            pw    = data.get("password", "")
            user  = User.query.filter_by(email=email).first()
            if user and user.check_password(pw):
                login_user(user, remember=data.get("remember", False))
                return jsonify({"ok": True, "redirect": url_for("dashboard")})
            return jsonify({"ok": False, "error": "Invalid email or password"}), 401
        except Exception as e:
            print(f"[LOGIN ERROR] {e}")
            return jsonify({"ok": False, "error": f"Server error: {str(e)}"}), 500
    return render_template("login.html")


@app.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
def register():
    try:
        data  = request.get_json(force=True) or {}
        name  = data.get("name", "").strip()
        email = data.get("email", "").strip().lower()
        pw    = data.get("password", "")
        if not name or not email or len(pw) < 6:
            return jsonify({"ok": False, "error": "All fields required; password ≥ 6 chars"}), 400
        if User.query.filter_by(email=email).first():
            return jsonify({"ok": False, "error": "Email already registered"}), 409
        user = User(name=name, email=email)
        user.set_password(pw)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return jsonify({"ok": True, "redirect": url_for("dashboard")})
    except Exception as e:
        print(f"[REGISTER ERROR] {e}")
        return jsonify({"ok": False, "error": f"Server error: {str(e)}"}), 500


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    since = datetime.utcnow() - timedelta(days=28)
    daily = {}
    for r in Reading.query.filter(Reading.user_id==current_user.id, Reading.timestamp>=since).all():
        key = r.timestamp.strftime("%Y-%m-%d")
        daily.setdefault(key, []).append(r.stress)
    heatmap = {k: round(sum(v)/len(v), 1) for k, v in daily.items()}

    sessions      = ScanSession.query.filter_by(user_id=current_user.id).order_by(ScanSession.started_at.desc()).limit(10).all()
    total_sessions = ScanSession.query.filter_by(user_id=current_user.id).count()
    week_sessions  = ScanSession.query.filter(
        ScanSession.user_id==current_user.id,
        ScanSession.started_at >= datetime.utcnow()-timedelta(days=7)
    ).count()

    return render_template("dashboard.html",
        user=current_user,
        heatmap_json=json.dumps(heatmap),
        sessions=sessions,
        total_sessions=total_sessions,
        week_sessions=week_sessions,
    )


@app.route("/history")
@login_required
def history():
    sessions = ScanSession.query.filter_by(user_id=current_user.id).order_by(ScanSession.started_at.desc()).all()
    return render_template("history.html", user=current_user, sessions=sessions)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        data   = request.get_json(force=True) or {}
        action = data.get("action")
        if action == "update_profile":
            current_user.name = data.get("name", current_user.name).strip()
            db.session.commit()
            return jsonify({"ok": True, "message": "Profile updated"})
        if action == "change_password":
            old = data.get("old_password", "")
            new = data.get("new_password", "")
            if not current_user.check_password(old):
                return jsonify({"ok": False, "error": "Current password incorrect"}), 400
            if len(new) < 6:
                return jsonify({"ok": False, "error": "New password must be ≥ 6 chars"}), 400
            current_user.set_password(new)
            db.session.commit()
            return jsonify({"ok": True, "message": "Password changed"})
    return render_template("settings.html", user=current_user)


# ── Session API ───────────────────────────────────────────────────────────
@app.route("/api/session/start", methods=["POST"])
@login_required
def session_start():
    s = ScanSession(user_id=current_user.id)
    db.session.add(s)
    db.session.commit()
    session["active_session_id"] = s.id
    return jsonify({"ok": True, "session_id": s.id})


@app.route("/api/session/stop", methods=["POST"])
@login_required
def session_stop():
    sid = session.get("active_session_id")
    if not sid:
        return jsonify({"ok": False}), 400
    s = db.session.get(ScanSession, sid)
    if s and s.user_id == current_user.id:
        data = request.get_json(force=True) or {}
        s.ended_at       = datetime.utcnow()
        s.avg_stress     = data.get("avg_stress", 0)
        s.peak_stress    = data.get("peak_stress", 0)
        s.readings       = data.get("readings", 0)
        s.readings_json  = json.dumps(data.get("stress_values", []))
        db.session.commit()
        session.pop("active_session_id", None)
    return jsonify({"ok": True})


# ── Main Analyze Endpoint ─────────────────────────────────────────────────
@app.route("/analyze", methods=["POST"])
@login_required
@limiter.limit("60 per minute")
def analyze():
    try:
        data  = request.get_json(force=True)
        image = data.get("image", "")
        blink = float(data.get("blink", 50))
        voice = float(data.get("voice", 50))

        if data.get("use_claude", True) and image:
            cv_result = analyze_face_claude(image)
            face  = float(cv_result.get("face_score", 50))
            extra = {
                "emotion":           cv_result.get("emotion", "neutral"),
                "tension":           cv_result.get("tension", "medium"),
                "emotional_valence": cv_result.get("emotional_valence", "neutral"),
                "stress_indicators": cv_result.get("stress_indicators", []),
                "vision_confidence": cv_result.get("confidence", 60),
            }
        else:
            face  = analyze_face_cv(image)
            extra = {
                "emotion": "unknown", "tension": "medium",
                "emotional_valence": "neutral", "stress_indicators": [], "vision_confidence": 50
            }

        result = calculate_stress(
            face, blink, voice,
            valence=extra.get("emotional_valence", "neutral"),
            emotion=extra.get("emotion", "neutral"),
            stress_indicators=extra.get("stress_indicators", []),
        )
        result.update(extra)

        # Persist reading with all metrics
        sid = session.get("active_session_id")
        r = Reading(
            session_id = sid,
            user_id    = current_user.id,
            stress     = result["stress"],
            focus      = result.get("focus", 50),
            fatigue    = result.get("fatigue", 50),
            anxiety    = result.get("anxiety", 50),
            face_score = face,
            blink      = blink,
            voice      = voice,
            emotion    = extra.get("emotion", "unknown"),
            level      = result["level"],
        )
        db.session.add(r)
        db.session.commit()

        return jsonify(result)
    except Exception as e:
        print(f"[/analyze ERROR] {e}")
        return jsonify({"error": str(e)}), 500


# ── History Chart API ─────────────────────────────────────────────────────
@app.route("/api/history/chart")
@login_required
def history_chart():
    days  = int(request.args.get("days", 7))
    since = datetime.utcnow() - timedelta(days=days)
    rows  = Reading.query.filter(
        Reading.user_id  == current_user.id,
        Reading.timestamp >= since
    ).order_by(Reading.timestamp).all()
    return jsonify([{
        "t": r.timestamp.isoformat(),
        "s": r.stress,
        "f": r.focus,
        "fa": r.fatigue,
        "a": r.anxiety,
        "e": r.emotion
    } for r in rows])


# ── Emotion breakdown API ─────────────────────────────────────────────────
@app.route("/api/emotions/summary")
@login_required
def emotions_summary():
    since = datetime.utcnow() - timedelta(days=7)
    rows  = Reading.query.filter(
        Reading.user_id  == current_user.id,
        Reading.timestamp >= since,
        Reading.emotion   != "unknown"
    ).all()
    counts = {}
    for r in rows:
        counts[r.emotion] = counts.get(r.emotion, 0) + 1
    return jsonify(counts)


# ── Init DB ───────────────────────────────────────────────────────────────
try:
    with app.app_context():
        db.create_all()
except Exception as e:
    print(f"[DB INIT ERROR] {e}")

# Local dev only — Vercel uses the `app` object directly via @vercel/python
if __name__ == "__main__":
    app.run(debug=True, port=5000)
