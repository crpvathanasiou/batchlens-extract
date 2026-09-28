"""Fixed V1 unit vocabulary and tightly controlled value-expression rules (L10).

These are implementation data for the lexical engine, not a user-selectable
execution-config switch. Equipment ``Unit`` rows remain a separate L05 vocabulary
source; this module covers common material-quantity units and narrow categorical
or cue forms that equipment units alone do not provide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.lexical_extraction.contracts import UNIT_VOCABULARY_ID

UNIT_VALUE_RULES_VERSION: Final = "lexical-unit-value-rules-v1"
FIXED_UNIT_VOCABULARY_SOURCE_TABLE: Final = UNIT_VOCABULARY_ID
FIXED_UNIT_VOCABULARY_SOURCE_FIELD: Final = "controlled_spelling"


@dataclass(frozen=True)
class FixedUnitEntry:
    """One fixed quantity-unit vocabulary entry.

    ``controlled_spelling`` is the canonical vocabulary form. ``aliases`` are
    additional original spellings that map to the same controlled identity.
    Original document text is never rewritten to the controlled spelling.
    """

    controlled_identity: str
    controlled_spelling: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CategoricalRule:
    """Exact categorical phrase recognized only under this fixed V1 rule."""

    category_label: str
    phrase: str


@dataclass(frozen=True)
class CueRule:
    """Explicit cue that may introduce a unitless numeric value."""

    cue: str


# Common material-quantity and process units absent from, or not solely covered
# by, equipment.Unit eligibility. Spellings are matched with L06 atomic_unit
# boundaries; controlled identity is distinct from original document spelling.
FIXED_QUANTITY_UNITS: Final[tuple[FixedUnitEntry, ...]] = (
    FixedUnitEntry("kg", "kg"),
    FixedUnitEntry("g", "g"),
    FixedUnitEntry("mg", "mg"),
    FixedUnitEntry("ug", "µg", aliases=("ug",)),
    FixedUnitEntry("L", "L"),
    FixedUnitEntry("mL", "mL", aliases=("ml",)),
    FixedUnitEntry("uL", "µL", aliases=("uL", "ul")),
    FixedUnitEntry("percent", "%"),
    FixedUnitEntry("deg_C", "°C", aliases=("C",)),
    FixedUnitEntry("deg_F", "°F", aliases=("F",)),
    FixedUnitEntry("K", "K"),
    FixedUnitEntry("Pa", "Pa"),
    FixedUnitEntry("kPa", "kPa"),
    FixedUnitEntry("bar", "bar"),
    FixedUnitEntry("atm", "atm"),
    FixedUnitEntry("mol", "mol"),
    FixedUnitEntry("mmol", "mmol"),
    FixedUnitEntry("IU", "IU"),
    FixedUnitEntry("CFU", "CFU"),
    FixedUnitEntry("rpm", "rpm"),
    FixedUnitEntry("min", "min"),
    FixedUnitEntry("s", "s"),
    FixedUnitEntry("h", "h"),
)

# Narrow categorical phrases only. No inferred entity or unit.
FIXED_CATEGORICAL_RULES: Final[tuple[CategoricalRule, ...]] = (
    CategoricalRule(category_label="OFF", phrase="OFF"),
    CategoricalRule(category_label="under vacuum", phrase="under vacuum"),
)

# Explicit cues only. The cue text is preserved; no parent parameter is implied.
FIXED_CUE_RULES: Final[tuple[CueRule, ...]] = (CueRule(cue="Speed:"),)


def fixed_unit_spellings() -> tuple[str, ...]:
    """Return every fixed original spelling eligible for unit or value recognition."""

    spellings: list[str] = []
    seen: set[str] = set()
    for entry in FIXED_QUANTITY_UNITS:
        for spelling in (entry.controlled_spelling, *entry.aliases):
            if spelling not in seen:
                seen.add(spelling)
                spellings.append(spelling)
    return tuple(spellings)


def controlled_unit_for_spelling(spelling: str) -> FixedUnitEntry | None:
    """Return the fixed entry whose controlled spelling or alias equals ``spelling``.

    Matching is case-sensitive on the exact vocabulary forms. Callers that need
    case-insensitive lookup should use :func:`controlled_unit_for_casefolded`.
    """

    for entry in FIXED_QUANTITY_UNITS:
        if spelling == entry.controlled_spelling or spelling in entry.aliases:
            return entry
    return None


def controlled_unit_for_casefolded(spelling: str) -> FixedUnitEntry | None:
    """Return the fixed entry matching ``spelling`` under Unicode casefold."""

    key = spelling.casefold()
    for entry in FIXED_QUANTITY_UNITS:
        if entry.controlled_spelling.casefold() == key:
            return entry
        for alias in entry.aliases:
            if alias.casefold() == key:
                return entry
    return None


def fixed_unit_row_id(controlled_identity: str) -> str:
    """Stable synthetic row id for a fixed vocabulary entry (not a catalogue id)."""

    return f"vocab:{controlled_identity}"
