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
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
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


def is_available() -> bool:
    """True when secrets expose a token, i.e. Drive saving can be attempted."""
    return bool(access_token())


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
