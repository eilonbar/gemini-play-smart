# Priority header variants — 2026-07-29 (project your-project-id)

```
project=your-project-id  location=global  model=gemini-3.6-flash

variant                         reported traffic_type     note
--------------------------------------------------------------------------------------------------------
priority (PT-first spelling)    ON_DEMAND                 Doc: 'use PT quota if available, then Priority'
priority (pinned spelling)      ON_DEMAND                 Doc: 'use only Priority PayGo' -- what this library sends
flex (control)                  ON_DEMAND_FLEX            Proves headers arrive and traffic_type reflects the lane
no headers (baseline)           ON_DEMAND                 PT-then-PayGo default
flex on gemini-2.5-flash        400 not supported         The service DOES reject an unhonourable lane -- for Flex

If the two priority rows read ON_DEMAND while the flex control reads
ON_DEMAND_FLEX, the headers are correct and reaching the service. What
you cannot conclude from here is why: entitlement, capacity fallback and
a reporting gap are indistinguishable at this layer. Take it to billing.
```
