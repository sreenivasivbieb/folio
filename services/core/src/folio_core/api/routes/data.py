"""Schema editing, jobs dashboard, export and import."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ...domain.errors import InvalidInput
from ...domain.schema import parse_schema_yaml
from ...jobs import Job
from ..deps import C
from ..dto import Ok, SchemaBody, SchemaView

router = APIRouter(tags=["data"])


@router.get("/schema", response_model=SchemaView)
def get_schema(c: C) -> SchemaView:
    version, schema = c.knowledge.schema()
    return SchemaView(version=version, schema=schema.model_dump(mode="json"), yaml=schema.to_yaml())


@router.put("/schema", response_model=SchemaView)
def put_schema(body: SchemaBody, c: C) -> SchemaView:
    """User-editable schema (FR-4). Every save is a new version; claims record their version."""
    try:
        schema = parse_schema_yaml(body.yaml)
    except Exception as exc:
        raise InvalidInput(f"invalid schema: {exc}") from exc
    c.knowledge.update_schema(schema)
    return get_schema(c)


@router.get("/jobs", response_model=list[Job])
def list_jobs(c: C, status: str | None = None, limit: int = 100) -> list[Job]:
    return c.queue.list(status, limit)


@router.post("/jobs/{job_id}/retry", response_model=Ok)
def retry_job(job_id: str, c: C) -> Ok:
    c.queue.retry(job_id)
    c.workers.notify()
    return Ok()


@router.get("/export/{fmt}")
def export(fmt: Literal["json", "graphml", "markdown", "csv"], c: C) -> Response:
    e = c.exporter
    if fmt == "json":
        return JSONResponse(e.to_json(), headers={"Content-Disposition": 'attachment; filename="folio-export.json"'})
    if fmt == "graphml":
        return Response(e.to_graphml(), media_type="application/graphml+xml",
                        headers={"Content-Disposition": 'attachment; filename="folio-graph.graphml"'})
    if fmt == "markdown":
        return Response(e.to_markdown(), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="folio-export.md"'})
    return Response(e.to_csv_zip(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="folio-export-csv.zip"'})


@router.post("/import/{fmt}", response_model=dict[str, int])
async def import_(fmt: Literal["json", "graphml"], request: Request, c: C) -> dict[str, int]:
    """Restore an export into an empty project (FR-9 round trip)."""
    body = await request.body()
    def restore() -> dict[str, int]:
        if fmt == "json":
            import json

            try:
                data = json.loads(body)
            except ValueError as exc:
                raise InvalidInput("not valid JSON") from exc
            counts = c.exporter.from_json(data)
        else:
            counts = c.exporter.from_graphml(body)
        c.ingestion.rescan_all()
        c.workers.notify()
        return counts

    return await run_in_threadpool(restore)
