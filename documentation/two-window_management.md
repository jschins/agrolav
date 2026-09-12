# Two-window management

The client frontend (matrix) and the balance sheet are two top-level browser
windows. Three rules:

1. Never open a second balance window.
2. Close the balance window automatically on logout from the client.
3. Escape in the balance window transfers focus to the client window.

The shape is right. The weak spots are browser-window facts, not missing
product rules.

## 1. Never a second balance window

`openBalanceSheetWindow` (client `App.tsx`) keeps a module handle and opens
with the fixed name `agrolavBalance`. A second click reuses that handle (and
retargets the URL if the country slug changed) instead of calling
`window.open` again.

The probe/pong is for leftovers: a sheet from an older deploy that no longer
talks to this opener is closed after a few unanswered `agrolav-probe`
messages so the next open can own it. The sheet answers `agrolav-probe` with
`agrolav-pong` when it still has `window.opener`.

That is as singleton as a browser allows.

- A client reload drops the JS handle, but the named window usually still
  receives the next `window.open(..., "agrolavBalance")`.
- Two client tabs typically share that same name.
- Two different browsers, or a sheet opened from a bookmark, can still
  produce a second window. That cannot be stopped.

## 2. Close on logout

`onLogout` calls `closeBalanceSheetWindow()` before `POST /api/logout`: post
`agrolav-close`, then `win.close()`. The sheet only honors `agrolav-close`
when `event.source === window.opener`, so a random tab cannot shut it.

The hole is the lost handle. If the client was reloaded while the sheet
stayed open, `balanceSheetWindow` is `null` and logout does not close that
sheet. The cookies are gone, but the already-rendered numbers stay on screen
until the user closes it. A named-window reopen-and-close, or a
`BroadcastChannel` ping, would cover that.

## 3. Escape: sheet → client

On the sheet, Escape first closes a category drill-down. Only when none is
open does it `postMessage({ type: "agrolav-focus-front" })` and
`opener.focus()`. The client focuses itself on that message.

That ordering is correct: Escape is not a “leave the sheet” key while a
sub-view is open. The client’s own Escape (return to the matrix) only runs
when the client already has focus.

`window.focus()` across top-level windows is unreliable. Escape counts as a
user gesture, so it often works, but Chrome can still refuse to raise the
client. If opener was lost (reload, or the sheet was not opened from the
client), Escape cannot transfer focus. That is expected.

## Messages

| type | from → to | meaning |
|:-----|:----------|:--------|
| `agrolav-close` | client → sheet | close if `event.source` is the opener |
| `agrolav-probe` | client → sheet | “are you still our window?” |
| `agrolav-pong` | sheet → client | yes; cancels the replace-after-timeout probe |
| `agrolav-focus-front` | sheet → client | raise the client (Escape) |

`postMessage` currently uses `"*"`. Same-site that is fine; checking origin
would be the only hardening worth adding.
