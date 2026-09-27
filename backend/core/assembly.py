"""Does the assembly work as a system? The connectors of the placed bricks.

Every brick lists what it needs (`in` connectors) and supplies (`out` connectors), as free-form kinds.
The application may supply some kinds itself (`Derived.provided`: a building's rough-in supplies cold
water, drainage and power once it has rooms). Any other need must be supplied by some brick in the
design, or it is an issue that names the bricks that would supply it and suggests a step placing the
best one.
"""

from __future__ import annotations

from bricks import Brick, library
from core.derive import Derived
from core.issues import Issue
from core.placement import candidates, first_fit
from schemas.bim import Asset
from schemas.design import Design


def providers(kind: str, design: Design, provided: tuple[str, ...] = ()) -> list[Brick]:
    """Bricks supplying `kind`: the design's own first, then those needing only what is already supplied,
    then dedicated ones (supplying fewer other things), then the best search match for the kind."""
    own = {b.id: b for b in design.library}
    pool = list(own.values()) + [b for b in library().bricks.values() if b.id not in own]
    found = [b for b in pool if kind in b.provides]
    relevance = {b.id: i for i, (b, _) in enumerate(library().search(kind.replace("_", " "), limit=len(found) + 20))}
    return sorted(found, key=lambda b: (b.id not in own, len(set(b.needs) - set(provided)), len(set(b.provides)),
                                        relevance.get(b.id, len(relevance)), b.id))


def services(design: Design, derived: Derived) -> list[Issue]:
    """An error per connector kind some brick needs that nothing supplies, each with the provider brick that fits."""
    assets = [e for e in derived.spec.elements if isinstance(e, Asset)]
    provided = set(derived.provided) | {c.kind for a in assets for c in a.connectors if c.direction == "out"}
    missing: dict[str, list[Asset]] = {}
    for a in assets:
        for c in a.connectors:
            if c.direction == "in" and c.kind not in provided:
                missing.setdefault(c.kind, []).append(a)
    gaps = [(kind, users, providers(kind, design, derived.provided)) for kind, users in sorted(missing.items())]
    issues = []
    for kind, users, offer in gaps:
        names = ", ".join(f"{u.brick} '{u.id}'" for u in users[:4]) + (" …" if len(users) > 4 else "")
        hint = f"; add one of: {', '.join(b.id for b in offer[:4])}" if offer else "; define an asset that supplies it"
        issues.append(Issue("service", "error", f"{names} need{'s' if len(users) == 1 else ''} {kind}, "
                                                f"but nothing in the design supplies it{hint}", [u.id for u in users]))
    _suggest_providers(issues, [(offer, _room_of(design, users[0])) for _, users, offer in gaps], design, derived)
    return issues


def _room_of(design: Design, a: Asset) -> str | None:
    room = design.room(a.ref) if a.ref else None
    return room.id if room else None


def _suggest_providers(issues: list[Issue], wanted: list[tuple[list[Brick], str | None]], design: Design, derived: Derived) -> None:
    """Attach to each issue a step placing its first provider that fits. Placed one after the other on
    the same design, so the suggestions can all be applied together without clashing."""
    for slot, (issue, (offer, near_room)) in enumerate(zip(issues, wanted)):
        for brick in offer:
            fit = first_fit(brick, design, candidates(brick, design, derived, near_room, slot))
            if fit is not None:
                args, design, derived = fit
                issue.suggestions.append({"step": "brick", "brick": brick.id, **args})
                break
