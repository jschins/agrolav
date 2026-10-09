<!-- {discard-en:a,am,can,could,do,find,get,have,how,i,is,me,must,need,please,should,supposed,tell,the,there,to,want,what,where,would} -->
<!-- {discard-nl:ben,bij,heb,hoe,ik,kan,kom,mag,moet,vind,waar,wil} -->

# Agrolav

Agrolav is de boekhouding van een stichting in de browser. Na het inloggen
zie je een **matrix van totalen**: categorieën links, rekeningen bovenaan.
Klik op een getal om de boekingen erachter te openen. Categorieën worden
toegekend op grond van trefwoorden (termen) in de naam en de omschrijving.

Deze pagina heeft twee gebruiken. Het is de beschrijving van wat je in de
app kunt doen, en het vragvak leest hem samen met elk ander markdownbestand
in de repo waarvan de naam niet op `_tech` eindigt. De taal van die pagina's
doet er niet toe. De inrichting voor de beheerder staat in
`documentation/deployment_tech.md`.

Elke latere sectie eindigt met één `{en: …}`-regel en één `{nl: …}`-regel.
Die regels zijn verborgen in het voorbeeld. Het vragvak telt alleen die
termen, niet de tekst van de sectie, en het doorzoekt deze openingssectie
niet. De Nederlandse regel vertaalt de Engelse regel in dezelfde volgorde,
één term voor één term, met hetzelfde gewicht. Termen worden gescheiden door
komma's, zonder spatie na de komma. `log in` is de enige term die een spatie
vanbinnen houdt. Een term mag eindigen op een gewicht, zoals in `category[3]`.
Die treffer telt als 3. Een term zonder getal telt als 1. Een term die ook een
woord in de sectietitel is, telt als 5. Elke treffer telt zijn gewicht op,
zodat twee treffers zwaarder wegen dan één. Elke sectie die treft, wordt
teruggegeven, de hoogste score eerst. De accoladeregels worden niet in het
antwoord getoond.

De regels `{discard-en:}` en `{discard-nl:}` boven de titel worden eerst uit
de vraag verwijderd. Een woord wordt alleen op zichzelf verwijderd, zodat
`to` niet aan `total` komt. Een vraag zonder passende term wordt beantwoord
met “I don't find an answer to that in the README.”

---

## Aanmelden

Open de client (lokaal `http://127.0.0.1:8300`). Vul je **gebruikersnaam** en
**wachtwoord** in.

Er zijn vier soorten login. De gebruikersnaam is de loginnaam van die rij:

| Login | Wat je ziet |
|---|---|
| **Stichting** | Alle rekeningen. |
| **Sectie** | `instudo_sia` versus `instudo_sib`. |
| **Deel** | Geconsolideerde werkeenheden versus geconsolideerde huishoudelijke diensten. |
| **Eenheid** | Een werkeenheid of een huishoudelijke dienst. |

Staat er een mobiel nummer op een deel- of eenheidslogin, dan is de volgende
stap een **sms-code van 6 cijfers**. Vul die in, of gebruik **Opnieuw**.
Stichting- en sectielogins zijn alleen toegestaan vanaf vermelde
IP-adressen; van elders krijg je *This login is not allowed from your IP
address*. Deel- en eenheidslogins worden niet op IP gecontroleerd.
<!-- {en:log in[5],login[3],username,usernames,password[3],passwords,foundation,section,part,unit,work-unit,household,kind,kinds,sms,code,codes,resend,mobile,mobiles,number,numbers,ip,address,addresses,phone,phones} -->
<!-- {nl:aanmelden[5],inloggen[3],gebruikersnaam,gebruikersnamen,wachtwoord[3],wachtwoorden,stichting,sectie,deel,eenheid,werkeenheid,huishoudelijke,soort,soorten,sms,code,codes,opnieuw,mobiel,mobielen,nummer,nummers,ip,adres,adressen,telefoon,telefoons} -->

---

## De bovenbalk

Op het overzicht staan deze bedieningen in de strook boven de matrix:

- **Sectie** — alleen bij een stichtinglogin. Kies `instudo_sia` of `instudo_sib`.
- **Jaar** — welk boekjaar de matrix gebruikt.
- **Bank** — `consolidated` (alle banken samen) of één bank, wanneer er meer
  dan één bank is.
