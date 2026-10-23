-- T25: `budget_state` runs before every Decision and looks up each live Redemption's order by its Offer. Without this
-- index each lookup scanned every event: 7 s per Decision a few simulated days in, on 10k Customers.
CREATE INDEX events_offer ON events(offer_id) WHERE offer_id IS NOT NULL;
