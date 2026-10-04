# Scoping

Login scope for terms, bookings, and which categories appear on screen.
Account scope and the right to edit G-terms are hard-coded. Two pieces of
data remain: `dbo.menu_item` decides whether the Terms row is in the menu,
and `dbo.dim_category.visibility` decides which categories that login may
see.

The hub is an API-key data API and does not know the browser login. The
client BFF refuses a write the login may not make. Resultaat and Balans
read SQL themselves. `dbo.dim_category.visibility` limits which categories
a login may assign. The sheets list every category that has a non-zero
amount.

Access strings are `country`, `local` (center), `personal` (person), and
`unit`. They come from `deduce_access` in `shared/shared/user_access.py`.

<!-- {en:scoping[5],terms,bookings,categories,visibility} -->
<!-- {nl:bereik[5],termen,boekingen,categorieën,zichtbaarheid} -->

## Who may change terms

Only a country login may add, change, or delete G-terms. Unit, person, and
center logins still see the G column, greyed out, both in the right-click
menu and in Alt+T. Greying the screen is not the control: the client
refuses the write with “Only a country login can change general terms.”
An administrator does not unlock G-term edits. The check is
`can_edit_general_terms` in `shared/shared/user_access.py`, called from
the client before a general-term save.

P-terms stay editable for every login, inside the accounts that login
already sees:

- A unit login may change P-terms only on its own account. A center-wide
  fan-out (`PUT /api/settings-center-accounts`) is refused for a unit.
  The message is “A unit login can change personal terms only on its own
  account.”
- A person, center, or country login may change P-terms on every account
  already in that login’s scope.

Unit logins open Edit Terms (Alt+T). The keyboard shortcut already did.
The menu row did not, because `dbo.menu_item` for `terms` had `unit = 0`.
`hub/sql/menu_item.sql` sets `unit = 1` on that row. G-terms on that
screen stay read-only.

<!-- {en:change[5],terms[5],g-term,country,unit} -->
<!-- {nl:wijzigen[5],termen[5],g-term,land,eenheid} -->

## Whose bookings each login sees

- An HD unit sees only its own bookings. That was already in place.
- A work-unit’s booking list is its own account. Writes of a booking are
  forced onto that account in the client.
- The result window still folds the sibling HD into a work-unit overview.
  An HD login does not fold the work-unit in.
- A person, center, or country login inspects and changes every account
  already in that login’s scope.

<!-- {en:bookings[5],sees[5],unit,account,scope} -->
<!-- {nl:boekingen[5],ziet[5],eenheid,rekening,bereik} -->

## Category visibility

`dbo.dim_category.visibility` is an integer from 1 to 5. A category is
shown when that number is at least the login’s rank.

| Login | Rank | Sees |
| --- | --- | --- |
| Country | 1 | 1–5 |
| Center | 2 | 2–5 |
| Person | 3 | 3–5 |
| Work-unit | 4 | 4–5 |
| HD | 5 | 5 only |

A missing, blank, or out-of-range value is treated as 5, so a category
stays visible until a tighter number is stored. The column default is 5.
If the column is not on the database yet, nothing is filtered.

This is display only. Totals, categorization, cross-postings, and term
matching still use every category. Hidden rows are omitted before the
displayed totals. On the live balance sheet the equity plug is recomputed
from the rows that remain, so that sheet still balances. The opening
balance sheet keeps the stored equity amount, so hiding rows there can
leave that sheet out of balance. Equity and Verlies follow the same
visibility number. At the default 5 they stay.

The filter is applied on:

- the matrix
- the Alt+T category list and the right-click category list
- the booking category picker (`valid_category_codes`)
- the result sheet
- the balance sheet, both standalone and the sheet under Resultaat
- the opening balance sheet
- the result-row list

A category name or code that is absent from the visibility map is kept.

HD versus work-unit is `category_role = 'hd'` on the unit’s mapped bank
category (`dbo.mapping_banks` joined to `dbo.dim_category`). The username
prefix `hd_` is the fallback. The flag is stored on the session at login.
Until the next login, a unit whose name starts with `hd_` is still treated
as HD.

`hub/sql/category_visibility.sql` adds the column and
`ck_dim_category_visibility` (`visibility BETWEEN 1 AND 5`). It is
idempotent. Existing rows stay at 5 until a tighter number is stored.
Run it on the database that holds `dbo.dim_category`.

The balance window URL now carries the same scope query as the result
window (`center`, `person`, or `unit=1` plus the account, and `login`),
so the standalone sheet filters too.

<!-- {en:category[5],visibility[5],dim_category,rank} -->
<!-- {nl:categorie[5],zichtbaarheid[5],dim_category,rang} -->

## Center rows in the term lists

The red center row is unchanged. In the right-click P-column dropdown,
and in the Alt+T account column, a center or country login sees each
center in red above that center’s accounts. Choosing it writes the
personal term onto every account in that center, through
`PUT /api/settings-center-accounts`. A country login gets one red row
per center. A center login gets that one center.

A person login does not get the red center row. The list is that
person’s own accounts. A unit login does not get the red row on
right-click, and a center-wide write from a unit login is refused.

<!-- {en:center[5],rows[5],term[5],lists[5],red} -->
<!-- {nl:centrum[5],rijen[5],term[5],lijsten[5],rood} -->

## Files that enforce login scope

| Rule | Code |
| --- | --- |
| Rank, G-term right, unit account check | `shared/shared/user_access.py` |
| Read `dim_category.visibility` | `shared/shared/balance_values.py` (`category_visibility`) |
| Settings and matrix payload maps | `hub/app/sql_catalog.py`, `hub/app/matrix.py`, `hub/app/center_api.py` |
| HD flag on the unit login | `hub/app/user_store.py`, `client/app/auth.py` |
| Filter matrix, settings, booking codes | `client/app/centrale_sync.py` |
| Refuse G-term and foreign-account P-term writes | `client/app/main.py` |
| Grey G-terms; red center rows | `client/frontend/src/App.tsx`, `client/frontend/src/index.css` |
| Result sheet and balance / opening sheets | `balance/app/result.py`, `balance/app/balance.py`, `balance/app/result_main.py`, `balance/app/main.py` |
| Terms menu bit for units | `hub/sql/menu_item.sql` |
| Visibility column | `hub/sql/category_visibility.sql` |
| Column note | `documentation/DATABASE.md` (`dim_category.visibility`) |

`hub/tests/test_term_scope.py` covers who may edit G-terms, which account
a unit may edit, and the visibility ranks.

<!-- {en:files[5],enforce[5],scope[5],g-term,account} -->
<!-- {nl:bestanden[5],afdwingen[5],bereik[5],g-term,rekening} -->

## SQL scripts and restarts after a scope change

Run `hub/sql/menu_item.sql` on a database that does not yet show Edit
Terms to a unit login. Run `hub/sql/category_visibility.sql` on the
database that holds `dbo.dim_category`.

Restart the hub, the client, balance, and result. Sign in again so an
HD login is taken from `category_role` and not only from the `hd_`
name. The client frontend was rebuilt for the grey G-terms; a refresh
picks that up once the client process is serving the new `dist`.

Until a visibility value below 5 is stored, every login still sees
every category.

<!-- {en:sql[5],scripts[5],restarts[5],scope[5],menu_item} -->
<!-- {nl:sql[5],scriptbestanden[5],herstarts[5],bereik[5],menu_item} -->
