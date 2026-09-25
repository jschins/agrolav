<!-- {discard-en:a,am,can,could,do,find,get,have,how,i,is,me,must,need,please,should,supposed,tell,the,there,to,want,what,where,would} -->
<!-- {discard-nl:ben,bij,heb,hoe,ik,kan,kom,mag,moet,vind,waar,wil} -->

# Agrolav

Agrolav is household bookkeeping in the browser. After you log in you see a
**matrix of totals**: categories down the left, people across the top. Click a
number to open the bookings behind it. Categories are assigned from keywords
(terms) in the name and description.

This page has two uses. It is the description of what you can do in the app,
and it is the only page the question box reads. Operator setup lives in
`documentation/deployment.md`.

Each later section ends with one `{en: …}` line and one `{nl: …}` line. Those
lines are hidden in the preview. The question box counts only those terms, not
the section text, and it does not search this opening section. The Dutch line
translates the English line in the same order, one term for one term, with the
same weight. Terms are separated by commas, with no space after the comma.
`log in` is the one term that keeps a space inside it. A term may end with a
weight, as in `category[3]`. That hit counts as 3. A term with no number counts
as 1. A term that is also a word in the section title counts as 5. Each hit
adds its weight, so two hits outweigh one. Every section that hits is returned,
highest score first. The brace lines are not shown in the answer.

The `{discard-en:}` and `{discard-nl:}` lines above the title are removed from
the question first. A word is removed only on its own, so `to` does not touch
`total`. A question with no matching term is answered with “I don't find an
answer to that in the README.”

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
SMS code**. Enter it, or use **Resend**. Country and center logins are allowed
only from listed IP addresses; from anywhere else you get *This login is not
allowed from your IP address*. Person logins are not IP-gated.
<!-- {en:log in[5],login[3],username,usernames,password[3],passwords,country,countries,center,centers,person,people,kind,kinds,sms,code,codes,resend,mobile,mobiles,number,numbers,ip,address,addresses,phone,phones} -->
<!-- {nl:log in[5],inloggen[3],gebruikersnaam,gebruikersnamen,wachtwoord[3],wachtwoorden,land,landen,centrum,centra,persoon,personen,soort,soorten,sms,code,codes,opnieuw,mobiel,mobielen,nummer,nummers,ip,adres,adressen,telefoon,telefoons} -->

---

## The top bar

On the overview these controls sit in the strip above the matrix:

- **Center** — country login only. Pick which center’s people to show.
- **Year** — which booking year the matrix uses.
- **Bank** — `consolidated` (all banks together) or one bank, when more than
  one bank exists.
- **menu** — actions for this login (see below).
- **Question** — the box to the right of menu. Type a question about using
  the program and press Enter. The answer is taken from the later sections
  of this page.

The left sidebar shows the title of whoever logged in. After you open a
category, it also shows that person’s column and a **← Matrix** knob to go
back.
<!-- {en:top[5],bar[5],overview,center,centers,switch[3],year[3],years,booking,bookings,bank,banks,consolidated,menu,question,questions,answer,answers,box,help,sidebar,title,titles,matrix,knob} -->
<!-- {nl:boven[5],balk[5],overzicht,centrum,centra,kiezen[3],jaar[3],jaren,boeking,boekingen,bank,banken,consolidatie,menu,vraag,vragen,antwoord,antwoorden,vak,hulp,zijbalk,titel,titels,matrix,knop} -->

---

## The menu

### Always (when the item exists)

Open **menu**. What you see depends on the login. Items that do not apply are
not listed.

