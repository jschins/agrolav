# Stichting Instudo (country_id = 5)

Notes from the planned split: account-only login, two account groups, one
country balance. Not implemented yet. Beheer (country 4) is out of scope.

Today one person (id 24) holds five IBANs, all mapped on `dbo.mapping_banks`:

| account_id | IBAN | name |
|-----------:|------|------|
| 39 | NL46INGB0001726568 | Stichting Instudo |
| 40 | NL93INGB0003150749 | Den Eker |
| 41 | NL22INGB0004005627 | Studiecentrum |
| 42 | NL63INGB0000776923 | Leidenhoven College |
| 43 | NL61INGB0002843544 | Lepelenburg |

Bank posts 1021–1025 stay country-level. The live sheet is
`/balance/beheer_instudo`.

---

## 1. One person per account, two centers — not a `has_balance` rewrite

**Idea.** Instudo has two groups of accounts. Some logins should see only
one IBAN. The thought was: create as many persons as accounts; use `center`
for the two groups; then a personal login is account-only. That might also
allow a balance per center plus one country total, and drop a lot of
`dbo.country.has_balance` special-casing.

**What already exists.** Login is already person / center / country.
Personal login is one person. Several accounts on that person are the bank
switcher (plus Consolidated). There is no missing “account login” type.

`has_balance` does two jobs:

1. This country has a **balance sheet** (1000–4999 catalog, journals,
   openings, 2000 plug, spaar, afschrijvingen, the `:8100` app, three-sheet
   Excel).
2. Personal terms are **per account** (`_account_modality()` is
   `country_has_balance()`), because one person holds several IBANs with
   different P-term lists (`category_term.account_id`).

Job 1 does not go away if you create more persons. Countries 1–3 are a
different product (2-digit expense matrix, no journal, no 2000).

**Do this (data).** One `dbo.person` per Instudo IBAN. Two centers for the
two groups. Personal login is then account-only; center login is one group;
country login is everyone. Keep the same `account_id`s so `mapping_banks`
can stay. Leave `has_balance`, account-modality, and the country sheet as
they are.

After a full 1:1 split, account-modality becomes redundant *for that
country* (terms can hang off `person_id` alone). That is the only
`has_balance` special case you might later delete — and only after every
balance country is 1:1. The balance-sheet flag itself stays. Country view
becomes one matrix column per account instead of one Instudo column plus a
bank switcher.

**Do not bundle center balances.** A center is an access group, not a
balance grain. Journals, `balance_opening`, `afschrijvingen`,
`dim_category`, `condensed_balance`, `mapping_banks`, and the 2000 plug are
all `country_id`. Two centers do not give two sheets. Instudo already has
**Bijdrage SI centrale** (3125): inter-group bookings make “sum of two
center 2000s = country 2000” false unless that contra is designed.

Making each group its own `has_balance` country would give two sheets
cheaply and lose a native country total.

If a later project needs legal sub-balances: nullable `center_id` on
journal/opening (`NULL` = country-wide), not “more persons.”

**Not a code rewrite.** Person / center / country login, a matrix column
per person, and one country balance already work. No new access mode and no
center sheet.

**Not a few INSERTs either.** Bookings already sit on person 24. Re-key
them, then run Enable Banking consent again:

- New `dbo.person` rows (and a second `dbo.center` if the groups split).
- `UPDATE dbo.account SET person_id = …` (keep `account_id`).
- The same `person_id` on `transaction_beheer_instudo`, `category_total`,
  personal `category_term`, `enable_redirect`, and anything else keyed by
  person 24. Matrix and refresh filter by `person_id`; moving only the
  account row leaves a personal login looking at an empty book.
- `number_of_accounts` = 1 on each new person; 0 or delete the old combined
  person.
- Passwords / phones / titles for the new logins.
- A new `enable_connection` row per person; **new consent**, not a copied
  `session_id`.

Coding is only needed later if you hide **Balance sheet** from person (or
center) login, drop account-modality after every balance country is 1:1, or
build center-level journals/openings.

---

## 2. Same PEM for different persons

Yes for the **application key**. No for treating that as one shared **bank
login**.

`pem` + `app_id` on `dbo.enable_connection` is the Enable Banking
*application*: the RSA key the hub uses to sign JWTs. One application is
meant to start many end-user consents. Neither column is unique. Uploading
the same `.pem` onto another person (or inserting a second row with the
same `app_id` and key) works for JWT signing.

`session_id` / `valid_until` is one PSD2 consent: one bank authorization,
one set of IBANs. The hub stores that on the same row and looks it up by
`person_id`.

- **Same PEM, new consent per person** — supported. Each new person gets
  their own `enable_connection` row, same `app_id`/`pem`, their own
  `session_id`. `upsert_person_accounts` writes returned accounts onto
  *that* person.
- **Same PEM and the same live session** — the key copies, the session does
  not stay clean. `credentials_for_person` can follow `account.connection_id`
  even when another person owns the connection, but session refresh and
  account upsert still assume “this person’s row.” Two persons writing
  `session_id` on one row (or two copies of the same session) will fight
  when consent is renewed.

Practical path: copy the PEM, then consent once per person (or once per
group if one consent still returns only that group’s IBANs). Do not reuse
person 24’s `session_id` as the way to share the key.

---

## 3. `dbo.consent_pending`

Short-lived map from an Enable Banking OAuth `state` token to **which
person** started that consent.

The bank’s browser returns to `/api/consent/callback` with no login cookie
and no API key. The only handle is `state`. When the hub builds the
authorization URL it writes a row:

| column | meaning |
|--------|---------|
| `state` | PK, the OAuth token on the authorize link |
| `center` | center of that person |
| `person_name` | who must receive the session |
| `created_at` | expire the row after 30 minutes |

The callback looks up that row, then `complete_authorization` writes
`session_id` / `valid_until` on **that** person’s `dbo.enable_connection`
and attaches the returned accounts.

The same mapping also lives in hub memory (`consent_flow._pending`). SQL is
the backup when the hub restarts between “open the bank link” and the
redirect. After a successful or abandoned callback the row is deleted. The
hub creates the table at startup if it is missing.

This is not the consent itself. The live bank session stays on
`dbo.enable_connection`. The table is only “this `state` belongs to that
person, for the next half hour.”

---

## 4. Balance sheet: already one country sheet

There are not three balances. There is **one** sheet per `has_balance`
country (`/balance/beheer`, `/balance/beheer_instudo`). Country, center,
and person logins all get the same `balance_url` when the session has a
country — which they all do (`person → center → country`). The menu is a
shortcut to that country sheet.

The person-per-account + two-center change does not alter the accounting
grain. After the split, a personal login would still open the **whole
Instudo** sheet unless you later hide the knob.

| Decision | Default after the data split |
|----------|------------------------------|
| What the sheet *is* | Still one country balance |
| Who *sees the menu* | Unchanged (all three levels) unless you restrict it |

Restricting the menu to country login is a small UI/access rule, not
something the split forces. It may be desirable after 1:1: an account-only
person should not necessarily see every other IBAN on the country sheet.

Center-level sheets would be the opposite of “country only”: a second
grain, only if you add `center_id` on journal/opening. Until then there is
nothing to reduce.
