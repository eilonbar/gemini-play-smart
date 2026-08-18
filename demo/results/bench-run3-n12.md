project=your-project-id  runs=12  prompt=82 chars

| step | tier requested | model | endpoint | ok | granted | median ms | p90 ms | failures |
|---|---|---|---|---|---|---:|---:|---|
| `flex` | flex | `gemini-3.6-flash` | global | 12/12 | `ON_DEMAND_FLEX` | 8681 | 9121 | - |
| `standard` | standard | `gemini-3.6-flash` | global | 12/12 | `ON_DEMAND` | 1778 | 2180 | - |
| `priority` | priority | `gemini-3.6-flash` | global | 12/12 | `ON_DEMAND` | 1727 | 2319 | - |
| `dedicated` | dedicated | `gemini-3.6-flash` | global | 0/12 | `-` | nan | nan | 429 |
| `alternative_model` | standard | `gemini-3.5-flash` | global | 12/12 | `ON_DEMAND` | 1993 | 2118 | - |
| `multi_region_us` | standard | `gemini-3.5-flash` | us | 12/12 | `ON_DEMAND` | 2000 | 2337 | - |
| `multi_region_eu` | standard | `gemini-3.5-flash` | eu | 11/12 | `ON_DEMAND` | 5508 | 21550 | 429 |

A `granted` of `ON_DEMAND` on the priority row means the tier was not
honoured. The call succeeded; the guarantee did not.
