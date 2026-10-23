"""`offer-engine chats link CUSTOMER_ID --bot @username`, `chats link-showcase` and `chats list`: which chat each
chat-attached Customer uses. A chat serves one Customer, so linking a Customer Bot moves it off any Customer it served
before."""

from __future__ import annotations

import argparse


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("chats", help="link Customers to Customer Bots and list chat links")
    actions = parser.add_subparsers(dest="action", required=True)
    link = actions.add_parser("link", help="make a Customer Bot from CUSTOMER_BOTS embody a Customer")
    link.add_argument("customer_id", metavar="CUSTOMER_ID")
    link.add_argument("--bot", required=True, metavar="@USERNAME")
    link.set_defaults(func=run_link)
    showcase = actions.add_parser(
        "link-showcase", help="link each frozen Persona Card's Customer to a Customer Bot, in order"
    )
    showcase.set_defaults(func=run_link_showcase)
    listing = actions.add_parser("list", help="list chat-attached Customers")
    listing.set_defaults(func=run_list)


def bot_chat_ids(customer_bots: list[tuple[str, str]]) -> dict[str, int]:
    """Customer Bot username (no @, lowercase) → its chat ID: a bot's ID is the number before the token's colon."""
    return {username.lstrip("@").lower(): int(token.split(":", 1)[0]) for username, token in customer_bots}


def link(conn, customer_id: str, chat_id: int, kind: str) -> list[str]:
    """Link `customer_id` to `chat_id`. Returns the Customers the chat was taken from."""
    moved = [
        row[0]
        for row in conn.execute(
            "SELECT customer_id FROM chats WHERE chat_id = ? AND customer_id != ?", (chat_id, customer_id)
        )
    ]
    conn.execute("DELETE FROM chats WHERE chat_id = ? AND customer_id != ?", (chat_id, customer_id))
    conn.execute(
        "INSERT INTO chats (customer_id, chat_id, kind) VALUES (?, ?, ?)"
        " ON CONFLICT (customer_id) DO UPDATE SET chat_id = excluded.chat_id, kind = excluded.kind",
        (customer_id, chat_id, kind),
    )
    conn.commit()
    return moved


def run_link(args: argparse.Namespace) -> int:
    from offer_engine.config import load_settings
    from offer_engine.db import connect, migrate
    from offer_engine.domain import ChatKind

    settings = load_settings()
    username = args.bot.lstrip("@").lower()
    chat_ids = bot_chat_ids(settings.customer_bots)
    if username not in chat_ids:
        known = ", ".join(f"@{name}" for name in chat_ids) or "none"
        raise SystemExit(f"@{username} isn't in CUSTOMER_BOTS (known: {known}); run `offer-engine setup`")
    conn = connect(settings.db_path)
    migrate(conn)
    if conn.execute("SELECT 1 FROM customers WHERE id = ?", (args.customer_id,)).fetchone() is None:
        raise SystemExit(f"no Customer {args.customer_id}; run `offer-engine generate` first?")
    moved = link(conn, args.customer_id, chat_ids[username], ChatKind.BOT)
    conn.close()
    for other in moved:
        print(f"unlinked {other} from @{username}")
    print(f"linked {args.customer_id} to @{username} (chat {chat_ids[username]})")
    return 0


def showcase_pairs(cards: list, customer_bots: list[tuple[str, str]]) -> tuple[list[tuple], list]:
    """([(card, bot username)], skipped cards): cards in order, the first gets the first bot. Short of bots, optional
    cases (`personas.OPTIONAL_CASES`) are skipped from the end; errors if the required ones still don't fit."""
    from offer_engine.personas import OPTIONAL_CASES

    required = sum(card.case not in OPTIONAL_CASES for card in cards)
    if len(customer_bots) < required:
        raise SystemExit(
            f"{required} required Persona Cards but {len(customer_bots)} Customer Bots in CUSTOMER_BOTS; "
            "add bots with `offer-engine setup`"
        )
    room = len(customer_bots) - required
    kept, skipped = [], []
    for card in cards:
        if card.case in OPTIONAL_CASES:
            if room == 0:
                skipped.append(card)
                continue
            room -= 1
        kept.append(card)
    usernames = [username.lstrip("@").lower() for username, _ in customer_bots]
    return list(zip(kept, usernames)), skipped


def run_link_showcase(args: argparse.Namespace) -> int:
    from offer_engine import personas
    from offer_engine.config import load_settings
    from offer_engine.db import connect, migrate
    from offer_engine.domain import ChatKind

    settings = load_settings()
    cards = personas.load_all(frozen_only=True)
    if not cards:
        raise SystemExit("no frozen Persona Cards; run `offer-engine personas draft` and `personas freeze`")
    pairs, skipped = showcase_pairs(cards, settings.customer_bots)
    chat_ids = bot_chat_ids(settings.customer_bots)
    conn = connect(settings.db_path)
    migrate(conn)
    missing = [
        card.customer_id
        for card, _ in pairs
        if conn.execute("SELECT 1 FROM customers WHERE id = ?", (card.customer_id,)).fetchone() is None
    ]
    if missing:
        conn.close()
        raise SystemExit(
            f"no Customer {', '.join(missing)}; run `offer-engine generate` with the cards' seed first"
        )
    for card, username in pairs:
        for other in link(conn, card.customer_id, chat_ids[username], ChatKind.BOT):
            print(f"unlinked {other} from @{username}")
        print(f"{card.customer_id}  {card.case:<20} {card.name:<22} @{username}")
    conn.close()
    for card in skipped:
        print(f"skipped {card.customer_id} ({card.case}, optional): not enough Customer Bots")
    return 0


def run_list(args: argparse.Namespace) -> int:
    from offer_engine.config import load_settings
    from offer_engine.db import connect, migrate

    settings = load_settings()
    names = {chat_id: f"@{name}" for name, chat_id in bot_chat_ids(settings.customer_bots).items()}
    conn = connect(settings.db_path)
    migrate(conn)
    rows = conn.execute(
        "SELECT ch.customer_id, ch.chat_id, ch.kind, c.opted_out FROM chats ch"
        " JOIN customers c ON c.id = ch.customer_id ORDER BY ch.customer_id"
    ).fetchall()
    conn.close()
    if not rows:
        print(
            "no chat-attached Customers; link one with `offer-engine chats link CUSTOMER_ID --bot @username`"
        )
    for row in rows:
        who = names.get(row["chat_id"], f"chat {row['chat_id']}")
        opted_out = " (opted out)" if row["opted_out"] else ""
        print(f"{row['customer_id']}  {row['kind']:<6}  {who}{opted_out}")
    return 0
