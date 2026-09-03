# Double login

Person usernames get a stored password hash, a Set password item in the menu, and a mobile number that can be verified with an SMS one-time code. Country and center logins stay on the current formula password and never use this path.

This document is the design. Schema changes on local and remote SQL are yours to apply so both databases stay identical. Do not run these `ALTER` statements from the agent.

---

## Current state

Login is username + password on the client (`LoginScreen` in `client/frontend/src/App.tsx`). The client BFF posts to hub `POST /api/auth/login` (`hub/app/main.py`). Hub `user_store.authenticate` compares the password to a **derived default**: `PASSWORD_PREFIX + username` (`!@#$%^&*()_` plus the username). Country, center, and person logins all use this.

The ⚙ **menu** (`ActionsMenu` in `client/frontend/src/App.tsx`) already opens terms, categories, and IP access in the same window (`history.pushState` / `openView`). Add-person and upload still navigate to a hub URL in the same window.

Add-person is a hub HTML wizard (`_ADD_PERSON_HTML` in `hub/app/main.py`): person name for both modes; manual-upload also Name, holder, account number, and initial balance. Create goes to `center_api.create_person` → `upsert_personal_login` or `create_manual_person`.

Scrypt helpers already exist in `client/app/passwords.py` (same encoding as upload tokens). The hub does not hash login passwords today. There is no SMS or OTP code in the repo.

```
Browser login → client BFF → hub POST /api/auth/login
                              → formula password (all login kinds)
                              → dbo.hub_ip allowlist
```

---

## 1. Set password — person usernames only

### Who

Only `access === "personal"` (a row in `dbo.person`). Country and center keep the formula password forever: no menu item, no `password_hash` column on those tables, and the set-password API must reject them even if called directly.

### Menu

Add **Set password** to `menuItems` in `client/frontend/src/App.tsx` when `access === "personal"`. Same in-window pattern as IP access: `openView("password")` plus a `SetPasswordApp`. Hidden for country and local (center) logins.

UI: current password, new password, confirm. On success stay logged in. Rebuild the client frontend after the UI change (`npm run build` in `client/frontend`).

### Storage

`dbo.person.password_hash` — `NVARCHAR(256)` (nullable until backfill). Never store plaintext.

Hash with the existing scrypt format from `client/app/passwords.py`:

```
scrypt$16384$8$1$<urlsafe-salt>$<urlsafe-digest>
```

Move `hash_password` / `verify_password` into `shared/` so hub and client use one implementation. Keep a thin re-export in `client/app/passwords.py` if other client code still imports from there.

### Default when a person is created

Hash `password_for_username(person)` (`PASSWORD_PREFIX + username`) and write it on insert in:

- `create_manual_person` (`hub/app/user_store.py`)
- `upsert_user` / `upsert_personal_login` (`hub/app/user_store.py`)
- load scripts that insert persons (`hub/scripts/load_phase_c.py`, `hub/scripts/load_barry.py`)

New persons can still log in with the familiar default until they set their own password.

### Existing persons

After the column exists, backfill `password_hash` from the same default formula so current logins keep working (see DDL below). Python backfill is awkward (per-row unique salts); a one-off hub script that hashes each username is the right tool, not a single SQL `UPDATE`.

### Authenticate

Change `user_store.authenticate` (`hub/app/user_store.py`):

- **Person** with `password_hash` set: `verify_password`.
- **Person** with `password_hash` still NULL (before backfill): fall back to `password_for_username` so nobody is locked out.
- **Country / center:** `password_for_username` only. Never read `password_hash`.

Hub `POST /api/auth/login` stays the entry point; IP allowlist (`dbo.hub_ip`) is unchanged.

### Set-password API

Authenticated, person-only, via the client BFF then hub:

- Body: current password, new password, confirm.
- Reject if current does not match the hash (or the formula fallback).
- Reject if new ≠ confirm, or new is empty.
- Write a new scrypt hash into `dbo.person.password_hash`.
- Return 403 for country/center sessions.

Suggested shape:

- Client BFF: `POST /api/auth/password`
- Hub: `POST /api/auth/password` (API key + session username from the BFF, same pattern as other authenticated hub calls)

---

## 2. Mobile phone + verification

### Columns

On `dbo.person`:

| Column | Type | Role |
|---|---|---|
| `mobile_phone` | `NVARCHAR(32) NULL` | E.164, e.g. `+31612345678` |
| `mobile_verified_at` | `DATETIME2 NULL` | Set only after a successful OTP. Unconfirmed numbers are not a second factor. |

### Add-person

One **Mobile phone** field on the hub wizard (`_ADD_PERSON_HTML`) for **both** modes (periodic consent and manual upload). Always visible; not gated by `applyModeUi`.

POST it on `POST /api/local/{center}/people/create` (`CreatePersonRequest` in `hub/app/main.py` plus `center_api.create_person`). Persist on insert in `create_manual_person` and `upsert_personal_login` / `upsert_user`.

Validation: required for **new** persons; must be E.164 (`+` then digits). Existing rows stay NULL until filled later (Set password screen or a verify-phone flow).

`mobile_verified_at` stays NULL at create; the person verifies after first login (or during the first OTP login step).

### Double login (person only)

After a number is stored **and** `mobile_verified_at` is set, person login is two steps:

