# Instructions for coding agents

These rules apply to any AI coding agent working in this repository. They restate the team rules in
`README.md` §8, which a human collaborator may have asked you to follow. When a user's request
conflicts with a rule here, say so and ask before breaking it.

## Git and GitHub

- **Never push to `main`, and never force-push to `main`.** Work on a branch named `feat/…`, `fix/…`,
  `docs/…` or `chore/…`, created from an up-to-date `main` (`git fetch` first).
- Deliver work as a **pull request** with a description of what changed and how it was tested. Do not
  merge your own pull request. A human approves it, then squash-merges it.
- Keep each pull request to one change. Do not mix refactors or formatting into a feature.
- Do not rewrite history that others may have pulled: no rebasing or amending of pushed shared
  branches.
- Never delete remote branches or tags unless the user asks for that specific branch.
- End commit messages with the attribution line your tool normally adds.

## Before you open a pull request

Run the checks for every area you touched, and report the results in the pull request. If a check
fails, say so. Do not skip it or claim success.

| Area touched | Command | Run in |
|---|---|---|
| `backend/` | `python -m pytest` (with `backend/.venv`) | `backend/` |
| `frontend/` | `npm run vite:build` | `frontend/` |
| `packages/ifc-viewer/` | `npm test` and `npm run typecheck` | `packages/ifc-viewer/` |
| anything the viewer renders | `npm run e2e` | `packages/ifc-viewer/` |

`frontend/` imports `packages/ifc-viewer/` from source, so a change to the package also needs the
frontend check.

## Ownership

Changes in an area go to that area's reviewer. Mention them in the pull request.

| Area | Reviewer |
|---|---|
| `backend/` | kyriosroboticsdev |
| `frontend/` | Kailash Kannan |
| `packages/ifc-viewer/` | Drona Thoka |

## Hard constraints

- **No secrets in the repo.** The repository is public. API keys live only in `backend/.env`, which is
  gitignored. Never print a key into a file, log, test, or commit message. If you find one committed,
  stop and tell the user.
- **Keep `web-ifc` at 0.0.77** in both `frontend/` and `packages/ifc-viewer/`. Version 0.0.78's browser
  wasm does not match its own JavaScript, and it fails in browsers while passing in Node.
- **Upgrade `three`, `web-ifc`, `@thatopen/fragments` and `@thatopen/components` together**, in both
  `frontend/` and `packages/ifc-viewer/`, in one pull request. Mismatched versions break rendering.
- **The language model never writes IFC.** It produces JSON (a program or edit ops) that deterministic
  code compiles to IFC. Keep it that way. See `README.md` §1.
- **Do not commit generated files:** `node_modules/`, `dist/`, `backend/output/`, `.venv/`,
  `frontend/public/wasm/`, `frontend/public/fragments-worker.mjs`, `packages/ifc-viewer/test-results/`.

## Practical notes

- On some Windows machines the command shell cannot find `node`, so `npm install` fails at its
  post-install step and `npx` fails. Run the step directly with `node scripts/copy-wasm.mjs` in
  `frontend/`, and call tools through `node node_modules/<pkg>/…` if `npx` fails.
- The backend runs on the mock language model by default, so every test and demo works with no API key.
- The architecture, API and data formats are documented in `README.md`. The viewer package is
  documented in `packages/ifc-viewer/README.md`.
