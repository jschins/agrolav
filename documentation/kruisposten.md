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

Every account in the country that has an IBAN in `dbo.account` is read.
Two statements form a pair when all of the following hold:

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

## Centrale SIb

`1020` Bank Centrale SIb is `NL46INGB0001726568`. Every paired booking on that account is local 1200, category 11200 (Kruisposten).

The other leg is written only in these cases:

- Centrale SIa (`NL84INGB0002801129`) goes to local 1100, category 11100.
- A `unitxxxx` account in center SIb goes to local 3125, category 13125.

Money in stays positive and money out stays negative.

## Centrale SIa and a SIa unit

A pair between Centrale SIa and a `unitxxxx` account in center SIa writes SIa to local 1200 (category 11200) and the unit to local 3126 (category 13126).

## Unit and its HD sibling

`hd` is the role exactly. The sibling of a `unitxxxx` account is the `hd` account in the same center. The rule applies in SIa and in SIb. A center with no `hd` account, such as Aenstal, has no sibling.

The unit's bookings go to local 1200 (category 11200). The sibling's bookings go to local xxxx, which country 5 stores as category 1xxxx. `unit1025` against its HD sibling writes the sibling to category 11025.

A four-digit local code that is itself a live bank category in
`dbo.mapping_banks` is not treated as a cross-posting category on a later
release.

## Everything else

A pair that matches none of the rules above is not given a cross-posting
category.

A later run releases a statement that this run does not assign and whose
current category is one this routine writes (1099, 1100, 1200, 3125, 3126,
or a four-digit code). Release sets the remainder category and
`modification = -1`. A statement on any other category is left as it is.
