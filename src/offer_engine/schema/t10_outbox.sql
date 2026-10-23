-- T10: bot messages other than Offer Cards (Redemption notices, withdrawals), sent by the Offer Bot in id order,
-- and when each Offer went out. Both times are simulated.

CREATE TABLE outbox (
    id          INTEGER PRIMARY KEY,
    chat_id     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    sent_at     TEXT                    -- NULL until the Offer Bot has sent it
);
CREATE INDEX outbox_unsent ON outbox(sent_at) WHERE sent_at IS NULL;

ALTER TABLE offers ADD COLUMN sent_at TEXT;
