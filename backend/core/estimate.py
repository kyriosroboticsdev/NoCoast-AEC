"""Quantities, an order-of-magnitude cost plan and an upfront-carbon estimate for a version.

`quantities(spec)` measures the model the way a cost consultant's take-off does (net wall areas with
openings deducted, floor and roof areas, counts). `estimate(spec, review)` prices those quantities
against UniFormat II elements with typical US unit rates, and multiplies the same quantities by
embodied-carbon factors (A1–A5, kgCO2e) to compare against the LETI / RIBA targets architects are
being asked to hit. Rates are deliberately round published-benchmark values; the result is an AACE
Class 5 figure (−30 % / +50 %), which is what a concept-stage estimate is.

Both also answer "what if": the carbon result carries the saving from swapping the external wall
build-up to timber frame, the most common first move to cut upfront carbon.
"""

from __future__ import annotations

import math
from collections import Counter

from core.review import lifts
from schemas.bim import (Asset, BuildingSpec, Column, CustomFixture, Door, Fixture, Roof, Slab, Stair, Wall, Window,
                         polygon_area)

# $ per unit, 2025 US national averages (RSMeans-order square-foot costs, converted to metric).
WALL_RATE = {"brick": 520, "masonry": 430, "concrete": 470, "timber": 310, "glass": 1100, "steel": 540,
             "render": 380, "stone": 760, "plaster": 300, None: 400}
PARTITION_RATE = 170            # $/m² interior partition incl. finishes both sides
WINDOW_RATE = 950               # $/m²
DOOR_RATE = {"exterior": 3200, "interior": 1300, "garage": 6500, "roller": 9000, "revolving": 60000}
SLAB_ON_GRADE = 190             # $/m² incl. foundations
UPPER_FLOOR = 240               # $/m² suspended floor
ROOF_RATE = {"flat": 230, "gable": 260, "hip": 280, "shed": 240}
STAIR_RATE = 22000              # $ per flight
FINISHES = 140                  # $/m² NIA floors + ceilings
FF_E = 950                      # $ per fixture / equipment item
ASSET_RATE = 2500               # $ per placed library asset
LIFT_RATE, LIFT_STOP = 85000, 15000  # $ per MRL passenger elevator, plus per stop
LIFT_CARBON = 9000              # kgCO2e per elevator installation (car, machine, rails, doors)
SERVICES = {"R-3": 420, "B": 780, "E": 760, "I-2": 1500, "M": 520, "A-1": 880, "A-2": 900, "A-3": 800,
            "F-1": 520, "S-1": 300, "S-2": 260, "U": 180}        # $/m² GIA, plumbing + HVAC + fire + electrical
SERVICES_SPLIT = {"D20 Plumbing": 0.16, "D30 HVAC": 0.44, "D40 Fire protection": 0.08, "D50 Electrical": 0.32}
GENERAL = 0.12                  # general conditions, overhead and profit
CONTINGENCY = 0.15              # design contingency at concept stage

# kgCO2e per unit, A1–A3 product stage (ICE v3-order values for typical assemblies).
WALL_CARBON = {"brick": 95, "masonry": 70, "concrete": 110, "timber": 28, "glass": 150, "steel": 95,
               "render": 62, "stone": 80, "plaster": 35, None: 70}
PARTITION_CARBON = 22
WINDOW_CARBON = 120
DOOR_CARBON = 80
GROUND_CARBON = 130             # slab on grade + foundations, per m²
FLOOR_CARBON = 95               # suspended RC floor, per m²
ROOF_CARBON = {"flat": 70, "gable": 45, "hip": 48, "shed": 42}
STAIR_CARBON = 1100
SERVICES_CARBON = 60            # per m² GIA (CIBSE TM65 rule of thumb)
FINISHES_CARBON = 25            # per m² NIA
A4_A5 = 0.10                    # transport and construction on top of A1–A3
# LETI 2020 design targets / 2030 targets, upfront carbon A1–A5 kgCO2e/m² GIA, and band edges.
LETI = {"residential": (500, 300, [100, 200, 300, 400, 500, 675, 850, 1000, 1200]),
        "office": (600, 350, [100, 225, 350, 475, 600, 775, 950, 1100, 1300]),
        "education": (500, 300, [100, 200, 300, 400, 500, 675, 850, 1000, 1200]),
        "retail": (550, 350, [100, 200, 350, 450, 550, 700, 850, 1100, 1300])}
