# Cross postings

'Bereken kruisposten' (calculate cross postings) writes categories on internal transfers for the logged-in country when `dbo.country.has_balance` is set.
The entry point is `apply_cross_postings` in `hub/app/cross_postings.py`.
The menu calls `POST /api/cross-postings`.
Uitlezen bankafschriften, and a one-person or year-to-date fetch, run the same pairing after the download, and only on pairs that include a statement just stored. On that run a row is written only when its `modification` is -1, so the other leg is written only when that leg is also -1. A row at 0 is left as it is. Statements outside those pairs stay as they are. The fetch then runs terms, and those terms also rewrite only rows still at `modification` -1. A menu run of Bereken kruisposten still writes -1 and 0. A hand row (`modification` 2) keeps its category and its description.

Balance countries (`dbo.country.has_balance`) are taken in `country_id`
order. The first stores the local code. Each later one adds 10000, so
country 5 stores `category_id = local_code + 10000` and the next balance
country stores `local_code + 20000`. A country without `has_balance` does
not take a block. A `dbo.dim_category` row for that local code supplies
the id when one exists. Otherwise the formula is used. A matched row whose `modification` is -1 or 0 is
written with `modification = 1`. A row at 2 is not written.

<!-- {en:cross-postings[5],pair,transfer,category} -->
<!-- {nl:kruisposten[5],paar,overboeking,categorie} -->

## Which statements form a pair

Every account in the country that has an IBAN in `dbo.account` is read.
Two statements form a pair when all of the following hold:

1. They sit on different accounts.
2. `booked_on` is the same calendar day, or the two dates differ by one day. The same day is taken when both exist.
3. The amounts are opposite to the cent.
4. Both statements name the other account’s IBAN. A blank counterparty
  IBAN does not form a pair.
5. Each `transaction_id` is used in at most one pair.

IBAN comparison strips spaces and ignores case. The center of an account is
`sia` or `sib`, taken from the holder’s `dbo.center.username`
(`sia`, `center_sia`, anything ending in `_sia`, and the same for `sib`).

Money in stays positive and money out stays negative.

<!-- {en:statements[5],pair[5],iban,amount,date} -->
<!-- {nl:afschriften[5],paar[5],iban,bedrag,datum} -->

## Centrale SIa and Centrale SIb

`1020` Bank Centrale SIb is `NL46INGB0001726568`. `1010` Bank Centrale SIa is `NL84INGB0002801129`.

A pair between those two accounts writes SIb to the category whose `category_role` is `cp` (Kruisposten, local 1200) and SIa to the category whose `category_role` is `siasib` (local 1100). The two amounts must be opposite. Both roles keep the statement sign, so the pair cancels on the balance sheet. `siasib` is not rekening courant: Calculate opening balance leaves it at its year-end amount.

<!-- {en:centrale[5],sia[5],sib[5],pair,accounts} -->
<!-- {nl:centrale[5],sia[5],sib[5],paar,rekeningen} -->

## Centrale SIa and a SIa unit

A pair between Centrale SIa and a `unitxxxx` account in center SIa writes SIa to local xxxx (category 1xxxx) and the unit to the category whose `category_role` is `sia`. `unit1108` writes SIa to category 11108.

<!-- {en:centrale[5],sia[5],unit[5],pair,center} -->
<!-- {nl:centrale[5],sia[5],eenheid[5],paar,centrum} -->

## Centrale SIb and a SIb unit

A pair between Centrale SIb and a `unitxxxx` account in center SIb writes SIb to local xxxx (category 1xxxx) and the unit to the category whose `category_role` is `sib`.

The `cp`, `siasib`, `sia` and `sib` rows are read from `dbo.dim_category` on every run. `sia` and `sib` count as rekening courant: Calculate opening balance sets them to zero and adds them to `cp`, and bookings on them keep the statement sign. A country without a row for a role leaves that leg uncategorized.

<!-- {en:centrale[5],sib[5],unit[5],pair,center} -->
<!-- {nl:centrale[5],sib[5],eenheid[5],paar,centrum} -->

## Unit and its sibling

`hd` is the role exactly. The sibling of a `unitxx0x` account is the `hd` account in the same center. The third digit of the unit role is 0, as in `unit1108`. The rule applies in SIa and in SIb. A center with no `hd` account has no sibling. A unit whose third digit is not 0 is left uncategorized by this rule.

The unit's bookings go to local xx1x, the same four digits plus 10, which country 5 stores as category 1xx1x. The sibling's bookings go to the `cp` row. That sum only chooses the local code. A category is rc when `dbo.dim_category.category_role` is `rc`, and the opening balance and the statement sign read that role.

`unit1102` through `unit1109` write the unit to categories 11112 through 11119. `unit1108` writes the unit to 11118 and the sibling to the `cp` row.

<!-- {en:unit[5],sibling[5],pair,center,account} -->
<!-- {nl:eenheid[5],zuster[5],paar,centrum,rekening} -->

## Pairs that match no cross-posting rule

A pair that matches none of the rules above is not given a cross-posting
category.

A later run releases a statement that this run does not assign and whose
current category is one this routine writes (the `cp`, `siasib`, `sia` and
`sib` rows, or a four-digit code, including the HD-sibling codes 1112
through 1119) and whose `modification` is -1 or 0. Release sets the remainder category
and `modification = -1`. A hand row (`modification` 2) is left as it
is, as is a statement on any other category. A four-digit local code that is itself a live bank category in
`dbo.mapping_banks` is not treated as a cross-posting category on that
release.





New rule set (my formulation)

From all bookings between registered accounts within the country:

+ for all transactions between Centrale SIa and Centrale SIb: write those of Centrale Sib to 11200 kruisposten, and those of Centrale Sia to 11100

+ for all transactions between Centrale SIa and a unitxxxx belonging to SIa: write those of Centrale SIa to 1xxxx, and those of the unit to 11126

+ for all transactions between Centrale SIb and a unitxxxx belonging to SIb: write those of Centrale SIb to 1xxxx, and those of the unit to 11125

+ for all transactions between a unitxx0x and its sibling: write those of the unit to 1xx1x, and those of its sibling to 11200

In all cases: explicitly check that all amounts are always written in sign-opposed pairs

<!-- {en:pairs[5],match[5],cross-posting[5],rule[5],category} -->
<!-- {nl:paren[5],overeenkomst[5],kruispost[5],regel[5],categorie} -->
