from __future__ import annotations

import sqlite3
from typing import Any

from ..domain.errors import InvalidInput, NotFound
from ..domain.ids import new_id
from ..domain.models import ClaimStatus, Entity, EntityStatus, Extractor
from ..domain.rules import claim_fingerprint, normalize_name, requires_evidence
from ..domain.schema import MENTIONED, MENTIONS, REPRESENTED_BY, SchemaDef, load_pack
from ..domain.values import coerce
from ..ledger import Ledger, Tx
from ..store import repo
from ..store.db import Database, dumps, loads, utcnow

BUILTIN_ATTRIBUTES = {REPRESENTED_BY, MENTIONED}
FINGERPRINT_FIELDS = ("subject_id", "predicate", "value", "object_id")


class KnowledgeService:
    def __init__(self, db: Database, ledger: Ledger) -> None:
        self.db = db
        self.ledger = ledger

    # --- schema ---------------------------------------------------------------------------

    def ensure_schema(self, pack: str = "default") -> None:
        if self.db.reader().execute("SELECT 1 FROM schema_versions LIMIT 1").fetchone():
            return
        self._store_schema(load_pack(pack), actor="system")

    def schema(self) -> tuple[int, SchemaDef]:
        return repo.active_schema(self.db.reader())

    def update_schema(self, schema: SchemaDef) -> int:
        return self._store_schema(schema, actor="user")

    def _store_schema(self, schema: SchemaDef, actor: str) -> int:
        conn = self.db.reader()
        last = conn.execute("SELECT MAX(version) FROM schema_versions").fetchone()[0] or 0
        version = last + 1
        schema = schema.model_copy(update={"version": version})
        with self.ledger.group(actor, "schema.update", f"v{version}") as tx:
            tx.insert("schema_versions", {
                "id": new_id("schema"), "version": version, "name": schema.name,
                "definition": dumps(schema.model_dump(mode="json")), "created_at": utcnow(),
            })
        return version

    # --- entities -------------------------------------------------------------------------

    def _entity_row(self, conn: sqlite3.Connection, entity_id: str) -> sqlite3.Row:
        r = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
        if r is None:
            raise NotFound(f"entity {entity_id} not found")
        return r

    def _check_type(self, entity_type: str) -> None:
        _v, schema = self.schema()
        if entity_type not in schema.entity_types:
            raise InvalidInput(f"unknown entity type '{entity_type}'")

    def create_entity_tx(self, tx: Tx, entity_type: str, name: str, *, actor: str,
                         status: EntityStatus = EntityStatus.VERIFIED) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise InvalidInput("entity name is empty")
        self._check_type(entity_type)
        now = utcnow()
        row = tx.insert("entities", {
            "id": new_id("entity"), "type": entity_type, "name": name, "status": status.value,
            "created_by": actor, "merged_into": None, "created_at": now, "updated_at": now,
        })
        self.add_alias_tx(tx, row["id"], name, origin="name")
        return row

    def create_entity(self, entity_type: str, name: str, actor: str = "user") -> Entity:
        with self.ledger.group(actor, "entity.create", name) as tx:
            row = self.create_entity_tx(tx, entity_type, name, actor=actor)
        return repo.get_entity(self.db.reader(), row["id"])  # type: ignore[return-value]

    def add_alias_tx(self, tx: Tx, entity_id: str, alias: str, origin: str) -> None:
        norm = normalize_name(alias)
        if not norm or repo.alias_row(tx.conn, entity_id, norm) is not None:
            return
        tx.insert("aliases", {"id": new_id("alias"), "entity_id": entity_id, "alias": alias.strip(),
                              "normalized": norm, "origin": origin, "created_at": utcnow()})

    def add_alias(self, entity_id: str, alias: str) -> Entity:
        with self.ledger.group("user", "entity.alias", alias) as tx:
            self._entity_row(tx.conn, entity_id)
            self.add_alias_tx(tx, entity_id, alias, origin="user")
        return repo.get_entity(self.db.reader(), entity_id)  # type: ignore[return-value]

    def remove_alias(self, entity_id: str, alias: str) -> Entity:
        with self.ledger.group("user", "entity.alias.remove", alias) as tx:
            row = repo.alias_row(tx.conn, entity_id, normalize_name(alias))
            if row is None:
                raise NotFound(f"alias '{alias}' not found")
            tx.delete("aliases", row["id"])
        return repo.get_entity(self.db.reader(), entity_id)  # type: ignore[return-value]

    def update_entity(self, entity_id: str, *, name: str | None = None, type: str | None = None,
                      status: EntityStatus | None = None, actor: str = "user") -> Entity:
        with self.ledger.group(actor, "entity.update", name or type or (status or "")) as tx:
            self.update_entity_tx(tx, entity_id, name=name, type=type, status=status)
        return repo.get_entity(self.db.reader(), entity_id)  # type: ignore[return-value]

    def update_entity_tx(self, tx: Tx, entity_id: str, *, name: str | None = None,
                         type: str | None = None, status: EntityStatus | None = None) -> None:
        row = self._entity_row(tx.conn, entity_id)
        changes: dict[str, Any] = {}
        if name and name.strip() != row["name"]:
            changes["name"] = name.strip()
            self.add_alias_tx(tx, entity_id, name, origin="user")  # old name stays as an alias
        if type and type != row["type"]:
            self._check_type(type)
            changes["type"] = type
        if status:
            changes["status"] = status.value
        elif row["status"] == EntityStatus.AUTO and tx.actor in ("user", "voice"):
            changes["status"] = EntityStatus.VERIFIED.value  # editing implies confirming
        if changes:
            tx.update("entities", entity_id, changes)
        if status == EntityStatus.REJECTED:
            # Claims about a rejected entity are rejected too, so they are never re-proposed.
            for c in tx.conn.execute(
                "SELECT id FROM claims WHERE (subject_id = ? OR object_id = ?) AND status = 'proposed'",
                (entity_id, entity_id),
            ).fetchall():
                tx.update("claims", c["id"], {"status": ClaimStatus.REJECTED.value})

    def merge_entities(self, keep_id: str, merge_id: str, actor: str = "user") -> Entity:
        """Fold ``merge_id`` into ``keep_id``. Rewrites no history: it is one undoable group.
        The merged entity's names become aliases of the survivor (learning signal, FR-8)."""
        conn = self.db.reader()
        keep_id, merge_id = repo.resolve_merged(conn, keep_id), repo.resolve_merged(conn, merge_id)
        if keep_id == merge_id:
            raise InvalidInput("cannot merge an entity with itself")
        keep = self._entity_row(conn, keep_id)
        merge = self._entity_row(conn, merge_id)
        with self.ledger.group(actor, "entity.merge", f"{merge['name']} → {keep['name']}") as tx:
            for a in tx.conn.execute("SELECT * FROM aliases WHERE entity_id = ?", (merge_id,)).fetchall():
                if repo.alias_row(tx.conn, keep_id, a["normalized"]) is not None:
                    tx.delete("aliases", a["id"])
                else:
                    tx.update("aliases", a["id"], {"entity_id": keep_id, "origin": "merge"})
            claims = tx.conn.execute(
                "SELECT * FROM claims WHERE subject_id = ? OR object_id = ?", (merge_id, merge_id)
            ).fetchall()
            for c in claims:
                subject = keep_id if c["subject_id"] == merge_id else c["subject_id"]
                obj = keep_id if c["object_id"] == merge_id else c["object_id"]
                self._repoint_claim(tx, c, subject, obj)
            tx.update("entities", merge_id, {"status": EntityStatus.MERGED.value, "merged_into": keep_id})
            if actor in ("user", "voice") and keep["status"] == EntityStatus.AUTO:
                tx.update("entities", keep_id, {"status": EntityStatus.VERIFIED.value})
        with self.db.write() as wconn:
            wconn.execute(
                "DELETE FROM ix.merge_suggestions WHERE (entity_a = ? AND entity_b = ?) OR (entity_a = ? AND entity_b = ?)",
                (keep_id, merge_id, merge_id, keep_id),
            )
        return repo.get_entity(self.db.reader(), keep_id)  # type: ignore[return-value]

    def split_entity(self, entity_id: str, new_name: str, claim_ids: list[str],
                     new_type: str | None = None, actor: str = "user") -> Entity:
        """Move the given claims from ``entity_id`` to a new entity (undo of a wrong merge)."""
        with self.ledger.group(actor, "entity.split", new_name) as tx:
            src = self._entity_row(tx.conn, entity_id)
            new = self.create_entity_tx(tx, new_type or src["type"], new_name, actor=actor)
            for claim_id in claim_ids:
                c = tx.conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
                if c is None or entity_id not in (c["subject_id"], c["object_id"]):
                    raise InvalidInput(f"claim {claim_id} is not about this entity")
                subject = new["id"] if c["subject_id"] == entity_id else c["subject_id"]
                obj = new["id"] if c["object_id"] == entity_id else c["object_id"]
                self._repoint_claim(tx, c, subject, obj)
        return repo.get_entity(self.db.reader(), new["id"])  # type: ignore[return-value]

    def _repoint_claim(self, tx: Tx, c: sqlite3.Row, subject: str, obj: str | None) -> None:
        if c["kind"] == "relation" and subject == obj:
            for ev in tx.conn.execute("SELECT id FROM evidence WHERE claim_id = ?", (c["id"],)).fetchall():
                tx.delete("evidence", ev["id"])
            tx.delete("claims", c["id"])  # a relation to itself is meaningless after merge
            return
        fp = claim_fingerprint(subject, c["predicate"], loads(c["value"]), obj)
        dup = tx.conn.execute(
            "SELECT * FROM claims WHERE fingerprint = ? AND id != ?", (fp, c["id"])
        ).fetchone()
        if dup is None:
            tx.update("claims", c["id"], {"subject_id": subject, "object_id": obj, "fingerprint": fp})
            return
        # Same fact now stated twice: keep one claim, move evidence, keep the stronger status.
        for ev in tx.conn.execute("SELECT id FROM evidence WHERE claim_id = ?", (c["id"],)).fetchall():
            tx.update("evidence", ev["id"], {"claim_id": dup["id"]})
        if c["status"] == ClaimStatus.VERIFIED and dup["status"] != ClaimStatus.VERIFIED:
            tx.update("claims", dup["id"], {"status": ClaimStatus.VERIFIED.value})
        tx.delete("claims", c["id"])

    # --- claims ---------------------------------------------------------------------------

    def _validate_claim(self, conn: sqlite3.Connection, schema: SchemaDef, subject_id: str,
                        predicate: str, value: Any, object_id: str | None) -> tuple[str, Any]:
        """Return (kind, normalised value) or raise InvalidInput (FR-4: schema-checked output)."""
        subject = self._entity_row(conn, subject_id)
        if predicate in schema.relation_types or predicate == MENTIONS:
            if not object_id:
                raise InvalidInput(f"relation '{predicate}' needs an object entity")
            obj = self._entity_row(conn, object_id)
            if not schema.relation_allows(predicate, subject["type"], obj["type"]):
                raise InvalidInput(
                    f"'{predicate}' is not allowed from {subject['type']} to {obj['type']}")
            return "relation", None
        if object_id:
            raise InvalidInput(f"'{predicate}' is not a relation in the schema")
        if predicate in BUILTIN_ATTRIBUTES:
            return "attribute", value
        attr = schema.attribute(subject["type"], predicate)
        if attr is None:
            raise InvalidInput(f"{subject['type']} has no attribute '{predicate}'")
        return "attribute", coerce(attr.type, value)

    def add_claim_tx(self, tx: Tx, *, subject_id: str, predicate: str, value: Any = None,
                     object_id: str | None = None, valid_from: str | None = None,
                     valid_to: str | None = None, confidence: float = 1.0,
                     status: ClaimStatus = ClaimStatus.VERIFIED, extractor: Extractor,
                     evidence: list[dict[str, Any]] | None = None, label_id: str | None = None,
                     schema: tuple[int, SchemaDef] | None = None) -> tuple[str | None, str]:
        """Create a claim or fold into an existing identical one.

        Returns (claim_id, outcome) with outcome one of ``created``, ``merged``, ``blocked``.
        ``blocked`` means a model proposed a fact the user already rejected (FR-8).
        """
        evidence = evidence or []
        if requires_evidence(extractor.kind) and not evidence:
            raise InvalidInput("model claims must cite at least one evidence span")
        version, sch = schema or self.schema()
        subject_id = repo.resolve_merged(tx.conn, subject_id)
        object_id = repo.resolve_merged(tx.conn, object_id) if object_id else None
        kind, value = self._validate_claim(tx.conn, sch, subject_id, predicate, value, object_id)
        fp = claim_fingerprint(subject_id, predicate, value, object_id)
        is_model = extractor.kind == "model"

        existing = repo.claims_by_fingerprint(tx.conn, fp)
        if existing:
            if is_model and any(e["status"] == ClaimStatus.REJECTED for e in existing):
                return None, "blocked"
            target = next((e for e in existing if e["status"] != ClaimStatus.REJECTED), existing[0])
            changes: dict[str, Any] = {}
            if not is_model and target["status"] != ClaimStatus.VERIFIED:
                changes["status"] = ClaimStatus.VERIFIED.value  # the user asserted it
            if target["status"] == ClaimStatus.PROPOSED and confidence > target["confidence"]:
                changes["confidence"] = confidence
            if changes:
                tx.update("claims", target["id"], changes)
            self._add_evidence_tx(tx, target["id"], evidence)
            return target["id"], "merged"

        now = utcnow()
        claim_id = new_id("claim")
        tx.insert("claims", {
            "id": claim_id, "subject_id": subject_id, "predicate": predicate, "kind": kind,
            "value": dumps(value) if kind == "attribute" else None, "object_id": object_id,
            "valid_from": valid_from, "valid_to": valid_to, "confidence": float(confidence),
            "status": status.value, "extractor": dumps(extractor.model_dump()), "fingerprint": fp,
            "label_id": label_id, "needs_review": 0, "schema_version": version,
            "created_at": now, "updated_at": now,
        })
        self._add_evidence_tx(tx, claim_id, evidence)
        return claim_id, "created"

    def _add_evidence_tx(self, tx: Tx, claim_id: str, evidence: list[dict[str, Any]]) -> None:
        for ev in evidence:
            locator = dumps(ev["locator"])
            dup = tx.conn.execute(
                "SELECT 1 FROM evidence WHERE claim_id = ? AND COALESCE(source_id, '') = ? "
                "AND quote = ? AND locator = ?",
                (claim_id, ev.get("source_id") or "", ev["quote"], locator),
            ).fetchone()
            if dup:
                continue
            tx.insert("evidence", {
                "id": new_id("evidence"), "claim_id": claim_id, "source_id": ev.get("source_id"),
                "chunk_id": ev.get("chunk_id"), "locator": locator, "quote": ev["quote"],
                "label_id": ev.get("label_id"), "created_at": utcnow(),
            })

    def add_claim(self, actor: str = "user", **kwargs: Any) -> str | None:
        with self.ledger.group(actor, "claim.create", kwargs.get("predicate", "")) as tx:
            claim_id, _ = self.add_claim_tx(tx, **kwargs)
        return claim_id

    def edit_claim(self, claim_id: str, changes: dict[str, Any], actor: str = "user") -> str:
        """User correction (FR-7). Changing *what* the claim says rejects the original (so the
        mistake is never re-proposed) and creates a verified replacement; changing only dates
        or confidence edits in place. Returns the id of the resulting claim."""
        allowed = {"subject_id", "predicate", "value", "object_id", "valid_from", "valid_to"}
        bad = set(changes) - allowed
        if bad:
            raise InvalidInput(f"cannot edit {sorted(bad)}")
        with self.ledger.group(actor, "claim.edit") as tx:
            c = tx.conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
            if c is None:
                raise NotFound(f"claim {claim_id} not found")
            current = {**dict(c), "value": loads(c["value"])}
            if any(k in changes and changes[k] != current[k] for k in FINGERPRINT_FIELDS):
                tx.update("claims", claim_id, {"status": ClaimStatus.REJECTED.value})
                new_id_, _ = self.add_claim_tx(
                    tx,
                    subject_id=changes.get("subject_id", c["subject_id"]),
                    predicate=changes.get("predicate", c["predicate"]),
                    value=changes.get("value", current["value"]),
                    object_id=changes.get("object_id", c["object_id"]),
                    valid_from=changes.get("valid_from", c["valid_from"]),
                    valid_to=changes.get("valid_to", c["valid_to"]),
                    status=ClaimStatus.VERIFIED, extractor=Extractor(kind="user"),
                )
                return new_id_  # type: ignore[return-value]
            tx.update("claims", claim_id, {
                **{k: changes[k] for k in ("valid_from", "valid_to") if k in changes},
                "status": ClaimStatus.VERIFIED.value, "needs_review": 0,
            })
            return claim_id

    def set_claim_status(self, claim_ids: list[str], status: ClaimStatus, actor: str = "user") -> int:
        action = {"verified": "claim.verify", "rejected": "claim.reject"}.get(status.value, "claim.status")
        with self.ledger.group(actor, action, f"{len(claim_ids)} claim(s)") as tx:
            for cid in claim_ids:
                if tx._row("claims", cid) is None:
                    raise NotFound(f"claim {cid} not found")
                tx.update("claims", cid, {"status": status.value, "needs_review": 0})
        return len(claim_ids)
