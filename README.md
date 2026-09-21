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
configuration, or with an empty allowlist, it refuses to render the invoice
form and shows what is missing instead. Bank details go into this form, so it
should never be an open page on the internet.

Note that Google sign-in on its own admits *any* Google account — the allowlist
is what limits the app to you, so both halves below are required.

### 1. Create an OAuth client

In the [Google Cloud Console](https://console.cloud.google.com/apis/credentials):
**Create credentials → OAuth client ID → Web application**, and add the
redirect URI for each place the app runs:

| Where | Authorized redirect URI |
| --- | --- |
| Local | `http://localhost:8501/oauth2callback` |
| Streamlit Cloud | `https://<your-app>.streamlit.app/oauth2callback` |

Then check the app's **publishing status** on the OAuth consent screen
(**APIs & Services → OAuth consent screen → Audience**). A new client starts in
**Testing**, where Google refuses everyone who is not listed:

> 403: access_denied — the app is currently being tested and only developer-approved testers can access it

Either add your own address under **Test users**, or press **Publish app**. All
the scopes this app uses (`openid`, `email`, `profile`, `drive.file`) are
non-sensitive, so publishing needs no Google verification review. Publishing does
not widen who can use the app either — `allowed_emails` still decides that.

### 2. Configure secrets

Put this in `.streamlit/secrets.toml` locally, or in **Settings → Secrets** on
Streamlit Community Cloud. The file is gitignored — keep it that way.

```toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "<a long random string>"   # e.g. python -c "import secrets; print(secrets.token_urlsafe(32))"

[auth.google]
client_id = "<...>.apps.googleusercontent.com"
client_secret = "<...>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[app_auth]
allowed_emails = ["you@example.com"]       # who may actually use the app
```

An address is admitted only when Google reports it as verified and it appears
in `allowed_emails` (matched case-insensitively). Everyone else gets a refusal
and a sign-out button.

Streamlit keeps the identity in a signed cookie, so a refresh does not sign you
out. Signing out clears the cookie **and** wipes the invoice form — bank details
included — from the session.

The app's own settings live in `[app_auth]` so they cannot collide with the
`[auth]` section that Streamlit's OIDC support owns.

## Saving invoices to Google Drive (optional)

With two more settings, a generated invoice can be saved to **the signed-in
person's own Drive** — `Invoices/<year>/INV-....pdf` plus `INV-....json`, the
form data, so an invoice can be loaded back and reissued later. Saving the same
invoice number again replaces those two files instead of piling up copies.

```toml
[auth]
expose_tokens = ["access"]                 # alongside redirect_uri / cookie_secret

[auth.google]
client_kwargs = { scope = "openid email profile https://www.googleapis.com/auth/drive.file" }
```

Enable the **Google Drive API** for the same project in the Cloud Console. The
`drive.file` scope is the narrow one: this app can only ever see files it created
itself, never the rest of the Drive.

The app stores **no credential of its own** — it borrows the access token from
the sign-in that already happened, so the files belong to the person who made
them and access can be revoked from their Google account settings. That token is
short-lived and Streamlit does not refresh it, so a long-open session may need a
fresh sign-in before saving; the app says so when that happens.

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
