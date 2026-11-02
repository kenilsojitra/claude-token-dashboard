#!/usr/bin/env python3
"""Claude Token Dashboard - USER setup.

* Reads this PC's Claude Code logs (~/.claude/projects/**/*.jsonl)
* Counts tokens per day / week / prompt, stores them locally (SQLite)
* Shows ONLY this user's data on a local dashboard (127.0.0.1)
* Creates a User ID + password. The admin types them into the Admin dashboard;
  after that the admin PC can fetch this PC's report over the same Wi-Fi / LAN.

No Anthropic API, no internet. Python 3.8+, standard library only.
"""
import argparse
import datetime as dt
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_ID = "ctd-user"
VERSION = 2
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = DATA_DIR / "usage.db"
IDENT_PATH = DATA_DIR / "identity.json"
PAIR_PATH = DATA_DIR / "pairing.json"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I - easy to read out loud

DEFAULTS = {
    "display_name": "",          # shown to the admin; default = Windows user + PC name
    "port": 18765,                # local dashboard (this PC only)
    "sync_port": 18766,           # LAN port the admin PC connects to
    "discovery_port": 18767,      # UDP port used to announce this PC to the admin PC
    "scan_interval_hours": 2,    # how often a snapshot is stored
    "share_prompt_text": True,   # admin sees the first ~100 characters of each prompt
    "claude_dir": "",            # leave empty to auto-detect ~/.claude
    "open_browser": True,
}

STATIC = {
    "/": ("dashboard.html", "text/html; charset=utf-8"),
    "/report.js": ("report.js", "application/javascript; charset=utf-8"),
    "/common.css": ("common.css", "text/css; charset=utf-8"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  key TEXT PRIMARY KEY, ts REAL NOT NULL, model TEXT, project TEXT, session TEXT, prompt_id TEXT,
  inp INTEGER NOT NULL DEFAULT 0, out INTEGER NOT NULL DEFAULT 0,
  cache_w INTEGER NOT NULL DEFAULT 0, cache_r INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);
CREATE INDEX IF NOT EXISTS idx_messages_prompt ON messages(prompt_id);
CREATE TABLE IF NOT EXISTS prompts(
  id TEXT PRIMARY KEY, ts REAL NOT NULL, session TEXT, project TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS idx_prompts_sess ON prompts(session, ts);
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, size INTEGER, offset INTEGER);
CREATE TABLE IF NOT EXISTS snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  today_io INTEGER, today_all INTEGER, h4_io INTEGER, h4_all INTEGER,
  life_io INTEGER, life_all INTEGER, messages INTEGER);