- **menu** — acties voor deze login (zie hieronder).
- **Vraag** — het vak rechts van menu. Typ een vraag over het gebruik van
  het programma en druk op Enter. Het antwoord komt uit de latere secties
  van deze pagina en uit elk ander markdownbestand waarvan de naam niet op
  `_tech` eindigt.

De linkerzijbalk toont de titel van wie is ingelogd. Nadat je een categorie
opent, toont hij ook die kolom en een knop **← Matrix** om terug te gaan.
<!-- {en:top[5],bar[5],overview,foundation,section,switch[3],year[3],years,booking,bookings,bank,banks,consolidated,menu,question,questions,answer,answers,box,help,sidebar,title,titles,matrix,knob} -->
<!-- {nl:boven[5],balk[5],overzicht,stichting,sectie,kiezen[3],jaar[3],jaren,boeking,boekingen,bank,banken,consolidatie,menu,vraag,vragen,antwoord,antwoorden,vak,hulp,zijbalk,titel,titels,matrix,knop} -->

---

## Het menu

<!-- {en:menu[5]} -->
<!-- {nl:menu[5]} -->

### Menu-onderdelen bij elke login

Open **menu**. Wat je ziet hangt af van de login. Onderdelen die niet van
toepassing zijn, staan er niet bij.

