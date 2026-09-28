# Tekt

**Describe a building in plain English and get an IFC model back.**

> **This is a hackathon project.** We built it over a weekend as a demo of a text-to-IFC agent. It works
> well enough to show the idea and it's fun to play with, but it isn't production software. Expect rough
> edges, don't use its output for anything that gets built, and read the code reviews and cost numbers
> as illustrations rather than advice.

![Tekt building a two-storey house](docs/screenshot.png)

*"Two storey house with a kitchen, living room and three bedrooms, a garage and a front porch."*

You type a prompt. An LLM agent plans the building and you watch it go up in the 3D viewer one room,
door and window at a time. When it's done you get a valid IFC4 file you can open in any BIM tool. Then
you can keep talking to it ("move the kitchen to the north side", "add a basement") and each prompt
becomes a new version of the project.

Project write-up: [Google Doc](https://docs.google.com/document/d/1tU3kCJchFRInzQXuF_GBEn_fQGtBhatj)

## How it works

The main idea is that **the model never writes IFC.** IFC files are big graphs of numbered references,
and LLMs are bad at keeping those consistent. They're also bad at wall offsets and boolean openings.
So we give the model a small vocabulary of design moves instead: add a room as a rectangle on a grid,
put a door between two rooms, put a window on the south wall, add a stair, pick a roof. Our own code
turns those moves into walls, slabs, openings and roofs, and IfcOpenShell compiles the result.

A run goes roughly like this:

1. The model turns the prompt into a checklist of requirements ("three bedrooms", "living room faces
   south").
2. It looks things up in a library of parametric components ("bricks") and short how-to notes
   ("skills"), for example kitchen layouts or structural spans.
3. It streams build steps. Each step is validated and applied as soon as it arrives, and a preview IFC
   is compiled in the background, so the model grows on screen as it's written. Invalid steps are
   rejected with an error message the model can act on.
4. The result gets checked in several ways: against the checklist, for clashes and spans, against a
   rough IBC/IRC/ADA code screen, and by the model itself looking at rendered screenshots. Anything
   that fails goes back for a fix round.
5. The final version is saved with stable GlobalIds, so an element that survives an edit keeps its ID.

Each version also comes with a set of concept-stage outputs: drawings (SVG/PDF), DXF plans, an Excel
schedule, a rough cost and carbon estimate, and BCF issues.

The LLM sits behind a single small interface, so you can swap providers. There's a mock provider that
needs no model at all and runs the whole test suite, plus adapters for Claude, any OpenAI-compatible
endpoint, Ollama and local GGUF models via llama.cpp.

For the full design (the step vocabulary, how walls are derived, the streaming protocol, the API and
the reasoning behind each decision), see [`docs/architecture.md`](docs/architecture.md).

## Stack

- **Backend:** Python, FastAPI, IfcOpenShell, shapely, SQLite
- **Frontend:** React and Vite, with [That Open](https://github.com/ThatOpen) (web-ifc, fragments,
  three.js) for the viewer
- **Desktop:** Tauri 2 (optional; the app also runs in a browser)

```
backend/            API, agent pipeline, IFC compiler, LLM adapters, tests
frontend/           React app and the Tauri shell (src-tauri/)
packages/ifc-viewer 3D version cards used in the history panel
docs/               screenshot and architecture notes
```

## Running it

You need Python 3.12 or newer and Node 20 or newer. The desktop build also needs Rust, and on Windows
the MSVC C++ build tools and WebView2.

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # optional; without it you get the mock LLM
python main.py          # http://127.0.0.1:8765
```

**Frontend, in a browser** (start the backend first)

```bash
cd frontend
npm install
npm run vite:dev        # http://localhost:5173
```

**Frontend, as a desktop app**

```bash
cd frontend
npm run dev                     # Tauri with hot reload; starts backend/.venv itself if nothing is on 8765
npx tauri build --no-bundle     # release build in src-tauri/target/release
```

### Choosing a model

Out of the box the backend uses the mock LLM. It turns prompts into buildings with templates and
regexes, which is enough to click around and run the tests. For real results, set a provider in
`backend/.env`. The file is re-read before every call, so you don't need to restart.

Claude (what we used for the demo):

```
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
```

Any OpenAI-compatible API (Fireworks, vLLM, LM Studio, and so on):

```
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.fireworks.ai/inference/v1
LLM_MODEL=accounts/fireworks/models/qwen3p8-max
LLM_API_KEY=...
```

A local GGUF model: run `python tools/get_llama.py` once to fetch `llama-server`, then set
`LLM_PROVIDER=llamacpp`, `LLM_MODELS_DIR` and `LLM_MODEL`. For Ollama, set `LLM_PROVIDER=ollama` and
`LLM_MODEL=llama3.1`.

Small local models can do simple houses but struggle with anything detailed. Every setting is listed
in `backend/.env.example` and explained in
[`docs/architecture.md`](docs/architecture.md#3-configuration-and-model-providers).

### No API key? Watch a recorded run

Two real Claude runs ship in `backend/demo/`: a two-floor architecture studio and a two-storey primary
school. They show up on the home screen under *Recorded runs* and play back at 10x speed with the
model's reasoning, each step, the previews and the screenshots it checked. When the replay finishes you
can keep prompting and edit the recorded building.

### Tests

```bash
cd backend
python -m pytest        # runs on the mock LLM; no network, no API key
python tools/eval.py    # scores the configured model on tests/evals/prompts.json
```

## Known limitations

- Buildings are made of rooms on a grid, with polygons and arcs when needed. It works best for
  houses, offices and schools, and gets awkward for anything very freeform.
- Pitched roofs only work on rectangular footprints. Stairs are straight single flights.
- Importing IFC only works for files Tekt produced itself. Arbitrary IFC files can't be edited yet.
- The viewer reloads the whole model on every version instead of patching changed elements.
- The code review, cost and carbon numbers are rough and US-centric. They show what an agent could
  produce, and they aren't a substitute for a professional.
- `web-ifc` is pinned to 0.0.77 on purpose. 0.0.78 breaks the viewer.

If something doesn't work, the backend console logs every LLM call and every rejected step
(`BIM_LOG_LEVEL=DEBUG` shows full prompts), and the browser console logs under `[nocoast]`. There are
more troubleshooting notes in the architecture doc.

## Team

- Kailash Kannan (kailashkannan06@gmail.com)
- Drona Thoka (thokadrona@gmail.com)
- Abhijyot Chadha (abhijyotschadha@gmail.com)
- Randy Yang (pineconees@gmail.com)
- Anshuman Sikhwal (anshumansikhwal@gmail.com)
- Andriy Mulyar (andriy@nomic.ai)
