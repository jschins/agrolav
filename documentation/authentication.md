# Enable Banking — add person, PEM, consent, download

How a person gets from “create login” to bank bookings in SQL. Consent and
the application private key live on `dbo.enable_connection`, not on disk.

---

## 1. Add person

From the client menu, **Add person** opens the hub page
`/add-person?center=<workspace>` (Caddy routes that path to `:8200`).

The wizard asks for a person name (both modes). Manual-upload also asks
for holder, account number, and initial balance. Optional: mobile phone
(E.164), which later turns on SMS login.

Create goes to `POST /api/local/{center}/people/create` → a row in
`dbo.person` (and `dbo.account` for manual upload).

---

## 2. Application PEM

Bank login is certificate-based. The private key authenticates the hub to
Enable Banking. It is stored on `dbo.enable_connection.pem` together with
`app_id`.

The hub loads that row, not a `secret/*.pem` file. After the person
downloads the PEM from the Enable Banking control panel, the wizard
uploads it onto the connection row for that `person_id`.

---

## 3. Consent

The hub starts authorization with `get_authorization_url` /
`start_authorization`. The callback URL is `ENABLEBANKING_REDIRECT_URL`
(production: `https://expenses.apsurt.nl/api/consent/callback`). That URL
must match the application registered for this `app_id`.

The pending callback is a row in `dbo.consent_pending`. `state` is not a
status. It is the OAuth `state` token Enable Banking puts on the
authorization link and sends back on the redirect. The row is:

| column | meaning |
|--------|---------|
| `state` | primary key; the token from the authorize link |
| `center` | center of the person who started consent |
| `person_name` | who must receive the session |
| `created_at` | the row is dropped after 30 minutes |

The bank’s browser opens `/api/consent/callback` with `code` and `state`
only. There is no login cookie and no API key. The hub looks the token up,
reads center and person, deletes the row, then exchanges `code` for the
session. A second click, or a new link after expiry, is a new `state` and
a new row. An older link stays valid until its own row expires.

A `state` column on `dbo.enable_connection` does not replace this table.
That table is one row per person and already holds the lasting credential
(`pem`, `app_id`, and later `session_id`). One extra column holds one
token. Each authorization link is its own token, so a second click
overwrites the first. The earlier bank tab then no longer matches.
`consent_pending` keeps one row per token, and deletes that row when the
callback is used or when it is older than 30 minutes. The connection row
has to stay. Clearing a column still leaves the used token’s lookup on the
row that holds the private key. The pending table holds neither the key
nor the session. The session is written to `enable_connection` only after
the token has been matched.

`/api/consent/callback` receives the redirect code;
`complete_authorization` exchanges it for a session. The hub writes
`session_id`, `valid_until`, and `created_at` on `dbo.enable_connection`.
Linked accounts land on `dbo.account` (`uid`, `connection_id`, `format`).

If consent is missing or expired, refresh does not fetch transactions; it
returns an authorization URL instead.

---

## 4. Download statements

Once the connection has a live session:

1. load the connection + accounts from SQL
2. for each linked account, `get_transactions(account_uid, …)`
3. normalize and insert into `dbo.transaction_{country}`
4. update `account.balance` and `account.last_booked`

The frontend can scope refresh to one person (`workspace + person`) so a
single download does not mix with the rest of the center.

---

## Sequence

1. Open **Add person**.
2. Create the `dbo.person` row (and optional mobile).
3. Store the PEM on `dbo.enable_connection`.
4. Complete Enable Banking consent; session lands on the same row.
5. **Download transactions** pulls bookings into SQL.
6. If consent expires, the same download action starts a new authorization.
