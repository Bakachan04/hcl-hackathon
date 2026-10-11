# Data card: Production Re-Planner synthetic pack

## Name and version

| Field | Value |
|---|---|
| Name | `replanner-synth` |
| Version | 1.0 (seed 42) |
| Date | 2026-10-11 |
| Owner | Lavanya |

## How it was made

- **Generator:** `backend/scripts/generate_data.py`, plain Python (`random.Random(seed)`), no LLM involved in producing the rows.
- **Command:** from `backend/`, run `.\.venv\Scripts\python.exe scripts\generate_data.py --seed 42 --out ..\data\raw`
- **Seed:** 42. The seed drives the orders (product mix, quantity, due date, priority, customer). The plant layout (machines, routings, changeovers, roster, disruptions) is fixed in the script so every trap is always in the same place.
- **Reproducible:** the same seed gives byte-identical files (checked by `tests/test_loader.py::test_generated_pack_is_deterministic_and_valid`).
- **AI assistance:** the generator code was written with an AI coding assistant (Claude Code) from the guide's §4 and Annex B. The prompt was, in short: "write a seeded generator for the Annex B files that meets the §4.3 minimums and plants every §4.4 edge case at a known place". No AI model produced or edited the data rows.
- The CSVs are not committed (`data/` is gitignored). Regenerate them with the command above.

## What it contains

Planning starts on **2026-10-12 06:00** (Monday). Due dates run from **2026-10-12 12:00 to 2026-10-14 20:00**. Times are plant local, `YYYY-MM-DD HH:MM`.

| File | Rows | Contents |
|---|---|---|
| `orders.csv` | 45 | 45 orders O-101..O-145, 4 products (PA 17, PB 10, PC 6, PD 12), priority 1/2/3 = 11/15/19, 8 synthetic customers |
| `routings_machines.csv` | 10 | 10 routing steps (2–3 per product) over 8 machines: CNC-1..4, LTH-1, LTH-2, ASM-1, ASM-2 |
| `changeovers_skills.csv` | 27 | 12 changeover rows (every ordered pair of 4 products) + 15 operator rows |
| `disruption.csv` | 2 | CNC-3 breakdown 10:00 for 6 h + rush order R-201 |
| `disruption_2.csv` | 2 | CNC-1 breakdown 08:00 for 4 h + rush order R-202 (evaluation) |
| `disruption_3.csv` | 2 | LTH-2 breakdown 14:00 for 5 h + rush order R-203 (evaluation) |

### Row counts

What `scripts/validate_data.py` compares against the loaded data (check `row_counts_match_data_card`):

| table | rows |
|---|---|
| orders | 45 |
| routings | 10 |
| changeovers | 12 |
| operators | 15 |

### Columns beyond Annex B (all optional; the loader also accepts files without them)

- `orders.csv`: `customer_tier` (1 = key customer), work in progress `wip_step`, `wip_machine`, `wip_operator`, `wip_start`, `wip_end`, `movable`.
- `disruption.csv`: rush-order details `product`, `qty`, `due`, `priority`, `customer`.
- `changeovers_skills.csv` holds two tables: rows with `from_product/to_product/minutes` are changeovers; rows with `operator_id/skill/shift` are operators. Shift A = 06:00–14:00, B = 14:00–22:00.

### Shape of the load

- Every job is at most 4 h (`qty × minutes_per_unit ≤ 240`).
- Total work is about 142 machine-hours on 8 machines; two days of two shifts give 256, so a sensible plan fits in about 2 days (~56 % load). LTH-2 is the busiest machine because PD step 2 can only run there.
- 8 operators on shift A and 7 on shift B; skills L1/L2/L3 = 7/6/2.

## Traps and edge cases (guide §4.4)

| Edge case | Where |
|---|---|
| An order that can only run on the machine that breaks | Product **PC** step 1 runs only on **CNC-3**, which breaks in `disruption.csv` (10:00–16:00). **O-107** (PC, priority 1, due 2026-10-12 16:00) is the sharpest case; all 6 PC orders are affected. |
| An operator with a rare skill who is the only one on the shift | **OP-01** (shift A) and **OP-09** (shift B) are the only **L3** operators. PD step 2 on LTH-2 needs L3. |
| Changeover times that differ by direction | Every pair, e.g. PA→PB 20 min vs PB→PA 45 min; PC→PD 60 vs PD→PC 20. |
| A rush order with the same due date as an existing high-priority order | Rush **R-201** (priority 1, due 2026-10-12 18:00) vs **O-110** (PB, priority 1, due 2026-10-12 18:00). |
| Work in progress that cannot be moved | **O-101** step 1 on CNC-1 (OP-02, 06:00–07:30) and **O-102** step 1 on CNC-3 (OP-03, 06:00–07:40) have `movable = false`. **O-103** step 1 on CNC-4 is WIP but `movable = true`. |
| A disruption that makes full on-time delivery impossible | **R-201** is product PC, so it needs CNC-3, which is down until 16:00. 150 min on CNC-3 then 72 min on a lathe → earliest finish 19:42, after its 18:00 due date, in every plan. |
| Extra (evaluation) | `disruption_3.csv` breaks **LTH-2**, the only machine for PD step 2, so all PD work waits. |

## Checks run

`scripts/validate_data.py` on the seed-42 pack: **8/8 PASS**. The saved output is in [`validation_output.txt`](validation_output.txt).

1. Every order's product has a routing
2. Every routing step has at least one capable machine (and steps are numbered 1..n)
3. Due dates are after the planning start
4. The changeover table covers every ordered product pair in use
5. Roster hours are not negative or overlapping
6. Row counts match this data card
7. Every required skill is held by at least one operator (extra)
8. WIP rows point at a machine and operator that can run that step (extra)

## Known limits

- One plant, 8 machines, 4 products, 3 days. No maintenance calendar, material shortages, scrap or machine speed differences.
- Shifts are the same every day (A and B), with no night shift and no absences.
- Changeover times depend only on the product pair, not on the machine.
- Quantities, due dates and priorities are drawn uniformly or from fixed weights. They are not fitted to real demand.

## Privacy

All data is synthetic, generated by the script above. No real plant, company, customer or person data is used. Customer names are `Synthetic Customer 01..08`; operator IDs are `OP-01..OP-15`.
