# Double login

Person usernames use a stored password hash, a **Set password** item in the
menu, and an optional mobile number verified with an SMS one-time code.
Country and center logins stay on the derived formula password and never
use this path.

---

## Who does what

| Login | Password | Second step | IP gate |
|:------|:---------|:------------|:--------|
| Person | scrypt hash on `dbo.person.password_hash` | SMS when `mobile_phone` is set | no |
| Center | `PASSWORD_PREFIX + username` (`!@#$%^&*()_` + name) | none | `dbo.administrator` ∪ own `egress_ip` |
| Country | same formula | none | same |

The set-password API rejects country and center sessions even if called
directly. There is no `password_hash` column on those tables.

---

## Browser path

```text
Browser → client POST /api/login
       → hub POST /api/auth/login  (username + password + client_ip)
            → person with mobile_phone: { otp_required, otp_token }
            → otherwise { user }
       → hub POST /api/auth/otp/verify  (person SMS step only)
       → client sets the session cookie
```

Hash format (shared by hub and client):

```text
scrypt$16384$8$1$<urlsafe-salt>$<urlsafe-digest>
```

Helpers live in `shared/`. New persons are inserted with a hash of the
formula password, so they can log in until they set their own.

---

## Set password

Menu item only when `access === "personal"`. UI: current password, new
password, confirm, optional mobile (`+316…` or `06…`). **Save** / **Cancel**;
the header menu is hidden on this page.

APIs: client `POST /api/auth/password` → hub `POST /api/auth/password`.
Rejects if current does not match, if new ≠ confirm, or if new is empty.

---

## SMS one-time code

Keys in env, not git: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_FROM`. If any of the three is missing, the hub still prints the
code so local testing works without sending SMS.

After password OK, a person with `mobile_phone` set gets `otp_required`
instead of a session. The client shows a 6-digit field and **Resend**.
Hub `POST /api/auth/otp/verify` and `POST /api/auth/otp/resend`. Country
and center never take this path.

---

## Schema

On `dbo.person`:

| Column | Type | Role |
|---|---|---|
| `password_hash` | `NVARCHAR(256) NULL` | scrypt; never plaintext |
| `mobile_phone` | `NVARCHAR(32) NULL` | E.164 |

These columns are in `hub/sql/phase_c.sql` for new installs. Live databases
that predate them need the same `ALTER` on **local and remote** so they
stay identical:

```sql
USE agrolav;
GO

IF COL_LENGTH(N'dbo.person', N'password_hash') IS NULL
    ALTER TABLE dbo.person ADD password_hash NVARCHAR(256) NULL;
GO

IF COL_LENGTH(N'dbo.person', N'mobile_phone') IS NULL
    ALTER TABLE dbo.person ADD mobile_phone NVARCHAR(32) NULL;
GO
```

Backfill hashes with a Python loop (unique scrypt salt per row), not a
single SQL `UPDATE`. `hub/scripts/` has the one-off hasher.

---

## Files

| Area | Where |
|---|---|
| Hash helpers | `shared/` (re-export in `client/app/passwords.py`) |
| Authenticate | `hub/app/user_store.py` |
| Login + OTP | `hub/app/main.py`, `hub/app/person_otp.py` |
| Set password UI | `client/frontend/src/App.tsx` |
| Add-person mobile | hub wizard `_ADD_PERSON_HTML` |
