# Stream Clipper installer for Windows 10/11.
# Double-click install.bat (it runs this script), or in PowerShell:
#   powershell -ExecutionPolicy Bypass -File install.ps1
# Written for Windows PowerShell 5.1 (built into Windows), so no PowerShell 7 syntax.

$ErrorActionPreference = 'Stop'
$RepoUrl = 'https://github.com/sludde05-coder/clipper'
$Interactive = -not $env:CLIPPER_NONINTERACTIVE

function Step($m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [X] $m" -ForegroundColor Red; throw "install failed" }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Refresh-Path {
    # Pick up programs installed a moment ago without reopening the window.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $links = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'
    $env:Path = "$machine;$user;$links"
}

function Add-UserPath($dir) {
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $user) { $user = '' }
    if (($user -split ';') -notcontains $dir) {
        [Environment]::SetEnvironmentVariable('Path', ($user.TrimEnd(';') + ";$dir").TrimStart(';'), 'User')
    }
    $env:Path = "$env:Path;$dir"
}

function Winget-Install($id, $extra) {
    if (-not (Have winget)) {
        Fail ("'winget' is missing. Install 'App Installer' from the Microsoft Store " +
              "(https://apps.microsoft.com/detail/9NBLGGH4NNS1), then run this again.")
    }
    $wingetArgs = @('install', '-e', '--id', $id, '--accept-package-agreements', '--accept-source-agreements')
    if ($extra) { $wingetArgs += $extra }
    & winget @wingetArgs
    Refresh-Path
}

function Test-Python($exe, $pre) {
    # The Microsoft Store "python" stub prints nothing useful here, so it fails this test.
    try {
        $out = & $exe @pre -c "import sys, venv; print(1 if sys.version_info >= (3, 11) else 0)" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq '1')
    } catch { return $false }
}

function Find-Python {
    $candidates = @(
        @{ exe = 'py'; pre = @('-3') },
        @{ exe = 'python'; pre = @() },
        @{ exe = 'python3'; pre = @() }
    )
    $installed = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe'),
                                     'C:\Program Files\Python3*\python.exe' -ErrorAction SilentlyContinue |
                 Sort-Object FullName -Descending
    foreach ($f in $installed) { $candidates += @{ exe = $f.FullName; pre = @() } }
    foreach ($c in $candidates) {
        if (((Have $c.exe) -or (Test-Path $c.exe)) -and (Test-Python $c.exe $c.pre)) { return $c }
    }
    return $null
}

try {
    Write-Host "=============================================="
    Write-Host "   Stream Clipper installer"
    Write-Host "=============================================="
    Write-Host "This installs Python, ffmpeg and everything the clipper needs."
    Write-Host "It can take 5-15 minutes. Windows may ask for permission. Click Yes."
    Refresh-Path

    # ------------------------------------------------------------ Python
    Step "Checking Python 3.11 or newer"
    $py = Find-Python
    if (-not $py) {
        Warn "Not found: installing Python 3.12"
        Winget-Install 'Python.Python.3.12' @('--scope', 'user', '--override',
            '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1')
        $py = Find-Python
        if (-not $py) { Fail "Python still not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this again." }
    }
    $pyVersion = & $py.exe @($py.pre) --version
    Ok "Python: $pyVersion"

    # ------------------------------------------------------------ ffmpeg
    Step "Checking ffmpeg (cuts the video)"
    if (-not (Have ffmpeg)) {
        Warn "Not found: installing ffmpeg"
        Winget-Install 'Gyan.FFmpeg' $null
        if (-not (Have ffmpeg)) {
            # winget sometimes doesn't link it onto PATH: find it and add its folder.
            $exe = Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Recurse `
                     -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($exe) { Add-UserPath $exe.DirectoryName }
        }
        if (-not (Have ffmpeg)) { Fail "ffmpeg didn't install. Run 'winget install ffmpeg' yourself, then run this again." }
    }
    Ok "ffmpeg"

    # ------------------------------------------------------------ project folder
    $here = $PSScriptRoot
    if ($here -and (Test-Path (Join-Path $here 'requirements.txt')) -and (Test-Path (Join-Path $here 'clipper'))) {
        Set-Location $here
    } else {
        Step "Downloading the project to $HOME\clipper"
        if (-not (Have git)) { Winget-Install 'Git.Git' $null }
        if (-not (Have git)) { Fail "Git didn't install. Download the project as a ZIP from $RepoUrl instead." }
        $dest = Join-Path $HOME 'clipper'
        if (Test-Path (Join-Path $dest '.git')) { & git -C $dest pull --ff-only } else { & git clone $RepoUrl $dest }
        if ($LASTEXITCODE -ne 0) { Fail "Download failed." }
        Set-Location $dest
    }
    Ok "Project folder: $(Get-Location)"

    # ------------------------------------------------------------ packages
    Step "Installing the clipper's Python packages (the slow part)"
    $vpy = Join-Path (Get-Location) '.venv\Scripts\python.exe'
    if (-not (Test-Path $vpy)) {
        & $py.exe @($py.pre) -m venv .venv
        if ($LASTEXITCODE -ne 0) { Fail "Couldn't create the Python environment." }
    }
    & $vpy -m pip install --quiet --upgrade pip
    & $vpy -m pip install --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "Package install failed. Check your internet connection and run this again." }
    Ok "Packages installed"

    if (-not (Test-Path 'config.toml')) { Copy-Item 'config.example.toml' 'config.toml'; Ok "Created config.toml" }

    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'

    Step "Checking the clipper works"
    $ErrorActionPreference = 'Continue'
    $selftest = (& $vpy -m clipper -c none simulate 2>&1 | Out-String)
    $ErrorActionPreference = 'Stop'
    if ($selftest -match 'fired') { Ok "Self-test passed" } else { Write-Host $selftest; Fail "Self-test failed. Send the output above to get help." }

    Step "Downloading the speech-to-text model (~500 MB, one time)"
    $ErrorActionPreference = 'Continue'
    & $vpy -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" *> $null
    $whisperOk = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = 'Stop'
    if ($whisperOk) { Ok "Speech model ready" } else { Warn "Couldn't download it now. It will download automatically with the first clip." }

    # ------------------------------------------------------------ keys
    if ($Interactive) {
        Step "API keys"
        & $vpy -m clipper setup
    } else {
        Warn "Skipping key setup. Open the clipper and choose option 6."
    }

    Write-Host ""
    Write-Host "=============================================="
    Write-Host "   All done!" -ForegroundColor Green
    Write-Host "=============================================="
    Write-Host "To start: double-click  Clipper.bat  in $(Get-Location)"
    Write-Host "Tip: try option 4 first to test it on a game that's live today."
    exit 0
} catch {
    if ("$_" -ne 'install failed') { Write-Host "  [X] Unexpected error: $_" -ForegroundColor Red }
    Write-Host "Installation did not finish. Fix the problem above and double-click install.bat again." -ForegroundColor Red
    exit 1
}
