#!/usr/bin/env python3
"""Tiny server for the date page: serves Index.html and saves answers to SQLite.

Run:   python3 server.py                  (http://localhost:8000)
       python3 server.py --host 0.0.0.0   (reachable from other devices on your Wi-Fi)

See answers at /admin?key=<your key> (the key is printed when the server starts).
"""
import argparse
import html
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "date.db"
PAGE_PATH = ROOT / "Index.html"
KEY_PATH = ROOT / ".admin_key"

MAX_BODY = 8 * 1024
LIMITS = {"date": 10, "time": 5, "venue": 60, "location": 140, "note": 600}


def get_admin_key():
    if os.environ.get("ADMIN_KEY"):
        return os.environ["ADMIN_KEY"]
    if KEY_PATH.exists():
        return KEY_PATH.read_text().strip()
    key = secrets.token_urlsafe(12)
    KEY_PATH.write_text(key)
    return key


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS responses (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT NOT NULL,
                time         TEXT NOT NULL,
                venue        TEXT NOT NULL,
                location     TEXT,
                note         TEXT,
                no_attempts  INTEGER DEFAULT 0,
                submitted_at TEXT NOT NULL
            )
            """
        )


def clean(payload):
    """Validate an answer from the page; returns a row dict or raises ValueError."""
    row = {}
    for field, limit in LIMITS.items():
        value = payload.get(field) or ""
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        row[field] = value.strip()[:limit]
    for required in ("date", "time", "venue"):
        if not row[required]:
            raise ValueError(f"{required} is required")
    try:
        datetime.strptime(row["date"], "%Y-%m-%d")
        datetime.strptime(row["time"], "%H:%M")
    except ValueError:
        raise ValueError("date or time is in the wrong format")
    try:
        row["no_attempts"] = max(0, min(int(payload.get("noAttempts") or 0), 10000))
    except (TypeError, ValueError):
        row["no_attempts"] = 0
    row["submitted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return row


def fetch_all():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM responses ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def admin_page(rows):
    def cell(v):
        return html.escape("" if v is None else str(v))

    body = "".join(
        f"<tr><td>{cell(r['id'])}</td><td>{cell(r['date'])}</td><td>{cell(r['time'])}</td>"
        f"<td>{cell(r['venue'])}</td><td>{cell(r['location'])}</td><td>{cell(r['note'])}</td>"
        f"<td>{cell(r['no_attempts'])}</td><td>{cell(r['submitted_at'])}</td></tr>"
        for r in rows
    ) or '<tr><td colspan="8" class="empty">No answers yet.</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Her Answers</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #fff0f4; color: #4a2c3a; margin: 0; padding: 32px 16px; }}
  h1 {{ color: #e0315d; margin: 0 0 16px; }}
  .wrap {{ overflow-x: auto; background: #fff; border-radius: 16px; box-shadow: 0 10px 30px -10px rgba(224,49,93,.3); }}
  table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
  th, td {{ text-align: left; padding: 10px 14px; border-bottom: 1px solid #ffd6e0; vertical-align: top; }}
  th {{ background: #ffe3ec; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
  .empty {{ text-align: center; color: #9b7d8a; padding: 24px; }}
</style></head><body>
<h1>Her answers ({len(rows)})</h1>
<div class="wrap"><table>
<tr><th>#</th><th>Date</th><th>Time</th><th>Kind of date</th><th>Location</th><th>Note</th><th>Tried “No”</th><th>Sent (UTC)</th></tr>
{body}
</table></div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    admin_key = ""

    def send(self, status, body, content_type="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def is_admin(self, query):
        given = parse_qs(query).get("key", [""])[0]
        return secrets.compare_digest(given, self.admin_key)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html", "/Index.html"):
            self.send(200, PAGE_PATH.read_bytes(), "text/html")
        elif url.path == "/admin":
            if not self.is_admin(url.query):
                self.send(403, "Wrong or missing key.", "text/plain")
                return
            self.send(200, admin_page(fetch_all()), "text/html")
        elif url.path == "/api/responses":
            if not self.is_admin(url.query):
                self.send(403, json.dumps({"error": "forbidden"}))
                return
            self.send(200, json.dumps(fetch_all(), indent=2))
        else:
            self.send(404, "Not found", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/api/responses":
            self.send(404, json.dumps({"error": "not found"}))
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self.send(400, json.dumps({"error": "bad request size"}))
            return
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("expected a JSON object")
            row = clean(payload)
        except (ValueError, json.JSONDecodeError) as e:
            self.send(400, json.dumps({"error": str(e)}))
            return

        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute(
                "INSERT INTO responses (date, time, venue, location, note, no_attempts, submitted_at) "
                "VALUES (:date, :time, :venue, :location, :note, :no_attempts, :submitted_at)",
                row,
            )
        print(f"💌 New answer #{cur.lastrowid}: {row['date']} {row['time']} · {row['venue']} · {row['location']}")
        self.send(201, json.dumps({"ok": True, "id": cur.lastrowid}))


def main():
    parser = argparse.ArgumentParser(description="Serve the date page and save answers to SQLite.")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow other devices on your network")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    init_db()
    Handler.admin_key = get_admin_key()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    shown_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0") else args.host
    print(f"Date page:   http://{shown_host}:{args.port}/")
    print(f"Her answers: http://{shown_host}:{args.port}/admin?key={Handler.admin_key}")
    print(f"Database:    {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
