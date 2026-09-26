"""Download a prebuilt llama.cpp server for Windows into backend/.llama/.

    python tools/get_llama.py                # vulkan build (any GPU, no CUDA toolkit needed)
    python tools/get_llama.py --backend cpu
    python tools/get_llama.py --backend cuda-13.4   # NVIDIA, also fetches the CUDA runtime DLLs

Then set LLM_PROVIDER=llamacpp in backend/.env (see llm/llamacpp.py).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / ".llama"
# Not /releases/latest: that can point at a tag without binaries. Scan recent releases for one that has them.
API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "nocoast-aec"})
    with urllib.request.urlopen(req) as r:
        total = int(r.headers.get("Content-Length") or 0)
        buf, done = io.BytesIO(), 0
        while chunk := r.read(1 << 20):
            buf.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)
        print()
        return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="vulkan", help="vulkan | cpu | cuda-12.4 | cuda-13.4")
    args = ap.parse_args()

    for release in json.loads(fetch(API)):
        tag = release["tag_name"]
        assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
        wanted = [f"llama-{tag}-bin-win-{args.backend}-x64.zip"]
        if args.backend.startswith("cuda"):
            wanted.append(f"cudart-llama-bin-win-{args.backend}-x64.zip")
        if all(w in assets for w in wanted):
            break
        print(f"skipping {tag}: no {args.backend} Windows build")
    else:
        sys.exit(f"no recent release has a win-{args.backend}-x64 build; available names look like: "
                 f"{[n for n in assets if 'win' in n][:8]}")

    DEST.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        print(f"downloading {name}")
        zipfile.ZipFile(io.BytesIO(fetch(assets[name]))).extractall(DEST)
    exe = next(DEST.rglob("llama-server.exe"), None)
    if exe is None:
        sys.exit(f"llama-server.exe not found after extracting into {DEST}")
    if exe.parent != DEST:  # some archives nest a folder; flatten so LLAMA_SERVER default works
        for f in exe.parent.iterdir():
            f.replace(DEST / f.name)
    print(f"ok: {DEST / 'llama-server.exe'} ({tag}, {args.backend})")


if __name__ == "__main__":
    main()
