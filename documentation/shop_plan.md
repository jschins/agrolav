# Webshop buyer administration — refactor plan

Branch `sqlserver`. The shop's own data now lives in a **separate database**, `webshop`,
a sibling of `agrolav` on the same server. Its tables carry **no `shop_` prefix**.

The old `shop_*` tables in `agrolav` (and the `address_json` / street-split work) are
superseded and are dropped by the operator; `shop/sql/webshop.sql` is the single source
of truth for the new schema.

# Model

Two kinds of buyer share one address table:

| table        | who                         | has orders | has invoices |
|--------------|-----------------------------|------------|--------------|
| `debtors`    | account buyers (on rekening)| yes        | yes          |
| `customers`  | Mollie buyers (iDEAL/card)  | no         | yes          |

- `invoices` — owned via `customer_id` and/or `debtor_id` (the old `ck_invoices_owner`
  xor check was dropped).
  - For a **debtor**, the invoice is created with the order and starts prepared. Its
    `id` is also the primary/foreign key of the corresponding order; the administrator
    edits and sends the invoice from Bestellingen.
  - For a **customer**, the invoice is written *and paid* at Mollie checkout.
  - the administrator can always make an invoice without reference to an order, e.g. in case
    of a correction invoice (both credit and debet); it is emailed automatically after creation.
- `address(id, street, number, postalcode, city)` — `number` is **text** (`12`, `12a`, `12-3`).
  Both `debtors.address_id` and `customers.address_id` point here.
- `orders` — written the moment an account buyer orders on the website. Debtor only.
- `invoicelines`, `orderlines`, `stock`, `bookings`, `payments`, `reminders`.

## 2. Decisions taken

1. **Rekening flow writes an invoice and order together.** The invoice is inserted first;
   `orders.invoice_id` uses that same ID and is both the order's primary key and a foreign
   key to `invoices.id`.
2. **Customer invoices carry a token.** A Mollie buyer views their purchase at
   `/betaling/{number}?token=…`; invoice numbers are sequential, so a bare number page
   would be guessable. Tracked by `invoices.token`.
3. **Mollie writes a customer + a paid invoice**, never an order.
4. `invoices.mollie_id` / `mollie_settlement_id` live on the invoice (not the order).
5. **The payment↔invoice link is `invoices.mollie_id` alone.** The webhook and the
   return-page poll find the invoice by the stored Mollie payment id, so no Mollie
   `metadata` is sent. The earlier `metadata.order_id` cross-check was redundant with
   that stored id (and with `ux_invoices_mollie`); the amount check remains.
6. **Order and invoice numbers share the invoice ID** — see § Invoice numbering.

## 3. Connections

The app now needs two connections:

- **webshop** — every shop table (`address`, `debtors`, `customers`, `orders`,
  `orderlines`, `invoices`, `invoicelines`, `payments`, `reminders`, `stock`).
  `connect()` returns this. URL: `WEBSHOP_DATABASE_URL`, else derived from
  `HUB_DATABASE_URL` by swapping `DATABASE=agrolav` → `DATABASE=webshop`.
- **agrolav** — read-only for the general ledger (`dbo.transaction_beheer_boog`,
  `dbo.account`). `connect_bookkeeping()` returns this. URL: `HUB_DATABASE_URL`.

## 4. Module changes

| file                | change |
|---------------------|--------|
| `app/orders.py`     | connection layer (`connect`, `connect_bookkeeping`); `Address(street, number, postalcode, city)`; order lookup by the shared invoice ID or token. Orders are written by `create_account_order` in `ledger`. |
| `app/ledger.py`     | `save_shop_debtor` / `shop_debtor_by_code` on `debtors`; `create_account_order` inserts the invoice and uses its `id` for `orders.invoice_id`; `create_customer_invoice` (Mollie); `attach_mollie`; `invoice_by_payment`; `get_invoice` resolves owner; `open_invoices` = debtor invoices only; `read_incoming_bookings` uses the bookkeeping connection. |
| `app/main.py`       | `/afrekenen` → address + customer + invoice + Mollie payment; `/mollie/webhook` → mark invoice paid; `/betaling/{number}?token=`; `/rekening/voltooi` → order and invoice together. |
| `app/pages.py`      | render the new `Order` / `Invoice`; paid vs open invoice; the order page shows `order.token`. |
| `app/admin.py`      | open, paid, and Mollie invoice tables; pending and sent orders; bank refresh registration and matching. |
| `app/reminders.py`  | bookkeeping connection for bookings. |
| `sql/webshop.sql`   | schema with `orders.invoice_id` as PK/FK to `invoices.id`; order number `DB-{id}`, invoice number `DBF-{id}`. |