BANDS = ["A++", "A+", "A", "B", "C", "D", "E", "F", "G"]


def _levels(spec: BuildingSpec):
    return {l.id: l for l in spec.levels}


def quantities(spec: BuildingSpec) -> dict:
    levels = _levels(spec)
    walls = {e.id: e for e in spec.elements if isinstance(e, Wall)}
    openings: dict[str, float] = Counter()
    for e in spec.elements:
        if isinstance(e, (Door, Window)):
            openings[e.wall] += e.width * e.height
    ext_by_material: Counter = Counter()
    ext_len = int_len = int_area = 0.0
    for w in walls.values():
        h = w.height or levels[w.level].height
        net = max(0.0, w.length * h - openings.get(w.id, 0.0))
        if w.external:
            ext_by_material[w.material] += net
            ext_len += w.length
        else:
            int_len += w.length
            int_area += net
    ground = spec.levels[0].id
    slabs = [e for e in spec.elements if isinstance(e, Slab)]
    ground_area = sum(polygon_area(s.outline) for s in slabs if s.level == ground)
    upper_area = sum(polygon_area(s.outline) for s in slabs if s.level != ground)
    roofs = Counter()
    roof_plan = 0.0
    for r in spec.elements:
        if isinstance(r, Roof):
            plan = polygon_area(r.outline)
            roof_plan += plan
            roofs[r.shape] += plan / (math.cos(math.radians(r.pitch)) if r.shape != "flat" else 1)
    windows = [e for e in spec.elements if isinstance(e, Window)]
    doors = [e for e in spec.elements if isinstance(e, Door)]
    ext_doors = [d for d in doors if d.wall in walls and walls[d.wall].external]
    fixtures = [e for e in spec.elements if isinstance(e, (Fixture, CustomFixture))]
    shafts = lifts(spec)
    return {
        "external_wall_area": round(sum(ext_by_material.values()), 2),
        "external_wall_by_material": {str(k or "unspecified"): round(v, 2) for k, v in ext_by_material.items()},
        "external_wall_length": round(ext_len, 2),
        "internal_wall_area": round(int_area, 2), "internal_wall_length": round(int_len, 2),
        "ground_floor_area": round(ground_area, 2), "upper_floor_area": round(upper_area, 2),
        "roof_area": round(sum(roofs.values()), 2), "roof_plan_area": round(roof_plan, 2),
        "roof_by_shape": {k: round(v, 2) for k, v in roofs.items()},
        "window_area": round(sum(w.width * w.height for w in windows), 2), "windows": len(windows),
        "doors": len(doors), "exterior_doors": len(ext_doors),
        "door_kinds": dict(Counter(d.kind for d in doors)),
        "stairs": sum(1 for e in spec.elements if isinstance(e, Stair)),
        "columns": sum(1 for e in spec.elements if isinstance(e, Column)),
        "fixtures": len(fixtures), "lifts": len(shafts), "lift_stops": sum(len(s) for s in shafts),
        "assets": sum(1 for e in spec.elements if isinstance(e, Asset)) - sum(len(s) for s in shafts),
        "window_wall_ratio": round(sum(w.width * w.height for w in windows) /
                                   max(1e-6, sum(ext_by_material.values()) + sum(w.width * w.height for w in windows)), 3),
    }


