param([string]$DesktopDirectory)
$ErrorActionPreference = 'Stop'
try {
    $project = Split-Path -Parent $PSScriptRoot
    $shell = New-Object -ComObject WScript.Shell
    if (-not $DesktopDirectory) { $DesktopDirectory = $shell.SpecialFolders.Item('Desktop') }
    if (-not (Test-Path -LiteralPath $DesktopDirectory -PathType Container)) { throw 'Nie znaleziono folderu pulpitu.' }
    $path = Join-Path $DesktopDirectory 'PrepareSynchrobook.lnk'
    $description = 'PrepareSynchrobook - przygotuj i wyslij synchrobook do Nokturna'
    if (Test-Path -LiteralPath $path) {
        if ($shell.CreateShortcut($path).Description -ne $description) { throw 'Istniejacy skrot ma inne przeznaczenie. Nie zostal nadpisany.' }
    }
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $shortcut.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $project 'tools\start.ps1') + '"'
    $shortcut.WorkingDirectory = $project
    $shortcut.IconLocation = (Join-Path $project 'assets\prepare-synchrobook.ico') + ',0'
    $shortcut.Description = $description
    $shortcut.WindowStyle = 7
    $shortcut.Save()
    Write-Host ('Utworzono skrot: ' + $path)
    Write-Host 'Zachowaj rozpakowany folder programu; skrot uruchamia go z tego miejsca.'
} catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
