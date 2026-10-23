-- T18: what each sent Offer will lead to, drawn by the simulator (ADR 0002, 0004). Simulator only; the decision
-- pipeline never reads sim_* tables. The hourly outcomes hook acts on each time once it has passed.
--   ground_truth: a Customer without a chat, drawn when the Offer is sent.
--   tester_claim: a Tester's Offer, drawn when they claim it.
--   bot_roleplay: a Customer Bot's Offer, written by its role-play (T24).

CREATE TABLE sim_offer_fates (
    offer_id    INTEGER PRIMARY KEY REFERENCES offers(id),
    buys        INTEGER NOT NULL CHECK (buys IN (0, 1)),
    buy_at      TEXT,                       -- the Redemption; NULL if they don't buy
    claim_at    TEXT,                       -- NULL if they don't claim, or claimed before the fate was drawn
    dismiss_at  TEXT,                       -- "Not now", or Stop when opts_out = 1
    opts_out    INTEGER NOT NULL DEFAULT 0 CHECK (opts_out IN (0, 1)),
    p_used      REAL NOT NULL,              -- the chance of buying the draw used
    source      TEXT NOT NULL CHECK (source IN ('ground_truth', 'tester_claim', 'bot_roleplay'))
);

CREATE INDEX offers_status ON offers(status);
