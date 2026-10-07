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





## Centrale SIa and Centrale SIb

`1020` Bank Centrale SIb is `NL46INGB0001726568`. `1010` Bank Centrale SIa is `NL84INGB0002801129`.

A pair between those two accounts writes SIb to the category whose `category_role` is `cp` (Kruisposten, local 1200) and SIa to the category whose `category_role` is `siasib` (local 1100). The two amounts must be opposite. Both roles keep the statement sign, so the pair cancels on the balance sheet. `siasib` is not rekening courant: Calculate opening balance leaves it at its year-end amount.





## Centrale SIa and a SIa unit

A pair between Centrale SIa and a `unitxxxx` account in center SIa writes SIa to local xxxx (category 1xxxx) and the unit to the category whose `category_role` is `sia`. `unit1108` writes SIa to category 11108.





## Centrale SIb and a SIb unit

A pair between Centrale SIb and a `unitxxxx` account in center SIb writes SIb to local xxxx (category 1xxxx) and the unit to the category whose `category_role` is `sib`.

The `cp`, `siasib`, `sia` and `sib` rows are read from `dbo.dim_category` on every run. `sia` and `sib` count as rekening courant: Calculate opening balance sets them to zero and adds them to `cp`, and bookings on them keep the statement sign. A country without a row for a role leaves that leg uncategorized.





## Unit and its sibling

`hd` is the role exactly. The sibling of a `unitxx0x` account is the `hd` account in the same center. The third digit of the unit role is 0, as in `unit1108`. The rule applies in SIa and in SIb. A center with no `hd` account has no sibling. A unit whose third digit is not 0 is left uncategorized by this rule.

The unit's bookings go to local xx1x, the same four digits plus 10, which country 5 stores as category 1xx1x. The sibling's bookings go to the `cp` row. That sum only chooses the local code. A category is rc when `dbo.dim_category.category_role` is `rc`, and the opening balance and the statement sign read that role.

`unit1102` through `unit1109` write the unit to categories 11112 through 11119. `unit1108` writes the unit to 11118 and the sibling to the `cp` row.





## Pairs that match no cross-posting rule

A pair that matches none of the rules above is not given a cross-posting
category.

A later run releases a statement that this run does not assign and whose
current category is one this routine writes (the `cp`, `siasib`, `sia` and
`sib` rows, or a four-digit code, including the HD-sibling codes 1112
through 1119) and whose `modification` is -1 or 0. Release sets the remainder category
and `modification = -1`. A hand row (`modification` 2) is left as it
is, as is a statement on any other category. A four-digit local code that is itself a live bank category in
`dbo.mapping` (counterparty empty) is not treated as a cross-posting category on that
release.

## How dbo.mapping was read previously

`apply_cross_postings` reads `dbo.mapping` only where `counterparty_account_id` is NULL. A filled counterparty is a stored pair leg. That row is not the lookup that chooses the two categories.

The two written category ids still come from `category_role`. `_user_roles` joins the NULL rows to `dbo.dim_category` and keeps `hd`, `unitNNNN`, `userNNNN`, `source`, and `mirror` for each `account_id`. `pair_local_codes` uses those roles. A `unitXX0X` against `hd` in the same center writes local `XX0X + 10` on the unit and the `cp` post on the HD. A `unitNNNN` against Centrale writes `NNNN` on Centrale and `sia` or `sib` on the unit. Centrale SIa against Centrale SIb writes `siasib` and `cp`. The `cp`, `siasib`, `sia`, and `sib` category ids come from `_pair_legs`, which reads `category_role` on `dbo.dim_category`, not a pair row in `dbo.mapping`.

`_account_categories` loads the same NULL rows as `account_id` to `category_id`. When one account has two such rows, category ids 11010, 11019, 11020, and 11021 win; otherwise the row order decides. That map is the set of live bank posts. `managed_category_ids` leaves a four-digit code out of the release set when that code's stored category is in the set, so a later run does not move a bank post back to the remainder.

Geldautomaat runs first, inside the same call. `cash_category_accounts` finds the HD account from a NULL row whose role is `hd`, and the cash post as the other NULL row on that account whose role is `cash` or empty. Country 5 falls back to category ids 11133–11139 when that query returns nothing. The cash write stores `modification` 1, and the pair pass leaves that booking alone.

New rule set (my formulation)

From all bookings between registered accounts within the country:

- for all transactions between Centrale SIa and Centrale SIb: write those of Centrale Sib to 11200 kruisposten, and those of Centrale Sia to 11100
- for all transactions between Centrale SIa and a unitxxxx belonging to SIa: write those of Centrale SIa to 1xxxx, and those of the unit to 11126
- for all transactions between Centrale SIb and a unitxxxx belonging to SIb: write those of Centrale SIb to 1xxxx, and those of the unit to 11125
- for all transactions between a unitxx0x and its sibling: write those of the unit to 1xx1x, and those of its sibling to 11200

