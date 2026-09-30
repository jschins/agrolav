# Inlogniveaus

Landen zonder balans hebben drie inlogniveaus. Landen met balans
(`dbo.country.has_balance`) hebben er vier.

De drie gemeenschappelijke niveaus zijn country, center en person. Het
vierde niveau is unit. Elk niveau heeft een eigen tabel waarin de
gebruikersnaam staat.

Voor de gebruiker heten die vier niveaus, in een land met balans,
stichting, sectie, deel en werkeenheid.



| Niveau  | Tabel         | Gebruiker                                        |
| ------- | ------------- | ------------------------------------------------ |
| country | `dbo.country` | *Stichting*                                      |
| center  | `dbo.center`  | *Sectie*                                         |
| person  | `dbo.person`  | *Deel*                                           |
| unit    | `dbo.unit`    | *Eenheid*: |
|||+ Werkeenheid |
|||+ Huishoudelijke Dienst|


---

<!-- {en:levels[5],foundation,section,part,unit,balance} -->
<!-- {nl:niveaus[5],stichting,sectie,deel,eenheid,balans} -->

## Stichting Instudo

<!-- NOTE: this formatting automatically disppears upon editing in Preview -->

<table>
  <tr>
    <td>Niveau</td>
    <td colspan="4">Login-namen</td>
  </tr>
  <tr>
    <td>Stichting</td>
    <td colspan="4"><code>beheer_instudo</code></td>
  </tr>
  <tr>
    <td>Sectie</td>
    <td colspan="2"><code>instudo_sia</code></td>
    <td colspan="2"><code>instudo_sib</code></td>
  </tr>
  <tr>
    <td>Deel</td>
    <td><code>sia</code></td>
    <td><code>hd_sia</code></td>
    <td><code>sib</code></td>
    <td><code>hd_sib</code></td>
  </tr>
  <tr>
    <td>Werkeenheid</td>
    <td><code>aenstal</code></td>
    <td></td>
    <td><code>leidenhoven</code></td>
    <td><code>hd_leidenhoven</code></td>
  </tr>
  <tr>
    <td></td>
    <td><code>hogeland</code></td>
    <td><code>hd_hogeland</code></td>
    <td><code>den_eker</code></td>
    <td><code>hd_den_eker</code></td>
  </tr>
  <tr>
    <td></td>
    <td><code>de_stade</code></td>
    <td><code>hd_de_stade</code></td>
    <td><code>lepelenburg</code></td>
    <td><code>hd_lepelenburg</code></td>
  </tr>
  <tr>
    <td></td>
    <td><code>de_borcht</code></td>
    <td><code>hd_de_borcht</code></td>
    <td><code>jan_luijken</code></td>
    <td><code>hd_jan_luijken</code></td>
  </tr>
  <tr>
    <td></td>
    <td><code>concertgebouw</code></td>
    <td></td>
    <td></td>
    <td></td>
  </tr>
</table>


Het sia-deel van sectie `instudo_sia` heeft 5 werkeenheden. Drie daarvan hebben een bijbehorende huishoudelijke dienst: Hogeland, De Stade en De Borcht. Aenstal en Concertgebouw hebben die niet.

Het sib-deel van sectie `instudo_sib` heeft 4 werkeenheden. Alle vier hebben een huishoudelijke dienst.

Instudo heeft 19 automatisch gedownloade rekeningen en 2 afgeleide spaarrekeningen.  
Van die 19 zijn er 18 rekeningen van evenzoveel werkeenheden, en 1 van SVOa. SVOa heeft geen eigen login.

---

<!-- {en:foundation[5],instudo[5],section,part,unit,work-unit,login[5],levels[5]} -->
<!-- {nl:stichting[5],instudo[5],sectie,deel,eenheid,werkeenheid,inlogniveaus[5],inloggen[5]} -->

## Resultaat en balans per inlogniveau

Op elk van de vier inlogniveaus zijn resultaat en balans in te zien, hieronder samen *overzicht*  genoemd.

- Op eenheid-inlogniveau ziet elke huishoudelijke dienst het eigen overzicht.
Elke werkeenheid ziet de consolidatie van het eigen overzicht met dat van de
bijbehorende huishoudelijke dienst.
- Op sectie- en deel-inlogniveau zijn de overzichten van de werkeenheid en geassocieerde
huishoudelijke dienst apart zichtbaar.
- Op stichting-niveau wordt weer geconsolideerd.

