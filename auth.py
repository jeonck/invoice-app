"""Google sign-in gate for the invoice app.

Authentication is Streamlit's built-in OIDC (``st.login``); this module adds
the part OIDC does not give you — **a decision about who may use the app**.
Any Google account in the world can complete the sign-in flow, so the email
that comes back is checked against what this app is configured to admit:

Open to everyone, no sign-in needed (a tool offered to visitors: they write
an invoice and download it; signing in is only how they save it to their own
Drive)::

    [app_auth]
    allow_anonymous_use = true

Open to anyone who signs in, but sign-in required::

    [app_auth]
    allow_any_google_account = true

Or limited to named addresses (a private tool)::

    # .streamlit/secrets.toml   (never commit this file)
    [auth]
    redirect_uri = "http://localhost:8501/oauth2callback"
    cookie_secret = "<a long random string>"

    [auth.google]
    client_id = "<...>.apps.googleusercontent.com"
    client_secret = "<...>"
    server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

    [app_auth]
    allowed_emails = ["you@example.com"]

Set exactly one of the three access modes. If ``allow_anonymous_use`` is on it wins over
the others, so adding it to an app that has an allowlist makes that app
public — which is the point, but worth knowing before adding it "just to
test". Missing OIDC config, or none of the three, fails closed: the app
refuses to render the invoice form rather than serving it to whoever
arrives. Opening it up is a decision someone has to make on purpose, never
the result of a missing setting.
"""

import streamlit as st

PROVIDER = "google"


def allowed_emails() -> set:
    """Addresses permitted to use this app, lowercased."""
    try:
        configured = st.secrets["app_auth"]["allowed_emails"]
    except Exception:
        return set()
    if isinstance(configured, str):
        configured = [configured]
    try:
        return {str(email).strip().lower() for email in configured if str(email).strip()}
    except Exception:
        return set()


def oidc_configured() -> bool:
    """True when secrets carry everything st.login() needs for Google."""
    try:
        auth_section = st.secrets["auth"]
        provider = auth_section[PROVIDER]
        return bool(auth_section["redirect_uri"]
                    and auth_section["cookie_secret"]
                    and provider["client_id"]
                    and provider["client_secret"])
    except Exception:
        return False


def _claim(name, default=None):
    """Read one claim off st.user without blowing up when it is absent."""
    try:
        return getattr(st.user, name)
    except Exception:
        return default


def is_signed_in() -> bool:
    return bool(_claim("is_logged_in", False))


def signed_in_email() -> str:
    return str(_claim("email", "") or "").strip().lower()


def _flag(name: str) -> bool:
    """Read a boolean access flag. Only a real `true` counts, so a quoted
    "true" in the secrets cannot open the app by accident."""
    try:
        return st.secrets["app_auth"][name] is True
    except Exception:
        return False


def open_to_anyone() -> bool:
    """True when any signed-in Google account may use the app."""
    return _flag("allow_any_google_account")


def anonymous_use() -> bool:
    """True when the app is usable without signing in at all."""
    return _flag("allow_anonymous_use")


def access_configured() -> bool:
    """True when the app has been told who it serves, in any of the modes."""
    return anonymous_use() or open_to_anyone() or bool(allowed_emails())


def is_allowed(email: str) -> bool:
    if not email:
        return False
    # Signing in on a public tool exists to reach the person's own Drive, so
    # there is nothing for an allowlist to protect there.
    return anonymous_use() or open_to_anyone() or email in allowed_emails()


def begin_sign_in():
    """Start the OIDC redirect. Only ever from a click — it navigates away."""
    st.login(PROVIDER)


def current_user():
    """The signed-in, admitted email — or None."""
    if not is_signed_in():
        return None
    email = signed_in_email()
    return email if is_allowed(email) else None


def _email_is_verified() -> bool:
    """Google sets email_verified; treat a present-and-false claim as a no."""
    return _claim("email_verified", True) is not False


def require_login(L, preview=None) -> bool:
    """Render the sign-in screen unless this visitor may use the app.

    `preview` is an optional callable that shows what the app does. A gate
    that says only "sign in" gives a first-time visitor nothing to decide
    with — and no reason why a Google account is being asked for.
    """
    if not oidc_configured():
        st.error(f"\N{LOCK} {L['login_setup_title']}")
        st.markdown(L["login_setup_body"])
        st.code(
            '# .streamlit/secrets.toml\n'
            '[auth]\n'
            'redirect_uri = "http://localhost:8501/oauth2callback"\n'
            'cookie_secret = "<a long random string>"\n\n'
            '[auth.google]\n'
            'client_id = "<...>.apps.googleusercontent.com"\n'
            'client_secret = "<...>"\n'
            'server_metadata_url = '
            '"https://accounts.google.com/.well-known/openid-configuration"\n\n'
            '[app_auth]\n'
            'allowed_emails = ["you@example.com"]\n',
            language="toml",
        )
        return False

    # OIDC alone would admit any Google account, so "nothing configured" is a
    # misconfiguration rather than a permissive default.
    if not access_configured():
        st.error(f"\N{LOCK} {L['login_allowlist_title']}")
        st.markdown(L["login_allowlist_body"])
        st.code('[app_auth]\n'
                '# no sign-in needed; sign in only to save to Drive\n'
                'allow_anonymous_use = true\n\n'
                '# or: sign-in required, any Google account\n'
                'allow_any_google_account = true\n\n'
                '# or: only these addresses\n'
                'allowed_emails = ["you@example.com"]\n', language="toml")
        return False

    # A public tool renders for everyone; signing in is optional and only
    # unlocks saving to Drive.
    if anonymous_use():
        return True

    signed_in = is_signed_in()
    _, middle, _ = st.columns([1, 1.6, 1])
    with middle:
        st.markdown(f'<div class="inv-doc-title">{L["login_title"]}</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="inv-doc-caption">{L["login_caption"]}</div>',
                    unsafe_allow_html=True)

        if not signed_in:
            # st.login() redirects, so it must come from a click rather than
            # from the script run itself.
            if st.button(f"\N{KEY} {L['login_google']}", type="primary",
                         use_container_width=True, key="google_login_btn"):
                st.login(PROVIDER)
        else:
            email = signed_in_email()
            if not email or not _email_is_verified() or not is_allowed(email):
                st.error(L["login_denied"].format(email=email or "?"))
                st.button(f"\N{DOOR} {L['logout']}", on_click=st.logout,
                          use_container_width=True, key="denied_logout_btn")
                signed_in = False

    if not signed_in:
        # Shown full width, below the sign-in box rather than beside it.
        if preview is not None:
            preview()
        return False

    return True
