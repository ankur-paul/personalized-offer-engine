"""`offer-engine personas draft | show | freeze`: Persona Cards for the showcase Customers (PLAN §4.2).

`draft` picks one Customer per case and has Claude (`OFFER_AGENT_MODEL`) write each card from observable data,
skipping frozen cards. A human reviews and edits the files in `personas/`, then `freeze` marks them all frozen so
demos repeat.
"""

from __future__ import annotations

import argparse
import textwrap
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("personas", help="draft, show or freeze the showcase Persona Cards")
    actions = parser.add_subparsers(dest="personas_action", metavar="<action>", required=True)
    draft = actions.add_parser("draft", help="pick the showcase Customers and draft their cards with Claude")
    draft.add_argument(
        "--seed", type=int, help="the seed the world was generated with (default: SEED, else 7)"
    )
    show = actions.add_parser("show", help="print every Persona Card")
    freeze = actions.add_parser("freeze", help="mark every Persona Card frozen after review")
    for action, func in ((draft, run_draft), (show, run_show), (freeze, run_freeze)):
        action.add_argument("--dir", type=Path, default=None, help="card directory (default: personas/)")
        action.set_defaults(func=func)


def run_draft(args: argparse.Namespace) -> int:
    import anthropic

    from offer_engine import clock, personas
    from offer_engine.config import load_settings
    from offer_engine.customers import load_customer_state
    from offer_engine.db import connect, load_catalog, migrate
    from offer_engine.rules_store import current_rules
    from offer_engine.sim.personas.draft import DraftError, build_summary, draft_card
    from offer_engine.sim.personas.select import select_showcase

    directory = args.dir or personas.PERSONAS_DIR
    settings = load_settings()
    if not settings.anthropic_api_key or not settings.offer_agent_model:
        raise SystemExit("set ANTHROPIC_API_KEY and OFFER_AGENT_MODEL in .env to draft Persona Cards")
    seed = args.seed if args.seed is not None else settings.seed

    conn = connect()
    migrate(conn)
    now = clock.now(conn)
    population = conn.execute("SELECT COUNT(*) FROM customers WHERE is_tester_copy = 0").fetchone()[0]
    try:
        picks = select_showcase(conn, current_rules(conn)[1], now)
    except ValueError as e:
        conn.close()
        raise SystemExit(str(e)) from None

    existing = {c.customer_id: c for c in personas.load_all(directory)}
    chosen = {p.customer_id for p in picks}
    for card in existing.values():
        if card.frozen and card.customer_id not in chosen:
            conn.close()
            raise SystemExit(
                f"{card.customer_id} has a frozen card ({card.case}) but this world doesn't pick them. Generate the "
                f"world the cards were made for (`generate --customers {card.population} --seed {card.seed}`)."
            )
    for card in existing.values():
        if card.customer_id not in chosen:
            personas.path_for(card.customer_id, directory).unlink()
            print(f"removed stale draft {card.customer_id} ({card.case})")

    client = _client(settings.anthropic_api_key)
    catalog = load_catalog(conn)
    others = [_first_sentence(c.card) for c in existing.values() if c.frozen]
    failed = 0
    for pick in picks:
        old = existing.get(pick.customer_id)
        if old and old.frozen:
            print(f"kept   {pick.case:<20}{pick.customer_id}  {old.name} (frozen)")
            continue
        summary = build_summary(load_customer_state(conn, pick.customer_id, now), catalog, now)
        try:
            draft = draft_card(client, settings.offer_agent_model, summary, others=tuple(others))
        except (anthropic.APIError, DraftError) as e:  # report it and draft the rest
            failed += 1
            print(f"FAILED {pick.case:<20}{pick.customer_id}  {type(e).__name__}: {e}")
            continue
        others.append(_first_sentence(draft.card))
        card = personas.PersonaCard(
            customer_id=pick.customer_id,
            case=pick.case,
            name=draft.name,
            card=draft.card,
            frozen=False,
            drafted_at=datetime.now(UTC).isoformat(timespec="seconds"),
            seed=seed,
            population=population,
        )
        path = personas.save(card, directory)
        print(f"draft  {pick.case:<20}{pick.customer_id}  {draft.name} → {path}")
    conn.close()
    print("\nReview and edit the files, then run `offer-engine personas freeze`.")
    return 1 if failed else 0


def run_show(args: argparse.Namespace) -> int:
    from offer_engine import personas
    from offer_engine.sim.personas.draft import CARD_WORDS

    directory = args.dir or personas.PERSONAS_DIR
    cards = personas.load_all(directory)
    if not cards:
        raise SystemExit(f"no Persona Cards in {directory}/; run `offer-engine personas draft`")
    for card in cards:
        words = len(card.card.split())
        state = "frozen" if card.frozen else "draft"
        label = personas.CASE_LABELS.get(card.case, card.case)
        fit = "" if CARD_WORDS[0] <= words <= CARD_WORDS[1] else f", outside {CARD_WORDS[0]}–{CARD_WORDS[1]}"
        print(f"{label} · {card.customer_id} · {card.name} [{state}, {words} words{fit}]")
        print(textwrap.indent(textwrap.fill(card.card, 100), "  ") + "\n")
    missing = [
        c for c in personas.CASES if c not in personas.OPTIONAL_CASES and c not in {x.case for x in cards}
    ]
    worlds = sorted({(c.population, c.seed) for c in cards})
    print(f"{len(cards)} cards for " + ", ".join(f"{n:,} Customers, seed {s}" for n, s in worlds))
    if missing:
        print("missing cases: " + ", ".join(missing))
    return 0


def run_freeze(args: argparse.Namespace) -> int:
    from offer_engine import personas

    directory = args.dir or personas.PERSONAS_DIR
    cards = personas.load_all(directory)
    if not cards:
        raise SystemExit(f"no Persona Cards in {directory}/; run `offer-engine personas draft`")
    drafts = [c for c in cards if not c.frozen]
    for card in drafts:
        personas.save(replace(card, frozen=True), directory)
    print(f"froze {len(drafts)} cards; {len(cards) - len(drafts)} were already frozen")
    return 0


def _first_sentence(text: str) -> str:
    return text.split(". ", 1)[0].rstrip(".") + "."


def _client(api_key: str) -> Any:
    import anthropic

    return anthropic.Anthropic(api_key=api_key)
