"""Optional Google Drive backups using only the user's own Desktop OAuth credentials."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from datetime import UTC, datetime
from urllib.parse import urlencode, urlparse

import httpx

from ..domain.errors import InvalidInput, Unavailable
from .secrets import SecretStore

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
FILES = "https://www.googleapis.com/drive/v3/files"
SCOPE = "https://www.googleapis.com/auth/drive.file"


class DriveService:
    def __init__(self, store: SecretStore, transport: httpx.BaseTransport | None = None) -> None:
        self.store = store
        self.client = httpx.Client(timeout=45, transport=transport, follow_redirects=False)
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._access: tuple[str, float] | None = None

    def status(self) -> dict:
        return {"connected": bool(self.store.get("drive.refresh_token")),
                "client_id": self.store.get("drive.client_id") or "",
                "secret_configured": bool(self.store.get("drive.client_secret"))}

    def begin(self, client_id: str, client_secret: str | None, redirect_uri: str) -> str:
        parsed = urlparse(redirect_uri)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise InvalidInput("Google Drive sign-in must return to this device's loopback address")
        if not client_id.endswith(".apps.googleusercontent.com"):
            raise InvalidInput("Import your own Google Desktop OAuth credentials JSON or enter its client ID")
        previous_id = self.store.get("drive.client_id")
        secret = client_secret or (self.store.get("drive.client_secret") if previous_id == client_id else None)
        if not secret:
            raise InvalidInput("The Desktop OAuth client secret is required")
        changes = {"drive.client_id": client_id, "drive.client_secret": secret}
        if client_id != previous_id:
            changes["drive.refresh_token"] = None
            self._access = None
        self.store.update(changes)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if v["expires"] > time.monotonic()}
            self._pending[state] = {"verifier": verifier, "redirect": redirect_uri, "expires": time.monotonic() + 600,
                                    "client_id": client_id, "client_secret": secret}
        return AUTH + "?" + urlencode({"client_id": client_id, "redirect_uri": redirect_uri,
            "response_type": "code", "scope": SCOPE, "access_type": "offline", "prompt": "consent",
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})

    def finish(self, state: str, code: str) -> None:
        with self._lock:
            pending = self._pending.pop(state, None)
        if not pending or pending["expires"] < time.monotonic() or not code:
            raise InvalidInput("Google sign-in expired or was cancelled. Start again in Folio.")
        response = self._request("POST", TOKEN, data={"client_id": pending["client_id"],
            "client_secret": pending["client_secret"], "code": code, "code_verifier": pending["verifier"],
            "redirect_uri": pending["redirect"], "grant_type": "authorization_code"})
        tokens = response.json()
        if (self.store.get("drive.client_id") != pending["client_id"]
                or self.store.get("drive.client_secret") != pending["client_secret"]):
            raise InvalidInput("This Google sign-in was cancelled or replaced. Start again in Folio.")
        if not tokens.get("refresh_token"):
            raise InvalidInput("Google did not grant offline access. Reconnect and approve consent.")
        self.store.set("drive.refresh_token", tokens["refresh_token"])
        self._access = (tokens["access_token"], time.monotonic() + max(0, int(tokens.get("expires_in", 3600)) - 60))

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise Unavailable("Could not reach Google Drive. Your local files and knowledge are unchanged.") from exc
        if response.status_code in (401, 403):
            self._access = None
            raise InvalidInput("Google Drive access was rejected. Reconnect using your own credentials.")
        if not response.is_success:
            raise Unavailable(f"Google Drive returned HTTP {response.status_code}; local data is unchanged")
        return response

    def _headers(self) -> dict[str, str]:
        refresh = self.store.get("drive.refresh_token")
        if not refresh:
            raise InvalidInput("Connect your own Google Drive account first")
        if self._access and self._access[1] > time.monotonic():
            return {"Authorization": "Bearer " + self._access[0]}
        tokens = self._request("POST", TOKEN, data={"client_id": self.store.get("drive.client_id"),
            "client_secret": self.store.get("drive.client_secret"), "refresh_token": refresh,
            "grant_type": "refresh_token"}).json()
        if self.store.get("drive.refresh_token") != refresh:
            raise InvalidInput("Google Drive was disconnected while connecting")
        self._access = (tokens["access_token"], time.monotonic() + max(0, int(tokens.get("expires_in", 3600)) - 60))
        return {"Authorization": "Bearer " + self._access[0]}

    def backups(self, page_token: str | None = None) -> dict:
        params = {"q": "trashed = false and appProperties has { key='application' and value='folio' }",
                  "fields": "files(id,name,size,modifiedTime),nextPageToken", "orderBy": "modifiedTime desc", "pageSize": 100}
        if page_token:
            params["pageToken"] = page_token
        return self._request("GET", FILES, headers=self._headers(), params=params).json()

    def backup(self, data: dict) -> dict:
        name = "folio-backup-" + datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S") + ".json"
        metadata = json.dumps({"name": name, "mimeType": "application/json", "appProperties": {"application": "folio"}})
        boundary = "folio_" + secrets.token_hex(16)
        content = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n"
                   f"--{boundary}\r\nContent-Type: application/json\r\n\r\n" + json.dumps(data, ensure_ascii=False)
                   + f"\r\n--{boundary}--\r\n").encode()
        return self._request("POST", "https://www.googleapis.com/upload/drive/v3/files",
            headers={**self._headers(), "Content-Type": f"multipart/related; boundary={boundary}"},
            params={"uploadType": "multipart", "fields": "id,name,size,modifiedTime"}, content=content).json()

    def download(self, file_id: str) -> dict:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
            raise InvalidInput("invalid Drive backup ID")
        headers = self._headers()
        metadata = self._request("GET", FILES + "/" + file_id, headers=headers,
                                params={"fields": "id,mimeType,appProperties,size"}).json()
        if metadata.get("appProperties", {}).get("application") != "folio" or metadata.get("mimeType") != "application/json":
            raise InvalidInput("Select a Folio JSON backup created by this OAuth app")
        if int(metadata.get("size", 0)) > 256 * 1024 * 1024:
            raise InvalidInput("This backup is too large for in-app restore; download and import it locally")
        response = self._request("GET", FILES + "/" + file_id, headers=headers, params={"alt": "media"})
        if len(response.content) > 256 * 1024 * 1024:
            raise InvalidInput("Backup exceeds the in-app restore size limit")
        try:
            data = response.json()
        except ValueError as exc:
            raise InvalidInput("The Drive backup is not valid JSON") from exc
        if not isinstance(data, dict) or data.get("format") != "folio.v2":
            raise InvalidInput("The Drive file is not a Folio backup")
        return data

    def disconnect(self) -> None:
        self._access = None
        with self._lock:
            self._pending.clear()
        self.store.update({key: None for key in ("drive.client_id", "drive.client_secret", "drive.refresh_token")})

    def close(self) -> None:
        self.client.close()
