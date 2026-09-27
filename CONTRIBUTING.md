# Working in parallel

Several people and AI sessions work on this repo at once. Three rules keep the history clean:

1. **One branch = one folder.** Never `git switch` inside a folder someone else is using.
   Each workstream gets its own git worktree:
   ```powershell
   tools\ws.ps1 new demo/vercel      # new branch from origin/main, in ..\<repo>-worktrees\demo-vercel
   tools\ws.ps1 adopt backend        # give an existing branch its own folder
   ```
   Open *that* folder in your terminal, editor or Claude session.
2. **`main` only changes through pull requests.** Branch → push → PR → merge.
3. **Stay current.** `tools\ws.ps1 sync` rebases your branch onto the latest `origin/main`.

See everything at a glance:
```powershell
tools\ws.ps1 list     # branch · ahead/behind main · unpushed · uncommitted · last commit · folder
```

## The guards

Run `tools\ws.ps1 setup` once per clone. It installs git hooks shared by every folder of that clone:

| Hook | Stops |
|---|---|
| pre-commit | commits on `main`; commits in a folder that belongs to a different branch; commits touching files another workstream owns (see `WORKSTREAMS`) |
| commit-msg | nothing; it adds a `Workstream: <branch>` trailer so every commit says where it came from |
| pre-push | pushing directly to `main` |

Each guard prints why it stopped you and how to override once (`ALLOW_MAIN_COMMIT=1`, `ALLOW_CROSS=1`, `ALLOW_MAIN_PUSH=1`).

## Ownership

`WORKSTREAMS` (on `main`) maps branch patterns to the folders they may change. Tighten a line when two
workstreams keep editing the same files; the guard then catches work landing on the wrong branch.
