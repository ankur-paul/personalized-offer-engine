# E-commerce benchmarks for calibrating the synthetic Customer population

Compiled 2026-10-22. Each table lists the figure, its context and the source. Source quality labels:

- **Primary**: the publisher's own data or a peer-reviewed paper.
- **Vendor**: a platform reporting its own customers' data.
- **Secondary**: a third party quoting someone else. Treat these as directional.
- **Computed**: we calculated it from a public dataset (the scripts were throwaway; rerun the steps described to reproduce).

Where no credible figure turned up, the table says so. India-specific data is thin for most behavioural metrics; most behavioural numbers are global or US.

---

## 1. Session-to-order conversion rate

| Figure | Context | Source |
|---|---|---|
| 1.3% of visits convert | Global, Q2 2026, Salesforce data (primary via Statista) | [Statista: online shopper conversion rate worldwide](https://www.statista.com/statistics/439576/online-shopper-conversion-rate-worldwide/) |
| 1.4% avg across sectors; skincare 2.4%, food & beverage 2.3% | Global, Q2 2026 | [Statista: conversion rate by vertical](https://www.statista.com/statistics/1106713/global-conversion-rate-by-industry-and-device/) |
| 1.8% avg; skincare 3.2%, food & beverage 3.1% | Global, Q4 2025 (festive quarter; earlier edition of the same chart) | Same Statista chart, Q4 2025 edition |
| 1.4% median; top 20% > 2.7%; bottom 20% < 0.5% | 433 Shopify stores, Jul–Oct 2026, GA4 sessions (vendor) | [Littledata benchmark](https://www.littledata.io/average/ecommerce-conversion-rate-(all-devices)) |
| 2.9% overall, add-to-cart 6.8%; desktop converts ~1.7x mobile | 2024, Dynamic Yield clients (400+ brands), secondary | [Smart Insights summary of Dynamic Yield](https://www.smartinsights.com/ecommerce/ecommerce-analytics/ecommerce-conversion-rates/) |
| 1.8–2.5% typical website conversion; 75–85% of traffic is mobile | Indian startups/D2C, 2026, agency analysis (methodology unstated) | [upGrowth](https://upgrowth.in/conversion-rate-benchmarks-for-indian-startups/) |
| Flipkart ~2.0–2.5% (estimate) | India, 2025, third-party estimate, definition unstated | [ecommerceDB: Flipkart](https://ecdb.com/resources/sample-data/retailer/Flipkart) |
| Fashion: India 1.2%, US 1.7%, Europe 1.5% | 2025, single agency report | [Noir and Blanco](https://noirandblanco.com/ecommerce-conversion-benchmark-report/) |

**India gap:** no primary or audited India session-to-order figure found. Flipkart, Myntra and Amazon India do not publish one.

## 2. Cart abandonment rate

| Figure | Context | Source |
|---|---|---|
| 70.22% average | Mean of 50 studies, updated Sep 2025 (primary) | [Baymard Institute](https://baymard.com/lists/cart-abandonment-rate) |
| 42% of US shoppers abandoned because "just browsing"; of the rest, 40% cite extra costs (shipping, tax, fees), 20% slow delivery | Baymard US survey | Same Baymard page |
| 76.2% | 2024, Dynamic Yield clients (secondary) | [Smart Insights summary](https://www.smartinsights.com/ecommerce/ecommerce-analytics/ecommerce-conversion-rates/) |
| 72.2% | Q4 2015, SaleCycle clients (vendor) | [Retail TouchPoints](https://www.retailtouchpoints.com/resources/cart-abandonment-emails-boast-40-3-open-rates) |
| 51% | India, Octane Research survey, date unclear (likely ~2015) | [WARC](https://www.warc.com/newsandopinion/news/indias-abandoned-carts-cost-billions/en-gb/35733) |

**India gap:** no recent credible India-wide rate. Indian vendor blogs claim ~85% on mobile, but none cites a traceable study.

## 3. Cart-recovery message performance

| Figure | Context | Source |
|---|---|---|
| Email abandoned-cart flow: open 50.5%, click 6.25%, **placed order 3.33%** (top 10%: 7.69%), revenue/recipient $3.65 | 143K Klaviyo flows, 2023 data (vendor) | [Klaviyo abandoned cart benchmarks (2024 ed.)](https://www.klaviyo.com/blog/abandoned-cart-benchmarks) |
| Abandoned cart click rate: email 6.0%, **SMS 10.3%**; RPR email $6.77, SMS $4.48 | 2026 Klaviyo benchmark, 110K+ customers (vendor) | [Klaviyo abandoned cart benchmarks (current)](https://www.klaviyo.com/marketing-resources/abandoned-cart-benchmarks) |
| Abandoned-cart email: open 37.1%, CTR 4.1%, **conversion 1.72%**, unsubscribe 0.45% | Omnisend, 2025 data, 27K+ brands (vendor) | [Omnisend email benchmarks](https://www.omnisend.com/blog/email-marketing-benchmarks/) |
| Push automation click-to-conversion 22.9%; SMS click-to-conversion 0.97% global; cart + welcome flows = 76% of automation orders | Omnisend, 2025 data (vendor) | [Omnisend 2026 report](https://www.omnisend.com/resources/reports/2026-ecommerce-marketing-report) |
| **19.8% of abandoned carts recovered** on average (range 6–50% by site) | SeeWhy, 65K+ recovered carts, ~2012 (secondary) | [CustomerThink](https://customerthink.com/cart_abandoners_spend_155_more/) |
| WhatsApp cart recovery conversion 14.3% | India, one D2C kitchenware brand (vendor case study) | [WebEngage](https://webengage.com/resource/case-study/d2c-kitchenware-whatsapp/) |
| WhatsApp recovery ~25% avg vs email 4–5% (vendor claim, no method) | India | [Edesy](https://edesy.in/whatsapp-marketing/features/whatsapp-cart-recovery) |
| Adding AI voice calls to WhatsApp doubled recoveries vs WhatsApp only | India, 30 brands, 6 months, Sep 2026 (vendor) | [MediaNews4U on GoKwik](https://www.medianews4u.com/d2c-brands-using-ai-voice-calls-double-abandoned-cart-recoveries-gokwik/) |

All of these are attributed conversions with no holdout, so they overstate incremental recovery (see section 9). No credible India SMS recovery figure found.

## 4. Coupon / promo redemption: broadcast vs targeted

| Figure | Context | Source |
|---|---|---|
| Campaign (broadcast) email conversion **0.08%** vs automated (triggered) **1.49%**; unsubscribe 0.20% vs 0.59% | Omnisend, 2025, 20B campaign + 470M automated sends (vendor) | [Omnisend email benchmarks](https://www.omnisend.com/blog/email-marketing-benchmarks/) |
| Flows have ~13x the placed-order rate of campaigns; flows = ~41% of email revenue from 5.3% of sends | Klaviyo 2026 (vendor) | [Klaviyo email benchmarks](https://www.klaviyo.com/products/email-marketing/benchmarks) |
| Targeted email discount offers raised spend 37.2% in the promo window; redemption rates low and **90% of the gain came without redemption**; +$1.55/week carryover after expiry | 70 randomized experiments, online ticket marketplace (primary) | [Sahni, Zou & Chintagunta, Management Science 2017](https://pubsonline.informs.org/doi/10.1287/mnsc.2016.2450) |
| Couponing lifted revenue mainly via customers who bought **without** redeeming; coupon redemption = ~20% of purchases (working-paper figure) | Randomized experiment, online retailer (primary) | [Gopalakrishnan & Park, Marketing Science 2021](https://pubsonline.informs.org/doi/10.1287/mksc.2020.1232); [MSI recap](https://msi.org/research-recap/the-impact-of-coupons-on-the-searchtopurchase-funnel-theory-and-empirical-evidence/) |

**Gap:** no credible source reports redemption rate per offer for broadcast vs targeted coupons in e-commerce. Figures like "email coupons 15–25% redemption" circulate without a traceable source and were excluded.

## 5. Repeat purchase and purchase frequency

| Figure | Context | Source |
|---|---|---|
| **29.2%** of new customers order again within 90 days; 51.1% never repeat in 18 months; median gap between orders 34 days | CDNOW (US online music retailer), 23,570 customers acquired Q1 1997 (computed) | [Bruce Hardie CDNOW dataset](https://www.brucehardie.com/datasets/) |
| 1,411 of 2,357 (60%) made no repeat purchase within 39 weeks | CDNOW 1/10 sample (primary) | [Hardie BG/NBD note](https://brucehardie.com/notes/004/bgnbd_spreadsheet_note.pdf) |
| **45.5%** repeat within 90 days; 35.7% one-time over 12 months | UCI Online Retail, UK online gift retailer, 4,338 customers, Dec 2010–Dec 2011; many are wholesale buyers, so repeat is inflated (computed) | [UCI ML Repository](https://archive.ics.uci.edu/dataset/352/online+retail) |
| ~**97%** of customers bought once; ~3% repeaters produced ~13% of sales | Olist, Brazilian marketplace, 2016–18, ~96K customers (secondary analysis of public dataset) | [Olist analysis](https://github.com/tolamoye/Olist-E-commerce-Data-Analysis) |
| **9.23 orders per annual transacting user** (FY25); 7.51 in FY23; 198.8M ATUs, 1.83B orders | India, Meesho (value fashion/home marketplace), DRHP figures via press coverage | [MediaNama on Meesho DRHP](https://www.medianama.com/2025/10/223-meesho-files-ipo-draft-drhp-sebi/) |
| ~3.5 orders per monthly transacting user per month (11.03 crore orders / 1.06 crore AMTU / 3 months) | India, Blinkit quick-commerce grocery, Q3 FY25 (computed from reported figures) | [MediaNama on Zomato Q3 FY25](https://www.medianama.com/2025/01/223-zomato-blinkit-2000-stores-rising-losses/) |
| ~300M annual online shoppers; 2025 GMV ~$65–66B; grocery, lifestyle, general merchandise to drive ~70% of incremental growth | India, Bain & Flipkart "How India Shops Online" (secondary summary) | [Branding in Asia](https://www.brandinginasia.com/how-india-shops-online-the-forces-shaping-indias-e-retail-market/) |
| Same data yields repeat rates from 22% to 51% depending on denominator and window | Definitional warning (vendor) | [Polar Analytics](https://www.polaranalytics.com/post/repeat-purchase-rate-ecommerce) |

**Gap:** no credible India figures for 90-day repeat or orders per year in electronics, beauty or home.

## 6. Churn / lapse definitions and rates

| Figure | Context | Source |
|---|---|---|
| In non-contractual retail, churn is never observed; models treat "alive" as a latent probability (BG/NBD) | Academic standard | [Fader, Hardie & Lee, Marketing Science 2005](https://brucehardie.com/papers/018/fader_et_al_mksc_05.pdf) |
| Churned = ordered in prior 12 months, no order in current 12 months; new customers excluded from denominator | BigCommerce KPI definition | [Vortex IQ docs](https://docs.vortexiq.ai/nerve-centre/kpi-cards/bigcommerce/churn-rate) |
| Churned = no reorder within 2x the average repeat-purchase interval | Shopify guidance | [Shopify blog](https://www.shopify.com/blog/churn-rate-in-ecommerce) |
| Of customers active Apr–Sep 1997, **60.1% bought again** in the next 9 months (so ~40% lapsed); 77.2% of the cohort made no purchase in the final 180 days of the 18-month window | CDNOW (computed) | [Hardie CDNOW dataset](https://www.brucehardie.com/datasets/) |
| Targeting retention offers by **lift** reduced churn more than targeting by **risk**; high-risk customers are often unresponsive | Field data, telecom + membership org (primary) | [Ascarza, JMR 2018 (Columbia summary)](https://business.columbia.edu/insights/chazen-global-insights/some-customers-are-best-left-alone) |

**Gap:** no credible cross-industry annual churn rate for e-commerce. Vendor figures (e.g. "55–70% annual churn") have no stated method and were excluded.

## 7. Gross margin by category

| Figure | Context | Source |
|---|---|---|
| India industry gross margins: Retail (Grocery & Food) **14.6%**, Retail (General) 40.7%, Retail (Special Lines) 34.3%, Furn/Home Furnishings **32.5%**, Household Products 52.6%, Electronics (Consumer & Office) 7.8%, Shoe 52.0% | Listed Indian firms, Damodaran dataset dated Jan 2026. Mixes manufacturers and retailers; India "Apparel" (11%) is mostly textile mills, so it does not reflect fashion retail (primary) | [Damodaran data page](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html) (file `marginIndia.xls`) |
| Grocery: DMart **14.5%** (FY25); guidance 14–15% | India, Avenue Supermarts (computed by StockAnalysis from filings) | [StockAnalysis](https://stockanalysis.com/quote/nse/DMART/financials/income-statement/) |
| Electronics: Electronics Mart India **14.3%** | India, Q3 FY26 investor presentation (secondary) | [AlphaStreet](https://alphastreet.com/india/?p=180007) |
| Electronics/mobiles online: ~**10%** typical margin | India e-tail, RedSeer, 2019 (secondary) | [Inc42](https://inc42.com/?p=158799) |
| Fashion: Trent (Westside, Zudio) **41.7%** | India, Q4 FY25 (secondary) | [Business Standard](https://www.business-standard.com/markets/news/high-valuations-moderating-growth-warrant-caution-for-trent-investors-125043001416_1.html) |
| Beauty-led: Nykaa consolidated ~**44.5%** (₹909 cr gross profit / ₹2,043 cr NSV); includes ad income | India, Q4 FY25 (computed from reported figures) | [Business Standard](https://www.business-standard.com/companies/quarterly-results/nykaa-q4fy25-results-profit-up-193-revenue-rises-24-125053001683_1.html) |
| Marketplace commission: fashion 11–15%, white goods 6–9%, mobiles 3–5% | India, RedSeer, 2016 (take rate, not retailer margin) | [BusinessWorld](https://businessworld.in/article/indian-e-commerce-market-to-touch-100-billion-by-2020-redseer-consulting--99933) |

**Gap:** no listed Indian online home-goods retailer margin found. Use Damodaran's home-furnishings figure as a proxy.

## 8. Distribution of customer spend (Pareto)

| Figure | Context | Source |
|---|---|---|
| Top 20% of customers = **73%** of brand sales (mean across categories) | US CPG, Nielsen panel, 100K+ households, 6 years (primary) | [Kim, Singh & Winer, Marketing Letters 2017](https://dx.doi.org/10.1007/s11002-017-9442-5) |
| Top 20% = **67.8%** of revenue; top 10% = 50.9%; top 1% = 15.8% | CDNOW, 18 months (computed) | [Hardie CDNOW dataset](https://www.brucehardie.com/datasets/) |
| Top 20% = **74.6%**; top 10% = 61.3%; top 1% = 31.8% | UCI Online Retail, 12 months, wholesale-heavy (computed) | [UCI ML Repository](https://archive.ics.uci.edu/dataset/352/online+retail) |
| Top 20% = 53.7% of prior-year spend | Hillstrom dataset, only customers active in last 12 months, spend floored at ~$30 (computed) | [MineThatData](https://blog.minethatdata.com/2008/03/minethatdata-e-mail-analytics-and-data.html) |

## 9. Uplift and incrementality of promotions

| Figure | Context | Source |
|---|---|---|
| 2-week conversion: no email **0.573%**, women's email **0.884%**, men's email **1.253%**; visits 10.6% / 15.1% / 18.3%. So **46–65% of buyers in the emailed groups would have bought anyway** | Hillstrom randomized email test, 64K US customers active in prior 12 months (computed from public data) | [MineThatData dataset](https://blog.minethatdata.com/2008/03/minethatdata-e-mail-analytics-and-data.html) |
| Conversion 0.29% overall; relative uplift on conversion **37.2%**, on visits 68.7%; 85% treated. Implies ~73% of treated conversions would have happened anyway | Criteo uplift v2, 13.98M users from ad incrementality tests (primary) | [Diemert et al., arXiv 2111.10106](https://arxiv.org/abs/2111.10106) |
| ~**59%** of promotions fail to break even globally, 71% in US | Nielsen CPG trade promotions (secondary) | [WARC](https://www.warc.com/newsandopinion/news/most-fmcg-promotions-lose-money/en-gb/34946); [FoodNavigator](https://www.foodnavigator-usa.com/Article/2014/10/09/Three-quarters-of-CPG-promotions-don-t-break-even-Nielsen) |
| Most coupon lift comes from non-redeeming buyers; 90% of offer-driven spend not via redemption | See section 4 | Sahni et al. 2017; Gopalakrishnan & Park 2021 |

**Gap:** no published source measures the population share of persuadables, sure things, lost causes and sleeping dogs. The quadrants are unobservable per person, and papers report only average or decile-level uplift.

## 10. Festive seasonality in Indian e-commerce

| Figure | Context | Source |
|---|---|---|
| Festive month ~₹90,000 cr vs ~₹5.25 lakh cr full year, so **~17% of annual GMV in one month** (our arithmetic) | India, RedSeer 2023 projection | [DT Next / IANS](https://www.dtnext.in/amp/story/news/business/india-to-see-rs-90k-cr-worth-e-commerce-sales-in-festive-month-this-year-736398) |
| 2024 festive projection ₹1.0–1.2 lakh cr, ~20% YoY; season "Onam to Bhaidooj"; mobiles, electronics, fashion are the big 3; q-commerce ~8% of festive GMV | India, RedSeer 2024 | [RedSeer](https://redseer.com/reports/festive-2024-insights-redseer-projects-20-yoy-e-commerce-growth/) |
| 2024 festive actual reported as $14B (Sep 15–Oct 31) by one outlet and ₹95,000 cr by another; not reconciled | India, RedSeer via press | [BusinessWorld](https://businessworld.in/article/indias-festive-ecommerce-sales-surge-12-to-14-bn-fueled-by-fashiontier-2-markets-redseer-539112); [Deccan Chronicle](https://www.deccanchronicle.com/amp/business/e-com-biggies-start-festive-season-sales-a-day-after-gst-rate-cut-1903893) |
| ~**7% of annual sales** in the 5 days of Flipkart Big Billion Days (vs 2.4% for China's Singles' Day) | RedSeer via secondary source, undated (older) | [Webcertain](https://webcertain.com/site/knowhowamp/indian-ecommerce-sales-are-condensed-in-festive-period/kb3045) |

## 11. Loyalty points breakage and expiry

| Figure | Context | Source |
|---|---|---|
| ~**One-third** ($16B of $48B) of reward value issued yearly goes unredeemed | US, Colloquy, 2011 | [Progressive Grocer](https://progressivegrocer.com/one-third-loyalty-reward-points-are-never-cashed) |
| **25% of members** have never redeemed any points | Canada, Bond Brand Loyalty, 2017 | [Newswire](https://www.newswire.ca/news-releases/customers-sitting-on-16-billion-of-unredeemed-loyalty-points-623827904.html) |
| 28% of members redeem once a year or less; C$13–15B unredeemed | Canada, Bond 2026 snapshot | [The Wise Marketer](https://thewisemarketer.com/2026-bond-loyalty-report-shows-canadians-are-sitting-on-13-15-billion-in-unredeemed-loyalty-points/) |
| A finite expiry window can raise purchases, mainly for customers able to adjust (heavy users, multi-store shoppers) | Field data + lab experiment (primary) | [Breugelmans & Liu-Thompkins, Marketing Letters 2017](https://link.springer.com/doi/10.1007/s11002-017-9438-1) |
| Customers buy more often as they near a reward (goal-gradient) | Coffee-card field study (primary) | [Kivetz, Urminsky & Zheng, JMR 2006](https://doi.org/10.1509/jmkr.43.1.39) |
| Card completion 34% with 2 of 12 stamps pre-filled vs 19% with 0 of 10 (endowed progress) | Car-wash field experiment (primary) | [Nunes & Drèze, JCR 2006](https://doi.org/10.1086/500480) |
| App push reminders may trigger redemption of stockpiled stamps rather than new buying | Loyalty app field data (primary) | [Bies, Bronnenberg & Gijsbrechts 2021](https://business.okstate.edu/behlab/assets/bies_bronnenberg_gijsbrechts_2021.pdf) |

**Gap:** no credible effect size for expiry **reminder** messages, and no Indian breakage data.

## 12. Opt-out / unsubscribe and message frequency

| Figure | Context | Source |
|---|---|---|
| Unsubscribe per email: e-commerce **0.19%**, all industries 0.22% | Mailchimp, data to Dec 2023 (vendor) | [Mailchimp benchmarks](https://mailchimp.com/resources/email-marketing-benchmarks/) |
| Campaign 0.20%, automated 0.59%, abandoned cart 0.45%, welcome 0.87% | Omnisend, 2025 (vendor) | [Omnisend email benchmarks](https://www.omnisend.com/blog/email-marketing-benchmarks/) |
| India: open 10.74%, click 0.84%, unsubscribe 0.07% | Benchmark Email, all industries, undated (vendor) | [Benchmark Email](https://www.benchmarkemail.com/email-marketing-benchmarks/) |
| SMS campaign unsubscribe 0.6–1.4% counts as "good" | Klaviyo 2026 data (secondary) | [ClickMinded](https://www.clickminded.com/sms-marketing-benchmarks/) |
| Reasons to unsubscribe: too many emails overall 26%, too many from this company 19%, irrelevant 21%, always pushing a sale 19% | US survey, n=2,400, 2017 | [MarketingSherpa](https://www.marketingsherpa.com/article/chart/why-consumers-unsubscribe) |
| Marketing intensity shortens time to opt-out (copula model; effect size not public) | Retailer data (primary) | Kumar, Zhang & Luo, JMR 51(4):403–419, 2014 ([GSU dissertation record](https://scholarworks.gsu.edu/marketing_diss/32)) |
| Push opt-in: Android ~91%, iOS ~44% | CleverTap/MoEngage, India-heavy app data (vendor) | [CleverTap](https://clevertap.com/blog/push-notification-ctr/) |
| 6+ SMS campaigns/month raise opt-outs without matching revenue; 2–4/month suggested | Omnisend guidance (vendor) | [Omnisend](https://www.omnisend.com/blog/sms-frequency/) |

**Gap:** no credible figures for WhatsApp or Telegram block/opt-out rates, and no causal frequency-to-unsubscribe curve.

---

## Suggested calibration targets (our judgement)

These ranges are **our judgement**, combining the figures above. They are not sourced numbers. The generator's aggregate behaviour should land inside them across a simulated year.

| # | Metric the generator should reproduce | Target range | Reasoning |
|---|---|---|---|
| 1 | Session-to-order conversion | 1.2–2.5% overall; grocery and beauty at the top, home and electronics at the bottom | Statista 1.3–1.8%, Littledata 1.4%, India agencies 1.8–2.5% |
| 1a | Weekly no-offer purchase probability (hidden baseline) | Mean 4–8% across active Customers; median 1–3%; top decile 25–50% | Consistent with 3–9 orders/year for actives (CDNOW, Meesho) and a heavy right tail |
| 2 | Cart abandonment | 70–80% of carts | Baymard 70%, Dynamic Yield 76%; mobile-heavy India points to the upper end |
| 3 | Cart-recovery nudge: attributed recovery per abandoned cart | 3–8% per single message (email-like); 8–15% for chat channels (Telegram as WhatsApp proxy); multi-touch ceiling ~20% | Klaviyo 3.3% (top 7.7%), Omnisend 1.7%, SeeWhy 19.8%, Indian WhatsApp cases 14–25% |
| 3a | Share of "recovered" carts that would have converted anyway | 45–75% | Hillstrom 46–65%, Criteo ~73% |
| 4 | Offer redemption per send | Broadcast 0.1–1%; targeted/triggered 1.5–5% | Omnisend 0.08% vs 1.49%, Klaviyo flows ~13x campaigns |
| 5 | 90-day repeat among new Customers | 20–35% blended. Grocery 40–60%, beauty 25–40%, fashion 15–30%, home 10–20%, electronics 5–15% | CDNOW 29%, UCI 45% (wholesale-inflated), Olist 3% (low-trust marketplace). Category split is judgement |
| 5a | Orders per active Customer per year | Blended 4–9; grocery 24–40; fashion 3–6; beauty 3–5; home 1–3; electronics 1–2 | Meesho 9.2/yr, Blinkit ~42/yr; category split is judgement |
| 6 | Lapse | Lapsed = no order in 2x the category's median gap, capped at 180 days. 35–50% of Customers active in a 6-month window lapse within the next 9–12 months; 50–65% of a year's new Customers stay one-time | CDNOW 40% lapse, 51% one-time; Shopify 2x rule |
| 7 | Gross margin by category | Grocery 12–18%; electronics 8–15%; fashion 40–50%; beauty 35–45%; home 25–35% | DMart 14.5%, Electronics Mart 14.3%, RedSeer ~10%, Trent 41.7%, Nykaa ~44.5%, Damodaran home 32.5% |
| 8 | Spend concentration over 12 months | Top 20% of Customers = 65–75% of revenue; top 10% = 45–60%; top 1% = 10–20% | Kim et al. 73%, CDNOW 68%, UCI 75% |
| 9 | Response Class shares for a typical offer | Lost causes 70–85%, sure things 5–15%, persuadables 3–10%, sleeping dogs 1–5%. A blanket offer should lift conversion 30–120% relative, and 45–75% of redeemers should be sure things | No published class shares; constrained by Hillstrom (+54% to +119%) and Criteo (+37%) |
| 10 | Festive seasonality | Festive window (mid-Sep to early Nov) = 15–20% of annual GMV; peak sale week ~7% of annual (≈5x a normal day's GMV) | RedSeer ~17% in festive month, BBD ~7% in 5 days |
| 11 | Loyalty points breakage | 25–35% of issued points value never redeemed; 20–30% of members never redeem. Expiry reminder: assume +5–15% relative redemption among reminded holders, and flag it as an untested assumption | Colloquy one-third, Bond 25%; no reminder effect size found |
| 12 | Opt-out per promotional message | Email-like broadcast 0.15–0.3%; triggered 0.4–0.6%; chat channel (Telegram) 0.5–1.5%. Per-message opt-out hazard should rise with frequency, e.g. doubling above ~2 promotional messages/week (assumed shape, not sourced) | Mailchimp 0.19%, Omnisend 0.20%/0.59%, Klaviyo SMS 0.6–1.4% |
