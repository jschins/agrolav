-- Long UI texts. dbo.language columns hold at most 64 characters, so the
-- priority-rules popup lives here.
-- term_key is the English lookup. term_lang1 is English, term_lang2 is Dutch.
-- Run against database agrolav in SSMS. Does not replace a row that already exists.

USE agrolav
GO

IF OBJECT_ID(N'dbo.language_long', N'U') IS NULL
CREATE TABLE dbo.language_long (
    id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    term_key NVARCHAR(64) NOT NULL,
    term_lang1 NVARCHAR(MAX) NOT NULL,
    term_lang2 NVARCHAR(MAX) NOT NULL,
    CONSTRAINT uq_language_long_key UNIQUE (term_key)
)
GO

UPDATE dbo.language
SET term_lang1 = N'Priority rules',
    term_lang2 = N'Voorrangsregels'
WHERE term_lang1 = N'priority rules'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.language WHERE term_lang1 = N'Priority rules'
  );

UPDATE dbo.language
SET term_lang2 = N'Voorrangsregels'
WHERE term_lang1 = N'Priority rules';
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    ('Priority rules', 'Voorrangsregels'),
    ('Close', 'Sluiten')
) AS v (term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language l WHERE l.term_lang1 = v.term_lang1
);
GO

INSERT INTO dbo.language_long (term_key, term_lang1, term_lang2)
SELECT v.term_key, v.term_lang1, v.term_lang2
FROM (VALUES
    (
        N'priority rules',
        N'A saved term is matched against the booking name and description, joined and written in lower case. The term itself is also written in lower case before the match. Every matching term is compared. The one with the highest rank is kept.

## What counts as one word

A term with no `#` must match a whole word. A word is a run of letters (including accented letters), digits, and underscores. The run ends at a space, a line break, a dot, a dash, or any other mark. Common marks that end a word are / , : '' * + ( ).

- `albert` matches `albert.heijn`, `albert-heijn`, and `albert heijn`.
- `albert` does not match `albert_heijn` or `albert1heijn`. The underscore and the digit keep it one word.
- A term may contain the mark itself. `albert.heijn` matches that exact sequence, with a word boundary before `albert` and after `heijn`.

## The # mark

`#` stands for zero or more letters, dots, or asterisks. Several `#` in a row count as one such run. What happens next depends on whether the term contains a space.

No space in the term. The booking text is cut on spaces only. Each piece is tried as it stands. It is then tried again after every character other than a letter, a dot, or an asterisk has been dropped. A dash, a slash, a digit, an underscore, a comma, and the same class of marks disappear on that second try, so the letters on both sides join.

- `albert#heijn` matches `albert.heijn` (the `#` takes the dot) and `albert-heijn` and `albert1heijn` (the dash and the digit are dropped).
- `albert#heijn` does not match `albert heijn`. The space cuts the text into two pieces.
- `bck#praxis` matches `BCK*Praxis229`. The asterisk stays and is taken by `#`. The digits are dropped.

A space in the term. The term is one phrase. The space must occur in the booking. `#` still stands for letters, dots, or asterisks, and the phrase must start and end on a word boundary. Marks are not dropped on this path, so a dash inside the `#` span does not match.

## &&

The separator is the three characters space, `&&`, space. Each piece must match on its own. `heijn && machtiging` matches a booking that contains both words, in either order, each as a whole word. The two words need not sit next to each other. `heijn&&machtiging` is one phrase, because the spaces around `&&` are missing. The stored hit keeps the whole term, including `&&`.

## Which match wins

Rank is compared from the top. A higher step decides the winner. A lower step is used only when every step above it is equal.

1. A personal term beats every general term. Personal means stored on that person, or on that account when the country keeps terms per account. General means shared by the country. A personal single word beats a general `&&` term.
2. A term that contains ` && ` beats a single phrase. Both pieces of the `&&` term must already have matched.
3. Activa/passiva beats lasten/baten. Activa and passiva are the categories whose code is below 3000. Lasten and baten are the categories whose code is 3000 or above. The code is the number at the start of the category name, such as 1052 in `1052 Spaarrekening`. A name with no number counts as activa/passiva.
4. The later category name wins, then the later term. Later is dictionary order of the text. The category name is compared as stored, code included, so `1110 Kruisposten` beats `1052 Spaarrekening`. The term is compared after it has been lowercased, so `spaarrekening` beats `oranje`. The time the term was saved is ignored.

Categories that cannot take a hit are left out of the comparison: bank, source, equity, profit, and the balance and last-booked footers. A mirror category can take a hit.

The winning hit is `P:` plus the term for a personal match, or `G:` plus the term for a general match. When no term matches, the booking goes to the remainder category and the hit is left empty.',
        N'Een opgeslagen term wordt vergeleken met de naam en de omschrijving van de boeking, aan elkaar gezet en in kleine letters. De term zelf wordt ook in kleine letters gezet voor de vergelijking. Elke term die past wordt vergeleken. De term met de hoogste rang blijft staan.

## Wat een woord is

Een term zonder `#` moet een heel woord raken. Een woord is een reeks letters (ook letters met accenten), cijfers en underscores. De reeks eindigt bij een spatie, een nieuwe regel, een punt, een streepje, of een ander teken. Tekens die een woord vaak afsluiten zijn / , : '' * + ( ).

- `albert` past op `albert.heijn`, `albert-heijn` en `albert heijn`.
- `albert` past niet op `albert_heijn` of `albert1heijn`. De underscore en het cijfer houden het een woord.
- Een term mag het teken zelf bevatten. `albert.heijn` past op die reeks, met een woordgrens voor `albert` en na `heijn`.

## Het teken #

`#` staat voor nul of meer letters, punten of sterretjes. Meerdere `#` achter elkaar tellen als een dergelijke reeks. Het vervolg hangt ervan af of de term een spatie bevat.

Geen spatie in de term. De tekst van de boeking wordt alleen op spaties geknipt. Elk stuk wordt eerst geprobeerd zoals het er staat. Daarna opnieuw, nadat elk teken dat geen letter, punt of sterretje is, is weggelaten. Een streepje, een schuine streep, een cijfer, een underscore, een komma en dezelfde soort tekens verdwijnen bij die tweede poging, zodat de letters aan beide kanten aan elkaar komen.

- `albert#heijn` past op `albert.heijn` (de `#` neemt de punt) en op `albert-heijn` en `albert1heijn` (het streepje en het cijfer vallen weg).
- `albert#heijn` past niet op `albert heijn`. De spatie knipt de tekst in twee stukken.
- `bck#praxis` past op `BCK*Praxis229`. Het sterretje blijft en wordt door `#` genomen. De cijfers vallen weg.

Een spatie in de term. De term is een zin. De spatie moet in de boeking staan. `#` staat nog steeds voor letters, punten of sterretjes, en de zin moet beginnen en eindigen op een woordgrens. Tekens worden op dit pad niet weggelaten, zodat een streepje binnen de `#` niet past.

## &&

Het scheidingsteken is de drie tekens spatie, `&&`, spatie. Elk stuk moet zelf passen. `heijn && machtiging` past op een boeking die beide woorden bevat, in welke volgorde ook, elk als heel woord. De twee woorden hoeven niet naast elkaar te staan. `heijn&&machtiging` is een zin, omdat de spaties om `&&` ontbreken. De opgeslagen hit bewaart de hele term, inclusief `&&`.

## Welke treffer wint

De rang wordt van boven naar beneden vergeleken. Een hogere stap beslist. Een lagere stap telt alleen als elke stap erboven gelijk is.

1. Een persoonlijke term wint van elke gemeenschappelijke term. Persoonlijk betekent opgeslagen bij die persoon, of bij die rekening wanneer het land de termen per rekening bewaart. Gemeenschappelijk betekent gedeeld door het land. Een persoonlijk enkel woord wint van een gemeenschappelijke `&&`-term.
2. Een term die ` && ` bevat wint van een enkele zin. Beide stukken van de `&&`-term moeten al gepast hebben.
3. Activa/passiva wint van lasten/baten. Activa en passiva zijn de categorieën met een code onder 3000. Lasten en baten zijn de categorieën met een code van 3000 of hoger. De code is het getal aan het begin van de categorienaam, zoals 1052 in `1052 Spaarrekening`. Een naam zonder getal telt als activa/passiva.
4. De latere categorienaam wint, daarna de latere term. Later is de woordenboekvolgorde van de tekst. De categorienaam wordt vergeleken zoals die is opgeslagen, met de code erbij, zodat `1110 Kruisposten` wint van `1052 Spaarrekening`. De term wordt vergeleken nadat die in kleine letters is gezet, zodat `spaarrekening` wint van `oranje`. Het tijdstip waarop de term is opgeslagen telt niet.

Categorieën die geen hit kunnen krijgen blijven buiten de vergelijking: bank, source, equity, profit, en de voetregels saldo en datum. Een mirror-categorie kan wel een hit krijgen.

De winnende hit is `P:` plus de term bij een persoonlijke treffer, of `G:` plus de term bij een gemeenschappelijke treffer. Als geen term past, gaat de boeking naar de restcategorie en blijft de hit leeg.'
    )
) AS v (term_key, term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language_long l WHERE l.term_key = v.term_key
);
GO

