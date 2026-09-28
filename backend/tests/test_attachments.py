"""Images attached to a prompt: validation, what each provider sends, and what the version keeps."""

import base64
import struct
import zlib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import config
from core import pipeline
from core.pipeline import attached_images
from llm import _build
from llm.base import Image, LLMError, LLMRequest, images_rejected, multimodal
from llm.claude import user_content as claude_content
from llm.mock import MockLLM
from llm.ollama import user_message as ollama_message
from llm.openai_compat import user_content as openai_content
from llm.prompts import build_user_message, requirements_user_message
from main import app
from schemas import attachments
from schemas.attachments import ImageAttachment
from store.db import Store
from tests.sse import done, events

client = TestClient(app)


def png(width: int = 1, height: int = 1) -> bytes:
    """A real (tiny) PNG, built here so the test carries no binary blob."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    pixels = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def jpeg() -> bytes:
    """A JFIF header and an end marker: enough for the code under test, which never decodes a photo."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def attach(name: str = "sketch.png", data: bytes | None = None) -> dict:
    return {"name": name, "data": b64(data if data is not None else png())}


# --- validation ---------------------------------------------------------------

def test_the_bytes_decide_the_media_type():
    raw = png(2, 2)
    img = ImageAttachment(name="plan.png", media_type="application/pdf", data=f"data:image/gif;base64,{b64(raw)}")
    assert img.media_type == "image/png" and img.raw == raw  # the data URL and the client's claim are only hints
    assert img.filename.endswith(".png") and len(img.filename) == 44  # sha1 + ".png"
    assert img.data_url.startswith("data:image/png;base64,")
    assert img.label() == f"plan.png (PNG, {round(len(raw) / 1024)} kB)"

    # Line-wrapped base64 and a path instead of a name: what shells and file pickers actually send.
    wrapped = ImageAttachment(name="C:\\photos\\plot.png", data="\n".join([b64(raw)[:8], b64(raw)[8:]]))
    assert wrapped.name == "plot.png" and wrapped.data == b64(raw)
    assert wrapped.filename == ImageAttachment(name="other.png", data=b64(raw)).filename  # content-addressed


def test_only_images_a_model_can_read_are_accepted():
    for data, why in [(b64(b"ISO-10303-21;\nHEADER;"), "an IFC file"), (b64(b"%PDF-1.7"), "a PDF"), ("", "nothing")]:
        with pytest.raises(ValidationError, match="not an image|is empty"):
            ImageAttachment(name="x", data=data), why
    with pytest.raises(ValidationError, match="not valid base64"):
        ImageAttachment(name="x", data="this is not base64!!")


def test_an_image_that_would_swamp_the_context_is_rejected(monkeypatch):
    monkeypatch.setattr(attachments, "MAX_BYTES", 64)
    with pytest.raises(ValidationError, match="the limit is"):
        ImageAttachment(name="big.png", data=b64(png(16, 16)))


# --- what goes to the model ------------------------------------------------------

def test_the_prompt_names_the_attachments():
    for message in (requirements_user_message("a cabin", attached=["sketch.png", "plot.jpg"]),
                    build_user_message("a cabin", [], None, attached=["sketch.png", "plot.jpg"])):
        assert "ATTACHED IMAGES (2), sent with this request: sketch.png, plot.jpg." in message
    assert "ATTACHED IMAGE (1)" in build_user_message("a cabin", [], None, attached=["sketch.png"])
    assert "ATTACHED" not in build_user_message("a cabin", [], None)


class Blind(MockLLM):
    """A provider that cannot see images (llamacpp, or ollama/openai without LLM_VISION); it records
    what it was asked so a test can check the bytes stayed behind."""
    vision = False

    def __init__(self):
        self.requests: list[LLMRequest] = []

    def complete(self, request, on_text=None, on_note=None):
        self.requests.append(request)
        return super().complete(request, on_text, on_note)


