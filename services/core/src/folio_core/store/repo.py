"""Read queries and document <-> domain conversions, one section per collection/table.

Writes to *tracked* collections (entities, claims, labels, ...) go through ``ledger.Tx`` so they
are recorded as events. Writes to *operational* data (a source's index status, chunks, jobs,
cache) happen directly because they are derived and would only add noise to the audit trail.

Functions that may run inside a ledger transaction accept ``session`` so they see its writes.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from typing import Any

from ..domain.models import Chunk, Claim, Entity, Evidence, Extractor, Label, Locator, Root, Source
from ..domain.schema import SchemaDef
from .index_db import dumps, loads, utcnow
from .local import KnowledgeDB
from .local import Session as ClientSession

HIDDEN_SOURCE_STATUSES = ["forgotten", "removed", "trashed"]


# --- settings & schema hints ----------------------------------------------------------------


def get_setting(kdb: KnowledgeDB, key: str, default: Any = None) -> Any:
    doc = kdb["settings"].find_one({"_id": key})
    return doc["value"] if doc else default


def active_schema(kdb: KnowledgeDB) -> tuple[int, SchemaDef]:
    doc = kdb["schema_versions"].find_one(sort=[("version", -1)])
    if doc is None:
        raise LookupError("no schema installed")
    return doc["version"], SchemaDef.model_validate(doc["definition"])


def types_in_use(kdb: KnowledgeDB) -> list[str]:
    """Entity types that actually occur (open schema: anything the user/model named)."""
    return sorted(t for t in kdb["entities"].distinct("type", {"status": {"$nin": ["merged", "rejected"]}}) if t)


# --- roots & sources ------------------------------------------------------------------------


def root_from_doc(d: dict[str, Any]) -> Root:
    return Root(id=d["_id"], path=d["path"], kind=d["kind"], watch=bool(d["watch"]), created_at=d["created_at"],
                include_hidden=d.get("include_hidden", False), exclude=d.get("exclude", []))


def list_roots(kdb: KnowledgeDB) -> list[Root]:
    return [root_from_doc(d) for d in kdb["roots"].find().sort("path", 1)]


def source_from_doc(d: dict[str, Any]) -> Source:
    return Source(id=d["_id"], **{k: d.get(k) for k in Source.model_fields if k != "id"})


def get_source(kdb: KnowledgeDB, source_id: str) -> Source | None:
    d = kdb["sources"].find_one({"_id": source_id})
    return source_from_doc(d) if d else None


def get_sources(kdb: KnowledgeDB, ids: list[str]) -> dict[str, Source]:
    return {d["_id"]: source_from_doc(d) for d in kdb["sources"].find({"_id": {"$in": list(set(ids))}})}


def source_by_path(kdb: KnowledgeDB, path: str) -> Source | None:
    d = kdb["sources"].find_one({"path": path})
    return source_from_doc(d) if d else None


def list_sources(kdb: KnowledgeDB, root_id: str | None = None) -> list[Source]:
    query: dict[str, Any] = {"status": {"$nin": HIDDEN_SOURCE_STATUSES}}
    if root_id:
        query["root_id"] = root_id
    return [source_from_doc(d) for d in kdb["sources"].find(query).sort("path", 1)]


def set_source_status(kdb: KnowledgeDB, source_id: str, status: str, error: str | None = None,
                      **extra: Any) -> None:
    kdb["sources"].update_one({"_id": source_id},
                              {"$set": {"status": status, "error": error, "updated_at": utcnow(), **extra}})


# --- chunks (index.db) ----------------------------------------------------------------------


def chunk_from_row(r: sqlite3.Row) -> Chunk:
    return Chunk(id=r["id"], source_id=r["source_id"], ord=r["ord"], text=r["text"],
                 locator=Locator.model_validate(loads(r["locator"])), content_hash=r["content_hash"])


def chunks_for_source(conn: sqlite3.Connection, source_id: str) -> list[Chunk]:
    rows = conn.execute("SELECT * FROM chunks WHERE source_id = ? ORDER BY ord", (source_id,))
    return [chunk_from_row(r) for r in rows]


def get_chunk(conn: sqlite3.Connection, chunk_id: str) -> Chunk | None:
    r = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    return chunk_from_row(r) if r else None


def cache_get(conn: sqlite3.Connection, key: str) -> Any:
    r = conn.execute("SELECT value FROM model_cache WHERE key = ?", (key,)).fetchone()
    return loads(r[0]) if r else None


def cache_put(conn: sqlite3.Connection, key: str, task: str, model: str, value: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO model_cache(key, task, model, value, created_at) VALUES (?,?,?,?,?)",
        (key, task, model, dumps(value), utcnow()),
    )


# --- entities -------------------------------------------------------------------------------


def entity_from_doc(d: dict[str, Any]) -> Entity:
    return Entity(id=d["_id"], type=d["type"], name=d["name"], status=d["status"],
                  created_by=d["created_by"], merged_into=d.get("merged_into"),
                  created_at=d["created_at"], updated_at=d["updated_at"],
                  aliases=[a["alias"] for a in d.get("aliases", [])])


def get_entities(kdb: KnowledgeDB, ids: list[str], session: ClientSession | None = None) -> dict[str, Entity]:
    if not ids:
        return {}
    docs = kdb["entities"].find({"_id": {"$in": list(set(ids))}}, session=session)
    return {d["_id"]: entity_from_doc(d) for d in docs}


def get_entity(kdb: KnowledgeDB, entity_id: str, session: ClientSession | None = None) -> Entity | None:
    return get_entities(kdb, [entity_id], session).get(entity_id)


def resolve_merged(kdb: KnowledgeDB, entity_id: str, session: ClientSession | None = None) -> str:
    """Follow merged_into pointers to the surviving entity."""
    seen: set[str] = set()
    while entity_id not in seen:
        seen.add(entity_id)
        d = kdb["entities"].find_one({"_id": entity_id}, {"merged_into": 1}, session=session)
        if d is None or not d.get("merged_into"):
            return entity_id
        entity_id = d["merged_into"]
    return entity_id


def claim_counts(kdb: KnowledgeDB, ids: list[str]) -> dict[str, int]:
    """How many non-rejected claims mention each entity (as subject or object)."""
    counts: dict[str, int] = defaultdict(int)
    if not ids:
        return counts
    for field in ("subject_id", "object_id"):
        for r in kdb["claims"].aggregate([
            {"$match": {field: {"$in": ids}, "status": {"$ne": "rejected"}}},
            {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
        ]):
            counts[r["_id"]] += r["n"]
    return counts


def search_entities(kdb: KnowledgeDB, q: str = "", types: list[str] | None = None,
                    include_rejected: bool = False, limit: int = 50) -> list[Entity]:
    from ..domain.rules import normalize_name

    query: dict[str, Any] = {"status": {"$nin": ["merged"] + ([] if include_rejected else ["rejected"])}}
    if types:
        query["type"] = {"$in": types}
    if q:
        query["aliases.normalized"] = {"$regex": re.escape(normalize_name(q))}
    docs = list(kdb["entities"].find(query).limit(max(limit * 4, 200)))
    counts = claim_counts(kdb, [d["_id"] for d in docs])
    norm = normalize_name(q) if q else ""

    def rank(d: dict[str, Any]) -> tuple[int, int, str]:
        exact = any(a["normalized"] == norm for a in d.get("aliases", [])) if norm else False
        return (0 if exact else 1, -counts.get(d["_id"], 0), d["name"].lower())

    found = [entity_from_doc(d) for d in sorted(docs, key=rank)[:limit]]
    if q and len(found) < 3 and len(norm) >= 3:  # typos: "lexi hackthon" -> Lexsi Hackathon
        import difflib

        seen = {e.id for e in found}
        pool = list(kdb["entities"].find({k: v for k, v in query.items() if k != "aliases.normalized"}).limit(5000))
        names: dict[str, dict[str, Any]] = {}
        for d in pool:
            for a in d.get("aliases", []):
                names.setdefault(a["normalized"], d)
        for match in difflib.get_close_matches(norm, list(names), n=limit, cutoff=0.72):
            d = names[match]
            if d["_id"] not in seen:
                seen.add(d["_id"])
                found.append(entity_from_doc(d))
    return found[:limit]


# --- claims & evidence ----------------------------------------------------------------------


def claim_from_doc(d: dict[str, Any]) -> Claim:
    evidence = [
        Evidence(id=e["id"], claim_id=d["_id"], source_id=e.get("source_id"), chunk_id=e.get("chunk_id"),
                 locator=Locator.model_validate(e["locator"]), quote=e["quote"], label_id=e.get("label_id"))
        for e in d.get("evidence", [])
    ]
    return Claim(
        id=d["_id"], subject_id=d["subject_id"], predicate=d["predicate"], kind=d["kind"],
        value=d.get("value"), object_id=d.get("object_id"), valid_from=d.get("valid_from"),
        valid_to=d.get("valid_to"), confidence=d["confidence"], status=d["status"],
        extractor=Extractor.model_validate(d["extractor"]), fingerprint=d["fingerprint"],
        label_id=d.get("label_id"), needs_review=bool(d.get("needs_review")),
        created_at=d["created_at"], updated_at=d["updated_at"], evidence=evidence,
    )


def get_claim(kdb: KnowledgeDB, claim_id: str) -> Claim | None:
    d = kdb["claims"].find_one({"_id": claim_id})
    return claim_from_doc(d) if d else None


def claims_for_entity(kdb: KnowledgeDB, entity_id: str, include_rejected: bool = True) -> list[Claim]:
    query: dict[str, Any] = {"$or": [{"subject_id": entity_id}, {"object_id": entity_id}]}
    if not include_rejected:
        query["status"] = {"$ne": "rejected"}
    docs = sorted(kdb["claims"].find(query), key=lambda d: d.get("valid_from") or d["created_at"])
    return [claim_from_doc(d) for d in docs]


def query_claims(
    kdb: KnowledgeDB, *, entity_id: str | None = None, status: list[str] | None = None,
    predicate: str | None = None, exclude_predicates: list[str] | None = None,
    entity_type: str | None = None, kind: str | None = None,
    min_confidence: float | None = None, max_confidence: float | None = None,
    source_id: str | None = None, dated_only: bool = False, needs_review: bool | None = None,
    order: str = "confidence", limit: int = 500, offset: int = 0,
) -> list[Claim]:
    q: dict[str, Any] = {}
    if entity_id:
        q["$or"] = [{"subject_id": entity_id}, {"object_id": entity_id}]
    if status:
        q["status"] = {"$in": status}
    if predicate:
        q["predicate"] = predicate
    elif exclude_predicates:
        q["predicate"] = {"$nin": exclude_predicates}
    if kind:
        q["kind"] = kind
    if entity_type:
        ids = [d["_id"] for d in kdb["entities"].find({"type": entity_type}, {"_id": 1})]
        q["subject_id"] = {"$in": ids}
    conf: dict[str, float] = {}
    if min_confidence is not None:
        conf["$gte"] = min_confidence
    if max_confidence is not None:
        conf["$lte"] = max_confidence
    if conf:
        q["confidence"] = conf
    if source_id:
        q["evidence.source_id"] = source_id
    if dated_only:
        q["valid_from"] = {"$ne": None}
    if needs_review is not None:
        q["needs_review"] = needs_review
    sort = {
        "confidence": [("confidence", 1), ("created_at", 1)],
        "date": [("valid_from", 1), ("created_at", 1)],
        "recent": [("updated_at", -1)],
        "subject": [("subject_id", 1)],
        "predicate": [("predicate", 1)],
        "status": [("status", 1)],
        "value": [("value", 1)],
    }.get(order.lstrip("-"), [("created_at", 1)])
    if order.startswith("-"):
        sort = [(key, -direction) for key, direction in sort]
    sort = [*sort, ("_id", 1)]
    docs = kdb["claims"].find(q).sort(sort).skip(offset).limit(limit)
    return [claim_from_doc(d) for d in docs]


# --- labels ---------------------------------------------------------------------------------


def label_from_doc(d: dict[str, Any]) -> Label:
    return Label(id=d["_id"], transcript=d["transcript"], audio_path=d.get("audio_path"),
                 target_kind=d["target_kind"], target_ids=d["target_ids"], parsed=d["parsed"],
                 status=d["status"], created_at=d["created_at"])


def get_label(kdb: KnowledgeDB, label_id: str) -> Label | None:
    d = kdb["labels"].find_one({"_id": label_id})
    return label_from_doc(d) if d else None


def list_labels(kdb: KnowledgeDB, limit: int = 50) -> list[Label]:
    return [label_from_doc(d) for d in kdb["labels"].find().sort("created_at", -1).limit(limit)]


# --- organization: what labels say about files --------------------------------------------

_DESCRIBING = ("description", "summary")
# Relations that say where a file belongs (labels and the AI organizer). Extraction's detailed
# facts ("lists entry", "covers", ...) are graph knowledge, not Library tags.
ORGANIZING = ("about", "part_of", "category")


def _organizes(c: dict[str, Any]) -> bool:
    """A Library tag comes from the user (a label) or the AI organizer — never from fact
    extraction, whose "about"/"part_of" facts are graph detail, not folders."""
    ex = c.get("extractor") or {}
    return c.get("predicate") in ORGANIZING and (ex.get("kind") in ("user", "voice")
                                                 or ex.get("prompt_version") in ("organize-v1", "drop-organize-v1"))


def _by_user_first(c: dict[str, Any]) -> int:
    """What the user said (a label, an edit) beats what a model suggested."""
    return 0 if (c.get("extractor") or {}).get("kind") in ("user", "voice") else 1


def _file_entities(kdb: KnowledgeDB, source_ids: list[str]) -> dict[str, list[str]]:
    """source id -> the entities that represent it ("this file is the Acme contract")."""
    out: dict[str, list[str]] = {}
    for c in kdb["claims"].find({"predicate": "represented_by", "value": {"$in": source_ids},
                                 "status": {"$ne": "rejected"}}):
        out.setdefault(c["value"], []).append(c["subject_id"])
    return out


def file_organization(kdb: KnowledgeDB, source_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Tags (entities a file is about / linked to) and a description, per file."""
    reps = _file_entities(kdb, source_ids)
    ent_ids = [e for ids in reps.values() for e in ids]
    if not ent_ids:
        return {}
    links: dict[str, list[str]] = {}
    described: dict[str, str] = {}
    titled: dict[str, str] = {}
    claims = sorted(kdb["claims"].find({"subject_id": {"$in": ent_ids}, "status": {"$ne": "rejected"}}), key=_by_user_first)
    for c in claims:
        if c.get("object_id") and _organizes(c):
            links.setdefault(c["subject_id"], []).append(c["object_id"])
        elif c["predicate"] in _DESCRIBING and c.get("value") and c["subject_id"] not in described:
            described[c["subject_id"]] = str(c["value"])
        elif c["predicate"] == "title" and c.get("value") and c["subject_id"] not in titled:
            titled[c["subject_id"]] = str(c["value"])
    _add_parent_projects(kdb, links)
    names = get_entities(kdb, [o for v in links.values() for o in v])
    out: dict[str, dict[str, Any]] = {}
    for sid, ents in reps.items():
        tags, seen = [], set()
        for e in ents:
            for o in links.get(e, []):
                ent = names.get(o)
                if ent and o not in seen and ent.status.value not in ("merged", "rejected"):
                    seen.add(o)
                    tags.append({"id": o, "name": ent.name, "type": ent.type})
        desc = next((described[e] for e in ents if e in described), None)
        title = next((titled[e] for e in ents if e in titled), None)
        out[sid] = {"tags": tags, "description": desc, "title": title}
    return out


