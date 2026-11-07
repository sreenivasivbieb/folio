from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ..domain.errors import Conflict, InvalidInput
from ..domain.schema import MENTIONS, REPRESENTED_BY
from ..realtime import Bus
from ..store.db import Database, loads, utcnow

FORMAT = "folio.v1"
DURABLE_TABLES = ["settings", "schema_versions", "roots", "sources", "entities", "aliases", "claims",
                  "evidence", "labels", "event_groups", "events"]
GRAPHML_NS = "http://graphml.graphdrawing.org/xmlns"
ENTITY_COLS = ["id", "type", "name", "status", "created_by", "merged_into", "created_at", "updated_at"]


class Exporter:
    def __init__(self, db: Database, bus: Bus) -> None:
        self.db = db
        self.bus = bus

    def _rows(self, table: str) -> list[dict[str, Any]]:
        order = "seq" if table in ("events", "event_groups") else "rowid"
        return [dict(r) for r in self.db.reader().execute(f"SELECT * FROM {table} ORDER BY {order}")]

    def _ensure_empty(self) -> None:
        n = self.db.reader().execute("SELECT (SELECT COUNT(*) FROM entities) + (SELECT COUNT(*) FROM claims)").fetchone()[0]
        if n:
            raise Conflict("import needs an empty project (this one already has entities or claims)")

    # --- JSON (lossless) ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {"format": FORMAT, "exported_at": utcnow(),
                **{t: self._rows(t) for t in DURABLE_TABLES}}

    def from_json(self, data: dict[str, Any]) -> dict[str, int]:
        if data.get("format") != FORMAT:
            raise InvalidInput(f"not a {FORMAT} export")
        self._ensure_empty()
        counts: dict[str, int] = {}
        with self.db.write() as conn:
            conn.execute("DELETE FROM schema_versions")  # replaced by the imported versions
            conn.execute("DELETE FROM settings")
            for table in DURABLE_TABLES:
                rows = data.get(table, [])
                ledger = table in ("events", "event_groups")
                for row in rows:
                    # The ledger is append-only: imported events are appended after this
                    # project's own (new sequence numbers, same ids and order).
                    cols = [c for c in row if not (ledger and c == "seq")]
                    verb = "INSERT OR IGNORE" if ledger else "INSERT OR REPLACE"
                    conn.execute(
                        f"{verb} INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [row[c] for c in cols],
                    )
                counts[table] = len(rows)
            # Sources must be re-indexed on this machine: derived data is not exported.
            conn.execute("UPDATE sources SET indexed_hash = NULL, status = 'pending' WHERE status != 'forgotten'")
        self.bus.publish({"type": "ledger", "action": "import", "tables": DURABLE_TABLES, "rows": []})
        return counts

    # --- GraphML --------------------------------------------------------------------------

    def to_graphml(self) -> bytes:
        ET.register_namespace("", GRAPHML_NS)
        root = ET.Element(f"{{{GRAPHML_NS}}}graphml")
        node_keys = [*ENTITY_COLS[1:], "aliases", "attribute_claims"]
        edge_keys = ["claim_id", "predicate", "status", "confidence", "valid_from", "valid_to",
                     "extractor", "fingerprint", "label_id", "needs_review", "schema_version",
                     "created_at", "updated_at", "evidence"]
        for k in node_keys:
            ET.SubElement(root, f"{{{GRAPHML_NS}}}key", id=f"n_{k}", attrib={"for": "node", "attr.name": k, "attr.type": "string"})
        for k in edge_keys:
            ET.SubElement(root, f"{{{GRAPHML_NS}}}key", id=f"e_{k}", attrib={"for": "edge", "attr.name": k, "attr.type": "string"})
        graph = ET.SubElement(root, f"{{{GRAPHML_NS}}}graph", id="folio", edgedefault="directed")

        aliases: dict[str, list[dict[str, Any]]] = {}
        for a in self._rows("aliases"):
            aliases.setdefault(a["entity_id"], []).append(a)
        evidence: dict[str, list[dict[str, Any]]] = {}
        for ev in self._rows("evidence"):
            evidence.setdefault(ev["claim_id"], []).append(ev)
        claims = self._rows("claims")
        attr_claims: dict[str, list[dict[str, Any]]] = {}
        for c in claims:
            if c["kind"] == "attribute":
                attr_claims.setdefault(c["subject_id"], []).append({**c, "evidence": evidence.get(c["id"], [])})

        def data(parent: ET.Element, key: str, value: Any) -> None:
            if value is None:
                return
            d = ET.SubElement(parent, f"{{{GRAPHML_NS}}}data", key=key)
            d.text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

        for e in self._rows("entities"):
            node = ET.SubElement(graph, f"{{{GRAPHML_NS}}}node", id=e["id"])
            for k in ENTITY_COLS[1:]:
                data(node, f"n_{k}", e[k])
            data(node, "n_aliases", aliases.get(e["id"], []))
            data(node, "n_attribute_claims", attr_claims.get(e["id"], []))
        for c in claims:
            if c["kind"] != "relation":
                continue
            edge = ET.SubElement(graph, f"{{{GRAPHML_NS}}}edge", id=c["id"], source=c["subject_id"], target=c["object_id"])
            data(edge, "e_claim_id", c["id"])
            for k in edge_keys[1:-1]:
                data(edge, f"e_{k}", c[k] if not isinstance(c[k], (int, float)) else json.dumps(c[k]))
            data(edge, "e_evidence", evidence.get(c["id"], []))
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def from_graphml(self, payload: bytes) -> dict[str, int]:
        self._ensure_empty()
        root = ET.fromstring(payload)
        ns = {"g": GRAPHML_NS}
        keymap = {k.get("id"): k.get("attr.name") for k in root.findall("g:key", ns)}

        def fields(el: ET.Element) -> dict[str, str]:
            return {keymap[d.get("key")]: d.text or "" for d in el.findall("g:data", ns)}

        counts = {"entities": 0, "claims": 0, "evidence": 0, "aliases": 0}
        with self.db.write() as conn:
            def insert(table: str, row: dict[str, Any]) -> None:
                cols = list(row)
                conn.execute(f"INSERT OR REPLACE INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             [row[c] for c in cols])
                counts[table] = counts.get(table, 0) + 1

            def insert_claim(c: dict[str, Any]) -> None:
                ev = c.pop("evidence", [])
                insert("claims", c)
                for e in ev:
                    insert("evidence", e)

            for node in root.iter(f"{{{GRAPHML_NS}}}node"):
                f = fields(node)
                insert("entities", {"id": node.get("id"), **{k: f.get(k) or None for k in ENTITY_COLS[1:]}})
                for a in json.loads(f.get("aliases") or "[]"):
                    insert("aliases", a)
                for c in json.loads(f.get("attribute_claims") or "[]"):
                    insert_claim(c)
            for edge in root.iter(f"{{{GRAPHML_NS}}}edge"):
                f = fields(edge)

                def num(k: str, f: dict[str, str] = f) -> Any:
                    return json.loads(f[k]) if f.get(k) else None
                insert_claim({
                    "id": f["claim_id"], "subject_id": edge.get("source"), "object_id": edge.get("target"),
                    "kind": "relation", "value": None, "predicate": f["predicate"], "status": f["status"],
                    "confidence": num("confidence"), "valid_from": f.get("valid_from"),
                    "valid_to": f.get("valid_to"), "extractor": f["extractor"],
                    "fingerprint": f["fingerprint"], "label_id": f.get("label_id"),
                    "needs_review": num("needs_review") or 0, "schema_version": num("schema_version"),
                    "created_at": f["created_at"], "updated_at": f["updated_at"],
                    "evidence": json.loads(f.get("evidence") or "[]"),
                })
        self.bus.publish({"type": "ledger", "action": "import", "tables": ["entities", "claims"], "rows": []})
        return counts

    # --- Markdown -------------------------------------------------------------------------

    def to_markdown(self) -> str:
        conn = self.db.reader()
        entities = {r["id"]: dict(r) for r in conn.execute(
            "SELECT * FROM entities WHERE status NOT IN ('merged', 'rejected') ORDER BY type, name")}
        sources = {r["id"]: r["path"] for r in conn.execute("SELECT id, path FROM sources")}
        aliases: dict[str, list[str]] = {}
        for r in conn.execute("SELECT entity_id, alias FROM aliases"):
            aliases.setdefault(r[0], []).append(r[1])
        evidence: dict[str, list[dict[str, Any]]] = {}
        for r in conn.execute("SELECT * FROM evidence"):
            evidence.setdefault(r["claim_id"], []).append(dict(r))
        claims: dict[str, list[dict[str, Any]]] = {}
        for r in conn.execute("SELECT * FROM claims WHERE status != 'rejected' AND predicate != ? ORDER BY valid_from", (MENTIONS,)):
            claims.setdefault(r["subject_id"], []).append(dict(r))

        def where(ev: dict[str, Any]) -> str:
            loc = loads(ev["locator"])
            name = Path(sources.get(ev["source_id"], "")).name or "voice label"
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
            other = [a for a in aliases.get(e["id"], []) if a != e["name"]]
            if other:
                lines.append(f"_Also known as: {', '.join(other)}_")
            for c in claims.get(e["id"], []):
                mark = "✓" if c["status"] == "verified" else "?"
                if c["predicate"] == REPRESENTED_BY:
                    text = f"file: {sources.get(loads(c['value']), loads(c['value']))}"
                elif c["kind"] == "relation":
                    obj = entities.get(c["object_id"], {"name": c["object_id"]})
                    text = f"{c['predicate']} → {obj['name']}"
                else:
                    text = f"{c['predicate']}: {loads(c['value'])}"
                when = f" ({c['valid_from']})" if c["valid_from"] and c["predicate"] != "mentioned" else ""
                refs = "; ".join(where(ev) for ev in evidence.get(c["id"], []))
                lines.append(f"- {mark} {text}{when}" + (f" — _{refs}_" if refs else ""))
            lines.append("")
        return "\n".join(lines)

    # --- CSV ------------------------------------------------------------------------------

    def to_csv_zip(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for table in ("entities", "aliases", "claims", "evidence"):
                rows = self._rows(table)
                s = io.StringIO()
                if rows:
                    w = csv.DictWriter(s, fieldnames=list(rows[0]))
                    w.writeheader()
                    w.writerows(rows)
                z.writestr(f"{table}.csv", s.getvalue())
        return buf.getvalue()
