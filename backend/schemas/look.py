"""Look turns: the model inspecting screenshots of what it built.

After the build and the deterministic checks, the model is shown rendered views of the model and
picks where to point the camera next, so it can check what numbers cannot: parts floating or buried,
things facing the wrong way, an asset that does not look like what it should, a blocked doorway.
Each turn is one JSON object: the next views to take, or the problems it saw, or done.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_VIEWS = 3


class View(BaseModel):
    """Where the camera is and what it shows. Coordinates in metres: x east, y north, z up."""

    model_config = ConfigDict(extra="ignore")

    target: Optional[str] = Field(None, description="id of an element, asset or room to frame; null = everything shown")
    look_at: Optional[list[float]] = Field(None, description="[x, y, z] to aim at instead of a target")
    position: Optional[list[float]] = Field(None, description="[x, y, z] to put the camera at (e.g. standing in a room at eye "
                                                              "height 1.6); overrides azimuth, elevation and distance")
    azimuth: float = Field(225, description="compass bearing the camera looks from: 0 = from the north, 90 = east, 180 = south, "
                                            "270 = west")
    elevation: float = Field(30, ge=-89, le=90, description="degrees above the horizon; 90 = straight down (a plan)")
    distance: Optional[float] = Field(None, gt=0, description="metres from the target; null = fit it in the frame")
    level: Optional[str] = Field(None, description="show only this level and below, cut 1.5 m above its floor (a plan cut)")
    cut: Optional[float] = Field(None, description="remove everything above this height z (m); what it cuts through is drawn solid dark")
    hide: list[str] = Field(default_factory=list, description="IFC classes (IfcRoof, IfcSlab …), element ids, or 'ground'")
    ortho: Optional[bool] = Field(None, description="parallel projection; default true for plans (elevation >= 85)")
    fov: float = Field(50, ge=10, le=120, description="field of view in degrees (perspective only)")
    note: Optional[str] = Field(None, description="what you want to check with this view")

    @field_validator("look_at", "position", mode="before")
    @classmethod
    def _point(cls, v):
        if v is None:
            return None
        if not isinstance(v, (list, tuple)) or len(v) not in (2, 3) or not all(isinstance(n, (int, float)) for n in v):
            raise ValueError(f"expected [x, y, z], got {v!r}")
        return [float(n) for n in v] + ([0.0] if len(v) == 2 else [])

    @field_validator("hide", mode="before")
    @classmethod
    def _listify(cls, v):
        return [] if v is None else [v] if isinstance(v, str) else v

    def describe(self) -> str:
        where = (f"from [{', '.join(f'{n:g}' for n in self.position)}]" if self.position
                 else f"from azimuth {self.azimuth:g}° elevation {self.elevation:g}°" + (f" at {self.distance:g} m" if self.distance else ""))
        what = self.target or (f"[{', '.join(f'{n:g}' for n in self.look_at)}]" if self.look_at else "everything")
        extra = [f"level {self.level}"] if self.level else []
        extra += [f"cut at z {self.cut:g}"] if self.cut is not None else []
        extra += [f"hiding {', '.join(self.hide)}"] if self.hide else []
        return f"{what} {where}" + (f" ({'; '.join(extra)})" if extra else "")


class LookTurn(BaseModel):
    views: list[View] = Field(default_factory=list, description=f"Up to {MAX_VIEWS} more screenshots to take")
    problems: list[str] = Field(default_factory=list, description="What looks wrong, each naming the element ids and the fix")
    done: bool = Field(False, description="true when you have seen enough: the model looks right, or `problems` lists what to fix")

    @field_validator("views", mode="before")
    @classmethod
    def _cap(cls, v):
        if v is None:
            return []
        v = [v] if isinstance(v, dict) else v
        return v[:MAX_VIEWS]
