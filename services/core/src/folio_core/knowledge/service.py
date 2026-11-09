from __future__ import annotations

from typing import Any

from ..domain.errors import InvalidInput, NotFound
from ..domain.ids import new_id
from ..domain.models import ClaimStatus, Entity, EntityStatus, Extractor
from ..domain.rules import claim_fingerprint, normalize_name, requires_evidence
from ..domain.schema import (
    MENTIONED,
    MENTIONS,
    REPRESENTED_BY,
    SchemaDef,
    canonical_predicate,
    canonical_type,
    load_pack,
)
from ..domain.values import coerce
from ..ledger import Ledger, Tx
from ..store import repo
from ..store.index_db import IndexDB, utcnow
from ..store.local import KnowledgeDB

BUILTIN_PREDICATES = {REPRESENTED_BY, MENTIONED, MENTIONS}
FINGERPRINT_FIELDS = ("subject_id", "predicate", "value", "object_id")


def _alias(alias: str, origin: str) -> dict[str, Any]:
    return {"alias": alias.strip(), "normalized": normalize_name(alias), "origin": origin,
            "created_at": utcnow()}


def _evidence_key(ev: dict[str, Any]) -> tuple[Any, ...]:
    loc = ev.get("locator") or {}
    return (ev.get("source_id") or "", ev.get("quote", ""), tuple(sorted((k, str(v)) for k, v in loc.items())))


