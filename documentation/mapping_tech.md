# Mapping an account to a category

`dbo.mapping` links a category to an account. `mapping_id` is the key.
A row whose `counterparty_account_id` is NULL is one link between a
balance category and a bank account. The columns of that link are
`country_id`, `category_id`, and `account_id`. A filled
`counterparty_account_id` is one leg of a cross-posting pair and is not
an account balance.

A NULL row is read in one of two directions.

- **Bank.** The category is the balance-sheet post. The account is where
  that post’s figure comes from. The sheet reads the account.
- **Cash on hand.** The account is where the booking sits. The category is
  the activa post the booking is written to. The booking is written onto
  the category.

Country 5 (`beheer_instudo`) stores `category_id = local_code + 10000`.
Its bookings are `dbo.transaction_beheer_instudo`.

---

## Bank categories

`account_links` in `shared/shared/balance_values.py` loads

```sql
SELECT category_id, account_id
FROM dbo.mapping
WHERE country_id = ?
  AND counterparty_account_id IS NULL
```

and keeps `category_id → account_id`. `category_map` then stores that
account on every activa/passiva post (local code 1000–2999). The balance
sheet uses the mapped account’s balance for that post. A click on the post
opens that account’s bookings (`load_bound_balance_transactions`: the
mapped `account_id`, or the account already selected in the session).

Three category ids stay on `dbo.balance_opening` even when a mapping row
still points at an account: `11019`, `11021` (spaar openings), and `11100`
(the SIa leg of the SIa/SIb pair, local 1100). A `mirror` role never uses a
leftover mapping row as a live account.

A spaar `source` still needs its mapping row: that `account_id` is the
checking account the mirror is paired with. The mirror post itself is not
filled from that account.

The same join answers what kind of account it is. `category_role = 'hd'`
on the mapped `dim_category` row marks the Huishoudelijke Dienst. Roles
`unitNNNN`, `userNNNN`, `source`, and `mirror` are read the same way
(`hub/app/cross_postings.py`, and the HD flag on a unit login).

A cross-posting release does not treat a mapped category as a
cross-posting category. A four-digit local code that is itself a live bank
post in `dbo.mapping` (counterparty NULL) stays where it is.

One account can have more than one row. The bank row is the post whose
figure is that account’s balance. The cash row, below, is a different
`category_id` on the same `account_id`.

---

## Cash-on-hand categories

Country 5 has seven cash posts, local codes 1133–1139, stored as
`category_id` 11133–11139. Each is an activa post for cash taken out of
one Huishoudelijke Dienst. The mapping row points that post at the HD
account the cash was withdrawn from.

| category_id | account_id |
|---|---|
| 11133 | 55 |
| 11134 | 48 |
| 11135 | 57 |
| 11136 | 47 |
| 11137 | 46 |
| 11138 | 45 |
| 11139 | 56 |

`account_id` is the HD account. `category_id` is the cash post.

The balance sheet does not read `dbo.account.balance` for these posts.
`Start (vóór mutaties)` is the `dbo.balance_opening` amount. When that
table has no row, the amount is zero. After that, the line is the sum of
bookings whose `category_id` is the cash post. A booking has one category:
once it is the cash post it is no longer a P&L category, so the amount
stays on the cash line and does not move Eigen vermogen.

A booking on one of those accounts is written to the matching
`category_id` when `dbo.transaction_beheer_instudo.bank_type` is
`Geldautomaat`. Any other `bank_type` on the same account is left to the
term lists and to cross-postings.

The write runs at two moments, and it runs first.

- **Recalculate categories**, before the term lists score the open rows.
- **Refresh download of bookings**, before cross-postings pair the rows
  just stored.

A row already set by hand (`modification` 2, 3, or 4) is not rewritten.
After the cash write, the term pass and the cross-posting pass leave that
booking on the cash post: it is no longer an open row for either of them.
A `Geldautomaat` row is not one leg of a cross-posting pair.

---

## Cross-posting categories

The work-unit against its HD is read from `dbo.dim_category` when
`account_id` and `assoc_category_id` are filled. `account_id` is the bank
of that category. `assoc_category_id` names one other category.

