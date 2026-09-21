# Rescore on a background thread

Adding a term from the right-click menu in the transactions view saves the
word and returns at once. The hub rescores bookings on a background thread.
The screen does not wait for that pass.

What you see: the menu closes immediately. The row you assigned to another
category leaves the list immediately. A further right-click opens the menu
from the settings already loaded on the page, so it does not call the hub
again while a rescore is running. You can add the next term during that pass. When the pass finishes, the
hub publishes its usual change event. The open list and the matrix reload
themselves from that event, about a second later. Until then, rows other than
the one you just assigned still show their old category.

A burst of terms becomes one pass, not one pass per word. Each pass matches
every unlocked booking against the full term lists, so one walk applies every
term that was saved before the walk started. A term saved while a walk is
already in progress is included in one follow-up pass. Locked rows (a category
you picked by hand) and Excel rows stay as they are.

The term save does not take the calculation lock, and neither does loading the
term menu. The rescore does take that lock, so it still does not overlap a
manual recalculate. The settings read used by the menu stays available while
the lock is held.

Scope of a pass: a personal term rescores that person (and, where terms are
per account, that account). Several personal terms in one burst rescore every
account those terms touched. A general term rescores every person in every
center of the country. One general term in a burst widens the whole burst to
that scope.

The terms editor and "Recalculate" still run their rescore in the request and
wait for it. Only the right-click add takes the background path.
