"""Deterministic, offline extractor (the default until a local LLM is configured — ADR-0005).

It is deliberately conservative and transparent; everything it produces is a *proposal* that
passes through the same validation, resolution and review as LLM output:

1. **Known names** — aliases from the gazetteer (verified/auto entities, merge decisions).
2. **"Name <email>"** — a Person with an email attribute.
3. **Relation phrases from the schema** — "Priya owns the Acme Contract" -> owns(Priya, Acme Contract).
4. **Dates** — "signed on March 3" near a Contract -> signed_on; otherwise a dated ``mentioned``
   claim, which is what the timeline and swimlane views are built from.
5. **Document mentions** — the document mentions every entity found in it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain.schema import MENTIONED, MENTIONS
from ..domain.values import EMAIL, find_dates
from .types import CandidateClaim, CandidateEntity, ExtractionContext, ExtractionOutput

DOCUMENT_REF = "@document"  # resolved by the service to the entity this source represents

_STOP = {
    "the", "a", "an", "this", "that", "these", "those", "it", "we", "i", "he", "she", "they",
    "our", "my", "your", "his", "her", "their", "in", "on", "at", "for", "and", "but", "or", "if",
    "when", "after", "before", "today", "tomorrow", "yesterday", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april", "may",
    "june", "july", "august", "september", "october", "november", "december", "mr", "ms", "dr",
}
# A capitalised word; a dot is allowed only inside it ("J.P.") so "Corp. Next" splits.
_CAP = r"[A-Z](?:[\w&'\-]|\.(?=\w))*"
NAME = rf"{_CAP}(?:[ \t]+(?:{_CAP}|&|of))*"  # never spans lines
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


@dataclass
class _Mention:
    name: str
    type: str
    start: int
    end: int
    known: bool


def _clean_name(raw: str) -> str | None:
    words = raw.strip().strip(".,;:").split()
    while words and words[0].lower().strip("'") in _STOP:
        words.pop(0)
    while words and words[-1].lower() in ("of", "&"):
        words.pop()
    if not words or all(w.lower() in _STOP for w in words):
        return None
    return " ".join(words)


class RuleBasedExtractor:
    model_id = "rules-v1"
    prompt_version = "rules-1"
    uses_llm = False

    def extract(self, text: str, ctx: ExtractionContext) -> ExtractionOutput:
        schema = ctx.schema
        mentions = self._known_mentions(text, ctx)
        entities: dict[tuple[str, str], CandidateEntity] = {}
        claims: list[CandidateClaim] = []

        def add_entity(name: str, etype: str) -> None:
            entities.setdefault((name.lower(), etype), CandidateEntity(name=name, type=etype))

        def type_of(name: str, allowed: list[str]) -> str | None:
            for m in mentions:
                if m.name.lower() == name.lower():
                    return m.type
            concrete = [t for t in allowed if t != "*"] or list(schema.entity_types)
            by_word = schema.type_for_word(name.split()[-1])  # "Acme Contract" -> Contract
            if by_word in concrete:
                return by_word
            return concrete[0] if concrete else None

        # 2. "Name <email>"
        for m in re.finditer(rf"(?P<name>{NAME})\s*[<(\[]\s*(?P<email>{EMAIL.pattern})\s*[>)\]]", text):
            name = _clean_name(m["name"])
            if name and "Person" in schema.entity_types and schema.attribute("Person", "email"):
                add_entity(name, "Person")
                mentions.append(_Mention(name, "Person", m.start(), m.end(), False))
                claims.append(CandidateClaim(subject=name, subject_type="Person", predicate="email",
                                             value=m["email"].lower(), confidence=0.7,
                                             quote=m.group(0)))

        # 3. relation phrases
        phrases = sorted(
            ((p, rel_name, rel) for rel_name, rel in schema.relation_types.items() for p in rel.phrases),
            key=lambda t: -len(t[0]),
        )
        sentences = [(m.start(), m.group(0)) for m in _SENTENCE.finditer(text)]
        for phrase, rel_name, rel in phrases:
            pat = re.compile(rf"(?P<s>{NAME})\s+{re.escape(phrase)}\s+(?:the\s+)?(?P<o>{NAME})")
            for offset, sentence in sentences:
                for m in pat.finditer(sentence):
                    s, o = _clean_name(m["s"]), _clean_name(m["o"])
                    if not s or not o or s.lower() == o.lower():
                        continue
                    st, ot = type_of(s, rel.source), type_of(o, rel.target)
                    if not st or not ot or not schema.relation_allows(rel_name, st, ot):
                        continue
                    add_entity(s, st)
                    add_entity(o, ot)
                    mentions += [_Mention(s, st, offset + m.start("s"), offset + m.end("s"), False),
                                 _Mention(o, ot, offset + m.start("o"), offset + m.end("o"), False)]
                    claims.append(CandidateClaim(subject=s, subject_type=st, predicate=rel_name,
                                                 object=o, object_type=ot, confidence=0.5,
                                                 quote=m.group(0)))

        # Every further occurrence of a newly found name is a mention too.
        taken = [(m.start, m.end) for m in mentions]
        for (_low, etype), ent in entities.items():
            for m in re.finditer(rf"(?<!\w){re.escape(ent.name)}(?!\w)", text):
                if not any(s < m.end() and m.start() < e for s, e in taken):
                    taken.append((m.start(), m.end()))
                    mentions.append(_Mention(ent.name, etype, m.start(), m.end(), False))

        # 4. dates: typed date attributes, else dated mentions
        for sm in _SENTENCE.finditer(text):
            sentence = sm.group(0).strip()
            dates = find_dates(sentence)
            if not dates:
                continue
            in_sentence = [m for m in mentions if sm.start() <= m.start < sm.end()]
            for m in {(x.name, x.type): x for x in in_sentence}.values():
                iso = dates[0][0]
                attr = self._date_attribute(schema, m.type, sentence)
                if attr:
                    claims.append(CandidateClaim(subject=m.name, subject_type=m.type, predicate=attr,
                                                 value=iso, valid_from=iso, confidence=0.55,
                                                 quote=sentence))
                else:
                    claims.append(CandidateClaim(subject=m.name, subject_type=m.type,
                                                 predicate=MENTIONED, value=sentence[:240],
                                                 valid_from=iso, confidence=0.45, quote=sentence))

        # 5. the document mentions everything found in it
        if "Document" in schema.entity_types:
            for m in {(x.name.lower(), x.type): x for x in mentions}.values():
                claims.append(CandidateClaim(
                    subject=DOCUMENT_REF, subject_type="Document", predicate=MENTIONS,
                    object=m.name, object_type=m.type, confidence=0.9 if m.known else 0.6,
                    quote=text[m.start:m.end],
                ))
        return ExtractionOutput(entities=list(entities.values()), claims=claims)

    @staticmethod
    def _known_mentions(text: str, ctx: ExtractionContext) -> list[_Mention]:
        found: list[_Mention] = []
        taken: list[tuple[int, int]] = []
        for entry in ctx.gazetteer:  # longest first
            if len(entry.normalized) < 3 or entry.status == "rejected":
                continue
            for m in re.finditer(rf"(?<!\w){re.escape(entry.alias)}(?!\w)", text, re.I):
                if any(s < m.end() and m.start() < e for s, e in taken):
                    continue
                taken.append((m.start(), m.end()))
                found.append(_Mention(entry.entity_name, entry.entity_type, m.start(), m.end(), True))
        return found

    @staticmethod
    def _date_attribute(schema, entity_type: str, sentence: str) -> str | None:  # type: ignore[no-untyped-def]
        et = schema.entity_types.get(entity_type)
        if not et:
            return None
        low = sentence.lower()
        for name, attr in et.attributes.items():
            if attr.type != "date":
                continue
            for phrase in [name.replace("_", " "), *attr.phrases]:
                if phrase in ("on", "held") and entity_type != "Meeting":
                    continue
                if re.search(rf"\b{re.escape(phrase.lower())}\b", low):
                    return name
        return None
