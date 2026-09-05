# SQL Server is the store

The SQLite / JSON cutover is done. Logins, bookings, categories, bank
connections, and IP allowlists live in database **agrolav**.

- Schema and table reference: `DATABASE.md`
- Deploy, restore, env files, Caddy: `deployment.md`

Do not create a parallel user table. Do not keep a JSON tree as a live
write path. `HUB_DATABASE_URL` is required; the hub will not start without
it.

Category ids are the 100+ surrogates in `dbo.dim_category` (Nederland 12
Vervoer = 104). Bookings sit in `dbo.transaction_{country}`. Enable Banking
PEM and session sit on `dbo.enable_connection`.