Country 4, in that shape:

| category | role | account_id | assoc_category_id | what it says |
|---|---|---|---|---|
| 1053 | `hd` | 44 | 1056 | this HD bank's work unit is 1056 |
| 1056 | `unit` | 21 | 1051 | this work unit's central bank is 1051 |
| 1051 | `source` | 18 | 1101 | the unit booking against this bank is written to 1101 |
| 1057 | `cash` | 44 | | Geldautomaat on account 44 is written to 1057 |
| 1101 | `rc` | 21 | 1051 | the same link as the work-unit bank |
| 1111 | `rc` | 44 | 1056 | written on account 21 against this HD |

A booking on account 21 against account 44 is written to 1111. The booking
on account 44 is written to `cp` (1110). A booking on account 21 against
account 18 is written to 1101. The booking on account 18 is written to `cp`.
SIa against SIb writes account 60 to 11100 and account 39 to `cp`.

When those columns do not resolve the pair, the previous rule still runs.
A `unitXX0X` role (third digit 0, as in `unit1108`) paired with `hd` in the
same center writes `XX0X + 10` on the unit and `cp` on the HD. `unit1101`
writes 1111 and 1110. `unit1108` writes 11118 and 11200. Both paths put
`cp` on the HD booking.

A `unitNNNN` role paired with Centrale still writes `NNNN` on Centrale and
the `sia` or `sib` post on the unit. Centrale SIa against Centrale SIb still
writes `siasib` on SIa and `cp` on SIb. Those two Centrale accounts are the
hard-coded IBANs. `cp` stays on the SIb booking.

The pair detector stays as it is: opposite amounts, same day or the next,
each statement names the other account’s IBAN. A matched pair is still
stored with `modification` 1. A hand row stays a hand row.

A cross-posting row in `dbo.mapping` is the same three columns plus
`counterparty_account_id`. Bank rows and cash rows leave that column
NULL. `account_links` and the cash write read only the NULL rows, so an
`xx1x` post does not become the account’s balance and a `Geldautomaat`
booking does not land on kruisposten. `hub/sql/mapping.sql` stores the
pair legs in the shape below. Bereken kruisposten does not SELECT those
rows.

`unit1108` against its HD, with `U` the unit account and `H` the HD
account:

| account_id | counterparty_account_id | category_id | written on |
|---|---|---|---|
| U | H | 11118 | the unit (`1108 + 10`) |
| H | U | 11200 | the HD (`cp`) |

`1102` through `1109` are the same shape: the unit account points at
11112–11119, and the HD account points back at 11200. The third digit and
the plus-ten are the contents of those rows.

The other three pair shapes are the same two rows.

| account_id | counterparty_account_id | category_id |
|---|---|---|
| Centrale SIb | Centrale SIa | 11200 (`cp`) |
| Centrale SIa | Centrale SIb | 11100 (`siasib`) |
| Centrale SIa | a SIa unit | that unit’s own post (`1xxxx`) |
| that SIa unit | Centrale SIa | 11126 (`sia`) |
| Centrale SIb | a SIb unit | that unit’s own post (`1xxxx`) |
| that SIb unit | Centrale SIb | 11125 (`sib`) |

Both rows present is the stored pair. The running function does not look
them up. A work-unit/HD pair that `assoc_category_id` resolves is written
from those columns. Any other pair is still computed from `category_role`.

The release set is the categories this routine writes: the `cp`,
`siasib`, `sia`, and `sib` rows, the `rc` local code named by an HD assoc
link, and the four-digit codes taken from `unitNNNN` and `unitXX0X`. A later run that does not assign the pair
returns an open booking on one of them to the remainder. A bank post
(counterparty NULL) stays out of that set.

---

## dbo.mapping

Bereken kruisposten keeps its procedure. A menu run still rewrites rows at
modification -1 and 0. A download still rewrites only -1. A matched pair
is still stored with modification 1. A hand row (2, 3, or 4) is still left
as it is. A later run still releases an open booking on a cross-posting
category back to the remainder. The pair detector stays as it is: opposite
amounts, same day or the next, each statement names the other account's
IBAN.

