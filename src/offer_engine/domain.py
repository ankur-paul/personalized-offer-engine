"""Shared types for the whole engine. Only a ticket whose Scope says so changes them.

Money is `float` rupees, percentages are `float` 0–100, and datetimes are naive simulated IST.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from typing import Any


class OfferType(StrEnum):
    PCT_CATEGORY = "pct_category"
    FLAT_ABOVE_MIN = "flat_above_min"
    FREE_SHIPPING = "free_shipping"
    POINTS_MULTIPLIER = "points_multiplier"
    NUDGE = "nudge"


class TriggerKind(StrEnum):
    CART_ABANDONED = "cart_abandoned"
    POINTS_EXPIRING = "points_expiring"
    LONG_GAP = "long_gap"
    FIRST_ORDER_DELIVERED = "first_order_delivered"
    DAILY_SWEEP = "daily_sweep"
    ON_REQUEST = "on_request"


class OfferStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    CLAIMED = "claimed"
    DISMISSED = "dismissed"
    REDEEMED = "redeemed"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class Chooser(StrEnum):
    AGENT = "agent"
    FALLBACK = "fallback"
    RULES = "rules"


class BudgetMode(StrEnum):
    WORST_CASE = "worst_case"
    EXPECTED = "expected"


class ChatKind(StrEnum):
    BOT = "bot"
    TESTER = "tester"


class OfferSource(StrEnum):
    LIVE = "live"
    HISTORY_RANDOM = "history_random"


# Loyalty tiers, lowest first. The generator draws from these; RuleSet caps discounts per tier.
LOYALTY_TIERS = ("bronze", "silver", "gold", "platinum")


# --- Marketplace -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Category:
    name: str
    margin_pct: float
    avg_basket: float


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category: str
    price: float


@dataclass(frozen=True)
class Catalog:
    categories: dict[str, Category]
    products: dict[str, Product]


# --- Customers ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Customer:
    id: str
    signup_at: datetime
    city_tier: int
    device: str
    channel: str
    loyalty_tier: str
    points_balance: int
    points_expire_at: datetime | None
    opted_out: bool = False
    is_tester_copy: bool = False
    source_customer_id: str | None = None


@dataclass(frozen=True)
class Event:
    customer_id: str
    at: datetime
    kind: str
    category: str | None = None
    product_id: str | None = None
    amount: float | None = None
    offer_id: int | None = None


@dataclass(frozen=True)
class ChatLink:
    customer_id: str
    chat_id: int
    kind: ChatKind


@dataclass(frozen=True)
class PastOffer:
    id: int
    offer_type: OfferType
    category: str | None
    status: OfferStatus
    created_at: datetime
    expires_at: datetime
    redeemed_at: datetime | None = None


@dataclass(frozen=True)
class CustomerState:
    """Everything the pipeline may know about one Customer at `now`: events from the last 180 days."""

    customer: Customer
    events: tuple[Event, ...]
    offers: tuple[PastOffer, ...]
    chat: ChatLink | None = None


@dataclass(frozen=True)
class BudgetState:
    week_start: datetime
    spent: float
    reserved: float


# --- Rules -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleSet:
    """Every Rule setting, with its default. Empty `max_pct_by_category` means no cap beyond the margin floor."""

    max_pct_by_category: dict[str, float] = field(default_factory=dict)
    max_pct_by_loyalty_tier: dict[str, float] = field(
        default_factory=lambda: {"bronze": 15.0, "silver": 20.0, "gold": 25.0, "platinum": 30.0}
    )
    margin_floor_pct: float = 5.0
    max_flat_amount: float = 300.0
    max_points_multiplier: float = 3.0
    per_offer_cost_cap: float = 500.0
    weekly_budget: float = 50_000.0
    budget_mode: BudgetMode = BudgetMode.WORST_CASE
    frequency_cap_count: int = 2
    frequency_cap_days: int = 7
    cooldown_days_after_redemption: int = 7
    min_days_since_signup: int = 1
    send_hour_start: int = 9
    send_hour_end: int = 21
    max_send_delay_hours: int = 24
    holdout_pct: float = 10.0
    fatigue_dismissals: int = 3
    fatigue_window_days: int = 14
    fatigue_pause_days: int = 14
    offer_validity_days: int = 3
    shipping_fee: float = 40.0
    point_value: float = 0.25
    long_gap_days: int = 45
    points_expiry_warning_days: int = 7

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-ready values: dicts copied, enums as their string value."""
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, dict):
                value = dict(value)
            elif isinstance(value, StrEnum):
                value = value.value
            out[f.name] = value
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuleSet:
        """Build from stored settings. Missing keys take their default; unknown keys are an error."""
        defaults = cls()
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f"unknown Rule settings: {', '.join(unknown)}")
        values: dict[str, Any] = {}
        for name in known & set(data):
            default = getattr(defaults, name)
            raw = data[name]
            if isinstance(default, dict):
                values[name] = {str(k): float(v) for k, v in raw.items()}
            elif isinstance(default, BudgetMode):
                values[name] = BudgetMode(raw)
            else:
                values[name] = type(default)(raw)
        return cls(**values)


@dataclass(frozen=True)
class ParamRange:
    lo: float
    hi: float


@dataclass(frozen=True)
class EligibleOption:
    offer_type: OfferType
    category: str | None
    ranges: dict[str, ParamRange]
    binding_rules: dict[str, str]
    worst_case_cost: float
    estimated_lift: float | None = None


@dataclass(frozen=True)
class EligibleSet:
    customer_id: str
    at: datetime
    options: tuple[EligibleOption, ...]
    send_window: tuple[datetime, datetime] | None
    short_circuit: str | None = None
    binding_rule: str | None = None
    dropped: dict[str, str] = field(default_factory=dict)


# --- Decisions and Offers ----------------------------------------------------------------------


@dataclass(frozen=True)
class Proposal:
    """A chooser's pick. `offer_type=None` is No Offer."""

    offer_type: OfferType | None
    category: str | None = None
    params: dict[str, float] = field(default_factory=dict)
    featured_product_ids: tuple[str, ...] = ()
    send_at: datetime | None = None
    caption: str = ""
    reason: str = ""


@dataclass(frozen=True)
class Offer:
    id: int | None
    code: str
    customer_id: str
    offer_type: OfferType
    category: str | None
    params: dict[str, float]
    featured_product_ids: tuple[str, ...]
    created_at: datetime
    send_at: datetime
    expires_at: datetime
    caption: str
    rule_version: int
    worst_case_cost: float
    expected_cost: float
    status: OfferStatus
    source: OfferSource


@dataclass(frozen=True)
class ValidationResult:
    """`checks` names the checks `validate` ran, in order (T35); `failures` may come from any of them."""

    ok: bool
    failures: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    id: int | None
    customer_id: str
    at: datetime
    trigger: TriggerKind
    chooser: Chooser
    offer_id: int | None
    reason: str
    binding_rule: str | None
    rule_version: int
    validation: ValidationResult | None
