"""Reading a name is not the same as something having assigned it.

`tests/test_shell_symbols.py` resolves FUNCTION names statically, because
neither interpreter does. This module does the same for the other half of the
problem -- VARIABLES, and the handful of syntax traps where a name is silently
not the name you wrote.

Both gaps were found the same way: a macOS port shipped, and the first Windows
install after it died before installing anything.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _ps_sources() -> list[Path]:
    return [p for p in ROOT.rglob("*.ps1") if ".git" not in p.parts and p.is_file()]


def _sh_sources() -> list[Path]:
    files = [p for p in ROOT.rglob("*.sh") if ".git" not in p.parts]
    files.append(ROOT / "dot_zshrc")
    return [p for p in files if p.is_file()]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


# Bound by the shell, by an argument completer, or automatic. Everything else
# read at script scope has to be assigned at script scope.
PS_AUTOMATIC = {
    "true", "false", "null", "_", "psscriptroot", "pscommandpath", "args", "input",
    "psitem", "error", "lastexitcode", "psversiontable", "home", "pwd", "pid",
    "myinvocation", "psboundparameters", "pscmdlet", "whatifpreference", "profile",
    "erroractionpreference", "progresspreference", "iswindows", "islinux", "ismacos",
    "env", "script", "global", "using", "this", "matches", "host", "outputencoding",
    "verbosepreference", "warningpreference", "confirmpreference", "foreach",
    "switch", "pshome", "debugpreference", "informationpreference", "stacktrace",
    "nestedpromptlevel", "shellid", "psculture", "psdefaultparametervalues",
    # Argument-completer parameters: PowerShell binds these when it calls the block.
    "wordtocomplete", "commandast", "cursorposition", "commandname",
    "parametername", "fakeboundparameters",
}

# Names this scan cannot see the assignment for. Keep it empty if you can; an
# entry is a promise that something else guarantees the value.
PS_SCOPE_ALLOWED: set[str] = set()

# Script-level assignments only, plus the top-level param() block. A dot-sourced
# file's FUNCTION parameters are deliberately NOT counted: treating them as
# script scope is exactly the leniency that made $SourceDir look defined.
PS_SCOPE_SCAN = r"""
$ErrorActionPreference = 'Stop'
$auto = @(__AUTO__)

function Get-ScriptScopeNames([string]$Path, [switch]$IncludeNestedParams) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    $names = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    if ($null -eq $ast) { return , $names }
    $fn = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true) |
        ForEach-Object { $_.Extent }
    $outside = {
        param($ex)
        -not ($fn | Where-Object { $ex.StartOffset -ge $_.StartOffset -and $ex.EndOffset -le $_.EndOffset })
    }
    $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true) |
        Where-Object { & $outside $_.Extent } | ForEach-Object {
            foreach ($v in $_.Left.FindAll({ param($x)
                    $x -is [System.Management.Automation.Language.VariableExpressionAst] }, $true)) {
                [void]$names.Add($v.VariablePath.UserPath)
            }
        }
    if ($ast.ParamBlock) {
        $ast.ParamBlock.Parameters | ForEach-Object { [void]$names.Add($_.Name.VariablePath.UserPath) }
    }
    # Every param() in THIS file, including scriptblocks' -- `$mk = { param($ms) ... }`
    # binds $ms perfectly well, and a scriptblock is not a FunctionDefinitionAst.
    # Only for the file under test: doing it for a DEPENDENCY is the leniency
    # that made $SourceDir look defined.
    if ($IncludeNestedParams) {
        $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.ParamBlockAst] }, $true) |
            ForEach-Object { $_.Parameters } |
            ForEach-Object { [void]$names.Add($_.Name.VariablePath.UserPath) }
    }
    $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.ForEachStatementAst] }, $true) |
        Where-Object { & $outside $_.Extent } |
        ForEach-Object { [void]$names.Add($_.Variable.VariablePath.UserPath) }
    return , $names
}

# Dot-sourced siblings, off the AST rather than a regex: the invocation operator
# says what a dot-source is far more reliably than matching the text of one.
function Get-DotSourced([string]$Path, $Ast) {
    $out = @()
    $dir = Split-Path -Parent $Path
    $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true) |
        Where-Object { $_.InvocationOperator -eq 'Dot' } | ForEach-Object {
            foreach ($s in $_.FindAll({ param($x)
                    $x -is [System.Management.Automation.Language.StringConstantExpressionAst] }, $true)) {
                if ($s.Value -like '*.ps1') {
                    $candidate = Join-Path $dir (Split-Path -Leaf $s.Value)
                    if (Test-Path -LiteralPath $candidate) { $out += $candidate }
                }
            }
        }
    return $out
}

