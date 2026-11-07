"""User-editable extraction schema: entity types, attributes and relation types.

Schemas are versioned (every edit stores a new version) so each claim's provenance can say which
schema it was extracted against. Default packs live in ``folio_core/schema_packs/*.yaml``.
"""

from __future__ import annotations

from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

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
    entity_types: dict[str, EntityTypeDef]
    relation_types: dict[str, RelationTypeDef]

    @model_validator(mode="after")
    def _check_refs(self) -> SchemaDef:
        known = set(self.entity_types) | {"*"}
        for rel_name, rel in self.relation_types.items():
            for t in [*rel.source, *rel.target]:
                if t not in known:
                    raise ValueError(f"relation '{rel_name}' references unknown type '{t}'")
        return self

    # --- lookups used by extraction and the label parser -------------------------------------

    def relation_allows(self, predicate: str, subject_type: str, object_type: str) -> bool:
        rel = self.relation_types.get(predicate)
        if rel is None:
            return predicate == MENTIONS
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
