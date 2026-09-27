---
name: plumbing-and-hot-water
title: Water supply, hot water and drainage
tags: plumbing, energy
triggers: plumbing, hot water, water heater, drainage, rainwater, sump, basement, laundry, utility, cylinder, tank
bricks: water_heater, tankless_water_heater, solar_thermal_collector, rainwater_tank, sump_pump, floor_drain, roof_drain, water_shutoff_valve, utility_sink, washing_machine, tumble_dryer
---
- Cold water and drainage reach every room that holds a wet brick automatically (a riser is derived per wet room).
- Hot water must come from somewhere: any brick needing `water_hot` (basins, showers, baths, bidets) needs a
  `water_heater` (utility room), `tankless_water_heater`, heat pump, boiler or `solar_thermal_collector`.
- Group wet rooms: kitchen, utility and bathrooms back to back or stacked keep risers short.
- Basements with wet rooms or below the water table: a `sump_pump` in the lowest room.
- Flat roofs: one `roof_drain` per ~100 m² of roof. Rainwater harvesting: `rainwater_tank` on the site next to
  a downpipe corner of the building.
- Utility room: `washing_machine`, `tumble_dryer` and `utility_sink` on one wall; the `water_heater` here too.
- One `water_shutoff_valve` where the main enters (utility room or kitchen, low on an exterior wall).