foreach ($f in (Get-ChildItem -Recurse -Filter *.ps1 -Path . |
        Where-Object { $_.FullName -notmatch '[\\/]\.git[\\/]' })) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors)
    if ($errors.Count) {
        "{0}:{1}  PARSE ERROR: {2}" -f $f.FullName, $errors[0].Extent.StartLineNumber, $errors[0].Message
        continue
    }
    $known = Get-ScriptScopeNames $f.FullName -IncludeNestedParams
    foreach ($dep in (Get-DotSourced $f.FullName $ast)) {
        (Get-ScriptScopeNames $dep) | ForEach-Object { [void]$known.Add($_) }
    }
    $fn = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true) |
        ForEach-Object { $_.Extent }
    $bad = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.VariableExpressionAst] }, $true) |
        Where-Object {
            $v = $_; $vp = $v.VariablePath
            (-not $vp.IsGlobal) -and (-not $vp.IsScript) -and
            ($vp.UserPath -notmatch ':') -and
            ($auto -notcontains $vp.UserPath.ToLowerInvariant()) -and
            (-not $known.Contains($vp.UserPath)) -and
            (-not ($fn | Where-Object {
                $v.Extent.StartOffset -ge $_.StartOffset -and $v.Extent.EndOffset -le $_.EndOffset }))
        }
    if ($bad) {
        $bad | Group-Object { $_.VariablePath.UserPath } | ForEach-Object {
            "{0}:{1}  `${2}" -f $f.FullName, $_.Group[0].Extent.StartLineNumber, $_.Name
        }
    }
}
"""


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 is unavailable")
def test_no_powershell_script_reads_a_script_scope_variable_nothing_assigns():
    r"""`$SourceDir` in windows-bootstrap.ps1 -- the gate that would have seen it.

    The macOS port left `Join-Path $SourceDir 'tstack\main.py'` in
    `bootstrap/windows-bootstrap.ps1` with nothing assigning `$SourceDir`: no
    `param()` entry, `install.ps1` calling `& $bootstrap` with no arguments, and
    only a FUNCTION PARAMETER of that name in the dot-sourced `_config.ps1`.
    `Join-Path -Path $null` is terminating, so every fresh Windows install died
    at the questionnaire, before installing anything.

    Nothing in the repo could see it. Every `.ps1` here PARSES, so a parse gate
    is no help; PowerShell has no `bash -n` equivalent for undefined names; and
    CI had no PowerShell job at all. Only a scope-aware AST walk finds it -- and
    it must count a dot-sourced file's SCRIPT-LEVEL assignments only, because
    counting its function parameters is what made `$SourceDir` look defined.
    """
    auto = ", ".join(f"'{n}'" for n in sorted(PS_AUTOMATIC))
    script = PS_SCOPE_SCAN.replace("__AUTO__", auto)
    got = subprocess.run(
        [str(shutil.which("pwsh")), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=ROOT,
        start_new_session=True,
    )
    assert got.returncode == 0, got.stdout + got.stderr
    findings = [
        line.strip()
        for line in got.stdout.splitlines()
        if line.strip() and line.strip().rsplit("$", 1)[-1] not in PS_SCOPE_ALLOWED
    ]
    assert not findings, "read but never assigned at script scope:\n" + "\n".join(findings)


def test_no_powershell_string_swallows_the_variable_name_after_it():
    """`"... set it to $canonRemote? [Y/n]"` printed no URL at all.

    `?` is legal in a PowerShell variable name, so inside an interpolated string
    `$canonRemote?` names a DIFFERENT, undefined variable and expands to empty --
    `bootstrap/_cleanup.ps1` asked the user to confirm changing their git origin
    to nothing. `${name}?` is the fix, and the same trap applies to `:`.
    """
    offenders = []
    pattern = re.compile(r'"[^"\n]*(\$[A-Za-z_][A-Za-z0-9_]*[?])')
    for p in _ps_sources():
        for lineno, line in enumerate(_read(p).splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for m in pattern.finditer(line):
                offenders.append(f"{_rel(p)}:{lineno} {m.group(1)} -- write ${{name}}? instead")
    assert not offenders, "\n" + "\n".join(offenders)
