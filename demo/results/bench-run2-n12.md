project=your-project-id  runs=12  prompt=82 chars

| step | tier requested | model | endpoint | ok | granted | median ms | p90 ms | failures |
|---|---|---|---|---|---|---:|---:|---|
| `flex` | flex | `gemini-3.6-flash` | global | 12/12 | `ON_DEMAND_FLEX` | 7817 | 8803 | - |
| `standard` | standard | `gemini-3.6-flash` | global | 12/12 | `ON_DEMAND` | 1586 | 2036 | - |
| `priority` | priority | `gemini-3.6-flash` | global | 12/12 | `ON_DEMAND` | 1908 | 2109 | - |
| `dedicated` | dedicated | `gemini-3.6-flash` | global | 0/12 | `-` | nan | nan | 429 |
| `alternative_model` | standard | `gemini-3.5-flash` | global | 12/12 | `ON_DEMAND` | 2292 | 2560 | - |
| `multi_region_us` | standard | `gemini-3.5-flash` | us | 12/12 | `ON_DEMAND` | 2021 | 2422 | - |
| `multi_region_eu` | standard | `gemini-3.5-flash` | eu | 12/12 | `ON_DEMAND` | 13516 | 41190 | - |

A `granted` of `ON_DEMAND` on the priority row means the tier was not
honoured. The call succeeded; the guarantee did not.
