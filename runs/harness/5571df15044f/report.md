# Prompt Harness Report (`5571df15044f`)

- **Model:** `FakeLLM(LegalXMLPolicy)`
- **Scenarios:** 20 × 1 samples = 20 runs
- **Parse OK (1st try):** 100.0%
- **Parse OK (after repair):** 100.0%
- **Parse failure rate:** 0.0%
- **Repair rate:** 0.0%
- **IAR:** 0.0% (`{}`)
- **Directive emission rate:** 90.0%
- **Directive follow rate:** 0.75
- **Memory ref usage rate:** 75.0%
- **CS usage rate:** 0.0%
- **Mean tokens:** 0 in / 0 out
- **Latency:** p50 = 0 ms, p95 = 0 ms
- **Total cost:** $0.000000

## Scenario Breakdown

| Scenario | Player | Action | Target | Parse OK | Invalid Reason |
|---|---|---|---|---|---|
| `01_open_shot_ball_handler` | `A1` | `SHOOT` | `None` | `True` | `None` |
| `02_needs_clear_ball_handler` | `A1` | `CLEAR` | `None` | `True` | `None` |
| `03_shot_clock_low` | `A2` | `SHOOT` | `None` | `True` | `None` |
| `04_off_ball_cut_opportunity` | `A2` | `CUT` | `PAINT` | `True` | `None` |
| `05_off_ball_captain_screen_directive` | `A3` | `SCREEN` | `B1` | `True` | `None` |
| `06_ball_handler_pass_directive` | `A1` | `PASS` | `A2` | `True` | `None` |
| `07_on_ball_defender_drive` | `B1` | `CONTEST` | `A1` | `True` | `None` |
| `08_off_ball_defender_help_paint` | `B3` | `CONTEST` | `A1` | `True` | `None` |
| `09_rebound_offense` | `A3` | `CRASH_BOARDS` | `None` | `True` | `None` |
| `10_rebound_defense` | `B3` | `CRASH_BOARDS` | `None` | `True` | `None` |
| `11_captain_no_prior_call` | `A1` | `SHOOT` | `None` | `True` | `None` |
| `12_team_b_non_captain_with_call` | `A2` | `SPOT_UP` | `LEFT_CORNER` | `True` | `None` |
| `13_team_b_captain` | `A1` | `SHOOT` | `None` | `True` | `None` |
| `14_team_c_ball_handler` | `A1` | `SHOOT` | `None` | `True` | `None` |
| `15_team_d_isolated_player` | `A2` | `CUT` | `PAINT` | `True` | `None` |
| `16_exploitable_memory_tendency` | `A1` | `SHOOT` | `None` | `True` | `None` |
| `17_defense_cs_switch` | `B2` | `CONTEST` | `A1` | `True` | `None` |
| `18_overtime_tied` | `A1` | `SHOOT` | `None` | `True` | `None` |
| `19_team_b_offense_initiation` | `B1` | `SHOOT` | `None` | `True` | `None` |
| `20_defender_steal_directive` | `B1` | `CONTEST` | `A1` | `True` | `None` |
