# Maaltijden

Meal matrix for center `nl_dkg` (country `nederland`). Listens on
`127.0.0.1:8400`. Public URL: `https://expenses.apsurt.nl/maaltijden`.

Login uses `dbo.maaltijden_users`: `user_login` plus `passphrase` (plain
text; `NULL` means no password). Matrix rows are that list except login
`admin`, which only edits the extra counts. Marks live in
`dbo.maaltijden_data.code` (five bits per matrix person per day). All five
meals **O M A L P** cycle ◯ ↔ ⬤. Default is ◯. A person login can
edit only its own row.

Weeks run Sunday–Saturday. Terms in the UI are Dutch.
<!-- {en:maaltijden[5],matrix,login,passphrase,admin,extra,mark,marks,empty,circle,full,week,weeks,sunday,O,M,A,L,P} -->
<!-- {nl:maaltijden[5],matrix,inloggen,wachtwoord,beheer,extra,markering,markeringen,leeg,cirkel,vol,week,weken,zondag,O,M,A,L,P} -->



