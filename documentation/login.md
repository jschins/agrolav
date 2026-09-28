# Inlogniveaus

Landen zonder balans hebben drie inlogniveaus. Landen met balans
(`dbo.country.has_balance`) hebben er vier.

De drie gemeenschappelijke niveaus zijn country, center en person. Het
vierde niveau is unit. Elk niveau heeft een eigen tabel waarin de
gebruikersnaam staat.

Voor de gebruiker heten die vier niveaus, in een land met balans,
stichting, sectie, deel en werkeenheid.


| Niveau  | Tabel         | Stichting   |
| ------- | ------------- | ----------- |
| country | `dbo.country` | stichting   |
| center  | `dbo.center`  | sectie      |
| person  | `dbo.person`  | deel        |
| unit    | `dbo.unit`    | werkeenheid |


---



## Stichting Instudo

<table>
<colgroup>
<col style="width:22%" />
<col style="width:19.5%" />
<col style="width:19.5%" />
<col style="width:19.5%" />
<col style="width:19.5%" />
</colgroup>
<thead>
<tr>
<th style="text-align:left">Niveau</th>
<th colspan="4" style="text-align:center">Login-namen</th>
</tr>
</thead>
<tbody>
<tr>
<td style="text-align:left">Stichting</td>
<td colspan="4" style="text-align:center"><code>beheer_instudo</code></td>
</tr>
<tr>
<td style="text-align:left">Sectie</td>
<td colspan="2" style="text-align:center"><code>instudo_sia</code></td>
<td colspan="2" style="text-align:center"><code>instudo_sib</code></td>
</tr>
<tr>
<td style="text-align:left">Deel</td>
<td style="text-align:center"><code>sia</code></td>
<td style="text-align:center"><code>hd_sia</code></td>
<td style="text-align:center"><code>sib</code></td>
<td style="text-align:center"><code>hd_sib</code></td>
</tr>
<tr>
<td style="text-align:left">Werkeenheid</td>
<td style="text-align:center"><code>aenstal</code></td>
<td></td>
<td style="text-align:center"><code>leidenhoven</code></td>
<td style="text-align:center"><code>hd_leidenhoven</code></td>
</tr>
<tr>
<td></td>
<td style="text-align:center"><code>hogeland</code></td>
<td style="text-align:center"><code>hd_hogeland</code></td>
<td style="text-align:center"><code>den_eker</code></td>
<td style="text-align:center"><code>hd_den_eker</code></td>
</tr>
<tr>
<td></td>
<td style="text-align:center"><code>de_stade</code></td>
<td style="text-align:center"><code>hd_de_stade</code></td>
<td style="text-align:center"><code>lepelenburg</code></td>
<td style="text-align:center"><code>hd_lepelenburg</code></td>
</tr>
<tr>
<td></td>
<td style="text-align:center"><code>de_borcht</code></td>
<td style="text-align:center"><code>hd_de_borcht</code></td>
<td style="text-align:center"><code>jan_luijken</code></td>
<td style="text-align:center"><code>hd_jan_luijken</code></td>
</tr>
<tr>
<td></td>
<td style="text-align:center"><code>concertgebouw</code></td>
<td></td>
<td></td>
<td></td>
</tr>
</tbody>
</table>


Het sia-deel van sectie `instudo_sia` heeft 5 werkeenheden. Drie daarvan hebben een bijbehorende huishoudelijke dienst: Hogeland, De Stade en De Borcht. Aenstal en Concertgebouw hebben die niet.

Het sib-deel van sectie `instudo_sib` heeft 4 werkeenheden. Alle vier hebben een huishoudelijke dienst.

Instudo heeft 19 automatisch gedownloade rekeningen en 2 afgeleide spaarrekeningen.   
Van die 19 zijn er 18 rekeningen van evenzoveel werkeenheden, en 1 van SVOa. SVOa heeft geen eigen login.

---



## Overzicht

Op elk van de vier inlogniveaus zijn resultaat en balans in te zien. Die
twee samen heten voorlopig **overzicht**.

- Op werkeenheid-niveau ziet elke huishoudelijke dienst het eigen overzicht.
Elk centrum ziet de consolidatie van het eigen overzicht met dat van de
bijbehorende huishoudelijke dienst. Die consolidatie heet voorlopig
**hd_sibling-consolidatie**.
- Op deel-niveau zijn de overzichten van de centra en van hun
huishoudelijke dienst apart zichtbaar.
- Op sectie-niveau eveneens.
- Op stichting-niveau vindt hd_sibling-consolidatie plaats.

