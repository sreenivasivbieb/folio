"""User-controlled Google Drive backup. No Folio credentials or hosted relay."""

from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...domain.errors import InvalidInput, Unavailable
from ..deps import C
from ..dto import (
    DriveAuthorization,
    DriveBackup,
    DriveBackups,
    DriveConnect,
    DriveRestore,
    DriveStatus,
    Ok,
)

router = APIRouter(tags=["drive"])


@router.get("/drive", response_model=DriveStatus)
def status(c: C) -> dict:
    return c.drive.status()


@router.post("/drive/connect", response_model=DriveAuthorization)
def connect(body: DriveConnect, request: Request, c: C) -> DriveAuthorization:
    redirect = str(request.base_url).rstrip("/") + "/api/drive/callback"
    return DriveAuthorization(authorization_url=c.drive.begin(body.client_id.strip(), body.client_secret, redirect))


@router.get("/drive/callback", response_class=HTMLResponse)
def callback(c: C, state: str = "", code: str = "", error: str = "") -> HTMLResponse:
    try:
        c.drive.finish(state, "" if error else code)
        message = "Google Drive is connected. Return to Folio; you can close this tab."
        status_code = 200
    except (InvalidInput, Unavailable) as exc:
        message, status_code = str(exc), 400
    return HTMLResponse("<!doctype html><title>Folio — Google Drive</title><h1>Folio</h1><p>"
                        + escape(message) + "</p>", status_code=status_code,
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.delete("/drive", response_model=Ok)
def disconnect(c: C) -> Ok:
    c.drive.disconnect()
    return Ok(detail="Local Drive credentials removed. Google account permissions can also be revoked in your Google account.")


@router.get("/drive/backups", response_model=DriveBackups)
def backups(c: C, page_token: str | None = None) -> dict:
    return c.drive.backups(page_token)


@router.post("/drive/backups", response_model=DriveBackup)
def backup(c: C) -> dict:
    return c.drive.backup(c.exporter.to_json())


@router.post("/drive/restore", response_model=dict[str, int])
def restore(body: DriveRestore, c: C) -> dict[str, int]:
    c.exporter._ensure_empty()
    counts = c.exporter.from_json(c.drive.download(body.file_id))
    c.ingestion.rescan_all()
    c.workers.notify()
    return counts
