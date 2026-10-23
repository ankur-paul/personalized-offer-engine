-- T24: each Customer Bot's role-play reaction to an Offer Card (ADR 0004). Simulator only, like sim_offer_fates.
-- p_used = clip(p_base · (1 + 0.3 · fit), 0, 1); buys is the weighted coin flip on it.

CREATE TABLE sim_bot_responses (
    offer_id    INTEGER PRIMARY KEY REFERENCES offers(id),
    p_base      REAL NOT NULL,              -- Ground Truth's chance of buying
    fit         REAL NOT NULL,              -- the agent's fit score in [-1, 1]; 0 on an agent outage
    p_used      REAL NOT NULL,
    buys        INTEGER NOT NULL CHECK (buys IN (0, 1)),
    claims      INTEGER NOT NULL CHECK (claims IN (0, 1)),  -- /claim, else /notnow
    reply       TEXT NOT NULL,              -- the message the bot sent, command line included
    created_at  TEXT NOT NULL               -- simulated time of the reaction
);
