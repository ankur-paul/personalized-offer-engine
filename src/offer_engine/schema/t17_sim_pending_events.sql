-- T17: organic events the live world has drawn but whose time hasn't come. Simulator only; the decision pipeline
-- never reads sim_* tables.
--   drawn = 1: an event of the current day, moved into `events` in the hour it happens.
--   drawn = 0: a delivery or return due on a later day; `simulate_day` processes it on that day.

CREATE TABLE sim_pending_events (
    id           INTEGER PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    at           TEXT NOT NULL,
    kind         TEXT NOT NULL,
    category     TEXT,
    product_id   TEXT REFERENCES products(id),
    amount       REAL,
    offer_id     INTEGER REFERENCES offers(id),
    drawn        INTEGER NOT NULL CHECK (drawn IN (0, 1))
);
CREATE INDEX sim_pending_events_drawn_at ON sim_pending_events(drawn, at);
