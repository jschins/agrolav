# De Boog book shop

A small shop for digital books. It listens on port **9000**.

Interim address: `http://expenses.apsurt.nl:9000`  
Later address: `https://deboog.apsurt.nl`

Shopify cannot run on a port of this server. WooCommerce would be a second
content system and database beside the bookkeeping site. This shop is one
process: a page per book, a cart, Mollie checkout, and a download after
Mollie confirms the payment.

The shop does not open the bookkeeping database on computer A. Orders are
`shop/data/orders.sqlite` on the computer that runs this process (computer B).

## What the customer does

1. Opens one book page. That page is the advertisement.
2. Chooses **Koop dit boek** (one link for that book) or adds several books to the cart.
3. Enters an email address on the checkout page.
4. **Betaal met Mollie** sends the customer to Mollie's page. Card numbers are entered there, not on this site.
5. Mollie calls `POST /mollie/webhook`. The return page also asks Mollie for the payment status.
6. When the status is `paid`, the order page shows one download link per book.

There is no paper book and no shipping address.

## Money and tax

Prices in `catalog.json` are VAT-inclusive euro cents. The sample rate is 9%,
the Dutch reduced rate for digital books, shown as included in the price.
The seller line states that the shop is a reseller using the rights holder's
permission, and is not the publisher. Confirm the rate with your tax adviser.
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
`SHOP_HOST=127.0.0.1`. The book pages, cart, and downloads stay the same.

## Add a book

1. Put the file you have permission to sell in `shop/files/`. The name has no folders.
2. Add an object to the `books` list in `catalog.json`: `slug`, `title`, `author`, `rights_holder`, `summary`, `price_cents`, `filename`.
3. Restart the shop.

The two sample books are placeholders. Replace them before taking real payments.
