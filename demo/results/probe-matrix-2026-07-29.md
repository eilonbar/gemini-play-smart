# Model × tier × endpoint matrix — 2026-07-29 (project your-project-id)

**Superseded, and kept on purpose.** The `us` and `eu` rows below are no longer
true: `gemini-3.6-flash` 404'd on both when this ran and serves from both today.
Current run: [`probe-matrix.md`](probe-matrix.md).

```

### endpoint: global
model                   pt_then_paygo     dedicated         standard          priority          flex              
------------------------------------------------------------------------------------------------------------------
gemini-3.6-flash        ON_DEMAND         429               ON_DEMAND         ON_DEMAND         ON_DEMAND_FLEX    
gemini-3.5-flash        ON_DEMAND         429               ON_DEMAND         ON_DEMAND         ON_DEMAND_FLEX    
gemini-3.5-flash-lite   ON_DEMAND         429               ON_DEMAND         ON_DEMAND         ON_DEMAND_FLEX    
gemini-2.5-flash        ON_DEMAND         429               ON_DEMAND         ON_DEMAND         unsupported       

### endpoint: us
model                   pt_then_paygo     dedicated         standard          priority          flex              
------------------------------------------------------------------------------------------------------------------
gemini-3.6-flash        404               404               404               n/a               n/a               
gemini-3.5-flash        ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-3.5-flash-lite   ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-2.5-flash        404               404               404               n/a               n/a               

### endpoint: eu
model                   pt_then_paygo     dedicated         standard          priority          flex              
------------------------------------------------------------------------------------------------------------------
gemini-3.6-flash        404               404               404               n/a               n/a               
gemini-3.5-flash        ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-3.5-flash-lite   ON_DEMAND         429               ON_DEMAND         n/a               n/a               
gemini-2.5-flash        404               404               404               n/a               n/a               

Read the PRIORITY column carefully: a value of ON_DEMAND rather than
ON_DEMAND_PRIORITY means the request succeeded but was not reported as
Priority. Whether it was refused or merely unlabelled is not visible
from here -- check your billing. Either way it is not an error, and
nothing but this field will tell you.
```
