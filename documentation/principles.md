# Booking principles

These rules keep the balance sheet consistent. **X** is always the signed bank
amount (in +, out −). “Increases with X” means the posted number changes by
+X (when X is negative, the displayed number goes down).

Ranges are type labels: only the one HIT / FROM / TO category moves; every
other category in the range stays put.

| Class | Codes | Role |
|---|---|---|
| **A** | 1000–1999 | Activa |
| **P** | 2001–2999 | Passiva other than 2000 |
| **R** | 3000–4999 | Resultaat (kosten and omzet, same sign) |
| **2000** | Eigen vermogen | Plug, never booked |
| **2100** | Verlies | Equals Saldo = numerical sum of R |

Kosten (3000–3999) and omzet (4000–4999) use the same sign. Saldo is the
numerical sum of all amounts in 3000–4999; passiva **2100** is that same
number.

---

## 1. 2000 is not a booking category

Eigen vermogen is never a HIT target and never a journal FROM or TO.
It is computed after every other post:

```text
2000 = (all activa) − (all passiva except 2000)
```

Passiva except 2000 includes 2050, 2055, 2100, 2500, and any other 2001–2999.

---

## 2. 2000 never changes

Whatever the mutation, **2000 stays the same**. That is the same statement as

```text
Δ activa = Δ (all passiva except 2000)
```

on every event. The booking and journal signs below are the counterparts that
make this true. 2100 moves with R, so a change in R is a change in passiva.

On the balance sheet the computed 2000 amount is compared to the Eigen
vermogen row in ``dbo.balance_opening`` for that year.

- **bold black** when it equals that opening amount — the identity held
- **bold red** when it differs

Red means the live calculation left the path in this file. Every mutation
above is written so 2000 does not move; if the plug is not still the opening
amount, a sign or an extra leg is wrong. 2000 itself is never booked.

---

## 3. Bank accounts 1051–1056

Six bank posts, of which five are live checking accounts and one is the
spaarrekening.

| Code | Kind | How the amount is known |
|---|---|---|
| 1051 | Bank algemeen | Live `dbo.account.balance` (rows in `dbo.transaction_{country}`) |
| 1053 | Bank huishoudelijke dienst | Live account (same table) |
| 1054 | Bank FPU | Live account (same table) |
| 1055 | Bank FOH | Live account (same table) |
| 1056 | Bank residentie ddkg | Live account (same table) |
| 1052 | Spaarrekening | Not readable as a live account |

1052 only communicates with 1051, plus bank interest.

**Transfers 1051 ↔ 1052.** They appear only on the 1051 statement (description
contains `spaarrekening`). The 1052 side is reconstructed into
`dbo.balance_transaction` by mirroring those 1051 rows with the sign flipped:
if X > 0 leaves 1051, live 1051 decreases by X and the mirror increases 1052
by X. Δ activa = 0, so 2000 is unchanged. Those 1051 spaar rows are not also
booked as A / P / R.

**Interest on 1052.** Written by hand into `dbo.balance_journal` (not mirrored
from the 1051 statement).

HIT onto 1051–1056 is invalid: the five checking posts already move with the
live account; 1052 moves only via the mirror and journals.

These rules are stored on `dbo.dim_category.category_role`:

| Role | Meaning | HIT | Journal |
|---|---|---|---|
| `remainder` | Unclassified / default HIT target | yes | yes |
| `never` | Eigen vermogen (plug) | no | no |
| `profit` | Verlies / resultaat plug (was 2100) | no | no |
| `no_hit` | Live bank posts other than the spaar pair | no | yes (as A) |
| `source` | Spaar source account (the checking statement that shows the transfers) | no | yes (as A) |
| `mirror` | Spaar mirror post (reconstructed counterpart) | no | yes (as A) |

`source` and `mirror` are treated like `no_hit` for HIT and journals. Runtime
code reads the spaar pair from those roles (plus `dbo.mapping` for the source
account), Eigen vermogen from `never`, and Verlies from `profit`, not from
hardcoded local codes.

`never` / `profit` / `no_hit` / `source` / `mirror` keep their coded names on
the matrix (`1051 Bank algemeen`). Only `balance` / `last_booked` are footer
labels.

Runtime reads Eigen vermogen from `never` and Verlies from `profit`, not from
hardcoded local codes.

---

## 4. Bank bookings (HIT)

A transaction on a live bank account (typically 1051) of signed amount X
always moves that bank post by +X (read from the account, not calculated).
The HIT category is the counterpart:

| HIT | Effect on that category |
|---|---|
| **R** (3000–4999) | increases with X → Saldo increases with X → 2100 increases with X |
| **P** (2001–2999) | increases with X |
| **A** (1000–1999, not 1051–1056) | decreases with X |

HIT onto 1051–1056 or 2000 is not used.

---

## 5. Journal mutations (amount X)

Class signs: **A = −1**, **P = R = +1**. One side always decreases with X
(`+= −X`). The other side takes the product of the two class signs
(A → A is (−1)×(−1) = +1, A → P is (−1)×(+1) = −1, and so on).

| | A | P | R |
|---|---|---|---|
| **A** | + | − | − |
| **P** | − | + | + |
| **R** | − | + | + |

---

## Why 2000 stays still (sketch)

Bank HIT of X on 1051:

- booked as R: 1051 +X, 2100 +X
- booked as P: 1051 +X, that P +X
- booked as A: 1051 +X, that A −X

Journal of X: each row above has ΔA = ΔP_other (P_other includes 2100).

1051 → 1052 transfer of X > 0: 1051 −X, 1052 +X.
