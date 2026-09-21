# Invoice Generator

A Streamlit app that turns a form into a PDF invoice, in Korean or English.
The create form is laid out in the same order as the document it produces, so
what you type is what the PDF looks like.

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Sign-in needs Streamlit's `auth` extra — `streamlit[auth]`, which pulls in
Authlib and **httpx**. Installing plain `streamlit` leaves the OIDC flow to
fail with `No module named 'httpx'` the moment someone clicks sign in, so
install from `requirements.txt` rather than by package name.

## Sign-in (required)

The app is gated by **Google sign-in** and **fails closed**: with no OIDC
configuration, or with nobody configured to use it, it refuses to render the invoice
form and shows what is missing instead. Bank details go into this form, so it
should never be an open page on the internet.

Google sign-in on its own admits *any* Google account, so the app has to be
told who it serves. Two ways, and one of them must be set:

```toml
[app_auth]
allow_anonymous_use = true                 # public tool: no sign-in to write and download
# or
allow_any_google_account = true            # sign-in required, any Google account
# or
allowed_emails = ["you@example.com"]       # a private tool
```

With `allow_anonymous_use`, writing an invoice and downloading the PDF needs
no account at all, and signing in is what unlocks Drive — saving a finished
invoice, and reopening a past one. That keeps the tool usable (and indexable)
for a first-time visitor while still giving returning users somewhere to keep
their work.

Both flags must be a real boolean `true` — the string `"true"` does not open
the app, so a quoting slip cannot unlock it by accident. `allow_anonymous_use`
takes precedence, so adding it alongside an `allowed_emails` list makes the app
public rather than combining the two. With none of the three set the app stays
locked: opening it up is a decision, never the
result of a missing setting. Each person's invoices go to their own Drive
either way, so the open mode does not make the operator a custodian of anyone
else's bank details.

**[docs/google-setup.md](docs/google-setup.md) walks through the whole setup**
(in Korean): the OAuth client, the consent screen, the `403: access_denied`
that a new client always hits, the secrets, and Drive saving. The summary:

```toml
# .streamlit/secrets.toml — or Settings -> Secrets on Streamlit Cloud
[auth]
redirect_uri = "https://<your-app>.streamlit.app/oauth2callback"
cookie_secret = "<a long random string>"
expose_tokens = ["access"]                 # only needed for Drive saving

[auth.google]
client_id = "<...>.apps.googleusercontent.com"
client_secret = "<...>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
client_kwargs = { scope = "openid email profile https://www.googleapis.com/auth/drive.file" }

[app_auth]
allowed_emails = ["you@example.com"]       # or allow_any_google_account = true
```

An address is admitted only when Google reports it as verified and it appears
in `allowed_emails` (matched case-insensitively). Everyone else gets a refusal
and a sign-out button.

Streamlit keeps the identity in a signed cookie, so a refresh does not sign you
out. Signing out clears the cookie **and** wipes the invoice form — bank details
included — from the session. The app's own settings live in `[app_auth]` so they
cannot collide with the `[auth]` section that Streamlit's OIDC support owns.

## Saving invoices to Google Drive (optional)

A generated invoice can be saved to **the signed-in person's own Drive** —
`Invoices/<year>/INV-....pdf` plus `INV-....json`, the form data. **Open from
Drive** in the create tab lists what was saved before and puts any of it back
into the form, which is what makes a recurring invoice a two-minute job rather
than a retype. Saving the same invoice number again replaces those two files
instead of piling up copies.

Signing in mid-session costs the form: the OIDC round trip reloads the page and
Streamlit starts a fresh session. The app warns about that before the redirect,
and anyone who means to save or reopen is better off signing in first — which
is exactly what the sidebar invites them to do.

The access token lasts about an hour and `st.login()` never refreshes it —
Streamlit mints no refresh token at all. Rather than discovering that at save
time, when re-authenticating costs the work, the app asks Drive once per session
whether the token still lives and says so up front, while signing in again is
free. A network failure is not treated as an expiry, so a blip cannot send
anyone through a pointless sign-in.

## Drafts

Folded into **Drafts · pick up later** in the create tab, since most sessions
never need it: **Save draft (file)** downloads the form as JSON and **Load a
draft file** puts it back. It opens by itself when a file fails to load, so the
reason is not hidden behind a collapsed panel. No account needed, so a visitor who is not signing in can still stop
and resume, and it survives anything that reloads the page — an expired token, a
stray refresh, a closed laptop.

A draft and a Drive-saved invoice are the same JSON, so either file loads through
either path. The file holds the bank details that were typed, which is worth
saying out loud to whoever downloads one; the app does.

It needs the two lines marked above (`expose_tokens` and the `drive.file`
scope) and the Google Drive API enabled on the same project — see
[docs/google-setup.md](docs/google-setup.md). Adding the scope to an existing
setup requires signing out and back in, since the old cookie carries a token
issued for the old scopes.

`drive.file` is the narrow scope: this app can only ever see files it created
itself, never the rest of the Drive. The app stores **no credential of its
own** — it borrows the access token from the sign-in that already happened, so
the files belong to the person who made them and access can be revoked from
their Google account. That token is short-lived and Streamlit does not refresh
it, so a long-open session may need a fresh sign-in before saving; the app says
so when that happens.

Without these settings the save button stays disabled and the app works exactly
as before — generate and download.

## How data is handled

- Nothing is written to disk or to a database on the server. Form values live
  in the Streamlit session and disappear on sign-out, on "Clear all", or when
  the session ends.
- The only thing that leaves the session is what you explicitly save to your own
  Google Drive. Those files contain the bank details you typed, so treat that
  folder the way you would treat the invoices themselves.
- Text from the form is escaped before it reaches reportlab, so a field cannot
  style itself in the PDF or make the server fetch a URL while the PDF builds.
- The generated PDF is **not** encrypted. Anyone who receives the file can read
  the account number in it.
- The PDF preview renders through pdf.js loaded from cdnjs. That is a third-party
  script holding the invoice bytes in the browser; self-hosting it, or pinning it
  with an SRI hash, is the next thing worth doing here.

## Korean font

`fonts/NanumGothic-*.ttf` (OFL, see `fonts/OFL.txt`) is bundled so Korean and the
won sign always render. The app falls back to a download only if the bundled file
is missing, and warns in the interface if neither is available rather than
producing a PDF full of empty boxes.
