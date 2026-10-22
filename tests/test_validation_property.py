"""Property: a valid proposal passes, and random rule-breaking proposals never do (T07, PLAN §7).

Each case builds a random Customer, Rules and budget, picks a valid proposal from the Eligible Set, then applies
mutations from a catalogue where each breaks a named Rule. A mutation names the failure it must cause: a failure
code, a Rule in brackets, or both in the same failure.

Mutations that change who the Customer is or how much money is left reshape the whole Eligible Set, so they run
alone. The others each touch a separate part of the proposal (params, send time, featured products, caption,
reason) and are combined.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from hypothesis import assume, event, given, settings
from hypothesis import strategies as st

from offer_engine.domain import (
    LOYALTY_TIERS,
    BudgetState,
    Catalog,
    Category,
    Customer,
    CustomerState,
    EligibleOption,
    EligibleSet,
    Event,
    OfferStatus,
    OfferType,
    PastOffer,
    Product,
    Proposal,
    RuleSet,
)
from offer_engine.rules import RECENT_CATEGORY_DAYS, eligible_set, in_holdout, offer_cost
from offer_engine.validation import validate

EXAMPLES = settings(max_examples=500, deadline=None)

MARGINS = {"electronics": 8.0, "fashion": 45.0, "grocery": 15.0, "beauty": 40.0, "home": 30.0}
BASKETS = {"electronics": 4000.0, "fashion": 1500.0, "grocery": 800.0, "beauty": 700.0, "home": 2000.0}
CATALOG = Catalog(
    categories={c: Category(c, MARGINS[c], BASKETS[c]) for c in MARGINS},
    products={
        f"{c}-{i}": Product(f"{c}-{i}", f"{c} {i}", c, 100.0 * (i + 1)) for c in MARGINS for i in range(4)
    },
)
OUT_IDS = [f"C{n:05d}" for n in range(1, 200) if not in_holdout(f"C{n:05d}", 10.0)]
IN_ID = next(f"C{n:05d}" for n in range(1, 10_000) if in_holdout(f"C{n:05d}", 10.0))
DAY = datetime(2026, 12, 10)


@dataclass(frozen=True)
class Case:
    proposal: Proposal
    state: CustomerState
    rules: RuleSet
    budget: BudgetState
    now: datetime
    es: EligibleSet
    option: EligibleOption

    def run(self):
        return validate(self.proposal, self.state, self.rules, self.budget, self.now, CATALOG)

    def seen(self) -> set[str]:
        since = self.now - timedelta(days=RECENT_CATEGORY_DAYS)
        return {e.product_id for e in self.state.events if e.product_id and since <= e.at <= self.now}

    def cost(self) -> float:
        p = self.proposal
        return offer_cost(p.offer_type, p.category, p.params, CATALOG, self.rules)[0]


@dataclass(frozen=True)
class Expect:
    """The failure a mutation must cause: one failure starting with `code` and containing `(rule)`."""

    code: str | None = None
    rule: str | None = None

    def found_in(self, failures: tuple[str, ...]) -> bool:
        return any(
            (self.code is None or f.startswith(f"{self.code}:"))
            and (self.rule is None or f"({self.rule})" in f)
            for f in failures
        )


# --- Valid cases -------------------------------------------------------------------------------


@st.composite
def rule_sets(draw) -> RuleSet:
    start = draw(st.integers(0, 20))
    by_category = draw(st.dictionaries(st.sampled_from(sorted(MARGINS)), st.floats(0, 50), max_size=3))
    return RuleSet(
        max_pct_by_category=by_category,
        max_pct_by_loyalty_tier={t: draw(st.floats(0, 40)) for t in LOYALTY_TIERS},
        margin_floor_pct=draw(st.floats(0, 20)),
        max_flat_amount=draw(st.floats(0, 600) | st.floats(0, 60)),  # often low enough to drop flat ₹ off
        max_points_multiplier=draw(st.floats(1, 5)),
        per_offer_cost_cap=draw(st.floats(20, 1000)),
        send_hour_start=start,
        send_hour_end=draw(st.integers(start + 1, 24)),
        max_send_delay_hours=draw(st.integers(1, 48)),
    )


@st.composite
def customer_states(draw, now: datetime) -> CustomerState:
    customer_id = draw(st.sampled_from(OUT_IDS))
    customer = Customer(
        id=customer_id,
        signup_at=now - timedelta(days=300),
        city_tier=draw(st.integers(1, 3)),
        device="android",
        channel="organic",
        loyalty_tier=draw(st.sampled_from(LOYALTY_TIERS)),
        points_balance=0,
        points_expire_at=None,
    )
    events = []
    for product in draw(st.lists(st.sampled_from(sorted(CATALOG.products)), max_size=8)):
        recent = draw(st.booleans())
        hours = draw(
            st.integers(0, RECENT_CATEGORY_DAYS * 24 - 1) if recent else st.integers(91 * 24, 200 * 24)
        )
        kind = draw(st.sampled_from(["product_view", "cart_add", "order"]))
        category = CATALOG.products[product].category
        events.append(Event(customer_id, now - timedelta(hours=hours), kind, category, product))
    return CustomerState(customer=customer, events=tuple(events), offers=())


@st.composite
def valid_cases(draw) -> Case:
    now = DAY + timedelta(hours=draw(st.integers(0, 23)), minutes=draw(st.integers(0, 59)))
    rules = draw(rule_sets())
    state = draw(customer_states(now))
    budget = BudgetState(
        DAY - timedelta(days=3), spent=draw(st.floats(0, 40_000)), reserved=draw(st.floats(0, 5_000))
    )
    es = eligible_set(state, rules, budget, now, CATALOG)
    assert es.short_circuit is None
    ranged = [o for o in es.options if o.ranges]
    option = draw(st.sampled_from(es.options) | st.sampled_from(ranged or es.options))

    params = {}
    for name, r in option.ranges.items():
        hi = r.hi if r.hi != float("inf") else r.lo * 3 + 1
        params[name] = draw(st.floats(r.lo, hi, allow_nan=False))

    window = es.send_window
    seconds = int((window[1] - window[0]).total_seconds()) if window else 0
    if seconds > 0:
        send_at = window[0] + timedelta(seconds=draw(st.integers(0, seconds - 1)))
    else:
        send_at = None

    case = Case(Proposal(offer_type=None), state, rules, budget, now, es, option)
    candidates = sorted(
        p for p in case.seen() if option.category is None or CATALOG.products[p].category == option.category
    )
    featured = draw(st.lists(st.sampled_from(candidates), unique=True, max_size=2)) if candidates else []
    proposal = Proposal(
        offer_type=option.offer_type,
        category=option.category,
        params=params,
        featured_product_ids=tuple(featured),
        send_at=send_at,
        caption=draw(st.sampled_from(["Something you'll like.", "Picked for you", "Back in stock ✨"])),
        reason=draw(st.sampled_from(["Recent views", "Cart left behind", "Long gap"])),
    )
    return replace(case, proposal=proposal)


@given(valid_cases())
@EXAMPLES
def test_unmutated_valid_proposals_pass(case):
    if case.proposal.send_at is None:  # no send window left: only No Offer can pass
        assert case.es.send_window is None
        return
    result = case.run()
    assert result.ok is True, result.failures


# --- Mutations ---------------------------------------------------------------------------------

# A mutation returns the broken case and what must fail, or None when it doesn't apply to this case.
Mutation = Callable[[Case, st.DataObject], tuple[Case, Expect] | None]


def _customer(case: Case, **changes) -> Case:
    return replace(case, state=replace(case.state, customer=replace(case.state.customer, **changes)))


def _offers(case: Case, *offers: PastOffer) -> Case:
    return replace(case, state=replace(case.state, offers=(*case.state.offers, *offers)))


def _past(
    case: Case, days_ago: float, status=OfferStatus.SENT, redeemed_days_ago: float | None = None
) -> PastOffer:
    created = case.now - timedelta(days=days_ago)
    redeemed = None if redeemed_days_ago is None else case.now - timedelta(days=redeemed_days_ago)
    return PastOffer(
        int(days_ago * 1000), OfferType.NUDGE, None, status, created, created + timedelta(days=3), redeemed
    )


def _proposal(case: Case, **changes) -> Case:
    return replace(case, proposal=replace(case.proposal, **changes))


def opt_out(case, data):
    return _customer(case, opted_out=True), Expect("short_circuit", "opt_out")


def holdout(case, data):
    return _customer(case, id=IN_ID), Expect("short_circuit", "holdout_pct")


def fatigue(case, data):
    dismissed = [_past(case, d, OfferStatus.DISMISSED) for d in (8, 9, 10)]
    return _offers(case, *dismissed), Expect("short_circuit", "fatigue_dismissals")


def frequency_cap(case, data):
    recent = [_past(case, h / 24) for h in range(1, case.rules.frequency_cap_count + 1)]
    return _offers(case, *recent), Expect("short_circuit", "frequency_cap_count")


def cooldown(case, data):
    return _offers(case, _past(case, 20, OfferStatus.REDEEMED, 1)), Expect(
        "short_circuit", "cooldown_days_after_redemption"
    )


def too_new(case, data):
    return _customer(case, signup_at=case.now - timedelta(hours=1)), Expect(
        "short_circuit", "min_days_since_signup"
    )


def dropped_offer_type(case, data):
    dropped = sorted(k for k in case.es.dropped if ":" not in k)
    if not dropped:
        return None
    key = data.draw(st.sampled_from(dropped))
    broken = _proposal(case, offer_type=OfferType(key), category=None)
    return broken, Expect("offer_type_not_eligible", case.es.dropped[key])


def category_not_an_option(case, data):
    if case.option.offer_type != OfferType.PCT_CATEGORY:
        category = data.draw(st.sampled_from(sorted(MARGINS)))
        return _proposal(case, category=category), Expect("category_not_eligible")
    allowed = {o.category for o in case.es.options if o.offer_type == OfferType.PCT_CATEGORY}
    others = sorted(set(MARGINS) - allowed) + ["toys"]
    return _proposal(case, category=data.draw(st.sampled_from(others))), Expect("category_not_eligible")


def over_budget(case, data):
    cost = case.cost()
    if cost <= 0:
        return None
    spent = case.rules.weekly_budget - case.budget.reserved - cost / 2
    return replace(case, budget=replace(case.budget, spent=spent)), Expect(rule="weekly_budget")


def over_cost_cap(case, data):
    cost = case.cost()
    if cost <= 0:
        return None
    return replace(case, rules=replace(case.rules, per_offer_cost_cap=cost / 2)), Expect(
        rule="per_offer_cost_cap"
    )


def param_above(case, data):
    bounded = sorted(n for n, r in case.option.ranges.items() if r.hi != float("inf"))
    if not bounded:
        return None
    name = data.draw(st.sampled_from(bounded))
    value = case.option.ranges[name].hi + data.draw(st.floats(0.01, 100))
    params = {**case.proposal.params, name: value}
    return _proposal(case, params=params), Expect("param_out_of_range", case.option.binding_rules[name])


def param_below(case, data):
    if not case.option.ranges:
        return None
    name = data.draw(st.sampled_from(sorted(case.option.ranges)))
    value = case.option.ranges[name].lo - data.draw(st.floats(0.01, 100))
    return _proposal(case, params={**case.proposal.params, name: value}), Expect("param_out_of_range")


def param_missing(case, data):
    if not case.proposal.params:
        return None
    name = data.draw(st.sampled_from(sorted(case.proposal.params)))
    params = {k: v for k, v in case.proposal.params.items() if k != name}
    return _proposal(case, params=params), Expect("param_missing")


def param_extra(case, data):
    return _proposal(case, params={**case.proposal.params, "bonus": 1.0}), Expect("param_extra")


def param_not_finite(case, data):
    if not case.option.ranges:
        return None
    name = data.draw(st.sampled_from(sorted(case.option.ranges)))
    value = data.draw(st.sampled_from([float("nan"), float("inf"), float("-inf")]))
    return _proposal(case, params={**case.proposal.params, name: value}), Expect("param_out_of_range")


def send_before_window(case, data):
    start = case.es.send_window[0]
    minutes = data.draw(st.integers(1, 3 * 24 * 60))
    return _proposal(case, send_at=start - timedelta(minutes=minutes)), Expect("send_at_outside_window")


def send_after_window(case, data):
    end = case.es.send_window[1]
    minutes = data.draw(st.integers(0, 3 * 24 * 60))
    return _proposal(case, send_at=end + timedelta(minutes=minutes)), Expect("send_at_outside_window")


def send_missing(case, data):
    return _proposal(case, send_at=None), Expect("send_at_missing")


def featured_unknown(case, data):
    featured = (*case.proposal.featured_product_ids[:1], "P404")
    return _proposal(case, featured_product_ids=featured), Expect("featured_unknown")


def featured_wrong_category(case, data):
    if case.option.category is None:
        return None
    others = sorted(p for p, v in CATALOG.products.items() if v.category != case.option.category)
    return _proposal(case, featured_product_ids=(data.draw(st.sampled_from(others)),)), Expect(
        "featured_wrong_category"
    )


def featured_not_seen(case, data):
    seen = case.seen()
    unseen = sorted(
        p
        for p, v in CATALOG.products.items()
        if p not in seen and (case.option.category is None or v.category == case.option.category)
    )
    if not unseen:
        return None
    return _proposal(case, featured_product_ids=(data.draw(st.sampled_from(unseen)),)), Expect(
        "featured_not_seen"
    )


def too_many_featured(case, data):
    featured = data.draw(
        st.lists(st.sampled_from(sorted(CATALOG.products)), unique=True, min_size=3, max_size=5)
    )
    return _proposal(case, featured_product_ids=tuple(featured)), Expect("too_many_featured")


def caption_missing(case, data):
    return _proposal(case, caption=data.draw(st.sampled_from(["", " ", "\n\t"]))), Expect("caption_missing")


def reason_missing(case, data):
    return _proposal(case, reason=data.draw(st.sampled_from(["", "  "]))), Expect("reason_missing")


ALONE: list[Mutation] = [
    opt_out,
    holdout,
    fatigue,
    frequency_cap,
    cooldown,
    too_new,
    dropped_offer_type,
    category_not_an_option,
    over_budget,
    over_cost_cap,
]
GROUPS: dict[str, list[Mutation]] = {
    "params": [param_above, param_below, param_missing, param_extra, param_not_finite],
    "send_at": [send_before_window, send_after_window, send_missing],
    "featured": [featured_unknown, featured_wrong_category, featured_not_seen, too_many_featured],
    "caption": [caption_missing],
    "reason": [reason_missing],
}


def _apply_one(case: Case, mutations: list[Mutation], data) -> tuple[Case, Expect, str]:
    """Try the mutations in a drawn order and apply the first that fits this case. Every list has one that
    always fits (`opt_out`, `param_extra`, `send_missing`, `featured_unknown`, the caption and reason ones).
    """
    for mutation in data.draw(st.permutations(mutations)):
        applied = mutation(case, data)
        if applied is not None:
            return (*applied, mutation.__name__)
    raise AssertionError(f"no mutation fits from {[m.__name__ for m in mutations]}")


@given(valid_cases(), st.data())
@EXAMPLES
def test_rule_breaking_proposals_never_pass(case, data):
    assume(case.proposal.send_at is not None)  # no send window left; covered by the valid test
    if data.draw(st.booleans(), label="alone"):
        groups = [ALONE]
    else:
        names = data.draw(st.lists(st.sampled_from(sorted(GROUPS)), unique=True, min_size=1), label="groups")
        groups = [GROUPS[n] for n in names]
    expected = []
    for mutations in groups:
        case, expect, name = _apply_one(case, mutations, data)
        event(name)
        expected.append((name, expect))

    result = case.run()
    assert result.ok is False, f"{[n for n, _ in expected]} passed Validation"
    for name, expect in expected:
        assert expect.found_in(result.failures), f"{name}: expected {expect} in {result.failures}"
