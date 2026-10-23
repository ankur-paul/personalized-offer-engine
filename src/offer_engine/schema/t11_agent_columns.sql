-- T11: the agent's raw `propose_offer` tool input on each Decision it made (JSON object), NULL otherwise.
-- `validation_failures` is already in t02_core.sql.

ALTER TABLE decisions ADD COLUMN agent_output TEXT;
