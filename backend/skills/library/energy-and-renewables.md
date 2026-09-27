---
name: energy-and-renewables
title: Solar, batteries and low-energy buildings
disciplines: energy, hvac
triggers: solar, pv, photovoltaic, renewable, renewables, battery, net zero, net-zero, zero carbon, off grid, off-grid, sustainable, eco, green, wind
bricks: solar_pv_array, solar_thermal_collector, home_battery, solar_inverter, small_wind_turbine, air_source_heat_pump, mvhr_unit, ev_charger
---
- PV: `solar_pv_array` on the roof (host roof), sized to the roof: w up to the roof length minus 1 m, d up to half
  the roof depth on pitched roofs. ≈ 1 kWp per 5 m². Pair it with a `solar_inverter` and optionally a
  `home_battery` in the garage or utility room.
- Solar hot water: `solar_thermal_collector` on the roof beside the PV, plus a `water_heater` cylinder indoors.
- Net-zero homes: PV + `air_source_heat_pump` (no gas) + `mvhr_unit` + `ev_charger`.
- Off-grid: add `home_battery` and optionally a `standby_generator` or `small_wind_turbine` on the site, well away
  from the building.
- Flat roofs hold `rooftop_unit`s, PV and `roof_drain`s — keep PV and plant apart (they may not overlap).