def _add_parent_projects(kdb: KnowledgeDB, links: dict[str, list[str]]) -> None:
    """A file in a drop folder also belongs to that folder's project: Library tags and the
    project filter show both (file -> Folder -> Project)."""
    targets = list({o for v in links.values() for o in v})
    if not targets:
        return
    parents: dict[str, list[str]] = {}
    for c in kdb["claims"].find({"subject_id": {"$in": targets}, "predicate": "part_of", "status": {"$ne": "rejected"}}):
        if c.get("object_id") and _organizes(c):
            parents.setdefault(c["subject_id"], []).append(c["object_id"])
    for key, objs in links.items():
        extra = [p for o in objs for p in parents.get(o, []) if p not in objs]
        links[key] = list(dict.fromkeys(extra + objs))  # the project first, then its folder


def files_tagged(kdb: KnowledgeDB, tag_id: str) -> list[str]:
    """Source ids of files organized under ``tag_id``: directly, through a drop folder
    (project -> folder -> file), or the file's own entity is the tag."""
    tag_id = resolve_merged(kdb, tag_id)
    members, frontier = {tag_id}, {tag_id}
    for _ in range(3):  # topic -> project -> folder -> file
        nxt = {c["subject_id"] for c in kdb["claims"].find({"object_id": {"$in": list(frontier)},
                                                            "status": {"$ne": "rejected"},
                                                            "predicate": {"$in": list(ORGANIZING)}}) if _organizes(c)}
        frontier = nxt - members
        members |= nxt
        if not frontier:
            break
    return [c["value"] for c in kdb["claims"].find({"predicate": "represented_by", "subject_id": {"$in": list(members)},
                                                    "status": {"$ne": "rejected"}})]

