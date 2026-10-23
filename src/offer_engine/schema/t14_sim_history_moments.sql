-- T14: every moment the history's random past Offers were drawn at. Simulator and tests only; T16 must find
-- comparable no-offer moments in `events` instead.

CREATE TABLE sim_history_moments (
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    at           TEXT NOT NULL,                  -- the moment, before moving into the send hours
    trigger      TEXT NOT NULL CHECK (trigger IN ('cart_abandoned', 'long_gap', 'broadcast')),
    offer_id     INTEGER REFERENCES offers(id),  -- NULL when the draw said don't send
    p_buy        REAL NOT NULL                   -- Ground Truth chance of buying in 7 days, with this Offer if any
);
CREATE INDEX sim_history_moments_customer ON sim_history_moments(customer_id, at);
