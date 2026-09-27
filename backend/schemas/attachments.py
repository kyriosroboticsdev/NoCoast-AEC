"""Images the user attaches to a prompt: a sketch of a plan, a photo of the plot, a reference building.

They are part of the request, so they travel with it to every stage that talks to the model
(checklist and build rounds) and are stored with the version the prompt produced. The bytes are
validated here rather than at the provider: the magic bytes decide the media type (a client's
claim is only a hint), unknown formats are rejected — no provider accepts a PDF or an IFC file,
and IFC has its own import route — and the size cap keeps a 40 MP phone photo out of the context.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re

from pydantic import BaseModel, model_validator

MAX_IMAGES = 6          # per prompt
MAX_BYTES = 8 * 1024 * 1024   # per image, decoded

# The formats Anthropic, the OpenAI-compatible endpoints and Ollama all accept, by magic bytes.
SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
]
EXTENSIONS = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
FORMATS = "PNG, JPEG, GIF or WebP"

DATA_URL = re.compile(r"^data:[\w.+-]*/?[\w.+-]*;base64,", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")  # MIME base64 arrives wrapped in lines
STORED_NAME = re.compile(r"^[0-9a-f]{40}\.(png|jpg|gif|webp)$")


def sniff(raw: bytes) -> tuple[str, str] | None:
    """(media type, extension) from the first bytes, or None if this is not an image we can send."""
    for magic, media_type, ext in SIGNATURES:
        if raw.startswith(magic):
            return media_type, ext
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def media_type_for(filename: str) -> str:
    return EXTENSIONS.get(filename.rsplit(".", 1)[-1].lower(), "application/octet-stream")


class ImageAttachment(BaseModel):
    """One attached image. `data` is base64 (a `data:` URL is accepted and unwrapped)."""

    name: str = "image"
    media_type: str = ""  # from the bytes; whatever the client sent is overwritten
    data: str

    @model_validator(mode="after")
    def _check(self) -> ImageAttachment:
        payload = WHITESPACE.sub("", DATA_URL.sub("", self.data.strip()))
        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"attachment '{self.name}' is not valid base64: {exc}") from exc
        if not raw:
            raise ValueError(f"attachment '{self.name}' is empty")
        if len(raw) > MAX_BYTES:
            raise ValueError(f"attachment '{self.name}' is {len(raw) / 1e6:.1f} MB; the limit is {MAX_BYTES // 1024 // 1024} MB")
        found = sniff(raw)
        if found is None:
            raise ValueError(f"attachment '{self.name}' is not an image the model can read ({FORMATS})")
        self.media_type = found[0]
        self.data = base64.b64encode(raw).decode()  # normalised: no line breaks, no data: prefix
        self.name = (self.name or "image").replace("\\", "/").rsplit("/", 1)[-1][:120] or "image"
        return self

    @property
    def raw(self) -> bytes:
        return base64.b64decode(self.data)

    @property
    def extension(self) -> str:
        return {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}[self.media_type]

    @property
    def filename(self) -> str:
        """Content-addressed, so the same sketch sent twice is stored once."""
        return f"{hashlib.sha1(self.raw).hexdigest()}.{self.extension}"

    @property
    def data_url(self) -> str:
        return f"data:{self.media_type};base64,{self.data}"

    def label(self) -> str:
        """`sketch.png (PNG, 210 kB)` — what the step log and the model's prompt call this image."""
        return f"{self.name} ({self.media_type.split('/')[1].upper()}, {round(len(self.raw) / 1024)} kB)"
