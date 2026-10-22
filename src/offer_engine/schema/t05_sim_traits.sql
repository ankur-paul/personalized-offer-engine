-- T05: hidden behaviour traits per Customer. Simulator only; the decision pipeline never reads sim_* tables.

CREATE TABLE sim_customer_traits (
    customer_id        TEXT PRIMARY KEY REFERENCES customers(id),
    visit_rate         REAL NOT NULL,   -- mean sessions per day while active
    buy_propensity     REAL NOT NULL,   -- multiplier on the add-to-cart chance, mean 1
    basket_size        REAL NOT NULL,   -- multiplier on the category's average basket, mean 1
    category_affinity  TEXT NOT NULL,   -- JSON {category: share of sessions}, sums to 1
    coupon_affinity    REAL NOT NULL,   -- 0–1; also the chance of burning points on an order
    churn_hazard       REAL NOT NULL,   -- daily chance of lapsing once past the new-Customer period
    churned_at         TEXT             -- simulated time the Customer lapsed; NULL while active
);
