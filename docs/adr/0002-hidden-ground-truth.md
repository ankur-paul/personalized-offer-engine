# Synthetic Customers carry a hidden Ground Truth

Every generated Customer has a hidden Response Class and response curve per Offer Type, which the simulator uses to decide conversions but the decision pipeline must never read. A handful of live recipients can't show whether offers are incremental, so this lets us score policies (no offers, blanket discount, rules only, rules plus agent) on Incremental Margin across thousands of Customers. Any code path in the decision pipeline that touches Ground Truth fields is a bug.
