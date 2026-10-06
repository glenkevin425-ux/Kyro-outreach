#!/usr/bin/env python3
"""Kyro Outreach — self-contained, tenant-scoped application server.

Local installations use SQLite; Vercel deployments use managed PostgreSQL through a
small compatibility adapter. Resend is optional; demo workspaces never send real email.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from email.utils import parseaddr
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"


def env_file() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'").replace("\n", "\n"))


env_file()
DATA_DIR = ROOT / "data"
VERCEL_RUNTIME = os.getenv("VERCEL", "").lower() in {"1", "true"}
DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or
                os.getenv("POSTGRES_PRISMA_URL") or "").strip()
DB_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "kyro.sqlite3")))
# Vercel's deployment filesystem is read-only; SQLite remains the local-development default.
if not VERCEL_RUNTIME and not DATABASE_URL:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
MAX_DAILY_SENDS = 10
RECENT_CONTACT_DAYS = 30
SESSION_DAYS = 7
DEMO_DEFAULT = "true"
DEMO_ENABLED = True  # Deployment-stage workspace: authentication is intentionally bypassed.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "").strip()
APP_URL = os.getenv("APP_URL", "").strip()
CRON_SECRET = os.getenv("CRON_SECRET", "").strip()
REPLY_WEBHOOK_SECRET = os.getenv("REPLY_WEBHOOK_SECRET", "").strip()
COOKIE_SECURE_DEFAULT = "true" if VERCEL_RUNTIME else "false"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", COOKIE_SECURE_DEFAULT).lower() in {"1", "true", "yes", "on"}
SERVICES = ["Graphic Design", "Branding", "Meta Ads", "TikTok Ads"]
PROSPECT_STATUSES = ["New", "Contacted", "Replied", "Interested", "Not Interested", "Suppressed"]
CAMPAIGN_STATUSES = ["Draft", "Active", "Paused", "Completed"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_now() -> str:
    return utc_now().isoformat()


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def normalize_email(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def valid_email(value: Any) -> bool:
    email = normalize_email(value)
    if len(email) > 254 or not email or " " in email:
        return False
    if email.count("@") != 1:
        return False
    local, domain = email.rsplit("@", 1)
    if not local or len(local) > 64 or not domain or "." not in domain:
        return False
    return bool(re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+", local, re.I) and
                re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain, re.I))


def clean_text(value: Any, limit: int = 2000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = html.unescape(value)
    value = re.sub(r"<[^>]*>", "", value)
    value = "".join(ch for ch in value if ch in "\n\t" or ord(ch) >= 32)
    return value.strip()[:limit]


def safe_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def get_tz(value: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(value or "Africa/Nairobi")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Africa/Nairobi")


def local_now(tz_name: str) -> datetime:
    return utc_now().astimezone(get_tz(tz_name))


def valid_time(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value))


def parse_datetime(value: Any, tz_name: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=get_tz(tz_name))
        return result.astimezone(timezone.utc).replace(microsecond=0)
    except (ValueError, TypeError):
        return None


def in_window(now: datetime, tz_name: str, start: str, end: str) -> bool:
    local = now.astimezone(get_tz(tz_name))
    current = local.strftime("%H:%M")
    # Sending windows deliberately do not cross midnight; this keeps quota dates clear.
    return start <= current < end


def local_day_bounds(tz_name: str, day=None) -> tuple[str, str, str]:
    local_date = day or local_now(tz_name).date()
    zone = get_tz(tz_name)
    start_local = datetime.combine(local_date, datetime.min.time(), tzinfo=zone)
    end_local = datetime.combine(local_date + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    return local_date.isoformat(), iso(start_local.astimezone(timezone.utc)), iso(end_local.astimezone(timezone.utc))


def successful_sends_today(c: sqlite3.Connection, user_id: str, tz_name: str, day=None) -> int:
    _, start_utc, end_utc = local_day_bounds(tz_name, day)
    return int(c.execute("SELECT COUNT(*) AS n FROM email_sends WHERE user_id=? AND status='sent' AND sent_at>=? AND sent_at<?",
                         (user_id, start_utc, end_utc)).fetchone()["n"])


def active_reservations_today(c: sqlite3.Connection, user_id: str, tz_name: str, day=None, campaign_id: str | None = None) -> int:
    target = day or local_now(tz_name).date()
    if campaign_id:
        rows = c.execute("SELECT created_at FROM send_reservations WHERE user_id=? AND campaign_id=? AND status='reserved'", (user_id, campaign_id)).fetchall()
    else:
        rows = c.execute("SELECT created_at FROM send_reservations WHERE user_id=? AND status='reserved'", (user_id,)).fetchall()
    count = 0
    for row in rows:
        created = parse_datetime(row["created_at"], tz_name)
        if created and created.astimezone(get_tz(tz_name)).date() == target:
            count += 1
    return count


class PostgresConnection:
    """Small SQLite-compatible adapter for the PostgreSQL statements used by Kyro.

    Keeping the application SQL parameterized with ``?`` lets local SQLite remain
    dependency-free while Vercel uses a pooled managed PostgreSQL connection.
    """
    is_postgres = True

    def __init__(self, dsn: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL is configured but psycopg is not installed.") from exc
        self._psycopg = psycopg
        self._raw = psycopg.connect(dsn, connect_timeout=10, autocommit=True, row_factory=dict_row)

    @property
    def in_transaction(self) -> bool:
        return bool(self._raw and self._raw.info.transaction_status != self._psycopg.pq.TransactionStatus.IDLE)

    @staticmethod
    def _sql(statement: str) -> str:
        sql = statement.replace("BEGIN IMMEDIATE", "BEGIN")
        sql = re.sub(r"\s+COLLATE\s+NOCASE\b", "", sql, flags=re.IGNORECASE)
        # SQLite's scalar MAX(a,b) becomes PostgreSQL's GREATEST(a,b).
        sql = re.sub(r"MAX\(([^()]+)\)", lambda m: "GREATEST(" + m.group(1) + ")"
                     if "," in m.group(1) else "MAX(" + m.group(1) + ")", sql, flags=re.IGNORECASE)
        return sql.replace("?", "%s")

    def execute(self, statement: str, parameters: tuple | list = ()):
        if statement.lstrip().upper().startswith("PRAGMA"):
            return _NoopCursor()
        try:
            return self._raw.execute(self._sql(statement), parameters)
        except self._psycopg.IntegrityError as exc:
            # Existing route logic intentionally catches sqlite3.IntegrityError.
            raise sqlite3.IntegrityError(str(exc)) from None

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            statement = statement.strip()
            if statement and not statement.upper().startswith("PRAGMA"):
                self.execute(statement)

    def close(self) -> None:
        if self._raw is not None:
            self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.in_transaction:
                self.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.close()


class _NoopCursor:
    rowcount = -1

    @staticmethod
    def fetchone():
        return None

    @staticmethod
    def fetchall():
        return []


def acquire_transaction_lock(connection, key: str) -> None:
    """Serialize quota/auth critical sections across independent serverless workers."""
    if getattr(connection, "is_postgres", False):
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))", (key,))


class ClosingSQLiteConnection(sqlite3.Connection):
    """Match the PostgreSQL adapter's context-manager close behavior for tests/local use."""
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def db_connect():
    if DATABASE_URL:
        return PostgresConnection(DATABASE_URL)
    if VERCEL_RUNTIME:
        raise RuntimeError("DATABASE_URL is required on Vercel; SQLite is local-only and not durable there.")
    c = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None, factory=ClosingSQLiteConnection)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = 15000")
    return c


