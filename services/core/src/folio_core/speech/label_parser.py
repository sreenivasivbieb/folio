"""Turn a spoken/typed label into a structured, previewable plan (FR-3).

    "This PDF is the Acme contract, Priya owns it, signed March 3."
    ->  e1 = Contract "Acme contract" (new) — represents this file
        e2 = "Priya" (new; type?)            — question: Person or Organization?
        owns(e2, e1)
        e1.signed_on = 2026-03-03

The parser never guesses on ambiguity: an unknown type or a name matching several entities
becomes a *question* the user answers in the preview before anything is written.

The grammar is English and rule-based (the offline default). The plan format is the contract:
an LLM-backed parser for free-form or mixed-language speech can produce the same structure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..domain.errors import InvalidInput
from ..domain.rules import normalize_name
from ..domain.schema import SchemaDef, canonical_type
from ..domain.values import coerce
from ..learning import GazetteerEntry

PRONOUN = re.compile(
    r"^(?:it|this|that|this one|that one|(?:this|that) (?:pdf|file|document|doc|video|recording|"
    r"image|photo|picture|meeting|contract|deck|one))$", re.I)
_SPLIT_STRONG = re.compile(r"[,;.!?]+")
_SPLIT_AND = re.compile(r"\s+(?:and|but|also)\s+", re.I)
_ARTICLE = re.compile(r"^(?:the|a|an|my|our|your|his|her|their|some)\s+", re.I)
TOPIC_TYPE = "Topic"  # built in, so topic labels work even with an older or custom schema
_THING = r"(?:it|this|that|this one|that one|(?:this|that) (?:pdf|file|document|doc|video|recording|image|photo|picture|meeting|contract|deck|one|folder|note|notes))"
# "tag this as finance", "label it physics", "put this under taxes", "mark this file as work"
_TAG = re.compile(rf"(?:please )?(?:tag|label|mark|categori[sz]e|classify|file|put|save|add)\s+{_THING}"
                  rf"(?:\s+(?:as|under|in|into|with|to|in the|under the))?(?:\s+(?:topic|category|tag|label|folder))?\s*:?\s+(?P<x>.+)", re.I)
# "topic is X", "topics: X", "category: X", "the subject is X", "tags are X"
_TOPIC_IS = re.compile(r"(?:the |its |this )?(?:main )?(?:topic|topics|subject|category|tag|tags|theme|keyword|keywords)"
                       r"(?:\s+(?:is|are|was|=)|\s*:)\s*(?P<x>.+)", re.I)
# "this is about X", "it's related to X", "this file covers X", "about X"
_ABOUT = re.compile(rf"(?:{_THING}(?:'s|\s+is|\s+was|\s+are)?\s+(?:all\s+)?)?"
                    r"(?:about|regarding|related to|relates to|concerning|concerns|covers|on the topic of|on)\s+(?P<x>.+)", re.I)
# a separate list item after a topic: "about taxes, invoices and receipts"
_LIST_ITEM = re.compile(r"(?:the |a |an )?[\w'&+.-]+(?:\s+[\w'&+.-]+){0,3}", re.I)


@dataclass
class LabelContext:
    target_kind: str  # source | chunk | entity | claim | none
    target_ids: list[str]
    schema: SchemaDef
    gazetteer: list[GazetteerEntry]
    source_id: str | None = None
    source_name: str | None = None
    source_entity: dict[str, Any] | None = None  # entity already representing the source
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)  # targeted entities by id
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)  # targeted claims by id
    known_types: list[str] = field(default_factory=list)  # hints + types already in use
    today: date | None = None


class _Plan:
    def __init__(self, ctx: LabelContext) -> None:
        self.ctx = ctx
        self.refs: dict[str, dict[str, Any]] = {}
        self.ops: list[dict[str, Any]] = []
        self.questions: list[dict[str, Any]] = []
        self.unparsed: list[str] = []
        self.focus: str | None = None
        self._by_norm: dict[str, str] = {}
        self._topic_subject: str | None = None  # set after a topic clause; lists continue it
        self._init_focus()

    # --- refs -----------------------------------------------------------------------------

    def _existing_ref(self, entity: dict[str, Any]) -> str:
        for key, ref in self.refs.items():
            if ref.get("entity_id") == entity["id"]:
                return key
        key = f"e{len(self.refs) + 1}"
        self.refs[key] = {"name": entity["name"], "type": entity["type"],
                          "entity_id": entity["id"], "new": False}
        self._by_norm[normalize_name(entity["name"])] = key
        return key

    def _init_focus(self) -> None:
        ctx = self.ctx
        if ctx.target_kind == "entity" and ctx.target_ids:
            self.focus = self._existing_ref(ctx.entities[ctx.target_ids[0]])
        elif ctx.target_kind == "claim" and ctx.target_ids:
            c = ctx.claims[ctx.target_ids[0]]
            thing = c.get("object") if c["kind"] == "relation" else c.get("subject")
            if thing:
                self.focus = self._existing_ref(thing)
        elif ctx.target_kind in ("source", "chunk") and ctx.source_entity:
            self.focus = self._existing_ref(ctx.source_entity)

    def _type_word(self, name: str) -> str | None:
        words = name.split()
        if not words:
            return None
        last = words[-1].lower()
        return self.ctx.schema.type_for_word(last) or next(
            (t for t in self.ctx.known_types if t.lower() == last), None)

    def ref(self, name: str, allowed: list[str] | None = None) -> str:
        """Resolve a spoken name to a ref; may add a question instead of guessing."""
        name = _ARTICLE.sub("", name.strip()).strip(" .")
        if PRONOUN.match(name):
            return self.this_ref()
        norm = normalize_name(name)
        if norm in self._by_norm:
            return self._by_norm[norm]
        concrete = [t for t in (allowed or []) if t != "*"]
        matches = {g.entity_id: g for g in self.ctx.gazetteer
                   if g.normalized == norm and g.status != "rejected"}
        if concrete:
            matches = {k: g for k, g in matches.items() if g.entity_type in concrete} or matches
        key = f"e{len(self.refs) + 1}"
        if len(matches) == 1:
            g = next(iter(matches.values()))
            self.refs[key] = {"name": g.entity_name, "type": g.entity_type,
                              "entity_id": g.entity_id, "new": False}
        elif len(matches) > 1:
            self.refs[key] = {"name": name, "type": None, "entity_id": None, "new": False}
            self.questions.append({
                "id": f"q{len(self.questions) + 1}", "ref": key, "field": "entity_id",
                "text": f"Which “{name}” do you mean?",
                "options": [{"label": f"{g.entity_name} ({g.entity_type})", "value": g.entity_id,
                             "type": g.entity_type} for g in matches.values()],
            })
        else:
            etype = self._type_word(name)
            if etype is None and len(concrete) == 1:
                etype = concrete[0]
            if etype is not None and concrete and etype not in concrete:
                etype = None
            type_options = concrete or self.ctx.known_types or list(self.ctx.schema.entity_types)
            self.refs[key] = {"name": name, "type": etype, "entity_id": None, "new": True,
                              "type_options": type_options}
            partial = self._partial_matches(norm, concrete)
            if partial:
                # Speech often gives a first name: "Priya" may be "Priya Sharma". Ask.
                self.questions.append({
                    "id": f"q{len(self.questions) + 1}", "ref": key, "field": "entity_id",
                    "text": f"Do you mean an existing entity, or a new “{name}”?",
                    "options": [{"label": f"{g.entity_name} ({g.entity_type})", "value": g.entity_id,
                                 "type": g.entity_type} for g in partial]
                               + [{"label": f"New “{name}”", "value": NEW_ENTITY}],
                })
            elif etype is None:
                self.questions.append(_type_question(len(self.questions) + 1, key, name, type_options))
        self._by_norm[norm] = key
        return key

    def _partial_matches(self, norm: str, types: list[str]) -> list[GazetteerEntry]:
        """Live entities whose name starts or ends with the spoken words (word boundary)."""
        if len(norm) < 3:
            return []
        out: dict[str, GazetteerEntry] = {}
        for g in self.ctx.gazetteer:
            if g.status == "rejected" or (types and g.entity_type not in types):
                continue
            if g.normalized != norm and (g.normalized.startswith(norm + " ") or g.normalized.endswith(" " + norm)):
                out.setdefault(g.entity_id, g)
        return list(out.values())[:5]

    def this_ref(self) -> str:
        """'it' / 'this file': the current focus, or the file itself as a Document."""
        if self.focus:
            return self.focus
        if self.ctx.target_kind in ("source", "chunk") and self.ctx.source_name:
            key = self.ref(self.ctx.source_name, ["Document"])
            self.refs[key]["type"] = self.refs[key]["type"] or "Document"
            self.ops.append({"op": "represent", "entity": key, "source_id": self.ctx.source_id})
            self.focus = key
            return key
        raise InvalidInput("nothing is selected for 'it' to refer to")

    # --- clauses --------------------------------------------------------------------------

    def clause(self, original: str) -> None:
        o = original.strip()
        c = o.lower()
        if not c:
            return
        o = re.sub(r"^(?:and|also|plus|then|okay|ok|so|please)\s+", "", o, flags=re.I).strip()
        c = o.lower()
        for handler in (self._status, self._merge, self._topic, self._relation_phrase, self._this_is,
                        self._the_noun_is, self._x_is_its_noun, self._attribute_phrase, self._topic_list_item):
            saved = (len(self.ops), {k: dict(v) for k, v in self.refs.items()}, list(self.questions),
                     self.focus, dict(self._by_norm))
            try:
                if handler(o, c):
                    if handler not in (self._topic, self._topic_list_item):
                        self._topic_subject = None
                    return
            except InvalidInput as exc:
                # A clause applies completely or not at all: drop anything it half-planned.
                n, self.refs, self.questions, self.focus, self._by_norm = saved
                del self.ops[n:]
                self.unparsed.append(f"{o} ({exc})")
                return
        self.unparsed.append(o)

    # --- topics / tags --------------------------------------------------------------------

    def _add_topic(self, subject: str, name: str) -> None:
        name = _ARTICLE.sub("", name.strip().strip(" .:;\"'")).strip()
        if not name or PRONOUN.match(name):
            raise InvalidInput("say which topic")
        key = self.ref(name)
        ref = self.refs[key]
        if ref["new"] and ref["type"] is None:  # a bare topic word is a Topic, not a question
            ref["type"] = TOPIC_TYPE
            self.questions = [q for q in self.questions if not (q["ref"] == key and q["field"] == "type")]
        if not any(op.get("op") == "relation" and op["subject"] == subject and op["object"] == key
                   and op["predicate"] == "about" for op in self.ops):
            self.ops.append({"op": "relation", "subject": subject, "predicate": "about", "object": key})

    def _topic(self, o: str, c: str) -> bool:
        """'tag this as X', 'topic is X', 'this is about X', 'about X' -> about(this, X: Topic).
        Several topics can follow: 'about taxes, invoices and receipts'."""
        m = _TAG.fullmatch(o) or _TOPIC_IS.fullmatch(o)
        if m is None:
            m = _ABOUT.fullmatch(o)
            # "on" alone is too common ("signed on March 3"); only with a leading "this/it".
            if m and re.match(r"on\s", c) :
                return False
        if m is None:
            return False
        subject = self.this_ref()
        for part in re.split(r"\s*(?:,|/|\band\b|&|\bor\b)\s*", m["x"]):
            if part.strip():
                self._add_topic(subject, part)
        self._topic_subject = subject
        return True

    def _topic_list_item(self, o: str, c: str) -> bool:
        """'... about taxes, invoices' — the clause after a topic is another topic."""
        if self._topic_subject is None or not _LIST_ITEM.fullmatch(o):
            return False
        self._add_topic(self._topic_subject, o)
        return True

    def _status(self, o: str, c: str) -> bool:
        reject = re.fullmatch(r"(?:no\s+)?(?:(?:this|that|it)(?:'s| is| was)\s+)?(?:wrong|incorrect|not right|reject(?: (?:this|that|it))?|delete(?: this| that| it)?)", c)
        verify = re.fullmatch(r"(?:yes\s+)?(?:(?:this|that|it)(?:'s| is)\s+)?(?:correct|right|verified|(?:verify|confirm|approve)(?: (?:this|that|it))?)", c)
        if not (reject or verify):
            return False
        status = "rejected" if reject else "verified"
        if self.ctx.target_kind == "claim" and self.ctx.target_ids:
            self.ops.append({"op": "claim_status", "claim_ids": list(self.ctx.target_ids), "status": status})
        elif self.ctx.target_kind == "entity" and self.ctx.target_ids:
            self.ops.append({"op": "entity_status", "entity_ids": list(self.ctx.target_ids), "status": status})
        else:
            raise InvalidInput("select a claim or entity first")
        return True

    def _merge(self, o: str, c: str) -> bool:
        if re.fullmatch(r"merge(?: (?:these|them|those|both))?(?: two| all)?(?: entities)?", c):
            if self.ctx.target_kind != "entity" or len(self.ctx.target_ids) < 2:
                raise InvalidInput("select at least two entities to merge")
            self.ops.append({"op": "merge", "entity_ids": list(self.ctx.target_ids)})
            return True
        m = re.fullmatch(r"merge (?P<a>.+?) (?P<how>and|with|into) (?P<b>.+)", o, re.I)
        if m:
            a, b = self.ref(m["a"]), self.ref(m["b"])
            # The first ref survives. "merge A into B" keeps B; "merge A and/with B" keeps A,
            # like merging a multi-selection in the UI (the first selected entity is kept).
            keep_second = m["how"].lower() == "into"
            self.ops.append({"op": "merge_refs", "refs": [b, a] if keep_second else [a, b]})
            return True
        return False

    def _relation_phrase(self, o: str, c: str) -> bool:
        schema = self.ctx.schema
        phrases = sorted(((p, name, rel) for name, rel in schema.relation_types.items()
                          for p in rel.phrases), key=lambda t: -len(t[0]))
        for phrase, name, rel in phrases:
            m = re.fullmatch(rf"(?P<s>.+?)\s+{re.escape(phrase)}\s+(?P<o>.+)", o, re.I)
            if not m:
                continue
            s = self.ref(m["s"], rel.source)
            ob = self.ref(m["o"], rel.target)
            self.ops.append({"op": "relation", "subject": s, "predicate": name, "object": ob})
            if not PRONOUN.match(m["s"].strip()):
                self.focus = self.focus or ob
            return True
        return False

    def _this_is(self, o: str, c: str) -> bool:
        m = re.fullmatch(r"(?P<pron>(?:this|that|it)(?: \w+)?)(?:'s| is| was)\s+(?P<rest>.+)", o, re.I)
        if not m or not PRONOUN.match(m["pron"]):
            return False
        rest = m["rest"].strip()
        # "it was signed on March 3" sets an attribute; it does not name the thing.
        first = re.match(r"(\w+)(?: (\w+))?", rest.lower())
        if first and any(self._is_attribute_word(w) for w in filter(None, (first[1], first.group(0)))):
            if self._attribute_phrase(rest, rest.lower()):
                return True
            raise InvalidInput(f"“{first[1]}” does not apply to this — say what it is first, e.g. “this is a contract”")
        bare = _ARTICLE.sub("", rest).strip()
        as_type = self.ctx.schema.type_for_word(bare)
        # Open schema: "it is a Course" / "this is an Algorithm" names a *type* even when no hint
        # knows it ("the X" names the thing itself).
        of_form = re.fullmatch(r"(?P<t>[\w-]+(?: [\w-]+)?) (?:of|for|by|from) (?:the )?(?P<n>.+)", bare, re.I)
        if as_type is None and re.match(r"(?:a|an)\s", rest, re.I) and len(bare.split()) <= 3 and not of_form:
            as_type = canonical_type(bare, self.ctx.known_types)
        if as_type is None and of_form and re.match(r"(?:a|an)\s", rest, re.I):
            # "this is a resume of Priya" -> a Resume named "Priya resume", not a type "Resume Of Priya"
            noun = of_form["t"]
            bare = f"{of_form['n']} {noun}"
            if not self.ctx.schema.type_for_word(noun.split()[-1]):
                key = self.ref(bare)
                if self.refs[key]["new"] and self.refs[key]["type"] is None:
                    self.refs[key]["type"] = canonical_type(noun, self.ctx.known_types)
                    self.questions = [q for q in self.questions if not (q["ref"] == key and q["field"] == "type")]
        if as_type:  # "it is a person" -> set/fix the type of the focus
            key = self.this_ref()
            if self.refs[key]["new"]:
                self.refs[key]["type"] = as_type
                self.questions = [q for q in self.questions if not (q["ref"] == key and q["field"] == "type")]
            else:
                self.ops.append({"op": "retype", "entity": key, "type": as_type})
            return True
        # "the contract of Acme" / "the report for Atlas" -> "Acme contract" (type from the noun).
        # Translated Hindi labels ("yeh Acme ka contract hai") come out in this shape.
        m2 = re.fullmatch(r"(?P<t>[\w-]+) (?:of|for) (?:the )?(?P<n>.+)", bare, re.I)
        if m2 and (self.ctx.schema.type_for_word(m2["t"]) or m2["t"].lower() in (t.lower() for t in self.ctx.known_types)):
            bare = f"{m2['n']} {m2['t']}"
        if self.ctx.target_kind in ("source", "chunk") and self.ctx.source_id:
            key = self.ref(bare)
            if not any(op.get("op") == "represent" and op["entity"] == key for op in self.ops):
                self.ops.append({"op": "represent", "entity": key, "source_id": self.ctx.source_id})
            self.focus = key
            return True
        if self.focus:
            self.ops.append({"op": "alias", "entity": self.focus, "alias": bare})
            return True
        return False

    def _the_noun_is(self, o: str, c: str) -> bool:
        m = re.fullmatch(r"(?:the |its |his |her |their )(?P<noun>[\w ]+?) (?:is|was|are|were) (?P<value>.+)", o, re.I)
        if not m:
            return False
        noun, value = m["noun"].lower().strip(), m["value"].strip()
        schema = self.ctx.schema
        for name, rel in schema.relation_types.items():
            if rel.noun and rel.noun == noun:
                subject = self.ref(value, rel.source)
                self.ops.append({"op": "relation", "subject": subject, "predicate": name,
                                 "object": self.this_ref()})
                return True
        attr = self._attribute_for(noun)
        if attr:
            self._add_attribute(attr, value)
            return True
        raise InvalidInput(f"'{noun}' is not an attribute or relation in the schema")

    def _x_is_its_noun(self, o: str, c: str) -> bool:
        """'Priya is its owner' / 'Acme is the party' — the reverse of 'the owner is Priya'
        (common after translating Hindi: 'Priya iski maalik hai')."""
        m = re.fullmatch(r"(?P<x>.+?) (?:is|was|are|were) (?:its|the|his|her|their) (?P<noun>[\w ]+?)(?: of (?:it|this|that|the)(?: [\w ]+)?)?", o, re.I)
        if not m or PRONOUN.match(m["x"].strip()):
            return False
        noun = m["noun"].lower().strip()
        for name, rel in self.ctx.schema.relation_types.items():
            if rel.noun and rel.noun == noun:
                subject = self.ref(m["x"], rel.source)
                self.ops.append({"op": "relation", "subject": subject, "predicate": name, "object": self.this_ref()})
                return True
        attr = self._attribute_for(noun)
        if attr:
            self._add_attribute(attr, m["x"])
            return True
        return False

    def _attribute_phrase(self, o: str, c: str) -> bool:
        m = re.fullmatch(r"(?:it |which )?(?:was |is |were )?(?P<phrase>\w+(?: \w+)??)(?: on| at| for| by| in)? (?P<value>.+)", o, re.I)
        if not m:
            return False
        attr = self._attribute_for(m["phrase"].lower())
        if not attr:
            return False
        self._add_attribute(attr, m["value"])
        return True

    def _is_attribute_word(self, word: str) -> bool:
        return any(word in (aname, aname.replace("_", " "), *[p.lower() for p in a.phrases])
                   for et in self.ctx.schema.entity_types.values() for aname, a in et.attributes.items()
                   if word not in ("on", "title", "value", "status", "role"))

    def _attribute_for(self, word: str) -> tuple[str, str] | None:
        """Find (entity_type, attribute) for a spoken word, preferring the focus entity's type."""
        word = word.strip().lower()
        schema = self.ctx.schema
        focus_type = self.refs[self.focus]["type"] if self.focus else None
        hits = []
        for tname, et in schema.entity_types.items():
            for aname, a in et.attributes.items():
                if word in (aname, aname.replace("_", " "), *[p.lower() for p in a.phrases]):
                    hits.append((tname, aname))
        if focus_type:
            own = [h for h in hits if h[0] == focus_type]
            return own[0] if own else None
        return hits[0] if len(hits) == 1 else None

    def _add_attribute(self, attr: tuple[str, str], raw: str) -> None:
        etype, aname = attr
        key = self.this_ref()
        ref = self.refs[key]
        if ref["type"] is None:  # the attribute tells us the type ("signed ..." -> Contract)
            ref["type"] = etype
            self.questions = [q for q in self.questions if not (q["ref"] == key and q["field"] == "type")]
        a = self.ctx.schema.attribute(ref["type"], aname)
        if a is None:
            raise InvalidInput(f"{ref['type']} has no attribute '{aname}'")
        value = coerce(a.type, raw)
        self.ops.append({"op": "attribute", "entity": key, "attribute": aname, "value": value,
                         "dated": a.type == "date"})

    # --- output ---------------------------------------------------------------------------

    def result(self) -> dict[str, Any]:
        return {"refs": self.refs, "ops": self.ops, "questions": self.questions,
                "unparsed": self.unparsed, "preview": preview_lines(self.refs, self.ops)}


