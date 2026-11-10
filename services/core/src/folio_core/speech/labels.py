"""Voice/typed labels end to end: capture -> transcript -> plan preview -> answer -> commit.

Nothing touches the knowledge graph until the user confirms the preview (FR-3). On confirm the
whole plan is applied as one ledger group by actor ``voice``, so one Ctrl+Z undoes it.
The label (transcript + audio) is the evidence of every claim it creates.
"""

from __future__ import annotations

import threading
import time
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
from .llm_label_parser import LLMLabelParser
from .recorder import MicRecorder

STATUS_TTL_S = 15.0
BEAM_SIZE = 3  # short commands: near-greedy decoding keeps end-of-speech -> preview fast


NOTHING_TO_APPLY = ("nothing to apply — select a file, person or project to describe it, "
                    "or say a fact such as “Priya works at Acme”")

class LabelService:
    def __init__(self, *, kdb: KnowledgeDB, index: IndexDB, ledger: Ledger, knowledge: KnowledgeService,
                 learning: CorrectionStore, transcriber: Transcriber, audio_dir: Path,
                 llm: Any = None) -> None:
        self.kdb = kdb
        self.index = index
        self.ledger = ledger
        self.knowledge = knowledge
        self.learning = learning
        self.transcriber = transcriber
        self.audio_dir = audio_dir
        self.rules = RuleLabelParser()
        self.llm = llm
        self.recorder = MicRecorder()
        self._target: tuple[str, list[str]] = ("none", [])
        self.focus: tuple[str, list[str]] = ("none", [])  # what the UI has selected right now
        self._lock = threading.Lock()
        self._probe: tuple[float, tuple[bool, str, bool, bool]] | None = None

    # --- capture --------------------------------------------------------------------------

    def refresh_status(self) -> None:
        """Forget the cached device/model probe (after a download, a settings change, or a start)."""
        self._probe = None

    def _probed(self) -> tuple[bool, str, bool, bool]:
        # The status endpoint is polled by the UI. Querying audio devices and looking the speech
        # model up can take seconds (more under indexing load), which made /api/status slow
        # enough for the UI's startup check to time out. Cache briefly.
        now = time.monotonic()
        if self._probe is None or now - self._probe[0] > STATUS_TTL_S:
            mic_ok, mic_reason = MicRecorder.available()
            installed = self.transcriber.installed()
            local_check = getattr(self.transcriber, "local_installed", None)
            local = bool(local_check()) if callable(local_check) else installed
            self._probe = (now, (mic_ok, mic_reason, installed, local))
        return self._probe[1]

    def status(self) -> dict[str, Any]:
        mic_ok, mic_reason, installed, local = self._probed()
        return {
            "recording": self.recorder.recording,
            "microphone": mic_ok, "microphone_detail": mic_reason,
            "speech_model": self.transcriber.model_id,
            "speech_available": installed,
            "speech_engine": "none" if not installed else ("local" if local else "cloud"),
            # Offline speech can still be downloaded when the cloud provider handles speech.
            "speech_downloadable": hasattr(self.transcriber, "download") and not local,
            "speech_size_mb": int(getattr(self.transcriber, "size_mb", 0)),
        }

    def start(self, target_kind: str, target_ids: list[str]) -> None:
        self.refresh_status()
        if not self.transcriber.installed():
            raise Unavailable("voice is not set up — connect Groq or OpenAI in Settings → AI model, "
                              "download the offline speech model in Settings → Voice, or type the label")
        if target_kind == "none":  # e.g. a desktop hotkey: label whatever the UI has selected
            target_kind, target_ids = self.focus
        with self._lock:
            self._target = (target_kind, target_ids)
            self.recorder.start()

    def stop_text(self) -> str:
        """Stop recording and return English text only (Hindi/Hinglish are translated) — for a
        drop's label box, where the user reviews the words before organizing."""
        audio = self.audio_dir / f"{new_id('label')}.wav"
        try:
            duration = self.recorder.stop(audio)
            if duration < 0.3:
                raise InvalidInput("recording too short")
            ensure_allowed(self.kdb, self.transcriber)
            segments = self.transcriber.transcribe(audio, prompt=self.learning.vocabulary_prompt(),
                                                   task="translate", beam_size=BEAM_SIZE)
        finally:
            audio.unlink(missing_ok=True)
        text = " ".join(s.text for s in segments).strip()
        if not text:
            raise InvalidInput("no speech detected — hold the button while you speak")
        return text

    def stop(self) -> Label:
        label_id = new_id("label")
        audio = self.audio_dir / f"{label_id}.wav"
        duration = self.recorder.stop(audio)
        if duration < 0.3:
            audio.unlink(missing_ok=True)
            raise InvalidInput("recording too short")
        ensure_allowed(self.kdb, self.transcriber)
        # Labels are always turned into English (Whisper's offline translate mode), so Hindi or
        # Hinglish speech reaches the English label grammar. The audio stays as evidence.
        segments = self.transcriber.transcribe(audio, prompt=self.learning.vocabulary_prompt(),
                                               task="translate", beam_size=BEAM_SIZE)
        transcript = " ".join(s.text for s in segments).strip()
        if not transcript:
            audio.unlink(missing_ok=True)
            raise InvalidInput("no speech detected — hold the button while you speak")
        kind, ids = self._target
        return self.preview(transcript, kind, ids, audio_path=str(audio), label_id=label_id)

    def cancel_recording(self) -> None:
        self.recorder.cancel()

    # --- plan -----------------------------------------------------------------------------

    def _parse(self, transcript: str, ctx: LabelContext) -> dict[str, Any]:
        """The connected model understands free-form labels; the rule grammar is the offline
        default and the fallback. Cloud models are only used when cloud is enabled."""
        if self.llm is not None and getattr(self.llm, "configured", False):
            try:
                ensure_allowed(self.kdb, self.llm)
            except Exception:
                return {**self.rules.parse(transcript, ctx), "engine": "rules (cloud AI is off)"}
            return LLMLabelParser(self.llm, self.rules).parse(transcript, ctx)
        return {**self.rules.parse(transcript, ctx), "engine": "rules"}

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
        parsed = self._parse(transcript, ctx)
        now = utcnow()
        with self.ledger.group("system", "label.preview", transcript[:80]) as tx:
            tx.insert("labels", {
                "id": label_id or new_id("label"), "transcript": transcript, "audio_path": audio_path,
                "target_kind": target_kind, "target_ids": target_ids, "parsed": parsed,
                "status": "preview", "created_at": now, "updated_at": now,
            })
            lid = tx.changed[0][1]
        return repo.get_label(self.kdb, lid)  # type: ignore[return-value]

    def revise(self, label_id: str, transcript: str) -> Label:
        """Fix what the speech model misheard ("PREA" -> "Priya") and re-plan. The audio stays."""
        label = self._open_label(label_id)
        transcript = transcript.strip()
        if not transcript:
            raise InvalidInput("label is empty")
        parsed = self._parse(transcript, self._context(label.target_kind, label.target_ids))
        with self.ledger.group("system", "label.revise", transcript[:80]) as tx:
            tx.update("labels", label_id, {"transcript": transcript, "parsed": parsed})
        return repo.get_label(self.kdb, label_id)  # type: ignore[return-value]

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
            raise InvalidInput(NOTHING_TO_APPLY)
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

