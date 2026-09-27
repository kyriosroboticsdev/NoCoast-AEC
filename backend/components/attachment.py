"""An IFC file attached to a prompt. Same transport as an image attachment (schemas/attachments.py):
base64 in the prompt request, validated here by its first bytes and its size, never by its name."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re

from pydantic import BaseModel, model_validator

MAX_COMPONENTS = 8                    # per prompt
MAX_BYTES = 25 * 1024 * 1024          # per file, decoded
MAGIC = b"ISO-10303-21"
DATA_URL = re.compile(r"^data:[\w.+-]*/?[\w.+-]*;base64,", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")


class IfcAttachment(BaseModel):
    """One attached IFC file. `data` is base64 (a `data:` URL is accepted and unwrapped)."""

    name: str = "component.ifc"
    data: str

    @model_validator(mode="after")
    def _check(self) -> IfcAttachment:
        self.name = (self.name or "component.ifc").replace("\\", "/").rsplit("/", 1)[-1][:120] or "component.ifc"
        payload = WHITESPACE.sub("", DATA_URL.sub("", self.data.strip()))
        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"component '{self.name}' is not valid base64: {exc}") from exc
        if not raw:
            raise ValueError(f"component '{self.name}' is empty")
        if len(raw) > MAX_BYTES:
            raise ValueError(f"component '{self.name}' is {len(raw) / 1e6:.1f} MB; the limit is {MAX_BYTES // 1024 // 1024} MB")
        if not raw.lstrip()[:len(MAGIC)] == MAGIC:
            raise ValueError(f"component '{self.name}' is not an IFC file (a STEP file starts with {MAGIC.decode()})")
        self.data = base64.b64encode(raw).decode()
        return self

    @property
    def raw(self) -> bytes:
        return base64.b64decode(self.data)

    @property
    def sha1(self) -> str:
        return hashlib.sha1(self.raw).hexdigest()

    @property
    def filename(self) -> str:
        """Content-addressed, so the same file attached twice is stored once."""
        return f"{self.sha1}.ifc"

    def label(self) -> str:
        return f"{self.name} (IFC, {round(len(self.raw) / 1024)} kB)"
