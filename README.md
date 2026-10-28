# Date Invite

A playful page that asks someone out on a date. The "No" button runs away, and after "Yes" they pick the day, time, kind of date and place, and leave a note. Answers are saved to a local SQLite database.

## Run it

Needs only Python 3 (no packages to install).

```bash
python3 server.py
```

- Date page: http://localhost:8000/
- Answers: http://localhost:8000/admin?key=YOUR_KEY (the key is printed when the server starts and saved in `.admin_key`)
- Database: `date.db`

To share it outside your computer, run a tunnel in a second terminal:

```bash
cloudflared tunnel --url http://localhost:8000
```

Use `python3 server.py --host 0.0.0.0` to open it to other devices on the same Wi-Fi instead.

`date.db` and `.admin_key` are git-ignored, so answers and the key never get committed.
