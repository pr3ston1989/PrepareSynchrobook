param([switch]$SetupOnly, [string]$RuntimeDirectory)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$runtime = if ($RuntimeDirectory) { [System.IO.Path]::GetFullPath($RuntimeDirectory) } else { Join-Path $env:LOCALAPPDATA 'PrepareSynchrobook\runtime' }
$venvPython = Join-Path $runtime 'Scripts\python.exe'
$mutex = New-Object System.Threading.Mutex($false, 'Local\PrepareSynchrobook-Setup')
$locked = $false
try {
    try { $locked = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw 'Trwa juz przygotowanie srodowiska. Poczekaj na zakonczenie pierwszego uruchomienia.' }
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $candidates = @()
        $py = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($py) {
            foreach ($version in @('3.13','3.12','3.11','3.10')) {
                $found = & $py.Source "-$version" -c 'import sys,tkinter; print(sys.executable)' 2>$null
                if ($LASTEXITCODE -eq 0 -and $found) { $candidates += [string]($found | Select-Object -Last 1); break }
            }
        }
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($pythonCommand) { $candidates += $pythonCommand.Source }
        foreach ($version in @('Python313','Python312','Python311','Python310')) {
            $candidates += Join-Path $env:LOCALAPPDATA "Programs\Python\$version\python.exe"
        }
        $selected = $null
        foreach ($candidate in ($candidates | Select-Object -Unique)) {
            if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
            & $candidate -c 'import sys, tkinter; assert (3,10) <= sys.version_info[:2] <= (3,13) and sys.maxsize > 2**32' 2>$null
            if ($LASTEXITCODE -eq 0) { $selected = $candidate; break }
        }
        if (-not $selected) { throw 'Zainstaluj Python 3.10-3.13 (64-bit) z python.org, z opcja Tcl/Tk, i uruchom ponownie. Program nie instaluje systemowego Pythona automatycznie.' }
        Write-Host 'Przygotowywanie osobnego srodowiska programu...'
        & $selected -m venv $runtime
        if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie przygotowac srodowiska Python.' }
    }
    $requirements = Join-Path $project 'requirements.txt'
    $hash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    $marker = Join-Path $runtime 'requirements.sha256'
    $installedHash = if (Test-Path -LiteralPath $marker) { (Get-Content -LiteralPath $marker -Raw).Trim() } else { '' }
    if ($installedHash -ne $hash) {
        Write-Host 'Instalowanie zaleznosci. Przy pierwszym uruchomieniu moze to potrwac...'
        & $venvPython -m pip install --disable-pip-version-check -r $requirements
        if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie zainstalowac zaleznosci. Sprawdz internet i ponow uruchomienie.' }
        & $venvPython -c 'import faster_whisper, mutagen, tkinter, ebooklib, bs4, rapidfuzz'
        if ($LASTEXITCODE -ne 0) { throw 'Kontrola zainstalowanego srodowiska nie powiodla sie.' }
        Set-Content -LiteralPath $marker -Value $hash -Encoding ASCII
    }
    $mutex.ReleaseMutex()
    $locked = $false
    if (-not $SetupOnly) {
        Push-Location $project
        try {
            & $venvPython -m prepare_synchrobook
            if ($LASTEXITCODE -ne 0) { throw 'Program zakonczyl sie bledem.' }
        } finally { Pop-Location }
    }
} catch {
    Write-Host ("BLAD: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
