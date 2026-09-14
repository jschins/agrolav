# Maaltijden

Meal matrix for center `nl_dkg` (country `nederland`). Listens on
`127.0.0.1:8400`. Public URL: `https://expenses.apsurt.nl/maaltijden`.

Login uses `dbo.maaltijden_users`: `user_login` plus `passphrase` (plain
text; `NULL` means no password). Matrix rows are that list except login
**`admin`**, which only edits the extra counts. Marks live in
`dbo.maaltijden_data.code` (five bits per matrix person per day). All five
meals **O M A L P** cycle `x` ↔ `v`. Default is `x`. A person login can
edit only its own row.

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