INSERT INTO dbo.language_long (term_key, term_lang1, term_lang2)
SELECT v.term_key, v.term_lang1, v.term_lang2
FROM (VALUES
    (
        N'term window hint',
        N'Term Window. Return to overview using Ctrl+Tab or Alt+M. Edits save immediately; matching bookings update in the background. # matches zero or more letters or dots within one word (not across spaces). Use && when both phrases must match (e.g. heijn && machtiging).',
        N'Termvenster. Terug naar het overzicht met Ctrl+Tab of Alt+M. Bewerkingen worden direct opgeslagen; passende boekingen worden op de achtergrond bijgewerkt. # past op nul of meer letters of punten binnen een woord (niet over spaties heen). Gebruik && wanneer beide zinnen moeten passen (bijv. heijn && machtiging).'
    )
) AS v (term_key, term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language_long l WHERE l.term_key = v.term_key
);
GO

UPDATE dbo.language_long
SET term_lang1 = REPLACE(REPLACE(term_lang1, N'albert && heijn', N'heijn && machtiging'), N'albert&&heijn', N'heijn&&machtiging'),
    term_lang2 = REPLACE(REPLACE(term_lang2, N'albert && heijn', N'heijn && machtiging'), N'albert&&heijn', N'heijn&&machtiging');
