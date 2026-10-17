# De Boog book shop

A small shop for paper books. It listens on port **9000**.

Interim address: `http://expenses.apsurt.nl:9000`  
Later address: `https://deboog.apsurt.nl`

The shop is one process: a home page, shelves, an events page, an about page,
a page per book, a cart, and Mollie checkout. A paid order is a paper copy
sent to the address on the order. There is no download.

The shop keeps its own records in the SQL Server database `webshop`, a
sibling of the bookkeeping database `agrolav` on the same server. The shop
reads the general ledger from `agrolav` and writes nothing there.

The prices charged are the cents stored on each book. Postage is not added.
The live shelf in `catalog.json` is still the small one. The old site’s list,
about 400 titles, is kept under `shop/old_website/` and is not the live catalogue yet.

## Buyer administration

There are two kinds of buyer, and both point at one row of `address`:

- **Debtors** are companies that buy on account. A debtor has orders and
  invoices.
- **Customers** are buyers who pay online through Mollie. A customer has
  invoices only.

The address is `street`, `number`, `postalcode`, and `city`. The number is
text, so `12`, `12a`, and `12-3` are all possible.

An **order** is written the moment an account buyer places it on the
website. It carries a token, a status, the amounts, and one row per book in
`orderlines`.

An **invoice** has a unique number and its lines are in `invoicelines`. Each
invoice belongs to a debtor or to a customer, never both. A debtor is
invoiced later, by an administrator through the admin site, after the mail
order has been sent, and is told to put the invoice number in the payment
description. A customer's invoice is written at checkout, already paid.

Payment matching and reminders run apart from the website, with `remind`
from the `shop` directory. A booking on the Boog account counts when its
description contains the invoice number and the money is coming in. A short
payment leaves the rest open. Several invoice numbers are settled only when
the booking equals their open sum. The same booking is not applied twice.
Reminders go out seven days before the due date, on the due date, and
fourteen and thirty days after, and each send is recorded in `reminders`.

`beheer_boog` is country 6 in the bookkeeping database. Its bookings are
`dbo.transaction_beheer_boog`. That database remains the general ledger.
The shop should read it and should not write a booking, a category, or a
`modification`. One debiteuren post on the balance is enough. Four hundred
titles, and every person who buys on account, do not each get a ledger
account. The shop keeps the subledger: who owes which invoice, and which
booking has settled it.

### What an invoice must carry

An order on account becomes an invoice with a stable number, a debtor or a
customer, an email, a date, a due date, and lines. Each line needs the book
slug, the quantity, and the unit price the customer is asked to pay. The
amount the customer must transfer is stored on the invoice as its own
figure, so a bank booking can be matched against it.

The old site asked companies that order on account for a VAT number, and
asked private customers either to pay with iDEAL or to transfer before
dispatch. Both are invoices. The difference is whether the books may leave
before the open amount is zero. A Mollie payment that is already `paid` is
not an open debt. A Mollie payout arrives later as one bank booking for
many sales, matched on Mollie’s settlement reference, not on an invoice
number.

### How the shop infers that an invoice is paid

The customer is told to put the invoice number in the payment description.
A booking on the Boog receiving account counts as a payment of that invoice
when the description contains that number and the amount is money coming in.
The shop stores the `transaction_id` it has already applied, so the same
booking is not applied twice. A partial amount leaves the remainder open.
Several invoice numbers in one description are applied only when the
booking equals the sum of those open amounts. Anything else stays unmatched
for a person to assign. The shop does not mark an invoice paid by hand and
then hope the bank agrees. The booking is the payment.

### Reminder mail

A separate pass sends mail for invoices whose open amount is still above
zero. It does not run inside a page request. Each step is recorded with
the invoice number, the address, and the moment, so a restart does not
send the same step again. A step is skipped once the next read of
`beheer_boog` shows that the open amount is zero.

A usable rhythm is a note seven days before the due date, a note on the
due date, and notes fourteen and thirty days after it. The mail states the
invoice number, the open amount, the IBAN, and the description the bank
match requires. The published address `info@deboog.nl` is the contact the
customer already has. The mailbox credentials stay in the server
environment, not in git.

### Cost of one copy sold

The selling price and the cost of getting that copy into the customer’s
hands are different numbers. The invoice line stores the selling price.
The costs are not columns of `invoicelines`.
None of the three costs below is invented here, and none is posted to
`beheer_boog` until the balance has a post for it.

