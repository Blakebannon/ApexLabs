# Protocols

Protocols are versioned machine-readable experiment definitions. Drafts may leave numerical sample and success rules undecided; a draft cannot become active until those rules, condition instructions, randomization seed/schedule, and analysis details are declared. `apex-labs experiment freeze` creates an immutable, non-overwritable snapshot binding the entire canonical protocol, exact source commit/code identity, freeze time, and predetermined seed/schedule. Changes require a new protocol version or a separate hash-bound amendment; neither path rewrites the original snapshot.

`first-controlled-campaign.json` designs—but does not execute—the initial two-car by two-track collection campaign. The cars and tracks remain intentionally unselected. They should differ meaningfully, and the collection order should be counterbalanced so order, learning, fatigue, fuel, tires, and session progression do not masquerade as condition effects. Focused performance questions should receive separate preregistered protocol versions.

`synthetic-mechanics-demo.json` documents only the software demonstration. It is separate so no artifact implies that the first racing campaign was executed.