"""

UPSERT = """INSERT INTO messages(key,ts,model,project,session,inp,out,cache_w,cache_r)
VALUES(?,?,?,?,?,?,?,?,?)
ON CONFLICT(key) DO UPDATE SET
  inp=max(inp,excluded.inp), out=max(out,excluded.out),
  cache_w=max(cache_w,excluded.cache_w), cache_r=max(cache_r,excluded.cache_r)"""

SCAN_LOCK = threading.Lock()
STATE = {"last_scan": None, "last_snapshot": None, "next_snapshot": None,
         "roots": [], "files": 0, "error": None, "ui_port": None, "sync_port": None}
IDENT = {}            # user_id, password, key (bytes)
CFG = {}
PAIR = {}
PAIR_LOCK = threading.Lock()


# ---------------------------------------------------------------- config / identity
def write_json(path, obj):
    DATA_DIR.mkdir(exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def load_config():
    cfg = dict(DEFAULTS)
    first_run = not CONFIG_PATH.exists()
    if not first_run:
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (ValueError, OSError) as e:
            print("WARNING: could not read config.json (%s); using defaults" % e)
    if not str(cfg.get("display_name") or "").strip():
        try:
            user = getpass.getuser()
        except Exception:
            user = "user"
        cfg["display_name"] = "%s (%s)" % (user, socket.gethostname())
    cfg["display_name"] = str(cfg["display_name"]).strip()[:60]
    if first_run:
        try:
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except OSError:
            pass
    return cfg


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


def norm_pw(p):
    return re.sub(r"[^A-Z0-9]", "", str(p).upper())


def derive_key(user_id, password):
    return hashlib.pbkdf2_hmac("sha256", norm_pw(password).encode("utf-8"),
                               ("ctd:" + str(user_id).upper()).encode("utf-8"), 50000)


def new_password():
    p = "".join(secrets.choice(ALPHABET) for _ in range(10))
    return p[:5] + "-" + p[5:]


def load_identity():
    ident = None
    if IDENT_PATH.exists():
        try:
            ident = json.loads(IDENT_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            ident = None
    if not ident or not ident.get("user_id") or not ident.get("password"):
        ident = {"user_id": "U" + "".join(secrets.choice(ALPHABET) for _ in range(5)),
                 "password": new_password(), "created": time.time()}
        write_json(IDENT_PATH, ident)
    IDENT.clear()
    IDENT.update(ident)
    IDENT["key"] = derive_key(ident["user_id"], ident["password"])


def load_pairing():
    try:
        PAIR.update(json.loads(PAIR_PATH.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        pass


def save_pairing():
    try:
        write_json(PAIR_PATH, PAIR)
    except OSError:
        pass


# ---------------------------------------------------------------- database
def db():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------- scanning
def find_roots(cfg):
    cands = []
    if cfg.get("claude_dir"):
        p = Path(cfg["claude_dir"]).expanduser()
        cands.append(p / "projects" if (p / "projects").is_dir() else p)
    else:
        env = os.environ.get("CLAUDE_CONFIG_DIR")
        if env:
            cands.append(Path(env).expanduser() / "projects")
        cands.append(Path.home() / ".claude" / "projects")
        cands.append(Path.home() / ".config" / "claude" / "projects")
    seen, out = set(), []
    for c in cands:
        try:
            r = c.resolve()
        except OSError:
            r = c
        if r in seen:
            continue
        seen.add(r)
        if c.is_dir():
            out.append(c)
    return out


def num(x):
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def parse_ts(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


_NOISE = re.compile(r"<(ide_[a-z_]+|system-reminder)>.*?</\1>", re.S)


def prompt_text(rec):
    """Text of a prompt the person actually typed, or None for tool results,
    sub-agent traffic, local-command noise, interruptions, etc."""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isSidechain"):
        return None
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return None
    c = msg.get("content")
    if isinstance(c, str):
        text = c
    elif isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return None
        bits = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        text = " ".join(bits)
        if not _NOISE.sub("", text).strip() and any(isinstance(b, dict) and b.get("type") == "image" for b in c):
            text = "[image]"
    else:
        return None
    text = _NOISE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or text.startswith(("<local-command", "Caveat:", "[Request interrupted")):
        return None
    m = re.match(r"<command-name>\s*([^<]+?)\s*</command-name>", text)
    if m:
        text = m.group(1)
    return text[:140]


def scan_root(conn, root):
    count = 0
    for path in root.rglob("*.jsonl"):
        try:
            st = path.stat()
        except OSError:
            continue
        count += 1
        row = conn.execute("SELECT size, offset FROM files WHERE path=?", (str(path),)).fetchone()
        offset = 0
        if row:
            if st.st_size == row[0]:
                continue
            if st.st_size > row[0]:
                offset = row[1]
        rel = path.relative_to(root)
        project = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        rows, prompts = [], []
        consumed = offset
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                for line in f:
                    if not line.endswith(b"\n"):
                        break  # half-written last line: picked up next scan
                    line_off = consumed
                    consumed += len(line)
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    rtype = rec.get("type")
                    sess = str(rec.get("sessionId") or path.stem)
                    if rtype == "user":
                        txt = prompt_text(rec)
                        ts = parse_ts(rec.get("timestamp"))
                        if txt is not None and ts is not None:
                            prompts.append(("%s:%s" % (sess, rec.get("uuid") or line_off), ts, sess, project, txt))
                        continue
                    if rtype != "assistant":
                        continue
                    msg = rec.get("message")
                    if not isinstance(msg, dict):
                        continue
                    u = msg.get("usage")
                    if not isinstance(u, dict):
                        continue
                    model = msg.get("model") or "unknown"
                    if model == "<synthetic>":
                        continue
                    ts = parse_ts(rec.get("timestamp"))
                    if ts is None:
                        continue
                    inp, out = num(u.get("input_tokens")), num(u.get("output_tokens"))
                    cw, cr = num(u.get("cache_creation_input_tokens")), num(u.get("cache_read_input_tokens"))
                    if inp + out + cw + cr == 0:
                        continue
                    mid, rid = msg.get("id"), rec.get("requestId")
                    # the same API message can be logged several times (streaming
                    # chunks, resumed sessions) -> one key, keep the max
                    key = "%s:%s" % (mid, rid) if mid else "%s:%d" % (path, line_off)
                    rows.append((key, ts, model, project, sess, inp, out, cw, cr))
        except OSError:
            continue
        if prompts:
            conn.executemany("INSERT OR IGNORE INTO prompts(id,ts,session,project,text) VALUES(?,?,?,?,?)", prompts)
        if rows:
            conn.executemany(UPSERT, rows)
        conn.execute("INSERT OR REPLACE INTO files(path,size,offset) VALUES(?,?,?)",
                     (str(path), st.st_size, consumed))
        conn.commit()
    return count


def scan_all(conn, cfg):
    roots = find_roots(cfg)
    STATE["roots"] = [str(r) for r in roots]
    total = 0
    for r in roots:
        total += scan_root(conn, r)
    STATE["files"] = total
    # every reply belongs to the latest prompt of its session that came before it
    conn.execute(
        "UPDATE messages SET prompt_id=(SELECT p.id FROM prompts p WHERE p.session=messages.session "
        "AND p.ts<=messages.ts ORDER BY p.ts DESC LIMIT 1) WHERE prompt_id IS NULL")
    conn.commit()
    return total


# ---------------------------------------------------------------- queries
def local_midnight():
    return dt.datetime.combine(dt.date.today(), dt.time.min).timestamp()


def utc_offset():
    return dt.datetime.now().astimezone().utcoffset().total_seconds()


def sums(conn, since):
    r = conn.execute(
        "SELECT COALESCE(SUM(inp),0),COALESCE(SUM(out),0),COALESCE(SUM(cache_w),0),"
        "COALESCE(SUM(cache_r),0),COUNT(*) FROM messages WHERE ts>=?", (since,)).fetchone()
    return {"input": r[0], "output": r[1], "cache_write": r[2], "cache_read": r[3],
            "messages": r[4], "io": r[0] + r[1], "all": r[0] + r[1] + r[2] + r[3]}


def window_starts():
    now = time.time()
    return {"today": local_midnight(), "last_4h": now - 4 * 3600, "last_24h": now - 86400,
            "last_7d": now - 7 * 86400, "lifetime": 0}


def all_windows(conn):
    return {k: sums(conn, v) for k, v in window_starts().items()}


def buckets(conn, days):
    off = utc_offset()
    now = time.time()
    since = dt.datetime.combine(dt.date.today() - dt.timedelta(days=days - 1), dt.time.min).timestamp()
    rows = conn.execute(
        "SELECT CAST((ts+?)/7200 AS INTEGER) b, SUM(inp),SUM(out),SUM(cache_w),SUM(cache_r) "
        "FROM messages WHERE ts>=? GROUP BY b", (off, since)).fetchall()
    data = {r[0]: r[1:] for r in rows}
    out = []
    for b in range(int((since + off) // 7200), int((now + off) // 7200) + 1):
        v = data.get(b, (0, 0, 0, 0))
        out.append({"start": b * 7200 - off, "input": v[0], "output": v[1],
                    "cache_write": v[2], "cache_read": v[3]})
    return out


def grouped(conn, expr, since):
    sql = ("SELECT %s k, SUM(inp),SUM(out),SUM(cache_w),SUM(cache_r),COUNT(*),COUNT(DISTINCT prompt_id) "
           "FROM messages WHERE ts>=? GROUP BY k" % expr)
    return {r[0]: r[1:] for r in conn.execute(sql, (since,))}


def item(v):
    return {"input": v[0], "output": v[1], "cache_write": v[2], "cache_read": v[3],
            "messages": v[4], "prompts": v[5]}


def daily(conn, days=60):
    today = dt.date.today()
    since = dt.datetime.combine(today - dt.timedelta(days=days - 1), dt.time.min).timestamp()
    rows = grouped(conn, "strftime('%Y-%m-%d', ts,'unixepoch','localtime')", since)
    out = []
    for i in range(days - 1, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        e = item(rows.get(d, (0, 0, 0, 0, 0, 0)))
        e["date"] = d
        out.append(e)
    return out


def weekly(conn, weeks=12):
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    first = monday - dt.timedelta(days=7 * (weeks - 1))
    since = dt.datetime.combine(first, dt.time.min).timestamp()
    rows = grouped(conn, "date(ts,'unixepoch','localtime','weekday 0','-6 days')", since)
    out = []
    for i in range(weeks):
        d = (first + dt.timedelta(days=7 * i)).isoformat()
        e = item(rows.get(d, (0, 0, 0, 0, 0, 0)))
        e["week_start"] = d
        out.append(e)
    return out


def prompt_list(conn, hide_text, limit=300):
    rows = conn.execute(
        "SELECT p.ts,p.text,p.project,SUM(m.inp),SUM(m.out),SUM(m.cache_w),SUM(m.cache_r),COUNT(m.key) "
        "FROM prompts p JOIN messages m ON m.prompt_id=p.id GROUP BY p.id ORDER BY p.ts DESC LIMIT ?",
        (limit,)).fetchall()
    return [{"ts": r[0], "text": "(hidden by user)" if hide_text else r[1], "project": r[2],
             "input": r[3], "output": r[4], "cache_write": r[5], "cache_read": r[6], "messages": r[7]}
            for r in rows]


def breakdown(conn, window):
    since = window_starts().get(window, 0)
    res = {}
    for col, name in (("model", "models"), ("project", "projects")):
        rows = conn.execute(
            "SELECT %s,SUM(inp),SUM(out),SUM(cache_w),SUM(cache_r),COUNT(*) FROM messages "
            "WHERE ts>=? GROUP BY %s ORDER BY SUM(inp)+SUM(out) DESC LIMIT 25" % (col, col),
            (since,)).fetchall()
        res[name] = [{"name": r[0] or "unknown", "input": r[1], "output": r[2],
                      "cache_write": r[3], "cache_read": r[4], "messages": r[5]} for r in rows]
    return res


def snapshots(conn, limit=30):
    rows = conn.execute(
        "SELECT ts,today_io,today_all,h4_io,h4_all,life_io,life_all,messages FROM snapshots "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    keys = ("ts", "today_io", "today_all", "h4_io", "h4_all", "life_io", "life_all", "messages")
    return [dict(zip(keys, r)) for r in rows]


def take_snapshot(conn):
    w = all_windows(conn)
    conn.execute(
        "INSERT INTO snapshots(ts,today_io,today_all,h4_io,h4_all,life_io,life_all,messages) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (time.time(), w["today"]["io"], w["today"]["all"], w["last_4h"]["io"], w["last_4h"]["all"],
         w["lifetime"]["io"], w["lifetime"]["all"], w["lifetime"]["messages"]))
    conn.commit()


def build_report(conn, cfg):
    return {
        "app": APP_ID, "version": VERSION, "user_id": IDENT["user_id"],
        "display_name": cfg["display_name"], "pc_name": socket.gethostname(),
        "generated_at": time.time(), "interval_hours": interval_seconds(cfg) / 3600,
        "windows": all_windows(conn),
        "buckets": buckets(conn, 14),
        "daily": daily(conn, 60),
        "weekly": weekly(conn, 12),
        "prompts": prompt_list(conn, not cfg.get("share_prompt_text", True)) ,
        "breakdown": {w: breakdown(conn, w) for w in ("today", "last_7d", "lifetime")},
        "snapshots": snapshots(conn, 30),
    }


# ---------------------------------------------------------------- scan loop
def interval_seconds(cfg):
    try:
        return max(0.01, float(cfg.get("scan_interval_hours") or 2)) * 3600
    except (TypeError, ValueError):
        return 7200.0


def run_cycle(cfg, snapshot):
    with SCAN_LOCK:
        conn = db()
        try:
            scan_all(conn, cfg)
            STATE["last_scan"] = time.time()
            if snapshot:
                take_snapshot(conn)
                STATE["last_snapshot"] = time.time()
                STATE["next_snapshot"] = time.time() + interval_seconds(cfg)
            STATE["error"] = None
        finally:
            conn.close()


def worker(cfg, stop):
    STATE["next_snapshot"] = time.time()
    while not stop.is_set():
        try:
            run_cycle(cfg, snapshot=time.time() >= (STATE["next_snapshot"] or 0))
        except Exception as e:  # keep the loop alive
            STATE["error"] = repr(e)
        stop.wait(60)


# ---------------------------------------------------------------- network helpers
def local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))     # no packet is sent
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


def announcer(stop):
    """Tell the admin PC (if it is listening) that this user is online and where."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        return
    while not stop.is_set():
        msg = json.dumps({"app": APP_ID, "user_id": IDENT["user_id"],
                          "port": STATE["sync_port"]}).encode("utf-8")
        targets = ["255.255.255.255"]
        for ip in local_ips():
            targets.append(ip.rsplit(".", 1)[0] + ".255")
        for t in targets:
            try:
                s.sendto(msg, (t, int(CFG["discovery_port"])))
            except OSError:
                pass
        stop.wait(30)


