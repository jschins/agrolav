# Remaining SQL-only work

The live store is SQL Server. This list is only what still has a filesystem
or dual-path leftover in the hub — not a second architecture.

## Still to finish

1. Person discovery and year data must not fall back to country/center/person
   directories. `dbo.center`, `dbo.person`, `dbo.account`, and
   `dbo.transaction_*` are already the intended source.
2. Upload: list filenames from `dbo.uploaded_files`; ingest parse-from-bytes
   into `dbo.transaction_*`. Tests should pass with no folders on disk.
3. Recategorize with `UPDATE` on `transaction_*` so refresh/upload cannot
   drift from a JSON replica.
4. Drop leftover file-based hub allowlist handling in `upload_acl.py`
   once no host still has that file.
5. Add tests covering SQL-only operation with no country, center, person,
   year, or account directories.

## Do not

Do not invent a second user table or a hub-wide IP table. Logins are
`dbo.country` / `dbo.center` / `dbo.person`. The IP gate is
`dbo.administrator` plus each login’s `egress_ip` column. Attempts go to
`dbo.visitor_ip`.
