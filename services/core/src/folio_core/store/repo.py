"""Read queries and row <-> domain conversions, one section per table.

Writes to *tracked* tables (entities, claims, ...) go through ``ledger.Tx`` so they are recorded
as events. Writes to *operational* tables (sources' index status, chunks, jobs, cache) happen
here directly because they are derived data and would only add noise to the audit trail.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from ..domain.models import (
    Chunk,
    Claim,
    Entity,
    Evidence,
    Extractor,
    Label,
    Locator,
    Root,
    Source,
)
from ..domain.schema import SchemaDef
from .db import dumps, loads, utcnow


def _marks(items: Iterable[Any]) -> str:
    return ",".join("?" * len(list(items)))


# --- settings -------------------------------------------------------------------------------


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE id = ?", (key,)).fetchone()
    return loads(row[0]) if row else default


# --- schema ---------------------------------------------------------------------------------


def active_schema(conn: sqlite3.Connection) -> tuple[int, SchemaDef]:
    row = conn.execute(
        "SELECT version, definition FROM schema_versions ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise LookupError("no schema installed")
    return row[0], SchemaDef.model_validate(loads(row[1]))


# --- roots & sources ------------------------------------------------------------------------


def root_from_row(r: sqlite3.Row) -> Root:
    return Root(id=r["id"], path=r["path"], kind=r["kind"], watch=bool(r["watch"]),
                created_at=r["created_at"])


def list_roots(conn: sqlite3.Connection) -> list[Root]:
    return [root_from_row(r) for r in conn.execute("SELECT * FROM roots ORDER BY path")]


def source_from_row(r: sqlite3.Row) -> Source:
    return Source(**{k: r[k] for k in Source.model_fields if k in r.keys()})  # noqa: SIM118 (sqlite3.Row: `in` checks values)


def get_source(conn: sqlite3.Connection, source_id: str) -> Source | None:
    r = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return source_from_row(r) if r else None


def source_by_path(conn: sqlite3.Connection, path: str) -> Source | None:
    r = conn.execute("SELECT * FROM sources WHERE path = ?", (path,)).fetchone()
    return source_from_row(r) if r else None


def list_sources(conn: sqlite3.Connection, root_id: str | None = None) -> list[Source]:
    if root_id:
        rows = conn.execute("SELECT * FROM sources WHERE root_id = ? ORDER BY path", (root_id,))
    else:
        rows = conn.execute("SELECT * FROM sources WHERE status != 'forgotten' ORDER BY path")
    return [source_from_row(r) for r in rows]


def set_source_status(
    conn: sqlite3.Connection, source_id: str, status: str, error: str | None = None, **extra: Any
) -> None:
    cols = {"status": status, "error": error, "updated_at": utcnow(), **extra}
    conn.execute(
        f"UPDATE sources SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?",
        [*cols.values(), source_id],
    )


# --- chunks ---------------------------------------------------------------------------------


def chunk_from_row(r: sqlite3.Row) -> Chunk:
    return Chunk(id=r["id"], source_id=r["source_id"], ord=r["ord"], text=r["text"],
                 locator=Locator.model_validate(loads(r["locator"])), content_hash=r["content_hash"])


def chunks_for_source(conn: sqlite3.Connection, source_id: str) -> list[Chunk]:
    rows = conn.execute("SELECT * FROM ix.chunks WHERE source_id = ? ORDER BY ord", (source_id,))
    return [chunk_from_row(r) for r in rows]


def get_chunk(conn: sqlite3.Connection, chunk_id: str) -> Chunk | None:
    r = conn.execute("SELECT * FROM ix.chunks WHERE id = ?", (chunk_id,)).fetchone()
    return chunk_from_row(r) if r else None


# --- entities -------------------------------------------------------------------------------


def entity_from_row(r: sqlite3.Row, aliases: list[str] | None = None) -> Entity:
    return Entity(id=r["id"], type=r["type"], name=r["name"], status=r["status"],
                  created_by=r["created_by"], merged_into=r["merged_into"],
                  created_at=r["created_at"], updated_at=r["updated_at"], aliases=aliases or [])


def aliases_for(conn: sqlite3.Connection, entity_ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    if not entity_ids:
        return out
    for r in conn.execute(
        f"SELECT entity_id, alias FROM aliases WHERE entity_id IN ({_marks(entity_ids)}) ORDER BY created_at",
        entity_ids,
    ):
        out[r[0]].append(r[1])
    return out


def get_entities(conn: sqlite3.Connection, ids: list[str]) -> dict[str, Entity]:
    if not ids:
        return {}
    ids = list(dict.fromkeys(ids))
    rows = conn.execute(f"SELECT * FROM entities WHERE id IN ({_marks(ids)})", ids).fetchall()
    al = aliases_for(conn, [r["id"] for r in rows])
    return {r["id"]: entity_from_row(r, al.get(r["id"], [])) for r in rows}


def get_entity(conn: sqlite3.Connection, entity_id: str) -> Entity | None:
    return get_entities(conn, [entity_id]).get(entity_id)


def resolve_merged(conn: sqlite3.Connection, entity_id: str) -> str:
    """Follow merged_into pointers to the surviving entity."""
    seen = set()
    while entity_id not in seen:
        seen.add(entity_id)
        r = conn.execute("SELECT merged_into FROM entities WHERE id = ?", (entity_id,)).fetchone()
        if r is None or r[0] is None:
            return entity_id
        entity_id = r[0]
    return entity_id


def search_entities(
    conn: sqlite3.Connection, q: str = "", types: list[str] | None = None,
    include_rejected: bool = False, limit: int = 50,
) -> list[Entity]:
    from ..domain.rules import normalize_name

    where = ["e.status != 'merged'"]
    args: list[Any] = []
    if not include_rejected:
        where.append("e.status != 'rejected'")
    if types:
        where.append(f"e.type IN ({_marks(types)})")
        args += types
    if q:
        where.append("e.id IN (SELECT entity_id FROM aliases WHERE normalized LIKE ?)")
        args.append(f"%{normalize_name(q)}%")
    rows = conn.execute(
        f"SELECT e.*, (SELECT COUNT(*) FROM claims c WHERE c.subject_id = e.id OR c.object_id = e.id) AS n "
        f"FROM entities e WHERE {' AND '.join(where)} ORDER BY n DESC, e.name LIMIT ?",
        [*args, limit],
    ).fetchall()
    al = aliases_for(conn, [r["id"] for r in rows])
    return [entity_from_row(r, al.get(r["id"], [])) for r in rows]


def entities_by_alias(conn: sqlite3.Connection, normalized: str) -> list[Entity]:
    rows = conn.execute(
        "SELECT e.* FROM entities e JOIN aliases a ON a.entity_id = e.id "
        "WHERE a.normalized = ? AND e.status NOT IN ('merged', 'rejected')",
        (normalized,),
    ).fetchall()
    return [entity_from_row(r) for r in {r["id"]: r for r in rows}.values()]


def alias_row(conn: sqlite3.Connection, entity_id: str, normalized: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM aliases WHERE entity_id = ? AND normalized = ?", (entity_id, normalized)
    ).fetchone()


# --- claims & evidence ----------------------------------------------------------------------


def evidence_from_row(r: sqlite3.Row) -> Evidence:
    return Evidence(id=r["id"], claim_id=r["claim_id"], source_id=r["source_id"],
                    chunk_id=r["chunk_id"], locator=Locator.model_validate(loads(r["locator"])),
                    quote=r["quote"], label_id=r["label_id"])


def evidence_for(conn: sqlite3.Connection, claim_ids: list[str]) -> dict[str, list[Evidence]]:
    out: dict[str, list[Evidence]] = defaultdict(list)
    for i in range(0, len(claim_ids), 500):
        batch = claim_ids[i : i + 500]
        for r in conn.execute(
            f"SELECT * FROM evidence WHERE claim_id IN ({_marks(batch)}) ORDER BY created_at", batch
        ):
            out[r["claim_id"]].append(evidence_from_row(r))
    return out


def claim_from_row(r: sqlite3.Row, evidence: list[Evidence] | None = None) -> Claim:
    return Claim(
        id=r["id"], subject_id=r["subject_id"], predicate=r["predicate"], kind=r["kind"],
        value=loads(r["value"]), object_id=r["object_id"], valid_from=r["valid_from"],
        valid_to=r["valid_to"], confidence=r["confidence"], status=r["status"],
        extractor=Extractor.model_validate(loads(r["extractor"])), fingerprint=r["fingerprint"],
        label_id=r["label_id"], needs_review=bool(r["needs_review"]),
        created_at=r["created_at"], updated_at=r["updated_at"], evidence=evidence or [],
    )


def hydrate_claims(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[Claim]:
    ev = evidence_for(conn, [r["id"] for r in rows])
    return [claim_from_row(r, ev.get(r["id"], [])) for r in rows]


def get_claim(conn: sqlite3.Connection, claim_id: str) -> Claim | None:
    r = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    return hydrate_claims(conn, [r])[0] if r else None


def claims_by_fingerprint(conn: sqlite3.Connection, fingerprint: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM claims WHERE fingerprint = ?", (fingerprint,)).fetchall()


def claims_for_entity(
    conn: sqlite3.Connection, entity_id: str, include_rejected: bool = True
) -> list[Claim]:
    status = "" if include_rejected else "AND status != 'rejected'"
    rows = conn.execute(
        f"SELECT * FROM claims WHERE (subject_id = ? OR object_id = ?) {status} "
        "ORDER BY COALESCE(valid_from, created_at)",
        (entity_id, entity_id),
    ).fetchall()
    return hydrate_claims(conn, rows)


def query_claims(
    conn: sqlite3.Connection, *, entity_id: str | None = None, status: list[str] | None = None,
    predicate: str | None = None, entity_type: str | None = None, kind: str | None = None,
    min_confidence: float | None = None, max_confidence: float | None = None,
    source_id: str | None = None, dated_only: bool = False, needs_review: bool | None = None,
    order: str = "confidence", limit: int = 500, offset: int = 0,
) -> list[Claim]:
    where, args = ["1=1"], []
    if entity_id:
        where.append("(c.subject_id = ? OR c.object_id = ?)")
        args += [entity_id, entity_id]
    if status:
        where.append(f"c.status IN ({_marks(status)})")
        args += status
    if predicate:
        where.append("c.predicate = ?")
        args.append(predicate)
    if kind:
        where.append("c.kind = ?")
        args.append(kind)
    if entity_type:
        where.append("c.subject_id IN (SELECT id FROM entities WHERE type = ?)")
        args.append(entity_type)
    if min_confidence is not None:
        where.append("c.confidence >= ?")
        args.append(min_confidence)
    if max_confidence is not None:
        where.append("c.confidence <= ?")
        args.append(max_confidence)
    if source_id:
        where.append("c.id IN (SELECT claim_id FROM evidence WHERE source_id = ?)")
        args.append(source_id)
    if dated_only:
        where.append("c.valid_from IS NOT NULL")
    if needs_review is not None:
        where.append("c.needs_review = ?")
        args.append(int(needs_review))
    order_sql = {
        "confidence": "c.confidence ASC, c.created_at",
        "date": "c.valid_from, c.created_at",
        "recent": "c.updated_at DESC",
    }.get(order, "c.created_at")
    rows = conn.execute(
        f"SELECT c.* FROM claims c WHERE {' AND '.join(where)} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return hydrate_claims(conn, rows)


# --- labels ---------------------------------------------------------------------------------


def label_from_row(r: sqlite3.Row) -> Label:
    return Label(id=r["id"], transcript=r["transcript"], audio_path=r["audio_path"],
                 target_kind=r["target_kind"], target_ids=loads(r["target_ids"]),
                 parsed=loads(r["parsed"]), status=r["status"], created_at=r["created_at"])


def get_label(conn: sqlite3.Connection, label_id: str) -> Label | None:
    r = conn.execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone()
    return label_from_row(r) if r else None


def list_labels(conn: sqlite3.Connection, limit: int = 50) -> list[Label]:
    rows = conn.execute("SELECT * FROM labels ORDER BY created_at DESC LIMIT ?", (limit,))
    return [label_from_row(r) for r in rows]


# --- model cache ----------------------------------------------------------------------------


def cache_get(conn: sqlite3.Connection, key: str) -> Any:
    r = conn.execute("SELECT value FROM ix.model_cache WHERE key = ?", (key,)).fetchone()
    return loads(r[0]) if r else None


def cache_put(conn: sqlite3.Connection, key: str, task: str, model: str, value: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ix.model_cache(key, task, model, value, created_at) VALUES (?,?,?,?,?)",
        (key, task, model, dumps(value), utcnow()),
    )
