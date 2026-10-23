-- T22: each emergency "withdraw outstanding Offers" from the console, with who and when.

CREATE TABLE withdrawals (
    id          INTEGER PRIMARY KEY,
    author      TEXT NOT NULL,
    offers      INTEGER NOT NULL,       -- how many Offers it withdrew
    created_at  TEXT NOT NULL,          -- simulated time
    saved_at    TEXT NOT NULL           -- wall-clock time
);
