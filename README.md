# Agrolav

Agrolav is household bookkeeping in the browser. After you log in you see a
**matrix of totals**: categories down the left, people across the top. Click a
number to open the bookings behind it. Categories are assigned from keywords
(terms) in the name and description.
{en: agrolav, matrix, totals, categories, bookings}
{nl: boekingen, overzicht}

This page describes what you can do in the app. Operator setup lives in
`documentation/deployment.md`.
{en: documentation, deployment, setup}

Words in the discard lines are removed from a question before any hit term
is counted. A word is removed only on its own, so `to` does not touch `total`.

{discard-en: a, am, can, could, do, find, get, have, how, i, is, me, must, need, please, should, supposed, tell, the, there, to, want, what, where, would}
{discard-nl: ben, bij, heb, hoe, ik, kan, kom, mag, moet, vind, waar, wil}

---

## Log in

Open the client (locally `http://127.0.0.1:8300`). Enter your **username** and
**password**.
{en: log in, login, username, password}
{nl: inloggen, gebruikersnaam, wachtwoord}

There are three kinds of login. The username is the login name of that row:

| Login | What you see |
|---|---|
| **Country** | Every center in that country. Switch centers from the top bar. |
| **Center** | Everyone in that one center. |
| **Person** | Your own column only. |
{en: country, center, person, login kind}
{nl: land, centrum, persoon}

If a mobile number is stored on a person login, the next step is a **6-digit
SMS code**. Enter it, or use **Resend**. Country and center logins are allowed
only from listed IP addresses; from anywhere else you get *This login is not
allowed from your IP address*. Person logins are not IP-gated.
{en: sms, sms code, resend, mobile number, ip address}
{nl: mobiel, telefoon, ip-adres}

---

## The top bar

On the overview these controls sit in the strip above the matrix:
{en: top bar, overview}
{nl: balk}

- **Center** — country login only. Pick which center’s people to show.
{en: center, switch}
{nl: centrum, kiezen}
- **Year** — which booking year the matrix uses.
{en: year, booking year}
{nl: jaar}
- **Bank** — `consolidated` (all banks together) or one bank, when more than
  one bank exists.
{en: bank, consolidated}
{nl: consolidatie}
- **menu** — actions for this login (see below).
{en: menu, open}
- **Question** — the box to the right of menu. Type a question about using
  the program and press Enter.

  `answer_question` (`client/app/help_agent.py`) calculates the answer. The
  client calls it from `POST /api/help`. Under each paragraph of this page is
  a line of `{hit terms}`. Only those terms are counted, not the paragraph
  itself. The reply is the paragraph, or the paragraphs, with the highest
  score. The `{en: …}` and `{nl: …}` lines are not shown. Words in the
  `{discard-en: …}` and `{discard-nl: …}` lines near the top of this page are
  removed from the question first. Only
  this page is read. A
  question with no matching term is answered with “I don't find an answer to
  that in the README.”
{en: question box, help question}
{nl: vraag, antwoord}

The left sidebar shows the title of whoever logged in. After you open a
category, it also shows that person’s column and a **← Matrix** knob to go
back.
{en: sidebar, title, matrix knob}
{nl: titel}

---

## The menu

Open **menu**. What you see depends on the login. Items that do not apply are
not listed.
{en: item, items, menu}

### Always (when the item exists)