1. Username + password (hash or default formula), same as today.
2. One-time code sent to `mobile_phone`.

Country and center: password only, never SMS.

### If `mobile_phone` is NULL (legacy persons)

**Policy (default):** password-only until a number is added and verified. Do not block existing person logins.

**Alternative (stricter):** refuse person login until a phone exists. Only switch to this after every person row has a number.

### SMS / OTP — nothing in the repo today

You pick the provider (Twilio, MessageBird, or similar). Put keys in env, not git.

Need:

- Env-configured sender (e.g. `SMS_PROVIDER`, `SMS_API_KEY`, `SMS_FROM`). Hub sends; client never holds SMS secrets.
- Short-lived OTP: store a **hash** of the code plus expiry, never the raw code. Table `dbo.person_otp` (see DDL).
- Hub after password OK: if the person has a verified phone, respond `otp_required` instead of issuing the full session. Then `request-otp` / `verify-otp`.
- Client `LoginScreen`: second step (code field) when the hub says `otp_required`. Cookie/session is issued only after OTP succeeds (or immediately for country/center / unverified phone).
- Local/dev: if the provider is unset, log the code (or skip OTP) so you can test without sending SMS. Never skip in production when a verified phone exists.

Suggested hub endpoints:

- `POST /api/auth/login` — password step; body unchanged; response `{ "user": ... }` or `{ "otp_required": true, "otp_token": "..." }` (short-lived, not a full session).
- `POST /api/auth/otp/request` — send SMS; rate-limit per person.
- `POST /api/auth/otp/verify` — `{ otp_token, code }` → `{ "user": ... }` then client sets the session cookie as today.

OTP rules: 6 digits, ~5 minute expiry, single use, invalidate older rows for that person when a new code is sent.

### Collecting a phone for legacy persons

Set password view (person only) can include **Mobile phone** + **Send code** / **Confirm** so an existing person can add and verify a number without going through Add person. Same validation and OTP table.

---

## 3. Schema you run on both databases

Idempotent, same spirit as `hub/sql/add_login_title.sql`. Run on **local and remote** `agrolav`. Backfill hashes with a small Python loop (unique scrypt salt per row), not a single SQL `UPDATE`.

```sql
USE agrolav;
GO

IF COL_LENGTH(N'dbo.person', N'password_hash') IS NULL
    ALTER TABLE dbo.person ADD password_hash NVARCHAR(256) NULL;
GO

IF COL_LENGTH(N'dbo.person', N'mobile_phone') IS NULL
    ALTER TABLE dbo.person ADD mobile_phone NVARCHAR(32) NULL;
GO

IF COL_LENGTH(N'dbo.person', N'mobile_verified_at') IS NULL
    ALTER TABLE dbo.person ADD mobile_verified_at DATETIME2 NULL;
GO

IF OBJECT_ID(N'dbo.person_otp', N'U') IS NULL
CREATE TABLE dbo.person_otp (
    otp_id INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    person_id INT NOT NULL,
    code_hash NVARCHAR(256) NOT NULL,
    expires_at DATETIME2 NOT NULL,
    created_at DATETIME2 NOT NULL CONSTRAINT df_person_otp_created DEFAULT (SYSUTCDATETIME()),
    consumed_at DATETIME2 NULL,
    CONSTRAINT fk_person_otp_person FOREIGN KEY (person_id) REFERENCES dbo.person (id)
);
GO

CREATE INDEX ix_person_otp_person_expires
    ON dbo.person_otp (person_id, expires_at)
    WHERE consumed_at IS NULL;
GO
```

Hash backfill (run once after the column exists; do not put plaintext passwords in SQL):

```text
For each dbo.person row with password_hash IS NULL:
  password_hash = scrypt(PASSWORD_PREFIX + username)
```

When implementing, also add `password_hash`, `mobile_phone`, and `mobile_verified_at` to `CREATE TABLE dbo.person` in `hub/sql/phase_c.sql` so **new** installs match. Do not run `phase_c.sql` against live data. Do not `DROP DATABASE`.

---

## Implementation map (when coding this later)

| Area | Files |
|---|---|
| Hash helpers | Move `hash_password` / `verify_password` to `shared/`; re-export from `client/app/passwords.py` |
| Default + insert | `hub/app/user_store.py` (`create_manual_person`, `upsert_user`), `hub/scripts/load_phase_c.py`, `hub/scripts/load_barry.py` |
| Authenticate | `hub/app/user_store.py` `authenticate`; `hub/app/main.py` `POST /api/auth/login` |
| Set password API | Hub + client BFF + `client/frontend/src/api.ts` |
| Menu + UI | `client/frontend/src/App.tsx` (`menuItems`, `openView`, `SetPasswordApp`); rebuild frontend |
| Add-person field | `hub/app/main.py` `_ADD_PERSON_HTML`, `CreatePersonRequest`; `hub/app/center_api.py` `create_person` |
| OTP | New hub module + `dbo.person_otp`; login screen second step |
| Target schema | `hub/sql/phase_c.sql` (CREATE TABLE only; you apply live ALTER) |

---

## Out of scope

- Changing country or center passwords
- Applying DDL from the agent (local and remote must stay identical under your control)
- Starting hub or client as part of writing this document
- Blocking legacy person login until a phone exists (optional later policy)
