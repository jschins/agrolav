# Calculate opening balance

Bereken beginbalans writes `dbo.balance_opening` for the logged-in country and a chosen year Y. The menu item is Calculate opening balance. The year field opens with the calendar year after the present one. The entry point is `calculate_opening_balance` in `shared/shared/balance_values.py`.

Who sees the item is `dbo.menu_item` row `calculate-opening-balance`. The screen offers it when the country has a balance sheet.

## Rows for year Y

Y−1 must already have opening rows for this country. Otherwise the procedure stops with “No opening balance for Y−1”.

When Y has no rows, every opening row of Y−1 is copied (category, amount, and note). When Y already has rows, that copy is skipped and the calculated amounts below replace the stored ones, including live bank posts.

Afschrijving journals are rebuilt before the year-end amounts are read, so Y−1 includes the current depreciation rules.

## Amounts

The starting figure for each post is its year-end amount on the balance sheet of Y−1: opening of Y−1, plus that year’s journal, spaar-mirror, and bookings. A live bank post uses the account balance on that sheet.

Then three closings:

1. Each non-bank post keeps that year-end amount.
2. `category_role=balance` (2200) is set to zero. That year-end amount is added to Eigen vermogen. Eigen vermogen (`category_role=equity`, 2000) starts from its opening in Y−1, not from the amount already stored for Y, so a second run does not add 2200 again.
3. Every post with local code 1101–1119 and `category_role=rc` is set to zero. The sum of those year-end amounts is added to local 1200 (`category_role=cp`).

Verlies (`category_role=profit`) is not rewritten. On a new year it stays the copied amount. A live bank post is rewritten only when Y already had rows; on a new year it stays the copied amount.

The country must have an equity post and a balance-sheet post with `category_role=balance`. If any 1101–1119 `rc` post exists, a `category_role=cp` post must exist too (local 1200 when that row is present).