class KnowledgeService:
    def __init__(self, kdb: KnowledgeDB, ledger: Ledger, index: IndexDB) -> None:
        self.kdb = kdb
        self.ledger = ledger
        self.index = index

    # --- type hints (schema) --------------------------------------------------------------

    def ensure_schema(self, pack: str = "default") -> None:
        if self.kdb["schema_versions"].find_one() is None:
            self._store_schema(load_pack(pack), actor="system")

    def schema(self) -> tuple[int, SchemaDef]:
        return repo.active_schema(self.kdb)

    def update_schema(self, schema: SchemaDef) -> int:
        return self._store_schema(schema, actor="user")

    def _store_schema(self, schema: SchemaDef, actor: str) -> int:
        last = self.kdb["schema_versions"].find_one(sort=[("version", -1)])
        version = (last["version"] if last else 0) + 1
        schema = schema.model_copy(update={"version": version})
        with self.ledger.group(actor, "schema.update", f"v{version}") as tx:
            tx.insert("schema_versions", {
                "id": new_id("schema"), "version": version, "name": schema.name,
                "definition": schema.model_dump(mode="json"), "created_at": utcnow(),
            })
        return version

    def known_types(self) -> list[str]:
        _v, schema = self.schema()
        return sorted(set(schema.entity_types) | set(repo.types_in_use(self.kdb)))

    # --- entities -------------------------------------------------------------------------

    @staticmethod
    def _entity(tx: Tx, entity_id: str) -> dict[str, Any]:
        row = tx.get("entities", entity_id)
        if row is None:
            raise NotFound(f"entity {entity_id} not found")
        return row

    def create_entity_tx(self, tx: Tx, entity_type: str, name: str, *, actor: str,
                         status: EntityStatus = EntityStatus.VERIFIED) -> dict[str, Any]:
        name = " ".join(name.split())
        if not name:
            raise InvalidInput("entity name is empty")
        now = utcnow()
        return tx.insert("entities", {
            "id": new_id("entity"), "type": canonical_type(entity_type, self.known_types()),
            "name": name, "status": status.value, "created_by": actor, "merged_into": None,
            "aliases": [_alias(name, "name")], "created_at": now, "updated_at": now,
        })

    def create_entity(self, entity_type: str, name: str, actor: str = "user") -> Entity:
        with self.ledger.group(actor, "entity.create", name) as tx:
            row = self.create_entity_tx(tx, entity_type, name, actor=actor)
        return repo.get_entity(self.kdb, row["id"])  # type: ignore[return-value]

    def add_alias_tx(self, tx: Tx, entity_id: str, alias: str, origin: str) -> None:
        row = self._entity(tx, entity_id)
        norm = normalize_name(alias)
        if not norm or any(a["normalized"] == norm for a in row["aliases"]):
            return
        tx.update("entities", entity_id, {"aliases": [*row["aliases"], _alias(alias, origin)]})

    def add_alias(self, entity_id: str, alias: str) -> Entity:
        with self.ledger.group("user", "entity.alias", alias) as tx:
            self.add_alias_tx(tx, entity_id, alias, origin="user")
        return repo.get_entity(self.kdb, entity_id)  # type: ignore[return-value]

    def remove_alias(self, entity_id: str, alias: str) -> Entity:
        norm = normalize_name(alias)
        with self.ledger.group("user", "entity.alias.remove", alias) as tx:
            row = self._entity(tx, entity_id)
            kept = [a for a in row["aliases"] if a["normalized"] != norm]
            if len(kept) == len(row["aliases"]):
                raise NotFound(f"alias '{alias}' not found")
            tx.update("entities", entity_id, {"aliases": kept})
        return repo.get_entity(self.kdb, entity_id)  # type: ignore[return-value]

    def update_entity(self, entity_id: str, *, name: str | None = None, type: str | None = None,
                      status: EntityStatus | None = None, actor: str = "user") -> Entity:
        with self.ledger.group(actor, "entity.update", name or type or (status or "")) as tx:
            self.update_entity_tx(tx, entity_id, name=name, type=type, status=status)
        return repo.get_entity(self.kdb, entity_id)  # type: ignore[return-value]

    def update_entity_tx(self, tx: Tx, entity_id: str, *, name: str | None = None,
                         type: str | None = None, status: EntityStatus | None = None) -> None:
        row = self._entity(tx, entity_id)
        changes: dict[str, Any] = {}
        if name and " ".join(name.split()) != row["name"]:
            changes["name"] = " ".join(name.split())
            self.add_alias_tx(tx, entity_id, name, origin="user")  # old name stays an alias
        if type:
            t = canonical_type(type, self.known_types())
            if t != row["type"]:
                changes["type"] = t
        if status:
            changes["status"] = status.value
        elif row["status"] == EntityStatus.AUTO and tx.actor in ("user", "voice"):
            changes["status"] = EntityStatus.VERIFIED.value  # editing implies confirming
        if changes:
            tx.update("entities", entity_id, changes)
        if status == EntityStatus.REJECTED:
            # Claims about a rejected entity are rejected too, so they are never re-proposed.
            for c in tx.find("claims", {"$or": [{"subject_id": entity_id}, {"object_id": entity_id}],
                                        "status": "proposed"}):
                tx.update("claims", c["id"], {"status": ClaimStatus.REJECTED.value})

    def merge_entities(self, keep_id: str, merge_id: str, actor: str = "user") -> Entity:
        """Fold ``merge_id`` into ``keep_id`` as one undoable group. The merged entity's names
        become aliases of the survivor (learning signal, FR-8)."""
        keep_id, merge_id = repo.resolve_merged(self.kdb, keep_id), repo.resolve_merged(self.kdb, merge_id)
        if keep_id == merge_id:
            raise InvalidInput("cannot merge an entity with itself")
        with self.ledger.group(actor, "entity.merge") as tx:
            keep = self._entity(tx, keep_id)
            merge = self._entity(tx, merge_id)
            have = {a["normalized"] for a in keep["aliases"]}
            extra = [{**a, "origin": "merge"} for a in merge["aliases"] if a["normalized"] not in have]
            if extra:
                tx.update("entities", keep_id, {"aliases": [*keep["aliases"], *extra]})
            for c in tx.find("claims", {"$or": [{"subject_id": merge_id}, {"object_id": merge_id}]}):
                subject = keep_id if c["subject_id"] == merge_id else c["subject_id"]
                obj = keep_id if c.get("object_id") == merge_id else c.get("object_id")
                self._repoint_claim(tx, c, subject, obj)
            tx.update("entities", merge_id, {"status": EntityStatus.MERGED.value, "merged_into": keep_id})
            if actor in ("user", "voice") and keep["status"] == EntityStatus.AUTO:
                tx.update("entities", keep_id, {"status": EntityStatus.VERIFIED.value})
        with self.index.write() as conn:
            conn.execute(
                "DELETE FROM merge_suggestions WHERE (entity_a = ? AND entity_b = ?) OR (entity_a = ? AND entity_b = ?)",
                (keep_id, merge_id, merge_id, keep_id),
            )
        return repo.get_entity(self.kdb, keep_id)  # type: ignore[return-value]

    def split_entity(self, entity_id: str, new_name: str, claim_ids: list[str],
                     new_type: str | None = None, actor: str = "user") -> Entity:
        """Move the given claims from ``entity_id`` to a new entity (undo of a wrong merge)."""
        with self.ledger.group(actor, "entity.split", new_name) as tx:
            src = self._entity(tx, entity_id)
            new = self.create_entity_tx(tx, new_type or src["type"], new_name, actor=actor)
            for claim_id in claim_ids:
                c = tx.get("claims", claim_id)
                if c is None or entity_id not in (c["subject_id"], c.get("object_id")):
                    raise InvalidInput(f"claim {claim_id} is not about this entity")
                subject = new["id"] if c["subject_id"] == entity_id else c["subject_id"]
                obj = new["id"] if c.get("object_id") == entity_id else c.get("object_id")
                self._repoint_claim(tx, c, subject, obj)
        return repo.get_entity(self.kdb, new["id"])  # type: ignore[return-value]

    def _repoint_claim(self, tx: Tx, c: dict[str, Any], subject: str, obj: str | None) -> None:
        if c["kind"] == "relation" and subject == obj:
            tx.delete("claims", c["id"])  # a relation to itself is meaningless after a merge
            return
        fp = claim_fingerprint(subject, c["predicate"], c.get("value"), obj)
        dup = next((d for d in tx.find("claims", {"fingerprint": fp}) if d["id"] != c["id"]), None)
        if dup is None:
            tx.update("claims", c["id"], {"subject_id": subject, "object_id": obj, "fingerprint": fp})
            return
        # Same fact now stated twice: keep one claim, move evidence, keep the stronger status.
        changes: dict[str, Any] = {"evidence": self._merge_evidence(dup["evidence"], c["evidence"])}
        if c["status"] == ClaimStatus.VERIFIED and dup["status"] != ClaimStatus.VERIFIED:
            changes["status"] = ClaimStatus.VERIFIED.value
        tx.update("claims", dup["id"], changes)
        tx.delete("claims", c["id"])

    # --- claims ---------------------------------------------------------------------------

    @staticmethod
    def _merge_evidence(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen = {_evidence_key(e) for e in existing}
        out = list(existing)
        for ev in new:
            if _evidence_key(ev) not in seen:
                seen.add(_evidence_key(ev))
                out.append({"id": ev.get("id") or new_id("evidence"), "created_at": ev.get("created_at") or utcnow(),
                            "source_id": ev.get("source_id"), "chunk_id": ev.get("chunk_id"),
                            "locator": ev["locator"], "quote": ev["quote"], "label_id": ev.get("label_id")})
        return out

    def _normalize(self, tx: Tx, schema: SchemaDef, subject_id: str, predicate: str, value: Any,
                   object_id: str | None) -> tuple[str, str, Any]:
        """Return (kind, predicate, value). Open schema: anything goes, but values of attributes
        that the hints type (e.g. dates) are parsed, and relations must point at an entity."""
        subject = self._entity(tx, subject_id)
        pred = predicate if predicate in BUILTIN_PREDICATES else canonical_predicate(predicate)
        if object_id:
            self._entity(tx, object_id)
            return "relation", pred, None
        if value is None or (isinstance(value, str) and not value.strip()):
            raise InvalidInput(f"'{pred}' needs a value")
        hint = schema.attribute(subject["type"], pred)
        if hint is not None and hint.type != "string":
            value = coerce(hint.type, value)
        elif isinstance(value, str):
            value = value.strip()
        return "attribute", pred, value

    def add_claim_tx(self, tx: Tx, *, subject_id: str, predicate: str, value: Any = None,
                     object_id: str | None = None, valid_from: str | None = None,
                     valid_to: str | None = None, confidence: float = 1.0,
                     status: ClaimStatus = ClaimStatus.VERIFIED, extractor: Extractor,
                     evidence: list[dict[str, Any]] | None = None, label_id: str | None = None,
                     schema: tuple[int, SchemaDef] | None = None) -> tuple[str | None, str]:
        """Create a claim or fold into an existing identical one.

        Returns (claim_id, outcome) with outcome ``created``, ``merged`` or ``blocked``.
        ``blocked`` means a model proposed a fact the user already rejected (FR-8).
        """
        evidence = evidence or []
        if requires_evidence(extractor.kind) and not evidence:
            raise InvalidInput("model claims must cite at least one evidence span")
        version, sch = schema or self.schema()
        subject_id = repo.resolve_merged(self.kdb, subject_id, tx.session)
        object_id = repo.resolve_merged(self.kdb, object_id, tx.session) if object_id else None
        kind, predicate, value = self._normalize(tx, sch, subject_id, predicate, value, object_id)
        fp = claim_fingerprint(subject_id, predicate, value, object_id)
        is_model = extractor.kind == "model"

        existing = tx.find("claims", {"fingerprint": fp})
        if existing:
            if is_model and any(e["status"] == ClaimStatus.REJECTED for e in existing):
                return None, "blocked"
            target = next((e for e in existing if e["status"] != ClaimStatus.REJECTED), existing[0])
            changes: dict[str, Any] = {}
            if not is_model and target["status"] != ClaimStatus.VERIFIED:
                changes["status"] = ClaimStatus.VERIFIED.value  # the user asserted it
            if target["status"] == ClaimStatus.PROPOSED and confidence > target["confidence"]:
                changes["confidence"] = confidence
            merged = self._merge_evidence(target["evidence"], evidence)
            if len(merged) != len(target["evidence"]):
                changes["evidence"] = merged
            if changes:
                tx.update("claims", target["id"], changes)
            return target["id"], "merged"

        now = utcnow()
        claim_id = new_id("claim")
        tx.insert("claims", {
            "id": claim_id, "subject_id": subject_id, "predicate": predicate, "kind": kind,
            "value": value if kind == "attribute" else None, "object_id": object_id,
            "valid_from": valid_from, "valid_to": valid_to, "confidence": float(confidence),
            "status": status.value, "extractor": extractor.model_dump(), "fingerprint": fp,
            "label_id": label_id, "needs_review": False, "schema_version": version,
            "evidence": self._merge_evidence([], evidence), "created_at": now, "updated_at": now,
        })
        return claim_id, "created"

    def add_claim(self, actor: str = "user", **kwargs: Any) -> str | None:
        with self.ledger.group(actor, "claim.create", kwargs.get("predicate", "")) as tx:
            claim_id, _ = self.add_claim_tx(tx, **kwargs)
        return claim_id

    def edit_claim(self, claim_id: str, changes: dict[str, Any], actor: str = "user") -> str:
        """User correction (FR-7). Changing *what* the claim says rejects the original (so the
        mistake is never re-proposed) and creates a verified replacement; changing only dates
        edits in place. Returns the id of the resulting claim."""
        allowed = {"subject_id", "predicate", "value", "object_id", "valid_from", "valid_to"}
        bad = set(changes) - allowed
        if bad:
            raise InvalidInput(f"cannot edit {sorted(bad)}")
        with self.ledger.group(actor, "claim.edit") as tx:
            c = tx.get("claims", claim_id)
            if c is None:
                raise NotFound(f"claim {claim_id} not found")
            if any(k in changes and changes[k] != c.get(k) for k in FINGERPRINT_FIELDS):
                tx.update("claims", claim_id, {"status": ClaimStatus.REJECTED.value})
                new_claim, _ = self.add_claim_tx(
                    tx,
                    subject_id=changes.get("subject_id", c["subject_id"]),
                    predicate=changes.get("predicate", c["predicate"]),
                    value=changes.get("value", c.get("value")),
                    object_id=changes.get("object_id", c.get("object_id")),
                    valid_from=changes.get("valid_from", c.get("valid_from")),
                    valid_to=changes.get("valid_to", c.get("valid_to")),
                    status=ClaimStatus.VERIFIED, extractor=Extractor(kind="user"),
                )
                return new_claim  # type: ignore[return-value]
            tx.update("claims", claim_id, {
                **{k: changes[k] for k in ("valid_from", "valid_to") if k in changes},
                "status": ClaimStatus.VERIFIED.value, "needs_review": False,
            })
            return claim_id

    def set_claim_status(self, claim_ids: list[str], status: ClaimStatus, actor: str = "user") -> int:
        action = {"verified": "claim.verify", "rejected": "claim.reject"}.get(status.value, "claim.status")
        with self.ledger.group(actor, action, f"{len(claim_ids)} claim(s)") as tx:
            for cid in claim_ids:
                if tx.get("claims", cid) is None:
                    raise NotFound(f"claim {cid} not found")
                tx.update("claims", cid, {"status": status.value, "needs_review": False})
        return len(claim_ids)
