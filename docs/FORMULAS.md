# Formulas

Every formula the engine and the simulator use, with the file that holds it. The two sides never share numbers (ADR 0002):

- **The simulator** knows each Customer's hidden Ground Truth and uses it to decide who buys. The engine never reads it.
- **The engine** sees only what a real marketplace would: past Offers and orders. It works from Estimated Lift.

Comparing the engine's Estimated Lift with the simulator's true Lift shows how good the engine's guesses are.

All chances are for buying **within 7 days**. `clamp(x)` limits `x` to the range 0 to 1.

---

## Part 1. The simulator (hidden from the engine)

### 1.1 Base chance: buying with no Offer

`sim/ground_truth.py` › `organic_weekly_chance`

```
per_session = Σ over categories ( affinity share × cart chance × order chance given a cart )
sessions    = 7 × visit_rate × lapse factor × demand
base        = 1 − e^(−sessions × per_session)
```

Sessions arrive at random (Poisson), so the chance of at least one order in 7 days is `1 − e^(−expected orders)`.

| Term | Value |
|---|---|
| cart chance | `min(0.95, CART_RATE[category] × buy_propensity × demand)` (`sim/generate/history.py` › `funnel`) |
| order chance given a cart | `ORDER_GIVEN_CART[category]`, from 0.14 (electronics) to 0.30 (grocery) |
| lapse factor | 0.03 if the Customer has lapsed (churned), else 1 |
| demand | `√season(day)`. Season multiplies weekends, the festive window and the peak sale week. The square root puts half the effect on visits and half on conversion |

Ground Truth is drawn at normal demand (`demand = 1`). When an Offer is sent, the simulator recomputes `base` for that day's season and lapse state.

### 1.2 Ground Truth buying chance with an Offer

`sim/ground_truth.py` › `p_buy`

```
p_buy(depth) = clamp( base + max_lift × (1 − e^(−depth / k)) )
```

The Offer adds up to `max_lift` to the base chance. Deeper Offers add more, but with diminishing returns: at `depth = k` the Offer gives about 63% of `max_lift`, and at `3k` about 95%.

Each Customer has one hidden formula per Offer Type, so five sets of `max_lift` and `k`.

**Depth** says how strong an Offer is, in its type's units (`offer_depth`):

| Offer Type | depth |
|---|---|
| % off a category | `pct / 100` |
| flat amount off above a minimum basket | `amount / category's average basket` |
| points multiplier | `multiplier − 1` |
| free shipping | `1` |
| Nudge | `1` |

**max_lift** is the most the Offer Type can add. It is drawn once per Customer from their traits, times noise (`draw`):

| Offer Type | mean max_lift |
|---|---|
| % off, flat off | `0.13 × coupon_affinity²` |
| points multiplier | `0.4 × 0.13 × coupon_affinity²` |
| free shipping | `0.012 × basket_size^(−1.5) × city tier factor` (tier 1: 0.6, tier 2: 1.0, tier 3: 1.5) |
| Nudge | `0.008` |

The noise is lognormal with mean 1 and σ = 0.5. So Customers who like coupons respond to discounts, and small-basket Customers in smaller cities respond to free shipping.

**k** is the saturation depth: 0.12 for % off and flat off, 0.5 for free shipping and Nudge, 1.0 for points. Each Customer's `k` varies around it (lognormal, σ = 0.2).

**Sleeping Dogs** are 3% of Customers. Any Offer makes them less likely to buy:

```
max_lift = −base × U(0.3, 0.8)        for every Offer Type
```

If `base` changes later (season, lapse), `with_base` scales this drop in proportion.

### 1.3 True Lift

`sim/offline.py` › `true_lift`

```
true_lift = p_buy(with the Offer's depth, on the send day) − base(on the send day)
          = max_lift × (1 − e^(−depth / k))          unless the clamp kicks in
```

The Results page shows it as "Ground Truth Lift". The live view shows it in "What the simulator knows".

### 1.4 Response Class

`sim/ground_truth.py` › `response_class`

Uses the % off formula at a typical 15% off. Checked in this order:

| Response Class | Condition |
|---|---|
| Sleeping Dog | Lift < 0 |
| Sure Thing | base ≥ 0.08 |
| Persuadable | Lift ≥ 0.05 |
| Lost Cause | everyone else |

Calibration aims for 70–85% Lost Causes, 5–15% Sure Things, 3–10% Persuadables and 1–5% Sleeping Dogs.

### 1.5 Who actually buys

`sim/world/outcomes.py`, `customer_sim/roleplay.py`

Every outcome ends in a weighted coin flip. The chance depends on the kind of Customer:

| Customer | Chance of buying |
|---|---|
| Customer without a chat | `p = p_buy(depth)` |
| Tester who claimed the Offer | `p / (p + 0.25 × (1 − p))`, because a quarter of non-buyers also claim, so a Claim makes buying more likely |
| Customer Bot | `clamp( p × (1 + 0.3 × fit) )`, where the agent scores how well the message fits, `fit` from −1 to 1 (ADR 0004) |