def _typology(group: str) -> str:
    return {"R-3": "residential", "B": "office", "E": "education", "M": "retail"}.get(group, "office")


def _band(value: float, edges: list[int]) -> str:
    for label, edge in zip(BANDS, edges):
        if value <= edge:
            return label
    return "G+"


def _carbon(q: dict, gia: float, nia: float, material_override: str | None = None) -> dict:
    walls = sum(WALL_CARBON.get(material_override if material_override else (None if m == "unspecified" else m),
                                WALL_CARBON[None]) * a for m, a in q["external_wall_by_material"].items())
    rows = {
        "Substructure": q["ground_floor_area"] * GROUND_CARBON,
        "Upper floors": q["upper_floor_area"] * FLOOR_CARBON,
        "Roof": sum(ROOF_CARBON.get(k, 60) * a for k, a in q["roof_by_shape"].items()),
        "External walls": walls,
        "Windows and external doors": q["window_area"] * WINDOW_CARBON + q["exterior_doors"] * DOOR_CARBON * 2,
        "Internal walls and doors": q["internal_wall_area"] * PARTITION_CARBON + (q["doors"] - q["exterior_doors"]) * DOOR_CARBON,
        "Stairs": q["stairs"] * STAIR_CARBON,
        "Finishes": nia * FINISHES_CARBON,
        "Services (MEP)": gia * SERVICES_CARBON,
        **({"Elevators": q["lifts"] * LIFT_CARBON} if q.get("lifts") else {}),
    }
    a13 = sum(rows.values())
    return {"rows": rows, "a1_a3": a13, "a1_a5": a13 * (1 + A4_A5)}


