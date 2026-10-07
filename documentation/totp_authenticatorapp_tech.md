# Authenticator app (TOTP)

The second step is a code from an authenticator app. Twilio SMS is no longer the second step.

It follows the lowest login of the country, the one that can sign in from anywhere:

| Country | `dbo.country.has_balance` | Login that enrolls | Table |
| ------- | ------------------------- | ------------------ | ----- |
| No balance sheet | not set | person | `dbo.person` |
| Balance sheet | set | unit | `dbo.unit` |

Country and center always stay on the IP check. In a balance country the person login stays on the IP check as well. A person row there does not enroll an authenticator. A unit login exists only in a balance country.

Any app that scans a QR code works: Google Authenticator, Microsoft Authenticator, Aegis, or another TOTP app. The code is six digits and changes every 30 seconds (RFC 6238, SHA-1, 30-second step, window of one step either side for clock skew).

---

## When the second step runs

The hub asks for the authenticator code only when both are true: this login is the one in the table above, and `totp_secret` is stored. Any other login finishes on username and password, then the IP check where that login has one.

An empty secret on an eligible login still finishes on username and password, the same way a login with no mobile number does today.

`mobile_phone` no longer turns the second step on.

---

## Login

```text
Browser → client POST /api/login
       → hub POST /api/auth/login  (username + password + client_ip)
            → eligible login with totp_secret: { otp_required, otp_token }
            → otherwise { user }
       → hub POST /api/auth/otp/verify  (code from the app)
       → client sets the session cookie
```

The screen keeps the six-digit field. The prompt tells the user to enter the code from the authenticator app. There is no Resend. There is no `dev_code` and no phone hint.

`otp_token` is a short-lived JWT that names the username. The hub checks the typed digits against that login's stored secret. A match issues the session. A mismatch or an expired token returns 401.

---

## Enrollment

Enrollment is on the set-password page, and only for a login that is already signed in and eligible: a person in a country without `has_balance`, or a unit in a country with `has_balance`.

1. The page asks the hub for a new secret.
2. The hub returns an `otpauth://totp/Agrolav:<username>?secret=...&issuer=Agrolav` URI and the secret in groups, for manual entry.
3. The page shows the QR code and the secret.
4. The user types the first code from the app.
5. The hub checks that code and then writes the secret. Until that check succeeds, the secret is not stored and login stays on password only.

Turning the authenticator off clears the secret. The next login is password only.

---

## Secret

One column on each login that can use the second step:

| Table | Column | Type | Role |
| ----- | ------ | ---- | ---- |
| `dbo.person` | `totp_secret` | `NVARCHAR(64) NULL` | Base32 TOTP secret for a person in a country without `has_balance`. Empty means no second step. |
| `dbo.unit` | `totp_secret` | `NVARCHAR(64) NULL` | Same, for a unit in a country with `has_balance`. |

The column is added in SSMS. The hub does not create it. The secret is the enrollment key, not a one-time code and not a password hash.

A lost phone is recovered by clearing `totp_secret` for that username. The user signs in with the password and enrolls again from the set-password page.

---

## What leaves the SMS path

`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM` are unused. `hub/app/person_otp.py` stops calling Twilio. `POST /api/auth/otp/resend` and the Resend button go away. The set-password page stops asking for a mobile number as the way to turn on the second step.

---

## Where this is implemented

| Area | Where |
| ---- | ----- |
| Issue and check the code | `hub/app/person_otp.py` |
| Login and verify routes | `hub/app/main.py` |
| Read and write `totp_secret` | `hub/app/user_store.py` |
| Client login and set-password page | `client/frontend/src/App.tsx` |
| Client proxy | `client/app/main.py`, `client/app/auth.py` |
| Column | `hub/sql/totp.sql` |
