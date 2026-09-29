# Modification parameter

`dbo.transaction_*.modification` records how a booking got its category and description.


| value of the modification field | meaning                                                                                        |
| ------------------------------- | ---------------------------------------------------------------------------------------------- |
| -1                              | Just downloaded from the bank. Not categorized.                                                |
| 0                               | Category came from the term calculation.                                                       |
| 1                               | Category came from the cross-posting calculation.                                              |
| 2                               | Category was set by hand or by the Smaller-amounts menu item. The description stays as it was. |
| 3                               | Description was set by hand.                                                                  |
| 4                               | Both 2 and 3.                                                                                 |


A later hand edit keeps the flag it does not touch: a description edit on a 2 writes 4, and a category edit on a 3 writes 4. A term run, a cross-posting run, a fresh download of that same booking, and a categorization wipe leave 2, 3, and 4 in place, including the category and the description.

A hand left-click on a category writes that category onto the booking and sets `modification` to 2, or to 4 when the description was already hand-set. A hand left-click on a description sets `modification` to 3, or to 4 when the category was already hand-set.

The Smaller-amounts (income/expenses) menu items affect only -1, and write 2.
The Terms and Cross-postings menu items affect both -1 and 0.
The Terms menu item writes 0, cross-postings 1.
Neither of the four menu items affects the hand-set rows, which are 2, 3, and 4.

With the new rules

- the order of running terms and cross postings after a category wipe is immaterial
- hand-edited modifications on either description or category (2, 3, and 4) are not reset by a category wipe
- Included in the bank statement refresh functionality are the runs of both cross postings and terms on the freshly downloaded statements

In contrast to menu-ordered runs, the automatic runs after a fresh download of bank statements

- start out with crosspostings EXCLUSIVELY affecting -1, and
- finish with terms EXCLUSIVELY affecting -1.
<!-- {en:modification[5],parameter[5],booking,bookings,category,categories,description,descriptions,hand,left-click,term,terms,cross-posting,cross-postings,wipe,smaller,amount,amounts,download,bank} -->
<!-- {nl:modificatie[5],parameter[5],boeking,boekingen,categorie,categorieën,omschrijving,omschrijvingen,hand,linksklik,term,termen,kruispost,kruisposten,wissen,kleiner,bedrag,bedragen,downloaden,bank} -->

# Amount splitting

Upon left-clicking an amount in the category-totals view, a new window opens, in which the user can split up that amount in several parts, each one with its own description and category.
<!-- {en:amount[5],splitting[5],split,splits,left-click,window,part,parts,description,descriptions,category,categories} -->
<!-- {nl:bedrag[5],splitsen[5],splitsing,splitsingen,linksklik,venster,deel,delen,omschrijving,omschrijvingen,categorie,categorieën} -->



