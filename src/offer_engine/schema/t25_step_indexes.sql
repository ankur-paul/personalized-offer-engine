-- T25: indexes for queries the day-step runs thousands of times a simulated day on 10k Customers.

-- `outcomes.cancel_orders` looks up one Customer's drawn orders per Offer window, about 7,000 times a day. Through
-- (drawn, at) each lookup read the whole day's drawn events: 18 s of a 36 s day.
CREATE INDEX sim_pending_events_customer_at ON sim_pending_events(customer_id, at);

-- `budget_state` (before every Decision) sums live outstanding and redeemed Offers. Through `offers_status` it read
-- every history Offer left `claimed` or `redeemed`, about 15 ms per Decision.
CREATE INDEX offers_source_status ON offers(source, status);
