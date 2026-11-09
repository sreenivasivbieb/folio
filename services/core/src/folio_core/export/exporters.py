from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ..domain.errors import Conflict, InvalidInput
from ..domain.schema import MENTIONS, REPRESENTED_BY, SchemaDef
from ..realtime import Bus
from ..store import repo
from ..store.index_db import utcnow
from ..store.local import KnowledgeDB, WriteConflict

FORMAT = "folio.v2"
DURABLE = ["settings", "schema_versions", "roots", "sources", "entities", "claims", "labels",
           "event_groups", "events"]
LEDGER = ("event_groups", "events")
GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"
NODE_KEYS = ["type", "name", "status", "aliases", "entity_json"]
EDGE_KEYS = ["predicate", "status", "confidence", "valid_from", "claim_json"]


class Exporter:
    def __init__(self, kdb: KnowledgeDB, bus: Bus) -> None:
        self.kdb = kdb
        self.bus = bus

    def _docs(self, coll: str) -> list[dict[str, Any]]:
        sort = [("seq", 1)] if coll in LEDGER else [("_id", 1)]
        return list(self.kdb[coll].find().sort(sort))

    def _ensure_empty(self, session=None) -> None:  # type: ignore[no-untyped-def]
        if (self.kdb["entities"].count_documents({}, limit=1, session=session)
                or self.kdb["claims"].count_documents({}, limit=1, session=session)):
            raise Conflict("import needs an empty project (this one already has entities or claims)")

    @staticmethod
    def _validate_rows(coll: str, docs: Any) -> list[dict[str, Any]]:
        if not isinstance(docs, list):
            raise InvalidInput(f"{coll} must be an array")
        seen: set[str] = set()
        try:
            for d in docs:
                if not isinstance(d, dict) or not isinstance(d.get("_id"), str) or not d["_id"]:
                    raise ValueError("each record needs a string _id")
                if d["_id"] in seen:
                    raise ValueError(f"duplicate id {d['_id']}")
                seen.add(d["_id"])
                if coll == "entities":
                    repo.entity_from_doc(d)
                elif coll == "claims":
                    repo.claim_from_doc(d)
                elif coll == "sources":
                    repo.source_from_doc(d)
                elif coll == "roots":
                    repo.root_from_doc(d)
                elif coll == "labels":
                    repo.label_from_doc(d)
                elif coll == "schema_versions":
                    SchemaDef.model_validate(d["definition"])
                    if not isinstance(d["version"], int):
                        raise ValueError("schema version must be an integer")
                elif coll in LEDGER and not isinstance(d["seq"], int):
                    raise ValueError("ledger sequence must be an integer")
        except (ValueError, TypeError, KeyError) as exc:
            raise InvalidInput(f"invalid {coll} import: {exc}") from exc
        return docs

    def _imported(self, colls: list[str]) -> None:
        self.bus.publish({"type": "ledger", "action": "import", "tables": colls, "rows": []})

    # --- JSON (lossless, including the full ledger) ---------------------------------------

    def to_json(self) -> dict[str, Any]:
        with self.kdb._write_lock:
            return {"format": FORMAT, "exported_at": utcnow(), **{c: self._docs(c) for c in DURABLE}}

    def from_json(self, data: dict[str, Any]) -> dict[str, int]:
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise InvalidInput(f"not a {FORMAT} export")
        prepared = {coll: self._validate_rows(coll, data.get(coll, [])) for coll in DURABLE}
        counts: dict[str, int] = {}
        # The fresh project only holds its own schema install: the import's hints replace it, and
        # imported ledger entries are appended after this project's own (renumbered, same order).
        try:
            with self.kdb.transaction() as session:
                self._ensure_empty(session)
                self.kdb["schema_versions"].delete_many({}, session=session)
                offsets = {c: (self.kdb[c].find_one(sort=[("seq", -1)], session=session)
                               or {"seq": 0})["seq"] for c in LEDGER}
                for coll in DURABLE:
                    docs = prepared[coll]
                    if coll in LEDGER:
                        docs = [{**d, "seq": d["seq"] + offsets[coll]} for d in docs]
                    if coll == "sources":
                        docs = [{**d, "indexed_hash": None,
                                 "status": d["status"] if d["status"] in ("forgotten", "removed") else "pending"}
                                for d in docs]
                    if docs:
                        if coll == "settings":
                            self.kdb[coll].delete_many({"_id": {"$in": [d["_id"] for d in docs]}}, session=session)
                        self.kdb[coll].insert_many(docs, session=session)
                    counts[coll] = len(docs)
                for coll, counter in (("events", "events"), ("event_groups", "groups")):
                    top = self.kdb[coll].find_one(sort=[("seq", -1)], session=session)
                    if top:
                        self.kdb["counters"].update_one({"_id": counter}, {"$max": {"seq": top["seq"]}},
                                                        upsert=True, session=session)
        except WriteConflict as exc:
            raise InvalidInput("import conflicts with existing records; nothing was imported") from exc
        self._imported(DURABLE)
        return counts

    # --- GraphML (readable fields + the full document for a lossless round trip) ----------

    def to_graphml(self) -> bytes:
        ET.register_namespace("", GRAPHML_NS)
        root = ET.Element(f"{{{GRAPHML_NS}}}graphml")
        for k in NODE_KEYS:
            ET.SubElement(root, f"{{{GRAPHML_NS}}}key", id=f"n_{k}", attrib={"for": "node", "attr.name": k, "attr.type": "string"})
        for k in EDGE_KEYS:
            ET.SubElement(root, f"{{{GRAPHML_NS}}}key", id=f"e_{k}", attrib={"for": "edge", "attr.name": k, "attr.type": "string"})
        ET.SubElement(root, f"{{{GRAPHML_NS}}}key", id="n_attribute_claims",
                      attrib={"for": "node", "attr.name": "attribute_claims", "attr.type": "string"})
        graph = ET.SubElement(root, f"{{{GRAPHML_NS}}}graph", id="folio", edgedefault="directed")

        def data(parent: ET.Element, key: str, value: Any) -> None:
            if value is None:
                return
            d = ET.SubElement(parent, f"{{{GRAPHML_NS}}}data", key=key)
            d.text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

        claims = self._docs("claims")
        attrs: dict[str, list[dict[str, Any]]] = {}
        for c in claims:
            if c["kind"] == "attribute":
                attrs.setdefault(c["subject_id"], []).append(c)
        for e in self._docs("entities"):
            node = ET.SubElement(graph, f"{{{GRAPHML_NS}}}node", id=e["_id"])
            data(node, "n_type", e["type"])
            data(node, "n_name", e["name"])
            data(node, "n_status", e["status"])
            data(node, "n_aliases", ", ".join(a["alias"] for a in e.get("aliases", [])))
            data(node, "n_entity_json", e)
            data(node, "n_attribute_claims", attrs.get(e["_id"], []))
        for c in claims:
            if c["kind"] != "relation":
                continue
            edge = ET.SubElement(graph, f"{{{GRAPHML_NS}}}edge", id=c["_id"], source=c["subject_id"], target=c["object_id"])
            data(edge, "e_predicate", c["predicate"])
            data(edge, "e_status", c["status"])
            data(edge, "e_confidence", str(c["confidence"]))
            data(edge, "e_valid_from", c.get("valid_from"))
            data(edge, "e_claim_json", c)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def from_graphml(self, payload: bytes) -> dict[str, int]:
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise InvalidInput("not valid GraphML") from exc
        ns = {"g": GRAPHML_NS}
        keymap = {k.get("id"): k.get("attr.name") for k in root.findall("g:key", ns)}

        def fields(el: ET.Element) -> dict[str, str]:
            return {keymap[d.get("key")]: d.text or "" for d in el.findall("g:data", ns)}

        entities, claims = [], []
        for node in root.iter(f"{{{GRAPHML_NS}}}node"):
            f = fields(node)
            if "entity_json" not in f:
                raise InvalidInput("not a Folio GraphML export (missing entity_json)")
            try:
                entities.append(json.loads(f["entity_json"]))
                claims += json.loads(f.get("attribute_claims") or "[]")
            except (ValueError, TypeError) as exc:
                raise InvalidInput("invalid GraphML node data") from exc
        for edge in root.iter(f"{{{GRAPHML_NS}}}edge"):
            try:
                claims.append(json.loads(fields(edge)["claim_json"]))
            except (ValueError, TypeError, KeyError) as exc:
                raise InvalidInput("invalid GraphML edge data") from exc
        self._validate_rows("entities", entities)
        self._validate_rows("claims", claims)
        try:
            with self.kdb.transaction() as session:
                self._ensure_empty(session)
                if entities:
                    self.kdb["entities"].insert_many(entities, session=session)
                if claims:
                    self.kdb["claims"].insert_many(claims, session=session)
        except WriteConflict as exc:
            raise InvalidInput("import conflicts with existing records; nothing was imported") from exc
        self._imported(["entities", "claims"])
        return {"entities": len(entities), "claims": len(claims)}

    # --- Markdown -------------------------------------------------------------------------

    def to_markdown(self) -> str:
        entities = {e["_id"]: e for e in self.kdb["entities"].find({"status": {"$nin": ["merged", "rejected"]}}).sort([("type", 1), ("name", 1)])}
        sources = {s["_id"]: s["path"] for s in self.kdb["sources"].find({}, {"path": 1})}
        claims: dict[str, list[dict[str, Any]]] = {}
        for c in self.kdb["claims"].find({"status": {"$ne": "rejected"}, "predicate": {"$ne": MENTIONS}}).sort("valid_from", 1):
            claims.setdefault(c["subject_id"], []).append(c)

        def where(ev: dict[str, Any]) -> str:
            loc = ev["locator"]
            name = Path(sources.get(ev.get("source_id") or "", "")).name or "voice label"
            if loc["kind"] == "page":
                return f"{name} p.{loc.get('page')}"
            if loc["kind"] == "time":
                s = int(loc.get("start") or 0)
                return f"{name} @{s // 60}:{s % 60:02d}"
            if loc["kind"] == "text":
                return f"{name} L{loc.get('line_start')}"
            return name

        lines = ["# Folio export", "", f"_Exported {utcnow()}_", ""]
        current_type = None
        for e in entities.values():
            if e["type"] != current_type:
                current_type = e["type"]
                lines += [f"## {current_type}", ""]
            lines.append(f"### {e['name']}")
            other = [a["alias"] for a in e.get("aliases", []) if a["alias"] != e["name"]]
            if other:
                lines.append(f"_Also known as: {', '.join(other)}_")
            for c in claims.get(e["_id"], []):
                mark = "✓" if c["status"] == "verified" else "?"
                if c["predicate"] == REPRESENTED_BY:
                    text = f"file: {sources.get(c['value'], c['value'])}"
                elif c["kind"] == "relation":
                    text = f"{c['predicate'].replace('_', ' ')} → {entities.get(c['object_id'], {'name': c['object_id']})['name']}"
                else:
                    text = f"{c['predicate'].replace('_', ' ')}: {c['value']}"
                when = f" ({c['valid_from']})" if c.get("valid_from") and c["predicate"] != "mentioned" else ""
                refs = "; ".join(where(ev) for ev in c.get("evidence", []))
                lines.append(f"- {mark} {text}{when}" + (f" — _{refs}_" if refs else ""))
            lines.append("")
        return "\n".join(lines)

    # --- CSV ------------------------------------------------------------------------------

    def to_csv_zip(self) -> bytes:
        entities = self._docs("entities")
        claims = self._docs("claims")
        tables = {
            "entities.csv": [{"id": e["_id"], "type": e["type"], "name": e["name"], "status": e["status"],
                              "created_by": e["created_by"], "merged_into": e.get("merged_into"),
                              "created_at": e["created_at"]} for e in entities],
            "aliases.csv": [{"entity_id": e["_id"], **a} for e in entities for a in e.get("aliases", [])],
            "claims.csv": [{"id": c["_id"], "subject_id": c["subject_id"], "predicate": c["predicate"],
                            "kind": c["kind"], "value": json.dumps(c.get("value"), ensure_ascii=False),
                            "object_id": c.get("object_id"), "valid_from": c.get("valid_from"),
                            "confidence": c["confidence"], "status": c["status"],
                            "extractor": json.dumps(c["extractor"]), "created_at": c["created_at"]} for c in claims],
            "evidence.csv": [{"claim_id": c["_id"], "id": ev["id"], "source_id": ev.get("source_id"),
                              "locator": json.dumps(ev["locator"]), "quote": ev["quote"]}
                             for c in claims for ev in c.get("evidence", [])],
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, rows in tables.items():
                s = io.StringIO()
                if rows:
                    w = csv.DictWriter(s, fieldnames=list(rows[0]))
                    w.writeheader()
                    w.writerows(rows)
                z.writestr(name, s.getvalue())
        return buf.getvalue()
