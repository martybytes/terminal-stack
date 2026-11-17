# Build the terminal-stack TTS hook/daemon as one console-free Windows exe.
[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist')
)

$ErrorActionPreference = 'Stop'
$buildRoot = Join-Path $env:TEMP ("terminal-stack-tts-build-" + [guid]::NewGuid().ToString('N'))
$venv = Join-Path $buildRoot 'venv'
$work = Join-Path $buildRoot 'work'

function Find-Python {
    foreach ($candidate in @(
        @{ Exe = 'py'; Args = @('-3') },
        @{ Exe = 'python'; Args = @() })) {
        $command = Get-Command $candidate.Exe -CommandType Application `
            -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { continue }
        try {
            $version = & $command.Source @($candidate.Args + @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])'))
            if ($version -and ([version]$version.Trim() -ge [version]'3.10')) {
                return [pscustomobject]@{ Exe = $command.Source; Args = $candidate.Args }
            }
        } catch {}
    }
    throw 'Python 3.10+ is required to build terminal-stack-tts.exe.'
}

New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
try {
    $python = Find-Python
    & $python.Exe @($python.Args + @('-m', 'venv', $venv))
    if ($LASTEXITCODE -ne 0) { throw 'TTS build venv creation failed.' }
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    & $venvPython -m pip install --quiet --disable-pip-version-check `
        'pyinstaller==6.22.2' -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'TTS build dependency installation failed.' }
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    # Captured, not streamed: a good build is ~230 lines of INFO that buried the rest of
    # an install. The whole log is printed when the build fails, so nothing is lost.
    # Captured with Continue, because PyInstaller logs to stderr and Stop would abort
    # on its first INFO line.
    $buildLog = & {
        $ErrorActionPreference = 'Continue'
        & $venvPython -m PyInstaller (Join-Path $PSScriptRoot 'terminal-stack-tts.spec') `
            --noconfirm --clean --distpath $OutputDirectory --workpath $work 2>&1
    }
    if ($LASTEXITCODE -ne 0) {
        $buildLog | ForEach-Object { Write-Host "$_" }
        throw 'PyInstaller TTS build failed.'
    }
    $result = Join-Path $OutputDirectory 'terminal-stack-tts.exe'
    if (-not (Test-Path -LiteralPath $result -PathType Leaf)) {
        throw "PyInstaller did not produce $result"
    }
    Write-Host $result
} finally {
    $resolvedTemp = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
    $resolvedBuild = [IO.Path]::GetFullPath($buildRoot)
    if ($resolvedBuild.StartsWith($resolvedTemp + '\', [StringComparison]::OrdinalIgnoreCase) `
            -and (Split-Path -Leaf $resolvedBuild) -like 'terminal-stack-tts-build-*' `
            -and (Test-Path -LiteralPath $resolvedBuild -PathType Container)) {
        Remove-Item -LiteralPath $resolvedBuild -Recurse -Force
    }
}
