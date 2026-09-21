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

## How data is handled

- Nothing is written to disk or to a database. Form values live in the
  Streamlit session and disappear on sign-out, on "Clear all", or when the
  session ends.
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
