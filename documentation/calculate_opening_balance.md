# Calculate opening balance

Bereken beginbalans writes `dbo.balance_opening` for the logged-in country and a chosen year Y. The menu item is Calculate opening balance. The year field opens with the calendar year after the present one. The entry point is `calculate_opening_balance` in `shared/shared/balance_values.py`.

Who sees the item is `dbo.menu_item` row `calculate-opening-balance`. The screen offers it when the country has a balance sheet.

## Rows for year Y

Y−1 must already have opening rows for this country. Otherwise the procedure stops with “No opening balance for Y−1”.

When Y has no rows, every opening row of Y−1 is copied (category and amount). When Y already has rows, that copy is skipped and the calculated amounts below replace the stored ones, including live bank posts.

Afschrijving journals are rebuilt before the year-end amounts are read, so Y−1 includes the current depreciation rules.

## Amounts

The starting figure for each post is its year-end amount on the balance sheet of Y−1: opening of Y−1, plus that year’s journal, spaar-mirror, and bookings. A live bank post uses the account balance on that sheet.

`category_role=profit` and `category_role=balance` are different posts. Profit is a 2000-range category (Resultaat on the balance sheet). Balance is a 3000-range category. Profit is taken from balance. Balance is the numerical sum of every local code 3000–4999 except the balance category itself.

Then three closings:

1. Each non-bank post keeps that year-end amount.
2. Profit is set to zero. The balance sum is added to Eigen vermogen. Eigen vermogen (`category_role=equity`, 2000) starts from its opening in Y−1, not from the amount already stored for Y, so a second run does not add the result again.
3. Every post with local code 1101–1119 and `category_role=rc` is set to zero. The sum of those year-end amounts is added to local 1200 (`category_role=cp`).

A live bank post is rewritten only when Y already had rows; on a new year it stays the copied amount.

The country must have an equity post, a 2000-range post with `category_role=profit`, and a 3000-range post with `category_role=balance`. If any 1101–1119 `rc` post exists, a `category_role=cp` post must exist too (local 1200 when that row is present).
