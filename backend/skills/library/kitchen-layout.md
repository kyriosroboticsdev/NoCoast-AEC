---
name: kitchen-layout
title: Kitchen layout and the work triangle
disciplines: interior, plumbing, hvac, electrical
triggers: kitchen, cooking, island, galley, pantry, chef, breakfast bar
bricks: kitchen_counter, kitchen_island, kitchen_sink, oven, fridge, dishwasher, upper_cabinets, pantry_cabinet, range_hood, microwave, bar_stool, heat_detector
---
- Run `kitchen_counter` along the longest wall (side or near). Put `kitchen_sink` and `oven` on that same wall:
  they sit IN the counter run, so give them the same side with different `at` (sink ≈0.3, oven ≈0.7).
- Work triangle: sink, cooker and fridge 1.2–2.7 m apart; `fridge` at the end of a run (at 0.05 or 0.95), never
  between sink and cooker. `dishwasher` beside the sink (at ± 0.1 of the sink's at).
- `range_hood` on the same wall and `at` as the oven. `upper_cabinets` on the counter wall avoid the window wall.
- An island needs the kitchen at least 3.6 m deep: `kitchen_island` with side "center" leaves 1.0–1.2 m aisles.
  Add `bar_stool` bricks on the island's dining side only when there is 0.9 m behind them.
- Galley kitchens (under 2.4 m wide): counters on both long walls, no island.
- Detection: a `heat_detector` (never a smoke detector) on the kitchen ceiling.
- Kitchens need a window and a door to the hall or dining room; wet services come automatically once the room holds a sink.
