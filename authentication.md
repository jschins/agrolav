# Authentication procedure in the legacy single-person flow

This is the bank-authentication sequence used by the older Boekh project, and it matches the same single-person Enable Banking pattern later reflected in the current hub/client setup.

## 1) Opening the add-person menu

The flow starts in the frontend when the user opens the add-person action. In the current hub/client UI, that action builds a URL like:

- `/add-person?center=<workspace>`
- or `/add-person` when no workspace is preselected

The server then creates a person pack under the relevant workspace. The request body includes a folder name and metadata like country, ASPSP, and the mode (`pem`). In other words, the system first creates the identity for a person, then prepares the folder where the bank credentials will live.

At this point the person is not yet fully authenticated; they simply have a dedicated folder that will hold:

- a `secret/` directory
- a `profile.json` entry
- a private key file (`*.pem`)
- later a consent record (`consent.json`)

---

## 2) Downloading the PEM file

The bank login is certificate-based. The private key is not just an optional file: it is the credential the app uses to authenticate itself to Enable Banking.

The key logic is roughly:

- `load_profile()` reads the person profile JSON
- `profile_app_id(profile)` reads the app id from `connections[].app_id`
- `profile_pem_path(profile)` resolves the matching PEM path
- `SingleDockerClient.from_profile()` requires both:
  - a valid `profile.json` containing an app id
  - a matching `.pem` file in the same `secret/` directory

The expected pattern is:

- `secret/profile.json`
- `secret/<app_id>.pem`

or, in older / simpler variants, a single `.pem` in the secret folder.

This is the critical upload/download step: the user owns the key material, downloads the PEM from the bank app / certificate flow, and the project stores it on disk so the app can later open a bank session.

---

## 3) Loading the bank statements

Once the PEM is in place, the project can actually connect to the bank.

The fetch flow is:

1. call `load_profile()`
2. instantiate `SingleDockerClient.from_profile(profile)`
3. call `_linked_accounts(profile, client, redirect_code)`
4. iterate over the linked accounts
5. call `client.get_transactions(account_uid, ...)`

The result is then normalized and returned as raw transaction data, with fields like:

- `_account_uid`
- `_account_index`
- the bank transaction payload itself

This is the step that downloads the actual bank statements. If consent or session data is missing or stale, the app will not proceed with the fetch; instead it asks the user to renew the consent.

The essential check is `needs_consent_renewal()`, which returns true when:

- no profile exists
- no valid bank session exists
- no account is linked
- or the consent/session is expired

---

## 4) If `consent.json` is missing: reconnect to Enable Banking for the consent record

This is the most important recovery path.

The project keeps the bank state in a consent record. That record is effectively the bank authorization/session data: account links, session id, valid until, and other consent metadata. The app can read it from `consent.json` and merge it into the person profile if needed.

If the consent record is absent, the app does this:

1. `get_authorization_url(...)` starts a fresh Enable Banking authorization
2. `client.start_authorization(profile, valid_until)` builds the bank login URL
3. the user is redirected to the bank login page
4. the callback endpoint `/api/consent/callback` receives the redirect code
5. `complete_authorization(raw_code)` exchanges that code for a real bank session
6. the session is written back into the consent/profile data

The pending callback registration is stored in `consent_flow.register_pending(...)`, tied to the workspace and short person name. This ensures the redirect can be matched back to the correct person when the bank returns to the callback page.

In plain terms: when `consent.json` is missing, the app does not just try to fetch transactions; it re-runs the Enable Banking consent flow so the bank will create the missing consent record, then the statements can be pulled normally.

---

## 5) Special frontend download menu for a single person

The frontend also has a special single-person scope. This is not the global workspace-wide refresh menu; it is a per-person menu used when the user is working in a single person's bank context.

The logic is:

- the frontend remembers the current scope as `workspace + person`
- refresh status is stored separately for that person, for example under a key scoped to the exact person
- only that person's refresh result is displayed or processed

This means the UI can trigger a single-person download/refresh without mixing it with the rest of the workspace. It is the narrow, person-specific menu that handles the final statement download after the consent is active.

In implementation terms, the app filters the stored refresh status and only keeps records matching the current person. That is the "special frontend menu" for the single-person workflow.

---

## Summary of the full sequence

The practical sequence is:

1. open the add-person menu
2. create the person pack for the workspace
3. download and store the PEM/private key
4. load the bank statements from the linked accounts
5. if `consent.json` is absent or stale, reconnect to Enable Banking and complete consent
6. once consent is present, download statements again for that person
7. use the special single-person frontend menu to refresh/download just that one account set

This is the legacy authentication pattern: certificate-based identity first, then Enable Banking consent/session as the real bank access record, then statement downloads on top of the valid consent.
