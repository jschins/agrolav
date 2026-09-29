# Modification parameter

`dbo.transaction_*.modification` records how a booking got its category and description.


| value of the modification field | meaning                                                                                        |
| ------------------------------- | ---------------------------------------------------------------------------------------------- |
| -1                              | Just downloaded from the bank. Not categorized.                                                |
| 0                               | Category came from the term calculation.                                                       |
| 1                               | Category came from the cross-posting calculation.                                              |
| 2                               | 1. Category was set by hand or by the Smaller-amounts menu item 2. Description was set by hand |


A 2 is replaced only by a later hand edit, which writes 2 again. A term run, a cross-posting run, a fresh download of that same booking, and a categorization wipe leave a 2 in place, including its category and its description.

A hand left-click on a category writes that category onto the booking and sets `modification` to 2.

The Smaller-amounts (income/expenses) menu items affect only -1, and write 2.
The Terms and Cross-postings menu items affect both -1 and 0.
The Terms menu item writes 0, cross-postings 1.
Neither of the four menu items affects the hand-set rows, which are 2.

With the new rules

- the order of running terms and cross postings after a category wipe is immaterial
- hand-edited modifications on either description or category are not reset by a category wipe
- Included in the bank statement refresh functionality are the runs of both cross postings and terms on the freshly downloaded statements

In contrast to menu-ordered runs, the automatic runs after a fresh download of bank statements

- start out with crosspostings EXCLUSIVELY affecting -1, and
- finish with terms EXCLUSIVELY affecting -1.



# Amount splitting

Upon left-clicking an amount in the category-totals view, a new window opens, in which the user can split up that amount in several parts, each one with its own description and category.



