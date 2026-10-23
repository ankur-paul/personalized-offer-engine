-- T16: Estimated Lift v1 per segment and Offer Type, rewritten by each `offer-engine lift fit`.
-- A row with no segment (loyalty_tier, recency and coupon_user all NULL) is the Offer Type average.

CREATE TABLE lift_estimates (
    offer_type      TEXT NOT NULL,
    loyalty_tier    TEXT,
    recency         TEXT,              -- days since the last order: '<=30', '31-90' or '>90'
    coupon_user     INTEGER,           -- 1 if the Customer had redeemed at least 2 past Offers
    past_offers     INTEGER NOT NULL,  -- random past Offers of this type at moments in the segment
    moments         INTEGER NOT NULL,  -- comparable no-offer moments in the segment
    offer_rate      REAL,              -- share who bought within 7 days of a past Offer's send
    base_rate       REAL,              -- share who bought within 7 days of a no-offer moment
    observed_lift   REAL,              -- offer_rate − base_rate, at the depths the past Offers had
    estimated_lift  REAL NOT NULL,     -- max Lift for the choosers; the type average below 30 past Offers
    from_type_avg   INTEGER NOT NULL,
    fitted_at       TEXT NOT NULL      -- simulated time
);
CREATE UNIQUE INDEX lift_estimates_segment
    ON lift_estimates(offer_type, IFNULL(loyalty_tier, ''), IFNULL(recency, ''), IFNULL(coupon_user, -1));