# ---------------------------------------------------------------- HTTP
class Base(BaseHTTPRequestHandler):
    server_version = "ctd"

    def log_message(self, *args):
        pass

    def _send(self, body, ctype, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, extra=None):
        self._send(json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8", code, extra)

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(min(n, 100000)) or b"{}")
        except (ValueError, OSError):
            return {}


class UIHandler(Base):
    """Local dashboard - reachable from this PC only."""

    def _local_only(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if self.client_address[0] not in ("127.0.0.1", "::1") or host not in ("127.0.0.1", "localhost", "::1"):
            self._json({"error": "local access only"}, 403)
            return False
        return True

    def do_GET(self):
        if not self._local_only():
            return
        u = urlparse(self.path)
        try:
            if u.path in STATIC:
                name, ctype = STATIC[u.path]
                return self._send((APP_DIR / name).read_bytes(), ctype)
            if u.path == "/api/ping":
                return self._json({"app": APP_ID})
            if u.path == "/api/report":
                conn = db()
                try:
                    return self._json(build_report(conn, CFG))
                finally:
                    conn.close()
            if u.path == "/api/identity":
                with PAIR_LOCK:
                    pair = dict(PAIR)
                pw = IDENT["password"]
                return self._json({
                    "user_id": IDENT["user_id"], "password": pw, "display_name": CFG["display_name"],
                    "ips": local_ips(), "sync_port": STATE["sync_port"], "pairing": pair,
                    "share_prompt_text": bool(CFG.get("share_prompt_text", True)),
                    "state": STATE, "now": time.time()})
            self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": repr(e)}, 500)

    def do_POST(self):
        if not self._local_only():
            return
        if self.headers.get("X-Dashboard") != "1":     # blocks cross-site requests
            return self._json({"error": "forbidden"}, 403)
        path = urlparse(self.path).path
        try:
            if path == "/api/stop":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path == "/api/scan":
                run_cycle(CFG, snapshot=True)
                return self._json({"ok": True})
            if path == "/api/rename":
                name = str(self._read_json().get("display_name", "")).strip()[:60]
                if name:
                    CFG["display_name"] = name
                    save_config(CFG)
                return self._json({"ok": True, "display_name": CFG["display_name"]})
            if path == "/api/reset-password":
                IDENT["password"] = new_password()
                IDENT["key"] = derive_key(IDENT["user_id"], IDENT["password"])
                write_json(IDENT_PATH, {k: v for k, v in IDENT.items() if k != "key"})
                with PAIR_LOCK:
                    PAIR["admin_ip"] = None
                    PAIR["last_contact"] = None
                    PAIR["contacts"] = 0
                    save_pairing()
                return self._json({"ok": True, "password": IDENT["password"]})
            self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": repr(e)}, 500)


FAILS = {}
SEEN_NONCES = {}
SYNC_LOCK = threading.Lock()


class SyncHandler(Base):
    """LAN endpoint for the admin PC. Every data request must carry an HMAC
    signature made with the key derived from User ID + password; the password
    itself never travels over the network."""

    def _fail(self, ip, code, error):
        with SYNC_LOCK:
            FAILS.setdefault(ip, []).append(time.time())
        with PAIR_LOCK:
            PAIR["last_failed"] = {"ip": ip, "ts": time.time(), "reason": error}
            save_pairing()
        self._json({"error": error}, code)

    def _check(self, path):
        ip = self.client_address[0]
        now = time.time()
        with SYNC_LOCK:
            recent = [t for t in FAILS.get(ip, []) if now - t < 60]
            FAILS[ip] = recent
            if len(recent) >= 10:
                self._json({"error": "too_many_attempts"}, 429)
                return None
        uid = (self.headers.get("X-User") or "").strip().upper()
        ts = self.headers.get("X-Ts") or ""
        nonce = self.headers.get("X-Nonce") or ""
        sig = self.headers.get("X-Sig") or ""
        try:
            ts_val = float(ts)
        except ValueError:
            self._fail(ip, 401, "bad_request")
            return None
        if uid != IDENT["user_id"] or not (8 <= len(nonce) <= 64):
            self._fail(ip, 401, "auth_failed")
            return None
        expect = hmac.new(IDENT["key"], ("GET\n%s\n%s\n%s" % (path, ts, nonce)).encode("utf-8"),
                          hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            self._fail(ip, 401, "auth_failed")
            return None
        if abs(now - ts_val) > 600:
            self._fail(ip, 401, "clock_skew")
            return None
        with SYNC_LOCK:
            for n in [n for n, exp in SEEN_NONCES.items() if exp < now]:
                del SEEN_NONCES[n]
            replay = nonce in SEEN_NONCES
            SEEN_NONCES[nonce] = now + 1300
        if replay:                      # (outside the lock: _fail takes it too)
            self._fail(ip, 401, "replay")
            return None
        with PAIR_LOCK:
            PAIR.setdefault("first_contact", now)
            PAIR["admin_ip"] = ip
            PAIR["last_contact"] = now
            PAIR["contacts"] = int(PAIR.get("contacts") or 0) + 1
            save_pairing()
        return nonce

    def _signed_json(self, obj, nonce):
        body = json.dumps(obj).encode("utf-8")
        sig = hmac.new(IDENT["key"], (nonce + "\n" + hashlib.sha256(body).hexdigest()).encode("utf-8"),
                       hashlib.sha256).hexdigest()
        self._send(body, "application/json; charset=utf-8", extra={"X-Resp-Sig": sig})

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/sync/ping":
                return self._json({"app": APP_ID, "user_id": IDENT["user_id"]})
            if path not in ("/sync/hello", "/sync/report"):
                return self._json({"error": "not found"}, 404)
            nonce = self._check(path)
            if nonce is None:
                return
            if path == "/sync/hello":
                return self._signed_json({"app": APP_ID, "version": VERSION, "user_id": IDENT["user_id"],
                                          "display_name": CFG["display_name"],
                                          "pc_name": socket.gethostname(), "time": time.time()}, nonce)
            run_cycle(CFG, snapshot=False)           # fresh numbers "right now"
            conn = db()
            try:
                rep = build_report(conn, CFG)
            finally:
                conn.close()
            self._signed_json(rep, nonce)
        except Exception as e:
            self._json({"error": repr(e)}, 500)


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
    ap = argparse.ArgumentParser(description="Claude Token Dashboard - USER setup")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--scan-once", action="store_true", help="scan, print totals and exit")
    args = ap.parse_args()

    CFG.update(load_config())
    load_identity()
    load_pairing()

    if args.scan_once:
        run_cycle(CFG, snapshot=True)
        conn = db()
        w = all_windows(conn)
        conn.close()
        print("User ID: %s   Password: %s" % (IDENT["user_id"], IDENT["password"]))
        print("Log folders: %s" % (", ".join(STATE["roots"]) or "none found"))
        for k, v in w.items():
            print("%-9s input+output=%-12d all=%-14d replies=%d" % (k, v["io"], v["all"], v["messages"]))
        return 0

    ui_port = int(CFG["port"])
    if already_running(ui_port):
        url = "http://127.0.0.1:%d/" % ui_port
        print("Dashboard is already running -> %s" % url)
        if CFG.get("open_browser") and not args.no_browser:
            webbrowser.open(url)
        return 0

    ui, ui_port = bind_first_free("127.0.0.1", ui_port, UIHandler)
    if ui is None:
        print("ERROR: no free port for the local dashboard")
        return 2
    sync, sync_port = bind_first_free("0.0.0.0", int(CFG["sync_port"]), SyncHandler, avoid=(ui_port,))
    if sync is None:
        print("WARNING: no free LAN port - the admin will not be able to connect")
    STATE["ui_port"], STATE["sync_port"] = ui_port, sync_port

    try:
        DATA_DIR.mkdir(exist_ok=True)
        (DATA_DIR / "port.txt").write_text(str(ui_port), encoding="utf-8")
    except OSError:
        pass

    stop = threading.Event()
    threading.Thread(target=worker, args=(CFG, stop), daemon=True).start()
    if sync:
        threading.Thread(target=sync.serve_forever, daemon=True).start()
        threading.Thread(target=announcer, args=(stop,), daemon=True).start()

    url = "http://127.0.0.1:%d/" % ui_port
    print("=" * 60)
    print(" Claude Token Dashboard - USER   |   %s" % CFG["display_name"])
    print(" Dashboard : %s" % url)
    print(" User ID   : %s    Password: %s" % (IDENT["user_id"], IDENT["password"]))
    print(" LAN port  : %s   (admin connects here)" % sync_port)
    print(" Keep this window open. Ctrl+C to stop.")
    print("=" * 60)
    if CFG.get("open_browser") and not args.no_browser:
        threading.Timer(1.5, webbrowser.open, [url]).start()
    try:
        ui.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        ui.server_close()
        if sync:
            sync.shutdown()
            sync.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