GO

UPDATE dbo.language
SET term_lang1 = 'Sign convention transactions',
    term_lang2 = 'Tekenconventie transacties'
WHERE term_lang1 IN ('sign convention', 'sign convention transactions')
  AND NOT EXISTS (
      SELECT 1 FROM dbo.language WHERE term_lang1 = 'Sign convention transactions'
  );
GO

UPDATE dbo.language
SET term_lang2 = 'Tekenconventie transacties'
WHERE term_lang1 = 'Sign convention transactions';
GO

UPDATE dbo.language
SET term_lang1 = 'Sign convention journal posts',
    term_lang2 = 'Tekenconventie journaalposten'
WHERE term_lang1 = 'sign convention journal posts'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.language WHERE term_lang1 = 'Sign convention journal posts'
  );
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    ('Sign convention transactions', 'Tekenconventie transacties'),
    ('Sign convention journal posts', 'Tekenconventie journaalposten')
) AS v (term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language l WHERE l.term_lang1 = v.term_lang1
);
GO

UPDATE dbo.language
SET term_lang2 = 'Tekenconventie journaalposten'
WHERE term_lang1 = 'Sign convention journal posts';
GO

UPDATE dbo.language_long
SET term_key = N'sign convention transactions'
WHERE term_key = N'sign convention'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.language_long WHERE term_key = N'sign convention transactions'
  );
GO

