# Maaltijden

Household meal sheet for center `nl_dkg` (country `nederland`). It is a
separate FastAPI app on **port 8400**, not a page of the 8300 client.

| | |
|---|---|
| Public URL | `https://expenses.apsurt.nl/maaltijden` |
| Local | `http://127.0.0.1:8400/maaltijden` |
| systemd | `agrolav-maaltijden` |
| Caddy | `handle /maaltijden*` → `127.0.0.1:8400` (before the 8300 catch-all) |
| Cookie | `maaltijden_session` (path `/maaltijden`, same `CLIENT_SESSION_SECRET` as the client) |

Login is **not** the hub / 8300 account. The username is
`dbo.maaltijden_users.user_login`. If `passphrase` is `NULL`, any (including
empty) password is accepted. If it is set, the submitted password must equal
that value as stored — not hashed. There is no SMS step and no IP gate.

Each login may edit only its own row.

The UI language is Dutch. Table columns are in [`DATABASE.md`](DATABASE.md).
First-start commands are below; [`deployment.md`](deployment.md) §12a is
the same unit.

---

## What you see

After login, a bar sits above a horizontal rule:

- **Week** — Sunday through Saturday. The menu starts at this week's
  Sunday and lists later Sundays of this year only (`13 september`,
  `20 september`, …). No year, and no past weeks.
- **Weergave** — **Matrix** or **Persoon**.
- **Uitloggen**

### Matrix

Rows are the people in `dbo.maaltijden_users`, in `id` order (display name
from `dbo.person.title` when that login exists).

Columns are seven days × four meals. Meals are the hardcoded letters
**O**, **L**, **A**, **P**. Above the meal letters: the day of the month;
above those days: the month name (one span when the week stays in one
month, two when it crosses).

The grid is packed so it can sit on a phone; cells that are not yours are
visible but not editable. The last row is **totalen**: count of `v` per
column, except **A** which is `{v}/{L}`.

### Persoon

Only the logged-in person’s marks. Five columns: **Dag**, **O**, **L**,
**A**, **P**. Seven rows: **Zondag** through **Zaterdag**. Larger tap
targets. If the login is not a row in `dbo.maaltijden_users`, this view
says the sheet is only available with a personal login.

---

## Marks

Each cell is a letter, not a native checkbox. Missing data displays as
**x**.

| Meal | Click cycle |
|------|-------------|
| O, L, P | `x` ↔ `v` |
| A | `x` → `v` → `L` → `x` |

**L** exists only on meal **A**. A login may change only the row whose
`user_login` matches.

---

## Storage

Two tables in database **agrolav**. The app does **not** create them. Run
[`maaltijden/sql/maaltijden.sql`](../maaltijden/sql/maaltijden.sql) in
SSMS, then insert the people.

### `dbo.maaltijden_users`

Who appears, and in which bit slots.

| column | |
|--------|--|
| `id` | `INT` PK. Must be the dense list `1, 2, …, N`. No gaps. |
| `user_login` | `VARCHAR(32)`. Login name. |
| `passphrase` | `VARCHAR(64)` NULL. Plain-text password; `NULL` means none. |

`N` must be ≤ **12**: each person uses five bits, and `code` is a signed
`BIGINT` (at most 60 bits used).

Adding or removing a person, or changing order, moves bit slots. Do that
only together with rewriting every `code` in `maaltijden_data`.

### `dbo.maaltijden_data`

One row per day of a **365-day** year. There is no year column, so 15 maart
in any calendar year reads the same row.

| column | |
|--------|--|
| `id` | `INT` PK, 1–365. 1 = 1 januari, 365 = 31 december. |
| `code` | `BIGINT NOT NULL`. Default `0` (every mark `x`). |

Leap years: 29 februari shares id **59** with 28 februari. Days after that
shift back by one so 31 december is still 365.

The week menu never lists a Sunday before this week.

---

## Bit layout of `code`

For user `id` *k*, the five bits start at bit `5 × (k − 1)` (user 1 =
lowest bits 0–4, user 2 = bits 5–9, …). Width of the used field is always
`5 × N`.

