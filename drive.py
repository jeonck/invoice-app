"""Save finished invoices to the signed-in person's own Google Drive.

The app stores no credential of its own: it borrows the access token that
Streamlit exposes from the sign-in already performed, so files are created
by the person using the app, in their Drive, and can be revoked by them.

Requires two additions to the auth secrets — the Drive scope, and the token:

    [auth]
    expose_tokens = ["access"]

    [auth.google]
    client_kwargs = { scope = "openid email profile https://www.googleapis.com/auth/drive.file" }

``drive.file`` is the narrow scope: this app can only ever see the files it
created itself, never the rest of the Drive.
"""

import json
import uuid

import httpx
import streamlit as st

SCOPE = "https://www.googleapis.com/auth/drive.file"
PROVIDER = "google"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
ABOUT_URL = "https://www.googleapis.com/drive/v3/about"
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_FOLDER = "Invoices"
TIMEOUT = 30


class DriveError(Exception):
    """A failure to report to the person, carrying a label key as `code`."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def access_token() -> str:
    """The Google access token Streamlit exposes, or "" when it is absent."""
    try:
        return str(st.user.tokens.access or "")
    except Exception:
        return ""


def is_configured() -> bool:
    """True when the operator has set Drive saving up at all.

    Distinct from having a token: an anonymous visitor on a correctly
    configured app has no token yet, and the answer to that is "sign in",
    not "ask the operator to fix the settings".
    """
    try:
        auth_section = st.secrets["auth"]
    except Exception:
        return False
    exposed = auth_section.get("expose_tokens") or []
    if isinstance(exposed, str):
        exposed = [exposed]
    if "access" not in [str(item) for item in exposed]:
        return False
    try:
        scope = str(auth_section[PROVIDER].get("client_kwargs", {}).get("scope", ""))
    except Exception:
        return False
    return SCOPE in scope


def is_available() -> bool:
    """True when a token is in hand, i.e. saving can be attempted now."""
    return bool(access_token())


def token_is_live() -> bool:
    """One cheap call to learn whether the exposed token still works.

    Worth asking before someone spends twenty minutes on a form: the token
    lasts about an hour and Streamlit never refreshes it, so the alternative
    is finding out at save time, when re-authenticating costs the work.
    """
    token = access_token()
    if not token:
        return False
    try:
        _request("GET", ABOUT_URL, token, params={"fields": "user(emailAddress)"})
        return True
    except DriveError as exc:
        # Only an actual refusal means expired; a network blip must not raise
        # a false alarm that sends someone through a pointless sign-in.
        return exc.code != "expired"


def _q_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _request(method: str, url: str, token: str, **kwargs):
    headers = {"Authorization": f"Bearer {token}"}
    headers.update(kwargs.pop("headers", {}))
    try:
        response = httpx.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    except httpx.HTTPError as exc:
        raise DriveError("network", str(exc))

    if response.status_code in (401, 403):
        # The token is short-lived and Streamlit does not refresh it, so an
        # expired one is the common case here rather than a real denial.
        raise DriveError("expired", response.text[:200])
    if response.status_code >= 400:
        raise DriveError("http", f"{response.status_code} {response.text[:200]}")
    try:
        return response.json()
    except Exception as exc:
        raise DriveError("http", str(exc))


def _find(name: str, token: str, parent: str = "", folder: bool = False) -> str:
    clauses = [f"name = '{_q_escape(name)}'", "trashed = false"]
    clauses.append(("mimeType = '%s'" if folder else "mimeType != '%s'") % FOLDER_MIME)
    if parent:
        clauses.append(f"'{_q_escape(parent)}' in parents")
    payload = _request("GET", FILES_URL, token, params={
        "q": " and ".join(clauses),
        "fields": "files(id,name)",
        "pageSize": 1,
        "spaces": "drive",
    })
    files = payload.get("files") or []
    return files[0]["id"] if files else ""


def _ensure_folder(name: str, token: str, parent: str = "") -> str:
    existing = _find(name, token, parent=parent, folder=True)
    if existing:
        return existing
    metadata = {"name": name, "mimeType": FOLDER_MIME}
    if parent:
        metadata["parents"] = [parent]
    return _request("POST", FILES_URL, token,
                    json=metadata, params={"fields": "id"})["id"]


def _multipart(metadata: dict, data: bytes, mime: str):
    boundary = uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode(),
        json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
        f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    return body, {"Content-Type": f"multipart/related; boundary={boundary}"}


def _put_file(name: str, data: bytes, mime: str, token: str, parent: str) -> dict:
    """Create the file, or replace it when this app already made one by that
    name — saving the same invoice twice should not litter the folder."""
    existing = _find(name, token, parent=parent)
    if existing:
        body, headers = _multipart({"name": name}, data, mime)
        return _request("PATCH", f"{UPLOAD_URL}/{existing}", token, content=body,
                        headers=headers,
                        params={"uploadType": "multipart",
                                "fields": "id,name,webViewLink"})
    body, headers = _multipart({"name": name, "parents": [parent]}, data, mime)
    return _request("POST", UPLOAD_URL, token, content=body, headers=headers,
                    params={"uploadType": "multipart",
                            "fields": "id,name,webViewLink"})


def list_invoices(limit: int = 25) -> list:
    """Saved invoices, newest first, as [{id, name, modified}].

    The drive.file scope only ever sees files this app created, so a search
    for its own JSON needs no folder walking — and cannot turn up anything
    else in the person's Drive.
    """
    token = access_token()
    if not token:
        raise DriveError("unavailable")
    payload = _request("GET", FILES_URL, token, params={
        "q": "mimeType = 'application/json' and trashed = false",
        "fields": "files(id,name,modifiedTime)",
        "orderBy": "modifiedTime desc",
        "pageSize": max(1, min(int(limit), 100)),
        "spaces": "drive",
    })
    return [
        {"id": f.get("id", ""),
         "name": str(f.get("name", "")).removesuffix(".json"),
         "modified": str(f.get("modifiedTime", ""))[:10]}
        for f in (payload.get("files") or []) if f.get("id")
    ]


def load_invoice(file_id: str) -> dict:
    """Read one saved invoice back as the dict the form was filled with."""
    token = access_token()
    if not token:
        raise DriveError("unavailable")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = httpx.get(f"{FILES_URL}/{file_id}", headers=headers,
                             params={"alt": "media"}, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise DriveError("network", str(exc))
    if response.status_code in (401, 403):
        raise DriveError("expired", response.text[:200])
    if response.status_code >= 400:
        raise DriveError("http", f"{response.status_code} {response.text[:200]}")
    try:
        data = json.loads(response.content.decode("utf-8"))
    except Exception as exc:
        raise DriveError("unreadable", str(exc))
    if not isinstance(data, dict):
        raise DriveError("unreadable", "not an invoice")
    return data


def save_invoice(pdf_bytes: bytes, invoice_data: dict, stem: str, year) -> dict:
    """Save `<stem>.pdf` and `<stem>.json` under Invoices/<year>/ in Drive.

    The JSON is what the form was filled with, so an invoice can be loaded
    back and reissued later; the PDF is the document that was sent.
    """
    token = access_token()
    if not token:
        raise DriveError("unavailable")

    folder = _ensure_folder(str(year), token,
                            parent=_ensure_folder(ROOT_FOLDER, token))
    pdf = _put_file(f"{stem}.pdf", pdf_bytes, "application/pdf", token, folder)
    payload = json.dumps(invoice_data, ensure_ascii=False, indent=2).encode("utf-8")
    data = _put_file(f"{stem}.json", payload, "application/json", token, folder)
    return {"pdf": pdf, "json": data, "folder": folder}
