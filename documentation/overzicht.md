# Inlogniveaus en balans

Landen zonder balans hebben drie inlogniveaus. Landen met balans
(`dbo.country.has_balance`) hebben er vier.

De drie gemeenschappelijke niveaus zijn country, center en person. Het
vierde niveau is unit. Elk niveau heeft een eigen tabel waarin de
gebruikersnaam staat.

Voor de gebruiker heten die vier niveaus, in een land met balans,
stichting, sectie, deel en werkeenheid.

## Niveaus


| Niveau  | Tabel         | Gebruiker   | HD-WE | Balans | Maandelijks | Termen |
| ------- | ------------- | ----------- | ----- | ------ | ----------- | ------ |
| country | `dbo.country` | *Stichting* | Ja    | Ja     | Nee         | G P    |
| center  | `dbo.center`  | *Sectie*    | Nee   | Nee    | Nee         | P      |
| person  | `dbo.person`  | *Deel*      | Nee   | Nee    | Ja          | P      |
| unit    | `dbo.unit`    | *Eenheid*   | Ja    | Nee    | Ja          | P      |


Op het niveau *Eenheid* kan de gebruiker inloggen als Werkeenheid (bvb. een studentenhuis) of als de daarmee geassocieerde Huishoudelijke Dienst. In de tabel hieronder staan de Werkeenheden in de tweede en vierde kolom, de Huishoudelijke diensten in de derde en vijfde. Op zowel stichting- als eenheidniveau vindt HD-WE consolidatie plaats: dat betekent dat Resultaat en Balans van een Werkeenheid die van de geassocieerde Huishoudelijke Dienst bevatten. De Werkeenheid kan de categorietotalen van de Huishoudelijke Dienst alleen maar inzien: het categoriseren van de bankafschriften van de Huishoudelijke Dienst blijft voorbehouden aan de Huishoudelijke Dienst, en aan de hogere niveaus waaronder die Huishoudelijke Dienst valt: op Deel-niveau zijn dat de twee verzamelingen van Huishoudelijke Diensten (hd_sia en hd_sib, zie hieronder).  
Alleen op Stichtingniveau is de volledige balans van de stichting te zien, met alle activa en passiva (waaronder het Eigen Vermogen). Onderliggende niveaus zien in plaats daarvan het banksaldo ten gevolge van inkomsten en uitgaven, en de onderste twee zien bovendien een maandelijkse onderverdeling.

---



## Stichting Instudo


| Niveau    | Inlognamen       |                |               |                  |
| --------- | ---------------- | -------------- | ------------- | ---------------- |
| Stichting | `beheer_instudo` |                |               |                  |
| Sectie    | `instudo_sia`    |                | `instudo_sib` |                  |
| Deel      | `sia`            | `hd_sia`       | `sib`         | `hd_sib`         |
| Eenheid   | `aenstal`        |                | `leidenhoven` | `hd_leidenhoven` |
|           | `hogeland`       | `hd_hogeland`  | `den_eker`    | `hd_den_eker`    |
|           | `de_stade`       | `hd_de_stade`  | `lepelenburg` | `hd_lepelenburg` |
|           | `de_borcht`      | `hd_de_borcht` | `jan_luijken` | `hd_jan_luijken` |
|           | `concertgebouw`  |                |               |                  |
|           |                  |                |               |                  |

Het sia-deel van sectie `instudo_sia` heeft 5 werkeenheden. Drie daarvan hebben een bijbehorende huishoudelijke dienst: Hogeland, De Stade en De Borcht. Aenstal en Concertgebouw hebben die niet.

Het sib-deel van sectie `instudo_sib` heeft 4 werkeenheden. Alle vier hebben een huishoudelijke dienst.

Instudo heeft 19 automatisch van de bank uitgelezen rekeningen en 2 afgeleide spaarrekeningen.  
Van de 19 zijn er 18 rekeningen van evenzoveel werkeenheden, en 1 van SVOa. SVOa heeft geen eigen login, en haar bankafschriften kunnen alleen op Sectie- of Stichtingsniveau gecategoriseerd worden.

---



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



# Dubbele login

Alle vier niveaus hebben een instelbaar wachtwoord. 

## SMS en IP-gate per inlogniveau

Op eenheidniveau kan vanaf overal ingelogd worden; daarom is deze wijze van inloggen SMS-beschermd. De gebruiker kan een telefoonnummer opgeven waarnaar een SMS-code wordt gestuurd ter (twee-staps)verificatie. Wie geen telefoonnummer opgeeft, kan zonder die controle inloggen (dat is uiteraard minder veilig).
De drie hogere niveaus hebben geen tweestaps-verificatie, maar een controle op IP adres. Wie graag op verschillende adressen wil inloggen, kan verschillende IP adressen opgeven. Inloggen vanuit een niet-geregistreerd IP-adres is geblokkeerd.



| Login     | Stichting     | Login    | Expenses       |
| --------- | ------------- | -------- | -------------- |
| Stichting | `IP adres`    | Land     | `IP adres`     |
| Sectie    | `IP adres`    | Centrum  | `IP adres`     |
| Deel      | `IP adres`    | Persoon  | `tweestaps`    |
| Eenheid   | `tweestaps`   |          |                |

