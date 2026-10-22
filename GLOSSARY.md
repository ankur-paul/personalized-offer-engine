# Personalised Offer Engine

Decides which offer, if any, each customer of a fictional Indian online marketplace should receive and when, within limits set by the marketing team, and delivers it over Telegram.

## People and profiles

**Customer**:
A synthetic shopper of the marketplace, with a profile and a history of behaviour. All customers are generated; none are real people.
_Avoid_: User, account, shopper

**Customer Bot**:
A Telegram bot that embodies one Customer, receives that Customer's offers, and acts on them as that Customer would.
_Avoid_: Fake user, test bot

**Persona Card**:
A short plain-language description of a Customer (situation, needs, habits) given to a Customer Bot or shown to a Tester. It never reveals Ground Truth.
_Avoid_: Profile (the profile is the full data record), bio

**Tester**:
A human who starts the Offer Bot and is assigned a Customer to play, receiving that Customer's offers.
_Avoid_: Classmate (unless they literally are one), user

**Offer Bot**:
The single Telegram bot through which the platform delivers offers.
_Avoid_: Main bot, the bot

## Offers and decisions

**Trigger**:
Something that prompts a Decision for a Customer: an event (cart abandoned, points about to expire, long gap since last order), the Daily Sweep, or the Customer asking.
_Avoid_: Campaign, event (an event is only one kind of trigger)

**Daily Sweep**:
The once-per-simulated-day pass that considers every Customer for an Offer.

**Offer**:
A specific incentive sent to one Customer at one time, such as 15% off fashion valid for 48 hours.
_Avoid_: Promo, deal, coupon

**Offer Type**:
A family of offers that marketing configures, such as percentage discount, flat amount off, free shipping or points multiplier.
_Avoid_: Offer template, campaign

**Offer Card**:
The image that presents an Offer, with its terms (amount, minimum basket, expiry) drawn by code from the validated Offer, alongside an agent-written caption.

**Nudge**:
An Offer Type with no incentive: a reminder such as an abandoned cart or expiring points. It costs nothing.
_Avoid_: Reminder offer, cart recovery (cart recovery is a Trigger)

**Campaign**:
A named range of simulated dates during which specific Rules are temporarily changed, and may be loosened, such as a Diwali sale.
_Avoid_: Using "campaign" for an Offer Type, a Trigger or a batch send

**No Offer**:
A deliberate decision to send a Customer nothing. It is a valid outcome of every decision.

**Rule**:
A business limit written by marketing that every Offer must satisfy, such as a maximum discount, a margin floor, a frequency cap or a budget.
_Avoid_: Guardrail, constraint, policy

**Eligible Set**:
The Offer Types and parameter ranges the Rules allow for one Customer at one moment.
_Avoid_: Candidates, options

**Decision**:
The record of choosing an Offer (or No Offer) for a Customer: what was chosen, by whom (agent or fallback), why, and whether it passed validation.
_Avoid_: Recommendation, prediction

**Binding Rule**:
The Rule that set the tightest limit in a Decision, e.g. the margin floor that capped a discount at 6%. When Rules conflict, the strictest always wins.

**Validation**:
The check of a proposed Offer against every Rule before it is sent, including the Caption Check.

**Caption Check**:
The part of Validation that rejects an agent-written caption which contradicts or adds to the Offer's terms, invents urgency, or is too long.

**Fallback**:
The rule-based Offer used when the agent's proposal fails Validation or the agent is unavailable.

**Opt-out**:
A Customer's instruction to receive no more offers, which nothing may override until they start again.
_Avoid_: Unsubscribe (acceptable in conversation), block

**Fatigue Pause**:
A temporary stop on offers after a Customer repeatedly dismisses them.

**Reserved Budget**:
The part of a budget held back for Offers already sent but not yet redeemed or expired, counted at each Offer's worst-case cost by default.

**Claim**:
A Customer accepting an Offer and receiving its code. It shows interest only; no money changes hands.
_Avoid_: Conversion, acceptance

**Redemption**:
A purchase that uses a Claimed Offer's code before it expires.
_Avoid_: Conversion (acceptable in conversation), usage

## Time

**Simulation Clock**:
The single clock of the synthetic marketplace. Every Rule, event and expiry is measured in simulated time; it moves only when advanced.
_Avoid_: Server time, now

## Measuring effect

**Response Class**:
How a Customer's buying changes when given an offer: Persuadable (buys only with it), Sure Thing (buys anyway), Lost Cause (doesn't buy either way) or Sleeping Dog (less likely to buy because of it).
_Avoid_: Segment (segments are what we observe; response class is the hidden truth)

**Lift**:
The change in a Customer's chance of buying caused by a given Offer; negative for Sleeping Dogs.
_Avoid_: Uplift (acceptable in conversation), impact

**Estimated Lift**:
The engine's prediction of Lift, learned from past Offers; the only kind of Lift the decision pipeline sees.

**Ground Truth**:
Each Customer's hidden Response Class and response curve, known to the simulator and never to the decision pipeline.

**Holdout**:
Customers permanently and randomly withheld from receiving offers so that the effect of offers can be measured against them.
_Avoid_: Control (acceptable in conversation), exclusion list

**Policy**:
A way of deciding Offers across the whole population, such as No Offers, Blanket 20%, Rules Only or Rules plus Agent, compared against each other in simulation.
_Avoid_: Strategy, model

**Incremental Margin**:
Margin earned because of offers, minus offer costs, compared with the Holdout.
_Avoid_: Uplift revenue, ROI
