<#
Workstreams: one branch = one folder (git worktree). Parallel sessions never share a
working tree, so nobody commits onto someone else's branch by accident.

  tools\ws.ps1 setup                 install the commit guards into this clone (once per clone)
  tools\ws.ps1 new demo/vercel       new branch from origin/main in its own folder
  tools\ws.ps1 adopt backend         own folder for an existing (remote) branch
  tools\ws.ps1 list                  every branch: folder, ahead/behind main, unpushed, uncommitted
  tools\ws.ps1 sync [branch]         fetch + rebase that branch onto origin/main (must be clean)
  tools\ws.ps1 claim                 mark the current folder as belonging to its current branch
  tools\ws.ps1 remove demo/vercel    delete the folder once the branch is merged
#>
param(
    [Parameter(Position = 0)][ValidateSet("setup", "new", "adopt", "list", "sync", "claim", "remove", "help")]
    [string]$Command = "list",
    [Parameter(Position = 1)][string]$Branch
)
$ErrorActionPreference = "Stop"

# Named Invoke-*/Read-* on purpose: PowerShell is case-insensitive, so a function called "git" would call itself.
function Invoke-Git {
    # git prints progress on stderr; in Windows PowerShell 5.1 that becomes an error record, so judge by exit code only.
    $ErrorActionPreference = "Continue"
    $out = & git.exe @args 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' '): $($out -join "`n")" }
    $out
}
function Read-Git { & git.exe @args 2>$null }

$top = (Read-Git rev-parse --show-toplevel)
if (-not $top) { throw "Run this inside the repository." }
$common = (Resolve-Path (Join-Path $top (Read-Git rev-parse --git-common-dir))).Path
# The main clone's folder (worktrees hang off its parent) — works from any worktree.
$mainRoot = Split-Path $common -Parent
$worktreeHome = Join-Path (Split-Path $mainRoot -Parent) ((Split-Path $mainRoot -Leaf) + "-worktrees")

function FolderFor([string]$b) { Join-Path $worktreeHome ($b -replace '[\\/]', '-') }

function Claim([string]$dir, [string]$b) {
    $gitDir = (& git.exe -C $dir rev-parse --absolute-git-dir)
    Set-Content -Path (Join-Path $gitDir "workstream") -Value $b -Encoding ascii -NoNewline
}

function Setup {
    $hooks = Join-Path $common "hooks"
    New-Item -ItemType Directory -Force $hooks | Out-Null
    $src = Join-Path $top "tools\githooks"
    if (-not (Test-Path $src)) { throw "tools\githooks not found on this branch; run setup from a branch that has it (main)." }
    foreach ($h in "pre-commit", "commit-msg", "pre-push") {
        Copy-Item (Join-Path $src $h) (Join-Path $hooks $h) -Force
    }
    # Shared by every worktree of this clone, whatever branch they have checked out.
    Write-Host "Installed commit guards into $hooks (pre-commit, commit-msg, pre-push)."
}

function Worktrees {
    $list = @(); $cur = $null
    foreach ($line in (Invoke-Git worktree list --porcelain)) {
        if ($line -like "worktree *") { $cur = [ordered]@{ path = $line.Substring(9); branch = "" }; $list += $cur }
        elseif ($line -like "branch *") { $cur.branch = $line.Substring(7) -replace '^refs/heads/', '' }
    }
    $list
}

