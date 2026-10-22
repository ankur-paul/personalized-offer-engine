# Customer Bots use bounded role-play

A Customer Bot's chance of buying comes from its Customer's Ground Truth; an agent reads the Offer message, rates its fit to the Persona Card, and may nudge that chance by at most ±30% before a weighted coin flip decides, then writes a reply consistent with the outcome. Pure role-play was rejected because LLM customers are agreeable (they claim nearly everything), drift from the offline simulator, and make results look like "AI persuading AI"; pure coin flips were rejected because then message wording could never matter and the chat would look dead.
