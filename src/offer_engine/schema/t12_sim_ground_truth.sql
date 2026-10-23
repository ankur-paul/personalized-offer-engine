-- T12: hidden Ground Truth per Customer and Offer Type (ADR 0002). Simulator only; the decision pipeline never
-- reads sim_* tables.

-- Chance of buying within 7 days given an Offer of depth d: clip(base + max_lift · (1 − e^(−d/k)), 0, 1).
CREATE TABLE sim_ground_truth (
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    offer_type   TEXT NOT NULL,
    base         REAL NOT NULL,   -- organic weekly purchase chance, no Offer
    max_lift     REAL NOT NULL,   -- Lift at full saturation; negative for Sleeping Dogs
    k            REAL NOT NULL,   -- saturation depth; Lift reaches 63% of max_lift at d = k
    PRIMARY KEY (customer_id, offer_type)
);

-- Derived from sim_ground_truth with a typical Offer, for reporting only.
CREATE TABLE sim_response_class (
    customer_id     TEXT PRIMARY KEY REFERENCES customers(id),
    response_class  TEXT NOT NULL
        CHECK (response_class IN ('persuadable', 'sure_thing', 'lost_cause', 'sleeping_dog'))
);
