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
    ('Maximum amount', 'Maximaal bedrag'),
    ('Apply', 'Toepassen')
) AS v (term_lang1, term_lang2)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.language l WHERE l.term_lang1 = v.term_lang1
);
GO
