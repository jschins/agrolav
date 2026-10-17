# Webshop buyer administration — refactor plan

Branch `sqlserver`. The shop's own data now lives in a **separate database**, `webshop`,
a sibling of `agrolav` on the same server. Its tables carry **no `shop_` prefix**.

The old `shop_*` tables in `agrolav` (and the `address_json` / street-split work) are
superseded and are dropped by the operator; `shop/sql/webshop.sql` is the single source
of truth for the new schema.

## 1. Model

Two kinds of buyer share one address table:

| table        | who                         | has orders | has invoices |
|--------------|-----------------------------|------------|--------------|
| `debtors`    | account buyers (on rekening)| yes        | yes          |
| `customers`  | Mollie buyers (iDEAL/card)  | no         | yes          |

- `address(id, street, number, postalcode, city)` — `number` is **text** (`12`, `12a`, `12-3`).
  Both `debtors.address_id` and `customers.address_id` point here.
- `orders` — written the moment an account buyer orders on the website. Debtor only.
- `invoices` — **exactly one** owner per invoice (`ck_invoices_owner`: `debtor_id` xor
  `customer_id`).
  - For a **debtor**, the invoice is written later by an administrator, after the mail
    order has been sent.
  - For a **customer**, the invoice is written *and paid* at Mollie checkout.
- `invoicelines`, `orderlines`, `stock`, `payments`, `reminders` as before.

## 2. Decisions taken

1. **Rekening flow writes an order only.** The website's `REKENING` completion no longer
   creates the invoice; it records the order. A new **admin invoice screen** turns an
   order into an invoice after the mail order is sent. Tracked by `orders.invoice_number`.
2. **Customer invoices carry a token.** A Mollie buyer views their purchase at
   `/betaling/{number}?token=…`; invoice numbers are sequential, so a bare number page
   would be guessable. Tracked by `invoices.token`.
3. **Mollie writes a customer + a paid invoice**, never an order.
4. `invoices.mollie_id` / `mollie_settlement_id` live on the invoice (not the order).

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
| `app/orders.py`     | connection layer (`connect`, `connect_bookkeeping`); `Address(street, number, postalcode, city)`; `save_address` / `address_by_id`; `get_order` / `orders_without_invoice` / `mark_invoiced`. Orders are written by `create_account_order` in `ledger`. Mollie-on-orders helpers removed. |
| `app/ledger.py`     | `save_shop_debtor` / `shop_debtor_by_code` on `debtors`; `create_customer_invoice` (Mollie); `create_debtor_invoice(order)` (admin); `attach_mollie`; `invoice_by_payment`; `mark_invoice_paid`; `get_invoice` resolves owner; `open_invoices` = debtor invoices only; `read_incoming_bookings` uses the bookkeeping connection. |
| `app/main.py`       | `/afrekenen` → address + customer + invoice + Mollie payment; `/mollie/webhook` → mark invoice paid; `/betaling/{number}?token=`; `/rekening/voltooi` → order only. |
| `app/pages.py`      | render the new `Order` / `Invoice`; paid vs open invoice. |
| `app/admin.py`      | new **invoice screen**: list un-invoiced debtor orders, turn one into an invoice. |
| `app/reminders.py`  | bookkeeping connection for bookings. |
| `sql/webshop.sql`   | new schema; `invoices.token`, `orders.invoice_number`. |

## 5. Schema (webshop)

`address`, `debtors`, `customers`, `orders` (+ `invoice_number`), `orderlines`,
`invoices` (+ `token`, `mollie_id`, `mollie_settlement_id`, `ck_invoices_owner`,
filtered unique index `ux_invoices_mollie`), `invoicelines`, `payments`, `reminders`,
`stock`.

Idempotent: guarded by `DB_ID` / `OBJECT_ID` / `COL_LENGTH` / `sys.indexes`, so it can
be re-run to bring an existing database up to date.

### Columns that are presently unused

The operator chose to keep the schema as it is, so these `orders` columns still exist
even though the application no longer needs them. They are candidates for a later drop.

| column                    | nullability  | status |
|---------------------------|--------------|--------|
| `orders.token`            | `NOT NULL`   | left over from the earlier per-order return page (`/bestelling/{id}?token=…`), which `invoices.token` replaced. `create_account_order` still writes it; nothing reads it. |
| `orders.vat_cents`        | `NOT NULL`   | written by `create_account_order`; never read. The debtor invoice takes its VAT from the lines, not from the order. |
| `orders.portokosten_cents`| `NULL`       | never written and never read. |

The Python model mirrors the first two: `Order.token` and `Order.vat_cents` are populated
by `order._order_from_row` only so the read path matches the columns. When the columns
are dropped, drop these fields, the `o.token` / `o.vat_cents` entries in `_ORDER_SELECT`,
the `token` / `vat_cents` values in `create_account_order`'s `INSERT`, and the `secrets`
token it generates for the order.

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

- `shop/sql/webshop.sql` re-runs clean (10 tables, 7 FKs, `ck_invoices_owner`).
- compile-check every `app/*.py`.
- `python -m unittest shop.tests.test_ledger shop.tests.test_shop shop.tests.test_admin`
  — 20 tests, green on repeated runs (integration tests hit the live `webshop`
  database, as they did before).

