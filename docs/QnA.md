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

## Round 11: building T26

**Q43. Does Blanket 20% send to a Customer who already holds an unexpired Offer?**
Options: one live Offer at a time; event Triggers only, skipping the Daily Sweep; literally every Trigger, overlapping Offers allowed.
Decided: one live Offer at a time. Blanket sends at every Trigger, the Daily Sweep included, unless the Customer holds an Offer that is queued, sent or claimed and not expired. It ignores every other Rule. The Daily Sweep is a Trigger, so the literal reading sends every Customer a new Offer each day, and each Offer draws its own 7-day buying chance: purchases would multiply and Blanket would look good because of the simulator, not the Policy.

## Round 12: the demo (2026-10-26)

The live demo felt non-deterministic and hard to follow, for five reasons:

- The offer agent and every Customer Bot reply call Claude fresh each time.
- Each rehearsal changes the database, and only `generate` resets it, in about 6.5 minutes.
- All Customers share one random stream per simulated hour, so one extra Offer moves other Customers' outcomes.
- Delivery and Customer Bot replies run on wall-clock time.
- The console shows counts, not one Decision moving through the pipeline.

A Decision also stores only its final reason, Binding Rule and Validation failures. It doesn't store the Eligible Set, which Rule removed which option, or the Lift per option.

**Q44. How is the live engine view built?**
Options: a separate web page fed live by a small FastAPI server; custom components inside Streamlit; one web app replacing Streamlit.
Decided: a separate page. The server pushes each pipeline stage to an HTML/SVG page as it happens, so the page can animate. Streamlit reruns the whole page on every update. The Streamlit console keeps the Clock, Decision log, Rules and Results pages. Deploy exposes one more port.

**Q45. What does the agent do in the demo?**
Options: replay recorded answers, with a switch to call Claude live; always live; always replay.
Decided: replay by default, for both the offer agent and the Customer Bots. Rehearsal and the judged run then show the same picks and captions. The live switch shows a real Claude call behind them.

**Q46. Which world does the demo run on?**
Options: the 10k seed-7 world from a snapshot, with the view following one spotlight Customer at a time and world totals as counters; a curated world of about 300 Customers.
Decided: the 10k snapshot. A reset copies it back in seconds, and the results numbers stay those of the world on screen.

**Q47. Demo work before or after deploy and README?**
Decided: before. T29 deploys what will be shown, and T30's `docs/DEMO.md` follows the demo scenarios. The host account can be set up meanwhile.

Before the next questions, one Decision for C09823 (the cart-abandoner persona) was traced stage by stage on a copy of the database. Claude picked a ₹0 Nudge, and the rules chooser agreed, since every paid option had negative value. Ground Truth makes her a Lost Cause: 3.3% chance of buying within 7 days, 5.3% with the Nudge, 6.5% with free shipping, which her segment's Estimated Lift puts at −0.7%. Her Customer Bot therefore replies "Not now" about 94% of the time.

**Q48. Which scenarios does the demo script include?**
Decided: all four groups.
- Saving margin: a Sure Thing gets No Offer, a Lost Cause gets a Nudge, a Persuadable gets a real discount.
- Hard limits: a Holdout Customer and an opted-out Customer get nothing, and three "Not now" replies start a Fatigue Pause.
- Safety net: a demo-only switch tampers with the agent's answer so that Validation rejects it and the Fallback runs, and a manipulative caption is blocked.
- Marketer controls: a Rule change flips a Decision, shown with Preview impact, and emergency withdraw pulls outstanding Offers.

**Q49. How does the demo settle whether a Customer buys?**
Options: show the chance with a coin flip seeded per scenario; script each outcome; a live random flip.
Decided: show the chance and what moved it, and seed the flip per scenario. Every run gives the same outcome, and the outcome still comes from Ground Truth as ADR 0004 says. Buying chances are 3–10%, so a live flip mostly shows "Not now".

**Q50. Does the live view show Ground Truth?**
Decided: yes, in a separate panel marked "hidden from the engine", next to the Estimated Lift. Judges see how far the estimate is from the truth. The pipeline still never reads Ground Truth, and the boundary test keeps passing.