**⚙ Termen bewerken (Alt+T)**  
Opent het termvenster: trefwoorden die boekingen aan categorieën toewijzen.
Zie [Termen bewerken](#termen-bewerken). Sneltoets: `Alt+T`.

**Categorieën herberekenen**  
Wijst boekingen opnieuw toe op grond van de termen, voor elk jaar binnen
bereik, en alleen de boekingen van deze login. Een eenheidslogin dekt die
werkeenheid of die huishoudelijke dienst. Een deellogin dekt geconsolideerde
werkeenheden of geconsolideerde huishoudelijke diensten. Een sectielogin
dekt `instudo_sia` of `instudo_sib`. Een stichtinglogin dekt alle rekeningen,
en daar worden de G-termen geschreven. Een categorie die je met de hand hebt
gezet, en een rij die uit Excel komt, blijven staan. Gebruik dit nadat je
termen of de categorielijst hebt gewijzigd.

**Uitlezen bankafschriften**  
Haalt nieuwe bankboekingen op (Enable Banking). Een eenheidslogin leest die
werkeenheid of huishoudelijke dienst uit. Een deellogin leest zijn
geconsolideerde werkeenheden of zijn geconsolideerde huishoudelijke diensten
uit. Een stichting- of sectielogin leest elke rekening in de gekozen sectie
(`instudo_sia` of `instudo_sib`) uit die banktoestemming heeft. Rekeningen
die een bestand uploaden, worden overgeslagen. Wie nog toestemming nodig
heeft, gaat in een nieuw tabblad naar de bank; na de toestemming gaat het
uitlezen verder. Alleen zichtbaar wanneer deze sectie een bankverbinding heeft.

**Persoon toevoegen**  
Opent de hubpagina om een deel aan te maken in de huidige sectie. Niet
zichtbaar bij een deel- of eenheidslogin.

**Uploaden**  
Opent de uploadpagina voor een rekenblad of een bank-CSV. Zichtbaar wanneer
deze login bestanden mag uploaden.

**Uitloggen**  
Beëindigt de browsersessie en keert terug naar de inlogkaart.
<!-- {en:item[5],items[5],menu,edit,term,terms,alt+t,window,recalculate[3],foundation,section,part,unit,download,statement,statements,transaction,transactions,consent,consents,add[3],upload,csv,spreadsheet,spreadsheets,logout[3],log,out} -->
<!-- {nl:onderdeel[5],onderdelen[5],menu,bewerken,term,termen,alt+t,termvenster,herberekenen[3],stichting,sectie,deel,eenheid,uitlezen,bankafschrift,bankafschriften,transactie,transacties,toestemming,toestemmingen,toevoegen[3],uploaden,csv,rekenblad,rekenbladen,uitloggen[3],loggen,uit} -->
**Bereid toestemming**  
Stichting- of sectielogin, wanneer deze sectie een bankverbinding heeft.
Vraagt welk deel, en opent daarna de bank zodat dat deel toestemming kan geven.

**Verwijder toestemming**  
Dezelfde logins. Vraagt welk deel, vraagt om bevestiging, en verwijdert daarna
de banktoestemming van dat deel.

**YTD bankafschriften**  
Dezelfde logins. Vraagt welk deel, en haalt daarna de afschriften van dat deel
op van 1 januari van dit jaar tot en met vandaag. Wil de bank die periode niet
geven, dan krijg je te horen dat je eerst de toestemming moet vernieuwen.
<!-- {en:prepare[3],consent[5],consents[5],invalidate[3],remove,download,ytd[5],year,january,renew} -->
<!-- {nl:bereid[3],toestemming[5],toestemmingen[5],verwijder[3],verwijderen,uitlezen,ytd[5],jaar,januari,vernieuwen} -->
**Bereken kruisposten**  
Zichtbaar wanneer deze login een balans heeft. Koppelt interne overboekingen
en schrijft hun categorieën. Een categorie die zo wordt gezet, telt als met
de hand gezet.

**Kleinere uitgaven**  
Stichting-, sectie- of deellogin. Vraagt een maximaal bedrag en een categorie.
Restboekingen waarvan de uitgave kleiner is dan dat bedrag krijgen de gekozen
categorie, en tellen als met de hand gezet. **Annuleren** doet niets.

**Kleinere inkomsten**  
Hetzelfde, voor restboekingen waarvan de inkomst kleiner is dan het maximum.
<!-- {en:cross-postings[5],cross,posting,postings,calculate[3],internal,transfer,transfers,smaller[5],expense,expenses,income,incomes,maximum,amount,category,remainder,cancel,apply} -->
<!-- {nl:kruisposten[5],kruis,post,posten,bereken[3],intern,overboeking,overboekingen,kleinere[5],uitgave,uitgaven,inkomst,inkomsten,maximaal,bedrag,categorie,restcategorie,annuleren,toepassen} -->
**Terug naar overzicht**  
Keert terug naar de matrix. Zichtbaar zolang er een jaar is gekozen en je in
het matrixmenu zit (niet op Termen, categorieën, IP, wachtwoord, splitsen of
een journaalpagina).
<!-- {en:back[5],summary[5],matrix,return,overview} -->
<!-- {nl:terug[5],overzicht[5],matrix,terugkeren,samenvatting} -->
### Categorieën bewerken en de IP-toegangslijst

**Categorieën bewerken**  
Wijzig de categoriecodes en labels van de stichting. Zie
[Categorieën bewerken](#categorieën-bewerken).

**IP-toegang beperken**  
Toegangslijst van client-IP's voor stichting- en sectielogins. Zie
[IP-toegang beperken](#ip-toegang-beperken).
<!-- {en:edit,category,categories,restrict[3],ip,access,allowlist,allowlists} -->
<!-- {nl:bewerken,categorie,categorieën,beperken[3],ip,toegang,toegangslijst,toegangslijsten} -->
### Jaar wissen

**Jaar wissen**  
Vraagt een jaar van vier cijfers, en vraagt daarna om bevestiging. Verwijdert
de boekingen van dat jaar, en verwijdert geüploade bestandsnamen voor de
betrokken rekeningen. Dit kan niet ongedaan worden gemaakt.

- Stichting-niveau login: alle rekeningen.
- Sectie-niveau login: `instudo_sia` versus `instudo_sib`.
- Deel-niveau login: geconsolideerde werkeenheden versus geconsolideerde huishoudelijke diensten.
- Eenheid-niveau login: werkeenheid of huishoudelijke dienst.
<!-- {en:wipe[5],year[5],years[5],delete,foundation,section,part,unit,work-unit,household,account,accounts} -->
<!-- {nl:wissen[5],jaar[5],jaren[5],verwijderen,stichting,sectie,deel,eenheid,werkeenheid,huishoudelijke,rekening,rekeningen} -->
### Wachtwoord instellen bij een deel- of eenheidslogin

**Wachtwoord instellen**  
Wijzig je wachtwoord en het optionele mobiele nummer. Zie
[Wachtwoord instellen](#wachtwoord-instellen). Het kopmenu is op deze pagina
verborgen; gebruik **Annuleren** of **Matrix (Alt+M)** om te vertrekken.
<!-- {en:set[3],password,passwords,change} -->
<!-- {nl:instellen[3],wachtwoord,wachtwoorden,wijzigen} -->

---

## De matrix

Elke cel is het totaal van die rekening in die categorie voor het gekozen jaar
(en de bankweergave).

- **Klik op een gevuld bedrag** om de boekingenlijst van die rekening en
  categorie te openen.
- Lege cellen en de twee **voettekstrijen** (saldo en laatst geboekte datum)
  zijn niet aanklikbaar.
- Negatieve bedragen staan in het rood.
<!-- {en:matrix[5],cell,cells,total,totals,click,amount,amounts,open,booking,bookings,footer,footers,last,booked,empty,negative,red,balance,balances,date,dates,option,options} -->
<!-- {nl:matrix[5],cel,cellen,totaal,totalen,klik,bedrag,bedragen,openen,boeking,boekingen,voettekst,voetteksten,laatste,geboekt,leeg,negatief,rood,saldo,saldo's,datum,optie,opties} -->

---

## De boekingenlijst

De tabel toont elke boeking in de gekozen cel. Passende termen zijn
gemarkeerd in de naam en de omschrijving.

**Linksklik**

**Omschrijving** — klik op de tekst, bewerk, en klik daarna weg of druk op
Enter. Een omschrijving die je hebt gewijzigd, staat in het **blauw**.

**Categorie (kolom C)** — klik op de code, typ een geldig categorienummer, en
klik daarna weg of druk op Enter. Een onbekende code wordt geweigerd. Een
categorie die je hebt overschreven, staat in het **vet**.

Andere kolommen (datum, type, IBAN, bedrag) worden niet met een linksklik
bewerkt.
<!-- {en:booking[5],bookings[5],list[5],lists[5],highlighted,description,descriptions,blue,text,left-click,left,click,category,categories,code,codes,c,bold,date,dates,iban,amount,amounts,column[5],columns[5],option,options} -->
<!-- {nl:boeking[5],boekingen[5],lijst[5],lijsten[5],gemarkeerd,omschrijving,omschrijvingen,blauw,tekst,linksklik,links,klik,categorie,categorieën,code,codes,c,vet,datum,datums,iban,bedrag,bedragen,kolom[5],kolommen[5],optie,opties} -->
### Rechtsklik op het bedrag

Klik met rechts op het **bedrag** om die boeking te **splitsen**. Je verlaat
de lijst en opent de splitpagina.

Het oorspronkelijke bedrag blijft het restbedrag: extra regels die je
toevoegt, worden ervan afgetrokken, zodat het totaal nooit verandert.

- **Regel toevoegen** — nog een omschrijving en bedrag.
- Bewerk omschrijvingen en bedragen in de tabel; verwijder een regel met zijn knop.
- **Opslaan** — schrijft de splitsing en keert terug naar de matrix.
- **Matrix (Alt+M)** — vertrek zonder op te slaan.
<!-- {en:split,splits,right-click[5],amount[5],amounts[5],remainder,remainders,add,line,lines,delete,save,leave,alt+m,option,options} -->
<!-- {nl:splitsen,splitsingen,rechtsklik[5],bedrag[5],bedragen[5],restbedrag,restbedragen,toevoegen,regel,regels,verwijderen,opslaan,verlaten,alt+m,optie,opties} -->
### Rechtsklik op een naam of omschrijving

Klik met rechts op een **woord** in de **naam** of de **omschrijving**. Er
opent een klein menu op dat woord (je kunt de frase bewerken in het vak
bovenaan).

Vink **G** (gemeenschappelijk) of **P** (persoonlijk) aan op een categorierij:

- **G** — de term geldt voor elke rekening in deze stichting of sectie.
- **P** — de term geldt alleen voor dit deel of deze eenheid.

Het woord wordt meteen opgeslagen. **annuleren**, of klik buiten het menu om
het te sluiten zonder toe te wijzen. Andere boekingen houden hun categorie tot
de volgende menuklik.
<!-- {en:right-click[5],word,words,menu,name[5],names[5],general,personal,cancel,term[5],terms[5],save} -->
<!-- {nl:klik,rechts[5],woord,woorden,menu,naam[5],namen[5],gemeenschappelijk,persoonlijk,annuleren,term[5],termen[5],opslaan} -->

---

## Termen bewerken

**menu → ⚙ Termen bewerken**, of `Alt+T`. **Matrix (Alt+M)** (of `Ctrl+Tab`)
keert terug naar het overzicht. Wijzigingen worden opgeslagen zodra je een
veld verlaat; passende boekingen worden op de achtergrond bijgewerkt.

Het venster heeft vier kolommen. Klik op een categorie in de eerste. De
tweede en de vierde kolom tonen dan de termen van die categorie.

**Categorie**  
De categorieën waarvoor een boeking een term kan krijgen. Categorieën die een
boeking niet kan krijgen, staan er niet bij. De termen in de andere kolommen
horen bij de categorie waarop je klikt.

**Gemeenschappelijk**  
Trefwoorden voor de gekozen categorie. Ze gelden voor alle rekeningen van de
stichting, in beide secties. Een persoonlijke term wint van een
gemeenschappelijke.

**Deel**, of **Rekening** wanneer termen per rekening worden bewaard  
Bij wie de persoonlijke termen horen. Een eenheidslogin toont alleen die
werkeenheid of huishoudelijke dienst. Een deellogin toont zijn geconsolideerde
werkeenheden of zijn geconsolideerde huishoudelijke diensten. Een stichting-
of sectielogin toont de rekeningen in de nu gekozen sectie (`instudo_sia` of
`instudo_sib`). Wanneer het opschrift Rekening is, is elke rij één rekening,
en is de sectienaam de eerste rij, gemarkeerd als sectie. De vierde kolom
toont dan elke persoonlijke term op een van die rekeningen. Een term die je
toevoegt, wordt op elk van hen geschreven. Een term die je verwijdert, wordt
van elk van hen verwijderd.

**Persoonlijk**  
Trefwoorden voor de gekozen categorie en voor het deel of de rekening die in
de derde kolom is gekozen. Ze gelden alleen daar.

- Typ in **+ term** en druk op Enter (of verlaat het veld) om een trefwoord toe te voegen.
- Bewerk een bestaande term en verlaat het veld om op te slaan.
- **×** verwijdert die term.
<!-- {en:edit[5],term[5],terms[5],page,alt+t,ctrl+tab,window,background,four,column[5],columns[5],category,categories,general,foundation,section,part,unit,account,accounts,personal,add,plus,delete,change} -->
<!-- {nl:bewerken[5],term[5],termen[5],pagina,alt+t,ctrl+tab,termvenster,achtergrond,vier,kolom[5],kolommen[5],categorie,categorieën,gemeenschappelijk,stichting,sectie,deel,eenheid,rekening,rekeningen,persoonlijk,toevoegen,plus,verwijderen,wijzig} -->
### Hoe termen overeenkomen

Een term komt overeen met een heel woord in de naam en de omschrijving van de
boeking. Een woord eindigt bij een spatie, een punt, een streepje of andere
leestekens (schuine streep, komma, dubbele punt, apostrof, sterretje, plus,
haakjes). Een cijfer of een onderstreping blijft binnen het woord.

`#` staat voor nul of meer letters, punten of sterretjes binnen één stuk dat
door spaties is gescheiden. Het gaat niet over een spatie heen. Een streepje
binnen dat stuk wordt overgeslagen, zodat `albert#heijn` nog steeds overeenkomt
met `albert-heijn`.

`&&` betekent dat beide frases moeten overeenkomen, in willekeurige volgorde,
en ze hoeven niet naast elkaar te staan. Bijvoorbeeld `heijn && machtiging`.
Het scheidingsteken is spatie, `&&`, spatie.

Voorrang, de hoogste eerst:

1. Een **persoonlijke** term wint van elke **gemeenschappelijke** term.
2. Een `&&`-term wint van een enkele frase.
3. **Activa/passiva** wint van **lasten/baten**. Activa en passiva zijn
   categoriecodes onder 3000. Lasten en baten zijn codes van 3000 of hoger.
4. De latere categorienaam wint, daarna de latere term. Later is de
   woordenboekvolgorde van de tekst, niet het tijdstip waarop de term is
   opgeslagen. `1110 Kruisposten` wint van `1052 Spaarrekening`. In dezelfde
   categorie wint `spaarrekening` van `oranje`.

De opgeslagen treffer is `P:` plus de term, of `G:` plus de term. Komt niets
overeen, dan blijft de boeking in de restcategorie en is de treffer leeg.
<!-- {en:terms[5],word,dash,dot,hash,wildcard,asterisk,&&,heijn,direct-debit,both,phrases,priority,hit,P,G,remainder,match[5],rules,assets,liabilities,costs,revenues,rank} -->
<!-- {nl:termen[5],woord,streepje,punt,hekje,jokerteken,sterretje,&&,heijn,machtiging,beide,zinnen,voorrang,treffer,P,G,restcategorie,overeenkomen[5],voorrangsregels,activa,passiva,lasten,baten,prioriteit} -->

### Strategie voor het definiëren van termen

Definieer termen in deze volgorde.

1. Draai eerst **Bereken kruisposten**. Dat koppelt interne overboekingen en
   schrijft hun categorieën. Die rijen tellen als met de hand gezet, zodat een
   latere term ze niet verplaatst.
2. Definieer de **gemeenschappelijke** termen zo volledig als je kunt. Een
   gemeenschappelijke term heeft de laagste voorrang. Binnen de
   gemeenschappelijke lijst wint een `&&`-term van een enkele frase, dus
   gebruik `&&` wanneer de ene gemeenschappelijke term van de andere moet
   winnen.
3. Definieer daarna de **persoonlijke** termen. Een persoonlijke term wint van
   elke gemeenschappelijke term. Staat dat woord ook in een omschrijving naast
   een gemeenschappelijke term, dan verlaat de boeking de categorie die de
   gemeenschappelijke term had gegeven. Beperk de persoonlijke term tot één
   rekening wanneer dat kan. Hij raakt dan minder afschriften dan dezelfde
   term op elke rekening van een sectie.
4. Moet een persoonlijke term voor elke rekening van een sectie gelden, schrijf
   hem dan op de sectierij. Hij wordt gekopieerd naar elke rekening van die
   sectie. Verwijderen van de sectierij haalt hem ook van die rekeningen weg.
5. Draai tot slot **Kleinere uitgaven** en **Kleinere inkomsten**. Elk vraagt
   een maximum en een categorie. Restboekingen kleiner dan dat maximum krijgen
   de gekozen categorie en tellen als met de hand gezet. De categorieën die je
   nog nakijkt, houden dan de grotere bedragen. De kleinere, die het resultaat
   minder bewegen, zijn al opgeslagen, zodat de balans sneller klaar is.
<!-- {en:strategy[5],order,first,cross-postings[5],general[5],precedence,&&,personal[5],particular,account,section,restrict,smaller[5],expenses,income,balance,sheet,maximum,remainder} -->
<!-- {nl:strategie[5],volgorde,eerst,kruisposten[5],gemeenschappelijk[5],voorrang,&&,persoonlijk[5],bijzonder,rekening,sectie,beperken,kleinere[5],uitgaven,inkomsten,balans,blad,maximaal,restcategorie} -->

---

## Categorieën bewerken

**menu → Categorieën bewerken** (stichting- of sectielogin). **Matrix (Alt+M)**
gaat terug.

Elke rij is een boekingscategorie: **code**, **label**, en welke rij
**Niet ingedeeld** is (de restcategorie). Een label wijzigen houdt bestaande
boekingen op die categorie. **Categorie toevoegen** voegt een rij toe.
**Verwijderen** haalt een categorie weg en verplaatst overgebleven boekingen
naar niet ingedeeld. **Indienen** schrijft de lijst.
<!-- {en:edit[5],category[5],categories[5],page,add,delete,submit} -->
<!-- {nl:bewerken[5],categorie[5],categorieën[5],pagina,toevoegen,verwijderen,indienen} -->

## Categorieën die een boeking niet kan krijgen

Een boeking kan niet worden toegewezen aan eigen vermogen, of aan een lopende
betaalrekening. Die bedragen worden berekend, of ze komen van de bank. Een
spaarrekening (mirror) kan wel een term krijgen. De restcategorie ontvangt
een boeking waarop geen term past.
<!-- {en:cannot[5],assign,bank,account,mirror,no,hit,equity,capital} -->
<!-- {nl:onmogelijk[5],toewijzen,bank,rekening,spaarrekening,geen,treffer,eigen,vermogen} -->

## Het categorietotaal komt niet overeen met de som van de leden

Het categorietotaal kom om meerdere redenen afwijken van de som van de getoonde bedragen:
- wanneer een ander centrum ook bijdraagt aan het totaal
- wanneer een journaalpost bijdraagt aan het totaal
- voor cumulatieve activa: wanneer een beginwaarde bijdraagt aan het totaal

<!-- {en:category[5],total[5],does[5],not[5],match[5],equal[5],unequal[5],differs,differ,contribute,contributes}>
<!-- {nl:categorietotaal[5],klopt[5],niet[5],komt[5],overeen[5],afwijken, wijkt,bijdragen,draagt,beginwaarde}>



---

## IP-toegang beperken

**menu → IP-toegang beperken** (stichting- of sectielogin). Deel- en
eenheidslogins worden nooit op IP gecontroleerd.

Kies een **Login** (de stichting of een sectie), typ een IPv4- of
IPv6-adres, **IP toevoegen**. De tabel toont de huidige adressen; verwijder
er een met zijn knop.

Een lege lijst op deze pagina betekent dat **geen** adres is toegestaan voor
die login, tenzij hetzelfde adres ook op de egress_ip-lijst staat (bewerkt in
SSMS, niet hier). De toegestane verzameling is de som van de twee lijsten.
Zijn beide leeg, dan werkt geen enkele stichting- of sectielogin.
<!-- {en:restrict[5],page,add,ipv4,ipv6,remove,empty,list,administrator,ssms,ip[5]} -->
<!-- {nl:beperken[5],pagina,toevoegen,ipv4,ipv6,verwijderen,leeg,lijst,beheerder,ssms,ip[5]} -->

---

## Wachtwoord instellen

**menu → Wachtwoord instellen** (deel- of eenheidslogin).

Vul het huidige wachtwoord in, het nieuwe wachtwoord tweemaal, en eventueel
een **mobiele telefoon** (`+316…` of `06…`). Een mobiel nummer zet het
inloggen in twee stappen per sms aan.

**Opslaan** schrijft de wijziging. **Annuleren** (of **Matrix (Alt+M)**) keert
terug naar de matrix zonder op te slaan.
<!-- {en:save,password[5],cancel,mobile,phone,sms,login} -->
<!-- {nl:opslaan,wachtwoord[5],annuleren,mobiel,telefoon,sms,inloggen} -->

---

## Uploaden en downloaden

**Uploaden** is voor een login die een bank-CSV of een rekenblad plakt in
plaats van een bank te koppelen. Kies het jaar en het formaat op de
uploadpagina.

**Uitlezen bankafschriften** haalt op bij de bank wanneer de toestemming er
is. Een eenheidslogin leest die werkeenheid of huishoudelijke dienst uit. Een
deellogin leest zijn geconsolideerde groep uit. Een stichting- of sectielogin
leest elke rekening in de gekozen sectie uit die toestemming heeft. De eerste
keer kan de banksite opengaan voor machtiging; nadat je goedkeurt, haalt
Agrolav de periode op en vult de matrix.
<!-- {en:upload[5],page,bank,csv,download[5],from,authorization,authorisation,consent,give} -->
<!-- {nl:uploaden[5],pagina,bank,csv,downloaden[5],van,machtiging,autorisatie,toestemming,geven} -->

---

## Toetsenbord

| Sneltoets | Actie |
|---|---|
| `Alt+T` | Termen bewerken |
| `Alt+M` | Terug naar de matrix (vanuit Termen, categorieën, IP, wachtwoord, splitsen) |
| `Alt+C` | Categorieën bewerken (vanuit de matrix, wanneer dat menu-onderdeel bestaat) |
| Enter | Bevestig een bewerking in een cel |
<!-- {en:keyboard[5],shortcut,alt+c,enter,key} -->
<!-- {nl:toetsenbord[5],sneltoets,alt+c,enter,toets} -->

---

## Achtergrondprocedure na het opslaan van een term

Een rechtsklik in de boekingenlijst slaat alleen het woord op en zet een
ronde in de wachtrij. Herhaalde rechtsklikken doen hetzelfde. De ronde draait
wanneer je op een menu-onderdeel klikt. De bovenbalk toont “background
procedure running: please wait…”, en het menucommando draait pas nadat de
ronde is gelukt. Meerdere termen die in één keer zijn opgeslagen, zijn één
ronde. Het termvenster zelf wacht op de ronde voordat het terugkeert.

Deze ronde is niet **Categorieën herberekenen**. Herberekenen wist treffers
en scoort opnieuw voor elk jaar: die eenheid bij een eenheidslogin, de
geconsolideerde werkeenheden of huishoudelijke diensten van dat deel bij een
deellogin, of elke rekening in de gekozen sectie bij een stichting- of
sectielogin. De ronde na een termwijziging laat een categorie die je met de
hand hebt gezet (getoond in het **vet**) staan, laat Excelrijen staan, en
loopt alleen het laatste boekjaar van elke rekening langs. Een omschrijving
die je hebt bewerkt (getoond in het **blauw**) wordt nog steeds gescoord; de
omschrijving blijft.

Een persoonlijke term herscoort dat deel of die eenheid, of die rekening
wanneer termen per rekening worden bewaard. Een gemeenschappelijke term
herscoort alle rekeningen van de stichting. Eén gemeenschappelijke term in
een reeks verbreedt de hele reeks tot dat bereik. Eerdere jaren worden niet
aangeraakt.
<!-- {en:background,procedure,please,wait,queued,menu,click,recalculate,difference,bold,category,blue,description,excel,latest,year,personal,scope,general,foundation,section,part,unit} -->
<!-- {nl:achtergrond,procedure,alstublieft,wachten,wachtrij,menu,klik,herberekenen,verschil,vet,categorie,blauw,omschrijving,excel,laatste,jaar,persoonlijk,bereik,gemeenschappelijk,stichting,sectie,deel,eenheid} -->

## De naam in het linkerpaneel

De kop is de titel die bij de login is opgeslagen: de eenheid, het deel, de
sectie of de stichting. Het is niet de gebruikersnaam.

Een eenheidslogin met twee of meer rekeningen krijgt een tweede regel. Bij
**Consolidated** is die regel het woord Consolidatie (of Consolidated). Bij
één rekening is het de naam van die rekening. Eén rekening, of een deel-,
sectie- of stichtinglogin, toont alleen de titel. Het browsertabblad gebruikt
de titel zonder de tweede regel.
<!-- {en:sidebar,title,subtitle,account,name[5],several,accounts,consolidated} -->
<!-- {nl:zijbalk,titel,ondertitel,rekening,naam[5],meerdere,rekeningen,consolidatie} -->
## Het balansvenster

**menu → Balans** opent het blad in een eigen venster. Een tweede klik
gebruikt datzelfde venster. **Uitloggen** sluit het. In het blad sluit Escape
eerst een open categorie; is er geen open, dan keert Escape terug naar het
boekhoudvenster.

Op het blad is eigen vermogen **vet zwart** wanneer het nog gelijk is aan het
beginbedrag van het jaar, en **vet rood** wanneer dat niet zo is.

Waar het menu ze aanbiedt, openen **Handmatige journaalposten** en
**Automatische journaalposten** vanuit hetzelfde menu. **Balans exporteren**
downloadt het werkboek.
<!-- {en:balance[5],sheet[5],escape,logout,window[5],bold,black,red,opening,manual,journal,automatic,export,equity,capital} -->
<!-- {nl:balans[5],blad[5],escape,uitloggen,balansvenster[5],vet,zwart,rood,beginstand,handmatig,journaal,automatisch,exporteren,eigen,vermogen} -->
## Maaltijden

Het maaltijdenblad is een aparte pagina, geen deel van deze matrix:
`https://expenses.apsurt.nl/maaltijden`. De login daarvan is niet de
boekhoudlogin. Een week loopt van zondag tot zaterdag. **Dag** toont vandaag,
**Week** toont de zeven dagen, **Reserveren** toont alleen je eigen rij.

Elke dag heeft vijf maaltijden, **O M A L P** (voor respectievelijk
`Ontbijt`, `Middag`, `Avond`, `Laat` en `Pakket`). Een klik wisselt een cel
tussen een lege cirkel en een volle. Je kunt alleen je eigen rij wijzigen.
De login `admin` is geen rij; die bewerkt de extra aantallen voor de huidige
week.
<!-- {en:meals[5],meal,sheet,eat,reserve,view,O,M,A,L,P} -->
<!-- {nl:maaltijden[5],maaltijd,blad,eten,reserveren,weergave,O,M,A,L,P} -->

---