When `assoc_category_id` resolves a work-unit/HD pair, Bereken kruisposten
writes the `rc` local code on the work unit and `cp` on the HD. Otherwise
the two `category_id`s still come from `category_role`: `unitXX0X` means
the third digit is 0, and the unit leg is `XX0X + 10`. `cp`, `sia`, `sib`,
and `siasib` are further role strings. A row in `dbo.mapping` with a filled
counterparty stores the category itself. The function does not read that
row. The read it does make is above, and in `cross-postings.md`.

`dbo.mapping` holds the bank link and the cross-posting rows above.

| column | |
|---|---|
| `country_id` | bank link and pair leg |
| `account_id` | the account this row describes |
| `category_id` | the post. For a pair, the post stored for that leg. |
| `counterparty_account_id` | the other account of a pair. NULL on a bank, cash, or mirror link. |

A NULL counterparty is a bank, cash, or mirror link. `account_links`,
the Geldautomaat write, and the mirror rule read those rows.

A filled counterparty is one stored leg of Bereken kruisposten. The
function does not SELECT it. After the IBAN match it still chooses the
two `category_id`s from `category_role`.

`unit1108` against its HD is then two rows, not a code. `U` is the unit
account, `H` the HD account. 11118 is the category written on the unit.
11200 is the category written on the HD. Nothing in the row says `xx0x`
or `xx1x`.

| account_id | counterparty_account_id | category_id |
|---|---|---|
| U | H | 11118 |
| H | U | 11200 |
| Centrale SIb | Centrale SIa | 11200 |
| Centrale SIa | Centrale SIb | 11100 |
| Centrale SIa | a SIa unit | that unit's own post |
| that SIa unit | Centrale SIa | 11126 |
| Centrale SIb | a SIb unit | that unit's own post |
| that SIb unit | Centrale SIb | 11125 |

`1102` through `1109` are the same two rows: the unit account points at
11112–11119, and the HD account points back at 11200.

A primary key cannot include the NULL counterparty. `mapping_id` is the
key. One unique index covers the NULL rows on
`(country_id, account_id, category_id)`. Another covers the pair rows on
`(country_id, account_id, counterparty_account_id, category_id)`.

`hub/sql/mapping.sql` creates this table and fills it for countries 4 and
5. It does not change `category_role`. Bereken kruisposten still reads
those values for the two categories it writes. Do not run that script
after `dbo.mapping_banks` has been dropped: the script still copies from
that table.

---

## Which category_role values are cleared

Clear a role only when every pair that used it is resolved by
`assoc_category_id`. Until then the role stays. A work-unit/HD pair that
the assoc columns do not resolve still reads `unitNNNN`.

Two roles are cleared. They sit on the bank post and exist to carry four
digits. `unit1108` is the `xx0x` code, and the written category `1118` is
the `xx1x` code. `user1108` is the same four digits. The pair row stores
11118 itself, so the digits are no longer the source.

| role | where it sits |
|---|---|
| `unitNNNN` | the work-unit bank post, such as `unit1108` or `unit1111` |
| `userNNNN` | a bank post whose role is `user` plus four digits |

The result sheet still reads `unitNNNN` to tell a work-unit bank from role
`hd`. That read is separate from Bereken kruisposten.

Every other role stays. The pair row names the `category_id` that is
written. It does not replace the rule that role still carries.

| role | why it stays |
|---|---|
| `remainder` | the uncategorized booking |
| `balance`, `last_booked` | the matrix footers |
| `equity`, `profit` | Eigen vermogen and the result plug |
| `4000` | the HD result line 4995 |
| `bank`, `source`, `mirror` | which post reads an account, and which mirror does not |
| `cash` | the Geldautomaat post |
| `hd` | which bank is the Huishoudelijke Dienst |
| `rc`, `sia`, `sib` | Calculate opening balance zeros them into `cp` |
| `siasib` | that post keeps its year-end amount |
| `cp` | the post that receives the zeroed total |
