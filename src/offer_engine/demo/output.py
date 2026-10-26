"""Plain-text demo scenario results (T37), for `offer-engine demo` and the live page's plain-text fallback."""

from __future__ import annotations

from offer_engine.commands.decisions import stage_lines
from offer_engine.demo.runner import ScenarioResult
from offer_engine.demo.scenarios import Scenario


def heading(scenario: Scenario) -> list[str]:
    return [
        f"{scenario.name} · {scenario.title}",
        f"  {scenario.group}: {scenario.proves}",
        f"  Customer {scenario.customer_id} · Trigger {scenario.trigger}",
    ]


def result_lines(result: ScenarioResult, *, trace: bool = True) -> list[str]:
    """The heading, each trace stage (with `trace`), the Decision, the seeded outcome and PASS or FAIL."""
    lines = heading(result.scenario)
    if trace:
        for stage in result.trace.stages:
            lines += ["", *stage_lines(stage)]
        lines.append("")
    lines.append(f"Decision: {decision_text(result)}")
    lines += outcome_lines(result)
    lines.append(verdict(result))
    return lines


def decision_text(result: ScenarioResult) -> str:
    offer = result.trace.stages[-1]
    if result.decision.offer_id is None:
        # The agent's No Offer carries only its reason.
        reason = offer.summary if offer.summary.startswith("No Offer") else f"No Offer: {offer.summary}"
        return f"{reason} · by {result.decision.chooser}"
    return f"{offer.data['code']} {offer.summary}"


def outcome_lines(result: ScenarioResult) -> list[str]:
    """What moved the buying chance, the seeded flip, and the replies. Nothing for No Offer."""
    if result.p_base is None:
        return [] if result.decision.offer_id is None else ["Outcome: no Ground Truth for this Customer"]
    if result.fit is None:
        chance = f"Ground Truth {result.p_base:.1%} (no Customer Bot, so no message fit)"
    else:
        chance = f"Ground Truth {result.p_base:.1%}, message fit {result.fit:+.2f} → {result.p_used:.1%}"
    act = "claims the code" if result.claims else 'says "Not now"'
    lines = [
        f"Outcome: chance of buying in 7 days {chance}",
        f"  seeded flip: {'buys' if result.buys else 'does not buy'}; {act}",
    ]
    if result.reply:
        lines.append(f"  Customer Bot: {result.reply.splitlines()[0]}")
    if result.bot_reply:
        lines.append(f"  Offer Bot: {result.bot_reply}")
    return lines


def verdict(result: ScenarioResult) -> str:
    if result.passed:
        return f"PASS {result.scenario.name}"
    return f"FAIL {result.scenario.name}: {'; '.join(result.mismatches)}"


def check_line(result: ScenarioResult) -> str:
    """One line per scenario for `demo check`: no timings, so two runs print the same."""
    return f"{verdict(result)} · {decision_text(result)}"
