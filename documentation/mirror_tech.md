# Spaarrekening mirror

Instudo is `beheer_instudo`, `country_id` 5. Its bookings are
`dbo.transaction_beheer_instudo`. A balance category id on that country is
`local_code + 10000`.

Centrale SIb is one spaar pair. The checking account is the source. The
savings post is the mirror. There is no live savings account.

| role | local code | category id | name |
| --- | --- | --- | --- |
| `source` | 1020 | 11020 | Centrale SIb |
| `mirror` | 1021 | 11021 | Spaarrekening SIb |

Centrale SIa is the same pair in the other center: source 1018 / 11018,
mirror 1019 / 11019. A source is paired only with the mirror in its own
center.

`dbo.dim_category.category_role` names the two posts. `source` is the
checking post. It follows the bank rules: no term hit, journals allowed.
`mirror` is the savings post. A term hit is allowed, and journals are
allowed. The pass that builds the pair reads those two roles. The checking
account itself comes from `dbo.mapping`: the row whose `category_id` is the
source category and whose `counterparty_account_id` is empty. That
`account_id` is the account whose bookings are scanned for `spaarrekening`.
`dbo.dim_category.account_id` is not read. A source with no such mapping row
is skipped, and the pair is not built. The mirror category has no mapping
row. The sheet does not take a live account balance for it.

`rebuild_spaar_mirror_rows` in `shared/shared/balance_values.py` rebuilds
the pair. The hub runs it when a center/year matrix is loaded. The balance
app runs it from `generate_spaarmirror`. Existing `[spaar-mirror]` rows for
that mirror category and year are deleted, then written again.

---

## The two writes

A bank booking on the source account counts when its description contains
`spaarrekening`, compared in lower case.

1. That booking’s `category_id` is set to the mirror id (11021 for
   Spaarrekening SIb). This runs only when `modification` is −1 or 0.
   A row at 1, 2, 3, or 4 keeps the category it already has.
2. Every such booking, including a row left at 1, 2, 3, or 4, produces one
   row in `dbo.transaction_mirror`. The description starts with
   `[spaar-mirror]`. The date is the booking date. The category is the
   mirror id. The amount is the opposite of the bank amount.

The bank amount `d` is the statement sign: money out is negative. The
mirror stores `−d`. €100 leaving Centrale SIb is `d = −100` on the checking
account and `+100` on Spaarrekening SIb. €100 arriving is `+100` on the
checking account and `−100` on the savings post.

---

## Counterpart of the mirror row

The `[spaar-mirror]` row is one stored line. Nothing else is inserted for
it. Its counterpart is the bank booking on Centrale SIb that caused it.

The checking post on the sheet is the live account balance, and that
balance already contains `d`. The savings post is its opening balance plus
the sum of these mirror rows, taken as stored. The activa sign flip is not
applied to them. The two sides sum to 0, so the plug (local code 2000)
does not move: money has changed post, from the checking account to the
savings post, or back.

The keyword booking is left out of the category totals. `d` is not added
again on top of the live account, and it is not added to 1021 through the
booking overlay. The category written onto the bank row is a label. The
amount that moves Spaarrekening SIb is the mirror row.

Opening 1021 shows the `[spaar-mirror]` rows. The bank bookings that caused
them stay on the Centrale SIb account and are left out of that list.

---

## What the category column shows

`dbo.transaction_mirror.category_id` stores `dbo.dim_category.category_id`.
On Instudo that is the local code plus 10000, so local code 1021 is stored
as 11021.

The booking table's category column shows the local code, four digits.
`_load_nonbank_category_rows` reads the stored id and sends
`dim_category.local_code`. A mirror row for Spaarrekening SIb shows 1021.
A bank booking does the same through its join to `dbo.dim_category`.
