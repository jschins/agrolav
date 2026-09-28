# modification

`dbo.transaction_*.modification` records how a booking got its category and description.

## Present

The value is a pair of bits. Bit 1 is the category. Bit 2 is the description.

| value | meaning |
| --- | --- |
| -1 | Just downloaded from the bank. Not categorized. |
| 0 | Category came from the term calculation. |
| 1 | Category was set by hand, or by the cross-posting calculation. |
| 2 | Description was edited by hand. Category was not. |
| 3 | Both: hand or cross-posting category, and a hand-edited description. |

A term run does not replace a row at 1 or 3. It does replace the category of a row at 2, and it keeps the description bit, so that row stays at 2 when the description was edited. A matched cross-posting is written as 1, whatever the row held before. A categorization wipe sets every row in scope to -1 and the remainder category. Small expenses also writes 1.

Because 1 means both a hand category and a cross-posting, a wipe cannot put the hand categories back without also putting the cross-postings back.

## Intended

Drop the bit combination. One value, one source.

| value | meaning |
| --- | --- |
| -1 | Just downloaded from the bank. Not categorized. |
| 0 | Category came from the term calculation. |
| 1 | Category came from the cross-posting calculation. |
| 2 | Category or description was set by hand. |

A 2 is replaced only by a later hand edit, which writes 2 again. A term run, a cross-posting run, a fresh download of that same booking, and a categorization wipe leave a 2 in place, including its category and its description.

Terms write 0 only onto rows that are still -1. Cross-postings write 1 only onto rows that are not 2. After a wipe, the order is cross-postings, then terms. The hand rows are already 2 and stay where they are.
