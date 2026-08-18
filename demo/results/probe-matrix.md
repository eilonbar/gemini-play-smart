# Model × tier × endpoint matrix — 2026-08-16 (project your-project-id)

Two probes earlier: [`probe-matrix-2026-07-29.md`](probe-matrix-2026-07-29.md).
Same project, same SDK, and `gemini-3.6-flash` went from 404 to served on both
`us` and `eu`. Nothing was announced. `gemini-3.7-flash` is new to this run and
arrived on every endpoint at once. That is why the matrix in
`play_smart/tiers.py` ships with a `--check` mode rather than a promise.

```

### endpoint: global
model                   pt_then_paygo     dedicated         standard          priority          flex              
------------------------------------------------------------------------------------------------------------------
gemini-3.7-flash        ON_DEMAND         429               ON_DEMAND         ON_DEMAND         ON_DEMAND_FLEX    
gemini-3.6-flash        ON_DEMAND         429               ON_DEMAND         ON_DEMAND         ON_DEMAND_FLEX    
gemini-3.5-flash        ON_DEMAND         429               ON_DEMAND         ON_DEMAND         ON_DEMAND_FLEX    
gemini-3.5-flash-lite   ON_DEMAND         429               ON_DEMAND         ON_DEMAND         ON_DEMAND_FLEX    
gemini-2.5-flash        ON_DEMAND         429               ON_DEMAND         ON_DEMAND         unsupported       

### endpoint: us
model                   pt_then_paygo     dedicated         standard          priority          flex              
------------------------------------------------------------------------------------------------------------------
gemini-3.7-flash        ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-3.6-flash        ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-3.5-flash        ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-3.5-flash-lite   ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-2.5-flash        404               404               404               n/a               n/a               

### endpoint: eu
model                   pt_then_paygo     dedicated         standard          priority          flex              
------------------------------------------------------------------------------------------------------------------
gemini-3.7-flash        ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-3.6-flash        ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-3.5-flash        ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-3.5-flash-lite   ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-2.5-flash        404               404               404               n/a               n/a               

Read the PRIORITY column carefully: a value of ON_DEMAND rather than
ON_DEMAND_PRIORITY means the request succeeded but was not reported as
Priority. Whether it was refused or merely unlabelled is not visible
from here -- check your billing. Either way it is not an error, and
nothing but this field will tell you.
```