def test_only_a_vision_provider_is_given_the_bytes():
    attached = [ImageAttachment(name="sketch.jpg", data=b64(jpeg()))]
    assert attached_images(Blind(), attached) == []
    seen = attached_images(MockLLM(), attached)
    assert [(i.data, i.media_type) for i in seen] == [(attached[0].raw, "image/jpeg")]
    assert seen[0].caption == "attached by the user: sketch.jpg"


def test_the_adapters_keep_an_attachment_s_own_format():
    # The look loop's screenshots are PNGs, but a photo from a phone is not: the media type travels
    # with the image (llm/base.py) instead of being assumed.
    request = LLMRequest(system="s", user="build it", schema={}, schema_name="build",
                         images=[Image(jpeg(), "attached by the user: plot.jpg", "image/jpeg")])
    assert claude_content(request)[2]["source"]["media_type"] == "image/jpeg"
    assert openai_content(request)[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert ollama_message(request)["images"] == [request.images[0].b64()]  # Ollama takes bare base64


# --- through the pipeline and the API --------------------------------------------------

def test_a_prompt_with_images_records_and_serves_them():
    pid = client.post("/projects", json={"name": "with a sketch"}).json()["id"]
    r = client.post(f"/projects/{pid}/prompt",
                    json={"prompt": "a one storey cabin", "images": [attach(), attach("plot.png", png(2, 2))]})
    version, evs = done(r.text), events(r.text)

    attached = next(e for e in evs if e["stage"] == "attachments")
    assert "sketch.png" in attached["message"] and "plot.png" in attached["message"] and attached["data"]["seen"] is True
    # The file names are in the prompt text too, for the checklist and every build round.
    named = [e for e in evs if e["stage"] == "llm" and "ATTACHED IMAGES (2)" in (e["data"] or {}).get("user", "")]
    assert {e["data"]["schema"] for e in named} == {"requirements", "build"}

    assert [i["name"] for i in version["images"]] == ["sketch.png", "plot.png"]
    assert all(i["media_type"] == "image/png" and i["bytes"] > 0 for i in version["images"])
    served = client.get(version["images"][0]["url"])
    assert served.status_code == 200 and served.content == png()
    assert client.get(f"/projects/{pid}").json()["versions"][0]["images"][0]["name"] == "sketch.png"

    # The attachment belongs to the prompt that carried it, not to the project.
    v2 = done(client.post(f"/projects/{pid}/prompt", json={"prompt": "add a bedroom"}).text)
    assert v2["images"] == []


def test_a_model_that_cannot_see_says_so_instead_of_pretending(tmp_path):
    llm = Blind()
    store = Store(tmp_path / "db.sqlite3", tmp_path / "projects")
    pid = store.create_project("blind").id
    seen: list[tuple[str, str, dict]] = []
    version = pipeline.run_prompt(store, llm, pid, "a one storey cabin",
                                  emit=lambda stage, msg, data=None: seen.append((stage, msg, data or {})),
                                  attached=[ImageAttachment(name="sketch.png", data=b64(png()))])
    assert [d["seen"] for s, _, d in seen if s == "attachments"] == [False]
    assert any("cannot read images" in n for n in version.notes)
    assert not any(r.images for r in llm.requests)  # the bytes stayed behind …
    assert any("sketch.png" in r.user for r in llm.requests)  # … the name did not
    assert version.images[0]["name"] == "sketch.png"  # and it is still stored with the version


class Refuses(Blind):
    """A provider configured as vision-capable whose model then rejects image parts, as a text-only
    model behind an OpenAI-compatible host does when LLM_VISION or its name suggested otherwise."""
    vision = True

    def complete(self, request, on_text=None, on_note=None):
        if request.images:
            self.requests.append(request)
            raise LLMError('chat/completions returned 400: {"error": "this model does not support image input"}')
        return super().complete(request, on_text, on_note)


def test_a_model_that_refuses_images_finishes_from_the_text(tmp_path):
    llm = Refuses()
    store = Store(tmp_path / "db.sqlite3", tmp_path / "projects")
    pid = store.create_project("refused").id
    seen: list[tuple[str, str, dict]] = []
    version = pipeline.run_prompt(store, llm, pid, "a one storey cabin",
                                  emit=lambda stage, msg, data=None: seen.append((stage, msg, data or {})),
                                  attached=[ImageAttachment(name="sketch.png", data=b64(png()))])
    assert [r.images != [] for r in llm.requests] == [True] + [False] * (len(llm.requests) - 1)  # asked once with them
    assert llm.vision is False
    assert any(d.get("vision") is False for s, _, d in seen if s == "llm")
    assert any(s == "look" and d.get("skipped") for s, _, d in seen)  # no screenshots for a model that refuses them
    assert any("refused image input" in n for n in version.notes)
    assert version.images[0]["name"] == "sketch.png"


def test_a_refused_screenshot_skips_the_visual_check_not_the_run(tmp_path):
    llm = Refuses()
    store = Store(tmp_path / "db.sqlite3", tmp_path / "projects")
    pid = store.create_project("no screenshots").id
    seen: list[tuple[str, str, dict]] = []
    version = pipeline.run_prompt(store, llm, pid, "a one storey cabin",
                                  emit=lambda stage, msg, data=None: seen.append((stage, msg, data or {})))
    assert [r.schema_name for r in llm.requests if r.images] == ["look"]  # the only request that carried images
    assert any(s == "look" and "does not accept images" in m for s, m, _ in seen)
    assert version.number == 1 and not any("refused image input" in n for n in version.notes)


def test_only_a_refusal_of_the_images_drops_them():
    assert images_rejected(LLMError("chat/completions returned 400: image_url is only supported by certain models"))
    assert images_rejected(LLMError("Anthropic rejected the request: Image does not match the provided media type"))
    assert not images_rejected(LLMError("chat/completions request failed: ReadTimeout: timed out"))  # the network
    assert not images_rejected(LLMError("chat/completions returned 401: invalid api key"))


@pytest.mark.parametrize("model, sees", [
    ("accounts/fireworks/models/qwen2p5-vl-32b-instruct", True),
    ("qwen2.5vl:7b", True),
    ("Qwen/Qwen3-VL-235B-A22B-Instruct", True),
    ("accounts/fireworks/models/llama4-maverick-instruct-basic", True),
    ("llama3.2-vision", True),
    ("gemma3:27b", True),
    ("pixtral-12b-2409", True),
    ("gpt-4o-mini", True),
    ("o4-mini", True),
    ("gemini-3.8-flash", True),
    ("claude-opus-5-5", True),
    ("accounts/fireworks/models/qwen3p8-max", False),
    ("llama3.1", False),
    ("qwen3-4b-instruct-2507-q4_k_m.gguf", False),
    ("deepseek-v3.2", False),
    ("gpt-oss-120b", False),
])
def test_a_model_id_says_whether_it_takes_images(model, sees):
    assert multimodal(model) is sees


def test_openai_and_ollama_providers_guess_vision_from_the_model(monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://api.fireworks.ai/inference/v1")
    monkeypatch.setattr(config, "LLM_MODEL", "accounts/fireworks/models/qwen2p5-vl-32b-instruct")
    assert _build("openai").vision is True
    monkeypatch.setattr(config, "LLM_MODEL", "accounts/fireworks/models/qwen3p8-max")
    assert _build("openai").vision is False
    monkeypatch.setattr(config, "LLM_BASE_URL", "")
    monkeypatch.setattr(config, "LLM_MODEL", "llava:13b")
    assert _build("ollama").vision is True


def test_bad_attachments_and_unknown_files_are_refused():
    pid = client.post("/projects", json={"name": "bad"}).json()["id"]
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "a cabin", "images": [attach(data=b"not a picture")]})
    assert r.status_code == 422 and "not an image" in r.text
    r = client.post(f"/projects/{pid}/prompt", json={"prompt": "a cabin", "images": [attach() for _ in range(7)]})
    assert r.status_code == 422
    assert client.get(f"/projects/{pid}/attachments/../../projects.sqlite3").status_code == 404
    assert client.get(f"/projects/{pid}/attachments/{'0' * 40}.png").status_code == 404