| bit in the group | meal | 0 | 1 |
|----------------:|:-----|---|---|
| 0 | O | `x` | `v` |
| 1 | L | `x` | `v` |
| 2 | A | `x` | `v` (ignored when bit 4 is 1) |
| 3 | P | `x` | `v` |
| 4 | A is `L` | A is `x` or `v` | A is **`L`** |

Example: user 1 has O=`v`, A=`L`, everything else `x` → `code = 1 + 16 = 17`.
User 2 with only P=`v` adds `8 << 5` → `code = 17 + 256 = 273`.

A click reads that day’s `code`, replaces the five bits for one user, and
writes the bigint back.

---

## How the pieces connect

```text
browser  →  Caddy  →  :8400  /maaltijden
                         │
                         ├─ login            →  SQL  dbo.maaltijden_users
                         └─ week / mark      →  SQL  dbo.maaltijden_*
```

- `maaltijden/app/auth.py` — `maaltijden_users` login, signed cookie.
- `maaltijden/app/meals.py` — Sunday weeks, day-id mapping, pack/unpack.
- `maaltijden/app/main.py` — `/maaltijden/api/login`, `/week`, `/mark`, SPA.
- `maaltijden/frontend` — login, week/weergave menus, matrix and person
  views. `base` is `/maaltijden/`.

Non-secret env: `HOST`, `PORT` (8400), `SERVER_URL` (hub), optional
`MAALTIJDEN_DIST`. Secrets stay in the root `.env`
(`HUB_DATABASE_URL`, `CENTRALE_API_KEY`, `CLIENT_SESSION_SECRET`). See
[`environment.md`](environment.md) §2.4.

---

## First start on the server

The unit is **not** in git. `systemctl restart agrolav-maaltijden` fails
with `Unit not found` until you create it. Do not put secrets in
`maaltijden.env`. Dist is gitignored: always `npm ci` **before**
`npm run build` (`tsc: not found` means `node_modules` is missing).

```bash
cd /opt/agrolav/maaltijden
uv sync

cd /opt/agrolav/maaltijden/frontend
npm ci
npm run build

sudo tee /etc/agrolav/maaltijden.env >/dev/null <<'EOF'
HOST=127.0.0.1
PORT=8400
SERVER_URL=http://127.0.0.1:8200
EOF
sudo chmod 600 /etc/agrolav/maaltijden.env

sudo tee /etc/systemd/system/agrolav-maaltijden.service >/dev/null <<'EOF'
[Unit]
Description=Agrolav maaltijden
After=network.target

[Service]
WorkingDirectory=/opt/agrolav/maaltijden
EnvironmentFile=/etc/agrolav/maaltijden.env
ExecStart=/opt/agrolav/maaltijden/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8400
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now agrolav-maaltijden
sudo systemctl status agrolav-maaltijden --no-pager
```

Caddy must send `/maaltijden*` to `:8400` **before** the catch-all to
`:8300`. Caddy does not read the repo file until you copy it:

```bash
grep maaltijden /etc/caddy/Caddyfile || true
sudo cp /opt/agrolav/client/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8400/maaltijden/api/health
curl -sSI https://expenses.apsurt.nl/maaltijden
```

`grep` must show `handle /maaltijden*`. Direct `:8400` health is `200`;
that does not prove Caddy is routing. The `https://` headers should be a
`307` to `/maaltijden/` or a `200` HTML page, not `{"detail":"Not Found"}`.

Create `dbo.maaltijden_users` and `dbo.maaltijden_data` in SSMS
(`maaltijden/sql/maaltijden.sql`), including column `passphrase`, then
insert the `1..N` people, before anyone uses the sheet. If the users table
already exists without that column:

```sql
ALTER TABLE dbo.maaltijden_users ADD passphrase VARCHAR(64) NULL;
```

Later frontend-only updates:

```bash
cd /opt/agrolav/maaltijden/frontend
npm ci
npm run build
sudo systemctl restart agrolav-maaltijden
```