def preview_lines(refs: dict[str, dict[str, Any]], ops: list[dict[str, Any]]) -> list[str]:
    def name(key: str) -> str:
        r = refs[key]
        t = r["type"] or "?"
        return f"“{r['name']}” ({t}{', new' if r['new'] else ''})"

    lines = []
    for op in ops:
        kind = op["op"]
        if kind == "represent":
            lines.append(f"{name(op['entity'])} is this file")
        elif kind == "attribute":
            lines.append(f"{name(op['entity'])} · {op['attribute'].replace('_', ' ')} = {op['value']}")
        elif kind == "relation":
            lines.append(f"{name(op['subject'])} —{op['predicate']}→ {name(op['object'])}")
        elif kind == "claim_status":
            lines.append(f"Mark {len(op['claim_ids'])} claim(s) {op['status']}")
        elif kind == "entity_status":
            lines.append(f"Mark {len(op['entity_ids'])} entit(y/ies) {op['status']}")
        elif kind in ("merge", "merge_refs"):
            n = len(op.get("entity_ids", op.get("refs", [])))
            lines.append(f"Merge {n} entities")
        elif kind == "retype":
            lines.append(f"Change {name(op['entity'])} to {op['type']}")
        elif kind == "alias":
            lines.append(f"Add alias “{op['alias']}” to {name(op['entity'])}")
    return lines