def top_tags(kdb: KnowledgeDB, limit: int = 14) -> list[dict[str, Any]]:
    """The entities most files are organized under (for the Library's topic chips)."""
    file_ents: dict[str, str] = {c["subject_id"]: c["value"] for c in kdb["claims"].find(
        {"predicate": "represented_by", "status": {"$ne": "rejected"}})}
    if not file_ents:
        return []
    counts: dict[str, set[str]] = {}
    links: dict[str, list[str]] = {}
    for c in kdb["claims"].find({"subject_id": {"$in": list(file_ents)}, "status": {"$ne": "rejected"},
                                 "predicate": {"$in": list(ORGANIZING)}}):
        if c.get("object_id") and _organizes(c):
            links.setdefault(c["subject_id"], []).append(c["object_id"])
    _add_parent_projects(kdb, links)
    # A project's topics (project --about--> topic) are tags of every file in the project.
    projects = list({o for objs in links.values() for o in objs})
    topics: dict[str, list[str]] = {}
    for c in kdb["claims"].find({"subject_id": {"$in": projects}, "predicate": {"$in": list(ORGANIZING)},
                                 "status": {"$ne": "rejected"}}):
        if c.get("object_id") and _organizes(c) and c["predicate"] != "part_of":
            topics.setdefault(c["subject_id"], []).append(c["object_id"])
    for doc, objs in links.items():
        inherited = [t for parent in objs for t in topics.get(parent, [])]
        for tag in objs + inherited:
            counts.setdefault(tag, set()).add(file_ents[doc])
    ents = get_entities(kdb, list(counts))
    ranked = sorted((e for e in ents.values() if e.status.value not in ("merged", "rejected") and e.type != "Document"),
                    key=lambda e: (-len(counts[e.id]), e.name.lower()))
    return [{"id": e.id, "name": e.name, "type": e.type, "count": len(counts[e.id])} for e in ranked[:limit]]
