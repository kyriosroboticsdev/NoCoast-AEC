---
name: hvac-systems
title: Heating, cooling and ventilation systems
tags: hvac
triggers: hvac, heating, cooling, air conditioning, ac, heat pump, boiler, radiator, ventilation, mvhr, fresh air, underfloor, passivhaus, low carbon, climate
bricks: air_source_heat_pump, gas_boiler, radiator, towel_radiator, underfloor_manifold, split_ac_indoor, ac_condenser, air_handling_unit, mvhr_unit, rooftop_unit, supply_diffuser, return_grille, extractor_fan, thermostat, gas_meter, flue_chimney, supply_duct
---
Every terminal needs a source — the check reports a consumer whose source is missing:
- Wet heating: a source of `heating` (`air_source_heat_pump` outside, or `gas_boiler` in the utility room) plus
  a `radiator` under each habitable room's window, or an `underfloor_manifold` per storey. One `thermostat` in the hall/living room.
- A `gas_boiler` also needs `gas_meter` (outside, position beside the wall) and a flue (`flue_chimney`), and a `co_detector` in its room.
- Heat pumps (low-carbon, Passivhaus): `air_source_heat_pump` on the site 0.3–1 m from a wall, near the utility room.
  It also provides hot water.
- Cooling: `split_ac_indoor` high on a bedroom/living wall + one `ac_condenser` (or the heat pump) outside.
- Ducted air: `air_handling_unit` (utility/plant room) or `rooftop_unit` (flat roofs, commercial), then one
  `supply_diffuser` per ~15 m² in habitable rooms and a `return_grille` per room or in the hall.
- Balanced ventilation (airtight homes): `mvhr_unit` in the utility room; supply diffusers in bedrooms/living,
  return grilles in kitchen and bathrooms.
- Bathrooms without MVHR get an `extractor_fan`; kitchens a `range_hood`.
