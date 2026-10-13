# De Boog book shop

A small shop for paper books. It listens on port **9000**.

Interim address: `http://expenses.apsurt.nl:9000`  
Later address: `https://deboog.apsurt.nl`

The shop is one process: a home page, shelves, an events page, an about page,
a page per book, a cart, and Mollie checkout. A paid order is a paper copy
sent to the address on the order. There is no download.

The shop does not open the bookkeeping database. Orders are
`shop/data/orders.sqlite` on the computer that runs this process.

The two books are the paper editions, with the cover files in `shop/files/`:

- Jacques Phillippe, *De innerlijke rust* — € 8,75
- Catharina van Siena, *De Dialoog* — € 14,75

Those prices are the paper prices on [deboog-uitgeverij.nl](https://deboog-uitgeverij.nl/),
VAT included. The price charged is the book price. Postage is not added.

## What the customer does

1. Opens the shop. Home, Planken, Agenda, and Over follow the Colophon layout.
2. Opens a book. The cover is the file in `shop/files/`.
3. Chooses **Koop dit exemplaar** or adds the book to the cart.
4. Enters a name, street, postcode, city, and email.
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
