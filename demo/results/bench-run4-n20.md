project=your-project-id  runs=20  prompt=82 chars

| step | tier requested | model | endpoint | ok | granted | median ms | p90 ms | failures |
|---|---|---|---|---|---|---:|---:|---|
| `flex` | flex | `gemini-3.6-flash` | global | 20/20 | `ON_DEMAND_FLEX` | 7757 | 8003 | - |
| `standard` | standard | `gemini-3.6-flash` | global | 20/20 | `ON_DEMAND` | 1708 | 1783 | - |
| `priority` | priority | `gemini-3.6-flash` | global | 20/20 | `ON_DEMAND` | 1760 | 1922 | - |
| `dedicated` | dedicated | `gemini-3.6-flash` | global | 0/20 | `-` | nan | nan | 429 |
| `alternative_model` | standard | `gemini-3.5-flash` | global | 20/20 | `ON_DEMAND` | 1926 | 2151 | - |
| `multi_region_us` | standard | `gemini-3.5-flash` | us | 20/20 | `ON_DEMAND` | 1818 | 1955 | - |
| `multi_region_eu` | standard | `gemini-3.5-flash` | eu | 20/20 | `ON_DEMAND` | 2358 | 2629 | - |

A `granted` of `ON_DEMAND` on the priority row means the tier was not
honoured. The call succeeded; the guarantee did not.