INSERT INTO dbo.language_long (term_key, term_lang1, term_lang2)
SELECT v.term_key, v.term_lang1, v.term_lang2
FROM (VALUES
    (
        N'sign convention transactions',
        N'The first IBAN column (account holder) becomes richer when the amount is positive, and poorer when the amount is negative.

The second IBAN column (counterparty) becomes poorer when the amount is positive, and richer when the amount is negative.

Another way to say the same thing:

A positive amount is taken from the counterparty and deposited on the account holder (money moves from right to left).

A negative amount is taken from the account holder and deposited on the counterparty (money moves from left to right).',
        N'De eerste IBAN kolom (rekeninghouder) wordt rijker als het bedrag positief is, armer als het bedrag negatief is.

De tweede IBAN kolom (tegenpartij) wordt armer als het bedrag positief is, rijker als het bedrag negatief is.

Een andere manier om hetzelfde te zeggen is als volgt:

Bij een positief bedrag wordt een geldbedrag weggehaald bij de tegenpartij en gestort op de rekeninghouder (geld verschuift van rechts naar links).

Bij een negatief bedrag wordt een geldhoeveelheid weggehaald bij de rekeninghouder en gestort op de tegenpartij (geld verschuift van links naar rechts).'
    )
) AS v (term_key, term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language_long l WHERE l.term_key = v.term_key
);
GO

INSERT INTO dbo.language_long (term_key, term_lang1, term_lang2)
SELECT v.term_key, v.term_lang1, v.term_lang2
FROM (VALUES
    (
        N'sign convention journal posts',
        N'The ''to'' side of the post sees the signed amount added;

The ''from'' side of the post sees the signed amount added or subtracted according to the APR product rule:

Subtracted when an asset is booked to a liability, an expense, or an income;

Added in all other cases.',
        N'De ''naar''-kant van de post ziet het getekende bedrag opgeteld;

De ''van''-kant van de post ziet het getekende bedrag opgeteld of afgetrokken volgens de APR-produktregel:

Afgetrokken als een Activum wordt geboekt op een Passivum, Last, of Baat;

Opgeteld in alle andere gevallen.'
    )
) AS v (term_key, term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language_long l WHERE l.term_key = v.term_key
);
GO

UPDATE dbo.language
SET term_lang1 = 'Calculate cross-postings',
    term_lang2 = 'Bereken kruisposten'
WHERE term_lang1 = 'Cross-postings'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.language WHERE term_lang1 = 'Calculate cross-postings'
  );
GO

UPDATE dbo.language
SET term_lang1 = 'Calculate cross-postings',
    term_lang2 = 'Bereken kruisposten'
WHERE term_lang1 = 'cross-postings'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.language WHERE term_lang1 = 'Calculate cross-postings'
  );
GO

UPDATE dbo.language
SET term_lang2 = 'Bereken kruisposten'
WHERE term_lang1 = 'Calculate cross-postings';
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    ('Calculate cross-postings', 'Bereken kruisposten')
) AS v (term_lang1, v.term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language l WHERE l.term_lang1 = v.term_lang1
);
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    (
        'Remove all bank statements; leave categorizations untouched',
        'Verwijder alle bankafschriften; laat categorisaties ongemoeid'
    ),
    (
        'Clear categories, cross-postings; keep terms, statements',
        'Wis categorisatie en kruisposten; behoud termen, afschriften'
    ),
    ('Cancel', 'Annuleren')
) AS v (term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language l WHERE l.term_lang1 = v.term_lang1
);
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    (
        'Remove all manual journal entries',
        'Verwijder alle handmatige journaalposten'
    ),
    (
        'Remove all automatic journal entries',
        'Verwijder alle automatische journaalposten'
    ),
    ('Smaller expenses', 'Kleinere uitgaven'),
    ('Smaller income', 'Kleinere inkomsten'),
    ('Maximum amount', 'Maximaal bedrag'),
    ('Apply', 'Toepassen'),
    ('From scratch', 'Vanaf nul'),
    ('Incremental', 'Incrementeel'),
    ('Color convention', 'Kleurconventie')
) AS v (term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language l WHERE l.term_lang1 = v.term_lang1
);
GO