Het overzicht kan op elk inlogniveau lokaal worden gedownload met de knop
**Export** in het Resultaat-venster.

Op stichting-niveau staat er een extra menu-item, **Export zip**. Dat
levert een zip-bestand met de 18 overzichten van de werkeenheden en het
overzicht van de stichting: 19 bestanden.

---



# Dubbele login

Alle vier niveaus bewaren een scrypt-wachtwoordhash. Person- en unit-logins
kunnen ook een mobiel nummer instellen en de login daarna bevestigen met
een sms-code voor eenmalig gebruik.

---



## Vier-niveaus-inlogschema

SMS: inloggen in twee stappen wanneer `mobile_phone` is gezet.

IP-gate: de vereniging van de lijst `dbo.administrator` en de
`egress_ip`-lijst die op de eigen gebruikersnaam staat, wanneer
`agrolav@agrolav:/etc/agrolav/hub.env` `HUB_LOGIN_GATING=1` heeft staan;
bij waarde 0 vindt géén IP-gating plaats.


| Login   | balans         | uitgaven       |
| ------- | -------------- | -------------- |
| Country | `egress_ip`    | `egress_ip`    |
| Center  | `egress_ip`    | `egress_ip`    |
| Person  | `egress_ip`    | `mobile_phone` |
| Unit    | `mobile_phone` |                |


De API om het wachtwoord in te stellen weigert country- en center-sessies,
ook bij een directe aanroep.

---

## Browser path

```text
Browser → client POST /api/login
       → hub POST /api/auth/login  (username + password + client_ip)
            → person with mobile_phone: { otp_required, otp_token }
            → otherwise { user }
       → hub POST /api/auth/otp/verify  (person SMS step only)
       → client sets the session cookie
```

Hash format (shared by hub and client):

```text
scrypt$16384$8$1$<urlsafe-salt>$<urlsafe-digest>
```

Helpers live in `shared/`. New persons are inserted with a hash of the
formula password, so they can log in until they set their own.

---



## Set password

Menu item only when `access === "personal"`. UI: current password, new
password, confirm, optional mobile (`+316…` or `06…`). **Save** / **Cancel**;
the header menu is hidden on this page.

APIs: client `POST /api/auth/password` → hub `POST /api/auth/password`.
Rejects if current does not match, if new ≠ confirm, or if new is empty.

---



## SMS one-time code

Keys in env, not git: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_FROM`. If any of the three is missing, the hub still prints the
code so local testing works without sending SMS.

After password OK, a person or unit login with `mobile_phone` set gets
`otp_required` instead of a session. The client shows a 6-digit field and
**Resend**. Hub `POST /api/auth/otp/verify` and `POST /api/auth/otp/resend`.
Country and center never take this path.

---



## Schema

On `dbo.person`:


| Column          | Type                 | Role                    |
| --------------- | -------------------- | ----------------------- |
| `password_hash` | `NVARCHAR(256) NULL` | scrypt; never plaintext |
| `mobile_phone`  | `NVARCHAR(32) NULL`  | E.164                   |


These columns are in `hub/sql/phase_c.sql` for new installs. Live databases
that predate them need the same `ALTER` on **local and remote** so they
stay identical:

```sql
USE agrolav;
GO

IF COL_LENGTH(N'dbo.person', N'password_hash') IS NULL
    ALTER TABLE dbo.person ADD password_hash NVARCHAR(256) NULL;
GO

IF COL_LENGTH(N'dbo.person', N'mobile_phone') IS NULL
    ALTER TABLE dbo.person ADD mobile_phone NVARCHAR(32) NULL;
GO
```

Backfill hashes with a Python loop (unique scrypt salt per row), not a
single SQL `UPDATE`. `hub/scripts/` has the one-off hasher.

---



## Files


| Area              | Where                                              |
| ----------------- | -------------------------------------------------- |
| Hash helpers      | `shared/` (re-export in `client/app/passwords.py`) |
| Authenticate      | `hub/app/user_store.py`                            |
| Login + OTP       | `hub/app/main.py`, `hub/app/person_otp.py`         |
| Set password UI   | `client/frontend/src/App.tsx`                      |
| Add-person mobile | hub wizard `_ADD_PERSON_HTML`                      |