In all cases: explicitly check that all amounts are always written in sign-opposed pairs



## How dbo.dim_category is read now (in the context of the cross-postings calculation)

`apply_cross_postings` loads every `dbo.dim_category` row of the country when the columns `account_id` and `assoc_cat_id` exist. The columns it keeps are `category_id`, `local_code`, `category_role`, `account_id`, and `assoc_cat_id`. 

`account_id` is the bank of that category. A booking’s account is matched to the row with that `account_id` whose role is `hd`, `unit`, `source`, or `bank`. A `cash`, `rc`, `cp`, or `mirror` row on the same account is not that bank. Where `hd` and another role share the account, `hd` is the bank.

`assoc_cat_id` names one other category. Four reads use these columns.

# Application of the cross-postings rules

1. All 'Geldautomaat' bookings
- all hd bookings using bank_type='Geldautomaat' are categorized as 
cash[category_id] = 11134
for which 
cash[account_id] = hd[account_id] = 48
e.g. 
11029	5	1029	Bank HD Den Eker	hd	  Activa/Vlottende activa/Bank  HD	2	48	11025
11134	5	1134	kas HD Den Eker	  cash	Activa/Vlottende activa/Kas   HD	5	48	11029


2. All transactions between two sources [instudo: between Centrale SIa and SIb]
e.g.
11010	5	1010	Bank Centrale SIa	source	Activa/Vlottende activa/Bank SIa	2	60	11126
11020	5	1020	Bank Centrale SIb	source	Activa/Vlottende activa/Bank SIb	2	39	11125
11100	5	1100	r/c SIa SIb	      siasib	Activa/Vlottende activa/Rekening	2	60	11020

- the bookings on Centrale SIa are categorized as 
siasib[category_id] = 11100
for which 
siasib[account_id] = party_source[account_id] = 60
siasib[assoc_cat_id] = counterparty_source[category_id] = 11020
- the bookings on Centrale SIb are categorized as 11200 Kruisposten

3. All transactions between a source and its unit
e.g. 
11025	5	1025	Bank Den Eker	        unit	  Activa/Vlottende activa/Bank SIb	2	40	11020
11104	5	1104	r/c Den Eker	        rc	    Activa/Vlottende activa/Rekening	2	40	11020
11125	5	1125	Bijdrage centrale SIb	sib	    Activa/Vlottende activa/Rekening	2	39	11020
11126	5	1126	Bijdrage centrale SIa	sia	    Activa/Vlottende activa/Rekening	2	60	11010
11020	5	1020	Bank Centrale SIb	    source	Activa/Vlottende activa/Bank SIb	2	39	11125

- the bookings of Bank Den Eker are categorized as
sib[category_id] = source[assoc_cat_id]
- the bookings of Centrale SIb are categorized as
rc[category_id] = 11104
for which
rc[assoc_cat_id] = unit[assoc_cat_id] = 11020
The unit and the source share a center.


4. All transactions between a unit and its hd-sibling
e.g.
11025	5	1025	Bank Den Eker	      unit	Activa/Vlottende activa/Bank SIb	2	40	11020
11029	5	1029	Bank HD Den Eker	  hd	  Activa/Vlottende activa/Bank HD	  2	48	11025
11114	5	1114	r/c HD Den Eker	    rc	  Activa/Vlottende activa/Rekening	2	48	11025

- the bookings of Bank Den Eker are categorized as
rc[category_id]  = 11114
for which
rc[assoc_cat_id] = unit[category_id] = 11025
rc[account_id] = hd[account_id]
- the bookings of Bank HD Den Eker are categorized as 11200 Kruisposten




# Cursor's proposal

`dbo.cp_rules` holds one row per booking. The category ids stay in `dbo.dim_category`. `tie_booking` equals `tie_other`: that field on this booking’s bank equals that field on the other bank. `write_as = other.assoc_cat_id` is the category that field names on the other bank. `write_as = role` finds the `dim_category` row with that `category_role`. `role_account` is `booking` or `other`: the row’s `account_id` is this bank’s or the other’s. `role_assoc` is the field that row’s `assoc_cat_id` must equal. `booking_role = unit` means role `unit`. The script is `hub/sql/cp_rules.sql`. Bereken kruisposten reads this table. A missing table runs no rule.

<div style="overflow-x: auto; width: 100%;">