class RuleLabelParser:
    def parse(self, transcript: str, ctx: LabelContext) -> dict[str, Any]:
        plan = _Plan(ctx)
        for segment in _SPLIT_STRONG.split(transcript):
            segment = segment.strip()
            if not segment:
                continue
            if segment.lower().startswith("merge "):
                plan.clause(segment)
                continue
            for clause in _SPLIT_AND.split(segment):
                plan.clause(clause)
        return plan.result()


NEW_ENTITY = "__new__"


def _type_question(n: int, ref: str, name: str, options: list[str]) -> dict[str, Any]:
    return {"id": f"q{n}", "ref": ref, "field": "type", "text": f"What is “{name}”?",
            "options": [{"label": t, "value": t} for t in options]}


def answer_question(parsed: dict[str, Any], question_id: str, value: str) -> dict[str, Any]:
    """Apply the user's answer to a preview question; returns the updated plan."""
    q = next((q for q in parsed["questions"] if q["id"] == question_id), None)
    if q is None:
        raise InvalidInput(f"no question {question_id}")
    allowed = {o["value"]: o for o in q["options"]}
    if value not in allowed and not (q["field"] == "type" and value.strip()):
        raise InvalidInput(f"'{value}' is not one of the options")  # types are open: any name is fine
    ref = parsed["refs"][q["ref"]]
    parsed["questions"] = [x for x in parsed["questions"] if x["id"] != question_id]
    if q["field"] == "type":
        ref["type"] = value
    elif value == NEW_ENTITY:
        ref["new"] = True
        if ref["type"] is None:  # now we need to know what the new entity is
            n = max((int(x["id"][1:]) for x in parsed["questions"]), default=int(question_id[1:])) + 1
            parsed["questions"].append(_type_question(n, q["ref"], ref["name"], ref.get("type_options") or []))
    else:
        ref["entity_id"] = value
        ref["type"] = allowed[value].get("type")
        ref["new"] = False
    parsed["preview"] = preview_lines(parsed["refs"], parsed["ops"])
    return parsed
