# Grilling session Q&A

Record of the planning session on 2026-10-22 that turned the draft plan into `docs/PLAN.md` v2. Each entry gives the question, the options weighed, what was decided and why. Terms follow `GLOSSARY.md`.

## Round 1: foundations

**Q1. Team and timeline?**
Decided: solo, about 1–2 weeks. This sets the cut line in the milestones.

**Q2. What does the store sell?**
Options: general Indian marketplace, fashion only, grocery/quick-commerce.
Decided: general Indian marketplace in ₹ with 5–6 categories whose margins differ widely (electronics ~8%, fashion ~45%). Margin-floor Rules then change outcomes by category, and the setting is familiar.

**Q3. How does a real person become a Customer?**
Options: assign a synthetic profile on `/start`; build a profile from a quiz and in-bot browsing; both.
Decided (user's own answer): use several Telegram bots as Customers instead of real classmates. Classmates can come later; the brief doesn't strictly require them. Checked: Bot API 10.0 (May 2026) lets bots message each other by username when both enable Bot-to-Bot Communication Mode in BotFather.

**Q4. Does the agent choose freely or from a pre-filtered set?**
Options: Rules first compute the Eligible Set and the agent picks from it; the agent proposes anything and only Validation stops it.
Decided: Rules first, Validation still re-checks, rule-based Fallback on failure. Free proposals would make rejection and Fallback the normal path. Recorded in ADR 0001.

**Q5. Stack?**
Decided: Python 3 + uv, python-telegram-bot, SQLite, Anthropic SDK, Streamlit. Data generation and simulation are pandas/numpy work, and Streamlit gives a console cheaply.

**Q6. How do we prove offers work?**
Decided: give every synthetic Customer a hidden Ground Truth response and score Policies offline on ~10k Customers by Incremental Margin, plus a live Holdout. A few dozen live recipients can't show significance. Recorded in ADR 0002.

**Q7. Where does the bot run?**
Decided: laptop in development, an always-on host (Railway, Fly or a free-tier VM) for judging, polling mode in both.

## Round 2: customer bots and time

**Q8. What drives a Customer Bot's behaviour?**
Options: Ground Truth coin flip only; pure LLM role-play; Ground Truth plus LLM-written replies.
The user asked whether pure role-play was feasible. It is: the bot sends the Persona Card, the Offer and the simulated date to Claude, gets back a structured action, and replies by text (`/claim CODE`), since a bot can't press another bot's inline buttons. The problems are behavioural. LLM customers claim almost everything, drift from the offline simulator, can't be reproduced without logging, and invite "AI persuading AI" objections. Three variants were weighed: pure role-play, role-play briefed with its hidden tendencies, and bounded role-play.
Decided: bounded role-play. Ground Truth sets the base chance, the agent rates the message's fit and nudges the chance by at most ±30%, a weighted coin flip decides, and the agent writes a reply that matches. Haggling within Rules is a later feature. Recorded in ADR 0004.

**Q9. How do Customer Bots relate to the 10k population?**
Decided: 6–8 hand-picked showcase Customers get bots (at-risk high value, new one-order, deal hunter, expiring points, cart abandoner, a Sure Thing who should get No Offer). The rest are simulated offline only.

**Q10. Can humans use the Offer Bot too?**
Decided: yes, as Testers, through the same code path as Customer Bots. Judges will open the bot themselves.

**Q11. Real time or a Simulation Clock?**
Decided: one Simulation Clock for every Rule, event and expiry, advanced from the console. Rules work in days and weeks, so on real time no cooldown or lapse would show up in a demo. Recorded in ADR 0003.

**Q12. What triggers a Decision?**
Decided: event Triggers as the core (cart abandoned, points expiring, long gap since last order), a Daily Sweep for win-back, and `/offers` on request.

**Q13. How do marketers edit Rules?**
Options: YAML in the repo, Streamlit forms, Google Sheet.
Decided: Streamlit forms with plain-English labels, versioned in SQLite with revert, and a "preview impact" dry run on the population before saving.

**Q14. What shape is the Ground Truth?**
The user asked twice how anyone knows a Customer's chance of accepting an offer.
On the data side, we invent the numbers in a controlled way. Each Customer gets a small formula per Offer Type, `p(d) = base + maxLift · (1 − e^(−d/k))`. Its parameters come from visible behaviour plus noise: recent frequent buyers get a high base, heavy coupon users high discount sensitivity, small baskets and tier-2/3 cities high free-shipping sensitivity. A check script then compares aggregate behaviour with sourced benchmarks (`docs/research/ecommerce-benchmarks.md`).
On the engine side, the engine never sees Ground Truth. It learns Estimated Lift from synthetic history that includes partly random past Offers, starting with per-segment averages and later a two-model uplift learner. The dashboard grades Estimated Lift against Ground Truth.
Worked example: Rahul buys at 5% with no offer, 22% with 10% off, 26% with 20% off and 28% with free shipping. Free shipping at ₹40 beats 20% off at ₹300, which a single "Persuadable" label could never show.
Decided: as described. Response Class labels are derived from the formulas, for reporting.

**Q15. How do we afford the agent in offline comparisons?**
Decided: rules-only Policies run on all ~10k Customers; Rules + Agent runs on a stratified ~500 sample with the fastest Claude model and cached results.

## Round 3: Testers, Rules, metrics

**Q16. How does a Tester get a Customer?**
Decided: pick from Persona Card buttons or "Surprise me". Each Tester gets their own copy, so two judges playing the same Customer don't use up each other's frequency caps.

**Q17. Who moves the clock?**
Decided: only the console, by manual +1 day or an auto mode for demos. Bot users see the simulated date but can't change it.

**Q18. What happens when Rules conflict?**
Decided: the strictest wins, and every Decision records its Binding Rule. A marketer can predict "strictest wins" without help.

**Q19. What happens to live Offers when a Rule changes?**
Decided: Offers already sent are honoured under the rule version they passed, and new Rules apply to new Decisions only. The console has an emergency "withdraw outstanding Offers".

**Q20. What does Claim mean without a store?**
Decided: Claim means the Customer took the code. Redemption is a simulated purchase using it before expiry. They are tracked as separate metrics, because Claim rate alone says nothing about money.

**Q21. How is the Holdout set up?**
Decided: a permanent 10% (a Rule setting), chosen by hashing the Customer ID. One Customer Bot sits in the Holdout so the demo shows a Customer who gets nothing on purpose.

## Round 4: timing, budget, delivery

**Q22. Does the agent choose when to send?**
Decided: yes, now or at hour H, within the allowed hours and maximum delay set by the Rules. This covers the "when" in the brief.

**Q23. How is budget counted?**
Decided: Reserved Budget at worst-case cost by default, so overspending can't happen. A console toggle switches to expected cost and shows an overspend warning.

**Q24. What does an Offer message look like?**
Decided: an Offer Card image whose terms are drawn by code from the validated Offer, plus an agent-written caption and buttons Claim / Not now / Stop. The agent can't misstate terms it doesn't write. Recorded in ADR 0005.

**Q25. Who writes Persona Cards?**
Decided: an agent generates them from Customer data, they get reviewed, then frozen so demos repeat.

**Q26. How do opt-outs work?**
Decided: Opt-out is absolute until the Customer starts again. Three "Not now" in 14 simulated days trigger a 14-day Fatigue Pause, which keeps the engine from creating Sleeping Dogs.

## Round 5: scope and quality

**Q27. Which Offer Types at launch?**
The draft wrongly listed cart recovery and points expiry as Offer Types. They are Triggers.
Decided: % off a category (with a ₹ cap), flat ₹ off above a minimum basket, free shipping, points multiplier and Nudge (no incentive, zero cost), plus No Offer. Bundles and tiered offers are out.

**Q28. Does the agent pick what to feature?**
Decided: yes, the category and a product or two, taken only from the Customer's own recent events or affinities. Validation checks this.

**Q29. How is the caption checked?**
Decided: a Caption Check inside Validation rejects captions with numbers, amounts or deadlines that differ from the Offer, promises not in the Offer, invented urgency, or excess length. An adversarial test set of bad captions and manipulative customer replies ships with the code and passes.

**Q30. Time-limited Campaigns?**
Decided: yes, after the core works. A Campaign is a named range of simulated dates that temporarily changes named Rules and may loosen them. The synthetic history includes a festive spike.

**Q31. Headline metric?**
Decided: Incremental Margin per ₹ of offer spend, across the No Offers, Blanket 20%, Rules Only and Rules + Agent Policies. Supporting views: live funnel against the Holdout, spend wasted on Sure Things, Validation rejections and Fallbacks, lift by decile.

**Q32. Testing approach?**
Decided: the Rules engine and Validation are pure functions built test-first, with a property test that random rule-breaking proposals never pass. The bot and console are tested by hand.

**Q33. Process layout?**
Decided: three long-running processes sharing SQLite (Offer Bot, a Customer Bot simulator holding all customer tokens, the console), plus scripts. One start command. Tokens live in `.env`, with a committed `.env.example`.

## Round 6: execution

**Q34. Milestones?**
Decided: M1 bot-to-bot plumbing, M2 Rules and Validation, M3 agent and Caption Check, M4 full data and Ground Truth, M5 console and live Customer Bots, M6 offline simulator and dashboard, M7 advanced features and deployment. M1–M6 is the submission; deployment and README are mandatory. If bot-to-bot messaging fails in M1, switch to Testers only.

**Q35. Git housekeeping?**
Decided: rename `master` to `main`, add a `.gitignore` that excludes `.env` and databases from the first commit, and commit the planning docs.

**Q36. Bot setup help?**
Decided: an interactive setup script in M1 walks through creating the bots in BotFather, enabling Bot-to-Bot Communication Mode and filling `.env`.

## Round 7: before ticketing

**Q37. Which Customers does the live world simulate when the clock advances?**
Options: all ~10k Customers, with the agent deciding only for Customers that have a chat; only the showcase Customers and Testers' copies.
Decided: all ~10k. The agent decides for Customers attached to a Customer Bot or Tester, and the rule-based chooser decides for the rest. Ground Truth settles outcomes. This gives a real live funnel against the Holdout and budgets that actually run down, and the offline Policy simulator reuses the same day-step code. Recorded in `docs/PLAN.md` §2.5.

**Q38. How does a human Tester's Claim become a Redemption?**
Options: a Ground Truth coin flip; a "Buy now" button the Tester presses; Claims only.
Decided: a weighted coin flip on the Customer's Ground Truth, without the agent nudge Customer Bots get. The Offer Bot then reports the simulated order. A button would let human whims into the Redemption metrics. Recorded in `docs/PLAN.md` §4.1.

## Round 8: building T14

**Q39. How long does a past Offer control the Customer's purchases?**
Options: the 3-day validity window, as T14 first said; 7 days, Ground Truth's horizon.
Decided: 7 days. Organic orders in the 7 days after the send are removed, and the Customer buys once with chance `p_buy`, at a time inside the validity window, so the purchase is the Redemption. Ground Truth's `p_buy` is a 7-day chance and T16 compares 7-day purchase rates. With a 3-day window, organic orders on days 4–7 would add about 4/7 × base to every Offer's measured Lift, most for Sure Things, so the engine would learn to target them. T18 should suppress 7 days too.

**Q40. Which base does a past Offer's `p_buy` use?**
Options: the stored Ground Truth, which reflects the Customer at the end of history; the base at the moment of the Offer.
Decided: the base at the moment. It is recomputed from traits, whether the Customer had lapsed by then and that day's season demand; max Lift and k stay as stored, and a Sleeping Dog's negative max Lift is rescaled with the base. Otherwise Customers who lapse later look as if Offers cut their buying, and festive Offers suppress real demand.

Refined while building T14: a Customer who buys keeps the organic orders after the Redemption. Only a Customer who doesn't buy loses the whole 7 days. T16's 7-day "bought at least once" rate still equals `p_buy`, and heavy buyers keep their volume: removing all 7 days took orders per buyer from 4.9 to 3.8, below calibration target 5a.

## Round 9: building T15

**Q41. Should T15 change how past Offers are redeemed to meet calibration targets 3, 3a and 4?**
Options: keep "every buyer in the window redeems" and record the misses; let a buyer who would have bought anyway use the code only with some chance per trigger; raise discount Lift and make heavy buyers abandon fewer carts.
Decided: record the misses. On 10k Customers cart recovery is 30% (target 8–15%), 96% of recovered carts would have bought anyway (45–75%), and Redemption per send is 15% targeted (1.5–5%) and 4% broadcast (0.1–1%). The benchmarks are low mostly because recipients never read the message, while our Customers read every Offer. The broadcast target needs a mean 7-day buying chance under 1% across recipients, against target 1a's 4–8% for active Customers, so no tuning of T05 or T12 meets both. T16 learns from 7-day purchase rates, which the misses don't affect, and Sure Things keep costing margin, which is the problem the engine exists to fix.

## Round 10: building T25

**Q42. Does a Tester's copy carry the source Customer's past Offers?**
Options: events and points only, as T25 first said; also the finished Offers of the last 180 days.
Decided: also the finished Offers (redeemed, expired, dismissed, withdrawn), with new codes and the copied events linked to them. Estimated Lift's coupon-user segment, the agent's prompt, frequency caps and cooldowns all read past Offers. Without them the engine would decide for a different Customer from the one the Persona Card describes. Open Offers (queued, sent, claimed) stay with the source, so none of the source's outcomes reach the Tester.

Refined while building T25: every past Offer that is finished or expired, whatever its age, not only the last 180 days. The pipeline reads all of a Customer's Offers, and a deal hunter's Redemptions can all be older than 180 days: Sameer Reddy's copy lost all 12 and stopped counting as a coupon user.
