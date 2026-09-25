# Kruisposten

Bereken kruisposten writes categories on internal transfers for the logged-in country when ``dbo.country.has_balance`` is set.
The entry point is `apply_cross_postings` in `hub/app/cross_postings.py`.
The menu calls `POST /api/cross-postings`.
Uitlezen bankafschriften runs the same pairing after the download, and only on pairs that include a statement just stored. The other leg of that pair is written as well. Statements outside those pairs stay as they are. It then categorizes every remaining statement with `modification` -1. Rows already at 0, 1, 2, or 3 are left as they are.

Balance countries (`dbo.country.has_balance`) are taken in `country_id`
order. The first stores the local code. Each later one adds 10000, so
country 5 stores `category_id = local_code + 10000` and the next balance
country stores `local_code + 20000`. A country without `has_balance` does
not take a block. A `dbo.dim_category` row for that local code supplies
the id when one exists. Otherwise the formula is used. A matched row is
written with `modification = 1`.

## Which rows are considered

A country bank is an account whose `dim_category.category_role` is `hd`, starts with
`unit`, `source`, or `funds`, or whose role is `user` or `unit` plus four
digits (`user1108`, `unit1108`). The two source accounts and their
spaarrekening categories are included as well, even when the role does not
match: `NL46INGB0001726568` (category 11020) and category 11021, and
`NL84INGB0002801129` (category 11010) and category 11019.

Only statements on those accounts are read. Two statements form a pair when
all of the following hold:

1. They sit on different accounts.
2. `booked_on` is the same calendar day.
3. The amounts are opposite to the cent.
4. The statement that opens the pair names the other account’s IBAN.
   The counterpart still counts when its own counterparty IBAN is empty.
   When that IBAN is a registered account, it must be the opening account.
5. Each `transaction_id` is used in at most one pair.

IBAN comparison strips spaces and ignores case. The center of an account is
`sia` or `sib`, taken from the holder’s `dbo.center.username`
(`sia`, `center_sia`, anything ending in `_sia`, and the same for `sib`).

## SIa and SIb

`1010` Bank Centrale SIa (`NL84INGB0002801129`) and `1020` Bank Centrale SIb (`NL46INGB0001726568`) are unchanged.

A transfer between these two accounts is two statements, and both are kept.
The statement on 1010 is local 1099 (category 11099). The statement on 1020 is local 1100 (category 11100). Money in stays positive and money out stays negative.

SIb paid SIa 6.000 (Salarissen, 25-06-2026) and 2.730 (Heijer Bouw, 21-04-2026):

- 1099 shows +6.000 and +2.730, received on SIa
- 1100 shows −6.000 and −2.730, paid from SIb

SIa paid SIb 5.652 and 1.276 (Donatus, 04-02-2026):

- 1100 shows +5.652 and +1.276, received on SIb
- 1099 shows −5.652 and −1.276, paid from SIa

1099 then totals +1.802. 1100 totals −1.802.

The balance sheet prints those same totals. `booking_signed_amount` returns
`+X` for 1099 and 1100. Other activa codes in 1000–1999 still return `−X`.

## Source and unitxxxx

A `source` account and a `unit` account with four digits, both in the same center, are booked on those four digits. Both statements take that one category. Country 5 stores `unit1108` as category 11108. A `unit1108` account in the other center is not this rule.

## hd and unitxxxx

An `hd` account and a `unit` account with four digits are booked on local 1200, whether or not they share a center. Country 5 stores that as category 11200. Both statements take that one category.

A four-digit local code that is itself a live bank category in
`dbo.mapping_banks` is not treated as a cross-posting category on a later
release.

## Spaarrekening

This rule runs when the pair is not SIa↔SIb, not source with `unitxxxx`, and not `hd` with `unitxxxx`.

`NL46INGB0001726568` against the account mapped to category 11021, or
`NL84INGB0002801129` against the account mapped to category 11019, in
either direction, is local 1200. Both statements are written to category
11200 (Kruisposten). The category id is the `mapping_banks` category of
the account, not the category currently stored on the statement.

## Everything else

A pair that matches none of the rules above is not given a cross-posting
category.

A later run releases a statement that this run does not assign and whose
current category is one this routine writes (1099, 1100, 1200, or a
four-digit code). Release sets the remainder category and
`modification = -1`. A statement on any other category is left as it is.