INSERT INTO dbo.language_long (term_key, term_lang1, term_lang2)
SELECT v.term_key, v.term_lang1, v.term_lang2
FROM (VALUES
    (
        N'color convention',
        N'Green underlined amounts are taken from a sub-ledger.
Blue underlined amounts are taken from journal entries (both manual and automatic).

*Legend*
Manual journal entries are ledger posts with a fixed amount.
Automatic journal entries are ledger posts with percentages of
- either the current value of a ledger category (flag set to 1)
- or the sum of all transactions booked on that ledger category in this year (flag set to 0)

The distinction between the flags makes it possible to depreciate more in the first year than in later years.',
        N'Groen onderlijnde bedragen zijn genomen van een subadministratie
Blauw onderlijnde bedragen van journaalposten (zowel handmatig als automatisch)

*Legenda*
Handmatige journaalposten betreffen grootboekposten met vaste bedrag
Automatische journaalposten betreffen grootboekposten met percentages van
- ofwel de actuele waarde van een grootboekcategorie (vlag op 1)
- ofwel de som van alle op die grootboekcategorie in dit jaar geboekte transacties (vlag op 0)

Het onderscheid in de vlaggen maakt het mogelijk om het eerste jaar meer af te schrijven dan in latere jaren.'
    )
) AS v (term_key, term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language_long l WHERE l.term_key = v.term_key
);
GO

UPDATE dbo.language
SET term_lang2 = '<b style="color:red">Rood: L&#8594;R</b><br>Zwart: R&#8594;L'
WHERE term_lang2 LIKE '%L->R%'
   OR term_lang2 LIKE '%Rood:%';
GO

UPDATE dbo.language_long
SET term_lang1 = N'<p>A saved term is matched against the booking name and description, joined and written in lower case. The term itself is also written in lower case before the match. Every matching term is compared. The one with the highest rank is kept.</p>
<p><strong>What a word is</strong></p>
<p>A term with no <code>#</code> must hit a whole word. A word is a run of letters (including accented letters), digits, and underscores. The run ends at a space, a line break, a dot, a dash, or another mark. Marks that often end a word are / , : '' * + ( ).</p>
<ul>
<li><code>albert</code> matches <code>albert.heijn</code>, <code>albert-heijn</code>, and <code>albert heijn</code>.</li>
<li><code>albert</code> does not match <code>albert_heijn</code> or <code>albert1heijn</code>. The underscore and the digit keep it one word.</li>
<li>A term may contain the mark itself. <code>albert.heijn</code> matches that sequence, with a word boundary before <code>albert</code> and after <code>heijn</code>.</li>
</ul>
<p><strong>The # mark</strong></p>
<p><code>#</code> stands for zero or more letters, dots, or asterisks. Several <code>#</code> in a row count as one such run. What follows depends on whether the term contains a space.</p>
<p>No space in the term. The booking text is cut on spaces only. Each piece is first tried as it stands. Then again, after every character that is not a letter, a dot, or an asterisk has been dropped. A dash, a slash, a digit, an underscore, a comma, and the same kind of marks disappear on that second try, so the letters on both sides join.</p>
<ul>
<li><code>albert#heijn</code> matches <code>albert.heijn</code> (the <code>#</code> takes the dot) and <code>albert-heijn</code> and <code>albert1heijn</code> (the dash and the digit are dropped).</li>
<li><code>albert#heijn</code> does not match <code>albert heijn</code>. The space cuts the text into two pieces.</li>
<li><code>bck#praxis</code> matches <code>BCK*Praxis229</code>. The asterisk stays and is taken by <code>#</code>. The digits are dropped.</li>
</ul>
<p>A space in the term. The term is one phrase. The space must occur in the booking. <code>#</code> still stands for letters, dots, or asterisks, and the phrase must start and end on a word boundary. Marks are not dropped on this path, so a dash inside the <code>#</code> span does not match.</p>
<p><strong>The &amp;&amp; mark</strong></p>
<p>The separator is the three characters space, <code>&amp;&amp;</code>, space. Each piece must match on its own. <code>heijn &amp;&amp; machtiging</code> matches a booking that contains both words, in either order, each as a whole word. The two words need not sit next to each other. <code>heijn&amp;&amp;machtiging</code> is one phrase, because the spaces around <code>&amp;&amp;</code> are missing. The stored hit keeps the whole term, including <code>&amp;&amp;</code>.</p>
<p><strong>Which hit wins</strong></p>
<p>Rank is compared from the top downward. A higher step decides. A lower step counts only when every step above it is equal.</p>
<ol>
<li>A personal term beats every general term. Personal means stored on that person, or on that account when the country keeps terms per account. General means shared by the country. A personal single word beats a general <code>&amp;&amp;</code> term.</li>
<li>A term that contains <code> &amp;&amp; </code> beats a single phrase. Both pieces of the <code>&amp;&amp;</code> term must already have matched.</li>
<li>Activa/passiva beats lasten/baten. Activa and passiva are the categories whose code is below 3000. Lasten and baten are the categories whose code is 3000 or above. The code is the number at the start of the category name, such as 1052 in <code>1052 Spaarrekening</code>. A name with no number counts as activa/passiva.</li>
<li>The later category name wins, then the later term. Later is dictionary order of the text. The category name is compared as stored, code included, so <code>1110 Kruisposten</code> beats <code>1052 Spaarrekening</code>. The term is compared after it has been lowercased, so <code>spaarrekening</code> beats <code>oranje</code>. The time the term was saved does not count.</li>
</ol>
<p>Categories that cannot take a hit stay out of the comparison: bank, source, equity, profit, and the balance and date footers. A mirror category can take a hit.</p>
<p>The winning hit is <code>P:</code> plus the term for a personal hit, or <code>G:</code> plus the term for a general hit. When no term matches, the booking goes to the remainder category and the hit stays empty.</p>',
    term_lang2 = N'<p>Een opgeslagen term wordt vergeleken met de naam en de omschrijving van de boeking, aan elkaar gezet en in kleine letters. De term zelf wordt ook in kleine letters gezet voor de vergelijking. Elke term die past wordt vergeleken. De term met de hoogste rang blijft staan.</p>
