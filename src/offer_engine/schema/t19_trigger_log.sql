-- T19: each Trigger that fired, so one underlying event asks the pipeline once. `key` names that event: the
-- abandoned cart's time, the points' expiry date, the last order's time, or 'first' for the first delivery.

CREATE TABLE trigger_log (
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    kind         TEXT NOT NULL,
    key          TEXT NOT NULL,
    at           TEXT NOT NULL,          -- simulated time it fired
    UNIQUE (customer_id, kind, key)
);

-- The long-gap Trigger looks up orders by time every hour.
CREATE INDEX events_kind_at ON events(kind, at);
