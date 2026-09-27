---
name: site-and-landscape
title: Site, garden and landscape
tags: site, transport
triggers: garden, landscape, landscaping, yard, site, pool, tree, trees, driveway, parking, patio, fence, hedge, outdoor, backyard, lawn, shed, hot tub
bricks: tree, shrub, hedge, lawn, planter_box, paving, driveway, fence, retaining_wall, swimming_pool, hot_tub, garden_bench, picnic_table, garden_shed, bin_store, bollard_light, street_light, mailbox, bike_rack, access_ramp
---
- Outdoor bricks take ref "site": give `position` [x, y] OUTSIDE the building (they are rejected inside it), or
  `side` N|S|E|W to stand against that outer face of the building; boundaries (`fence`, `hedge`) are paths with
  ref "site", `start` and `end`.
  The building's footprint bounds are in the CURRENT DESIGN; work out positions from them.
- Leave 1 m between the building and anything on the site; trees their canopy radius (w/2) plus 1 m.
- `driveway` from the garage door out to the plot edge on the garage's door side; `paving` in front of patio doors.
- `swimming_pool` in the sunniest part of the garden (south in the northern hemisphere), 1.2 m of `paving` around it,
  a `fence` (start/end) enclosing it when children are mentioned.
- Boundaries: `fence` or `hedge` bricks as spans along the plot edges; `retaining_wall` where the brief mentions a slope.
- `garden_shed` and `bin_store` near a side door; `bollard_light`s along paths every 3–4 m.
