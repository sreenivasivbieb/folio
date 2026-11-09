"""Voice/typed labels end to end: capture -> transcript -> plan preview -> answer -> commit.

Nothing touches the knowledge graph until the user confirms the preview (FR-3). On confirm the
whole plan is applied as one ledger group by actor ``voice``, so one Ctrl+Z undoes it.
The label (transcript + audio) is the evidence of every claim it creates.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ..domain.errors import Conflict, InvalidInput, NotFound, Unavailable
from ..domain.ids import new_id
from ..domain.models import ClaimStatus, EntityStatus, Extractor, Label
from ..domain.schema import REPRESENTED_BY
from ..knowledge import KnowledgeService
from ..learning import CorrectionStore
from ..ledger import Ledger
from ..providers.privacy import ensure_allowed
from ..providers.stt.base import Transcriber
from ..store import repo
from ..store.index_db import IndexDB, utcnow
from ..store.local import KnowledgeDB
from .label_parser import LabelContext, RuleLabelParser, answer_question
from .recorder import MicRecorder


class LabelService:
    def __init__(self, *, kdb: KnowledgeDB, index: IndexDB, ledger: Ledger, knowledge: KnowledgeService,
                 learning: CorrectionStore, transcriber: Transcriber, audio_dir: Path) -> None:
        self.kdb = kdb
        self.index = index
        self.ledger = ledger
        self.knowledge = knowledge
        self.learning = learning
        self.transcriber = transcriber
        self.audio_dir = audio_dir
        self.parser = RuleLabelParser()
        self.recorder = MicRecorder()
        self._target: tuple[str, list[str]] = ("none", [])
        self._lock = threading.Lock()

    # --- capture --------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        mic_ok, mic_reason = MicRecorder.available()
        installed = self.transcriber.installed()
        return {
            "recording": self.recorder.recording,
            "microphone": mic_ok, "microphone_detail": mic_reason,
            "speech_model": self.transcriber.model_id,
            "speech_available": installed,
            "speech_downloadable": hasattr(self.transcriber, "download") and not installed,
            "speech_size_mb": int(getattr(self.transcriber, "size_mb", 0)),
        }

    def start(self, target_kind: str, target_ids: list[str]) -> None:
        if not self.transcriber.installed():
            raise Unavailable("the speech model is not downloaded yet — download it in Settings, or type the label")
        with self._lock:
            self._target = (target_kind, target_ids)
            self.recorder.start()

    def stop(self) -> Label:
        label_id = new_id("label")
        audio = self.audio_dir / f"{label_id}.wav"
        duration = self.recorder.stop(audio)
        if duration < 0.3:
            audio.unlink(missing_ok=True)
            raise InvalidInput("recording too short")
        ensure_allowed(self.kdb, self.transcriber)
        segments = self.transcriber.transcribe(audio, prompt=self.learning.vocabulary_prompt())
        transcript = " ".join(s.text for s in segments).strip()
        if not transcript:
            raise InvalidInput("no speech detected")
        kind, ids = self._target
        return self.preview(transcript, kind, ids, audio_path=str(audio), label_id=label_id)

    def cancel_recording(self) -> None:
        self.recorder.cancel()

    # --- plan -----------------------------------------------------------------------------

    def _context(self, target_kind: str, target_ids: list[str]) -> LabelContext:
        _v, schema = self.knowledge.schema()
        ctx = LabelContext(target_kind=target_kind, target_ids=target_ids, schema=schema,
                           gazetteer=self.learning.gazetteer(include_rejected=True),
                           known_types=self.knowledge.known_types())
        if target_kind == "chunk" and target_ids:
            chunk = repo.get_chunk(self.index.reader(), target_ids[0])
            if chunk is None:
                raise NotFound("chunk not found")
            target_kind, target_ids = "source", [chunk.source_id]
            ctx.target_kind, ctx.target_ids = "chunk", target_ids
        if target_kind == "source" and target_ids:
            src = repo.get_source(self.kdb, target_ids[0])
            if src is None:
                raise NotFound("source not found")
            ctx.source_id, ctx.source_name = src.id, Path(src.path).name
            for c in self.kdb["claims"].find({"predicate": REPRESENTED_BY, "value": src.id, "status": {"$ne": "rejected"}}):
                e = self.kdb["entities"].find_one({"_id": c["subject_id"], "status": {"$nin": ["merged", "rejected"]}})
                if e and (ctx.source_entity is None or ctx.source_entity["type"] == "Document"):
                    ctx.source_entity = {"id": e["_id"], "name": e["name"], "type": e["type"]}
        if target_kind == "entity":
            ents = repo.get_entities(self.kdb, target_ids)
            missing = set(target_ids) - set(ents)
            if missing:
                raise NotFound(f"entities not found: {sorted(missing)}")
            ctx.entities = {k: v.model_dump() for k, v in ents.items()}
        if target_kind == "claim":
            for cid in target_ids:
                c = repo.get_claim(self.kdb, cid)
                if c is None:
                    raise NotFound(f"claim {cid} not found")
                ents = repo.get_entities(self.kdb, [x for x in (c.subject_id, c.object_id) if x])
                ctx.claims[cid] = {
                    "kind": c.kind.value,
                    "subject": ents[c.subject_id].model_dump(),
                    "object": ents[c.object_id].model_dump() if c.object_id else None,
                }
        return ctx

    def preview(self, transcript: str, target_kind: str, target_ids: list[str], *,
                audio_path: str | None = None, label_id: str | None = None) -> Label:
        transcript = transcript.strip()
        if not transcript:
            raise InvalidInput("label is empty")
        ctx = self._context(target_kind, target_ids)
        parsed = self.parser.parse(transcript, ctx)
        now = utcnow()
        with self.ledger.group("system", "label.preview", transcript[:80]) as tx:
            tx.insert("labels", {
                "id": label_id or new_id("label"), "transcript": transcript, "audio_path": audio_path,
                "target_kind": target_kind, "target_ids": target_ids, "parsed": parsed,
                "status": "preview", "created_at": now, "updated_at": now,
            })
            lid = tx.changed[0][1]
        return repo.get_label(self.kdb, lid)  # type: ignore[return-value]

    def answer(self, label_id: str, question_id: str, value: str) -> Label:
        label = self._open_label(label_id)
        parsed = answer_question(label.parsed, question_id, value)
        with self.ledger.group("system", "label.answer") as tx:
            tx.update("labels", label_id, {"parsed": parsed})
        return repo.get_label(self.kdb, label_id)  # type: ignore[return-value]

    def cancel(self, label_id: str) -> Label:
        self._open_label(label_id)
        with self.ledger.group("system", "label.cancel") as tx:
            tx.update("labels", label_id, {"status": "cancelled"})
        return repo.get_label(self.kdb, label_id)  # type: ignore[return-value]

    def _open_label(self, label_id: str) -> Label:
        label = repo.get_label(self.kdb, label_id)
        if label is None:
            raise NotFound(f"label {label_id} not found")
        if label.status != "preview":
            raise Conflict(f"label is already {label.status}")
        return label

    # --- commit ---------------------------------------------------------------------------

    def confirm(self, label_id: str) -> Label:
        label = self._open_label(label_id)
        parsed = label.parsed
        if parsed["questions"]:
            raise Conflict("answer the open questions first")
        if not parsed["ops"]:
            raise InvalidInput("nothing to apply")
        source_id = None
        if label.target_kind == "source" and label.target_ids:
            source_id = label.target_ids[0]
        elif label.target_kind == "chunk" and label.target_ids:
            chunk = repo.get_chunk(self.index.reader(), label.target_ids[0])
            source_id = chunk.source_id if chunk else None
        evidence = [{"source_id": source_id, "locator": {"kind": "label", "label_id": label.id},
                     "quote": label.transcript, "label_id": label.id}]
        voice = Extractor(kind="voice")
        created: list[str] = []
        with self.ledger.group("voice", "label.apply", label.transcript[:80]) as tx:
            ids: dict[str, str] = {}

            def entity(ref_key: str) -> str:
                if ref_key in ids:
                    return ids[ref_key]
                ref = parsed["refs"][ref_key]
                if ref.get("entity_id"):
                    ids[ref_key] = ref["entity_id"]
                else:
                    if not ref.get("type"):
                        raise Conflict(f"type of “{ref['name']}” is unknown")
                    row = self.knowledge.create_entity_tx(tx, ref["type"], ref["name"], actor="voice",
                                                          status=EntityStatus.VERIFIED)
                    ids[ref_key] = row["id"]
                return ids[ref_key]

            def claim(**kw: Any) -> None:
                cid, _ = self.knowledge.add_claim_tx(tx, status=ClaimStatus.VERIFIED, extractor=voice,
                                                     evidence=evidence, label_id=label.id, **kw)
                if cid:
                    created.append(cid)

            for op in parsed["ops"]:
                kind = op["op"]
                if kind == "represent":
                    claim(subject_id=entity(op["entity"]), predicate=REPRESENTED_BY, value=op["source_id"])
                elif kind == "attribute":
                    claim(subject_id=entity(op["entity"]), predicate=op["attribute"], value=op["value"],
                          valid_from=op["value"] if op.get("dated") else None)
                elif kind == "relation":
                    claim(subject_id=entity(op["subject"]), predicate=op["predicate"],
                          object_id=entity(op["object"]))
                elif kind == "claim_status":
                    for cid in op["claim_ids"]:
                        tx.update("claims", cid, {"status": op["status"], "needs_review": False})
                elif kind == "entity_status":
                    for eid in op["entity_ids"]:
                        self.knowledge.update_entity_tx(tx, eid, status=EntityStatus(op["status"]))
                elif kind == "retype":
                    self.knowledge.update_entity_tx(tx, entity(op["entity"]), type=op["type"])
                elif kind == "alias":
                    self.knowledge.add_alias_tx(tx, entity(op["entity"]), op["alias"], origin="user")
                elif kind in ("merge", "merge_refs"):
                    targets = op.get("entity_ids") or [entity(r) for r in op["refs"]]
                    for other in targets[1:]:
                        self.knowledge.merge_entities(targets[0], other, actor="voice")
            # Naming an auto-extracted entity in a label confirms that it is real.
            for eid in set(ids.values()):
                row = tx.get("entities", eid)
                if row and row["status"] == EntityStatus.AUTO:
                    tx.update("entities", eid, {"status": EntityStatus.VERIFIED.value})
            tx.update("labels", label.id, {
                "status": "committed",
                "parsed": {**parsed, "created_claims": created, "entity_ids": ids},
            })
        return repo.get_label(self.kdb, label.id)  # type: ignore[return-value]

    def list(self, limit: int = 50) -> list[Label]:
        return repo.list_labels(self.kdb, limit)

    def audio_path(self, label_id: str) -> Path:
        label = repo.get_label(self.kdb, label_id)
        if label is None or not label.audio_path or not Path(label.audio_path).exists():
            raise NotFound("no audio for this label")
        return Path(label.audio_path)