**Q51. How is the demo driven?**
Options: scenario buttons on the live page plus one Tester exchange on a phone; the console clock; Telegram only.
Decided: scenario buttons on the live engine page fire and animate each scenario, with the Offer Card and the Customer Bot's reply shown on the page. One real Telegram exchange as a Tester runs on the phone.

**Q52. Which Customer does `real-discount` use? (T37, 2026-10-26)**
Options: C01588, a Persuadable with no chat, whom the rules chooser gives 7% off fashion; keep C01377 and retitle the scenario around the Nudge; keep C01377 and let any Offer pass.
Decided: C01588. C01377 has a Customer Bot chat, so the agent decides for her, and Claude gave her a free Nudge on her grocery cart instead of the rules chooser's 6% off fashion. The scenario now shows no agent caption and no Customer Bot reply: its outcome is the plain Ground Truth draw.

**Q53. How should the live engine view look? (T39, 2026-10-26)**
Asked: will the page be easy to understand, easy on the eyes and clean? T39 set the behaviour but no layout or visual rules, and by T40 the page holds about eight panels.
Decided: T39 gets a "Look and feel" section. Scenarios and the ticker sit in a left rail, the diagram goes across the top, and below it one card shows the current stage. T40's panels appear only after the Offer stage. Glossary terms get tooltips taken from `GLOSSARY.md`. T38's scenario lines become a numbered "What the scenario did" list. The page uses one accent colour plus green, red and grey for status, the system font and an 8 px spacing grid. The earlier T39 claim was cancelled before any work, so the ticket is claimed fresh with this section in it.

## Round 13: after the demo pass (2026-10-26)

Ankur ran the 10k world to 5 Dec and asked why so few Offers go out, why the agent rarely runs and why the header numbers vanish. The live database showed 7,384 Offers on 1 Dec and 7,017 on 2 Dec, 13,341 of them ₹0 Nudges from the Daily Sweep, then 29 and 134. From 3 Dec most Decisions stop at the frequency cap (14,125 so far). The agent made 21 of about 40,000 Decisions, all for the 7 chat-attached Customers, as PLAN §2.5 intends. The header counts only the current simulated day, so it drops to 0 at each simulated midnight.

**Q54. How should the live page show what the world is doing?**
Options: charts on the live view; charts on the console's Results page; both.
Decided: a chart module whose data comes from one Python function and one JSON route, and whose page part is one JS file and one CSS file, so it can move to another page later. It goes on the live view first. Four charts: Decisions per simulated day (Offers and No Offer by reason), the funnel with the Holdout comparison, Offers by hidden Response Class, and the chooser split with the chat-attached Customers. Built in T41.

**Q55. What should the header counters show?**
Decided: today's number and, beneath it, the total since the clock start, so the numbers no longer drop to 0 at midnight. T41.

**Q56. Should a ₹0 Nudge be held back? (left to Claude)**
Options: Nudges skip the frequency cap; the Daily Sweep sends no Nudges; price each message's opt-out risk into the value; leave it.
Decided: a Nudge is eligible only when there is something to remind about, an abandoned cart or expiring points, as `GLOSSARY.md` defines it. A Nudge from the Daily Sweep, a long gap, a first delivery or `/offers` reminds the Customer of nothing, yet it uses one of the two weekly slots and risks an opt-out. Skipping the cap would let the sweep message 7,000 Customers a day, which is spam. Pricing opt-out risk needs a new Rule and tuning. Built test-first in T42.

## Round 14: live view design pass (2026-10-26)

A design critique of the live view at 1280 px found that playback often happened off screen, a No Offer ended on a green node, and raw rule keys showed in plain-word text. T43 fixes these.

**Q57. Where does Latest Decisions go in the rail? (T43)**
Options: below the scenario groups, as T39's Look and feel set it; above them.
Decided: above them. Below 11 scenario buttons the ticker sat about 1,500 px down, so a viewer had to scroll to find it, and clicking a row played the trace out of sight. With the ticker on top, both ways to start a playback are above the fold. Narrow screens keep T39's order.
