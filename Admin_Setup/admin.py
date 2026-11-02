#!/usr/bin/env python3
"""Claude Token Dashboard - ADMIN setup.

* Runs on ONE PC (the admin PC).
* The admin adds each user (User ID + password shown on the user's PC).
* This PC then fetches every user's report over the same Wi-Fi / LAN
  (automatically every 30 minutes, or any time with "Fetch now").
* Admin sees everyone. A user who logs in here sees only their own data.

No Anthropic API, no internet. Python 3.8+, standard library only.
"""
import argparse
import csv
import getpass
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_ID = "ctd-admin"
USER_APP_ID = "ctd-user"
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = DATA_DIR / "admin.db"
ADMIN_PW_PATH = DATA_DIR / "admin.json"

DEFAULTS = {
    "port": 18800,                  # admin dashboard
    "lan_access": False,           # true = dashboard also reachable from other PCs (users can log in too)
    "fetch_interval_minutes": 30,  # automatic fetch from all users
    "default_user_port": 18766,
    "discovery_port": 18767,        # UDP: users announce themselves here
    "open_browser": True,
}

STATIC = {
    "/": ("admin.html", "text/html; charset=utf-8"),
    "/report.js": ("report.js", "application/javascript; charset=utf-8"),
    "/common.css": ("common.css", "text/css; charset=utf-8"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  user_id TEXT PRIMARY KEY, label TEXT, reported_name TEXT, pc_name TEXT,
  key_hex TEXT NOT NULL, host TEXT, port INTEGER,
  status TEXT NOT NULL DEFAULT 'never', last_error TEXT, last_ok REAL, last_try REAL, added_at REAL);
CREATE TABLE IF NOT EXISTS reports(
  user_id TEXT PRIMARY KEY, fetched_at REAL, summary TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS fetch_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, ts REAL, ok INTEGER, message TEXT);
CREATE INDEX IF NOT EXISTS idx_log_user ON fetch_log(user_id, id);
"""

CFG = {}
STATE = {"next_fetch": None, "last_fetch_all": None, "discovery": "starting"}
SESSIONS = {}
SESS_LOCK = threading.Lock()
LOGIN_FAILS = {}
SEEN = {}                         # user_id -> last UDP announcement time
FETCH_LOCKS = {}
FETCH_LOCKS_GUARD = threading.Lock()
USER_ID_RE = re.compile(r"^[A-Z0-9_-]{3,24}$")
HOST_RE = re.compile(r"^[A-Za-z0-9.\-]{1,100}$")


# ---------------------------------------------------------------- helpers
def load_config():
    cfg = dict(DEFAULTS)
    first = not CONFIG_PATH.exists()
    if not first:
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (ValueError, OSError) as e:
            print("WARNING: could not read config.json (%s); using defaults" % e)
    if first:
        try:
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except OSError:
            pass
    return cfg


def db():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def norm_pw(p):
    return re.sub(r"[^A-Z0-9]", "", str(p).upper())


def derive_key(user_id, password):
    return hashlib.pbkdf2_hmac("sha256", norm_pw(password).encode("utf-8"),
                               ("ctd:" + str(user_id).upper()).encode("utf-8"), 50000)


def hash_admin_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000).hex()


def admin_pw_set():
    return ADMIN_PW_PATH.exists()


def set_admin_pw(password):
    salt = secrets.token_bytes(16)
    DATA_DIR.mkdir(exist_ok=True)
    ADMIN_PW_PATH.write_text(json.dumps({"salt": salt.hex(), "hash": hash_admin_pw(password, salt)}), encoding="utf-8")


def check_admin_pw(password):
    try:
        d = json.loads(ADMIN_PW_PATH.read_text(encoding="utf-8"))
        return hmac.compare_digest(hash_admin_pw(password, bytes.fromhex(d["salt"])), d["hash"])
    except (OSError, ValueError, KeyError):
        return False


def local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = ai[4][0]
            if ip not in ips and not ip.startswith("127.") and not ip.startswith("169.254."):
                ips.append(ip)
    except OSError:
        pass
    return ips


def parse_host_port(text, default_port):
    """'192.168.1.20' or '192.168.1.20:18766' -> (host, port) or (None, None)"""
    text = str(text or "").strip()
    if not text:
        return None, None
    port = default_port
    if text.count(":") == 1:
        text, p = text.split(":")
        try:
            port = int(p)
        except ValueError:
            return "bad", None
    if not HOST_RE.match(text) or not (1 <= int(port) <= 65535):
        return "bad", None
    return text, int(port)


# ---------------------------------------------------------------- talking to a user PC
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never use a proxy for LAN


def request_report(u):
    path = "/sync/report"
    nonce = secrets.token_hex(12)
    ts = str(int(time.time()))
    key = bytes.fromhex(u["key_hex"])
    sig = hmac.new(key, ("GET\n%s\n%s\n%s" % (path, ts, nonce)).encode("utf-8"), hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        "http://%s:%d%s" % (u["host"], u["port"], path),
        headers={"X-User": u["user_id"], "X-Ts": ts, "X-Nonce": nonce, "X-Sig": sig})
    try:
        with OPENER.open(req, timeout=12) as r:
            body = r.read(30_000_001)
            resp_sig = r.headers.get("X-Resp-Sig") or ""
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read(2000)).get("error", "")
        except Exception:
            err = ""
        if e.code == 401 and err == "clock_skew":
            return False, "The clocks of the two PCs differ by more than 10 minutes - fix the date/time.", None
        if e.code == 401:
            return False, ("Wrong User ID or password - check them on the user's \"Connection to admin\" tab. "
                           "(Also possible: the user reset the password, or an OLDER copy of this tool is still running on that PC - "
                           "run clean_old_versions.bat there.)"), None
        if e.code == 429:
            return False, "Too many failed attempts - wait a minute and try again.", None
        return False, "The user PC answered with error %d." % e.code, None
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
        return False, "Cannot reach %s:%s - the PC is off or asleep, on another network, or its firewall blocks the port." % (u["host"], u["port"]), None
    if len(body) > 30_000_000:
        return False, "Report is too large.", None
    expect = hmac.new(key, (nonce + "\n" + hashlib.sha256(body).hexdigest()).encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, resp_sig):
        return False, "Answer is not signed with this user's password (another device is using that IP address?).", None
    try:
        rep = json.loads(body)
    except ValueError:
        return False, "Unreadable answer from the user PC.", None
    if not isinstance(rep, dict) or rep.get("user_id") != u["user_id"] or "windows" not in rep:
        return False, "Answer does not belong to this user.", None
    return True, "OK", rep


def record_result(uid, ok, msg, rep=None):
    conn = db()
    try:
        now = time.time()
        if ok:
            conn.execute("UPDATE users SET status='ok', last_error=NULL, last_ok=?, last_try=?, reported_name=?, pc_name=? "
                         "WHERE user_id=?", (now, now, rep.get("display_name"), rep.get("pc_name"), uid))
            conn.execute("INSERT OR REPLACE INTO reports(user_id,fetched_at,summary,body) VALUES(?,?,?,?)",
                         (uid, now, json.dumps({"windows": rep["windows"]}), json.dumps(rep)))
        else:
            conn.execute("UPDATE users SET status='error', last_error=?, last_try=? WHERE user_id=?", (msg, now, uid))
        conn.execute("INSERT INTO fetch_log(user_id,ts,ok,message) VALUES(?,?,?,?)", (uid, now, 1 if ok else 0, msg))
        conn.execute("DELETE FROM fetch_log WHERE user_id=? AND id NOT IN "
                     "(SELECT id FROM fetch_log WHERE user_id=? ORDER BY id DESC LIMIT 200)", (uid, uid))
        conn.commit()
    finally:
        conn.close()


def fetch_user(uid):
    with FETCH_LOCKS_GUARD:
        lock = FETCH_LOCKS.setdefault(uid, threading.Lock())
    if not lock.acquire(False):
        return {"user_id": uid, "ok": False, "message": "A fetch is already running."}
    try:
        conn = db()
        try:
            u = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
            if u is not None and not u["host"]:
                conn.execute("UPDATE users SET status='waiting' WHERE user_id=?", (uid,))
                conn.commit()
        finally:
            conn.close()
        if u is None:
            return {"user_id": uid, "ok": False, "message": "Unknown user."}
        if not u["host"]:
            return {"user_id": uid, "ok": False, "message": "No IP address yet - enter it, or wait until the PC is found on the network."}
        ok, msg, rep = request_report(u)
        record_result(uid, ok, msg, rep)
        return {"user_id": uid, "ok": ok, "message": msg}
    finally:
        lock.release()


def fetch_all():
    conn = db()
    try:
        ids = [r["user_id"] for r in conn.execute("SELECT user_id FROM users WHERE host IS NOT NULL AND host<>''")]
    finally:
        conn.close()
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(fetch_user, ids))
    STATE["last_fetch_all"] = time.time()
    return res


def worker(stop):
    stop.wait(10)
    nxt = 0
    while not stop.is_set():
        try:
            if time.time() >= nxt:
                fetch_all()
                nxt = time.time() + max(1, float(CFG["fetch_interval_minutes"])) * 60
                STATE["next_fetch"] = nxt
        except Exception as e:
            print("fetch loop error:", repr(e))
        stop.wait(15)


def on_announce(uid, ip, port):
    SEEN[uid] = time.time()
    conn = db()
    try:
        u = conn.execute("SELECT host, port, status, last_try FROM users WHERE user_id=?", (uid,)).fetchone()
        if u is None or not port:
            return
        changed = (u["host"] != ip or u["port"] != port)
        if changed:
            conn.execute("UPDATE users SET host=?, port=? WHERE user_id=?", (ip, port, uid))
            conn.commit()
    finally:
        conn.close()
    # a PC that comes back online (or moves to a new IP) is fetched right away
    back = u["status"] == "error" and time.time() - (u["last_try"] or 0) > 120
    if changed or back or u["status"] in ("never", "waiting"):
        threading.Thread(target=fetch_user, args=(uid,), daemon=True).start()


def discovery_listener(stop):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", int(CFG["discovery_port"])))
        s.settimeout(2)
    except OSError:
        STATE["discovery"] = "unavailable"
        return
    STATE["discovery"] = "listening"
    while not stop.is_set():
        try:
            data, addr = s.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            msg = json.loads(data.decode("utf-8"))
            if msg.get("app") != USER_APP_ID:
                continue
            on_announce(str(msg.get("user_id", "")).upper(), addr[0], int(msg.get("port") or 0))
        except Exception:
            continue


# ---------------------------------------------------------------- data views
def user_rows(conn):
    out = []
    now = time.time()
    rows = conn.execute(
        "SELECT u.*, r.fetched_at, r.summary FROM users u LEFT JOIN reports r ON r.user_id=u.user_id "
        "ORDER BY COALESCE(u.label, u.reported_name, u.user_id)").fetchall()
    for r in rows:
        try:
            windows = json.loads(r["summary"])["windows"] if r["summary"] else None
        except (ValueError, KeyError):
            windows = None
        out.append({
            "user_id": r["user_id"], "name": r["label"] or r["reported_name"] or r["user_id"],
            "label": r["label"] or "", "reported_name": r["reported_name"], "pc_name": r["pc_name"],
            "host": r["host"], "port": r["port"], "status": r["status"], "error": r["last_error"],
            "last_ok": r["last_ok"], "last_try": r["last_try"], "fetched_at": r["fetched_at"],
            "online": bool(SEEN.get(r["user_id"]) and now - SEEN[r["user_id"]] < 120),
            "windows": windows})
    return out


def csv_export(conn):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["user_id", "name", "date", "tokens_in_plus_out", "input", "output", "cache_write", "cache_read", "prompts", "replies"])
    for r in conn.execute("SELECT u.user_id, COALESCE(u.label,u.reported_name,u.user_id) n, r.body FROM users u "
                          "JOIN reports r ON r.user_id=u.user_id ORDER BY n"):
        try:
            rep = json.loads(r["body"])
        except ValueError:
            continue
        for d in rep.get("daily", []):
            if d["input"] or d["output"] or d["cache_write"] or d["cache_read"]:
                w.writerow([r["user_id"], r["n"], d["date"], d["input"] + d["output"], d["input"], d["output"],
                            d["cache_write"], d["cache_read"], d.get("prompts", 0), d.get("messages", 0)])
    return buf.getvalue().encode("utf-8-sig")


def build_user_zip():
    src = None
    for cand in (APP_DIR.parent / "User_Setup", APP_DIR / "User_Setup"):
        if (cand / "user.py").exists():
            src = cand
            break
    if src is None:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.iterdir()):
            if p.is_file() and p.name != "config.json" and not p.name.endswith((".pyc", ".tmp")):
                z.write(str(p), "User_Setup/" + p.name)
    return buf.getvalue()


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "ctd-admin"

    def log_message(self, *args):
        pass

    # ---- plumbing
    def _send(self, body, ctype, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, extra=None):
        self._send(json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8", code, extra)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(min(n, 100000)) or b"{}")
            return d if isinstance(d, dict) else {}
        except (ValueError, OSError):
            return {}

    def _is_loopback(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _host_ok(self):
        if CFG.get("lan_access"):
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return self._is_loopback() and host in ("127.0.0.1", "localhost", "::1")

    def _session(self):
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie") or "")
        except Exception:
            return None
        m = c.get("sid")
        if not m:
            return None
        with SESS_LOCK:
            s = SESSIONS.get(m.value)
            if s and s["exp"] > time.time():
                return s
            SESSIONS.pop(m.value, None)
        return None

    def _need_admin(self):
        s = self._session()
        if not s or s["role"] != "admin":
            self._json({"error": "admin login required"}, 401 if not s else 403)
            return None
        return s

    # ---- GET
    def do_GET(self):
        if not self._host_ok():
            return self._json({"error": "local access only"}, 403)
        u = urlparse(self.path)
        p = u.path
        try:
            if p in STATIC:
                name, ctype = STATIC[p]
                return self._send((APP_DIR / name).read_bytes(), ctype)
            if p == "/api/ping":
                return self._json({"app": APP_ID})
            if p == "/user-setup.zip":
                z = build_user_zip()
                if z is None:
                    return self._json({"error": "User_Setup folder not found next to Admin_Setup"}, 404)
                return self._send(z, "application/zip", extra={"Content-Disposition": 'attachment; filename="User_Setup.zip"'})
            if p == "/api/me":
                s = self._session()
                return self._json({"setup_needed": not admin_pw_set(), "role": s["role"] if s else None,
                                   "user_id": s.get("user_id") if s else None, "lan_access": bool(CFG.get("lan_access"))})
            if p == "/api/my/report":
                s = self._session()
                if not s or s["role"] != "user":
                    return self._json({"error": "login required"}, 401)
                conn = db()
                try:
                    r = conn.execute("SELECT body, fetched_at FROM reports WHERE user_id=?", (s["user_id"],)).fetchone()
                    n = conn.execute("SELECT COALESCE(label,reported_name,user_id) n FROM users WHERE user_id=?", (s["user_id"],)).fetchone()
                finally:
                    conn.close()
                return self._json({"name": n["n"] if n else s["user_id"], "fetched_at": r["fetched_at"] if r else None,
                                   "report": json.loads(r["body"]) if r else None})
            # ---- admin only below
            if p == "/api/users":
                if not self._need_admin():
                    return
                conn = db()
                try:
                    users = user_rows(conn)
                finally:
                    conn.close()
                ips = local_ips()
                return self._json({
                    "users": users, "now": time.time(), "next_fetch": STATE["next_fetch"],
                    "last_fetch_all": STATE["last_fetch_all"], "interval_minutes": CFG["fetch_interval_minutes"],
                    "discovery": STATE["discovery"], "lan_access": bool(CFG.get("lan_access")),
                    "admin_ips": ips, "port": STATE.get("port"), "default_user_port": CFG["default_user_port"],
                    "package_available": any((c / "user.py").exists() for c in (APP_DIR.parent / "User_Setup", APP_DIR / "User_Setup"))})
            m = re.match(r"^/api/users/([A-Za-z0-9_-]+)$", p)
            if m:
                if not self._need_admin():
                    return
                uid = m.group(1).upper()
                conn = db()
                try:
                    rows = [x for x in user_rows(conn) if x["user_id"] == uid]
                    r = conn.execute("SELECT body FROM reports WHERE user_id=?", (uid,)).fetchone()
                    log = [dict(x) for x in conn.execute(
                        "SELECT ts, ok, message FROM fetch_log WHERE user_id=? ORDER BY id DESC LIMIT 15", (uid,))]
                finally:
                    conn.close()
                if not rows:
                    return self._json({"error": "unknown user"}, 404)
                return self._json({"user": rows[0], "report": json.loads(r["body"]) if r else None, "log": log})
            if p == "/api/export.csv":
                if not self._need_admin():
                    return
                conn = db()
                try:
                    data = csv_export(conn)
                finally:
                    conn.close()
                return self._send(data, "text/csv; charset=utf-8",
                                  extra={"Content-Disposition": 'attachment; filename="claude-token-usage.csv"'})
            self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": repr(e)}, 500)

    # ---- POST
    def do_POST(self):
        if not self._host_ok():
            return self._json({"error": "local access only"}, 403)
        if self.headers.get("X-Dashboard") != "1":        # blocks cross-site form posts
            return self._json({"error": "forbidden"}, 403)
        p = urlparse(self.path).path
        ip = self.client_address[0]
        try:
            body = self._body()
            if p == "/api/stop":
                if not self._is_loopback():
                    return self._json({"error": "forbidden"}, 403)
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if p == "/api/setup":
                if admin_pw_set() or not self._is_loopback():
                    return self._json({"error": "setup is only possible once, on the admin PC itself"}, 403)
                pw = str(body.get("password", ""))
                if len(pw) < 6:
                    return self._json({"error": "Password must be at least 6 characters."}, 400)
                set_admin_pw(pw)
                return self._login_ok("admin", None)
            if p == "/api/login":
                now = time.time()
                with SESS_LOCK:
                    recent = [t for t in LOGIN_FAILS.get(ip, []) if now - t < 600]
                    LOGIN_FAILS[ip] = recent
                    if len(recent) >= 8:
                        return self._json({"error": "Too many wrong attempts. Wait 10 minutes."}, 429)
                name = str(body.get("username", "")).strip().upper()
                pw = str(body.get("password", ""))
                if name == "ADMIN" and admin_pw_set() and check_admin_pw(pw):
                    return self._login_ok("admin", None)
                if USER_ID_RE.match(name) and name != "ADMIN":
                    conn = db()
                    try:
                        u = conn.execute("SELECT key_hex FROM users WHERE user_id=?", (name,)).fetchone()
                    finally:
                        conn.close()
                    if u and hmac.compare_digest(derive_key(name, pw).hex(), u["key_hex"]):
                        return self._login_ok("user", name)
                with SESS_LOCK:
                    LOGIN_FAILS.setdefault(ip, []).append(now)
                return self._json({"error": "Wrong username or password."}, 401)
            if p == "/api/logout":
                c = SimpleCookie()
                try:
                    c.load(self.headers.get("Cookie") or "")
                    with SESS_LOCK:
                        SESSIONS.pop(c["sid"].value, None)
                except Exception:
                    pass
                return self._json({"ok": True}, extra={"Set-Cookie": "sid=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})

            # ---- admin only below
            if not self._need_admin():
                return
            if p == "/api/admin-password":
                if not check_admin_pw(str(body.get("old", ""))) or len(str(body.get("new", ""))) < 6:
                    return self._json({"error": "Old password is wrong, or the new one is shorter than 6 characters."}, 400)
                set_admin_pw(str(body["new"]))
                return self._json({"ok": True})
            if p == "/api/fetch-all":
                return self._json({"results": fetch_all()})
            if p == "/api/users":
                return self._add_user(body)
            m = re.match(r"^/api/users/([A-Za-z0-9_-]+)/(fetch|delete|connection)$", p)
            if m:
                uid, action = m.group(1).upper(), m.group(2)
                if action == "fetch":
                    return self._json(fetch_user(uid))
                conn = db()
                try:
                    if conn.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone() is None:
                        return self._json({"error": "unknown user"}, 404)
                    if action == "delete":
                        for t in ("users", "reports", "fetch_log"):
                            conn.execute("DELETE FROM %s WHERE user_id=?" % t, (uid,))
                        conn.commit()
                        return self._json({"ok": True})
                    # connection settings
                    host, port = parse_host_port(body.get("host"), int(body.get("port") or CFG["default_user_port"]))
                    if host == "bad":
                        return self._json({"error": "Invalid IP address / port."}, 400)
                    conn.execute("UPDATE users SET label=?, host=?, port=? WHERE user_id=?",
                                 (str(body.get("label", "")).strip()[:60] or None, host, port, uid))
                    if str(body.get("password", "")).strip():
                        conn.execute("UPDATE users SET key_hex=? WHERE user_id=?",
                                     (derive_key(uid, str(body["password"])).hex(), uid))
                    conn.commit()
                finally:
                    conn.close()
                return self._json(fetch_user(uid))
            self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": repr(e)}, 500)

    def _login_ok(self, role, user_id):
        token = secrets.token_urlsafe(32)
        with SESS_LOCK:
            SESSIONS[token] = {"role": role, "user_id": user_id, "exp": time.time() + 12 * 3600}
        self._json({"ok": True, "role": role, "user_id": user_id},
                   extra={"Set-Cookie": "sid=%s; Path=/; Max-Age=43200; HttpOnly; SameSite=Strict" % token})

    def _add_user(self, body):
        uid = str(body.get("user_id", "")).strip().upper()
        pw = str(body.get("password", "")).strip()
        if not USER_ID_RE.match(uid) or uid == "ADMIN":
            return self._json({"error": "User ID looks wrong (example: U7K2M9)."}, 400)
        if len(norm_pw(pw)) < 6:
            return self._json({"error": "Enter the password shown on the user's PC."}, 400)
        host, port = parse_host_port(body.get("host"), int(body.get("port") or CFG["default_user_port"]))
        if host == "bad":
            return self._json({"error": "Invalid IP address / port."}, 400)
        label = str(body.get("label", "")).strip()[:60] or None
        conn = db()
        try:
            if conn.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
                return self._json({"error": "This User ID is already added."}, 409)
            conn.execute("INSERT INTO users(user_id,label,key_hex,host,port,status,added_at) VALUES(?,?,?,?,?,?,?)",
                         (uid, label, derive_key(uid, pw).hex(), host, port or CFG["default_user_port"],
                          "never" if host else "waiting", time.time()))
            conn.commit()
        finally:
            conn.close()
        if not host:
            return self._json({"ok": True, "connected": False,
                               "message": "Added. Waiting for the user's PC to appear on the network - or enter its IP address."})
        r = fetch_user(uid)
        return self._json({"ok": True, "connected": r["ok"], "message": "Connected." if r["ok"] else r["message"]})


def already_running(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == APP_ID
    except Exception:
        return False


class Server(ThreadingHTTPServer):
    """HTTP server that never silently shares its port with another program
    (on Windows SO_REUSEADDR would let two programs listen on the same port)."""
    daemon_threads = True
    allow_reuse_address = (os.name != "nt")

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def bind_first_free(host, start, handler, avoid=()):
    for p in range(start, start + 20):
        if p in avoid:
            continue
        try:
            return Server((host, p), handler), p
        except OSError:
            continue
    try:                                    # last resort: let the OS pick any free port
        srv = Server((host, 0), handler)
        return srv, srv.server_address[1]
    except OSError:
        return None, None


def main():
    for stream in (sys.stdout, sys.stderr):      # never crash on non-ASCII names when logging
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Claude Token Dashboard - ADMIN setup")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--reset-password", action="store_true", help="set a new admin password and exit")
    args = ap.parse_args()
    CFG.update(load_config())

    if args.reset_password:
        a = getpass.getpass("New admin password (min 6 characters): ")
        if len(a) < 6 or a != getpass.getpass("Repeat: "):
            print("Passwords differ or are too short.")
            return 1
        set_admin_pw(a)
        print("Admin password changed.")
        return 0

    port = int(CFG["port"])
    if already_running(port):
        url = "http://127.0.0.1:%d/" % port
        print("Admin dashboard is already running -> %s" % url)
        if CFG.get("open_browser") and not args.no_browser:
            webbrowser.open(url)
        return 0

    bind_host = "0.0.0.0" if CFG.get("lan_access") else "127.0.0.1"
    server, port = bind_first_free(bind_host, port, Handler)
    if server is None:
        print("ERROR: no free port for the admin dashboard")
        return 2
    STATE["port"] = port
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "port.txt").write_text(str(port), encoding="utf-8")
    db().close()

    stop = threading.Event()
    threading.Thread(target=worker, args=(stop,), daemon=True).start()
    threading.Thread(target=discovery_listener, args=(stop,), daemon=True).start()

    url = "http://127.0.0.1:%d/" % port
    print("=" * 60)
    print(" Claude Token Dashboard - ADMIN")
    print(" Open: %s" % url)
    if CFG.get("lan_access"):
        print(" Other PCs on the LAN: %s" % ", ".join("http://%s:%d/" % (i, port) for i in local_ips()))
    print(" Keep this window open. Ctrl+C to stop.")
    print("=" * 60)
    if CFG.get("open_browser") and not args.no_browser:
        threading.Timer(1.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
