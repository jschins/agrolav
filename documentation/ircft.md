# iRCfT

iRCfT re-scores bookings after a term is added or removed. The term lists are
already saved. The pass matches bookings against those full lists and writes
back only the rows whose category or hit changed.

It is not Recalculate. Recalculate clears hits and scores the rows again from
scratch. iRCfT leaves hand-set categories and Excel rows where they are, and
it only walks each person’s latest booking year.

## When a pass runs

A right-click in the transactions view only saves the word and queues a pass.
Repeated right-clicks in that view do the same. The pass runs when a menu item
is clicked. The top bar then shows “background procedure running: please
wait…”, and the menu command runs only after the pass succeeds. A burst of
terms is one pass, not one pass per word. A term saved while that pass is
already walking is included in one follow-up before the menu click returns.

The terms editor runs iRCfT in the request and waits for it.

## Scope

A personal term rescores that person. Where terms are stored per account, it
rescores that account only. Several personal terms in one burst rescore every
account those terms touched.

A general term rescores every person in every center of the country. One
general term in a burst widens the whole burst to that scope.

For each person in scope, the walk loads that person’s latest year. Earlier
years are not touched.

## One pass

1. Load the general term list and, for a personal edit, that person’s list
   (per account, when the country stores terms that way).
2. Apply removals first, one removed term at a time.
3. Apply additions in one walk. The lists already contain every term saved
   before the walk, so one walk covers the whole burst.
4. Write the rows that changed, then rebuild that person’s category totals
   for the year.
5. On a queued pass, publish the change event after those writes. The client
   then reloads the matrix and the open category.

## Which rows move

| `modification` | meaning | iRCfT |
|---------------:|:--------|:------|
| -1 | not yet categorized | scored; then set to 0 |
| 0 | categorized, not edited by hand | scored |
| 2 | description edited by hand | scored; the description stays |
| 1 | category set by hand | category kept |
| 3 | category and description set by hand | category kept |

Excel rows are kept as they are.

On an **add**, a locked row (1 or 3) is skipped. On a **remove**, a locked row
keeps its category; if its hit is the deleted term, that hit is cleared and
the row is not scored again.

An unlocked row is scored on remove when its hit is the deleted term, or when
it has no hit. Other unlocked rows are left on remove.

## How one row is scored

The haystack is the booking’s name and description, lowercased. A term matches
a whole word. A word ends at a space, a dot, a dash, or other punctuation
(slash, comma, colon, apostrophe, asterisk, plus, brackets). A digit or an
underscore stays inside the word. `#` stands for zero or more letters, dots,
or asterisks inside one space-separated piece. It does not cross a space. A
dash or similar mark in that piece is skipped. `&&` means both phrases must
match.

The winning keyword is chosen in this order, highest first:

1. A personal term beats a general term.
2. An `&&` term beats a single phrase.
3. Activa/passiva beats lasten/baten. Activa and passiva are category codes
   below 3000. Lasten and baten are codes of 3000 or above.
4. The later category name, then the later term, wins.

Rule 4 is the last tie-break. It runs only when two matching terms are equal
on the three rules above. “Later” is dictionary order of the text, not the
time the term was saved. The category name is the label as stored, code
included (`1052 Spaarrekening`). The name that sorts later wins, so
`1110 Kruisposten` beats `1052 Spaarrekening`. When both matches sit in the
same category, the term text is compared the same way, after it has been
lowercased. `spaarrekening` beats `oranje`. The match that sorts last is
the one that sticks.

The row’s `hit` is `P:` plus the term, or `G:` plus the term.

If no keyword matches, the row goes to the remainder category and `hit` is
left empty.