**⚙ Edit Terms (Alt+T)**  
Opens the term window: keywords that assign bookings to categories. See
[Edit Terms](#edit-terms). Shortcut: `Alt+T`.

**Recalculate categories**  
Reassigns bookings from the terms, for every year in reach. A person login
covers that person. A country or center login covers every person in the
center now selected; other centers stay as they are. A category you set by
hand, and a row that came from Excel, stay. Use this after you change terms
or the category list.

**Download transactions**  
Fetches new bank bookings (Enable Banking). A person login fetches that
person. A country or center login fetches every person in the selected
center who has bank consent. People who upload a file are skipped. Someone
who still needs consent is sent to the bank in a new tab; after consent,
download continues. Shown only when this center has a bank connection.

**Add person**  
Opens the hub page to create a person in the current center. Not shown on a
personal login.

**Upload**  
Opens the upload page for a spreadsheet or bank CSV. Shown when this login may
upload files.

**Logout**  
Ends the browser session and returns to the login card.
<!-- {en:item[5],items[5],menu,edit,term,terms,alt+t,window,recalculate[3],person,people,center,centers,download,statement,statements,transaction,transactions,consent,consents,add[3],upload,csv,spreadsheet,spreadsheets,logout[3],log,out} -->
<!-- {nl:onderdeel[5],onderdelen[5],menu,bewerken,term,termen,alt+t,termvenster,herberekenen[3],persoon,personen,centrum,centra,uitlezen,bankafschrift,bankafschriften,transactie,transacties,toestemming,toestemmingen,toevoegen[3],uploaden,csv,rekenblad,rekenbladen,uitloggen[3],log,uit} -->
**Prepare consent**  
Country or center login, when this center has a bank connection. Asks which
person, then opens the bank so that person can grant consent.

**Invalidate consent**  
Same logins. Asks which person, asks you to confirm, then removes that
person’s bank consent.

**Download YTD**  
Same logins. Asks which person, then fetches that person’s statements from
1 January of this year through today. If the bank will not give that range,
you are told to renew consent first.
<!-- {en:prepare[3],consent[5],consents[5],invalidate[3],remove,download,ytd[5],year,january,renew} -->
<!-- {nl:bereid[3],toestemming[5],toestemmingen[5],verwijder[3],verwijderen,uitlezen,ytd[5],jaar,januari,vernieuwen} -->
**Calculate cross-postings**  
Shown when this login has a balance sheet. Pairs internal transfers and
writes their categories. A category set this way counts as set by hand.

**Smaller expenses**  
Country, center, or person login. Asks for a maximum amount and a category.
Remainder bookings whose expense is smaller than that amount take the chosen
category, and count as set by hand. **Cancel** does nothing.

**Smaller income**  
The same, for remainder bookings whose income is smaller than the maximum.
<!-- {en:cross-postings[5],cross,posting,postings,calculate[3],internal,transfer,transfers,smaller[5],expense,expenses,income,incomes,maximum,amount,category,remainder,cancel,apply} -->
<!-- {nl:kruisposten[5],kruis,post,posten,bereken[3],intern,overboeking,overboekingen,kleinere[5],uitgave,uitgaven,inkomst,inkomsten,maximaal,bedrag,categorie,restcategorie,annuleren,toepassen} -->
**Back to summary**  
Returns to the matrix. Shown while a year is selected and you are on the
matrix menu (not on Terms, categories, IP, password, split, or a journal
page).
<!-- {en:back[5],summary[5],matrix,return,overview} -->
<!-- {nl:terug[5],overzicht[5],matrix,terugkeren,samenvatting} -->
### Country and center logins

**Edit categories**  
Change the country’s category codes and labels. See
[Edit categories](#edit-categories).

**Restrict IP access**  
Allowlist of client IPs for country and center logins. See
[Restrict IP access](#restrict-ip-access).
<!-- {en:edit,category,categories,restrict[3],ip,access,allowlist,allowlists} -->
<!-- {nl:bewerken,categorie,categorieën,beperken[3],ip,toegang,toegangslijst,toegangslijsten} -->
### Wipe year

**Wipe year**  
Asks for a four-digit year, then asks you to confirm. Deletes that year’s
bookings, and removes uploaded filenames for the accounts involved. This
cannot be undone.

- Country login: every account in the center now selected.
- Center login: the person you name.
- Person login: the account selected under **Bank**. Pick one account;
  consolidated does not wipe.
<!-- {en:wipe[5],year[5],years[5],delete,person,people,center,centers,account,accounts} -->
<!-- {nl:wissen[5],jaar[5],jaren[5],verwijderen,persoon,personen,centrum,centra,rekening,rekeningen} -->
### Person login only

**Set password**  
Change your password and optional mobile number. See
[Set password](#set-password). The header menu is hidden on this page; use
**Cancel** or **Matrix (Alt+M)** to leave.
<!-- {en:set[3],password,passwords,change} -->
<!-- {nl:instellen[3],wachtwoord,wachtwoorden,wijzigen} -->

---

## The matrix

Each cell is that person’s total in that category for the selected year (and
bank view).

- **Click a non-empty amount** to open the booking list for that person and
  category.
- Empty cells and the two **footer rows** (balance and last booked date) are
  not clickable.
- Negative amounts are shown in red.
<!-- {en:matrix[5],cell,cells,total,totals,click,amount,amounts,open,booking,bookings,footer,footers,last,booked,empty,negative,red,balance,balances,date,dates} -->
<!-- {nl:matrix[5],cel,cellen,totaal,totalen,klik,bedrag,bedragen,openen,boeking,boekingen,voettekst,voetteksten,laatste,geboekt,leeg,negatief,rood,saldo,saldo's,datum,datums} -->

---

## The booking list

The table lists every booking in the chosen cell. Matching terms are
highlighted in the name and description.

**Left-click**

**Description** — click the text, edit, then click away or press Enter. A
description you changed is shown in **blue**.

**Category (column C)** — click the code, type a valid category number, then
click away or press Enter. An unknown code is rejected. A category you
overrode is shown in **bold**.

Other columns (date, type, IBAN, amount) are not edited with a left-click.
<!-- {en:booking[5],bookings[5],list[5],lists[5],highlighted,description,descriptions,blue,text,left-click,left,click,category,categories,code,codes,c,bold,date,dates,iban,amount,amounts,column[5],columns[5]} -->
<!-- {nl:boeking[5],boekingen[5],lijst[5],lijsten[5],gemarkeerd,omschrijving,omschrijvingen,blauw,tekst,linksklik,links,klik,categorie,categorieën,code,codes,c,vet,datum,datums,iban,bedrag,bedragen,kolom[5],kolommen[5]} -->
### Right-click the amount

Right-click the **amount** to **split** that booking. You leave the list and
open the split page.

The original amount stays the remainder: extra lines you add are subtracted
from it, so the total never changes.

- **Add line** — another description and amount.
- Edit descriptions and amounts in the table; delete a line with its button.
- **Save** — writes the split and returns to the matrix.
- **Matrix (Alt+M)** — leave without saving.
<!-- {en:split,splits,right-click[5],amount[5],amounts[5],remainder,remainders,add,line,lines,delete,save,leave,alt+m} -->
<!-- {nl:splitsen,splitsingen,rechtsklik[5],bedrag[5],bedragen[5],restbedrag,restbedragen,toevoegen,regel,regels,verwijderen,opslaan,verlaten,alt+m} -->
### Right-click a name or description

Right-click a **word** in the **name** or **description**. A small menu opens
on that word (you can edit the phrase in the box at the top).

Tick **G** (general) or **P** (personal) on a category row:

- **G** — the term applies to everyone in this country/center.
- **P** — the term applies only to this person.

The word is saved at once. **cancel** or click outside the menu to close it
without assigning. Other bookings keep their category until the next menu
click.
<!-- {en:right-click[5],word,words,menu,name[5],names[5],general,personal,cancel,term[5],terms[5],save} -->
<!-- {nl:rechtsklik[5],woord,woorden,menu,naam[5],namen[5],gemeenschappelijk,persoonlijk,annuleren,term[5],termen[5],opslaan} -->

---

## Edit Terms

**menu → ⚙ Edit Terms**, or `Alt+T`. **Matrix (Alt+M)** (or `Ctrl+Tab`)
returns to the overview. Edits save as soon as you leave a field; matching
bookings update in the background.

The window has four columns. Click a category in the first. The second and
fourth columns then show that category’s terms.

**Category**  
The categories a booking can take a term for. Categories a booking cannot
take are not listed. The terms in the other columns belong to the category
you click.

**General**  
Keywords for the selected category. They apply to every person in the
country, in every center. A personal term beats a general one.

**Person**, or **Account** when terms are stored per account  
Who the personal terms belong to. A person login lists only you. A country
or center login lists the people in the center now selected. When the
heading is Account, each row is one account, and the center name is the
first row, marked center. The fourth column then shows every personal term
on any of those accounts. A term you add is written on each of them. A term
you delete is removed from each of them.

**Personal**  
Keywords for the selected category and for the person or account selected
in the third column. They apply only there.

- Type in **+ term** and press Enter (or leave the field) to add a keyword.
- Edit an existing term and leave the field to save.
- **×** deletes that term.
<!-- {en:edit[5],term[5],terms[5],page,alt+t,ctrl+tab,window,background,four,column[5],columns[5],category,categories,general,person,people,account,accounts,center,centers,personal,add,plus,delete,change} -->
<!-- {nl:bewerken[5],term[5],termen[5],pagina,alt+t,ctrl+tab,termvenster,achtergrond,vier,kolom[5],kolommen[5],categorie,categorieën,gemeenschappelijk,persoon,personen,rekening,rekeningen,centrum,centra,persoonlijk,toevoegen,plus,verwijderen,wijzig} -->
### How terms match

A term matches a whole word in the booking’s name and description. A word
ends at a space, a dot, a dash, or other punctuation (slash, comma, colon,
apostrophe, asterisk, plus, brackets). A digit or an underscore stays inside
the word.

`#` stands for zero or more letters, dots, or asterisks inside one
space-separated piece. It does not cross a space. A dash inside that piece
is skipped, so `albert#heijn` still matches `albert-heijn`.

`&&` means both phrases must match, in either order, and they need not sit
next to each other. For example `heijn && machtiging`. The separator is
space, `&&`, space.

Priority, highest first:

1. A **personal** term beats every **general** term.
2. An `&&` term beats a single phrase.
3. **Activa/passiva** beats **lasten/baten**. Activa and passiva are category
   codes below 3000. Lasten and baten are codes of 3000 or above.
4. The later category name wins, then the later term. Later is dictionary
   order of the text, not the time the term was saved. `1110 Kruisposten`
   beats `1052 Spaarrekening`. In the same category, `spaarrekening` beats
   `oranje`.

The stored hit is `P:` plus the term, or `G:` plus the term. If nothing
matches, the booking stays in the remainder category and the hit is empty.
<!-- {en:terms[5],word,dash,dot,hash,wildcard,asterisk,&&,heijn,machtiging,both,phrases,priority,hit,P,G,remainder,match[5],rules,activa,passiva,lasten,baten,prioriteit} -->
<!-- {nl:termen[5],woord,streepje,punt,hekje,jokerteken,sterretje,&&,heijn,machtiging,beide,frasen,voorrang,treffer,P,G,restcategorie,overeenkomen[5],voorrangsregels,activa,passiva,lasten,baten,prioriteit} -->

### Term definition strategy

Define terms in this order.

1. Run **Calculate cross-postings** first. It pairs internal transfers and
   writes their categories. Those rows count as set by hand, so a later term
   does not move them.
2. Define the **general** terms as completely as you can. A general term has
   the lowest precedence. Inside the general list, an `&&` term beats a
   single phrase, so use `&&` when one general term should win over another.
3. Then define the **personal** terms. A personal term beats every general
   term. If that word also sits in a description next to a general term, the
   booking leaves the category the general term had given it. Restrict the
   personal term to one account when you can. It then touches fewer
   statements than the same term on every account of a center.
4. When a personal term should apply to every account of a center, write it
   on the center row. It is copied onto each account of that center. Deleting
   it from the center row removes it from those accounts.
5. Last, run **Smaller expenses** and **Smaller income**. Each asks for a
   maximum and a category. Remainder bookings smaller than that maximum take
   the chosen category and count as set by hand. The categories you still
   review then hold the larger amounts. The smaller ones, which move the
   result less, are already stored, so the balance sheet is faster to prepare.
<!-- {en:strategy[5],order,first,cross-postings[5],general[5],precedence,&&,personal[5],particular,account,center,restrict,smaller[5],expenses,income,balance,sheet,maximum,remainder} -->
<!-- {nl:strategie[5],volgorde,eerst,kruisposten[5],bereken,gemeenschappelijk[5],voorrang,&&,persoonlijk[5],bijzonder,rekening,centrum,beperken,kleinere[5],uitgaven,inkomsten,balans,blad,maximaal,restcategorie} -->

---

## Edit categories

**menu → Edit categories** (country or center login). **Matrix (Alt+M)** goes
back.

Each row is a booking category: **code**, **label**, and which row is
**Unclassified** (the remainder). Changing a label keeps existing bookings on
that category. **Add category** appends a row. **Delete** removes a category
and moves leftover bookings to unclassified. **Submit** writes the list.
<!-- {en:edit[5],category[5],categories[5],page,add,delete,submit} -->
<!-- {nl:bewerken[5],categorie[5],categorieën[5],pagina,toevoegen,verwijderen,indienen} -->

---

## Restrict IP access

**menu → Restrict IP access** (country or center login). Person logins are
never IP-gated.

Pick a **Login** (a country or a center), type an IPv4 or IPv6 address,
**Add IP**. The table lists current addresses; remove one with its button.

An empty list on this page means **no** address is allowed for that login,
unless the same address is also on the administrator list (edited in SSMS,
not here). The allowed set is the sum of the two lists. If both are empty,
no country or center login works at all.
<!-- {en:restrict[5],page,add,ipv4,ipv6,remove,empty,list,administrator,ssms,ip[5]} -->
<!-- {nl:beperken[5],pagina,toevoegen,ipv4,ipv6,verwijderen,leeg,lijst,beheerder,ssms,ip[5]} -->

---

## Set password

**menu → Set password** (person login).

Enter the current password, the new password twice, and optionally a **mobile
phone** (`+316…` or `06…`). A mobile number turns on SMS two-step login.

**Save** writes the change. **Cancel** (or **Matrix (Alt+M)**) returns to the
matrix without saving.
<!-- {en:save,password[5],cancel,mobile,phone,sms,login} -->
<!-- {nl:opslaan,wachtwoord[5],annuleren,mobiel,telefoon,sms,inloggen} -->

---

## Upload and download

**Upload** is for people who paste a bank CSV or spreadsheet rather than
connecting a bank. Pick the year and format on the upload page.

**Download transactions** pulls from the bank when consent is in place. A
person login fetches that person. A country or center login fetches every
person in the selected center who has consent. The first time, the bank
site may open for authorization; after you approve, Agrolav fetches the
range and fills the matrix.
<!-- {en:upload[5],page,bank,csv,download[5],from,authorization,authorisation,consent,give} -->
<!-- {nl:uploaden[5],pagina,bank,csv,downloaden[5],van,machtiging,autorisatie,toestemming,geven} -->

---

## Keyboard

| Shortcut | Action |
|---|---|
| `Alt+T` | Edit Terms |
| `Alt+M` | Back to the matrix (from Terms, categories, IP, password, split) |
| `Alt+C` | Edit categories (from the matrix, when that menu item exists) |
| Enter | Confirm an in-cell edit |
<!-- {en:keyboard[5],shortcut,alt+c,enter,key} -->
<!-- {nl:toetsenbord[5],sneltoets,alt+c,enter,toets} -->

---

## When a saved term is applied

A right-click in the booking list only saves the word and queues a pass.
Repeated right-clicks do the same. The pass runs when you click a menu item.
The top bar shows “background procedure running: please wait…”, and the menu
command runs only after the pass succeeds. Several terms saved in a burst are
one pass. The terms window itself waits for the pass before it returns.

This pass is not **Recalculate**. Recalculate clears hits and scores again
for every year: that person on a person login, or every person in the
selected center on a country or center login. The pass after a term edit
leaves a category you set by hand (shown **bold**) where it is, leaves Excel
rows where they are, and walks only each person’s latest booking year. A
description you edited (shown **blue**) is still scored; the description
stays.

A personal term rescores that person, or that account when terms are stored
per account. A general term rescores every person in every center. One
general term in a burst widens the whole burst to that scope. Earlier years
are not touched.
<!-- {en:background,procedure,please,wait,queued,menu,click,recalculate,difference,bold,category,blue,description,excel,latest,year,personal,scope,general,every,person,everyone} -->
<!-- {nl:achtergrond,procedure,alstublieft,wachten,wachtrij,menu,klik,herberekenen,verschil,vet,categorie,blauw,omschrijving,excel,laatste,jaar,persoonlijk,bereik,gemeenschappelijk,iedere,persoon,iedereen} -->
## Categories a booking cannot take

A booking cannot be assigned to eigen vermogen, or to a live checking
account. Those amounts are computed, or they come from the bank. A
spaarrekening (mirror) can take a term. The remainder category receives a
booking that no term matches.
<!-- {en:cannot[5],assign,bank,account,mirror,no,hit,eigen,vermogen} -->
<!-- {nl:cannot[5],toewijzen,bank,rekening,spaarrekening,geen,treffer,eigen,vermogen} -->
## The name in the left panel

The heading is the title stored for the login: the person, the center, or
the country. It is not the username.

A personal login with two or more accounts gets a second line. On
**Consolidated** that line is the word Consolidatie (or Consolidated). On
one account it is that account’s name. One account, or a center or country
login, shows the title only. The browser tab uses the title without the
second line.
<!-- {en:sidebar,title,subtitle,account,name[5],several,accounts,consolidated} -->
<!-- {nl:zijbalk,titel,ondertitel,rekening,naam[5],meerdere,rekeningen,consolidatie} -->
## The balance sheet window

**menu → Balance sheet** opens the sheet in its own window. A second click
uses that same window. **Logout** closes it. In the sheet, Escape closes an
open category first; with none open, Escape returns to the bookkeeping
window.

On the sheet, eigen vermogen is **bold black** when it still equals the
year’s opening amount, and **bold red** when it does not.

Where the menu offers them, **Manual journal posts** and **Automatic journal
posts** open from the same menu. **Export balance sheet** downloads the
workbook.
<!-- {en:balance[5],sheet[5],escape,logout,window[5],bold,black,red,opening,manual,journal,automatic,export,eigen,vermogen} -->
<!-- {nl:balans[5],blad[5],escape,uitloggen,balansvenster[5],vet,zwart,rood,beginstand,handmatig,journaal,automatisch,export,eigen,vermogen} -->
## Meals

The meal sheet is a separate page, not part of this matrix:
`https://expenses.apsurt.nl/maaltijden`. Its login is not the bookkeeping
login. A week runs Sunday to Saturday. **Dag** shows today, **Week** shows
the seven days, **Reserveren** shows only your own row.

Each day has five meals, **O M A L P** (standing for `Ontbijt`, `Middag`, `Avond`, `Laat`, and `Pakket`, respectively). A click switches a cell between an empty circle and a full one. You can change only your own row. The login `admin` is not a
row; it edits the extra counts for the current week.
<!-- {en:meals[5],meal,sheet,eat,reserve,view,O,M,A,L,P} -->
<!-- {nl:maaltijden[5],maaltijd,blad,eten,reserveren,weergave,O,M,A,L,P} -->

---