## 5. Schema (webshop)

`address`, `debtors`, `customers`, `orders` (`invoice_id` PK/FK, `token`), `orderlines`,
`invoices` (+ `token`, `mollie_id`, `mollie_settlement_id`, `sent_at`, `paid_at`,
`status`, filtered unique index `ux_invoices_mollie`), `invoicelines`,
`bookings`, `payments`, `reminders`, `stock`.

Idempotent: guarded by `DB_ID` / `OBJECT_ID` / `COL_LENGTH` / `sys.indexes`, so it can
be re-run to bring an existing database up to date.

### Invoice numbering

Public numbers are derived from `invoices.id` (identity). There is no separate
number column; `ledger.invoice_number` / `orders.order_number` format the strings.

1. **A new `invoice_id` is allocated when an order (or Mollie checkout) is placed.**
   The invoice row is inserted first; SQL Server returns `invoices.id`.
2. **Invoice display number:** `DBF-{invoice_id}` (e.g. `DBF-100000`).
3. **Every order has its invoice.** For a debtor purchase, `orders.invoice_id` is
   set to that same id and is both the order’s primary key and a foreign key to
   `invoices.id`. `orderlines.order_id` references `orders.invoice_id`.
4. **Order display number:** `DB-{invoice_id}` (e.g. `DB-100000`).
5. **Only debtor orders are stored in `orders`.** Mollie (customer) checkouts write
   a paid invoice (and customer) only — no order row — because for Mollie buyers
   the invoice and the purchase are the same thing; a separate order would be
   redundant.

| Buyer        | DB row(s)                         | Public labels                          |
|--------------|-----------------------------------|----------------------------------------|
| Debtor       | `invoices` + `orders` (same id)   | order `DB-{id}`, invoice `DBF-{id}`    |
| Mollie customer | `invoices` only                | invoice `DBF-{id}` (no `DB-…` order)   |

The order URL token remains a random 32-hex secret (`orders.token`), independent
of the numeric id. Customer invoices use `invoices.token` the same way.

Run `empty.sql` after the schema change; no existing orders or invoices are
carried into the new structure.

### Columns that are presently unused

The operator chose to keep these two `orders` columns even though the application no
longer needs them. They are candidates for a later drop.

| column                    | nullability  | status |
|---------------------------|--------------|--------|
| `orders.vat_cents`        | `NOT NULL`   | written by `create_account_order`; never read. The debtor invoice takes its VAT from the lines, not the order. |

`orders.portokosten_cents` was dropped; postage lives on `invoices.portokosten_cents` only.

`Order.vat_cents` is still populated by `_order_from_row` so the read path matches the
column. To drop `vat_cents` later: remove the `o.vat_cents` entry from `_ORDER_SELECT`,
the `vat_cents` value from `create_account_order`'s `INSERT`, and the `vat_cents` field
from `Order` / `_order_from_row`.

## 6. Removed legacy (cleanup pass)

Dead code found by an unused-symbol sweep and deleted:

- `orders.py`: `identity`, `set_debtor_address`, `insert_order` (orders are written by
  `create_account_order` in `ledger`).
- `ledger.py`: `match_settlement`.
- `pages.py`: `rekening_done_page`, and dead CSS (`.hero`, `.kicker`, `.lede`,
  `.band blockquote`, `.band cite`).
- `rekening.py`: reduced to the signed count-cookie helpers (`dump_counts`,
  `load_counts`, `counts_from_form`, `order_lines`); the JSON company/order store
  (`read_rekening`, `find_company`, `append_order`, `order_by_number`) is gone.
- `catalog.py`: `Catalog.require` and the never-rendered `hero_kicker`, `hero_title`,
  `hero_text`, `quote`, `quote_by` fields (and their parsing).
- `main.py`: `Settings.rekening_path` and the `SHOP_REKENING` environment variable.

Still present in `catalog.json` but no longer read by any code: the `hero_kicker`,
`hero_title`, `hero_text`, `quote`, and `quote_by` keys (authored content, left in place).

## 7. Verification

- `shop/sql/webshop.sql` creates `orders.invoice_id` as a PK/FK to `invoices.id`;
  `shop/sql/empty.sql` clears all shop rows without carrying old data forward.
- compile-check every `app/*.py`.
- `python -m unittest shop.tests.test_shop shop.tests.test_ledger shop.tests.test_admin`
  — integration suite green against an emptied and freshly initialized `webshop`.
- debtor order IDs and invoice IDs are the same; order names are `DB-{id}` and invoice
  names are `DBF-{id}`. `orders.token` remains 32 hex digits.
