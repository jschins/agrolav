# Agrolav

Agrolav is household bookkeeping in the browser. After you log in you see a
**matrix of totals**: categories down the left, people across the top. Click a
number to open the bookings behind it. Categories are assigned from bank
type-rules and from keywords (terms) in the name and description.

This page describes what you can do in the app. Operator setup lives in
`documentation/deployment.md`.

---

## Log in

Open the client (locally `http://127.0.0.1:8300`). Enter your **username** and
**password**.

There are three kinds of login. The username is the login name of that row:

| Login | What you see |
|---|---|
| **Country** | Every center in that country. Switch centers from the top bar. |
| **Center** | Everyone in that one center. |
| **Person** | Your own column only. |

If a mobile number is stored on a person login, the next step is a **6-digit
SMS code**. Enter it, or use **Resend**. Country and center logins can also be
limited to listed IP addresses; from a blocked address you get *This login is
not allowed from your IP address*.

---

## The top bar

On the overview these controls sit in the strip above the matrix:

- **Center** — country login only. Pick which center’s people to show.
- **Year** — which booking year the matrix uses.
- **Bank** — `consolidated` (all banks together) or one bank, when more than
  one bank exists.
- **menu** — actions for this login (see below).

The left sidebar shows the title of whoever logged in. After you open a
category, it also shows that person’s column and a **← Matrix** knob to go
back.

---

## The menu

Open **menu**. What you see depends on the login. Items that do not apply are
not listed.

### Always (when the item exists)

**⚙ Edit Terms (Alt+T)**  
Opens the term window: keywords that assign bookings to categories. See
[Edit Terms](#edit-terms). Shortcut: `Alt+T`.

**Recalculate categories**  
Clears previous keyword hits and assigns every booking in the current scope
again (this person, or this center). Use this after you change terms or the
category list.

**Download transactions**  
Fetches new bank bookings (Enable Banking). A person who still needs bank
consent is sent to the bank in a new tab; after consent, download continues.
Shown only when bank download is available.

**Add person**  
Opens the hub page to create a person in the current center. Not shown on a
personal login.

**Upload**  
Opens the upload page for a spreadsheet or bank CSV. Shown when this login may
upload files.

**Logout**  
Ends the browser session and returns to the login card.

### Country and center logins

**Edit categories**  
Change the country’s category codes and labels. See
[Edit categories](#edit-categories).

**Restrict IP access**  
Allowlist of client IPs for country and center logins. See
[Restrict IP access](#restrict-ip-access).

### Country login only

**Wipe year**  
Asks for a four-digit year, then asks you to confirm. Deletes that year’s
bookings for **every account in the country**, and removes uploaded filenames
for those accounts. This cannot be undone.

### Person login only

**Set password**  
Change your password and optional mobile number. See
[Set password](#set-password). The header menu is hidden on this page; use
**Cancel** or **Matrix (Alt+M)** to leave.

---

## The matrix

Each cell is that person’s total in that category for the selected year (and
bank view).

- **Click a non-empty amount** to open the booking list for that person and
  category.
- Empty cells and the two **footer rows** (balance and last booked date) are
  not clickable.
- Negative amounts are shown in red.

---

## The booking list

The table lists every booking in the chosen cell. Matching terms are
highlighted in the name and description.

### Left-click

**Description** — click the text, edit, then click away or press Enter. A
description you changed is shown in **blue**.

**Category (column C)** — click the code, type a valid category number, then
click away or press Enter. An unknown code is rejected. A category you
overrode is shown in **bold**.

Other columns (date, type, IBAN, amount) are not edited with a left-click.

### Right-click the amount

Right-click the **amount** to **split** that booking. You leave the list and
open the split page.

The original amount stays the remainder: extra lines you add are subtracted
from it, so the total never changes.

- **Add line** — another description and amount.
- Edit descriptions and amounts in the table; delete a line with its button.
- **Save** — writes the split and returns to the matrix.
- **Matrix (Alt+M)** — leave without saving.

### Right-click a name or description

Right-click a **word** in the **name** or **description**. A small menu opens
on that word (you can edit the phrase in the box at the top).

Tick **G** (general) or **P** (personal) on a category row:

- **G** — the term applies to everyone in this country/center.
- **P** — the term applies only to this person.

The booking is recategorized if the new term sends it elsewhere. **cancel** or
click outside the menu to close it without assigning.

---

## Edit Terms

**menu → ⚙ Edit Terms**, or `Alt+T`. **Matrix (Alt+M)** (or `Ctrl+Tab`)
returns to the overview. Edits save as soon as you leave a field; matching
bookings update in the background.

There is a **General** panel, then one panel per person.

- Type in **+ term** and press Enter (or leave the field) to add a keyword.
- Edit an existing term and leave the field to save.
- **×** deletes that term.

### How terms match

`#` matches zero or more letters or dots **inside one word** (not across
spaces). Use `&&` when both phrases must match, for example `albert && heijn`.

Priority, highest first:

1. Bank **typerules** (type → category) beat all keywords.
2. **Personal** terms beat **general** terms.
3. `&&` terms beat a single phrase.
4. Later category, then later term, wins when more than one keyword matches.

Unclassified bookings sit in the remainder category until a rule or term
moves them.

---

## Edit categories

**menu → Edit categories** (country or center login). **Matrix (Alt+M)** goes
back.

Each row is a booking category: **code**, **label**, and which row is
**Unclassified** (the remainder). Changing a label keeps existing bookings on
that category. **Add category** appends a row. **Delete** removes a category
and moves leftover bookings to unclassified. **Submit** writes the list.

---

## Restrict IP access

**menu → Restrict IP access** (country or center login). Person logins are
never IP-gated.

Pick a **Login** (a country or a center), type an IPv4 address, **Add IP**.
The table lists current addresses; remove one with its button. An empty list
means that login is not restricted.

---

## Set password

**menu → Set password** (person login).

Enter the current password, the new password twice, and optionally a **mobile
phone** (`+316…` or `06…`). A mobile number turns on SMS two-step login.

**Save** writes the change. **Cancel** (or **Matrix (Alt+M)**) returns to the
matrix without saving.

---

## Upload and download

**Upload** is for people who paste a bank CSV or spreadsheet rather than
connecting a bank. Pick the year and format on the upload page.

**Download transactions** pulls from the bank when consent is in place. The
first time, the bank site may open for authorization; after you approve,
Agrolav fetches the range and fills the matrix.

---

## Keyboard

| Shortcut | Action |
|---|---|
| `Alt+T` | Edit Terms |
| `Alt+M` | Back to the matrix (from Terms, categories, IP, password, split) |
| `Alt+C` | Edit categories (from the matrix, when that menu item exists) |
| Enter | Confirm an in-cell edit |

---

## Running it yourself

Start the hub, then the client (do not start them from this README’s agent):

```text
cd hub     →  uv run hub      (port 8200)
cd client  →  uv run client   (port 8300)
```

Open `http://127.0.0.1:8300`. SQL Server database `agrolav` must be up;
`HUB_DATABASE_URL` is in `hub/.env`. Production deploy is
`documentation/deployment.md`.