<p><strong>Wat een woord is</strong></p>
<p>Een term zonder <code>#</code> moet een heel woord raken. Een woord is een reeks letters (ook letters met accenten), cijfers en underscores. De reeks eindigt bij een spatie, een nieuwe regel, een punt, een streepje, of een ander teken. Tekens die een woord vaak afsluiten zijn / , : '' * + ( ).</p>
<ul>
<li><code>albert</code> past op <code>albert.heijn</code>, <code>albert-heijn</code> en <code>albert heijn</code>.</li>
<li><code>albert</code> past niet op <code>albert_heijn</code> of <code>albert1heijn</code>. De underscore en het cijfer houden het een woord.</li>
<li>Een term mag het teken zelf bevatten. <code>albert.heijn</code> past op die reeks, met een woordgrens voor <code>albert</code> en na <code>heijn</code>.</li>
</ul>
<p><strong>Het teken #</strong></p>
<p><code>#</code> staat voor nul of meer letters, punten of sterretjes. Meerdere <code>#</code> achter elkaar tellen als een dergelijke reeks. Het vervolg hangt ervan af of de term een spatie bevat.</p>
<p>Geen spatie in de term. De tekst van de boeking wordt alleen op spaties geknipt. Elk stuk wordt eerst geprobeerd zoals het er staat. Daarna opnieuw, nadat elk teken dat geen letter, punt of sterretje is, is weggelaten. Een streepje, een schuine streep, een cijfer, een underscore, een komma en dezelfde soort tekens verdwijnen bij die tweede poging, zodat de letters aan beide kanten aan elkaar komen.</p>
<ul>
<li><code>albert#heijn</code> past op <code>albert.heijn</code> (de <code>#</code> neemt de punt) en op <code>albert-heijn</code> en <code>albert1heijn</code> (het streepje en het cijfer vallen weg).</li>
<li><code>albert#heijn</code> past niet op <code>albert heijn</code>. De spatie knipt de tekst in twee stukken.</li>
<li><code>bck#praxis</code> past op <code>BCK*Praxis229</code>. Het sterretje blijft en wordt door <code>#</code> genomen. De cijfers vallen weg.</li>
</ul>
<p>Een spatie in de term. De term is een zin. De spatie moet in de boeking staan. <code>#</code> staat nog steeds voor letters, punten of sterretjes, en de zin moet beginnen en eindigen op een woordgrens. Tekens worden op dit pad niet weggelaten, zodat een streepje binnen de <code>#</code> niet past.</p>
<p><strong>Het teken &amp;&amp;</strong></p>
<p>Het scheidingsteken is de drie tekens spatie, <code>&amp;&amp;</code>, spatie. Elk stuk moet zelf passen. <code>heijn &amp;&amp; machtiging</code> past op een boeking die beide woorden bevat, in welke volgorde ook, elk als heel woord. De twee woorden hoeven niet naast elkaar te staan. <code>heijn&amp;&amp;machtiging</code> is een zin, omdat de spaties om <code>&amp;&amp;</code> ontbreken. De opgeslagen hit bewaart de hele term, inclusief <code>&amp;&amp;</code>.</p>
<p><strong>Welke treffer wint</strong></p>
<p>De rang wordt van boven naar beneden vergeleken. Een hogere stap beslist. Een lagere stap telt alleen als elke stap erboven gelijk is.</p>
<ol>
<li>Een persoonlijke term wint van elke gemeenschappelijke term. Persoonlijk betekent opgeslagen bij die persoon, of bij die rekening wanneer het land de termen per rekening bewaart. Gemeenschappelijk betekent gedeeld door het land. Een persoonlijk enkel woord wint van een gemeenschappelijke <code>&amp;&amp;</code>-term.</li>
<li>Een term die <code> &amp;&amp; </code> bevat wint van een enkele zin. Beide stukken van de <code>&amp;&amp;</code>-term moeten al gepast hebben.</li>
<li>Activa/passiva wint van lasten/baten. Activa en passiva zijn de categorieën met een code onder 3000. Lasten en baten zijn de categorieën met een code van 3000 of hoger. De code is het getal aan het begin van de categorienaam, zoals 1052 in <code>1052 Spaarrekening</code>. Een naam zonder getal telt als activa/passiva.</li>
<li>De latere categorienaam wint, daarna de latere term. Later is de woordenboekvolgorde van de tekst. De categorienaam wordt vergeleken zoals die is opgeslagen, met de code erbij, zodat <code>1110 Kruisposten</code> wint van <code>1052 Spaarrekening</code>. De term wordt vergeleken nadat die in kleine letters is gezet, zodat <code>spaarrekening</code> wint van <code>oranje</code>. Het tijdstip waarop de term is opgeslagen telt niet.</li>
</ol>
<p>Categorieën die geen hit kunnen krijgen blijven buiten de vergelijking: bank, source, equity, profit, en de voetregels saldo en datum. Een mirror-categorie kan wel een hit krijgen.</p>
<p>De winnende hit is <code>P:</code> plus de term bij een persoonlijke treffer, of <code>G:</code> plus de term bij een gemeenschappelijke treffer. Als geen term past, gaat de boeking naar de restcategorie en blijft de hit leeg.</p>'
WHERE term_key = N'priority rules';
GO

