project=your-project-id  runs=5  prompt=82 chars

| step | tier requested | model | endpoint | ok | granted | median ms | p90 ms | failures |
|---|---|---|---|---|---|---:|---:|---|
| `flex` | flex | `gemini-3.6-flash` | global | 3/5 | `ON_DEMAND_FLEX` | 18201 | 21927 | 429 |
| `standard` | standard | `gemini-3.6-flash` | global | 5/5 | `ON_DEMAND` | 2396 | 2596 | - |
| `priority` | priority | `gemini-3.6-flash` | global | 5/5 | `ON_DEMAND` | 2494 | 6634 | - |
| `dedicated` | dedicated | `gemini-3.6-flash` | global | 0/5 | `-` | nan | nan | 429 |
| `alternative_model` | standard | `gemini-3.5-flash` | global | 5/5 | `ON_DEMAND` | 2153 | 2353 | - |
| `multi_region_us` | standard | `gemini-3.5-flash` | us | 5/5 | `ON_DEMAND` | 2011 | 2575 | - |
| `multi_region_eu` | standard | `gemini-3.5-flash` | eu | 5/5 | `ON_DEMAND` | 2255 | 3279 | - |

A `granted` of `ON_DEMAND` on the priority row means the tier was not
honoured. The call succeeded; the guarantee did not.
