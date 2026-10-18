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

- `invoices` — **exactly one** owner per invoice (`ck_invoices_owner`: `debtor_id` xor
  `customer_id`).
  - For a **debtor**, the invoice is created with the order and starts prepared. Its
    `id` is also the primary/foreign key of the corresponding order; the administrator
    edits and sends the invoice from Bestellingen.
  - For a **customer**, the invoice is written *and paid* at Mollie checkout.
  - the administrator can always make an invoice without reference to an order, e.g. in case
    of a correction invoice (both credit and debet); it is emailed automatically after creation.
- `address(id, street, number, postalcode, city)` — `number` is **text** (`12`, `12a`, `12-3`).
  Both `debtors.address_id` and `customers.address_id` point here.
- `orders` — written the moment an account buyer orders on the website. Debtor only.
- `invoicelines`, `orderlines`, `stock`, `payments`, `reminders` as before.

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
6. **Order and invoice numbers share the invoice ID.** An order is displayed as
   `DB-{orders.invoice_id}` and its invoice as `BDF-{invoices.id}`. The order token remains
   the random 32-hex secret used in the order URL.

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
| `app/admin.py`      | open and paid invoice tables; pending orders; send and reminder dates. |
| `app/reminders.py`  | bookkeeping connection for bookings. |
| `sql/webshop.sql`   | schema with `orders.invoice_id` as PK/FK to `invoices.id`; order number `DB-{id}`, invoice number `BDF-{id}`. |

## 5. Schema (webshop)

`address`, `debtors`, `customers`, `orders` (`invoice_id` PK/FK, `token`), `orderlines`,
`invoices` (+ `token`, `mollie_id`, `mollie_settlement_id`, `sent_at`, `status`,
`ck_invoices_owner`, filtered unique index `ux_invoices_mollie`), `invoicelines`,
`payments`, `reminders`, `stock`.

Idempotent: guarded by `DB_ID` / `OBJECT_ID` / `COL_LENGTH` / `sys.indexes`, so it can
be re-run to bring an existing database up to date.

### Shared order and invoice key

`invoices.id` is the identity counter. For debtor purchases the invoice is inserted
first, then `orders.invoice_id` stores that same value as both PK and FK. Its public
order number is `DB-{invoice_id}` and its invoice number is `BDF-{invoice_id}`.
`orderlines.order_id` references `orders.invoice_id`; customer checkout creates an
invoice without an order row. Run `empty.sql` after the schema change; no existing
orders or invoices are carried into the new structure.

### Columns that are presently unused

The operator chose to keep these two `orders` columns even though the application no
longer needs them. They are candidates for a later drop.

| column                    | nullability  | status |
|---------------------------|--------------|--------|
| `orders.vat_cents`        | `NOT NULL`   | written by `create_account_order`; never read. The debtor invoice takes its VAT from the lines, not the order. |
| `orders.portokosten_cents`| `NULL`       | never written and never read. |

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
  names are `BDF-{id}`. `orders.token` remains 32 hex digits.