**⚙ Edit Terms (Alt+T)**  
Opens the term window: keywords that assign bookings to categories. See
[Edit Terms](#edit-terms). Shortcut: `Alt+T`.
{en: edit terms, alt+t, term window}
{nl: termen, term, bewerken, termvenster}

**Recalculate categories**  
Clears previous keyword hits and assigns every booking in the current scope
again (this person, or this center). Use this after you change terms or the
category list.
{en: recalculate}
{nl: herberekenen, herbereken}

**Download transactions**  
Fetches new bank bookings (Enable Banking). A person who still needs bank
consent is sent to the bank in a new tab; after consent, download continues.
Shown only when bank download is available.
{en: download, transactions, consent}
{nl: bankafschrift, uitlezen, toestemming}

**Add person**  
Opens the hub page to create a person in the current center. Not shown on a
personal login.
{en: add person}
{nl: persoon toevoegen, voeg persoon}

**Upload**  
Opens the upload page for a spreadsheet or bank CSV. Shown when this login may
upload files.
{en: upload, csv, spreadsheet}

**Logout**  
Ends the browser session and returns to the login card.
{en: logout, log out}
{nl: uitloggen, log uit, log ik uit, afmelden}

### Country and center logins

**Edit categories**  
Change the country’s category codes and labels. See
[Edit categories](#edit-categories).
{en: edit categories}
{nl: categorieën, categorieen, bewerk categorieën}

**Restrict IP access**  
Allowlist of client IPs for country and center logins. See
[Restrict IP access](#restrict-ip-access).
{en: restrict ip, ip access, allowlist}

### Country login only

**Wipe year**  
Asks for a four-digit year, then asks you to confirm. Deletes that year’s
bookings for **every account in the country**, and removes uploaded filenames
for those accounts. This cannot be undone.
{en: wipe year, delete year}
{nl: jaar wissen}

### Person login only

**Set password**  
Change your password and optional mobile number. See
[Set password](#set-password). The header menu is hidden on this page; use
**Cancel** or **Matrix (Alt+M)** to leave.
{en: set password}
{nl: verander paswoord, wachtwoord wijzigen}

---

## The matrix

Each cell is that person’s total in that category for the selected year (and
bank view).
{en: matrix, cell, total}
{nl: totaal}

- **Click a non-empty amount** to open the booking list for that person and
  category.
{en: click amount, open bookings}
- Empty cells and the two **footer rows** (balance and last booked date) are
  not clickable.
{en: footer, last booked, empty cell}
{nl: saldo, datum}
- Negative amounts are shown in red.
{en: negative, red amount}
{nl: rood}

---

## The booking list

The table lists every booking in the chosen cell. Matching terms are
highlighted in the name and description.
{en: booking list, highlighted}
{nl: boekingen, gemarkeerd}

### Left-click

**Description** — click the text, edit, then click away or press Enter. A
description you changed is shown in **blue**.
{en: description, blue text, left-click, left click}
{nl: omschrijving, blauw}

**Category (column C)** — click the code, type a valid category number, then
click away or press Enter. An unknown code is rejected. A category you
overrode is shown in **bold**.
{en: category code, column c, bold category}
{nl: categoriecode, vet}

Other columns (date, type, IBAN, amount) are not edited with a left-click.
{en: date column, iban, amount column}
{nl: bedrag}

### Right-click the amount

Right-click the **amount** to **split** that booking. You leave the list and
open the split page.
{en: split, right-click amount}
{nl: splitsen, rechtsklik bedrag}

The original amount stays the remainder: extra lines you add are subtracted
from it, so the total never changes.
{en: split remainder}
{nl: restbedrag}

- **Add line** — another description and amount.
{en: add line}
{nl: regel toevoegen}
- Edit descriptions and amounts in the table; delete a line with its button.
{en: delete line}
{nl: verwijder regel}
- **Save** — writes the split and returns to the matrix.
{en: save split}
{nl: splitsing opslaan}
- **Matrix (Alt+M)** — leave without saving.
{en: leave split, alt+m}

### Right-click a name or description

Right-click a **word** in the **name** or **description**. A small menu opens
on that word (you can edit the phrase in the box at the top).
{en: right-click word, term menu, name}
{nl: rechtsklik, naam}

Tick **G** (general) or **P** (personal) on a category row:

- **G** — the term applies to everyone in this country/center.
- **P** — the term applies only to this person.
{en: general term, personal term}
{nl: gemeenschappelijk, persoonlijk}

The word is saved at once. **cancel** or click outside the menu to close it
without assigning. Other bookings keep their category until the next menu
click.
{en: cancel term, save term}
{nl: annuleer}

---

## Edit Terms

**menu → ⚙ Edit Terms**, or `Alt+T`. **Matrix (Alt+M)** (or `Ctrl+Tab`)
returns to the overview. Edits save as soon as you leave a field; matching
bookings update in the background.
{en: edit terms page, alt+t, ctrl+tab, background}

There is a **General** panel, then one panel per person.
{en: general panel, personal panel}

- Type in **+ term** and press Enter (or leave the field) to add a keyword.
{en: add term, plus term}
{nl: term toevoegen}
- Edit an existing term and leave the field to save.
{en: edit term}
{nl: wijzig term}
- **×** deletes that term.
{en: delete term}
{nl: verwijder term}

### How terms match

A term matches a whole word in the booking’s name and description. A word
ends at a space, a dot, a dash, or other punctuation (slash, comma, colon,
apostrophe, asterisk, plus, brackets). A digit or an underscore stays inside
the word.
{en: word, dash, dot}
{nl: woord, streepje, punt}

`#` stands for zero or more letters, dots, or asterisks inside one
space-separated piece. It does not cross a space. A dash inside that piece
is skipped, so `albert#heijn` still matches `albert-heijn`.
{en: hash, wildcard, asterisk}
{nl: hekje}

`&&` means both phrases must match, in either order, and they need not sit
next to each other. For example `heijn && machtiging`. The separator is
space, `&&`, space.
{en: &&, heijn, machtiging, both phrases}
{nl: beide}

Priority, highest first:

1. A **personal** term beats every **general** term.
2. An `&&` term beats a single phrase.
3. **Activa/passiva** beats **lasten/baten**. Activa and passiva are category
   codes below 3000. Lasten and baten are codes of 3000 or above.
4. The later category name wins, then the later term. Later is dictionary
   order of the text, not the time the term was saved. `1110 Kruisposten`
   beats `1052 Spaarrekening`. In the same category, `spaarrekening` beats
   `oranje`.
{en: priority}
{nl: prioriteit, voorrang, voorrangsregels, activa, passiva, lasten, baten}

The stored hit is `P:` plus the term, or `G:` plus the term. If nothing
matches, the booking stays in the remainder category and the hit is empty.
{en: hit, P:, G:, remainder}
{nl: restcategorie}

---

## Edit categories

**menu → Edit categories** (country or center login). **Matrix (Alt+M)** goes
back.

Each row is a booking category: **code**, **label**, and which row is
**Unclassified** (the remainder). Changing a label keeps existing bookings on
that category. **Add category** appends a row. **Delete** removes a category
and moves leftover bookings to unclassified. **Submit** writes the list.
{en: edit categories page, add category, delete category, submit categories}

---

## Restrict IP access

**menu → Restrict IP access** (country or center login). Person logins are
never IP-gated.
{en: restrict ip page}

Pick a **Login** (a country or a center), type an IPv4 or IPv6 address,
**Add IP**. The table lists current addresses; remove one with its button.
{en: add ip, ipv4, ipv6, remove ip}

An empty list on this page means **no** address is allowed for that login,
unless the same address is also on the administrator list (edited in SSMS,
not here). The allowed set is the sum of the two lists. If both are empty,
no country or center login works at all.
{en: empty ip list, administrator list, ssms}

---

## Set password

**menu → Set password** (person login).

Enter the current password, the new password twice, and optionally a **mobile
phone** (`+316…` or `06…`). A mobile number turns on SMS two-step login.

**Save** writes the change. **Cancel** (or **Matrix (Alt+M)**) returns to the
matrix without saving.
{en: save password, cancel password, mobile phone, sms login}

---

## Upload and download

**Upload** is for people who paste a bank CSV or spreadsheet rather than
connecting a bank. Pick the year and format on the upload page.
{en: upload page, bank csv}

**Download transactions** pulls from the bank when consent is in place. The
first time, the bank site may open for authorization; after you approve,
Agrolav fetches the range and fills the matrix.
{en: download from bank, authorization}
{nl: toestemming geven}

---

## Keyboard

| Shortcut | Action |
|---|---|
| `Alt+T` | Edit Terms |
| `Alt+M` | Back to the matrix (from Terms, categories, IP, password, split) |
| `Alt+C` | Edit categories (from the matrix, when that menu item exists) |
| Enter | Confirm an in-cell edit |
{en: keyboard, shortcut, alt+c, enter key}
{nl: sneltoets}

---

## When a saved term is applied

A right-click in the booking list only saves the word and queues a pass.
Repeated right-clicks do the same. The pass runs when you click a menu item.
The top bar shows “background procedure running: please wait…”, and the menu
command runs only after the pass succeeds. Several terms saved in a burst are
one pass. The terms window itself waits for the pass before it returns.
{en: background procedure, please wait, queued, menu click}
{nl: wachten}

This pass is not **Recalculate**. Recalculate clears hits and scores every
booking in the current scope again. The pass after a term edit leaves a
category you set by hand (shown **bold**) where it is, leaves Excel rows
where they are, and walks only each person’s latest booking year. A
description you edited (shown **blue**) is still scored; the description
stays.
{en: recalculate difference, bold category, blue description, excel, latest year}
{nl: laatste jaar}

A personal term rescores that person, or that account when terms are stored
per account. A general term rescores every person in every center. One
general term in a burst widens the whole burst to that scope. Earlier years
are not touched.
{en: personal scope, general scope, every person}
{nl: iedereen}

## Categories a booking cannot take

A booking cannot be assigned to eigen vermogen, or to a live checking
account. Those amounts are computed, or they come from the bank. A
spaarrekening (mirror) can take a term. The remainder category receives a
booking that no term matches.
{en: cannot assign, bank account, mirror, no hit}
{nl: eigen vermogen, spaarrekening}

## A journal line in the wrong direction

In a category’s booking list, a journal line whose sign opposes the bookings
in that list shows its category code in **bold red**. The line is moving
this category the other way from the real bookings. Mirror rows are not
marked.
{en: journal, bold red, wrong sign}
{nl: journaal, rood}

## The name in the left panel

The heading is the title stored for the login: the person, the center, or
the country. It is not the username.

A personal login with two or more accounts gets a second line. On
**Consolidated** that line is the word Consolidatie (or Consolidated). On
one account it is that account’s name. One account, or a center or country
login, shows the title only. The browser tab uses the title without the
second line.
{en: sidebar title, subtitle, account name, several accounts}
{nl: titel, consolidatie}

## The balance sheet window

**menu → Balance sheet** opens the sheet in its own window. A second click
uses that same window. **Logout** closes it. In the sheet, Escape closes an
open category first; with none open, Escape returns to the bookkeeping
window.
{en: balance sheet, escape, logout window}
{nl: balans, balansvenster}

On the sheet, eigen vermogen is **bold black** when it still equals the
year’s opening amount, and **bold red** when it does not.
{en: bold black, bold red, opening}
{nl: eigen vermogen}

Where the menu offers them, **Manual journal posts** and **Automatic journal
posts** open from the same menu. **Export balance sheet** downloads the
workbook.
{en: manual journal, automatic journal, export balance}
{nl: export balans}

## Meals

The meal sheet is a separate page, not part of this matrix:
`https://expenses.apsurt.nl/maaltijden`. Its login is not the bookkeeping
login. A week runs Sunday to Saturday. **Dag** shows today, **Week** shows
the seven days, **Reserveren** shows only your own row.

Each day has five meals, **O M A L P**. A click switches a cell between
`x` and `v`. You can change only your own row. The login `admin` is not a
row; it edits the extra counts for the current week.
{en: meals, meal sheet, O M A L P}
{nl: maaltijden, eten, reserveren, weergave}

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
{en: run hub, run client, port 8200, port 8300, database}
