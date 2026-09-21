"""Password gate for the invoice app.

Credentials are read from Streamlit secrets and only ever stored as a
PBKDF2-SHA256 hash — the app never holds a plaintext password:

    # .streamlit/secrets.toml   (never commit this file)
    [app_auth.users]
    jeonck = "pbkdf2_sha256$600000$<salt>$<hash>"

Kept out of ``[auth]`` on purpose: that section belongs to Streamlit's own
``st.login()`` OIDC support, which reads ``[auth.<provider>]`` subsections.

Generate the value with `python tools/hash_password.py`.

With no users configured the gate fails closed: the app refuses to render
and explains the setup instead of quietly serving an open invoice form.
"""

import base64
import hashlib
import hmac
import os
import time

import streamlit as st

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000  # OWASP's floor for PBKDF2-HMAC-SHA256
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60

# Compared against when the username is unknown, so a wrong username costs
# the same time as a wrong password and cannot be told apart from one.
_DUMMY_HASH = (
    "pbkdf2_sha256$600000$AAAAAAAAAAAAAAAAAAAAAA==$"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """Return a self-describing hash string for secrets.toml."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join([ALGORITHM, str(iterations), _b64(salt), _b64(digest)])


def verify_password(password: str, encoded: str) -> bool:
    """Check a password against a stored hash in constant time."""
    try:
        algorithm, iterations, salt_b64, digest_b64 = str(encoded).split("$")
        if algorithm != ALGORITHM:
            return False
        expected = _unb64(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _unb64(salt_b64),
            int(iterations), dklen=len(expected),
        )
    except Exception:
        return False
    return hmac.compare_digest(actual, expected)


def configured_users() -> dict:
    """Users from secrets. Empty when secrets are missing or malformed."""
    try:
        users = st.secrets["app_auth"]["users"]
    except Exception:
        return {}
    try:
        return {str(name): str(value) for name, value in dict(users).items()}
    except Exception:
        return {}


def current_user():
    return st.session_state.get("auth_user")


def logout():
    """Callback: end the session's authentication."""
    st.session_state.pop("auth_user", None)
    st.session_state.pop("auth_failures", None)
    st.session_state.pop("auth_locked_until", None)


def _lock_remaining() -> int:
    until = st.session_state.get("auth_locked_until", 0)
    return max(0, int(until - time.time()))


def _register_failure():
    failures = st.session_state.get("auth_failures", 0) + 1
    st.session_state.auth_failures = failures
    if failures >= MAX_ATTEMPTS:
        st.session_state.auth_locked_until = time.time() + LOCKOUT_SECONDS
        st.session_state.auth_failures = 0


def require_login(L) -> bool:
    """Render the login screen unless this session is already signed in.

    Returns True when the caller may render the app. The lockout counter
    lives in session state, so it slows down guessing in one browser
    session rather than a determined attacker — the passphrase is what
    carries the security here.
    """
    if current_user():
        return True

    users = configured_users()
    if not users:
        st.error(f"🔒 {L['login_setup_title']}")
        st.markdown(L["login_setup_body"])
        st.code(
            "# .streamlit/secrets.toml\n"
            "[app_auth.users]\n"
            'your-name = "pbkdf2_sha256$600000$...$..."\n',
            language="toml",
        )
        st.code("python tools/hash_password.py", language="bash")
        return False

    _, middle, _ = st.columns([1, 1.6, 1])
    with middle:
        st.markdown(f'<div class="inv-doc-title">{L["login_title"]}</div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="inv-doc-caption">{L["login_caption"]}</div>',
                    unsafe_allow_html=True)

        locked_for = _lock_remaining()
        with st.form("login_form"):
            username = st.text_input(L["login_user"], autocomplete="username")
            password = st.text_input(L["login_password"], type="password",
                                     autocomplete="current-password")
            submitted = st.form_submit_button(L["login_submit"],
                                              type="primary",
                                              use_container_width=True,
                                              disabled=bool(locked_for))

        if locked_for:
            st.error(L["login_locked"].format(seconds=locked_for))
        elif submitted:
            stored = users.get(username.strip(), _DUMMY_HASH)
            if username.strip() in users and verify_password(password, stored):
                st.session_state.auth_user = username.strip()
                st.session_state.pop("auth_failures", None)
                st.rerun()
            else:
                _register_failure()
                st.error(L["login_failed"])

    return False
