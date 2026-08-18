project=your-project-id  runs=20  prompt=82 chars

| step | tier requested | model | endpoint | ok | granted | median ms | p90 ms | failures |
|---|---|---|---|---|---|---:|---:|---|
| `flex` | flex | `gemini-3.6-flash` | global | 20/20 | `ON_DEMAND_FLEX` | 7778 | 8017 | - |
| `standard` | standard | `gemini-3.6-flash` | global | 20/20 | `ON_DEMAND` | 1713 | 1997 | - |
| `priority` | priority | `gemini-3.6-flash` | global | 20/20 | `ON_DEMAND` | 1636 | 1802 | - |
| `alternative_model` | standard | `gemini-3.5-flash` | global | 20/20 | `ON_DEMAND` | 1946 | 2022 | - |
| `multi_region_us` | standard | `gemini-3.5-flash` | us | 20/20 | `ON_DEMAND` | 1881 | 2016 | - |
| `multi_region_eu` | standard | `gemini-3.5-flash` | eu | 20/20 | `ON_DEMAND` | 2273 | 2549 | - |

A `granted` of `ON_DEMAND` on the priority row means the tier was not
honoured. The call succeeded; the guarantee did not.
