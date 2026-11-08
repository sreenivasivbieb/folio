"""Type *hints*: suggested entity types, attributes and relations (open schema).

Folio has no fixed categories: an entity can have any type and a claim any predicate. The hints
only help — colours in the UI, spoken phrases for voice labels ("signed" -> signed_on), value
parsing for known attributes (dates), and examples for the LLM prompt. Unknown types and
predicates are always accepted.

Hints are versioned (every edit stores a new version) so provenance can say which hints a claim
was extracted with. Default packs live in ``folio_core/schema_packs/*.yaml``.
"""

from __future__ import annotations

import re
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, Field

AttrType = Literal["string", "date", "number", "money", "email", "url"]

# Built-in predicates that every schema understands.
REPRESENTED_BY = "represented_by"  # entity -> source file it *is* ("This PDF is the Acme contract")
MENTIONED = "mentioned"  # dated mention of an entity in a source (feeds the timeline)
MENTIONS = "mentions"  # Document -> any entity mentioned in it


class AttributeDef(BaseModel):
    type: AttrType = "string"
    description: str = ""
    multi: bool = False  # single-valued attributes are checked for conflicts
    phrases: list[str] = Field(default_factory=list)  # spoken forms: "signed" -> signed_on


class EntityTypeDef(BaseModel):
    description: str = ""
    color: str = "#888888"
    attributes: dict[str, AttributeDef] = Field(default_factory=dict)
    phrases: list[str] = Field(default_factory=list)  # spoken forms: "contract", "agreement"


class RelationTypeDef(BaseModel):
    description: str = ""
    source: list[str]  # allowed subject types ("*" = any)
    target: list[str]  # allowed object types ("*" = any)
    phrases: list[str] = Field(default_factory=list)  # verb forms: "owns", "is owned by"
    noun: str | None = None  # "the <noun> is X" means relation(X, this): "the owner is Priya"
    dated: bool = False


class SchemaDef(BaseModel):
    name: str
    version: int = 1
    entity_types: dict[str, EntityTypeDef] = Field(default_factory=dict)
    relation_types: dict[str, RelationTypeDef] = Field(default_factory=dict)

    # --- lookups used by extraction and the label parser -------------------------------------

    def relation_allows(self, predicate: str, subject_type: str, object_type: str) -> bool:
        """Whether the *hints* suggest this relation fits these types. Used only to infer a type
        or pick between candidates — never to reject what the user or model stated."""
        rel = self.relation_types.get(predicate)
        if rel is None:
            return True
        return ("*" in rel.source or subject_type in rel.source) and (
            "*" in rel.target or object_type in rel.target
        )

    def attribute(self, entity_type: str, name: str) -> AttributeDef | None:
        et = self.entity_types.get(entity_type)
        return et.attributes.get(name) if et else None

    def type_for_word(self, word: str) -> str | None:
        """Map a spoken/written noun ("contract", "people") to an entity type name."""
        w = word.lower().strip()
        for name, et in self.entity_types.items():
            if w == name.lower() or w in (p.lower() for p in et.phrases):
                return name
        return None

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json", exclude_defaults=False), sort_keys=False)


def load_pack(name: str = "default") -> SchemaDef:
    text = resources.files("folio_core.schema_packs").joinpath(f"{name}.yaml").read_text()
    return SchemaDef.model_validate(yaml.safe_load(text))


def parse_schema_yaml(text: str) -> SchemaDef:
    return SchemaDef.model_validate(yaml.safe_load(text))


_WORDS = re.compile(r"[A-Za-z0-9]+")


def canonical_type(raw: str, known: list[str]) -> str:
    """Tidy a free-form type name and reuse an existing spelling: "people" stays new, but
    "person" -> "Person" when Person already exists. Never rejects."""
    words = _WORDS.findall(raw or "")
    if not words:
        return "Thing"
    by_lower = {k.lower(): k for k in known}
    joined = " ".join(words)
    if joined.lower() in by_lower:
        return by_lower[joined.lower()]
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in words)


def canonical_predicate(raw: str) -> str:
    """Free-form predicate -> snake_case ("works at" -> works_at)."""
    return "_".join(w.lower() for w in _WORDS.findall(raw or "")) or "related_to"
