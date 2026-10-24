"""Results (PLAN §5): the offline Policy comparison on Incremental Margin per ₹ of offer spend, then the live funnel
against the Holdout, spend wasted on Sure Things, Validation rejections and Fallbacks, and Lift by decile."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from console import data
from offer_engine import clock, rules_store
from offer_engine.sim import live_metrics

# Categorical slots 1 and 2 of the dataviz reference palette, stepped per theme (validated for both surfaces), and
# its primary ink for labels: Streamlit's chart theme doesn't recolour text marks.
SERIES = {"light": ("#2a78d6", "#eb6834"), "dark": ("#3987e5", "#d95926")}
INK = {"light": "#0b0b0b", "dark": "#f0efec"}


def rupees(value: float, sign: bool = False) -> str:
    return f"{'+' if sign and value > 0 else '-' if value < 0 else ''}₹{abs(value):,.0f}"


def theme() -> str:
    return "dark" if st.context.theme.type == "dark" else "light"


def series_colors() -> tuple[str, str]:
    return SERIES[theme()]


def bar_chart(frame: pd.DataFrame, value: str, title: str, label: str, tooltip: list) -> alt.LayerChart:
    """Horizontal bars of `value` by `name`, in frame order, each labelled past its end with `label`. The axis runs
    a third past the longest bar, and an eighth past a negative one, so the labels fit."""
    order = frame["name"].tolist()
    lo, hi = min(0.0, frame[value].min()), max(0.0, frame[value].max())
    span = (hi - lo) or 1.0
    domain = [lo - span / 8 if lo < 0 else 0, hi + span / 3]
    base = alt.Chart(frame).encode(
        y=alt.Y("name:N", sort=order, title=None),
        x=alt.X(
            f"{value}:Q", title=title, scale=alt.Scale(domain=domain, nice=False), axis=alt.Axis(tickCount=6)
        ),
        tooltip=tooltip,
    )
    bars = base.mark_bar(color=series_colors()[0], size=22, cornerRadiusEnd=4)
    ink = INK[theme()]
    right = base.mark_text(align="left", dx=6, color=ink).encode(text=f"{label}:N")
    left = base.mark_text(align="right", dx=-6, color=ink).encode(text=f"{label}:N")
    labels = right.transform_filter(alt.datum[value] >= 0) + left.transform_filter(alt.datum[value] < 0)
    return (bars + labels).properties(height=46 * len(frame) + 40)


st.title("Results")
st.caption(
    "Is the engine making money? An offer only pays when it changes what a Customer does, so every number here"
    " compares against sending nothing."
)

conn = data.open_db()
try:
    run = data.latest_policy_run(conn)
    now = clock.now(conn)
    holdout_pct = rules_store.current_rules(conn)[1].holdout_pct
    funnel = live_metrics.funnel(conn)
    groups = live_metrics.holdout_comparison(conn, holdout_pct)
    days = live_metrics.validation_by_day(conn)
    codes = live_metrics.failure_codes(conn)
finally:
    conn.close()

scope_names = {}
if run is not None:
    for s, label in (("sample", "{:,}-Customer sample"), ("population", "All {:,} Customers")):
        rows = run.rows[run.rows["scope"] == s]
        if not rows.empty:
            scope_names[s] = label.format(rows["customers"].iloc[0])
scopes = list(scope_names)
scope = (
    st.radio(
        "Customers in the Policy comparison",
        scopes,
        format_func=scope_names.get,
        horizontal=True,
        key="scope",
        help="Rules + Agent runs on the sample only, so the sample compares all four Policies.",
    )
    if scopes
    else None
)
policies = run.rows[run.rows["scope"] == scope].reset_index(drop=True) if scope else pd.DataFrame()

# --- 1. Policies ---------------------------------------------------------------------------------

st.header("Policies")
if run is None:
    st.info(
        "No Policy comparison yet. Run `uv run offer-engine simulate` (about 100 minutes on 10k Customers; add"
        " `--days 3` for a quick look), then reload this page."
    )
else:
    st.caption(
        f"Run {run.run_at:{data.TIME_FORMAT}} UTC: {run.days} simulated days from {run.start_at:{data.TIME_FORMAT}},"
        f" seed {run.seed}. Rerun with `{run.command}`."
    )
    scored = policies[policies["per_rupee"].notna()]
    if scored.empty:
        st.info("No Policy in this run spent anything, so there is nothing to compare per ₹.")
    else:
        chart = pd.DataFrame(
            {
                "name": scored["policy"],
                "per_rupee": scored["per_rupee"],
                "label": [f"{v:+.2f}" for v in scored["per_rupee"]],
                "spend": [rupees(v) for v in scored["spend"]],
                "margin": [rupees(v, sign=True) for v in scored["incremental_margin"]],
            }
        )
        st.altair_chart(
            bar_chart(
                chart,
                "per_rupee",
                "₹ of extra margin per ₹ of offer spend",
                "label",
                [
                    alt.Tooltip("name:N", title="Policy"),
                    alt.Tooltip("label:N", title="Per ₹ spent"),
                    alt.Tooltip("margin:N", title="Incremental Margin"),
                    alt.Tooltip("spend:N", title="Offer spend"),
                ],
            ),
            width="stretch",
        )
        st.caption(
            "Each bar is the margin a Policy earned beyond sending nothing, for every ₹1 it spent on offers. Longer"
            " is better; below zero means the offers cost more than they brought in."
        )
    st.dataframe(
        pd.DataFrame(
            {
                "Policy": policies["policy"],
                "Customers": policies["customers"].map("{:,}".format),
                "Offers sent": policies["offers_sent"].map("{:,}".format),
                "Claimed": policies["claimed"].map("{:,}".format),
                "Redeemed": policies["redeemed"].map("{:,}".format),
                "Offer spend": policies["spend"].map(rupees),
                "Incremental Margin": [rupees(v, sign=True) for v in policies["incremental_margin"]],
                "Per ₹ spent": ["baseline" if pd.isna(v) else f"{v:+.2f}" for v in policies["per_rupee"]],
            }
        ),
        hide_index=True,
    )

# --- 2. Live funnel vs Holdout -------------------------------------------------------------------

st.header("Live funnel vs Holdout")
st.caption(
    f"Live offers since the clock start, {clock.START:{data.TIME_FORMAT}}, up to {now:{data.TIME_FORMAT}}."
)
if funnel.sent == 0:
    st.info("No live Offers sent yet. Advance the Simulation Clock to run the Triggers.")
else:
    stages = [("Sent", funnel.sent), ("Claimed", funnel.claimed), ("Redeemed", funnel.redeemed)]
    chart = pd.DataFrame(
        {
            "name": [name for name, _ in stages],
            "count": [n for _, n in stages],
            "label": [f"{n:,} ({n / funnel.sent:.0%} of sent)" for _, n in stages],
        }
    )
    st.altair_chart(
        bar_chart(
            chart,
            "count",
            "Offers",
            "label",
            [alt.Tooltip("name:N", title="Stage"), alt.Tooltip("label:N", title="Offers")],
        ),
        width="stretch",
    )
    st.caption(
        "How many live offers went out, were claimed and were used at checkout. A big drop from Claimed to"
        " Redeemed means people like the offer but don't buy."
    )

treated_col, holdout_col = st.columns(2)
treated, holdout = groups.treated.per_customer, groups.holdout.per_customer
treated_col.metric(
    "Orders per Customer, can get offers",
    "—" if treated is None else f"{treated:.3f}",
    None if treated is None or not holdout else f"{(treated - holdout) / holdout:+.1%} vs Holdout",
    help=f"{groups.treated.orders:,} orders by {groups.treated.customers:,} Customers outside the Holdout.",
)
holdout_col.metric(
    f"Orders per Customer, Holdout ({holdout_pct:g}%)",
    "—" if holdout is None else f"{holdout:.3f}",
    help=f"{groups.holdout.orders:,} orders by {groups.holdout.customers:,} Customers who never get offers.",
)
st.caption(
    "The Holdout is a random group that never gets offers. If everyone else orders more per head, the offers are"
    " bringing in orders that wouldn't have happened."
)

# --- 3. Wasted on Sure Things --------------------------------------------------------------------

st.header("Wasted on Sure Things")
share = f" ({funnel.sure_thing_spend / funnel.spend:.0%} of {rupees(funnel.spend)})" if funnel.spend else ""
st.metric("Live offer spend on Sure Things", rupees(funnel.sure_thing_spend) + share)
spenders = policies[policies["spend"] > 0] if run is not None else policies
if not spenders.empty:
    chart = pd.DataFrame(
        {
            "name": spenders["policy"],
            "wasted": spenders["sure_thing_spend"],
            "label": [
                f"{rupees(w)} ({w / s:.0%} of spend)"
                for w, s in zip(spenders["sure_thing_spend"], spenders["spend"], strict=True)
            ],
        }
    )
    st.altair_chart(
        bar_chart(
            chart,
            "wasted",
            "₹ of offer spend on Sure Things",
            "label",
            [alt.Tooltip("name:N", title="Policy"), alt.Tooltip("label:N", title="On Sure Things")],
        ),
        width="stretch",
    )
    st.caption(
        "Sure Things would have bought anyway, so a discount they redeem is margin given away. Shorter bars are"
        " better."
    )

# --- 4. Validation -------------------------------------------------------------------------------

st.header("Validation")
decided = sum(d.decisions for d in days)
if not days:
    st.info("No live Decisions yet. Advance the Simulation Clock to run the Triggers.")
elif not any(d.rejections or d.fallbacks for d in days):
    st.success(f"All {decided:,} live Decisions passed Validation, with no Fallback.")
else:
    frame = pd.DataFrame(
        [
            {"day": f"{d.day:%-d %b}", "what": what, "count": n}
            for d in days
            for what, n in (("Rejected by Validation", d.rejections), ("Fallback used", d.fallbacks))
        ]
    )
    rejected, fallback = series_colors()
    chart = (
        alt.Chart(frame)
        .mark_bar(size=14, cornerRadiusEnd=4)
        .encode(
            x=alt.X("day:N", title="Simulated day", sort=None, axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("what:N"),
            y=alt.Y("count:Q", title="Decisions", axis=alt.Axis(format="d", tickMinStep=1)),
            color=alt.Color(
                "what:N",
                scale=alt.Scale(
                    domain=["Rejected by Validation", "Fallback used"], range=[rejected, fallback]
                ),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=[
                alt.Tooltip("day:N", title="Day"),
                alt.Tooltip("what:N", title="What"),
                alt.Tooltip("count:Q", title="Decisions"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(chart, width="stretch")
    st.caption(
        f"Each day, how many proposed offers broke a Rule and how often the rule-based Fallback stepped in, out of"
        f" {decided:,} live Decisions. Rising bars mean the agent is fighting the Rules."
    )
    if codes:
        st.dataframe(
            pd.DataFrame(
                {
                    "Failure": [code for code, _ in codes[:10]],
                    "What it means": [data.FAILURE_LABELS.get(code, "") for code, _ in codes[:10]],
                    "Times": [n for _, n in codes[:10]],
                }
            ),
            hide_index=True,
        )
        st.caption("The most common reasons a proposed offer was rejected.")

# --- 5. Lift by decile ---------------------------------------------------------------------------

st.header("Lift by decile")
graded = policies[[bool(d) for d in policies["lift_deciles"]]] if run is not None else policies
if graded.empty:
    st.info("Lift by decile comes from the Policy comparison. Run `uv run offer-engine simulate` first.")
else:
    names = graded["policy"].tolist()
    name = st.selectbox("Policy", names, index=len(names) - 1, key="decile_policy")
    deciles = graded[graded["policy"] == name]["lift_deciles"].iloc[0]
    estimated, truth = series_colors()
    frame = pd.DataFrame(
        [
            {"decile": d["decile"], "what": what, "lift": d[key], "offers": d["offers"]}
            for d in deciles
            for what, key in (("Estimated Lift", "estimated_lift"), ("Ground Truth Lift", "true_lift"))
        ]
    )
    chart = (
        alt.Chart(frame)
        .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64, filled=True))
        .encode(
            x=alt.X("decile:O", title="Decile of Estimated Lift (1 = lowest)", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("lift:Q", title="Mean Lift in buying chance", axis=alt.Axis(format="%")),
            color=alt.Color(
                "what:N",
                scale=alt.Scale(domain=["Estimated Lift", "Ground Truth Lift"], range=[estimated, truth]),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=[
                alt.Tooltip("decile:O", title="Decile"),
                alt.Tooltip("what:N", title="What"),
                alt.Tooltip("lift:Q", title="Mean Lift", format=".1%"),
                alt.Tooltip("offers:Q", title="Offers"),
            ],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch")
    st.caption(
        "Offers sorted into ten equal groups by how much the engine expected them to help. If its estimates are"
        " right, the Ground Truth line climbs from left to right along with the Estimated one."
    )
