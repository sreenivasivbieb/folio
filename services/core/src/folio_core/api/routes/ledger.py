"""Undo/redo, audit history and the live event stream (SSE)."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..deps import C
from ..dto import GroupEntry, GroupRef, UndoBody

router = APIRouter(tags=["ledger"])


@router.post("/undo", response_model=GroupRef)
def undo(body: UndoBody, c: C) -> GroupRef:
    return GroupRef(group_id=c.ledger.undo(body.group_id))


@router.post("/redo", response_model=GroupRef)
def redo(c: C) -> GroupRef:
    return GroupRef(group_id=c.ledger.redo())


@router.get("/history", response_model=list[GroupEntry])
def history(c: C, limit: int = 100) -> list[GroupEntry]:
    return [GroupEntry(**g) for g in c.ledger.recent_groups(limit)]


@router.get("/events/stream")
async def stream(request: Request, c: C) -> StreamingResponse:
    """Server-sent events: ledger changes, job progress, source status, voice state.
    The UI invalidates its caches on each message, so every view updates together (FR-6)."""
    queue = c.bus.subscribe()

    async def gen():  # type: ignore[no-untyped-def]
        try:
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(msg, default=str)}\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            c.bus.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