UPDATE dbo.language_long
SET term_lang1 = N'<p>Term window. Return to the overview with Ctrl+Tab or Alt+M.</p>
<p>Edits are saved immediately; matching bookings are updated in the background.</p>
<p><code>#</code> matches zero or more letters or dots within one word (not across spaces). Use <code>&amp;&amp;</code> when both phrases must match (e.g. heijn &amp;&amp; machtiging).</p>',
    term_lang2 = N'<p>Termvenster. Terug naar het overzicht met Ctrl+Tab of Alt+M.</p>
<p>Bewerkingen worden direct opgeslagen; passende boekingen worden op de achtergrond bijgewerkt.</p>
<p><code>#</code> past op nul of meer letters of punten binnen een woord (niet over spaties heen). Gebruik <code>&amp;&amp;</code> wanneer beide zinnen moeten passen (bijv. heijn &amp;&amp; machtiging).</p>'
WHERE term_key = N'term window hint';
GO

UPDATE dbo.language_long
SET term_lang1 = N'<p>The first IBAN column (account holder) becomes richer when the amount is positive, and poorer when the amount is negative.</p>
<p>The second IBAN column (counterparty) becomes poorer when the amount is positive, and richer when the amount is negative.</p>
<p>Another way of saying the same thing is as follows:</p>
<p>With a positive amount, a sum of money is taken from the counterparty and deposited on the account holder (money moves from right to left).</p>
<p>With a negative amount, a quantity of money is taken from the account holder and deposited on the counterparty (money moves from left to right).</p>',
    term_lang2 = N'<p>De eerste IBAN kolom (rekeninghouder) wordt rijker als het bedrag positief is, armer als het bedrag negatief is.</p>
