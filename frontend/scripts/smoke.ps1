# Smoke test for the Tauri app: launch, wait for the UI to report ready/error, screenshot the window.
#   .\scripts\smoke.ps1 -Autoload samples/sample-house.ifc -Out shot.png
#   .\scripts\smoke.ps1 -Prompt "two-story house with a garage" -Select IFCWINDOW -Out shot.png
param(
    [string]$Exe = "$PSScriptRoot\..\src-tauri\target\release\generative-bim.exe",
    [string]$Autoload,
    [string]$Prompt,
    [string]$Select,
    [string]$Tab,
    [string]$Out = "$env:TEMP\bim-smoke.png",
    [int]$TimeoutSec = 120,
    # Use the app's real browser profile (sessions persist) instead of a throwaway one.
    [switch]$SharedProfile
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class Win {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[Win]::SetProcessDPIAware() | Out-Null

$state = Join-Path $env:TEMP "bim-smoke-state.json"
Remove-Item $state -ErrorAction SilentlyContinue
$env:BIM_SMOKE = $state
$env:BIM_SMOKE_HOLD = "4"
$env:BIM_AUTOLOAD = $Autoload
$env:BIM_PROMPT = $Prompt
$env:BIM_SMOKE_SELECT = $Select
$env:BIM_SMOKE_TAB = $Tab
if (-not $SharedProfile) {
    # Throwaway WebView2 profile so test sessions never show up in the real app.
    $env:WEBVIEW2_USER_DATA_FOLDER = Join-Path $env:TEMP "bim-smoke-webview"
}

$sw = [Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath (Resolve-Path $Exe) -PassThru
while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
    if (Test-Path $state) {
        $s = Get-Content $state -Raw | ConvertFrom-Json
        if ($s.status -in "ready", "error") { break }
    }
    if ($proc.HasExited) { throw "app exited before reporting (code $($proc.ExitCode))" }
    Start-Sleep -Milliseconds 250
}
$ready = $sw.Elapsed.TotalSeconds
Start-Sleep -Milliseconds 1200  # let the last frames paint

$proc.Refresh()
$h = $proc.MainWindowHandle
$r = New-Object Win+RECT
[Win]::GetWindowRect($h, [ref]$r) | Out-Null
$bmp = New-Object Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
$g = [Drawing.Graphics]::FromImage($bmp)
# PW_RENDERFULLCONTENT (2) captures GPU/WebView2 content even if the window is covered.
$hdc = $g.GetHdc()
[Win]::PrintWindow($h, $hdc, 2) | Out-Null
$g.ReleaseHdc($hdc)
$bmp.Save($Out, [Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()

$mem = [math]::Round($proc.WorkingSet64 / 1MB)
$proc.WaitForExit(10000) | Out-Null
"state:      $(Get-Content $state -Raw)"
"ready in:   {0:N1}s" -f $ready
"shell RAM:  $mem MB (generative-bim.exe only; WebView2 runs in separate msedgewebview2 processes)"
"screenshot: $Out"