De privé-uitgaven App kent maar drie inlogniveaus: ook daar is het laagste niveau SMS-beschermbaar, en zijn de hogere IP-adres-beschermd.

---


## Klik-overzicht

Dit overzicht beschrijft de werking van links- en rechts-klikken in de verschillende vensters.
De openingstabel toont de categorie-totalen: voor elke categorie toont het bedrag de som van alle boekingen op die categorie, voor de geselecteerde rekening(en).
Door te links-klikken op een categorie-totaalbedrag, verschijnt de lijst van alle boekingen die aan dat totaal bijdragen.
De eerste kolom toont het bankrekeningnummer van de rekeninghouder, waarvan het afschrift genomen is. De overige kolommen vatten de informatie van het bankafschrift samen. 

### Links-klikken op een categorie-totaal in de lijst van bankafschriften

Links-klikken op een bedrag opent de boekingenlijst van die rekening
en die categorie. Een lege cel blijft staan. De twee voetrijen, saldo en
laatste boekdatum, blijven staan. De categorienaam links is een opschrift.
Negatieve bedragen staan in het rood.

Wanneer de kolomkop een keuzelijst is, kiest een links-klik daar een andere
rekening. Dat is een eenheid met meer dan één rekening.

### Links-klikken op een afschriftbeschrijving of op een afschriftnaam in de lijst van bankafschriften

Het boekingsoverzicht toont de lijst bankafschriften voor een gekozen (groep van) bankrekeningnummer(s) in de geselecteerde categorie.
De kolommen "naam" en "omschrijving" bevatten vetgedrukte woorden/woorddelen als die de oorzaak zijn van hun categorisering. 
Als de categorie vetgedrukt is, duidt dat erop dat het afschrift handmatig is gecategoriseerd. 
'Handmatig' staat hier tegenover 'geautomatiseerd', namelijk, via de trefwoorden.

Klikken op de knop **← Matrix** toont het overzicht van aangesloten centra/personen; voor de laagste inlogniveaus is er geen verschil tussen het overzicht aan de rechterkant en de selectie aan de linkerkant.

**Omschrijving** en **Naam**: Links-klikken op de tekst verander het gehele veld in bewerkbaar: gebruik deze optie om de omschrijving aan te passen. Een gewijzigde omschrijving is blauw gekleurd.

**Categorie**: Een links-klik op de code opent een lijst met code en post.
Een links-klik op een rij wijst die categorie toe. De code staat daarna vet.
**cancel**, een links-klik op de grijze rand, of Escape sluit de lijst.

**Tekenconventie**: De knop boven de lijst opent de uitleg. De sluitknop,
een links-klik op de grijze rand, of Escape sluit die uitleg.


### Rechts-klikken op een bedrag in de lijst van bankafschriften

Rechts-klikken op het bedrag opent een nieuwe scherm in hetzelfde
venster: daarin kan de gebruiker een bedrag opsplitsen in meerdere posten; zoveel als de gebruiker wil. In toegevoegde onderdeel-post kan de gebruiker een willekeurig bedrag invullen, positief zowel als negatief. Het programma berekent op basis van het ingevulde bedrag welk bedrag er op de restpost komt te staan, met dien verstande, dat de som van de gesplitste bedragen altijd gelijk is aan het oorspronkelijke bedrag.
Gebruik deze optie met name voor kas-opnames. De eerste post kan de gebruiker een willekeurige naam geven. Elke keer dat de gebruiker een deel van het bedrag uitgeeft, kunnen bedrag en categorie worden genoteerd, totdat de opgenomen hoeveelheid geld volledig besteed is.

Op het splitscherm voegt **Add line** een regel toe. Bedrag en omschrijving
van elke extra regel zijn in te vullen. **Delete** haalt die regel weg.
**Save** schrijft de splitsing en keert terug naar de matrix. **Matrix (Alt+M)** verlaat het scherm en laat de boeking onveranderd.

**Naam of omschrijving.** Rechts-klikken selecteert het aangeklikte woord.
Letters, cijfers, een underscore, `&` en een streepje horen bij het woord: een spatie, een punt en alle overige leestekens scheiden woorden.

### Termmenu

Bovenaan staat het woord in een veld. Dat veld is te wijzigen voordat een
vakje wordt aangevinkt. Elke rij is een categorie die een term mag krijgen.

- **G** bewaart een gemeenschappelijke term voor alle rekeningen van de
stichting. Alleen een stichting-login vinkt G aan. Op sectie, deel en
eenheid is dat vakje grijs.
- **P** bewaart een persoonlijke term voor dit deel of deze eenheid. Wanneer
termen per rekening staan, is de kolomkop P een keuzelijst van rekeningen.
Een sectie in die lijst staat rood. P geldt dan voor de gekozen rekening
of sectie.

Het aanvinken bewaart meteen. **cancel**, een links-klik of Rechts-klikken
buiten het menu, of Escape sluit het menu. Andere boekingen houden hun
categorie tot de volgende menuklik. Een Rechts-klikken binnen het menu opent
het browsermenu niet.

