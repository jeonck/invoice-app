# Invoice Generator

A Streamlit app that turns a form into a PDF invoice, in Korean or English.
The create form is laid out in the same order as the document it produces, so
what you type is what the PDF looks like.

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Login (required)

The app is gated and **fails closed**: with no account configured it refuses to
render the invoice form and shows the setup instructions instead. Bank details
go into this form, so it should never be an open page on the internet.

1. Generate a password hash — the password itself is never stored anywhere:

   ```bash
   python tools/hash_password.py
   ```

2. Paste the output into `.streamlit/secrets.toml` locally, or into
   **Settings → Secrets** on Streamlit Community Cloud:

   ```toml
   [app_auth.users]
   your-name = "pbkdf2_sha256$600000$...$..."
   ```

   More than one line adds more users. `.streamlit/secrets.toml` is gitignored —
   keep it that way.

Passwords are hashed with PBKDF2-HMAC-SHA256 (600,000 iterations, per-user salt)
and compared in constant time. Five failed attempts lock that browser session for
a minute; the passphrase is what carries the security, so make it a long one.

Signing in is per browser session: a refresh asks again, and signing out wipes
the invoice form — bank details included — from the session.

The section is `[app_auth]`, not `[auth]`, because `[auth]` belongs to
Streamlit's own `st.login()` OIDC support. Switching to Google sign-in later
therefore doesn't collide with this.

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