<p>De tweede IBAN kolom (tegenpartij) wordt armer als het bedrag positief is, rijker als het bedrag negatief is.</p>
<p>Een andere manier om hetzelfde te zeggen is als volgt:</p>
<p>Bij een positief bedrag wordt een geldbedrag weggehaald bij de tegenpartij en gestort op de rekeninghouder (geld verschuift van rechts naar links).</p>
<p>Bij een negatief bedrag wordt een geldhoeveelheid weggehaald bij de rekeninghouder en gestort op de tegenpartij (geld verschuift van links naar rechts).</p>'
WHERE term_key = N'sign convention transactions';
GO

UPDATE dbo.language_long
SET term_lang1 = N'<p>The ''to'' side of the post sees the signed amount added;</p>
<p>The ''from'' side of the post sees the signed amount added or subtracted according to the APR product rule:</p>
<p>Subtracted when an asset is booked to a liability, an expense, or an income;</p>
<p>Added in all other cases.</p>',
    term_lang2 = N'<p>De ''naar''-kant van de post ziet het getekende bedrag opgeteld;</p>
<p>De ''van''-kant van de post ziet het getekende bedrag opgeteld of afgetrokken volgens de APR-produktregel:</p>
<p>Afgetrokken als een Activum wordt geboekt op een Passivum, Last, of Baat;</p>
<p>Opgeteld in alle andere gevallen.</p>'
WHERE term_key = N'sign convention journal posts';
GO

UPDATE dbo.language_long
SET term_lang1 = N'<p><strong style="color:#15803d">Green underlined amounts</strong> are taken from a sub-ledger.</p>
<p><strong style="color:#2563eb">Blue underlined amounts</strong> are taken from both manual and automatic journal entries.</p>
<p><strong style="font-size:calc(1em + 2pt)">Legend</strong></p>
<p>Manual journal entries are fixed amounts.</p>
<p>Automatic journal entries are percentages of</p>
<ul>
<li>either the current value of a ledger category (flag set to 1)</li>
<li>or the sum of all transactions booked on that ledger category in this year (flag set to 0)</li>
</ul>
<p>The distinction between the flags makes it possible to depreciate more in the first year than in later years.</p>
<p>Manual and automatic journal entries are visible only on the balance sheet (blue underlined amounts).</p>
<p>Bank statements are visible only in the results (black amounts, as opposed to grey ones).</p>
<p>A sub-ledger records how a ledger category is built up; this is typically the case for private creditors and debtors (for whom it is not useful to give each one a ledger category of their own).</p>',
    term_lang2 = N'<p><strong style="color:#15803d">Groen onderlijnde bedragen</strong> zijn genomen van een subadministratie</p>
<p><strong style="color:#2563eb">Blauw onderlijnde bedragen</strong> zijn genomen van zowel handmatige als automatische journaalposten</p>
<p><strong style="font-size:calc(1em + 2pt)">Legenda</strong></p>
<p>Handmatige journaalposten betreffen vaste bedragen</p>
<p>Automatische journaalposten betreffen percentages van</p>
<ul>
<li>ofwel de actuele waarde van een grootboekcategorie (vlag op 1)</li>
<li>ofwel de som van alle op die grootboekcategorie in dit jaar geboekte transacties (vlag op 0)</li>
</ul>
<p>Het onderscheid in de vlaggen maakt het mogelijk om het eerste jaar meer af te schrijven dan in latere jaren.</p>
<p>Handmatige en automatische journaalposten zijn alleen zichtbaar in de balans (blauw onderlijnde bedragen)</p>
<p>Bankafschriften zijn alleen zichtbaar in de resultaten (zwarte bedragen, in tegenstelling tot grijze)</p>
<p>Een subadministratie houdt bij op welke wijze een grootboekcategorie is opgebouwd; dit is typisch het geval voor particuliere crediteuren en debiteuren (waarvoor het immers niet zinvol is om eenieder van een eigen grootboekcategorie te voorzien)</p>'
WHERE term_key = N'color convention';
GO

INSERT INTO dbo.language (term_lang1, term_lang2)
SELECT v.term_lang1, v.term_lang2
FROM (VALUES
    (
        N'recalculating categories before logging out...',
        N'categorieën herberekenen voor het uitloggen...'
    )
) AS v (term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language l WHERE l.term_lang1 = v.term_lang1
);
GO
