# Maaltijden

Meal matrix for center `nl_dkg` (country `nederland`). Listens on
`127.0.0.1:8400`. Public URL: `https://expenses.apsurt.nl/maaltijden`.

Login uses `dbo.maaltijden_users`: `user_login` plus `passphrase` (plain
text; `NULL` means no password). The matrix rows are that same list (ids
`1..N`). Marks live in `dbo.maaltijden_data.code` (five bits per user per
day). Meal **A** cycles `x` → `v` → `L` → `x`; **O**, **L**, and **P**
cycle `x` ↔ `v`. Default is `x`. A login can edit only its own row.

Weeks run Sunday–Saturday. Terms in the UI are Dutch.

```bash
cd maaltijden
uv sync
cd frontend
npm ci
npm run build
cd ..
uv run maaltijden
```

On the server, create systemd unit `agrolav-maaltijden` (not in git) with
`EnvironmentFile=/etc/agrolav/maaltijden.env` and
`ExecStart=.../uvicorn app.main:app --host 127.0.0.1 --port 8400`. Reload
Caddy so `/maaltijden*` reaches `:8400` before the client catch-all. Then
`npm run build` in `maaltijden/frontend` and restart the unit. See
[`documentation/deployment.md`](../documentation/deployment.md) §12a.
