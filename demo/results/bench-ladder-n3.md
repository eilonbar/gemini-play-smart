project=your-project-id  runs per depth=3  ladder=play-smart-default  prompt=82 chars

| forced 429s | first live step | answered at | measured | granted | median s | p90 s | hops verified | organic 429s |
|---:|---|---|---|---|---:|---:|---|---|
| 0 | `flex` | `flex` | 3/3 | `ON_DEMAND_FLEX` | 11.5 | 12.1 | ok | - |
| 1 | `standard` | `standard` | 3/3 | `ON_DEMAND` | 4.9 | 5.1 | ok | - |
| 2 | `priority` | `priority` | 3/3 | `ON_DEMAND` | 8.5 | 9.9 | ok | - |
| 3 | `alternative_model` | `alternative_model` | 3/3 | `ON_DEMAND` | 12.6 | 15.4 | ok | - |
| 4 | `multi_region_us` | `multi_region_us` | 3/3 | `ON_DEMAND` | 14.9 | 16.4 | ok | - |
| 5 | `multi_region_eu` | `multi_region_eu` | 3/3 | `ON_DEMAND` | 16.0 | 20.4 | ok | - |
| 6 | `-- none left --` | `-- exhausted --` | 3/3 | `-` | 12.3 | 14.6 | ok | - |

Forced 429s are real: the first N steps are sent with the `dedicated`
header, which a project with no Provisioned Throughput order cannot serve.
Every step below them runs against real capacity, so an organic 429 there
is a genuine refusal, not part of the setup. The timing is wall clock from
the call to the ladder's verdict -- an answer on every row but the last,
where the verdict is `LadderExhausted`.

The attempt trail of one run from the `5` row (`--trail`):

```
#  step                requested  granted              model              loc      tries  step ms  result
---------------------------------------------------------------------------------------------------------
1  flex                dedicated  -                    gemini-3.6-flash   global       1      952  FAIL  capacity exhausted (429)
2  standard            dedicated  -                    gemini-3.6-flash   global       3     3715  FAIL  capacity exhausted (429)
3  priority            dedicated  -                    gemini-3.6-flash   global       3     2612  FAIL  capacity exhausted (429)
4  alternative_model   dedicated  -                    gemini-3.5-flash   global       2     1822  FAIL  capacity exhausted (429)
5  multi_region_us     dedicated  -                    gemini-3.5-flash   us           2     2678  FAIL  capacity exhausted (429)
6  multi_region_eu     standard   ON_DEMAND            gemini-3.5-flash   eu           2     6814  OK
```
