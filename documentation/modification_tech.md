# Modification parameter

`dbo.transaction_*.modification` records how a booking got its category and description.


| value of the modification field | meaning                                                                                        |
| ------------------------------- | ---------------------------------------------------------------------------------------------- |
| -1                              | Just downloaded from the bank. Not categorized.                                                |
| 0                               | Category came from the term calculation.                                                       |
| 1                               | Category came from the cross-posting calculation or from the Geldautomaat cash write.         |
| 2                               | Category was set by hand or by the Smaller-amounts menu item. The description stays as it was. |
| 3                               | Description was set by hand.                                                                  |
| 4                               | Both 2 and 3.                                                                                 |


A later hand edit keeps the flag it does not touch: a description edit on a 2 writes 4, and a category edit on a 3 writes 4. A term run, a cross-posting run, a fresh download of that same booking, and the wipe that keeps terms and statements leave 2, 3, and 4 in place, including the category and the description. Clear categories, cross-postings, terms, and statements sets every row in scope to `modification` -1 and the remainder category.

A hand left-click on a category writes that category onto the booking and sets `modification` to 2, or to 4 when the description was already hand-set. A hand left-click on a description sets `modification` to 3, or to 4 when the category was already hand-set.

The Smaller-amounts (income/expenses) menu items affect only -1, and write 2.
The Terms and Cross-postings menu items affect both -1 and 0.
The Terms menu item writes 0. Bereken kruisposten writes 1.
Neither of the four menu items affects the hand-set rows, which are 2, 3, and 4.

The Geldautomaat cash write also stores 1. It runs first inside Bereken kruisposten, both from the menu and after a fresh download, and it runs first again at Recalculate and at a term save. It rewrites a Geldautomaat row that is at -1, 0, or 1. A row at 2, 3, or 4 keeps its category.

With the new rules

- the order of running terms and cross postings after a category wipe is immaterial
- hand-edited modifications on either description or category (2, 3, and 4) are not reset by the wipe that keeps terms and statements. Clear categories, cross-postings, terms, and statements sets every row to -1 and the remainder category
- Included in the bank statement refresh are the Geldautomaat cash write, cross-postings, and terms, each on the freshly downloaded statements

In contrast to menu-ordered runs, the automatic runs after a fresh download of bank statements

- start with the Geldautomaat cash write on the statements just stored, writing 1,
- then run cross-postings exclusively on rows still at -1, writing 1, and
- finish with terms exclusively on rows still at -1, writing 0.