<table style="border-collapse: collapse; min-width: 1680px; white-space: nowrap; font-size: 14px;">
<thead>
<tr>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">rule_name</th>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">leg</th>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">booking_role</th>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">other_role</th>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">same_center</th>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">tie_booking</th>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">tie_other</th>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">write_as</th>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">category_role</th>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">role_account</th>
<th style="text-align: left; padding: 6px 14px; border-bottom: 1px solid #ccc;">role_assoc</th>
</tr>
</thead>
<tbody>
<tr>
<td style="padding: 6px 14px;">geldautomaat</td>
<td style="padding: 6px 14px;">1</td>
<td style="padding: 6px 14px;">hd</td>
<td style="padding: 6px 14px;"></td>
<td style="padding: 6px 14px;">0</td>
<td style="padding: 6px 14px;"></td>
<td style="padding: 6px 14px;"></td>
<td style="padding: 6px 14px;">role</td>
<td style="padding: 6px 14px;">cash</td>
<td style="padding: 6px 14px;">booking</td>
<td style="padding: 6px 14px;"></td>
</tr>
<tr>
<td style="padding: 6px 14px;">unit-hd</td>
<td style="padding: 6px 14px;">1</td>
<td style="padding: 6px 14px;">unit</td>
<td style="padding: 6px 14px;">hd</td>
<td style="padding: 6px 14px;">1</td>
<td style="padding: 6px 14px;">category_id</td>
<td style="padding: 6px 14px;">assoc_cat_id</td>
<td style="padding: 6px 14px;">role</td>
<td style="padding: 6px 14px;">rc</td>
<td style="padding: 6px 14px;">other</td>
<td style="padding: 6px 14px;">booking.category_id</td>
</tr>
<tr>
<td style="padding: 6px 14px;">source-unit</td>
<td style="padding: 6px 14px;">1</td>
<td style="padding: 6px 14px;">unit</td>
<td style="padding: 6px 14px;">source</td>
<td style="padding: 6px 14px;">1</td>
<td style="padding: 6px 14px;">assoc_cat_id</td>
<td style="padding: 6px 14px;">category_id</td>
<td style="padding: 6px 14px;">other.assoc_cat_id</td>
<td style="padding: 6px 14px;"></td>
<td style="padding: 6px 14px;"></td>
<td style="padding: 6px 14px;"></td>
</tr>
<tr>
<td style="padding: 6px 14px;">source-unit</td>
<td style="padding: 6px 14px;">2</td>
<td style="padding: 6px 14px;">source</td>
<td style="padding: 6px 14px;">unit</td>
<td style="padding: 6px 14px;">1</td>
<td style="padding: 6px 14px;">category_id</td>
<td style="padding: 6px 14px;">assoc_cat_id</td>
<td style="padding: 6px 14px;">role</td>
<td style="padding: 6px 14px;">rc</td>
<td style="padding: 6px 14px;">other</td>
<td style="padding: 6px 14px;">other.assoc_cat_id</td>
</tr>
<tr>
<td style="padding: 6px 14px;">source-source</td>
<td style="padding: 6px 14px;">1</td>
<td style="padding: 6px 14px;">source</td>
<td style="padding: 6px 14px;">source</td>
<td style="padding: 6px 14px;">0</td>
<td style="padding: 6px 14px;"></td>
<td style="padding: 6px 14px;"></td>
<td style="padding: 6px 14px;">role</td>
<td style="padding: 6px 14px;">siasib</td>
<td style="padding: 6px 14px;">booking</td>
<td style="padding: 6px 14px;">other.category_id</td>
</tr>
</tbody>
</table>

</div>

A leg the matched rule does not write is `cp`. `cp` is not a row in the table. A transfer that fits no rule stays as it is.

A work unit and its HD share a center. The HD row’s assoc is the work-unit bank. The `rc` row on the HD account whose assoc is that same work-unit bank is written on the work-unit booking. The HD booking is `cp`. Account 21 against account 44 is written to 1111. Account 44 is `cp`. Account 40 against account 48 is written to 11114. Account 48 is `cp`.

A work unit and its centrale share a center. The unit row’s assoc is the source category, and that source row’s assoc is the category written on the unit booking. The source booking is written to the `rc` row on the unit account whose assoc is that same source category. When that `rc` is absent, the source booking is written to `cp`. Account 21 against account 18 is written to 1101, because 1051 points at 1101. Account 18 is written to `cp` when account 21 has no `rc` pointing at 1051. Account 40 against account 39 is written to 11125, because 11020 points at 11125. Account 39 is written to 11104.

SIa against SIb: the `siasib` row’s account is written to that category. The other source is `cp`. 11100 has account 60 and points at 11020, so account 60 is written to 11100 and account 39 is `cp`.

Geldautomaat uses the other category on the HD account whose role is `cash` or empty. 11134 shares account 48 with 11029. 1057 shares account 44 with 1053. The cash write stores `modification` 1, and the pair pass leaves that booking alone.

