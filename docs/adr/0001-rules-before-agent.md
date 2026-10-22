# Rules narrow the choice before the agent picks

The Rules first compute an Eligible Set (allowed Offer Types and parameter ranges) for a Customer, and the AI agent may only choose from that set and write the message; Validation then re-checks the agent's output against every Rule, with a rule-based Fallback on failure. We rejected letting the agent propose freely and relying on Validation alone, because it would cause frequent rejections, waste agent calls on offers that could never be sent, and make Fallback the common path rather than the exception.
