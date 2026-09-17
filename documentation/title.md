# Left-panel title

The heading at the top of the client sidebar (`:8300`) is two parts: a
**title** from the login row, and an optional **subtitle** when a personal
login has more than one bank account.

The title is always `dbo.person.title`, `dbo.center.title`, or
`dbo.country.title`. It is never the username, never `display_title()`, and
never invented in the React app.

---

## 1. Which login row

Access is the session’s person / center / country, same as the rest of the
client.

| Access | Title column (first hit wins) |
|---|---|
| person | `dbo.person.title` for the login username |
| center | `dbo.center.title` for the selected center, else `dbo.person.title` / `dbo.center.title` for the login username |
| country | `dbo.country.title` for the login username, else for `session.country` |

Lookup is `GET /api/auth/user?username=` on the hub (`find_user`: person,
then center, then country). The BFF (`sidebar_title`) asks for the live
column, not the title stored in the login cookie.

If every lookup is empty, the BFF falls back to the session cookie `title`
(whatever was written at login). The sidebar still shows nothing when that
is empty too.

The React app uses, in order: polled `/api/centrale/status` → `title`, then
the `/api/auth/me` title from login.

---

## 2. Subtitle — only several accounts

The bank list is loaded only for **personal** access (`getBanks`). Center
and country logins clear that list, so they never get a subtitle.

Then:

1. **0 or 1 account** → title only. No second line, even if that account
   has an `account_name`.
2. **2 or more accounts** → title plus a second line:
   - bank switcher on **Consolidated** → the country’s `dbo.language` label
     for English key `Consolidated` (`term_lang1` → `term_lang{language_id}`;
     Dutch is `Consolidatie`). If that row is missing, the English key is
     shown as-is.
   - bank switcher on one IBAN → that row’s `dbo.account.account_name`. If
     the name is blank, the subtitle is omitted (title only).

The two lines are one `h1`: title, then a line break and the subtitle in
`app-heading-sub`.

---

## 3. Decision sequence

```text
access?
  country → dbo.country.title (login, else session.country)
  center  → dbo.center.title (selected center, else login username)
  person  → dbo.person.title (login username)
if empty → session cookie title
if still empty → render no heading

personal login AND more than one account?
  no  → stop (title only)
  yes → bank view is consolidated?
          yes → dbo.language["Consolidated"] as subtitle
          no  → selected account_name as subtitle
        subtitle empty? → title only
        else → title + newline + subtitle
```

---

## 4. What this is not

- The browser tab uses the same title string (`document.title`), without the
  account subtitle.
- Menu labels (Export resultaat, Recalculate, …) are also `dbo.language`,
  but they are not the left-panel heading.
- `user_store.display_title(username)` (Title Case / UPPER) is only a
  default when **creating** a login with an empty title. It is not the
  sidebar path.