switch ($Command) {
    "help" { Get-Help $PSCommandPath; break }

    "setup" { Setup; Claim $top ((Read-Git branch --show-current)); Write-Host "This folder is claimed by '$(Read-Git branch --show-current)'." }

    "new" {
        if (-not $Branch) { throw "Usage: tools\ws.ps1 new <branch>   e.g. demo/vercel" }
        Invoke-Git fetch origin --prune | Out-Null
        $dir = FolderFor $Branch
        Invoke-Git worktree add -b $Branch $dir origin/main | Out-Null
        Claim $dir $Branch
        & git.exe -C $dir config "branch.$Branch.pushRemote" origin
        Write-Host "Created '$Branch' from origin/main in:`n  $dir`nOpen that folder for this work (new terminal / editor / Claude session there)."
    }

    "adopt" {
        if (-not $Branch) { throw "Usage: tools\ws.ps1 adopt <existing-branch>" }
        Invoke-Git fetch origin --prune | Out-Null
        $existing = Worktrees | Where-Object { $_.branch -eq $Branch }
        if ($existing) { Write-Host "'$Branch' already has a folder: $($existing.path)"; break }
        $dir = FolderFor $Branch
        if (Read-Git show-ref --verify "refs/heads/$Branch") { Invoke-Git worktree add $dir $Branch | Out-Null }
        else { Invoke-Git worktree add --track -b $Branch $dir "origin/$Branch" | Out-Null }
        Claim $dir $Branch
        Write-Host "'$Branch' now lives in:`n  $dir"
    }

    "claim" { $b = Read-Git branch --show-current; Claim $top $b; Write-Host "This folder is claimed by '$b'." }

    "sync" {
        $b = if ($Branch) { $Branch } else { Read-Git branch --show-current }
        $wt = Worktrees | Where-Object { $_.branch -eq $b }
        if (-not $wt) { throw "'$b' has no folder; run: tools\ws.ps1 adopt $b" }
        Invoke-Git fetch origin --prune | Out-Null
        if (& git.exe -C $wt.path status --porcelain) { throw "'$b' has uncommitted changes in $($wt.path); commit or stash first." }
        & git.exe -C $wt.path rebase origin/main
        if ($LASTEXITCODE -ne 0) { throw "Rebase stopped on conflicts in $($wt.path). Resolve, then: git rebase --continue" }
        Write-Host "'$b' is now on top of origin/main. Push with: git push --force-with-lease"
    }

    "remove" {
        if (-not $Branch) { throw "Usage: tools\ws.ps1 remove <branch>" }
        $wt = Worktrees | Where-Object { $_.branch -eq $Branch }
        if (-not $wt) { throw "'$Branch' has no folder." }
        if ($wt.path -eq ($mainRoot -replace '\\', '/')) { throw "That's the main clone; not removing it." }
        Invoke-Git worktree remove $wt.path | Out-Null
        Write-Host "Removed folder for '$Branch' (the branch itself is kept)."
    }

    "list" {
        Read-Git fetch origin --prune | Out-Null
        $wts = @(Worktrees)
        $names = @(Read-Git for-each-ref --format='%(refname:short)' refs/heads) +
                 @(Read-Git for-each-ref --format='%(refname:lstrip=3)' refs/remotes/origin) |
                 Where-Object { $_ -and $_ -notin "HEAD", "main", "master", "origin" } | Sort-Object -Unique
        $rows = foreach ($b in $names) {
            $local = [bool](Read-Git show-ref --verify "refs/heads/$b")
            $remote = [bool](Read-Git show-ref --verify "refs/remotes/origin/$b")
            $ref = if ($local) { $b } else { "origin/$b" }
            $ab = (Read-Git rev-list --left-right --count "origin/main...$ref") -split '\s+'
            $wt = $wts | Where-Object { $_.branch -eq $b }
            $unpushed = if ($local -and $remote) { [int](Read-Git rev-list --count "origin/$b..$b") } elseif ($local) { "no remote" } else { "" }
            $dirty = if ($wt) { @(& git.exe -C $wt.path status --porcelain).Count } else { "" }
            [pscustomobject]@{
                Branch      = $b
                Ahead       = [int]$ab[1]
                Behind      = [int]$ab[0]
                Unpushed    = $unpushed
                Uncommitted = $dirty
                Last        = (Read-Git log -1 --format='%cr · %an' $ref)
                Folder      = if ($wt) { $wt.path } elseif ($local) { "(local, no folder)" } else { "(remote only)" }
            }
        }
        $rows | Format-Table -AutoSize | Out-String -Width 220 | Write-Host
        Write-Host "Ahead/Behind are vs origin/main. Give a branch its own folder with: tools\ws.ps1 adopt <branch>"
    }
}
