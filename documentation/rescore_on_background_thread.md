# Rescore after right-click edits

Adding a term from the right-click menu in the transactions view only saves
the word. Repeated right-clicks in that same view do the same. They do not
start a rescore, and they do not wait for one.

The queued pass runs when a menu item is clicked, and when you leave the
transaction list for the matrix. That click may wait until the pass finishes.
The hub then publishes its usual change event, and the list and the matrix
reload. Until then, rows other than the one you just assigned still show
their old category. The right-click menu opens from settings already loaded
on the page.

A burst of terms becomes one pass, not one pass per word. Each pass matches
every unlocked booking against the full term lists, so one walk applies every
term saved before the walk started. A term saved while that walk is already
in progress is included in one follow-up before the menu click returns.
Locked rows (a category you picked by hand) and Excel rows stay as they are.

Scope of a pass: a personal term rescores that person (and, where terms are
per account, that account). Several personal terms in one burst rescore every
account those terms touched. A general term rescores every person in every
center of the country. One general term in a burst widens the whole burst to
that scope.

The terms editor and "Recalculate" still run their own rescore in the request
and wait for it.