def init_db() -> None:
    with db_connect() as c:
        postgres = getattr(c, "is_postgres", False)
        if postgres:
            c.execute("BEGIN")
            acquire_transaction_lock(c, "kyro-schema-v1")
        try:
            c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL, display_name TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS profiles (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
          display_name TEXT NOT NULL, sender_name TEXT NOT NULL, sender_email TEXT NOT NULL,
          reply_to TEXT NOT NULL DEFAULT '', timezone TEXT NOT NULL DEFAULT 'Africa/Nairobi', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agency_settings (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
          agency_name TEXT NOT NULL DEFAULT 'Kcreatives', tagline TEXT NOT NULL DEFAULT 'Design. Strategy. Growth.',
          services TEXT NOT NULL DEFAULT '["Graphic Design","Branding","Meta Ads","TikTok Ads"]',
          description TEXT NOT NULL DEFAULT '', sending_window_start TEXT NOT NULL DEFAULT '09:00',
          sending_window_end TEXT NOT NULL DEFAULT '17:00', daily_limit INTEGER NOT NULL DEFAULT 10 CHECK(daily_limit BETWEEN 1 AND 10),
          follow_up_delay_days INTEGER NOT NULL DEFAULT 4, test_recipient TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prospects (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          business_name TEXT NOT NULL, contact_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL,
          phone TEXT NOT NULL DEFAULT '', website TEXT NOT NULL DEFAULT '', social_urls TEXT NOT NULL DEFAULT '[]',
          industry TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'New', tags TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_contacted_at TEXT, next_follow_up_at TEXT,
          responded_at TEXT, UNIQUE(user_id, email),
          CHECK(status IN ('New','Contacted','Replied','Interested','Not Interested','Suppressed'))
        );
        CREATE INDEX IF NOT EXISTS prospects_user_status_idx ON prospects(user_id,status,created_at DESC);
        CREATE INDEX IF NOT EXISTS prospects_user_business_idx ON prospects(user_id,business_name COLLATE NOCASE);
        CREATE TABLE IF NOT EXISTS campaigns (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          name TEXT NOT NULL, service_focus TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Draft',
          daily_limit INTEGER NOT NULL DEFAULT 10 CHECK(daily_limit BETWEEN 1 AND 10),
          sending_window_start TEXT NOT NULL, sending_window_end TEXT NOT NULL,
          follow_up_delay_days INTEGER NOT NULL DEFAULT 4, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          CHECK(status IN ('Draft','Active','Paused','Completed'))
        );
        CREATE INDEX IF NOT EXISTS campaigns_user_status_idx ON campaigns(user_id,status);
        CREATE TABLE IF NOT EXISTS campaign_prospects (
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
          prospect_id TEXT NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
          status TEXT NOT NULL DEFAULT 'Selected', created_at TEXT NOT NULL,
          PRIMARY KEY(user_id,campaign_id,prospect_id)
        );
        CREATE TABLE IF NOT EXISTS email_drafts (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          prospect_id TEXT NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
          campaign_id TEXT REFERENCES campaigns(id) ON DELETE SET NULL,
          subject TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '', personalization_notes TEXT NOT NULL DEFAULT '',
          service_focus TEXT NOT NULL DEFAULT 'Graphic Design', status TEXT NOT NULL DEFAULT 'Draft',
          kind TEXT NOT NULL DEFAULT 'initial', original_send_id TEXT,
          scheduled_for TEXT, approved_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          CHECK(status IN ('Draft','Awaiting Approval','Approved','Scheduled','Sending','Sent','Failed','Cancelled','Paused')),
          CHECK(kind IN ('initial','follow_up'))
        );
        CREATE INDEX IF NOT EXISTS drafts_user_status_schedule_idx ON email_drafts(user_id,status,scheduled_for);
        CREATE TABLE IF NOT EXISTS email_sends (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          prospect_id TEXT NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
          campaign_id TEXT REFERENCES campaigns(id) ON DELETE SET NULL,
          draft_id TEXT NOT NULL REFERENCES email_drafts(id) ON DELETE CASCADE,
          message_id TEXT NOT NULL DEFAULT '', recipient TEXT NOT NULL, subject TEXT NOT NULL,
          sent_at TEXT NOT NULL, status TEXT NOT NULL, provider_status TEXT NOT NULL DEFAULT '',
          error_message TEXT NOT NULL DEFAULT '', idempotency_key TEXT NOT NULL DEFAULT '',
          CHECK(status IN ('sent','failed'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_success_per_draft ON email_sends(user_id,draft_id) WHERE status='sent';
        CREATE INDEX IF NOT EXISTS sends_user_sent_idx ON email_sends(user_id,sent_at DESC,status);
        CREATE TABLE IF NOT EXISTS follow_ups (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          prospect_id TEXT NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
          campaign_id TEXT REFERENCES campaigns(id) ON DELETE SET NULL,
          original_send_id TEXT NOT NULL REFERENCES email_sends(id) ON DELETE CASCADE,
          scheduled_for TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled', draft_id TEXT REFERENCES email_drafts(id) ON DELETE SET NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          CHECK(status IN ('scheduled','awaiting_approval','sent','cancelled','paused')),
          UNIQUE(user_id,original_send_id)
        );
        CREATE INDEX IF NOT EXISTS followups_user_due_idx ON follow_ups(user_id,status,scheduled_for);
        CREATE TABLE IF NOT EXISTS activity_log (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          prospect_id TEXT REFERENCES prospects(id) ON DELETE SET NULL,
          campaign_id TEXT REFERENCES campaigns(id) ON DELETE SET NULL,
          type TEXT NOT NULL, description TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS activity_user_date_idx ON activity_log(user_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS suppressions (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          email TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(user_id,email)
        );
        CREATE TABLE IF NOT EXISTS daily_send_counters (
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, date TEXT NOT NULL,
          timezone TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0 CHECK(count BETWEEN 0 AND 10), updated_at TEXT NOT NULL,
          PRIMARY KEY(user_id,date,timezone)
        );
        CREATE TABLE IF NOT EXISTS send_reservations (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          draft_id TEXT NOT NULL REFERENCES email_drafts(id) ON DELETE CASCADE,
          campaign_id TEXT REFERENCES campaigns(id) ON DELETE SET NULL,
          date TEXT NOT NULL, timezone TEXT NOT NULL, idempotency_key TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('reserved','used','released')),
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_id,idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS reservations_active_idx ON send_reservations(user_id,date,timezone,status);
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          csrf_token TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rate_limits (
          key TEXT PRIMARY KEY, count INTEGER NOT NULL, window_start DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_events (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          provider_event_id TEXT NOT NULL, event_type TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(user_id,provider_event_id)
        );
            """)
            if postgres:
                c.execute("COMMIT")
        except Exception:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise


class APIError(Exception):
    def __init__(self, status: int, message: str, code: str = "request_error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def audit(c: sqlite3.Connection, user_id: str, kind: str, description: str,
          prospect_id: str | None = None, campaign_id: str | None = None, metadata: dict | None = None) -> None:
    c.execute("INSERT INTO activity_log(id,user_id,prospect_id,campaign_id,type,description,metadata,created_at) VALUES(?,?,?,?,?,?,?,?)",
              (secrets.token_hex(12), user_id, prospect_id, campaign_id, kind, description,
               json.dumps(metadata or {}, ensure_ascii=False), iso_now()))


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 310_000
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${derived.hex()}"


def password_verify(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(got, digest)
    except (ValueError, TypeError):
        return False


def create_session(c: sqlite3.Connection, user_id: str) -> tuple[str, str]:
    raw = secrets.token_urlsafe(36)
    csrf = secrets.token_urlsafe(24)
    created = utc_now()
    c.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
              (hashlib.sha256(raw.encode()).hexdigest(), user_id, csrf,
               iso(created + timedelta(days=SESSION_DAYS)), iso(created)))
    return raw, csrf


def create_profile_and_settings(c: sqlite3.Connection, user_id: str, display_name: str,
                                sender_name: str, sender_email: str) -> None:
    timestamp = iso_now()
    c.execute("INSERT INTO profiles(id,user_id,display_name,sender_name,sender_email,reply_to,timezone,created_at) VALUES(?,?,?,?,?,?,?,?)",
              (secrets.token_hex(12), user_id, display_name, sender_name, sender_email, sender_email, "Africa/Nairobi", timestamp))
    c.execute("INSERT INTO agency_settings(id,user_id,agency_name,tagline,services,description,sending_window_start,sending_window_end,daily_limit,follow_up_delay_days,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (secrets.token_hex(12), user_id, "Kcreatives", "Design. Strategy. Growth.", json.dumps(SERVICES),
               "A compact client-acquisition studio for finding the right businesses, starting relevant conversations and turning interest into work.", "09:00", "17:00", MAX_DAILY_SENDS, 4, timestamp))


def ensure_demo_user() -> str:
    uid = "kyro-clientos-demo-v2"
    with db_connect() as c:
        user = c.execute("SELECT id FROM users WHERE id=? AND is_demo=1", (uid,)).fetchone()
        if not user:
            c.execute("INSERT INTO users(id,workspace_id,email,password_hash,display_name,is_demo,created_at) VALUES(?,?,?,?,?,?,?)",
                      (uid, uid, "demo@kyro.example", password_hash(secrets.token_urlsafe(24)), "Kyro Demo", 1, iso_now()))
            create_profile_and_settings(c, uid, "Kyro Demo", "Glen", "glen@kcreatives.example")
        existing = c.execute("SELECT COUNT(*) AS n FROM prospects WHERE user_id=?", (uid,)).fetchone()["n"]
        if existing:
            return uid
        # Fictional, reserved .example addresses. Every row and metric in this workspace is labeled DEMO.
        names = [
          ("Maji House", "Amina", "hello@majihouse.example", "Hospitality", "Kakamega", "Branding", ["hospitality", "local"]),
          ("Northline Motors", "Brian", "service@northline.example", "Automotive", "Kisumu", "Graphic Design", ["automotive"]),
          ("Luma Wellness", "Miriam", "care@lumawellness.example", "Wellness", "Kakamega", "Meta Ads", ["wellness"]),
          ("Nairobi Form", "Nia", "hello@nairobiform.example", "Fashion", "Nairobi", "TikTok Ads", ["fashion"]),
          ("Pulse Studio", "David", "team@pulsestudio.example", "Fitness", "Eldoret", "Meta Ads", ["fitness"]),
          ("Lakehouse Living", "Sam", "info@lakehouseliving.example", "Home & Living", "Kisumu", "Branding", ["retail"]),
          ("Northstar Creative", "Leah", "studio@northstar.example", "Creative Services", "Nairobi", "Graphic Design", ["creative"]),
          ("Mara Events", "Joel", "hello@maraevents.example", "Events", "Kakamega", "TikTok Ads", ["events"]),
        ]
        campaign_id = secrets.token_hex(12)
        now = utc_now()
        c.execute("INSERT INTO campaigns(id,user_id,name,service_focus,status,daily_limit,sending_window_start,sending_window_end,follow_up_delay_days,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (campaign_id, uid, "Kcreatives Growth Sprint", "Branding", "Active", 10, "09:00", "17:00", 4, iso(now - timedelta(days=10)), iso_now()))
        ids: list[str] = []
        for ix, (business, contact, email, industry, loc, service, tags) in enumerate(names):
            pid = secrets.token_hex(12)
            ids.append(pid)
            status = "Replied" if ix in (1, 5) else ("Interested" if ix == 2 else ("New" if ix == 7 else "Contacted"))
            created = iso(now - timedelta(days=18 - ix))
            c.execute("INSERT INTO prospects(id,user_id,business_name,contact_name,email,industry,location,notes,source,status,tags,created_at,updated_at,last_contacted_at,responded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (pid, uid, business, contact, email, industry, loc, "Demo record — replace with verified research before using it in a real client workflow.", "Demo workspace", status,
                       json.dumps(tags), created, created,
                       iso(now - timedelta(days=5)) if ix < 7 else None,
                       iso(now - timedelta(days=3)) if status in ("Replied", "Interested") else None))
            c.execute("INSERT INTO campaign_prospects(user_id,campaign_id,prospect_id,status,created_at) VALUES(?,?,?,?,?)",
                      (uid, campaign_id, pid, "Selected", created))
        tz = "Africa/Nairobi"
        today = local_now(tz).date().isoformat()
        c.execute("INSERT INTO daily_send_counters(user_id,date,timezone,count,updated_at) VALUES(?,?,?,?,?)",
                  (uid, today, tz, 7, iso_now()))
        # Seven recorded demo sends, no provider contact is ever made for this account.
        for ix in range(7):
            pid = ids[ix]
            draft_id = secrets.token_hex(12)
            sent_at = iso(now - timedelta(hours=max(1, 7 - ix)))
            subject = f"A quick idea for {names[ix][0]}"
            body = f"Hi {names[ix][1]},\n\nA demo draft focused on {names[ix][5]}.\n\nBest,\nGlen\nKcreatives"
            c.execute("INSERT INTO email_drafts(id,user_id,prospect_id,campaign_id,subject,body,personalization_notes,service_focus,status,kind,approved_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (draft_id, uid, pid, campaign_id, subject, body, "Fictional demo content", names[ix][5], "Sent", "initial", sent_at, sent_at, sent_at))
            c.execute("INSERT INTO email_sends(id,user_id,prospect_id,campaign_id,draft_id,message_id,recipient,subject,sent_at,status,provider_status,error_message,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (secrets.token_hex(12), uid, pid, campaign_id, draft_id, "demo-message", names[ix][2], subject,
                       sent_at, "sent", "Demo simulator — not delivered", "", "demo-seed-" + draft_id))
        # Earlier demo activity produces a realistic follow-up workload without inventing production metrics.
        for ix in (0, 3, 4, 6):
            pid = ids[ix]
            original = c.execute("SELECT id,draft_id FROM email_sends WHERE user_id=? AND prospect_id=? ORDER BY sent_at LIMIT 1", (uid, pid)).fetchone()
            if not original:
                continue
            due = iso(now - timedelta(minutes=20 - ix))
            follow_id = secrets.token_hex(12)
            follow_draft = secrets.token_hex(12)
            c.execute("INSERT INTO email_drafts(id,user_id,prospect_id,campaign_id,subject,body,personalization_notes,service_focus,status,kind,original_send_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (follow_draft, uid, pid, campaign_id, "A brief follow-up", f"Hi {names[ix][1]},\n\nJust following up on my note. If useful, I can share a few ideas around {names[ix][5]}.\n\nBest,\nGlen", "Demo follow-up — review before approval.", names[ix][5], "Draft", "follow_up", original["id"], iso(now - timedelta(days=4)), iso(now - timedelta(days=4))))
            c.execute("INSERT INTO follow_ups(id,user_id,prospect_id,campaign_id,original_send_id,scheduled_for,status,draft_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (follow_id, uid, pid, campaign_id, original["id"], due, "scheduled", follow_draft, iso(now - timedelta(days=4)), iso_now()))
        demo_local_now = local_now(tz)
        demo_candidate = demo_local_now + timedelta(minutes=10)
        if demo_candidate.strftime("%H:%M") >= "17:00":
            demo_candidate = datetime.combine(demo_local_now.date() + timedelta(days=1), datetime.min.time().replace(hour=9, minute=15), tzinfo=get_tz(tz))
        elif demo_candidate.strftime("%H:%M") < "09:00":
            demo_candidate = demo_local_now.replace(hour=9, minute=15, second=0, microsecond=0)
        demo_schedule = demo_candidate.astimezone(timezone.utc)
        demo_draft_id = secrets.token_hex(12)
        c.execute("INSERT INTO email_drafts(id,user_id,prospect_id,campaign_id,subject,body,personalization_notes,service_focus,status,kind,scheduled_for,approved_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (demo_draft_id, uid, ids[7], campaign_id, "A quick idea for Mara Events",
                   "Hi Joel,\n\nThis is a fictional demo email scheduled for review. No email will be delivered in DEMO MODE.\n\nBest,\nGlen\nKcreatives",
                   "Fictional demo content — review before use.", "TikTok Ads", "Scheduled", "initial", iso(demo_schedule), iso(now), iso(now), iso(now)))
        activities = [
          ("email_sent", "7 demo outreach emails recorded today", ids[0]),
          ("reply_recorded", "Reply recorded from Northline Motors", ids[1]),
          ("reply_recorded", "Interested reply recorded from Luma Wellness", ids[2]),
          ("reply_recorded", "Reply recorded from Lakehouse Living", ids[5]),
          ("draft_approved", "Branding draft approved", ids[5]),
          ("prospect_added", "Prospect added to the pipeline", ids[7]),
          ("follow_up_scheduled", "4 demo follow-ups are due for review", ids[0]),
        ]
        for i, (kind, description, pid) in enumerate(activities):
            audit(c, uid, kind, description, prospect_id=pid, campaign_id=campaign_id,
                  metadata={"demo": True, "recorded_at": iso(now - timedelta(minutes=i * 13))})
        return uid


def provider_status(user: sqlite3.Row | dict) -> dict:
    if user and int(user["is_demo"]):
        return {"connected": True, "mode": "demo", "label": "Demo simulator", "provider": "Demo"}
    connected = bool(RESEND_API_KEY and RESEND_FROM_EMAIL)
    return {"connected": connected, "mode": "live" if connected else "not_configured",
            "label": "Configured · Resend" if connected else "Email provider not connected",
            "provider": "Resend" if connected else None}


class EmailProvider:
    """Provider-neutral email contract."""
    def send_email(self, *, sender: str, reply_to: str, recipient: str, subject: str,
                   text: str, idempotency_key: str) -> dict:
        raise NotImplementedError

    def verify_connection(self) -> bool:
        raise NotImplementedError

    def get_status(self) -> dict:
        raise NotImplementedError


class ResendEmailProvider(EmailProvider):
    def __init__(self, api_key: str, from_email: str):
        self.api_key = api_key
        self.from_email = from_email

    def send_email(self, *, sender: str, reply_to: str, recipient: str, subject: str,
                   text: str, idempotency_key: str) -> dict:
        sender_address = self.from_email
        sender_value = f"{sender} <{sender_address}>" if sender else sender_address
        payload: dict[str, Any] = {"from": sender_value, "to": [recipient], "subject": subject, "text": text}
        if reply_to:
            payload["reply_to"] = reply_to
        request = urllib.request.Request(
            "https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                     "Idempotency-Key": idempotency_key})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.loads(response.read(1024 * 128).decode("utf-8"))
                return {"id": str(result.get("id", "")), "status": "accepted"}
        except urllib.error.HTTPError as exc:
            # Never expose or log credentials. Keep only a short provider response for the operator.
            detail = ""
            try:
                body = json.loads(exc.read(4096).decode("utf-8", "replace"))
                detail = clean_text(body.get("message", body.get("name", "")), 220)
            except Exception:
                detail = ""
            raise RuntimeError(detail or f"Provider returned HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("The email provider could not be reached") from None

    def verify_connection(self) -> bool:
        return bool(self.api_key and self.from_email)

    def get_status(self) -> dict:
        return {"connected": self.verify_connection(), "provider": "Resend" if self.verify_connection() else None}


def make_provider() -> ResendEmailProvider | None:
    if RESEND_API_KEY and RESEND_FROM_EMAIL:
        return ResendEmailProvider(RESEND_API_KEY, RESEND_FROM_EMAIL)
    return None


def provision_campaign_send_window(c: sqlite3.Connection, user_id: str, campaign_id: str | None,
                                   settings: sqlite3.Row) -> tuple[str, str, sqlite3.Row | None]:
    camp = None
    if campaign_id:
        camp = c.execute("SELECT * FROM campaigns WHERE id=? AND user_id=?", (campaign_id, user_id)).fetchone()
    if camp:
        return camp["sending_window_start"], camp["sending_window_end"], camp
    return settings["sending_window_start"], settings["sending_window_end"], camp


def prospect_record(data: dict) -> dict:
    business = clean_text(data.get("business_name"), 160)
    email = normalize_email(data.get("email"))
    if not business:
        raise APIError(400, "Business name is required.", "validation")
    if not valid_email(email):
        raise APIError(400, "Enter a valid email address. Email addresses are normalized before saving.", "validation")
    status = clean_text(data.get("status", "New"), 32) or "New"
    if status not in PROSPECT_STATUSES:
        raise APIError(400, "Choose a valid prospect status.", "validation")
    socials = data.get("social_urls", data.get("socials", []))
    if isinstance(socials, str):
        socials = [x.strip() for x in re.split(r"[\n,]+", socials) if x.strip()]
    if not isinstance(socials, list):
        socials = []
    normalized_socials = []
    for item in socials[:20]:
        social = clean_text(item, 500)
        if not social:
            continue
        if not re.match(r"^https?://", social, re.I):
            social = "https://" + social
        parsed = urlparse(social)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
            raise APIError(400, "Social profile URLs must be valid http or https links.", "validation")
        normalized_socials.append(social)
    socials = normalized_socials
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [x.strip() for x in re.split(r"[,\n]+", tags) if x.strip()]
    if not isinstance(tags, list):
        tags = []
    tags = list(dict.fromkeys(clean_text(x, 40) for x in tags if clean_text(x, 40)))[:30]
    website = clean_text(data.get("website"), 500)
    if website:
        if not re.match(r"^https?://", website, re.I):
            website = "https://" + website
        parsed_website = urlparse(website)
        if parsed_website.scheme not in ("http", "https") or not parsed_website.netloc or parsed_website.username or parsed_website.password:
            raise APIError(400, "Website must be a valid http or https URL.", "validation")
    return {
      "business_name": business, "contact_name": clean_text(data.get("contact_name"), 120), "email": email,
      "phone": clean_text(data.get("phone"), 80), "website": website,
      "social_urls": json.dumps(socials, ensure_ascii=False), "industry": clean_text(data.get("industry"), 120),
      "location": clean_text(data.get("location"), 120), "notes": clean_text(data.get("notes"), 3000),
      "source": clean_text(data.get("source"), 120), "status": status, "tags": json.dumps(tags, ensure_ascii=False)
    }


def row_dict(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    return {k: row[k] for k in row.keys()}


def compute_followup_draft(c: sqlite3.Connection, user_id: str, prospect: sqlite3.Row,
                           campaign: sqlite3.Row | None, send_row_id: str, original_subject: str,
                           service: str, due: datetime) -> str:
    draft_id = secrets.token_hex(12)
    profile = c.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    agency = c.execute("SELECT * FROM agency_settings WHERE user_id=?", (user_id,)).fetchone()
    signature = profile["sender_name"] if profile else "Kcreatives"
    recipient_name = prospect["contact_name"] or "there"
    business = prospect["business_name"]
    subject = original_subject if original_subject.lower().startswith("re:") else "Re: " + original_subject
    body = (f"Hi {recipient_name},\n\nI wanted to follow up on my note about {service.lower()} for {business}. "
            f"If it would be useful, I can send a few practical ideas based on the details you've shared. "
            f"Would you prefer I send those by email, or is a short conversation easier?\n\n"
            f"Best,\n{signature}\n{agency['agency_name'] if agency else 'Kcreatives'}")
    timestamp = iso_now()
    c.execute("INSERT INTO email_drafts(id,user_id,prospect_id,campaign_id,subject,body,personalization_notes,service_focus,status,kind,original_send_id,scheduled_for,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (draft_id, user_id, prospect["id"], campaign["id"] if campaign else None, subject, body,
               "Follow-up draft based only on the original sent message. Review and approve before sending.", service,
               "Draft", "follow_up", send_row_id, iso(due), timestamp, timestamp))
    follow_id = secrets.token_hex(12)
    c.execute("INSERT INTO follow_ups(id,user_id,prospect_id,campaign_id,original_send_id,scheduled_for,status,draft_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (follow_id, user_id, prospect["id"], campaign["id"] if campaign else None, send_row_id, iso(due),
               "scheduled", draft_id, timestamp, timestamp))
    c.execute("UPDATE prospects SET next_follow_up_at=?,updated_at=? WHERE id=? AND user_id=?",
              (iso(due), timestamp, prospect["id"], user_id))
    return follow_id


def send_draft(user: sqlite3.Row, draft_id: str, idempotency_key: str | None = None) -> dict:
    user_id = user["id"]
    idempotency_key = (idempotency_key or f"outreach:{draft_id}").strip()[:180]
    if not re.fullmatch(r"[A-Za-z0-9:_-]{8,180}", idempotency_key):
        raise APIError(400, "A valid idempotency key is required.", "validation")
    provider = make_provider()
    if not int(user["is_demo"]) and not provider:
        raise APIError(503, "Email provider not connected. No outreach quota was consumed.", "provider_not_configured")

    c = db_connect()
    reservation_id = secrets.token_hex(12)
    draft = None
    prospect = None
    campaign = None
    settings = None
    profile = None
    recipient = ""
    subject = ""
    body = ""
    today = ""
    tz_name = "Africa/Nairobi"
    try:
        c.execute("BEGIN IMMEDIATE")
        acquire_transaction_lock(c, "send-quota:" + user_id)
        draft = c.execute("SELECT * FROM email_drafts WHERE id=? AND user_id=?", (draft_id, user_id)).fetchone()
        if not draft:
            raise APIError(404, "Draft not found.", "not_found")
        prospect = c.execute("SELECT * FROM prospects WHERE id=? AND user_id=?", (draft["prospect_id"], user_id)).fetchone()
        if not prospect:
            raise APIError(404, "Prospect not found.", "not_found")
        settings = c.execute("SELECT * FROM agency_settings WHERE user_id=?", (user_id,)).fetchone()
        profile = c.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        if not settings or not profile:
            raise APIError(400, "Complete your sender settings before sending.", "settings_required")
        tz_name = profile["timezone"] or "Africa/Nairobi"
        now = utc_now()
        local = now.astimezone(get_tz(tz_name))
        today = local.date().isoformat()
        existing = c.execute("SELECT * FROM email_sends WHERE user_id=? AND draft_id=? AND status='sent'", (user_id, draft_id)).fetchone()
        if existing:
            c.execute("COMMIT")
            result = {"sent": True, "duplicate": True, "send_id": existing["id"], "sent_at": existing["sent_at"], "message": "This approved email was already sent; it was not sent again."}
            c.close()
            return result
        if draft["status"] not in ("Approved", "Scheduled", "Sending") or not draft["approved_at"]:
            raise APIError(409, "Only an explicitly approved email can be sent.", "approval_required")
        if draft["status"] == "Scheduled" and draft["scheduled_for"]:
            due = parse_datetime(draft["scheduled_for"], tz_name)
            if due and due > now:
                raise APIError(409, "This email is scheduled for a later time.", "not_due")
        if draft["scheduled_for"] and draft["kind"] == "follow_up":
            due = parse_datetime(draft["scheduled_for"], tz_name)
            if due and due > now:
                raise APIError(409, "This follow-up is not due yet.", "not_due")
        if not valid_email(prospect["email"]) or prospect["email"] != normalize_email(prospect["email"]):
            raise APIError(400, "The prospect's email address is invalid.", "invalid_recipient")
        if prospect["status"] in ("Suppressed", "Not Interested", "Replied", "Interested"):
            raise APIError(409, "This prospect is not eligible for outreach. Their status stops further sends and follow-ups.", "prospect_ineligible")
        if c.execute("SELECT 1 FROM suppressions WHERE user_id=? AND email=?", (user_id, prospect["email"])).fetchone():
            raise APIError(409, "This address is on the suppression list. No email was sent.", "suppressed")
        if not draft["subject"].strip() or not draft["body"].strip():
            raise APIError(400, "Add a subject and message before sending.", "empty_draft")
        if not draft["campaign_id"]:
            raise APIError(409, "Assign this approved email to an active campaign before sending.", "campaign_required")
        campaign = c.execute("SELECT * FROM campaigns WHERE id=? AND user_id=?", (draft["campaign_id"], user_id)).fetchone()
        if not campaign or campaign["status"] != "Active":
            raise APIError(409, "This campaign is not active. Activate it before sending.", "campaign_inactive")
        if not c.execute("SELECT 1 FROM campaign_prospects WHERE user_id=? AND campaign_id=? AND prospect_id=?", (user_id, campaign["id"], prospect["id"])).fetchone():
            raise APIError(409, "This prospect is not selected for the campaign.", "campaign_membership_required")
        if draft["kind"] == "follow_up":
            fup = c.execute("SELECT * FROM follow_ups WHERE draft_id=? AND user_id=?", (draft_id, user_id)).fetchone()
            if not fup or fup["status"] != "scheduled":
                raise APIError(409, "This follow-up has been stopped or cancelled.", "followup_stopped")
            original = c.execute("SELECT * FROM email_sends WHERE id=? AND user_id=? AND status='sent'", (fup["original_send_id"], user_id)).fetchone()
            if not original:
                raise APIError(409, "The original email was not successfully sent.", "followup_not_eligible")
        else:
            recent_cutoff = iso(now - timedelta(days=RECENT_CONTACT_DAYS))
            recent = c.execute("SELECT id FROM email_sends WHERE user_id=? AND prospect_id=? AND status='sent' AND sent_at>=? LIMIT 1",
                               (user_id, prospect["id"], recent_cutoff)).fetchone()
            if recent:
                raise APIError(409, "This prospect was contacted recently. The 30-day contact safeguard prevents another initial email.", "recent_contact")
        # Stop any send if a prior response was recorded, even if a status update was missed.
        replied = c.execute("SELECT 1 FROM activity_log WHERE user_id=? AND prospect_id=? AND type IN ('reply_recorded','reply_received','prospect_not_interested') LIMIT 1",
                            (user_id, prospect["id"])).fetchone()
        if replied:
            raise APIError(409, "A reply is recorded for this prospect. Pending outreach is stopped.", "replied")
        start, end, _ = provision_campaign_send_window(c, user_id, campaign["id"], settings)
        if not in_window(now, tz_name, start, end):
            raise APIError(409, f"Outside the sending window ({start}–{end} {tz_name}). Nothing was sent.", "outside_window")
        # A single active reservation per draft prevents a caller from racing the same message
        # through two different idempotency keys.
        active_draft_reservation = c.execute("SELECT * FROM send_reservations WHERE user_id=? AND draft_id=? AND status='reserved' ORDER BY updated_at DESC LIMIT 1", (user_id, draft_id)).fetchone()
        if active_draft_reservation:
            active_since = datetime.fromisoformat(active_draft_reservation["updated_at"])
            if active_since.tzinfo is None:
                active_since = active_since.replace(tzinfo=timezone.utc)
            if (now - active_since).total_seconds() < 180:
                raise APIError(409, "This email is already being processed. Please wait before retrying.", "send_in_progress")
            c.execute("UPDATE send_reservations SET status='released',updated_at=? WHERE id=?", (iso_now(), active_draft_reservation["id"]))
        # A stable idempotency row plus an active reservation makes parallel clicks/workers safe.
        reservation = c.execute("SELECT * FROM send_reservations WHERE user_id=? AND idempotency_key=?", (user_id, idempotency_key)).fetchone()
        if reservation and reservation["status"] == "used":
            # Recover the result for callers that lost the first response.
            old = c.execute("SELECT * FROM email_sends WHERE user_id=? AND draft_id=? AND status='sent'", (user_id, draft_id)).fetchone()
            if old:
                c.execute("COMMIT")
                result = {"sent": True, "duplicate": True, "send_id": old["id"], "sent_at": old["sent_at"], "message": "This send was already completed."}
                c.close()
                return result
        if reservation and reservation["status"] == "reserved":
            created = datetime.fromisoformat(reservation["updated_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if (now - created).total_seconds() < 180:
                raise APIError(409, "This email is already being processed. Please wait before retrying.", "send_in_progress")
            c.execute("UPDATE send_reservations SET status='released',updated_at=? WHERE id=?", (iso_now(), reservation["id"]))
        counter = c.execute("SELECT count FROM daily_send_counters WHERE user_id=? AND date=? AND timezone=?",
                            (user_id, today, tz_name)).fetchone()
        # Sent rows are the cross-timezone source of truth. This prevents changing the
        # workspace timezone from resetting today's 10-send ceiling.
        count = max(int(counter["count"]) if counter else 0, successful_sends_today(c, user_id, tz_name, local.date()))
        pending = active_reservations_today(c, user_id, tz_name, local.date())
        limit = min(int(settings["daily_limit"]), MAX_DAILY_SENDS)
        if count + int(pending) >= limit:
            audit(c, user_id, "quota_reached", "Daily outreach limit reached; send was blocked.", prospect["id"], campaign["id"], {"count": count, "limit": limit})
            c.execute("COMMIT")
            raise APIError(429, "Daily outreach limit reached. Kyro will resume tomorrow. No email was sent.", "quota_reached")
        campaign_today = 0
        sent_rows = c.execute("SELECT sent_at FROM email_sends WHERE user_id=? AND campaign_id=? AND status='sent'",
                              (user_id, campaign["id"])).fetchall()
        for sent_row in sent_rows:
            try:
                when = datetime.fromisoformat(sent_row["sent_at"].replace("Z", "+00:00"))
                if when.astimezone(get_tz(tz_name)).date().isoformat() == today:
                    campaign_today += 1
            except (ValueError, TypeError):
                continue
        camp_pending = active_reservations_today(c, user_id, tz_name, local.date(), campaign["id"])
        camp_limit = min(int(campaign["daily_limit"]), limit)
        if campaign_today + int(camp_pending) >= camp_limit:
            c.execute("COMMIT")
            raise APIError(429, "This campaign's daily cap is reached. The global quota remains protected.", "campaign_quota_reached")
        if reservation:
            c.execute("UPDATE send_reservations SET campaign_id=?,draft_id=?,date=?,timezone=?,status='reserved',updated_at=? WHERE id=?",
                      (campaign["id"], draft_id, today, tz_name, iso_now(), reservation["id"]))
            reservation_id = reservation["id"]
        else:
            c.execute("INSERT INTO send_reservations(id,user_id,draft_id,campaign_id,date,timezone,idempotency_key,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (reservation_id, user_id, draft_id, campaign["id"], today, tz_name, idempotency_key, "reserved", iso_now(), iso_now()))
        c.execute("UPDATE email_drafts SET status='Sending',updated_at=? WHERE id=? AND user_id=?", (iso_now(), draft_id, user_id))
        c.execute("COMMIT")
        recipient = prospect["email"]
        subject = draft["subject"]
        body = draft["body"]
        sender_name = profile["sender_name"]
        reply_to = profile["reply_to"] or profile["sender_email"]
        c.close()
    except APIError:
        if c.in_transaction:
            c.execute("ROLLBACK")
        c.close()
        raise
    except Exception:
        if c.in_transaction:
            c.execute("ROLLBACK")
        c.close()
        raise

    # The DB reservation is committed before the external request. It counts against pending
    # capacity, but the successful-send counter changes only after a provider acceptance.
    try:
        if int(user["is_demo"]):
            provider_result = {"id": "demo-" + secrets.token_hex(6), "status": "simulated"}
            provider_label = "Demo simulator — not delivered"
        else:
            assert provider is not None
            result = provider.send_email(sender=sender_name, reply_to=reply_to, recipient=recipient,
                                        subject=subject, text=body, idempotency_key=idempotency_key)
            provider_result = result
            provider_label = "Resend accepted"
    except Exception as exc:
        fail = db_connect()
        try:
            fail.execute("BEGIN IMMEDIATE")
            acquire_transaction_lock(fail, "send-quota:" + user_id)
            fail.execute("UPDATE send_reservations SET status='released',updated_at=? WHERE id=?", (iso_now(), reservation_id))
            fail.execute("UPDATE email_drafts SET status='Failed',updated_at=? WHERE id=? AND user_id=? AND status='Sending'", (iso_now(), draft_id, user_id))
            fail.execute("INSERT INTO email_sends(id,user_id,prospect_id,campaign_id,draft_id,message_id,recipient,subject,sent_at,status,provider_status,error_message,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (secrets.token_hex(12), user_id, prospect["id"], campaign["id"], draft_id, "", recipient, subject,
                          iso_now(), "failed", "rejected", clean_text(str(exc), 240), idempotency_key))
            audit(fail, user_id, "email_failed", "The email provider rejected this message. No outreach quota was consumed.", prospect["id"], campaign["id"], {"draft_id": draft_id})
            fail.execute("COMMIT")
        except Exception:
            if fail.in_transaction:
                fail.execute("ROLLBACK")
        finally:
            fail.close()
        raise APIError(502, "The email provider rejected this message. No outreach quota was consumed.", "provider_rejected") from None

    finish = db_connect()
    try:
        finish.execute("BEGIN IMMEDIATE")
        acquire_transaction_lock(finish, "send-quota:" + user_id)
        # A successful send increments exactly once under the DB write lock.
        was_sent = finish.execute("SELECT id FROM email_sends WHERE user_id=? AND draft_id=? AND status='sent'", (user_id, draft_id)).fetchone()
        if was_sent:
            finish.execute("UPDATE send_reservations SET status='used',updated_at=? WHERE id=?", (iso_now(), reservation_id))
            finish.execute("COMMIT")
            return {"sent": True, "duplicate": True, "send_id": was_sent["id"], "message": "Already sent; no duplicate was created."}
        finish_local = local_now(tz_name)
        local_date = finish_local.date().isoformat()
        counter = finish.execute("SELECT count FROM daily_send_counters WHERE user_id=? AND date=? AND timezone=?", (user_id, local_date, tz_name)).fetchone()
        next_count = max(int(counter["count"]) if counter else 0,
                         successful_sends_today(finish, user_id, tz_name, finish_local.date())) + 1
        if next_count > MAX_DAILY_SENDS:
            raise APIError(500, "Quota reservation invariant failed after provider acceptance. Contact support before retrying.", "quota_invariant_failed")
        send_id = secrets.token_hex(12)
        sent_at = iso_now()
        finish.execute("INSERT INTO email_sends(id,user_id,prospect_id,campaign_id,draft_id,message_id,recipient,subject,sent_at,status,provider_status,error_message,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (send_id, user_id, prospect["id"], campaign["id"], draft_id, provider_result.get("id", ""), recipient,
                        subject, sent_at, "sent", provider_label, "", idempotency_key))
        finish.execute("INSERT INTO daily_send_counters(user_id,date,timezone,count,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,date,timezone) DO UPDATE SET count=MAX(daily_send_counters.count,excluded.count),updated_at=excluded.updated_at",
                       (user_id, local_date, tz_name, next_count, sent_at))
        finish.execute("UPDATE send_reservations SET status='used',updated_at=? WHERE id=?", (iso_now(), reservation_id))
        finish.execute("UPDATE email_drafts SET status='Sent',updated_at=? WHERE id=? AND user_id=?", (sent_at, draft_id, user_id))
        old_status = prospect["status"]
        finish.execute("UPDATE prospects SET status=CASE WHEN status='New' THEN 'Contacted' ELSE status END,last_contacted_at=?,next_follow_up_at=NULL,updated_at=? WHERE id=? AND user_id=?",
                       (sent_at, sent_at, prospect["id"], user_id))
        if draft["kind"] == "follow_up":
            finish.execute("UPDATE follow_ups SET status='sent',updated_at=? WHERE draft_id=? AND user_id=?", (sent_at, draft_id, user_id))
        else:
            delay = int(campaign["follow_up_delay_days"] or settings["follow_up_delay_days"] or 4)
            due = utc_now() + timedelta(days=delay)
            follow_id = compute_followup_draft(finish, user_id, prospect, campaign, send_id, subject, draft["service_focus"], due)
            audit(finish, user_id, "follow_up_scheduled", f"A follow-up draft was created for {due.astimezone(get_tz(tz_name)).strftime('%b %d')} and needs approval.", prospect["id"], campaign["id"], {"follow_up_id": follow_id, "draft_id": draft_id})
        audit(finish, user_id, "email_sent", ("Demo send simulated (not delivered)." if int(user["is_demo"]) else "Email accepted by provider."),
              prospect["id"], campaign["id"], {"draft_id": draft_id, "provider_status": provider_label, "send_id": send_id})
        finish.execute("COMMIT")
        return {"sent": True, "duplicate": False, "send_id": send_id, "sent_at": sent_at,
                "provider_status": provider_label, "quota_count": next_count}
    except Exception:
        if finish.in_transaction:
            finish.execute("ROLLBACK")
        raise APIError(500, "The provider accepted the email, but Kyro could not finalize its send record. Retrying is safe; the provider idempotency key prevents a duplicate.", "finalize_failed") from None
    finally:
        finish.close()


def serialize_prospect(row: sqlite3.Row) -> dict:
    result = {k: row[k] for k in row.keys()}
    result["social_urls"] = safe_json(result.get("social_urls"), [])
    result["tags"] = safe_json(result.get("tags"), [])
    return result


def get_user_for_api(c: sqlite3.Connection, user_id: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise APIError(401, "Please sign in again.", "unauthorized")
    return row


def settings_payload(c: sqlite3.Connection, user_id: str, user: sqlite3.Row) -> dict:
    p = c.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    s = c.execute("SELECT * FROM agency_settings WHERE user_id=?", (user_id,)).fetchone()
    if not p or not s:
        raise APIError(500, "Workspace settings could not be loaded.", "settings_missing")
    provider = provider_status({**dict(user), "sender_email": p["sender_email"]})
    suppressions = c.execute("SELECT id,email,reason,created_at FROM suppressions WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
    return {"profile": dict(p), "agency": {**dict(s), "services": safe_json(s["services"], SERVICES)},
            "provider": provider, "suppressions": [dict(x) for x in suppressions], "demo_mode": bool(user["is_demo"]),
            "hard_daily_limit": MAX_DAILY_SENDS}


def dashboard_payload(c: sqlite3.Connection, user_id: str) -> dict:
    p = c.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    s = c.execute("SELECT * FROM agency_settings WHERE user_id=?", (user_id,)).fetchone()
    tz_name = p["timezone"] if p else "Africa/Nairobi"
    today = local_now(tz_name).date().isoformat()
    counter = c.execute("SELECT count FROM daily_send_counters WHERE user_id=? AND date=? AND timezone=?", (user_id, today, tz_name)).fetchone()
    sent_today = max(int(counter["count"]) if counter else 0, successful_sends_today(c, user_id, tz_name, local_now(tz_name).date()))
    total = c.execute("SELECT COUNT(*) AS n FROM prospects WHERE user_id=?", (user_id,)).fetchone()["n"]
    replies = c.execute("SELECT COUNT(*) AS n FROM prospects WHERE user_id=? AND status IN ('Replied','Interested')", (user_id,)).fetchone()["n"]
    interested = c.execute("SELECT COUNT(*) AS n FROM prospects WHERE user_id=? AND status='Interested'", (user_id,)).fetchone()["n"]
    followups = c.execute("SELECT COUNT(*) AS n FROM follow_ups WHERE user_id=? AND status='scheduled' AND scheduled_for<=?", (user_id, iso_now())).fetchone()["n"]
    sent_total = c.execute("SELECT COUNT(*) AS n FROM email_sends WHERE user_id=? AND status='sent'", (user_id,)).fetchone()["n"]
    approved = c.execute("SELECT COUNT(*) AS n FROM email_drafts WHERE user_id=? AND status IN ('Approved','Scheduled','Sent')", (user_id,)).fetchone()["n"]
    queue_rows = c.execute("""SELECT d.id,d.subject,d.status,d.scheduled_for,d.approved_at,d.kind,p.business_name,p.contact_name,p.email,c.name AS campaign_name
                         FROM email_drafts d JOIN prospects p ON p.id=d.prospect_id AND p.user_id=d.user_id
                         LEFT JOIN campaigns c ON c.id=d.campaign_id AND c.user_id=d.user_id
                         WHERE d.user_id=? AND d.status='Scheduled' AND d.scheduled_for IS NOT NULL
                         ORDER BY d.scheduled_for LIMIT 30""", (user_id,)).fetchall()
    queue = []
    for q in queue_rows:
        scheduled = parse_datetime(q["scheduled_for"], tz_name)
        if scheduled and scheduled.astimezone(get_tz(tz_name)).date().isoformat() == today:
            queue.append(dict(q))
    queue = queue[:8]
    activity = c.execute("SELECT a.*,p.business_name FROM activity_log a LEFT JOIN prospects p ON p.id=a.prospect_id AND p.user_id=a.user_id WHERE a.user_id=? ORDER BY a.created_at DESC LIMIT 8", (user_id,)).fetchall()
    funnel = {"prospects": total, "approved": approved, "sent": sent_total,
              "replies": c.execute("SELECT COUNT(*) AS n FROM activity_log WHERE user_id=? AND type IN ('reply_recorded','reply_received')", (user_id,)).fetchone()["n"],
              "interested": interested}
    return {"display_name": p["display_name"] if p else "there", "timezone": tz_name,
            "sent_today": sent_today, "daily_limit": min(int(s["daily_limit"] if s else 10), MAX_DAILY_SENDS),
            "remaining": max(0, min(int(s["daily_limit"] if s else 10), MAX_DAILY_SENDS) - sent_today),
            "prospects": total, "replies": replies, "interested": interested, "followups_due": followups,
            "sent_total": sent_total, "approved_total": approved, "queue": [dict(x) for x in queue],
            "activity": [dict(x) for x in activity], "funnel": funnel, "source_label": "App recorded"}


def analytics_payload(c: sqlite3.Connection, user_id: str) -> dict:
    p = c.execute("SELECT timezone FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    tz_name = p["timezone"] if p else "Africa/Nairobi"
    today = local_now(tz_name).date()
    start = today - timedelta(days=29)
    send_rows = c.execute("SELECT s.sent_at,s.status,d.service_focus FROM email_sends s LEFT JOIN email_drafts d ON d.id=s.draft_id AND d.user_id=s.user_id WHERE s.user_id=? AND s.sent_at>=? ORDER BY s.sent_at", (user_id, iso(datetime.combine(start, datetime.min.time(), tzinfo=get_tz(tz_name)).astimezone(timezone.utc)))).fetchall()
    daily: dict[str, dict[str, int]] = {}
    service = {x: {"sent": 0, "replies": 0, "interested": 0} for x in SERVICES}
    for row in send_rows:
        try:
            date = datetime.fromisoformat(row["sent_at"].replace("Z", "+00:00")).astimezone(get_tz(tz_name)).date().isoformat()
        except (ValueError, TypeError):
            continue
        daily.setdefault(date, {"sent": 0, "failed": 0})
        if row["status"] == "sent":
            daily[date]["sent"] += 1
            if row["service_focus"] in service:
                service[row["service_focus"]]["sent"] += 1
        else:
            daily[date]["failed"] += 1
    totals = c.execute("SELECT COUNT(*) AS all_sends,SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent,SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed FROM email_sends WHERE user_id=?", (user_id,)).fetchone()
    replies = c.execute("SELECT COUNT(*) AS n FROM activity_log WHERE user_id=? AND type IN ('reply_recorded','reply_received')", (user_id,)).fetchone()["n"]
    interested = c.execute("SELECT COUNT(*) AS n FROM prospects WHERE user_id=? AND status='Interested'", (user_id,)).fetchone()["n"]
    followups = c.execute("SELECT COUNT(*) AS n FROM follow_ups WHERE user_id=?", (user_id,)).fetchone()["n"]
    suppressed = c.execute("SELECT COUNT(*) AS n FROM suppressions WHERE user_id=?", (user_id,)).fetchone()["n"]
    prospect_count = c.execute("SELECT COUNT(*) AS n FROM prospects WHERE user_id=?", (user_id,)).fetchone()["n"]
    # Reply and interest breakdowns by service are based on prospects associated to a sent draft.
    sr = c.execute("""SELECT d.service_focus,p.status,COUNT(*) AS n FROM email_sends s
                       JOIN email_drafts d ON d.id=s.draft_id AND d.user_id=s.user_id
                       JOIN prospects p ON p.id=s.prospect_id AND p.user_id=s.user_id
                       WHERE s.user_id=? AND s.status='sent' GROUP BY d.service_focus,p.status""", (user_id,)).fetchall()
    for row in sr:
        if row["service_focus"] in service and row["status"] in ("Replied", "Interested"):
            service[row["service_focus"]]["replies"] += int(row["n"])
        if row["service_focus"] in service and row["status"] == "Interested":
            service[row["service_focus"]]["interested"] += int(row["n"])
    return {"source_label": "App recorded", "period_days": 30,
            "total_prospects": prospect_count, "emails_sent": int(totals["sent"] or 0), "replies": int(replies),
            "positive_replies": int(interested), "interested": int(interested), "follow_ups": int(followups),
            "suppressed": int(suppressed), "failed_sends": int(totals["failed"] or 0),
            "reply_rate": round((int(replies) / int(totals["sent"]) * 100), 1) if totals["sent"] else 0,
            "interest_rate": round((int(interested) / int(totals["sent"]) * 100), 1) if totals["sent"] else 0,
            "daily": [{"date": (start + timedelta(days=i)).isoformat(), **daily.get((start + timedelta(days=i)).isoformat(), {"sent": 0, "failed": 0})} for i in range(30)],
            "service_performance": [{"service": k, **v} for k, v in service.items()]}


def import_preview(c: sqlite3.Connection, user_id: str, records: list) -> dict:
    valid, duplicates, invalid = [], [], []
    seen: set[str] = set()
    existing = {r["email"] for r in c.execute("SELECT email FROM prospects WHERE user_id=?", (user_id,)).fetchall()}
    for index, row in enumerate(records[:2000], start=1):
        try:
            if not isinstance(row, dict):
                raise APIError(400, "Row must be an object.")
            record = prospect_record(row)
            record["_row"] = index
            if record["email"] in existing or record["email"] in seen:
                duplicates.append({"row": index, "email": record["email"], "business_name": record["business_name"], "reason": "Email already exists in this workspace or upload."})
            else:
                valid.append(record)
                seen.add(record["email"])
        except APIError as exc:
            invalid.append({"row": index, "business_name": clean_text(row.get("business_name"), 160) if isinstance(row, dict) else "", "email": normalize_email(row.get("email")) if isinstance(row, dict) else "", "reason": exc.message})
    return {"valid": valid, "duplicates": duplicates, "invalid": invalid,
            "counts": {"valid": len(valid), "duplicates": len(duplicates), "invalid": len(invalid), "reviewed": min(len(records), 2000)}}


def create_prospect(c: sqlite3.Connection, user_id: str, data: dict) -> dict:
    record = prospect_record(data)
    timestamp = iso_now()
    pid = secrets.token_hex(12)
    try:
        inserted = c.execute("INSERT INTO prospects(id,user_id,business_name,contact_name,email,phone,website,social_urls,industry,location,notes,source,status,tags,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,email) DO NOTHING",
                             (pid, user_id, record["business_name"], record["contact_name"], record["email"], record["phone"], record["website"], record["social_urls"], record["industry"], record["location"], record["notes"], record["source"], record["status"], record["tags"], timestamp, timestamp))
    except sqlite3.IntegrityError:
        raise APIError(409, "A prospect with this normalized email already exists.", "duplicate_email") from None
    if inserted.rowcount == 0:
        raise APIError(409, "A prospect with this normalized email already exists.", "duplicate_email")
    audit(c, user_id, "prospect_created", f"{record['business_name']} added to prospects.", pid)
    return serialize_prospect(c.execute("SELECT * FROM prospects WHERE id=? AND user_id=?", (pid, user_id)).fetchone())


def cancel_followups(c: sqlite3.Connection, user_id: str, prospect_id: str) -> None:
    rows = c.execute("SELECT draft_id FROM follow_ups WHERE user_id=? AND prospect_id=? AND status IN ('scheduled','awaiting_approval')", (user_id, prospect_id)).fetchall()
    c.execute("UPDATE follow_ups SET status='cancelled',updated_at=? WHERE user_id=? AND prospect_id=? AND status IN ('scheduled','awaiting_approval')", (iso_now(), user_id, prospect_id))
    for row in rows:
        if row["draft_id"]:
            c.execute("UPDATE email_drafts SET status='Cancelled',scheduled_for=NULL,updated_at=? WHERE id=? AND user_id=? AND status IN ('Draft','Awaiting Approval','Approved','Scheduled')", (iso_now(), row["draft_id"], user_id))


def stop_pending_outreach(c: sqlite3.Connection, user_id: str, prospect_id: str) -> None:
    """Stop follow-ups and any other queued messages once a prospect is ineligible."""
    cancel_followups(c, user_id, prospect_id)
    c.execute("UPDATE email_drafts SET status='Cancelled',scheduled_for=NULL,updated_at=? WHERE user_id=? AND prospect_id=? AND status IN ('Approved','Scheduled')",
              (iso_now(), user_id, prospect_id))


class KyroHandler(BaseHTTPRequestHandler):
    server_version = "KyroClientOS/2.0"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        # Request logs intentionally omit query/body values to avoid leaking personal data.
        print(f"{self.address_string()} {self.command} {self.path.split('?')[0]} {args[1] if len(args)>1 else ''}")

    def _cookies(self) -> SimpleCookie:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            pass
        return cookie

    def _cookie_flags(self, http_only: bool) -> str:
        parts = ["Path=/", "SameSite=Lax", f"Max-Age={SESSION_DAYS * 86400}"]
        if http_only:
            parts.append("HttpOnly")
        if COOKIE_SECURE:
            parts.append("Secure")
        return "; ".join(parts)

    def _send_json(self, status: int, data: dict, set_cookies: list[str] | None = None) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self' data: blob:; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'")
        for val in set_cookies or []:
            self.send_header("Set-Cookie", val)
        self.end_headers()
        self.wfile.write(payload)

    def _set_session_cookies(self, raw: str, csrf: str) -> list[str]:
        secure = "; Secure" if COOKIE_SECURE else ""
        max_age = SESSION_DAYS * 86400
        return [f"kyro_session={raw}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}",
                f"kyro_csrf={csrf}; Path=/; SameSite=Lax; Max-Age={max_age}{secure}"]

    def _clear_cookies(self) -> list[str]:
        secure = "; Secure" if COOKIE_SECURE else ""
        return [f"kyro_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}",
                f"kyro_csrf=; Path=/; SameSite=Lax; Max-Age=0{secure}"]

    def _body(self) -> dict:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if size > 2_000_000:
            raise APIError(413, "This request is too large.", "body_too_large")
        if size <= 0:
            return {}
        raw = self.rfile.read(size)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise APIError(400, "Request data could not be read.", "invalid_json") from None
        if not isinstance(value, dict):
            raise APIError(400, "Request data must be an object.", "invalid_json")
        return value

    def _rate(self, key: str, limit: int, seconds: int) -> None:
        c = db_connect()
        now = time.time()
        try:
            c.execute("BEGIN IMMEDIATE")
            acquire_transaction_lock(c, "rate:" + key)
            row = c.execute("SELECT count,window_start FROM rate_limits WHERE key=?", (key,)).fetchone()
            if not row or now - float(row["window_start"]) > seconds:
                c.execute("INSERT INTO rate_limits(key,count,window_start) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET count=excluded.count,window_start=excluded.window_start", (key, 1, now))
            elif int(row["count"]) >= limit:
                raise APIError(429, "Too many attempts. Wait a moment and try again.", "rate_limited")
            else:
                c.execute("UPDATE rate_limits SET count=count+1 WHERE key=?", (key,))
            c.execute("COMMIT")
        except APIError:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def _current(self) -> tuple[sqlite3.Row, sqlite3.Row] | None:
        cookies = self._cookies()
        raw = cookies.get("kyro_session").value if cookies.get("kyro_session") else ""
        if not raw:
            return None
        c = db_connect()
        try:
            row = c.execute("SELECT s.*,u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",
                            (hashlib.sha256(raw.encode()).hexdigest(), iso_now())).fetchone()
            if not row:
                return None
            return row, row
        finally:
            c.close()

    def _require_csrf(self, session_row: sqlite3.Row) -> None:
        cookies = self._cookies()
        cookie_csrf = cookies.get("kyro_csrf").value if cookies.get("kyro_csrf") else ""
        header_csrf = self.headers.get("X-CSRF-Token", "")
        if not cookie_csrf or not header_csrf or not hmac.compare_digest(cookie_csrf, header_csrf) or not hmac.compare_digest(session_row["csrf_token"], header_csrf):
            raise APIError(403, "Your secure session expired. Refresh the page and try again.", "csrf_failed")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/healthz":
            self._send_json(200, {"ok": True, "service": "Kyro Outreach"})
            return
        if path == "/api/bootstrap":
            self._bootstrap()
            return
        if path.startswith("/api/"):
            self._api("GET", path, parse_qs(parsed.query), {})
            return
        if path == "/" or path == "/index.html":
            self._static(PUBLIC / "index.html")
            return
        self._static(PUBLIC / path.lstrip("/"))

    def do_POST(self) -> None:
        self._api_from_request("POST")

    def do_PUT(self) -> None:
        self._api_from_request("PUT")

    def do_PATCH(self) -> None:
        self._api_from_request("PATCH")

    def do_DELETE(self) -> None:
        self._api_from_request("DELETE")

    def _static(self, path: Path) -> None:
        try:
            if not path.resolve().is_relative_to(PUBLIC.resolve()) or not path.is_file():
                raise FileNotFoundError
            data = path.read_bytes()
        except (FileNotFoundError, PermissionError, OSError):
            self.send_error(404)
            return
        content_type = "text/html; charset=utf-8" if path.suffix == ".html" else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(data)

    def _bootstrap(self) -> None:
        c = db_connect()
        try:
            # Deployment-stage mode: bootstrap creates the demo session server-side.
            # This removes the fragile client-side auth round-trip while keeping the
            # real authentication routes available for the later production stage.
            current = self._current()
            if not current and DEMO_ENABLED:
                uid = ensure_demo_user()
                raw, csrf = create_session(c, uid)
                current = (c.execute("SELECT * FROM sessions WHERE token_hash=?", (hashlib.sha256(raw.encode()).hexdigest(),)).fetchone(),
                           c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
                set_cookie_headers = self._set_session_cookies(raw, csrf)
            else:
                set_cookie_headers = []

            real = c.execute("SELECT COUNT(*) AS n FROM users WHERE is_demo=0").fetchone()["n"]
            payload: dict[str, Any] = {"authenticated": False, "setup_required": real == 0,
                                       "demo_enabled": DEMO_ENABLED, "app_name": "Kyro Client Acquisition OS"}
            if current:
                session, user = current
                p = c.execute("SELECT * FROM profiles WHERE user_id=?", (user["id"],)).fetchone()
                settings = c.execute("SELECT * FROM agency_settings WHERE user_id=?", (user["id"],)).fetchone()
                payload.update({"authenticated": True, "csrf": session["csrf_token"],
                                "user": {"id": user["id"], "email": user["email"], "display_name": user["display_name"], "demo_mode": bool(user["is_demo"])},
                                "sender": dict(p) if p else {}, "agency": {**dict(settings), "services": safe_json(settings["services"], SERVICES)} if settings else {}})
            self._send_json(200, payload, set_cookie_headers)
        finally:
            c.close()

    def _api_from_request(self, method: str) -> None:
        parsed = urlparse(self.path)
        try:
            body = self._body()
            self._api(method, unquote(parsed.path), parse_qs(parsed.query), body)
        except APIError as exc:
            self._send_json(exc.status, {"error": exc.message, "code": exc.code})
        except Exception as exc:
            print(f"Internal error: {type(exc).__name__}")
            self._send_json(500, {"error": "Something went wrong. Your data was not changed.", "code": "internal_error"})

    def _api(self, method: str, path: str, query: dict, body: dict) -> None:
        try:
            if path == "/api/auth/setup" and method == "POST":
                self._rate("setup:" + self.client_address[0], 5, 300)
                self._setup(body)
                return
            if path == "/api/auth/login" and method == "POST":
                self._rate("login:" + self.client_address[0], 8, 300)
                self._login(body)
                return
            if path == "/api/auth/demo" and method == "POST":
                self._rate("demo:" + self.client_address[0], 30, 60)
                self._demo_login()
                return
            if path == "/api/cron/run" and method in ("GET", "POST"):
                self._cron()
                return
            if path == "/api/webhooks/reply" and method == "POST":
                self._reply_webhook(body)
                return
            current = self._current()
            if not current:
                raise APIError(401, "Sign in to access this workspace.", "unauthorized")
            session, user = current
            if method in ("POST", "PUT", "PATCH", "DELETE") and path != "/api/auth/logout":
                self._require_csrf(session)
                self._rate("mutation:" + user["id"], 200, 60)
            if path == "/api/auth/logout" and method == "POST":
                self._require_csrf(session)
                c = db_connect()
                try:
                    cookies = self._cookies()
                    raw = cookies.get("kyro_session").value if cookies.get("kyro_session") else ""
                    c.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(raw.encode()).hexdigest(),))
                finally:
                    c.close()
                self._send_json(200, {"ok": True}, self._clear_cookies())
                return
            self._route(method, path, query, body, user)
        except APIError as exc:
            self._send_json(exc.status, {"error": exc.message, "code": exc.code})
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "That record conflicts with existing workspace data.", "code": "conflict"})
        except Exception as exc:
            print(f"Internal error: {type(exc).__name__}")
            self._send_json(500, {"error": "Something went wrong. Your data was not changed.", "code": "internal_error"})

    def _setup(self, body: dict) -> None:
        display = clean_text(body.get("display_name"), 100)
        sender = clean_text(body.get("sender_name") or display, 100)
        email = normalize_email(body.get("email"))
        password = body.get("password", "")
        if not display or not valid_email(email) or not isinstance(password, str) or len(password) < 12 or len(password) > 200:
            raise APIError(400, "Enter your name, a valid email, and a password with at least 12 characters.", "validation")
        c = db_connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            acquire_transaction_lock(c, "owner-setup")
            if c.execute("SELECT 1 FROM users WHERE is_demo=0 LIMIT 1").fetchone():
                raise APIError(409, "An owner account already exists. Please sign in.", "setup_complete")
            uid = secrets.token_hex(16)
            c.execute("INSERT INTO users(id,workspace_id,email,password_hash,display_name,is_demo,created_at) VALUES(?,?,?,?,?,?,?)",
                      (uid, secrets.token_hex(16), email, password_hash(password), display, 0, iso_now()))
            create_profile_and_settings(c, uid, display, sender, email)
            raw, csrf = create_session(c, uid)
            audit(c, uid, "workspace_created", "Kyro workspace created.")
            c.execute("COMMIT")
        except APIError:
            if c.in_transaction:
                c.execute("ROLLBACK")
            c.close()
            raise
        except sqlite3.IntegrityError:
            if c.in_transaction:
                c.execute("ROLLBACK")
            c.close()
            raise APIError(409, "An account with this email already exists.", "account_exists") from None
        c.close()
        self._send_json(201, {"ok": True}, self._set_session_cookies(raw, csrf))

    def _login(self, body: dict) -> None:
        email = normalize_email(body.get("email"))
        password = body.get("password", "")
        c = db_connect()
        try:
            user = c.execute("SELECT * FROM users WHERE email=? AND is_demo=0", (email,)).fetchone()
            if not user or not isinstance(password, str) or not password_verify(password, user["password_hash"]):
                raise APIError(401, "Email or password is incorrect.", "login_failed")
            # Rotate sessions to avoid leaving old credentials active after sign-in.
            c.execute("DELETE FROM sessions WHERE expires_at<=?", (iso_now(),))
            raw, csrf = create_session(c, user["id"])
        finally:
            c.close()
        self._send_json(200, {"ok": True}, self._set_session_cookies(raw, csrf))

    def _demo_login(self) -> None:
        if not DEMO_ENABLED:
            raise APIError(404, "Demo mode is disabled.", "not_found")
        uid = ensure_demo_user()
        c = db_connect()
        try:
            raw, csrf = create_session(c, uid)
        finally:
            c.close()
        self._send_json(200, {"ok": True, "demo_mode": True}, self._set_session_cookies(raw, csrf))

    def _reply_webhook(self, body: dict) -> None:
        """Provider-neutral, bearer-authenticated reply callback.

        Adapters translate provider webhooks into {event_id, workspace_id,
        prospect_email, status, note}; raw provider payloads are not logged.
        """
        if not REPLY_WEBHOOK_SECRET or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + REPLY_WEBHOOK_SECRET):
            raise APIError(403, "Reply webhook authorization failed.", "forbidden")
        event_id = clean_text(body.get("event_id"), 180)
        workspace_id = clean_text(body.get("workspace_id"), 100)
        prospect_email = normalize_email(body.get("prospect_email") or body.get("email"))
        status = clean_text(body.get("status") or "Replied", 32)
        if not event_id or not workspace_id or not valid_email(prospect_email):
            raise APIError(400, "Reply event needs an event ID, workspace ID, and valid prospect email.", "validation")
        if status not in ("Replied", "Interested", "Not Interested", "Do Not Contact"):
            raise APIError(400, "Reply event has an unsupported prospect status.", "validation")
        c = db_connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            user = c.execute("SELECT * FROM users WHERE workspace_id=? AND is_demo=0", (workspace_id,)).fetchone()
            if not user:
                c.execute("ROLLBACK")
                self._send_json(202, {"ok": True, "matched": False})
                return
            duplicate = c.execute("SELECT 1 FROM provider_events WHERE user_id=? AND provider_event_id=?", (user["id"], event_id)).fetchone()
            if duplicate:
                c.execute("COMMIT")
                self._send_json(200, {"ok": True, "duplicate": True})
                return
            prospect = c.execute("SELECT * FROM prospects WHERE user_id=? AND email=?", (user["id"], prospect_email)).fetchone()
            if not prospect:
                c.execute("ROLLBACK")
                self._send_json(202, {"ok": True, "matched": False})
                return
            if status == "Do Not Contact":
                c.execute("INSERT INTO suppressions(id,user_id,email,reason,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,email) DO UPDATE SET reason=excluded.reason",
                          (secrets.token_hex(12), user["id"], prospect_email, "Do not contact requested in reply", iso_now()))
                status = "Suppressed"
            c.execute("UPDATE prospects SET status=?,responded_at=?,next_follow_up_at=NULL,updated_at=? WHERE id=? AND user_id=?",
                      (status, iso_now(), iso_now(), prospect["id"], user["id"]))
            stop_pending_outreach(c, user["id"], prospect["id"])
            note = clean_text(body.get("note"), 500)
            desc = f"Provider reply recorded for {prospect['business_name']} — status: {status}." + (f" Note: {note}" if note else "")
            audit(c, user["id"], "reply_received", desc, prospect["id"], metadata={"status": status, "provider_event_id": event_id})
            c.execute("INSERT INTO provider_events(id,user_id,provider_event_id,event_type,created_at) VALUES(?,?,?,?,?)",
                      (secrets.token_hex(12), user["id"], event_id, "reply", iso_now()))
            c.execute("COMMIT")
            self._send_json(200, {"ok": True, "matched": True, "status": status, "followups_stopped": True})
        except APIError:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        except Exception:
            if c.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def _cron(self) -> None:
        if not CRON_SECRET or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + CRON_SECRET):
            raise APIError(403, "Scheduled worker authorization failed.", "forbidden")
        c = db_connect()
        try:
            rows = c.execute("SELECT * FROM users WHERE is_demo=0").fetchall()
            user_ids = [r["id"] for r in rows]
        finally:
            c.close()
        result = {"processed": 0, "sent": 0, "skipped": 0, "errors": []}
        for uid in user_ids:
            c = db_connect()
            try:
                profile = c.execute("SELECT timezone FROM profiles WHERE user_id=?", (uid,)).fetchone()
                tz_name = profile["timezone"] if profile else "Africa/Nairobi"
                now = utc_now()
                stale_before = iso(now - timedelta(minutes=3))
                scheduled = c.execute("SELECT id FROM email_drafts WHERE user_id=? AND ((status='Scheduled' AND scheduled_for<=?) OR (status='Sending' AND updated_at<=?)) ORDER BY COALESCE(scheduled_for,updated_at) LIMIT 30", (uid, iso(now), stale_before)).fetchall()
                due_fups = c.execute("""SELECT d.id FROM follow_ups f JOIN email_drafts d ON d.id=f.draft_id AND d.user_id=f.user_id
                                          WHERE f.user_id=? AND f.status='scheduled' AND f.scheduled_for<=? AND (d.status='Approved' OR (d.status='Sending' AND d.updated_at<=?)) ORDER BY f.scheduled_for LIMIT 30""", (uid, iso(now), stale_before)).fetchall()
                draft_ids = list(dict.fromkeys([r["id"] for r in scheduled + due_fups]))
            finally:
                c.close()
            user_conn = db_connect()
            try:
                user = user_conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            finally:
                user_conn.close()
            for did in draft_ids:
                result["processed"] += 1
                try:
                    sent = send_draft(user, did, f"outreach:{did}")
                    result["sent"] += int(bool(sent.get("sent")))
                except APIError as exc:
                    if exc.code in ("outside_window", "quota_reached", "campaign_quota_reached", "not_due"):
                        result["skipped"] += 1
                    else:
                        result["errors"].append({"draft_id": did, "code": exc.code})
        self._send_json(200, result)

    def _route(self, method: str, path: str, query: dict, body: dict, user: sqlite3.Row) -> None:
        uid = user["id"]
        user_conn = db_connect()
        try:
            if method == "GET" and path == "/api/me":
                self._send_json(200, {"user": {"id": uid, "email": user["email"], "display_name": user["display_name"], "demo_mode": bool(user["is_demo"]), "workspace_id": user["workspace_id"]}})
                return
            if method == "GET" and path == "/api/dashboard":
                self._send_json(200, dashboard_payload(user_conn, uid))
                return
            if method == "GET" and path == "/api/analytics":
                self._send_json(200, analytics_payload(user_conn, uid))
                return
            if method == "GET" and path == "/api/settings":
                self._send_json(200, settings_payload(user_conn, uid, user))
                return
            if method == "PUT" and path == "/api/settings":
                self._save_settings(user_conn, uid, user, body)
                return
            if method == "POST" and path == "/api/settings/test-send":
                self._test_send(user_conn, uid, user)
                return
            if method == "GET" and path == "/api/prospects":
                self._list_prospects(user_conn, uid, query)
                return
            if method == "POST" and path == "/api/prospects":
                prospect = create_prospect(user_conn, uid, body)
                self._send_json(201, {"prospect": prospect})
                return
            if path == "/api/import/preview" and method == "POST":
                records = body.get("rows", [])
                if not isinstance(records, list):
                    raise APIError(400, "Upload rows could not be read.", "validation")
                result = import_preview(user_conn, uid, records)
                self._send_json(200, result)
                return
            if path == "/api/import/commit" and method == "POST":
                records = body.get("rows", [])
                if not isinstance(records, list) or len(records) > 2000:
                    raise APIError(400, "Import contains too many rows.", "validation")
                preview = import_preview(user_conn, uid, records)
                created = []
                user_conn.execute("BEGIN IMMEDIATE")
                try:
                    for record in preview["valid"]:
                        payload = {k: v for k, v in record.items() if not k.startswith("_")}
                        try:
                            created.append(create_prospect(user_conn, uid, payload))
                        except APIError as exc:
                            if exc.code == "duplicate_email":
                                preview["duplicates"].append({"row": record["_row"], "email": record["email"], "business_name": record["business_name"], "reason": "Email already exists."})
                            else:
                                raise
                    audit(user_conn, uid, "csv_imported", f"{len(created)} prospect(s) imported from CSV.", metadata={"count": len(created)})
                    user_conn.execute("COMMIT")
                except Exception:
                    if user_conn.in_transaction:
                        user_conn.execute("ROLLBACK")
                    raise
                self._send_json(201, {"created": len(created), "prospects": created, "duplicates": preview["duplicates"], "invalid": preview["invalid"]})
                return
            if path == "/api/campaigns" and method == "GET":
                self._list_campaigns(user_conn, uid)
                return
            if path == "/api/campaigns" and method == "POST":
                self._create_campaign(user_conn, uid, body)
                return
            if path == "/api/drafts/generate" and method == "POST":
                self._generate_draft(user_conn, uid, body)
                return
            if path == "/api/drafts" and method == "POST":
                self._save_draft(user_conn, uid, body)
                return
            if path == "/api/queue" and method == "GET":
                self._queue(user_conn, uid)
                return
            if path == "/api/suppressions" and method == "GET":
                rows = user_conn.execute("SELECT id,email,reason,created_at FROM suppressions WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
                self._send_json(200, {"items": [dict(r) for r in rows]})
                return
            if path == "/api/suppressions" and method == "POST":
                self._add_suppression(user_conn, uid, body)
                return
            # Resource-specific routes, with identifiers strictly scoped by user_id.
            bits = [unquote(x) for x in path.strip("/").split("/")]
            if len(bits) >= 3 and bits[1] == "prospects":
                pid = bits[2]
                if len(bits) == 3 and method == "GET":
                    self._prospect_detail(user_conn, uid, pid)
                    return
                if len(bits) == 3 and method == "PUT":
                    self._update_prospect(user_conn, uid, pid, body)
                    return
                if len(bits) == 3 and method == "DELETE":
                    if body.get("confirm") is not True:
                        raise APIError(400, "Confirm deletion before removing this prospect.", "confirmation_required")
                    user_conn.execute("DELETE FROM prospects WHERE id=? AND user_id=?", (pid, uid))
                    audit(user_conn, uid, "prospect_deleted", "Prospect permanently deleted.", pid)
                    self._send_json(200, {"ok": True})
                    return
                if len(bits) == 4 and bits[3] == "suppress" and method == "POST":
                    self._suppress_prospect(user_conn, uid, pid, body)
                    return
                if len(bits) == 4 and bits[3] == "status" and method == "POST":
                    self._set_prospect_status(user_conn, uid, pid, body)
                    return
                if len(bits) == 4 and bits[3] == "reply" and method == "POST":
                    self._record_reply(user_conn, uid, pid, body)
                    return
            if len(bits) >= 3 and bits[1] == "campaigns":
                cid = bits[2]
                if len(bits) == 3 and method == "GET":
                    row = user_conn.execute("SELECT * FROM campaigns WHERE id=? AND user_id=?", (cid, uid)).fetchone()
                    if not row:
                        raise APIError(404, "Campaign not found.", "not_found")
                    self._send_json(200, {"campaign": dict(row)})
                    return
                if len(bits) == 4 and bits[3] == "status" and method == "POST":
                    self._campaign_status(user_conn, uid, cid, body)
                    return
                if len(bits) == 3 and method == "PUT":
                    self._update_campaign(user_conn, uid, cid, body)
                    return
            if len(bits) >= 3 and bits[1] == "drafts":
                did = bits[2]
                if len(bits) == 3 and method == "PUT":
                    self._update_draft(user_conn, uid, did, body)
                    return
                if len(bits) == 4 and bits[3] == "approve" and method == "POST":
                    self._approve_draft(user_conn, uid, did)
                    return
                if len(bits) == 4 and bits[3] == "schedule" and method == "POST":
                    self._schedule_draft(user_conn, uid, did, body)
                    return
                if len(bits) == 4 and bits[3] == "send" and method == "POST":
                    self._send_now(uid, user, did, body)
                    return
                if len(bits) == 4 and bits[3] in ("pause", "cancel") and method == "POST":
                    self._pause_or_cancel_draft(user_conn, uid, did, bits[3], body)
                    return
            if len(bits) >= 3 and bits[1] == "suppressions" and len(bits) == 3 and method == "DELETE":
                self._remove_suppression(user_conn, uid, bits[2], body)
                return
            self._send_json(404, {"error": "This Kyro endpoint does not exist.", "code": "not_found"})
        finally:
            user_conn.close()

    def _list_prospects(self, c: sqlite3.Connection, uid: str, query: dict) -> None:
        term = clean_text(query.get("q", [""])[0], 160)
        status = clean_text(query.get("status", [""])[0], 32)
        sort = clean_text(query.get("sort", ["newest"])[0], 40)
        page = max(1, min(100000, int(query.get("page", ["1"])[0] or 1)))
        per = max(10, min(50, int(query.get("limit", ["20"])[0] or 20)))
        where = ["user_id=?"]
        params: list[Any] = [uid]
        if term:
            where.append("(business_name LIKE ? ESCAPE '\\' OR contact_name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' OR industry LIKE ? ESCAPE '\\' OR location LIKE ? ESCAPE '\\')")
            pat = "%" + term.replace("%", "\\%").replace("_", "\\_") + "%"
            params.extend([pat] * 5)
        if status and status != "All":
            if status == "Follow-up Due":
                where.append("next_follow_up_at IS NOT NULL AND next_follow_up_at<=?")
                params.append(iso_now())
            elif status == "Suppressed":
                where.append("(status='Suppressed' OR email IN (SELECT email FROM suppressions WHERE user_id=?))")
                params.append(uid)
            else:
                if status not in PROSPECT_STATUSES:
                    raise APIError(400, "Choose a valid filter.", "validation")
                where.append("status=?")
                params.append(status)
        order = {"newest": "created_at DESC", "oldest": "created_at ASC", "recent": "COALESCE(last_contacted_at,'') DESC,created_at DESC", "followup": "COALESCE(next_follow_up_at,'9999') ASC", "business": "business_name COLLATE NOCASE ASC", "status": "status ASC,business_name COLLATE NOCASE ASC"}.get(sort, "created_at DESC")
        clause = " AND ".join(where)
        total = c.execute(f"SELECT COUNT(*) AS n FROM prospects WHERE {clause}", params).fetchone()["n"]
        rows = c.execute(f"SELECT * FROM prospects WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?", params + [per, (page - 1) * per]).fetchall()
        self._send_json(200, {"items": [serialize_prospect(r) for r in rows], "page": page, "limit": per, "total": total, "pages": (total + per - 1) // per})

    def _prospect_detail(self, c: sqlite3.Connection, uid: str, pid: str) -> None:
        row = c.execute("SELECT * FROM prospects WHERE id=? AND user_id=?", (pid, uid)).fetchone()
        if not row:
            raise APIError(404, "Prospect not found.", "not_found")
        drafts = c.execute("SELECT id,campaign_id,subject,body,service_focus,status,kind,scheduled_for,approved_at,created_at,updated_at FROM email_drafts WHERE prospect_id=? AND user_id=? ORDER BY created_at DESC LIMIT 20", (pid, uid)).fetchall()
        sends = c.execute("SELECT id,campaign_id,draft_id,subject,sent_at,status,provider_status,error_message FROM email_sends WHERE prospect_id=? AND user_id=? ORDER BY sent_at DESC LIMIT 30", (pid, uid)).fetchall()
        activity = c.execute("SELECT * FROM activity_log WHERE prospect_id=? AND user_id=? ORDER BY created_at DESC LIMIT 30", (pid, uid)).fetchall()
        self._send_json(200, {"prospect": serialize_prospect(row), "drafts": [dict(x) for x in drafts], "sends": [dict(x) for x in sends], "timeline": [dict(x) for x in activity]})

    def _update_prospect(self, c: sqlite3.Connection, uid: str, pid: str, body: dict) -> None:
        old = c.execute("SELECT * FROM prospects WHERE id=? AND user_id=?", (pid, uid)).fetchone()
        if not old:
            raise APIError(404, "Prospect not found.", "not_found")
        data = {k: body.get(k, old[k]) for k in ("business_name", "contact_name", "email", "phone", "website", "social_urls", "industry", "location", "notes", "source", "status", "tags")}
        data["business_name"] = clean_text(data["business_name"], 160)
        data["email"] = normalize_email(data["email"])
        if not data["business_name"] or not valid_email(data["email"]):
            raise APIError(400, "Business name and a valid email address are required.", "validation")
        if data["status"] not in PROSPECT_STATUSES:
            raise APIError(400, "Choose a valid prospect status.", "validation")
        record = prospect_record(data)
        try:
            c.execute("UPDATE prospects SET business_name=?,contact_name=?,email=?,phone=?,website=?,social_urls=?,industry=?,location=?,notes=?,source=?,status=?,tags=?,updated_at=? WHERE id=? AND user_id=?",
                      (record["business_name"], record["contact_name"], record["email"], record["phone"], record["website"], record["social_urls"], record["industry"], record["location"], record["notes"], record["source"], record["status"], record["tags"], iso_now(), pid, uid))
        except sqlite3.IntegrityError:
            raise APIError(409, "A prospect with this normalized email already exists.", "duplicate_email") from None
        if data["status"] == "Suppressed":
            c.execute("INSERT INTO suppressions(id,user_id,email,reason,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,email) DO UPDATE SET reason=excluded.reason",
                      (secrets.token_hex(12), uid, record["email"], "Prospect marked suppressed", iso_now()))
        if data["status"] in ("Replied", "Interested", "Not Interested", "Suppressed"):
            stop_pending_outreach(c, uid, pid)
        if data["status"] in ("Replied", "Interested") and data["status"] != old["status"]:
            c.execute("UPDATE prospects SET responded_at=?,updated_at=? WHERE id=? AND user_id=?", (iso_now(), iso_now(), pid, uid))
            audit(c, uid, "reply_received", f"{record['business_name']} marked {data['status']}.", pid, metadata={"status": data["status"]})
        elif data["status"] == "Not Interested" and data["status"] != old["status"]:
            audit(c, uid, "prospect_not_interested", f"{record['business_name']} marked Not Interested; follow-ups stopped.", pid)
        audit(c, uid, "prospect_edited", f"{record['business_name']} updated.", pid)
        self._send_json(200, {"prospect": serialize_prospect(c.execute("SELECT * FROM prospects WHERE id=? AND user_id=?", (pid, uid)).fetchone())})

    def _suppress_prospect(self, c: sqlite3.Connection, uid: str, pid: str, body: dict) -> None:
        prospect = c.execute("SELECT * FROM prospects WHERE id=? AND user_id=?", (pid, uid)).fetchone()
        if not prospect:
            raise APIError(404, "Prospect not found.", "not_found")
        reason = clean_text(body.get("reason") or "Do not contact requested", 240)
        c.execute("INSERT INTO suppressions(id,user_id,email,reason,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,email) DO UPDATE SET reason=excluded.reason",
                  (secrets.token_hex(12), uid, prospect["email"], reason, iso_now()))
        c.execute("UPDATE prospects SET status='Suppressed',next_follow_up_at=NULL,updated_at=? WHERE id=? AND user_id=?", (iso_now(), pid, uid))
        stop_pending_outreach(c, uid, pid)
        audit(c, uid, "prospect_suppressed", f"{prospect['email']} added to suppression list.", pid, metadata={"reason": reason})
        self._send_json(200, {"ok": True})

    def _add_suppression(self, c: sqlite3.Connection, uid: str, body: dict) -> None:
        email = normalize_email(body.get("email"))
        if not valid_email(email):
            raise APIError(400, "Enter a valid email address.", "validation")
        reason = clean_text(body.get("reason") or "Do not contact requested", 240)
        c.execute("INSERT INTO suppressions(id,user_id,email,reason,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,email) DO UPDATE SET reason=excluded.reason",
                  (secrets.token_hex(12), uid, email, reason, iso_now()))
        row = c.execute("SELECT id FROM prospects WHERE user_id=? AND email=?", (uid, email)).fetchone()
        if row:
            c.execute("UPDATE prospects SET status='Suppressed',next_follow_up_at=NULL,updated_at=? WHERE id=? AND user_id=?", (iso_now(), row["id"], uid))
            stop_pending_outreach(c, uid, row["id"])
        audit(c, uid, "prospect_suppressed", f"{email} added to suppression list.", row["id"] if row else None, metadata={"reason": reason})
        self._send_json(201, {"ok": True})

    def _remove_suppression(self, c: sqlite3.Connection, uid: str, sid: str, body: dict) -> None:
        if body.get("confirm") is not True:
            raise APIError(400, "Confirm removal from the suppression list.", "confirmation_required")
        row = c.execute("SELECT * FROM suppressions WHERE id=? AND user_id=?", (sid, uid)).fetchone()
        if not row:
            raise APIError(404, "Suppression not found.", "not_found")
        c.execute("DELETE FROM suppressions WHERE id=? AND user_id=?", (sid, uid))
        c.execute("UPDATE prospects SET status='New',updated_at=? WHERE user_id=? AND email=? AND status='Suppressed'", (iso_now(), uid, row["email"]))
        audit(c, uid, "prospect_unsuppressed", f"{row['email']} removed from the suppression list.", metadata={"email": row["email"]})
        self._send_json(200, {"ok": True})

    def _set_prospect_status(self, c: sqlite3.Connection, uid: str, pid: str, body: dict) -> None:
        status = clean_text(body.get("status"), 32)
        if status not in PROSPECT_STATUSES:
            raise APIError(400, "Choose a valid status.", "validation")
        prospect = c.execute("SELECT * FROM prospects WHERE id=? AND user_id=?", (pid, uid)).fetchone()
        if not prospect:
            raise APIError(404, "Prospect not found.", "not_found")
        if status == "Suppressed":
            return self._suppress_prospect(c, uid, pid, {"reason": body.get("reason", "Do not contact requested")})
        if status in ("Replied", "Interested"):
            return self._record_reply(c, uid, pid, {"status": status, "note": body.get("note", "")})
        c.execute("UPDATE prospects SET status=?,updated_at=? WHERE id=? AND user_id=?", (status, iso_now(), pid, uid))
        if status == "Not Interested":
            stop_pending_outreach(c, uid, pid)
            audit(c, uid, "prospect_not_interested", f"{prospect['business_name']} marked Not Interested; follow-ups stopped.", pid)
        else:
            audit(c, uid, "prospect_status_changed", f"{prospect['business_name']} status changed to {status}.", pid)
        self._send_json(200, {"ok": True, "status": status})

    def _record_reply(self, c: sqlite3.Connection, uid: str, pid: str, body: dict) -> None:
        prospect = c.execute("SELECT * FROM prospects WHERE id=? AND user_id=?", (pid, uid)).fetchone()
        if not prospect:
            raise APIError(404, "Prospect not found.", "not_found")
        status = clean_text(body.get("status") or "Replied", 32)
        if status not in ("Replied", "Interested", "Not Interested", "Do Not Contact"):
            raise APIError(400, "Choose a valid reply status.", "validation")
        if status == "Do Not Contact":
            status = "Suppressed"
            c.execute("INSERT INTO suppressions(id,user_id,email,reason,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,email) DO UPDATE SET reason=excluded.reason",
                      (secrets.token_hex(12), uid, prospect["email"], "Do not contact requested", iso_now()))
        c.execute("UPDATE prospects SET status=?,responded_at=?,next_follow_up_at=NULL,updated_at=? WHERE id=? AND user_id=?", (status, iso_now(), iso_now(), pid, uid))
        stop_pending_outreach(c, uid, pid)
        note = clean_text(body.get("note"), 500)
        description = f"Reply recorded from {prospect['business_name']} — status: {status}." + (f" Note: {note}" if note else "")
        audit(c, uid, "reply_recorded", description, pid, metadata={"status": status})
        self._send_json(200, {"ok": True, "status": status})

    def _list_campaigns(self, c: sqlite3.Connection, uid: str) -> None:
        rows = c.execute("SELECT * FROM campaigns WHERE user_id=? ORDER BY updated_at DESC", (uid,)).fetchall()
        items = []
        for row in rows:
            cid = row["id"]
            prospects = c.execute("SELECT COUNT(*) AS n FROM campaign_prospects WHERE user_id=? AND campaign_id=?", (uid, cid)).fetchone()["n"]
            approved = c.execute("SELECT COUNT(*) AS n FROM email_drafts WHERE user_id=? AND campaign_id=? AND status IN ('Approved','Scheduled')", (uid, cid)).fetchone()["n"]
            sent = c.execute("SELECT COUNT(*) AS n FROM email_sends WHERE user_id=? AND campaign_id=? AND status='sent'", (uid, cid)).fetchone()["n"]
            replies = c.execute("SELECT COUNT(*) AS n FROM prospects p JOIN campaign_prospects cp ON cp.prospect_id=p.id AND cp.user_id=p.user_id WHERE cp.user_id=? AND cp.campaign_id=? AND p.status IN ('Replied','Interested')", (uid, cid)).fetchone()["n"]
            interested = c.execute("SELECT COUNT(*) AS n FROM prospects p JOIN campaign_prospects cp ON cp.prospect_id=p.id AND cp.user_id=p.user_id WHERE cp.user_id=? AND cp.campaign_id=? AND p.status='Interested'", (uid, cid)).fetchone()["n"]
            followups = c.execute("SELECT COUNT(*) AS n FROM follow_ups WHERE user_id=? AND campaign_id=? AND status='scheduled'", (uid, cid)).fetchone()["n"]
            items.append({**dict(row), "prospects": prospects, "approved": approved, "sent": sent, "replies": replies,
                          "interested": interested, "followups": followups, "remaining": max(0, prospects - sent)})
        self._send_json(200, {"items": items, "empty": len(items) == 0})

    def _create_campaign(self, c: sqlite3.Connection, uid: str, body: dict) -> None:
        name = clean_text(body.get("name"), 100)
        service = clean_text(body.get("service_focus"), 40)
        limit = body.get("daily_limit", 10)
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise APIError(400, "Campaign limit must be a number from 1 to 10.", "validation") from None
        if not name or service not in SERVICES or not 1 <= limit <= MAX_DAILY_SENDS:
            raise APIError(400, "Enter a campaign name, service focus, and a limit no higher than 10.", "validation")
        start = clean_text(body.get("sending_window_start") or "09:00", 5)
        end = clean_text(body.get("sending_window_end") or "17:00", 5)
        if not valid_time(start) or not valid_time(end) or start >= end:
            raise APIError(400, "Choose a valid sending window that ends after it starts.", "validation")
        settings = c.execute("SELECT * FROM agency_settings WHERE user_id=?", (uid,)).fetchone()
        delay = body.get("follow_up_delay_days", settings["follow_up_delay_days"] if settings else 4)
        try:
            delay = max(1, min(30, int(delay)))
        except (ValueError, TypeError):
            raise APIError(400, "Follow-up delay must be between 1 and 30 days.", "validation") from None
        selected = body.get("prospect_ids", [])
        if not isinstance(selected, list):
            selected = []
        selected = list(dict.fromkeys(str(x)[:100] for x in selected[:500]))
        if selected:
            marks = ",".join("?" for _ in selected)
            found = c.execute(f"SELECT id FROM prospects WHERE user_id=? AND id IN ({marks})", [uid] + selected).fetchall()
            if len(found) != len(selected):
                raise APIError(400, "One or more selected prospects are not in this workspace.", "authorization")
        cid = secrets.token_hex(12)
        timestamp = iso_now()
        c.execute("INSERT INTO campaigns(id,user_id,name,service_focus,status,daily_limit,sending_window_start,sending_window_end,follow_up_delay_days,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (cid, uid, name, service, "Draft", limit, start, end, delay, timestamp, timestamp))
        for pid in selected:
            c.execute("INSERT INTO campaign_prospects(user_id,campaign_id,prospect_id,status,created_at) VALUES(?,?,?,?,?)", (uid, cid, pid, "Selected", timestamp))
        audit(c, uid, "campaign_created", f"Campaign {name} created.", campaign_id=cid, metadata={"prospects": len(selected), "daily_limit": limit})
        self._send_json(201, {"campaign": dict(c.execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone())})

    def _campaign_status(self, c: sqlite3.Connection, uid: str, cid: str, body: dict) -> None:
        status = clean_text(body.get("status"), 20)
        if status not in CAMPAIGN_STATUSES:
            raise APIError(400, "Choose a valid campaign status.", "validation")
        campaign = c.execute("SELECT * FROM campaigns WHERE id=? AND user_id=?", (cid, uid)).fetchone()
        if not campaign:
            raise APIError(404, "Campaign not found.", "not_found")
        if status == "Completed" and body.get("confirm") is not True:
            raise APIError(400, "Confirm completing this campaign.", "confirmation_required")
        c.execute("UPDATE campaigns SET status=?,updated_at=? WHERE id=? AND user_id=?", (status, iso_now(), cid, uid))
        audit(c, uid, "campaign_activated" if status == "Active" else "campaign_paused" if status == "Paused" else "campaign_status_changed",
              f"Campaign {campaign['name']} set to {status}.", campaign_id=cid)
        self._send_json(200, {"ok": True, "status": status})

    def _update_campaign(self, c: sqlite3.Connection, uid: str, cid: str, body: dict) -> None:
        row = c.execute("SELECT * FROM campaigns WHERE id=? AND user_id=?", (cid, uid)).fetchone()
        if not row:
            raise APIError(404, "Campaign not found.", "not_found")
        name = clean_text(body.get("name", row["name"]), 100)
        service = clean_text(body.get("service_focus", row["service_focus"]), 40)
        limit = int(body.get("daily_limit", row["daily_limit"]))
        if not name or service not in SERVICES or limit < 1 or limit > MAX_DAILY_SENDS:
            raise APIError(400, "Campaign daily limit cannot exceed the global maximum of 10.", "validation")
        start = clean_text(body.get("sending_window_start", row["sending_window_start"]), 5)
        end = clean_text(body.get("sending_window_end", row["sending_window_end"]), 5)
        if not valid_time(start) or not valid_time(end) or start >= end:
            raise APIError(400, "Choose a valid sending window.", "validation")
        c.execute("UPDATE campaigns SET name=?,service_focus=?,daily_limit=?,sending_window_start=?,sending_window_end=?,updated_at=? WHERE id=? AND user_id=?",
                  (name, service, limit, start, end, iso_now(), cid, uid))
        audit(c, uid, "campaign_edited", f"Campaign {name} updated.", campaign_id=cid)
        self._send_json(200, {"ok": True})

    def _generate_draft(self, c: sqlite3.Connection, uid: str, body: dict) -> None:
        pid = clean_text(body.get("prospect_id"), 80)
        prospect = c.execute("SELECT * FROM prospects WHERE id=? AND user_id=?", (pid, uid)).fetchone()
        if not prospect:
            raise APIError(404, "Select a prospect in this workspace first.", "not_found")
        campaign_id = clean_text(body.get("campaign_id"), 80) or None
        campaign = c.execute("SELECT * FROM campaigns WHERE id=? AND user_id=?", (campaign_id, uid)).fetchone() if campaign_id else None
        if campaign_id and not campaign:
            raise APIError(404, "Campaign not found.", "not_found")
        if campaign:
            c.execute("INSERT INTO campaign_prospects(user_id,campaign_id,prospect_id,status,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,campaign_id,prospect_id) DO NOTHING",
                      (uid, campaign_id, pid, "Selected", iso_now()))
        service = clean_text(body.get("service_focus") or (campaign["service_focus"] if campaign else "Graphic Design"), 40)
        if service not in SERVICES:
            raise APIError(400, "Select one Kcreatives service.", "validation")
        tone = clean_text(body.get("tone") or "Professional", 30)
        if tone not in ("Professional", "Friendly", "Direct", "Minimal"):
            tone = "Professional"
        observation = clean_text(body.get("verified_observation"), 600)
        notes = clean_text(body.get("personalization_notes"), 1000)
        profile = c.execute("SELECT * FROM profiles WHERE user_id=?", (uid,)).fetchone()
        agency = c.execute("SELECT * FROM agency_settings WHERE user_id=?", (uid,)).fetchone()
        sender = profile["sender_name"] if profile else "Glen"
        agency_name = agency["agency_name"] if agency else "Kcreatives"
        signature = agency["tagline"] if agency else "Design. Strategy. Growth."
        name = prospect["contact_name"] or "there"
        business = prospect["business_name"]
        # Grounded, deterministic generation: only verified, user-entered details are interpolated.
        observation_block = ("\n\n" + observation) if observation else ""
        if tone == "Friendly":
            opening = f"I’m {sender} from {agency_name}. We help small businesses with {service.lower()}, and I wanted to ask whether it’s something {business} is exploring right now."
            cta = f"Would you be open to a short chat next week? I can also send a few starting ideas for {business}."
        elif tone == "Direct":
            opening = f"I’m {sender} at {agency_name}. We provide {service.lower()} for businesses, and I’m reaching out to see if {business} has a current need in this area."
            cta = "Would a brief conversation next week be useful?"
        elif tone == "Minimal":
            opening = f"I’m {sender} from {agency_name}. We work on {service.lower()} with businesses like {business}."
            cta = "Would a short conversation next week be useful?"
        else:
            opening = f"I’m {sender} from {agency_name}. We help small businesses with {service.lower()}, and I’m reaching out to ask whether it is a current priority for {business}."
            cta = f"Would you be open to a brief conversation next week? I can share a few options for {business}."
        body_text = (f"Hi {name},\n\n{opening}{observation_block}\n\n"
                     f"Our approach is to shape the work around a clear goal and a practical next step, rather than assume what a business needs. "
                     f"If this is relevant, I can share a few starting points for {service.lower()} based on the information you have provided.\n\n"
                     f"{cta}\n\nBest,\n{sender}\n{agency_name}\n{signature}")
        subject = f"A quick idea for {business}"
        draft_id = secrets.token_hex(12)
        timestamp = iso_now()
        c.execute("INSERT INTO email_drafts(id,user_id,prospect_id,campaign_id,subject,body,personalization_notes,service_focus,status,kind,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (draft_id, uid, pid, campaign_id, subject, body_text, notes, service, "Draft", "initial", timestamp, timestamp))
        audit(c, uid, "draft_generated", f"Grounded {service} draft created for {business}; review required.", pid, campaign_id,
              {"method": "rules_based", "verified_observation_provided": bool(observation), "tone": tone})
        self._send_json(201, {"draft": dict(c.execute("SELECT * FROM email_drafts WHERE id=?", (draft_id,)).fetchone()),
                              "generation": {"mode": "grounded_template", "ai_connected": False, "notice": "This draft uses only the prospect record and your verified notes. Review and approve before scheduling."}})

    def _save_draft(self, c: sqlite3.Connection, uid: str, body: dict) -> None:
        pid = clean_text(body.get("prospect_id"), 80)
        prospect = c.execute("SELECT id FROM prospects WHERE id=? AND user_id=?", (pid, uid)).fetchone()
        if not prospect:
            raise APIError(404, "Select a valid prospect.", "not_found")
        subject = clean_text(body.get("subject"), 240)
        email_body = clean_text(body.get("body"), 10000)
        service = clean_text(body.get("service_focus") or "Graphic Design", 40)
        if not subject or not email_body or service not in SERVICES:
            raise APIError(400, "Subject, message, and one Kcreatives service are required.", "validation")
        cid = clean_text(body.get("campaign_id"), 80) or None
        if cid and not c.execute("SELECT 1 FROM campaigns WHERE id=? AND user_id=?", (cid, uid)).fetchone():
            raise APIError(404, "Campaign not found.", "not_found")
        if cid:
            c.execute("INSERT INTO campaign_prospects(user_id,campaign_id,prospect_id,status,created_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,campaign_id,prospect_id) DO NOTHING",
                      (uid, cid, pid, "Selected", iso_now()))
        did = clean_text(body.get("id"), 80)
        timestamp = iso_now()
        if did:
            row = c.execute("SELECT * FROM email_drafts WHERE id=? AND user_id=?", (did, uid)).fetchone()
            if not row:
                raise APIError(404, "Draft not found.", "not_found")
            if row["status"] in ("Sent", "Sending"):
                raise APIError(409, "A send in progress or a sent email cannot be edited.", "draft_locked")
            c.execute("UPDATE email_drafts SET prospect_id=?,campaign_id=?,subject=?,body=?,personalization_notes=?,service_focus=?,status='Draft',approved_at=NULL,scheduled_for=NULL,updated_at=? WHERE id=? AND user_id=?",
                      (pid, cid, subject, email_body, clean_text(body.get("personalization_notes"), 1000), service, timestamp, did, uid))
            if row["kind"] == "follow_up":
                c.execute("UPDATE follow_ups SET status='awaiting_approval',updated_at=? WHERE draft_id=? AND user_id=? AND status='scheduled'", (timestamp, did, uid))
        else:
            did = secrets.token_hex(12)
            c.execute("INSERT INTO email_drafts(id,user_id,prospect_id,campaign_id,subject,body,personalization_notes,service_focus,status,kind,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (did, uid, pid, cid, subject, email_body, clean_text(body.get("personalization_notes"), 1000), service, "Draft", "initial", timestamp, timestamp))
        audit(c, uid, "draft_saved", f"Draft saved for {c.execute('SELECT business_name FROM prospects WHERE id=?', (pid,)).fetchone()[0]}.", pid, cid)
        self._send_json(200, {"draft": dict(c.execute("SELECT * FROM email_drafts WHERE id=? AND user_id=?", (did, uid)).fetchone())})

    def _update_draft(self, c: sqlite3.Connection, uid: str, did: str, body: dict) -> None:
        merged = dict(body)
        merged["id"] = did
        self._save_draft(c, uid, merged)

    def _approve_draft(self, c: sqlite3.Connection, uid: str, did: str) -> None:
        row = c.execute("SELECT * FROM email_drafts WHERE id=? AND user_id=?", (did, uid)).fetchone()
        if not row:
            raise APIError(404, "Draft not found.", "not_found")
        if row["status"] in ("Sent", "Sending", "Cancelled"):
            raise APIError(409, "This email cannot be approved in its current state.", "invalid_state")
        if not row["subject"].strip() or not row["body"].strip():
            raise APIError(400, "Add a subject and message before approval.", "empty_draft")
        timestamp = iso_now()
        c.execute("UPDATE email_drafts SET status='Approved',approved_at=?,updated_at=? WHERE id=? AND user_id=?", (timestamp, timestamp, did, uid))
        if row["kind"] == "follow_up":
            c.execute("UPDATE follow_ups SET status='scheduled',updated_at=? WHERE draft_id=? AND user_id=? AND status IN ('scheduled','awaiting_approval')", (timestamp, did, uid))
        audit(c, uid, "draft_approved", "Outreach email explicitly approved.", row["prospect_id"], row["campaign_id"], {"draft_id": did})
        self._send_json(200, {"ok": True, "status": "Approved"})

    def _schedule_draft(self, c: sqlite3.Connection, uid: str, did: str, body: dict) -> None:
        row = c.execute("SELECT * FROM email_drafts WHERE id=? AND user_id=?", (did, uid)).fetchone()
        if not row:
            raise APIError(404, "Draft not found.", "not_found")
        if row["status"] not in ("Approved", "Scheduled") or not row["approved_at"]:
            raise APIError(409, "Approve this email before scheduling it.", "approval_required")
        if not row["campaign_id"]:
            raise APIError(409, "Choose a campaign before scheduling.", "campaign_required")
        campaign = c.execute("SELECT * FROM campaigns WHERE id=? AND user_id=?", (row["campaign_id"], uid)).fetchone()
        if not campaign or campaign["status"] != "Active":
            raise APIError(409, "Activate the campaign before scheduling an email.", "campaign_inactive")
        if not c.execute("SELECT 1 FROM campaign_prospects WHERE user_id=? AND campaign_id=? AND prospect_id=?", (uid, campaign["id"], row["prospect_id"])).fetchone():
            raise APIError(409, "Add this prospect to the campaign before scheduling.", "campaign_membership_required")
        profile = c.execute("SELECT timezone FROM profiles WHERE user_id=?", (uid,)).fetchone()
        tz_name = profile["timezone"] if profile else "Africa/Nairobi"
        when = parse_datetime(body.get("scheduled_for"), tz_name)
        if not when or when <= utc_now():
            raise APIError(400, "Choose a future scheduled time.", "validation")
        settings = c.execute("SELECT * FROM agency_settings WHERE user_id=?", (uid,)).fetchone()
        start, end, _ = provision_campaign_send_window(c, uid, row["campaign_id"], settings)
        local = when.astimezone(get_tz(tz_name))
        if not (start <= local.strftime("%H:%M") < end):
            raise APIError(400, f"Choose a time inside the sending window ({start}–{end} {tz_name}).", "outside_window")
        if row["kind"] == "follow_up":
            fup = c.execute("SELECT * FROM follow_ups WHERE draft_id=? AND user_id=?", (did, uid)).fetchone()
            if fup and fup["status"] == "cancelled":
                raise APIError(409, "This follow-up has been stopped.", "followup_stopped")
            if fup:
                c.execute("UPDATE follow_ups SET scheduled_for=?,status='scheduled',updated_at=? WHERE id=? AND user_id=?", (iso(when), iso_now(), fup["id"], uid))
        c.execute("UPDATE email_drafts SET status='Scheduled',scheduled_for=?,updated_at=? WHERE id=? AND user_id=?", (iso(when), iso_now(), did, uid))
        audit(c, uid, "email_scheduled", f"Email scheduled for {local.strftime('%b %d, %H:%M')}.", row["prospect_id"], row["campaign_id"], {"draft_id": did, "scheduled_for": iso(when)})
        self._send_json(200, {"ok": True, "scheduled_for": iso(when)})

    def _send_now(self, uid: str, user: sqlite3.Row, did: str, body: dict) -> None:
        self._rate("send:" + uid, 12, 60)
        c = db_connect()
        try:
            draft = c.execute("SELECT status FROM email_drafts WHERE id=? AND user_id=?", (did, uid)).fetchone()
            if not draft:
                raise APIError(404, "Draft not found.", "not_found")
            if draft["status"] != "Scheduled" and body.get("confirm") is not True:
                raise APIError(400, "Confirm Send Now. The message must still be approved and pass every safeguard.", "confirmation_required")
        finally:
            c.close()
        result = send_draft(user, did, f"outreach:{did}")
        self._send_json(200, result)

    def _pause_or_cancel_draft(self, c: sqlite3.Connection, uid: str, did: str, action: str, body: dict) -> None:
        row = c.execute("SELECT * FROM email_drafts WHERE id=? AND user_id=?", (did, uid)).fetchone()
        if not row:
            raise APIError(404, "Queue item not found.", "not_found")
        if body.get("confirm") is not True:
            raise APIError(400, "Confirm this queue change.", "confirmation_required")
        if row["status"] in ("Sent", "Sending"):
            raise APIError(409, "A sent or in-progress email cannot be changed.", "invalid_state")
        status = "Paused" if action == "pause" else "Cancelled"
        c.execute("UPDATE email_drafts SET status=?,scheduled_for=NULL,updated_at=? WHERE id=? AND user_id=?", (status, iso_now(), did, uid))
        if row["kind"] == "follow_up":
            c.execute("UPDATE follow_ups SET status=?,updated_at=? WHERE draft_id=? AND user_id=? AND status='scheduled'", ("paused" if action == "pause" else "cancelled", iso_now(), did, uid))
        audit(c, uid, "email_paused" if action == "pause" else "email_cancelled", f"Scheduled email {action}d.", row["prospect_id"], row["campaign_id"], {"draft_id": did})
        self._send_json(200, {"ok": True, "status": status})

    def _queue(self, c: sqlite3.Connection, uid: str) -> None:
        profile = c.execute("SELECT timezone FROM profiles WHERE user_id=?", (uid,)).fetchone()
        tz_name = profile["timezone"] if profile else "Africa/Nairobi"
        today = local_now(tz_name).date().isoformat()
        drafts = c.execute("""SELECT d.*,p.business_name,p.contact_name,p.email,c.name AS campaign_name,c.status AS campaign_status
                              FROM email_drafts d JOIN prospects p ON p.id=d.prospect_id AND p.user_id=d.user_id
                              LEFT JOIN campaigns c ON c.id=d.campaign_id AND c.user_id=d.user_id
                              WHERE d.user_id=? AND d.status IN ('Scheduled','Approved','Failed','Sending')
                              ORDER BY CASE WHEN d.scheduled_for IS NULL THEN 1 ELSE 0 END,d.scheduled_for,d.created_at DESC""", (uid,)).fetchall()
        items = []
        for row in drafts:
            local_date = ""
            if row["scheduled_for"]:
                dt = parse_datetime(row["scheduled_for"], tz_name)
                if dt:
                    local_date = dt.astimezone(get_tz(tz_name)).date().isoformat()
            if row["status"] in ("Scheduled", "Failed", "Approved", "Sending"): 
                items.append({**dict(row), "item_type": "email", "local_date": local_date})
        followups = c.execute("""SELECT f.id AS follow_up_id,f.scheduled_for AS follow_up_for,f.status AS follow_up_status,d.*,
                                  p.business_name,p.contact_name,p.email,c.name AS campaign_name,c.status AS campaign_status
                                  FROM follow_ups f JOIN email_drafts d ON d.id=f.draft_id AND d.user_id=f.user_id
                                  JOIN prospects p ON p.id=f.prospect_id AND p.user_id=f.user_id
                                  LEFT JOIN campaigns c ON c.id=f.campaign_id AND c.user_id=f.user_id
                                  WHERE f.user_id=? AND f.status='scheduled' ORDER BY f.scheduled_for LIMIT 50""", (uid,)).fetchall()
        for row in followups:
            due = parse_datetime(row["follow_up_for"], tz_name)
            local_date = due.astimezone(get_tz(tz_name)).date().isoformat() if due else ""
            items.append({**dict(row), "scheduled_for": row["follow_up_for"], "local_date": local_date,
                          "item_type": "follow_up", "status": row["status"]})
        items.sort(key=lambda x: (x.get("scheduled_for") is None, x.get("scheduled_for") or x.get("follow_up_for") or "9999", x.get("created_at", "")))
        deduped = []
        seen_drafts = set()
        for item in items:
            if item.get("id") in seen_drafts:
                continue
            seen_drafts.add(item.get("id"))
            deduped.append(item)
        items = deduped
        today_items = [x for x in items if x.get("local_date") == today]
        counter = c.execute("SELECT count FROM daily_send_counters WHERE user_id=? AND date=? AND timezone=?", (uid, today, tz_name)).fetchone()
        sent = max(int(counter["count"]) if counter else 0, successful_sends_today(c, uid, tz_name, local_now(tz_name).date()))
        self._send_json(200, {"items": items[:100], "today": today_items, "today_date": today, "sent_today": sent,
                              "daily_limit": MAX_DAILY_SENDS, "remaining": max(0, MAX_DAILY_SENDS - sent), "timezone": tz_name})

    def _save_settings(self, c: sqlite3.Connection, uid: str, user: sqlite3.Row, body: dict) -> None:
        p = c.execute("SELECT * FROM profiles WHERE user_id=?", (uid,)).fetchone()
        s = c.execute("SELECT * FROM agency_settings WHERE user_id=?", (uid,)).fetchone()
        if not p or not s:
            raise APIError(500, "Workspace settings could not be loaded.", "settings_missing")
        if "daily_limit" in body:
            try:
                requested_limit = int(body.get("daily_limit") or MAX_DAILY_SENDS)
            except (ValueError, TypeError):
                raise APIError(400, "Daily limit must be 10; the global ceiling is protected.", "limit_protected") from None
            if requested_limit != MAX_DAILY_SENDS:
                raise APIError(403, "The global outreach ceiling is fixed at 10 per calendar day and cannot be raised here.", "limit_protected")
        sender_name = clean_text(body.get("sender_name", p["sender_name"]), 100)
        sender_email = normalize_email(body.get("sender_email", p["sender_email"]))
        reply_to = normalize_email(body.get("reply_to", p["reply_to"]))
        tz_name = clean_text(body.get("timezone", p["timezone"]), 80)
        try:
            ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            raise APIError(400, "Select a recognized timezone.", "validation") from None
        start = clean_text(body.get("sending_window_start", s["sending_window_start"]), 5)
        end = clean_text(body.get("sending_window_end", s["sending_window_end"]), 5)
        if not valid_email(sender_email) or (reply_to and not valid_email(reply_to)):
            raise APIError(400, "Enter a valid sender and reply-to email address.", "validation")
        if not sender_name or not valid_time(start) or not valid_time(end) or start >= end:
            raise APIError(400, "Sender name and a valid, same-day sending window are required.", "validation")
        agency_name = clean_text(body.get("agency_name", s["agency_name"]), 100)
        tagline = clean_text(body.get("tagline", s["tagline"]), 160)
        description = clean_text(body.get("description", s["description"]), 1000)
        delay = body.get("follow_up_delay_days", s["follow_up_delay_days"])
        try:
            delay = int(delay)
        except (ValueError, TypeError):
            raise APIError(400, "Follow-up delay must be a whole number.", "validation") from None
        if not 1 <= delay <= 30:
            raise APIError(400, "Follow-up delay must be between 1 and 30 days.", "validation")
        test_recipient = normalize_email(body.get("test_recipient", s["test_recipient"]))
        if test_recipient and not valid_email(test_recipient):
            raise APIError(400, "Enter a valid test recipient email.", "validation")
        c.execute("UPDATE profiles SET sender_name=?,sender_email=?,reply_to=?,timezone=? WHERE user_id=?",
                  (sender_name, sender_email, reply_to, tz_name, uid))
        c.execute("UPDATE agency_settings SET agency_name=?,tagline=?,description=?,sending_window_start=?,sending_window_end=?,follow_up_delay_days=?,test_recipient=?,updated_at=? WHERE user_id=?",
                  (agency_name, tagline, description, start, end, delay, test_recipient, iso_now(), uid))
        audit(c, uid, "settings_updated", "Workspace sending and sender settings updated.")
        self._send_json(200, settings_payload(c, uid, user))

    def _test_send(self, c: sqlite3.Connection, uid: str, user: sqlite3.Row) -> None:
        if int(user["is_demo"]):
            raise APIError(409, "Test email is disabled in DEMO MODE. Demo sends are simulated and never delivered.", "demo_send_blocked")
        profile = c.execute("SELECT * FROM profiles WHERE user_id=?", (uid,)).fetchone()
        agency = c.execute("SELECT * FROM agency_settings WHERE user_id=?", (uid,)).fetchone()
        test_email = agency["test_recipient"] if agency else ""
        provider = make_provider()
        if not test_email or not valid_email(test_email):
            raise APIError(400, "Set a test recipient in Settings first.", "test_recipient_required")
        if not provider:
            raise APIError(503, "Email provider not connected. No test email was sent.", "provider_not_configured")
        try:
            result = provider.send_email(sender=profile["sender_name"], reply_to=profile["reply_to"], recipient=test_email,
                                         subject="[KYRO TEST] Provider connection check",
                                         text="This is a Kyro Outreach test email. It is not outreach and does not count toward the daily quota.",
                                         idempotency_key="kyro-test:" + secrets.token_urlsafe(18))
        except Exception:
            audit(c, uid, "test_email_failed", "Provider test email failed; quota was not affected.")
            raise APIError(502, "The email provider rejected this test message. The outreach quota was not affected.", "provider_rejected") from None
        audit(c, uid, "test_email_sent", "A provider test email was sent to the configured test recipient.", metadata={"message_id": result.get("id", "")})
        self._send_json(200, {"ok": True, "message": "Test email sent. It did not count toward outreach quota."})


def main() -> None:
    init_db()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), KyroHandler)
    server.daemon_threads = True
    print(f"Kyro Outreach listening on http://{host}:{port} (demo={'on' if DEMO_ENABLED else 'off'})")
    server.serve_forever()


if __name__ == "__main__":
    main()
