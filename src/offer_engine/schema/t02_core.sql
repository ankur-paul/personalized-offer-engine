-- T02: core tables. Columns follow the field names in domain.py.
-- Datetimes are ISO-8601 text ('2026-12-01T00:00:00'), naive simulated IST. JSON columns are noted.

CREATE TABLE categories (
    name        TEXT PRIMARY KEY,
    margin_pct  REAL NOT NULL,
    avg_basket  REAL NOT NULL
);

CREATE TABLE products (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL REFERENCES categories(name),
    price     REAL NOT NULL
);

CREATE TABLE customers (
    id                  TEXT PRIMARY KEY,
    signup_at           TEXT NOT NULL,
    city_tier           INTEGER NOT NULL,
    device              TEXT NOT NULL,
    channel             TEXT NOT NULL,
    loyalty_tier        TEXT NOT NULL,
    points_balance      INTEGER NOT NULL DEFAULT 0,
    points_expire_at    TEXT,
    opted_out           INTEGER NOT NULL DEFAULT 0,
    is_tester_copy      INTEGER NOT NULL DEFAULT 0,
    source_customer_id  TEXT REFERENCES customers(id)
);

CREATE TABLE rule_versions (
    version     INTEGER PRIMARY KEY,
    rules       TEXT NOT NULL,          -- JSON, RuleSet.to_dict()
    author      TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,          -- simulated time
    saved_at    TEXT NOT NULL           -- wall-clock time
);

CREATE TABLE offers (
    id                    INTEGER PRIMARY KEY,
    code                  TEXT NOT NULL UNIQUE,
    customer_id           TEXT NOT NULL REFERENCES customers(id),
    offer_type            TEXT NOT NULL,
    category              TEXT,
    params                TEXT NOT NULL DEFAULT '{}',   -- JSON object of floats
    featured_product_ids  TEXT NOT NULL DEFAULT '[]',   -- JSON array
    created_at            TEXT NOT NULL,
    send_at               TEXT NOT NULL,
    expires_at            TEXT NOT NULL,
    caption               TEXT NOT NULL DEFAULT '',
    rule_version          INTEGER NOT NULL,
    worst_case_cost       REAL NOT NULL,
    expected_cost         REAL NOT NULL,
    status                TEXT NOT NULL,
    source                TEXT NOT NULL,
    redeemed_at           TEXT
);
CREATE INDEX offers_customer_status ON offers(customer_id, status);

CREATE TABLE events (
    id           INTEGER PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    at           TEXT NOT NULL,
    kind         TEXT NOT NULL,
    category     TEXT,
    product_id   TEXT REFERENCES products(id),
    amount       REAL,
    offer_id     INTEGER REFERENCES offers(id)
);
CREATE INDEX events_customer_at ON events(customer_id, at);

CREATE TABLE chats (
    customer_id  TEXT PRIMARY KEY REFERENCES customers(id),
    chat_id      INTEGER NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('bot', 'tester'))
);

CREATE TABLE decisions (
    id                   INTEGER PRIMARY KEY,
    customer_id          TEXT NOT NULL REFERENCES customers(id),
    at                   TEXT NOT NULL,
    trigger              TEXT NOT NULL,
    chooser              TEXT NOT NULL,
    offer_id             INTEGER REFERENCES offers(id),
    reason               TEXT NOT NULL DEFAULT '',
    binding_rule         TEXT,
    rule_version         INTEGER NOT NULL,
    validation_ok        INTEGER,               -- NULL when nothing was proposed
    validation_failures  TEXT NOT NULL DEFAULT '[]'   -- JSON array of failure strings
);
CREATE INDEX decisions_at ON decisions(at);

-- One row: the Simulation Clock. Absent until first set; clock.now() then returns the start time.
CREATE TABLE clock (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    now  TEXT NOT NULL
);