### Termvenster

De toetscombinatie **alt+T** opent een nieuw venster met een overzicht van alle categorieën en bijbehorende trefwoorden.

Links-klikken op een categorie in de eerste kolom selecteert de categorie. Links-klikken op een
deel, eenheid of rekening in de derde kolom kiest voor wie de persoonlijke
termen gelden. Voor hogere inlogniveaus: In het rood, bovenin de lijst, staat het Deel of de Sectie. Wie daarop klikt, voegt termen toe aan alle eenheden die vallen onder het Deel of de Sectie. 

In **+ term** typt u een woord en drukt u op Enter, of u verlaat het veld.
Een bestaand woord wijzigt u op dezelfde manier. **×** verwijdert dat woord.
De gemeenschappelijke kolom wijzigt alleen een stichting-login.

De knop **Voorrangsregels** opent de uitleg van de treffers. De sluitknop,
een links-klik op de grijze rand, of Escape sluit die uitleg. **Matrix
(Alt+M)** of Ctrl+Tab keert terug naar de matrix.

Ook al kan de gebruiker op eenheid-niveau de G-termen niet definiëren, loont het wel degelijk de moeite om te proberen te begrijpen hoe de voorrangsregels werken. Elke G/P-term draagt immers bij tot de automatisering van de categorisering. Dat merkt de gebruiker al meteen in het jaar van de definitie (dan kunnen vele bankschriften in één keer worden gecategoriseerd), maar nog veel meer in de jaren daarna: naarmate de termenlijst beter gekozen is, blijven er minder bankafschriften over die individueel moeten worden gecategoriseerd. Laat daarom vooral niet na om je voorstel voor een G-term te communiceren naar de stichting: die draagt er zorg voor dat de G- en P-termen constructief bijdragen aan een optimale automatisering van de categorisatie.

### Journaal en afschrijvingen

Gebruik het menu-item *Handmatige journaalposten* 

De knop voor de tekenconventie opent de uitleg. De sluitknop, een links-klik
op de grijze rand, of Escape sluit die.

De eerste regel is een nieuwe post. **Save** schrijft die. Op een bestaande
regel opent **Edit** de velden, **Save** bewaart de wijziging, en **×**
verwijdert de regel. Datum, van-categorie, naar-categorie, bedrag en
omschrijving staan in die regel. Filters links beperken de getoonde regels.

### Balans en resultaat

Het menu-item voor resultaat en balans opent het blad in een eigen venster.
Een tweede klik gebruikt datzelfde venster.

Een links-klik op een bedrag dat een journaalpost of een subadministratie
heeft, opent die lijst. De andere bedragen zijn tekst. **✕**, een links-klik
op de grijze rand, of Escape sluit de lijst. Zonder open lijst brengt Escape
u terug naar het boekhoudvenster.

Het jaar kiest u met de knoppen of de keuzelijst. De datumkeuze toont het
blad per datum, actueel, of de start vóór mutaties. **Export** downloadt
het overzicht. Op stichting-login staat ook **Export zip**. De infoknop
opent de kleurtoelichting. De sluitknop of een links-klik op de grijze rand
sluit die toelichting.

De maandtabel, vanuit het menu, is tekst. **Matrix (Alt+M)** keert terug.

### Maaltijden

De maaltijdenpagina staat apart van de matrix. Een links-klik op een cel
wisselt een lege cirkel en een volle. U wijzigt alleen de eigen rij. De
login `admin` wijzigt de extra aantallen van de lopende week.

**Dag**, **Week** en **Reserveren** wisselen de weergave. De weekkeuze en,
bij Reserveren, het aantal weken zitten in dezelfde balk. **Uitloggen**
beëindigt die sessie. **Aanmelden** verstuurt gebruikersnaam en wachtwoord
van die pagina.

### Menu, balk en dialogen

Een links-klik op **menu** opent de lijst. Een links-klik op een onderdeel
voert dat uit.

In de balk erboven kiest een stichting-login de sectie. Het jaar en, bij
meer dan één bank, de bank zitten in dezelfde balk. Het vraagvak rechts
neemt de vraag aan met Enter.

Dialogen voor herberekenen, wissen, kleinere uitgaven en kleinere inkomsten
sluiten met **Annuleren** of met een links-klik op de grijze rand. De
knoppen in het dialoog voeren de keuze uit: bij herberekenen **vanaf nul**
of **incrementeel**, bij wissen de aangevinkte onderdelen en **OK**, bij
kleinere bedragen **toepassen**.

**Sign in** verstuurt gebruikersnaam en wachtwoord. Bij een sms-stap
verstuurt **Verify** de code. **Resend code** vraagt een nieuwe code.
**Back** keert terug naar gebruikersnaam en wachtwoord.

Categorieën bewerken: **Add category** voegt een rij toe, **Delete**
verwijdert een rij, **Submit** schrijft de lijst. IP-lijst: **Add IP** en
de verwijderknop per adres. Wachtwoord: **Save** schrijft, **Cancel** of
**Matrix (Alt+M)** keert terug naar de matrix.