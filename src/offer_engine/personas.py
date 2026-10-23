"""Persona Cards of the showcase Customers (PLAN §4.2): one JSON file per Customer in `personas/`, drafted by an
agent, reviewed by a human, then frozen so demos repeat. Customer Bots (T24) and Testers (T25) read them here.

A card never reveals Ground Truth (ADR 0002). Its `case` names why the Customer was picked; only people see it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

PERSONAS_DIR = Path("personas")

# Showcase cases in the order cards are listed and Customer Bots are linked. `persuadable` is optional.
CASES = (
    "at_risk_high_value",
    "new_one_order",
    "deal_hunter",
    "expiring_points",
    "cart_abandoner",
    "sure_thing",
    "holdout",
    "persuadable",
)
OPTIONAL_CASES = ("persuadable",)
CASE_LABELS = {
    "at_risk_high_value": "At-risk high value",
    "new_one_order": "New, one order",
    "deal_hunter": "Deal hunter",
    "expiring_points": "Expiring points",
    "cart_abandoner": "Cart abandoner",
    "sure_thing": "Sure Thing",
    "holdout": "Holdout",
    "persuadable": "Persuadable",
}


@dataclass(frozen=True)
class PersonaCard:
    customer_id: str
    case: str
    name: str
    card: str
    frozen: bool
    drafted_at: str  # wall-clock time, UTC
    seed: int  # the generator seed whose Customer IDs this card belongs to
    population: int  # Customers in that generated world


def path_for(customer_id: str, directory: Path = PERSONAS_DIR) -> Path:
    return directory / f"{customer_id}.json"


def save(card: PersonaCard, directory: Path = PERSONAS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = path_for(card.customer_id, directory)
    path.write_text(json.dumps(asdict(card), indent=2, ensure_ascii=False) + "\n")
    return path


def load(path: Path) -> PersonaCard:
    return PersonaCard(**json.loads(path.read_text()))


def load_all(directory: Path = PERSONAS_DIR, frozen_only: bool = False) -> list[PersonaCard]:
    """Every card in `directory` in CASES order (unknown cases last, then by Customer ID)."""
    cards = [load(p) for p in sorted(directory.glob("*.json"))] if directory.is_dir() else []
    if frozen_only:
        cards = [c for c in cards if c.frozen]
    order = {case: i for i, case in enumerate(CASES)}
    return sorted(cards, key=lambda c: (order.get(c.case, len(CASES)), c.customer_id))
