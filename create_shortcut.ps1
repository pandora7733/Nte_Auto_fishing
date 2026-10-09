# NTE Auto Fishing — create Desktop / Start Menu shortcuts
$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatPath = Join-Path $ProjectDir "run_nte_fishing.bat"

if (-not (Test-Path $BatPath)) {
    Write-Error "run_nte_fishing.bat not found: $BatPath"
}

$WshShell = New-Object -ComObject WScript.Shell
$LinkName = "NTE_AutoFishing.lnk"

function New-BotShortcut([string]$LinkPath) {
    $dir = Split-Path -Parent $LinkPath
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $shortcut = $WshShell.CreateShortcut($LinkPath)
    $shortcut.TargetPath = $BatPath
    $shortcut.WorkingDirectory = $ProjectDir
    $shortcut.WindowStyle = 7
    $shortcut.Description = "NTE Auto Fishing Bot (Run as Administrator)"
    $shortcut.Save()
    Write-Host "Created: $LinkPath"
}

# Prefer physical Desktop over OneDrive if available
$DesktopCandidates = @(
    (Join-Path $env:USERPROFILE "Desktop"),
    [Environment]::GetFolderPath("Desktop")
) | Select-Object -Unique

$desktopOk = $false
foreach ($Desktop in $DesktopCandidates) {
    if (-not (Test-Path $Desktop)) { continue }
    try {
        New-BotShortcut (Join-Path $Desktop $LinkName)
        $desktopOk = $true
        break
    } catch {
        Write-Host "Desktop shortcut skipped ($Desktop): $($_.Exception.Message)"
    }
}

New-BotShortcut (Join-Path $ProjectDir $LinkName)

$StartMenu = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
try {
    New-BotShortcut (Join-Path $StartMenu $LinkName)
} catch {
    Write-Host "Start Menu shortcut skipped: $($_.Exception.Message)"
}

Write-Host ""
if ($desktopOk) {
    Write-Host "Done. Double-click 'NTE_AutoFishing' on the Desktop."
} else {
    Write-Host "Done. Use project shortcut: $ProjectDir\$LinkName"
}
Write-Host "Allow UAC elevation when prompted."