Het overzicht kan op elk inlogniveau lokaal worden gedownload met de knop
**Export** in het Resultaat-venster.

Op eenheid- en deel-inlogniveaus is er een extra menuknop met maandelijkse overzichten beschikbaar.

Op stichting-niveau staat er een extra menuknop, **Export zip**. Dat
levert een zip-bestand met de 18 overzichten van de werkeenheden en het
overzicht van de stichting: 19 bestanden.

---

<!-- {en:result[5],balance[5],login-level[5],overview} -->
<!-- {nl:resultaat[5],balans[5],inlogniveau[5],overzicht} -->

# Dubbele login

Alle vier niveaus bewaren een scrypt-wachtwoordhash. Person- en unit-logins
kunnen ook een mobiel nummer instellen en de login daarna bevestigen met
een sms-code voor eenmalig gebruik met tweestaps verificatie.

---

<!-- {en:double[5],password,hash,scrypt} -->
<!-- {nl:dubbele[5],wachtwoord,hash,scrypt} -->

## SMS en IP-gate per inlogniveau

SMS: inloggen in twee stappen wanneer `mobile_phone` is gezet.

IP-gate: de vereniging van de lijst `dbo.administrator` en de `egress_ip`-lijst die op de eigen gebruikersnaam staat,  
wanneer `agrolav@agrolav:/etc/agrolav/hub.env` `HUB_LOGIN_GATING=1` heeft staan;  
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

<!-- {en:sms[5],ip[5],gate[5],login-level[5],phone,address} -->
<!-- {nl:sms[5],ip[5],poort[5],inlogniveau[5],telefoon,adres} -->

## Login request path and scrypt hash

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

<!-- {en:request[5],path[5],scrypt[5],hash[5],password} -->
<!-- {nl:verzoek[5],pad[5],scrypt[5],hash[5],wachtwoord} -->

## Set password

UI: new password, confirm, optional mobile (`+316…` or `06…`). **Save** / **Cancel**;
the header menu is hidden on this page.

APIs: client `POST /api/auth/password` → hub `POST /api/auth/password`.
Rejects if new ≠ confirm, or if new is empty.

---

<!-- {en:set[5],password[5],mobile,save,menu} -->
<!-- {nl:instellen[5],wachtwoord[5],mobiel,opslaan,menu} -->

## SMS one-time code

Keys in env, not git: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_FROM`. If any of the three is missing, the hub still prints the
code so local testing works without sending SMS.

After password OK, a person or unit login with `mobile_phone` set gets
`otp_required` instead of a session. The client shows a 6-digit field and
**Resend**. Hub `POST /api/auth/otp/verify` and `POST /api/auth/otp/resend`.
Country and center never take this path.

---

<!-- {en:sms[5],one-time[5],code[5],twilio,otp} -->
<!-- {nl:sms[5],eenmalig[5],code[5],twilio,otp} -->

## password_hash and mobile_phone on dbo.person

On `dbo.person`:


| Column          | Type                 | Role                    |
| --------------- | -------------------- | ----------------------- |
| `password_hash` | `NVARCHAR(256) NULL` | scrypt; never plaintext |
| `mobile_phone`  | `NVARCHAR(32) NULL`  | E.164                   |




---

<!-- {en:password_hash[5],mobile_phone[5],person[5],scrypt,sms} -->
<!-- {nl:password_hash[5],mobile_phone[5],persoon[5],scrypt,sms} -->

## Where login and OTP are implemented


| Area              | Where                                              |
| ----------------- | -------------------------------------------------- |
| Hash helpers      | `shared/` (re-export in `client/app/passwords.py`) |
| Authenticate      | `hub/app/user_store.py`                            |
| Login + OTP       | `hub/app/main.py`, `hub/app/person_otp.py`         |
| Set password UI   | `client/frontend/src/App.tsx`                      |
| Add-person mobile | hub wizard `_ADD_PERSON_HTML`                      |

<!-- {en:otp[5],implemented[5],passwords,hub,client} -->
<!-- {nl:otp[5],geimplementeerd[5],wachtwoorden,hub,client} -->
