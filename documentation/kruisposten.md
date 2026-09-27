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
4. Both statements name the other account’s IBAN. A blank counterparty
   IBAN does not form a pair.
5. Each `transaction_id` is used in at most one pair.

IBAN comparison strips spaces and ignores case. The center of an account is
`sia` or `sib`, taken from the holder’s `dbo.center.username`
(`sia`, `center_sia`, anything ending in `_sia`, and the same for `sib`).

Money in stays positive and money out stays negative.

## Centrale SIa and Centrale SIb

`1020` Bank Centrale SIb is `NL46INGB0001726568`. `1010` Bank Centrale SIa is `NL84INGB0002801129`.

A pair between those two accounts writes SIb to local 1200, category 11200 (Kruisposten), and SIa to local 1100, category 11100. The two amounts must be opposite. Local 1100 and local 1200 both keep the statement sign, so the pair cancels on the balance sheet.

## Centrale SIa and a SIa unit

A pair between Centrale SIa and a `unitxxxx` account in center SIa writes SIa to local xxxx (category 1xxxx) and the unit to local 1126 (category 11126). `unit1108` writes SIa to category 11108.

## Centrale SIb and a SIb unit

A pair between Centrale SIb and a `unitxxxx` account in center SIb writes SIb to local xxxx (category 1xxxx) and the unit to local 1125 (category 11125).

## Unit and its sibling

`hd` is the role exactly. The sibling of a `unitxx0x` account is the `hd` account in the same center. The third digit of the unit role is 0, as in `unit1108`. The rule applies in SIa and in SIb. A center with no `hd` account has no sibling. A unit whose third digit is not 0 is left uncategorized by this rule.

The unit's bookings go to local xx1x, the same four digits with the third digit set to 1, which country 5 stores as category 1xx1x. The sibling's bookings go to local 1200, category 11200.

`unit1102` through `unit1109` write the unit to categories 11112 through 11119. `unit1108` writes the unit to 11118 and the sibling to 11200.

## Everything else

A pair that matches none of the rules above is not given a cross-posting
category.

A later run releases a statement that this run does not assign and whose
current category is one this routine writes or used to write (1099, 1100,
1200, 1125, 1126, 3125, 3126, or a four-digit code, including the earlier
HD-sibling codes 1112 through 1119). Release sets the remainder category
and `modification = -1`. A statement on any other category is left as it
is. A four-digit local code that is itself a live bank category in
`dbo.mapping_banks` is not treated as a cross-posting category on that
release.
