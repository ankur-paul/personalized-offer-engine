"""Tamper with the agent's answer, so a demo scenario can show Validation and the Fallback catching it (T38).

Only scenarios use it, through `pipeline.chooser_wrapper`; Validation is unchanged (ADR 0001). The tampered values
also go into the agent's recorded output, marked `tampered`, so the trace shows what Validation was given.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from offer_engine.choosers import rules_chooser
from offer_engine.domain import EligibleSet, OfferType, Proposal


class Tampered:
    """A chooser (`pipeline.ChooserFn`) that gives `wrapped`'s Proposal the given params and caption, moved first
    to the Eligible Set's first `offer_type` option if one is given. `model`, `trigger` and the rest come from
    `wrapped`."""

    def __init__(
        self, wrapped: Any, offer_type: OfferType | None, params: dict[str, float] | None, caption: str | None
    ):
        self.wrapped = wrapped
        self.offer_type = offer_type
        self.params = params or {}
        self.caption = caption
        self.last_output: dict[str, Any] | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.wrapped, name)

    def __call__(self, eligible, state, catalog, rules) -> Proposal:
        proposal = self.wrapped(eligible, state, catalog, rules)
        output = getattr(self.wrapped, "last_output", None)
        self.last_output = output
        changes: dict[str, Any] = {}
        if self.offer_type is not None:
            proposal, index = _move(proposal, eligible, self.offer_type)
            if index is not None:
                changes["option_index"] = index
        if proposal.offer_type is None:
            return proposal
        if self.params:
            changes["params"] = self.params
        if self.caption is not None:
            changes["caption"] = self.caption
        tampered = replace(
            proposal,
            params={**proposal.params, **self.params},
            caption=changes.get("caption", proposal.caption),
        )
        if output is not None:
            self.last_output = {
                **output,
                "option_index": changes.get("option_index", output.get("option_index")),
                "params": tampered.params,
                "featured_product_ids": list(tampered.featured_product_ids),
                "caption": tampered.caption,
                "tampered": changes,
            }
        return tampered


def _move(proposal: Proposal, eligible: EligibleSet, offer_type: OfferType) -> tuple[Proposal, int | None]:
    """The Proposal on the first `offer_type` option, each param at the top of its range and no featured products,
    and that option's index. Unchanged, with index None, when it is already that type or the Eligible Set has no
    such option."""
    if proposal.offer_type == offer_type:
        return proposal, None
    for index, option in enumerate(eligible.options):
        if option.offer_type == offer_type:
            params = {name: r.hi for name, r in option.ranges.items()}
            send_at = proposal.send_at or (eligible.send_window[0] if eligible.send_window else None)
            caption = proposal.caption or "An offer for you."
            moved = replace(
                proposal,
                offer_type=offer_type,
                category=option.category,
                params=params,
                featured_product_ids=(),
                send_at=send_at,
                caption=caption,
            )
            return moved, index
    return proposal, None


def tampered(
    chooser: Any,
    *,
    offer_type: OfferType | None = None,
    params: dict[str, float] | None = None,
    caption: str | None = None,
) -> Any:
    """`chooser` with its Proposal moved to an `offer_type` option, and its params and caption replaced. The rules
    chooser is left alone: only the agent's answer is tampered with."""
    if chooser is rules_chooser.choose:
        return chooser
    return Tampered(chooser, offer_type, params, caption)
