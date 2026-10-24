-- T26: the offline Policy simulator. Simulator only; the decision pipeline never reads sim_* tables.

-- The agent's answers in offline runs, keyed by a hash of everything sent (model, system prompt, tool, user
-- message), so a rerun from the same state makes no agent calls.
CREATE TABLE sim_agent_cache (
    prompt_hash  TEXT PRIMARY KEY,
    model        TEXT NOT NULL,
    response     TEXT NOT NULL,   -- JSON: the agent's propose_offer tool input
    created_at   TEXT NOT NULL    -- wall-clock time
);

-- One row per Policy and scope in each `offer-engine simulate` run.
CREATE TABLE sim_policy_results (
    id                     INTEGER PRIMARY KEY,
    run_at                 TEXT NOT NULL,     -- wall-clock time the run finished
    start_at               TEXT NOT NULL,     -- simulated time the Policies started from
    days                   INTEGER NOT NULL,
    seed                   INTEGER NOT NULL,
    policy                 TEXT NOT NULL,
    scope                  TEXT NOT NULL CHECK (scope IN ('population', 'sample')),
    customers              INTEGER NOT NULL,
    offers_sent            INTEGER NOT NULL,
    claimed                INTEGER NOT NULL,
    redeemed               INTEGER NOT NULL,
    spend                  REAL NOT NULL,     -- ₹ the Policy's Redemptions cost
    incremental_margin     REAL NOT NULL,     -- ₹, against No Offers on the same Customers, days and seed
    per_rupee              REAL,              -- Incremental Margin per ₹ of spend; NULL with no spend
    sure_thing_spend       REAL NOT NULL,     -- ₹ of spend on Sure Things (Ground Truth class)
    validation_rejections  INTEGER NOT NULL,  -- Decisions with a Validation failure
    fallbacks              INTEGER NOT NULL,
    lift_deciles           TEXT NOT NULL,     -- JSON: [{decile, offers, estimated_lift, true_lift}]
    runtime_seconds        REAL NOT NULL
);