def estimate(spec: BuildingSpec, review: dict) -> dict:
    q = quantities(spec)
    group = review.get("occupancy", {}).get("group", "B")
    gia = review.get("totals", {}).get("gia") or (q["ground_floor_area"] + q["upper_floor_area"])
    nia = review.get("totals", {}).get("nia") or gia * 0.85

    ext_walls = sum(WALL_RATE.get(None if m == "unspecified" else m, WALL_RATE[None]) * a
                    for m, a in q["external_wall_by_material"].items())
    kinds = q["door_kinds"]
    ext_door_cost = sum(DOOR_RATE.get(k, DOOR_RATE["exterior"]) * n for k, n in kinds.items()
                        if k in ("garage", "roller", "revolving"))
    plain_ext = max(0, q["exterior_doors"] - sum(n for k, n in kinds.items() if k in ("garage", "roller", "revolving")))
    ext_door_cost += plain_ext * DOOR_RATE["exterior"]
    int_doors = max(0, q["doors"] - q["exterior_doors"])
    services = SERVICES.get(group, 700) * gia
    elements = [
        ("A", "Substructure", "A10 Foundations + A40 slab on grade", q["ground_floor_area"], "m²", SLAB_ON_GRADE),
        ("B", "Shell", "B10 Superstructure — upper floors", q["upper_floor_area"], "m²", UPPER_FLOOR),
        ("B", "Shell", "B20 Exterior walls (net of openings)", q["external_wall_area"], "m²",
         ext_walls / q["external_wall_area"] if q["external_wall_area"] else 0),
        ("B", "Shell", "B20 Exterior windows", q["window_area"], "m²", WINDOW_RATE),
        ("B", "Shell", "B20 Exterior doors", q["exterior_doors"], "ea",
         ext_door_cost / q["exterior_doors"] if q["exterior_doors"] else 0),
        ("B", "Shell", "B30 Roofing", q["roof_area"], "m²",
         (sum(ROOF_RATE.get(k, 240) * a for k, a in q["roof_by_shape"].items()) / q["roof_area"]) if q["roof_area"] else 0),
        ("C", "Interiors", "C10 Partitions", q["internal_wall_area"], "m²", PARTITION_RATE),
        ("C", "Interiors", "C10 Interior doors", int_doors, "ea", DOOR_RATE["interior"]),
        ("C", "Interiors", "C20 Stairs", q["stairs"], "flight", STAIR_RATE),
        ("C", "Interiors", "C30 Interior finishes", nia, "m²", FINISHES),
        ("D", "Services", "D10 Conveying — passenger elevators", q["lifts"], "ea",
         (LIFT_RATE + LIFT_STOP * q["lift_stops"] / q["lifts"]) if q["lifts"] else 0),
        *[("D", "Services", name, gia, "m²", SERVICES.get(group, 700) * share) for name, share in SERVICES_SPLIT.items()],
        ("E", "Equipment & furnishings", "E20 Furnishings and fixtures", q["fixtures"], "ea", FF_E),
        ("E", "Equipment & furnishings", "E10 Library equipment and site assets", q["assets"], "ea", ASSET_RATE),
    ]
    lines = [{"group": g, "group_name": gn, "element": name, "quantity": round(qty, 2), "unit": unit,
              "rate": round(rate, 0), "total": round(qty * rate, 0)} for g, gn, name, qty, unit, rate in elements if qty]
    direct = sum(l["total"] for l in lines)
    general = direct * GENERAL
    contingency = (direct + general) * CONTINGENCY
    total = direct + general + contingency
    del services

    base = _carbon(q, gia, nia)
    per_m2 = base["a1_a5"] / gia if gia else 0.0
    typ = _typology(group)
    target_2020, target_2030, edges = LETI[typ]
    options = []
    materials = set(q["external_wall_by_material"])
    if materials - {"timber"}:
        alt = _carbon(q, gia, nia, "timber")
        saving = base["a1_a5"] - alt["a1_a5"]
        if saving > 0:
            options.append({"move": "Timber-frame external walls instead of the current build-up",
                            "saving_kg": round(saving), "saving_pct": round(saving / base["a1_a5"], 3),
                            "per_m2": round(alt["a1_a5"] / gia) if gia else 0})
    if q["upper_floor_area"]:
        saving = q["upper_floor_area"] * (FLOOR_CARBON - 45) * (1 + A4_A5)
        options.append({"move": "CLT upper floors instead of reinforced concrete",
                        "saving_kg": round(saving), "saving_pct": round(saving / base["a1_a5"], 3),
                        "per_m2": round((base["a1_a5"] - saving) / gia) if gia else 0})
    if q["ground_floor_area"]:
        saving = q["ground_floor_area"] * GROUND_CARBON * 0.3 * (1 + A4_A5)
        options.append({"move": "30 % GGBS cement replacement in the ground slab and foundations",
                        "saving_kg": round(saving), "saving_pct": round(saving / base["a1_a5"], 3),
                        "per_m2": round((base["a1_a5"] - saving) / gia) if gia else 0})
    options.sort(key=lambda o: -o["saving_kg"])

    return {
        "quantities": q,
        "cost": {
            "basis": "UniFormat II elemental estimate, 2025 US national average unit rates",
            "class": "AACE Class 5 — concept (−30 % / +50 %)",
            "currency": "USD",
            "lines": lines,
            "direct": round(direct), "general_conditions": round(general), "contingency": round(contingency),
            "total": round(total), "low": round(total * 0.7), "high": round(total * 1.5),
            "per_m2": round(total / gia) if gia else 0, "per_sf": round(total / (gia * 10.7639)) if gia else 0,
        },
        "carbon": {
            "basis": "Upfront embodied carbon, modules A1–A5 (ICE v3-order factors)",
            "rows": [{"element": k, "kg": round(v * (1 + A4_A5))} for k, v in base["rows"].items() if v > 0],
            "total_kg": round(base["a1_a5"]), "per_m2": round(per_m2),
            "typology": typ, "target_2020": target_2020, "target_2030": target_2030,
            "band": _band(per_m2, edges), "meets_2030": per_m2 <= target_2030,
            "options": options,
        },
    }