- **Drukkosten.** The cost of printing that copy. The balance has no post
  for this yet. Until it does, the shop can store a cents amount per copy,
  or the cost of a print run and the number of copies in that run. A later
  run does not change the cost of copies already sold. No local code is
  chosen here.
- **Vrijwilligersbijdrage.** The handling contribution for one copy. It is
  not postage and it is not a wage. Store it as cents on the book, in
  `book_costs`, not on the invoice line. Whether the customer is charged
  for it is still open. Today the customer is charged the book price only.
- **Portokosten.** The cost of one shipment. It belongs to the order first.
  Splitting it across the books in that order waits on a rule (by copy, by
  weight, or left on the order). The shop still does not add a postage
  tariff, and this note does not supply one. The old site sends twice a
  week. That is the rhythm, not a price.

The invoice line stores the selling price only. The cost amounts above are
not columns of `invoicelines`.

### Catalogue and stock

The catalogue stays in `catalog.json`. Four hundred titles are still one
document that can be edited and diffed, and the covers stay files in
`shop/files/`. Title, author, ISBN, and the other descriptive fields never
move into the database.

The buyer administration lives in SQL Server, not in a file. An order is one
row in `orders` with its books as rows in `orderlines`; an invoice is one
row in `invoices` with its books as rows in `invoicelines`. A JSON list of
items is not a column: one hundred copies of one book are one line, with the
slug, the number of copies, and the unit price charged.

An invoice line stores the slug and the cents charged at that moment, so a
later price change does not rewrite the invoice. The title is read from
`catalog.json` when the invoice or order page is printed.

Stock is the catalogue figure that leaves the JSON file. Saving an invoice
and lowering `voorraad` has to succeed or fail together, so that number
lives in the `stock` table.

## What the customer does

1. Opens the shop. Home, Agenda, Over, Rekening, and Winkelwagen follow the Colophon layout.
2. Opens a book. The cover is the file in `shop/files/`.
3. Chooses **Koop dit exemplaar** or adds the book to the cart.
4. Enters a name, street name, house number, postcode, city, and email.
5. **Betaal met Mollie** sends the customer to Mollie's page. Card numbers are entered there, not on this site.
6. Mollie calls `POST /mollie/webhook`. The return page also asks Mollie for the payment status.
7. When the status is `paid`, the order page shows the books and the delivery address.

## Money and tax

Prices in `catalog.json` are VAT-inclusive euro cents. The rate is 9%,
the Dutch reduced rate for paper books, shown as included in the price.
Confirm the rate with your tax adviser.
A sale to a consumer in another EU country can require that country's VAT rate.

## Run locally

From `shop/`, with `SHOP_DEV_PAYMENTS=1`, the pay button opens a local stand-in
instead of Mollie. No money is taken. Do not set that flag on the server.

On this Windows machine, from `shop/` after the dependencies are installed:

```text
$env:SHOP_DEV_PAYMENTS="1"
shop
```

Then open `http://127.0.0.1:9000`.

## Mollie, on the server

Put `MOLLIE_API_KEY` and `SHOP_SECRET` in the server environment (the same
place as the other secrets, not in git). A test key starts with `test_`.
A live key starts with `live_`. When the key is set, the local stand-in is
not used.

For the interim host, the process must be reachable on port 9000 and Mollie
must be able to call the webhook:

```text
SHOP_HOST=0.0.0.0
SHOP_PORT=9000
SHOP_PUBLIC_BASE_URL=http://expenses.apsurt.nl:9000
SHOP_SECRET=...
MOLLIE_API_KEY=test_...
```

`SHOP_PUBLIC_BASE_URL` is written into the Mollie payment as the return
address and the webhook address.

## Move to deboog.apsurt.nl

When that name exists, keep the shop on `127.0.0.1:9000` and let Caddy serve
the name:

```text
deboog.apsurt.nl {
    reverse_proxy 127.0.0.1:9000
}
```

Set `SHOP_PUBLIC_BASE_URL=https://deboog.apsurt.nl` and
`SHOP_HOST=127.0.0.1`.

## Add a book

1. Put the cover image in `shop/files/`. The name has no folders.
2. Add an object to the `books` list in `catalog.json`: `slug`, `title`, `author`, `genre`, `summary`, `price_cents`, `cover`.
3. Restart the shop.

The visiting hours in the footer are the hours published for Keizersgracht 218-B.
Change `place` and `hours` in `catalog.json` if that counter is not this shop.
