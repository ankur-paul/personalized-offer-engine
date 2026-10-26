-- T35: why each live Decision came out as it did, stage by stage, as JSON (offer_engine/trace.py). Decisions made
-- before T35, by the offline Policy simulator or by Preview impact have none.

CREATE TABLE decision_traces (
    decision_id INTEGER PRIMARY KEY REFERENCES decisions(id),
    trace       TEXT NOT NULL
);
