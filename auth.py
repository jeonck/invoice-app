"""Google sign-in gate for the invoice app.

Authentication is Streamlit's built-in OIDC (``st.login``); this module adds
the part OIDC does not give you — **an allowlist**. Any Google account in the
world can complete the sign-in flow, so the email that comes back is checked
against the addresses configured for this app:

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

Both halves must be present. Missing OIDC config, or an empty allowlist,
fails closed: the app refuses to render the invoice form rather than serving
it to whoever arrives.
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


def current_user():
    """The signed-in, allowed email — or None."""
    if not is_signed_in():
        return None
    email = signed_in_email()
    return email if email and email in allowed_emails() else None


def _email_is_verified() -> bool:
    """Google sets email_verified; treat a present-and-false claim as a no."""
    return _claim("email_verified", True) is not False


def require_login(L) -> bool:
    """Render the sign-in screen unless this visitor may use the app."""
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

    # OIDC alone would let in any Google account, so an empty allowlist is a
    # misconfiguration rather than a permissive default.
    if not allowed_emails():
        st.error(f"\N{LOCK} {L['login_allowlist_title']}")
        st.markdown(L["login_allowlist_body"])
        st.code('[app_auth]\nallowed_emails = ["you@example.com"]\n', language="toml")
        return False

    _, middle, _ = st.columns([1, 1.6, 1])
    with middle:
        st.markdown(f'<div class="inv-doc-title">{L["login_title"]}</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="inv-doc-caption">{L["login_caption"]}</div>',
                    unsafe_allow_html=True)

        if not is_signed_in():
            # st.login() redirects, so it must come from a click rather than
            # from the script run itself.
            if st.button(f"\N{KEY} {L['login_google']}", type="primary",
                         use_container_width=True, key="google_login_btn"):
                st.login(PROVIDER)
            return False

        email = signed_in_email()
        if not email or not _email_is_verified() or email not in allowed_emails():
            st.error(L["login_denied"].format(email=email or "?"))
            st.button(f"\N{DOOR} {L['logout']}", on_click=st.logout,
                      use_container_width=True, key="denied_logout_btn")
            return False

    return True
