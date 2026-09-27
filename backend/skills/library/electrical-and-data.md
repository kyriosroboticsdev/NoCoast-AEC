---
name: electrical-and-data
title: Power, lighting, data and smart home
disciplines: electrical, data
triggers: electrical, sockets, outlets, lighting, lights, switches, smart home, wifi, network, data, home office, cinema, security, cctv, ev, electric car, charger
bricks: consumer_unit, light_switch, dimmer_switch, double_socket, usb_socket, outdoor_socket, pendant_light, recessed_downlight, wall_sconce, floor_lamp, ev_charger, router, network_rack, wifi_access_point, data_outlet, security_camera, doorbell, motion_sensor, ceiling_speaker, projector, television
---
- The main panel, one ceiling light and two outlets per room are derived automatically. Add bricks for anything
  more specific the brief asks for.
- `light_switch` on the wall beside each door (near a point 0.3 m from the door on the latch side), 1.1 m high.
  `dimmer_switch` for living/dining/bedrooms when mood lighting is asked for.
- Kitchens: a `double_socket` every 1 m of counter wall. Home offices: 2 sockets + a `data_outlet` at the desk wall.
- Downlights: `recessed_downlight` in a grid ≈ 1.2–1.5 m apart (use `position` for each).
- Data: exactly one `router` (hall or utility); `wifi_access_point`s on the ceiling ≈ one per 80 m² per storey;
  `network_rack` for offices. Anything needing `data` requires a router or rack in the building.
- EV charging: `ev_charger` on a garage or carport wall next to the car.
- Security: `doorbell` beside the entrance door (hall, exterior wall), `security_camera`s on hall/garage ceilings.
