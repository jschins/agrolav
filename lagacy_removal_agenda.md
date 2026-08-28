# Legacy Removal Agenda

## Goal

Remove the remaining folder-based terminology and filesystem dependencies from the active application once all data is database-backed.

## Remaining Legacy Areas

- `PersonPack.folder` and related filesystem paths in `hub/app/paths.py` and `hub/app/people.py`.
- `folder_name` fields and folder-derived person discovery.
- Folder-based year data and JSON files used by the legacy filesystem workflow.
- Bank-account subfolder handling in `hub/app/core/bank_csv.py`.
- Folder-based transaction, category, totals, profile, consent, and upload paths.
- Legacy folder terminology in API payloads and UI labels outside the add-person and PEM flow.
- `artifacts/` release copies containing older folder-based implementations.

## Dependencies To Resolve First

1. Ensure `dbo.center` is the sole source for center selection and validation.
2. Ensure `dbo.person` is the sole source for person discovery and identity.
3. Ensure `dbo.account` is the sole source for account registration and account metadata.
4. Ensure Enable Banking session data is stored in `dbo.enable_connection`.
5. Ensure transactions, categories, balances, and modifications are read from and written to SQL Server.
6. Replace JSON profile and consent state with database tables or a defined SQL representation.
7. Replace filesystem upload and bank-account folder logic with database-backed APIs.
8. Migrate or explicitly discard existing legacy JSON and folder data.
9. Update client and hub API contracts so `person` is used consistently and no folder keys remain.
10. Add tests covering SQL-only operation with no country, center, person, year, or account directories.

## Removal Sequence

1. Inventory all runtime imports and API consumers of `PersonPack.folder`, `folder_name`, and folder-derived paths.
2. Add SQL replacements for every remaining filesystem read and write.
3. Migrate existing data and verify row counts and referential integrity.
4. Remove filesystem fallback branches from hub and client workflows.
5. Remove folder fields from shared models and API responses.
6. Remove obsolete JSON and folder helpers, terminology, and documentation.
7. Rebuild release artifacts from the updated source.
8. Run SQL-only integration tests and verify a complete PEM workflow from person creation through transaction ingestion.

## Current Constraint

Do not remove the remaining folder fields yet: they are still used by legacy filesystem compatibility and bank-account subpath handling. Deleting them before the SQL replacements and migration are complete can break existing workflows.