The Customer Bot's message fit can move the chance by at most ±30% of itself. Ground Truth still sets the base.

---

## Part 2. The engine (what the decision pipeline uses)

### 2.1 Estimated Lift

`lift/segment_lift.py` › `fit` (run with `offer-engine lift fit`)

The engine learns Lift from the history's random past Offers, per **segment** and Offer Type. A segment is loyalty tier × days since the last order (≤30, 31–90, more than 90 or never) × coupon user (redeemed at least 2 past Offers).

```
observed_lift = (buyers after a past Offer / past Offers)
              − (buyers after a no-offer moment / no-offer moments)
```

A no-offer moment is a time an Offer could have gone out but didn't: an abandoned cart, 45 days without an order, or the weekly Friday 18:00 broadcast slot. Moments inside a past Offer's 7 days don't count. Holdout Customers are left out.

Past Offers had random depths, so the observed Lift is scaled up to the Lift at full depth:

```
saturation    = 1 − e^(−depth / k_prior)            for each past Offer
estimated_lift = observed_lift / mean(saturation)
```

A segment with fewer than 30 past Offers of a type uses that type's average over all segments.

### 2.2 Lift at a given depth

`choosers/priors.py` › `lift_at`

```
lift(depth) = estimated_lift × (1 − e^(−depth / k_prior))
```

This is the same curve shape as Ground Truth, but with guessed `k` values, not Ground Truth's. Until `lift fit` runs, a fixed prior replaces `estimated_lift`:

| Offer Type | prior max Lift | k_prior |
|---|---|---|
| % off | 0.12 | 0.10 |
| flat off | 0.10 | 0.10 |
| free shipping | 0.04 | 0.50 |
| points multiplier | 0.05 | 1.00 |
| Nudge | 0.02 | 0.50 |

The engine assumes a base chance of 0.10 for everyone (`BASE_BUY_CHANCE`).

### 2.3 Offer cost

`rules.py` › `offer_cost`, `budget.py` › `redemption_cost`

| Offer Type | worst-case cost | cost if redeemed |
|---|---|---|
| % off | `cap` | `min(pct × basket / 100, cap)` |
| flat off | `amount` | `amount` |
| free shipping | shipping fee | shipping fee |
| points multiplier | `(multiplier − 1) × basket × 0.1 × point value` | same |
| Nudge | 0 | 0 |

`basket` is the category's average basket, or the catalog average when the Offer has no category. A Customer earns 0.1 points per ₹.

### 2.4 Valuation

`choosers/rules_chooser.py` › `assess`, shown as the Valuation stage in the live view (`trace.py`)

```
lift           = lift_at(depth, estimated_lift)
redeem_chance  = clamp(0.10 + lift)
expected_cost  = redeem_chance × cost if redeemed
value          = lift × expected margin − expected_cost
```

`expected margin` is `average basket × margin % / 100` for the Offer's category, else the Customer's focus category, else the catalog average.

For each option in the Eligible Set, the engine tries a grid of terms (for example several % off levels and caps) and keeps the terms with the highest value. The rules chooser sends the best option if its value is above 0, else No Offer. The agent sees the same Eligible Set with its Estimated Lift and may choose differently, within the Rules.

The value charges the full expected cost but credits only the margin the Offer causes. An Offer to a Sure Thing has low Lift and a high chance of redemption, so its value comes out negative.

### 2.5 Weekly budget

`budget.py` › `budget_state`, `rules.py` › `eligible_set`

```
remaining = max(weekly_budget − spent − reserved, 0)
```

- `spent` is what this week's Redemptions actually cost.
- `reserved` is the cost of every outstanding, unexpired Offer: worst-case cost by default, or expected cost in expected-cost mode.

The smaller of `remaining` and the per-Offer cost cap sets the most an option's terms may cost, such as the highest cap on a % off or the largest flat amount. An option leaves the Eligible Set when even its smallest terms cost more (for example a ₹50 cap).

### 2.6 Holdout

`rules.py` › `in_holdout`

```
in Holdout ⇔ (first 8 bytes of SHA-256(Customer ID), as a number) mod 10,000 < holdout_pct × 100
```

A hash makes the Holdout permanent and the same on every run. A Tester copy shares its source Customer's Holdout.

---

## Part 3. Scoring the results

### 3.1 Margin per Customer

`sim/offline.py`

```
margin = Σ orders (amount × margin %) − Σ returns (amount × margin %) − Σ Offer costs redeemed
```

### 3.2 Incremental Margin

`sim/metrics.py` › `incremental_margin`

```
Incremental Margin   = Σ over Customers ( margin under the Policy − margin under No Offers )
per ₹ of offer spend = Incremental Margin / total cost of redeemed Offers
```

Both runs share the same Customers, start time, days and seed, so the only difference is the Offers. This is the headline number the engine optimises.

### 3.3 Lift by decile

`sim/metrics.py` › `lift_deciles`

Sent Offers are sorted by Estimated Lift and split into 10 equal groups. Each group shows its mean Estimated Lift next to its mean true Lift. If the engine's estimates are good, the true Lift rises from decile 1 to decile 10.
