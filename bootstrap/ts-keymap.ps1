<#
.NAME        keymap
.SYNOPSIS    Every keyboard shortcut on this PC in one CSV: global hotkeys (probed, with the owning process named), Windows built-ins, Start-menu shortcut keys, PowerToys, WezTerm, Windows Terminal, VS Code/Cursor/Zed, herdr, Claude Code, PSReadLine, AutoHotkey, and tmux/zsh in WSL. Flags shortcuts another program swallows.
.PLATFORM    windows
.CATEGORY    diagnostics
.USAGE       keymap.ps1 [-OutFile x.csv] [-Identify [-Force]] [-Chord 'ctrl+shift+o'] [-Collect a,b] [-Skip a,b] [-ConflictsOnly] [-DeepScan] [-PassThru] [-Help]
.WHEN        "this shortcut does nothing", "what app has Ctrl+Shift+O", "which program took my hotkey", "list all my keyboard shortcuts", "find keybinding conflicts", "give Claude my keybindings"
.NOTE        Read-only except -Identify, which PRESSES each taken global hotkey once with a hook that
             swallows it, so the owner is named without acting. Owners running elevated (when this is
             not) or 32-bit are not intercepted: their action runs, and the owner stays unnamed.
             Canonical copy: terminal-stack bootstrap/ts-keymap.ps1 (`tstack keys`).
             Twin copy: claude-local tools/windows/diagnostics/keymap.ps1. Keep them identical.
#>
[CmdletBinding()]
param(
    # Where the CSV goes. Default: keymap-<PC>-<date>.csv in the current folder
    # (the Desktop when started from the script's own folder, e.g. the .cmd launcher).
    [string]$OutFile,
    # Which collectors to run (default: all). See -Help for the list.
    [string[]]$Collect = @('all'),
    # Collectors to leave out.
    [string[]]$Skip = @(),
    # Only report these chords, e.g. 'ctrl+shift+o','win+v'. Any spelling works.
    [string[]]$Chord,
    # Name the owner of each taken global hotkey by pressing it once (swallowed).
    [switch]$Identify,
    # Do not ask before pressing (for scripts and agents).
    [switch]$Force,
    # Write only rows that have a conflict.
    [switch]$ConflictsOnly,
    # Also scan app settings files under AppData for hotkey-like settings (slower).
    [switch]$DeepScan,
    # Also probe bare keys (no modifier) such as letters and arrows.
    [switch]$ProbeAllBare,
    # Path to a prebuilt hkspy.dll (otherwise built once from ./hkspy with cargo, then cached).
    [string]$HookDll,
    # Emit the rows to the pipeline as well as writing the CSV.
    [switch]$PassThru,
    # Seconds to wait for each external program (wezterm, pwsh, wsl).
    [int]$TimeoutSec = 30,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3.0

$script:AllCollectors = [ordered]@{
    probe           = 'global hotkeys: tries every modifier+key and lists the ones another program holds'
    windows         = 'Windows built-in shortcuts (Win+E, Win+V, Alt+Tab, ...)'
    shelllinks      = 'shortcut keys set on Start menu, Desktop and taskbar .lnk files'
    powertoys       = 'PowerToys module shortcuts and Keyboard Manager remaps'
    wezterm         = 'WezTerm key tables and leader (wezterm show-keys)'
    windowsterminal = 'Windows Terminal actions (defaults and settings.json)'
    editors         = 'VS Code, Cursor, Windsurf, VSCodium and Zed user keybindings'
    herdr           = 'herdr desktop app keys.json and herdr TUI config.toml'
    claude          = 'Claude Code ~/.claude/keybindings.json'
    psreadline      = 'PowerShell line-editor key handlers (with your profile loaded)'
    autohotkey      = 'hotkeys in running AutoHotkey scripts'
    wsl             = 'tmux list-keys and zsh bindkey inside WSL'
    deepscan        = 'hotkey-like settings in any app settings file under AppData (-DeepScan)'
}

if ($Help) {
    @"
keymap - every keyboard shortcut on this PC, in one CSV

  -OutFile <path>     where to write (default: keymap-<PC>-<date>.csv here)
  -Chord <c>[,<c>]    only these chords, any spelling: 'ctrl+shift+o', 'Win+V', 'alt-space'
  -Identify           name the program behind each taken global hotkey. Presses each one once
                      through a hook that swallows it; asks first unless -Force.
  -Collect a,b        run only these collectors;  -Skip a,b  leave some out
  -ConflictsOnly      only rows where something is swallowed or bound twice
  -DeepScan           also read hotkey-like settings from every app's config under AppData
  -ProbeAllBare       also probe bare keys (letters, arrows) with no modifier
  -PassThru           also return the rows as objects
  -HookDll <path>     use this hkspy.dll instead of building one (needs Rust's cargo once)

Collectors:
"@ | Write-Host
    foreach ($k in $script:AllCollectors.Keys) { Write-Host ('  {0,-16} {1}' -f $k, $script:AllCollectors[$k]) }
    Write-Host @"

CSV columns: Chord, Scope, App, Context, Action, Owner, OwnerPid, Conflict, Source, Path, Notes

Examples:
  keymap.ps1                                   everything, to a CSV
  keymap.ps1 -Chord ctrl+shift+o -Identify     who holds Ctrl+Shift+O?
  keymap.ps1 -Identify -Force -OutFile k.csv   everything, owners named, no questions
  keymap.ps1 -ConflictsOnly                    just the shortcuts that cannot work
"@
    return
}

if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'keymap needs PowerShell 7 (pwsh).' }
if (-not $IsWindows) { throw 'keymap reads Windows hotkeys and settings; run it on Windows.' }

# --------------------------------------------------------------------------- native
if (-not ('KmNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;

public static class KmNative {
    [DllImport("user32.dll", SetLastError = true)] static extern bool RegisterHotKey(IntPtr hWnd, int id, uint mods, uint vk);
    [DllImport("user32.dll", SetLastError = true)] static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)] public static extern IntPtr LoadLibraryW(string path);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Ansi)] public static extern IntPtr GetProcAddress(IntPtr h, string name);
    [DllImport("user32.dll", SetLastError = true)] public static extern IntPtr SetWindowsHookExW(int id, IntPtr proc, IntPtr hMod, uint tid);
    [DllImport("user32.dll", SetLastError = true)] public static extern bool UnhookWindowsHookEx(IntPtr h);
    [DllImport("user32.dll", SetLastError = true)] static extern uint SendInput(uint n, INPUT[] inputs, int size);
    [DllImport("user32.dll")] static extern bool PeekMessageW(out MSG m, IntPtr h, uint a, uint b, uint r);
    [DllImport("user32.dll")] static extern bool TranslateMessage(ref MSG m);
    [DllImport("user32.dll")] static extern IntPtr DispatchMessageW(ref MSG m);
    [DllImport("user32.dll")] static extern short GetAsyncKeyState(int vk);

    [StructLayout(LayoutKind.Sequential)] struct MSG { public IntPtr hwnd; public uint message; public UIntPtr wParam; public IntPtr lParam; public uint time; public int x; public int y; }
    [StructLayout(LayoutKind.Sequential)] struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Sequential)] struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Explicit)] struct UNION { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
    [StructLayout(LayoutKind.Sequential)] struct INPUT { public uint type; public UNION u; }

    // 0 = free, 1 = held by another program, anything else = the Win32 error.
    public static int Probe(uint mods, uint vk) {
        if (RegisterHotKey(IntPtr.Zero, 0x7A12, mods | 0x4000, vk)) { UnregisterHotKey(IntPtr.Zero, 0x7A12); return 0; }
        int e = Marshal.GetLastWin32Error();
        return e == 1409 ? 1 : e;
    }

    static bool Extended(ushort vk) {
        return (vk >= 0x21 && vk <= 0x28) || vk == 0x2C || vk == 0x2D || vk == 0x2E
            || vk == 0x5B || vk == 0x5C || vk == 0x5D || vk == 0x6F || vk == 0x90;
    }
    static INPUT Key(ushort vk, bool up) {
        var i = new INPUT();
        i.type = 1;
        i.u.ki.wVk = vk;
        i.u.ki.dwFlags = (uint)((up ? 2 : 0) | (Extended(vk) ? 1 : 0));
        i.u.ki.dwExtraInfo = new IntPtr(0x4B4D4150);
        return i;
    }
    // Presses mods+vk once (MOD_ALT=1 CTRL=2 SHIFT=4 WIN=8). Returns the events Windows accepted.
    public static uint Press(uint mods, ushort vk) {
        var list = new List<INPUT>();
        var held = new List<ushort>();
        if ((mods & 2) != 0) held.Add(0x11);
        if ((mods & 1) != 0) held.Add(0x12);
        if ((mods & 4) != 0) held.Add(0x10);
        if ((mods & 8) != 0) held.Add(0x5B);
        foreach (var k in held) list.Add(Key(k, false));
        list.Add(Key(vk, false));
        list.Add(Key(vk, true));
        for (int j = held.Count - 1; j >= 0; j--) list.Add(Key(held[j], true));
        return SendInput((uint)list.Count, list.ToArray(), Marshal.SizeOf(typeof(INPUT)));
    }
    public static void Pump(int ms) {
        int end = Environment.TickCount + ms;
        MSG msg;
        while (Environment.TickCount < end) {
            while (PeekMessageW(out msg, IntPtr.Zero, 0, 0, 1)) { TranslateMessage(ref msg); DispatchMessageW(ref msg); }
            Thread.Sleep(15);
        }
    }
    public static bool ModifierHeld() {
        foreach (int k in new[] { 0x10, 0x11, 0x12, 0x5B, 0x5C }) if ((GetAsyncKeyState(k) & 0x8000) != 0) return true;
        return false;
    }
}
'@
}

# --------------------------------------------------------------------------- key names
$script:VkName = @{}
$script:VkName[0x08] = 'Backspace'; $script:VkName[0x09] = 'Tab'; $script:VkName[0x0C] = 'Clear'
$script:VkName[0x0D] = 'Enter'; $script:VkName[0x13] = 'Pause'; $script:VkName[0x14] = 'CapsLock'
$script:VkName[0x1B] = 'Esc'; $script:VkName[0x20] = 'Space'; $script:VkName[0x21] = 'PageUp'
$script:VkName[0x22] = 'PageDown'; $script:VkName[0x23] = 'End'; $script:VkName[0x24] = 'Home'
$script:VkName[0x25] = 'Left'; $script:VkName[0x26] = 'Up'; $script:VkName[0x27] = 'Right'
$script:VkName[0x28] = 'Down'; $script:VkName[0x2C] = 'PrintScreen'; $script:VkName[0x2D] = 'Insert'
$script:VkName[0x2E] = 'Delete'; $script:VkName[0x5D] = 'Menu'; $script:VkName[0x5F] = 'Sleep'
foreach ($i in 0..9) { $script:VkName[0x30 + $i] = "$i"; $script:VkName[0x60 + $i] = "Num$i" }
foreach ($i in 0..25) { $script:VkName[0x41 + $i] = [string][char](0x41 + $i) }
foreach ($i in 1..24) { $script:VkName[0x6F + $i] = "F$i" }
$script:VkName[0x6A] = 'NumMultiply'; $script:VkName[0x6B] = 'NumAdd'; $script:VkName[0x6C] = 'NumSeparator'
$script:VkName[0x6D] = 'NumSubtract'; $script:VkName[0x6E] = 'NumDecimal'; $script:VkName[0x6F] = 'NumDivide'
$script:VkName[0x90] = 'NumLock'; $script:VkName[0x91] = 'ScrollLock'
$script:VkName[0xA6] = 'BrowserBack'; $script:VkName[0xA7] = 'BrowserForward'; $script:VkName[0xA8] = 'BrowserRefresh'
$script:VkName[0xA9] = 'BrowserStop'; $script:VkName[0xAA] = 'BrowserSearch'; $script:VkName[0xAB] = 'BrowserFavorites'
$script:VkName[0xAC] = 'BrowserHome'; $script:VkName[0xAD] = 'VolumeMute'; $script:VkName[0xAE] = 'VolumeDown'
$script:VkName[0xAF] = 'VolumeUp'; $script:VkName[0xB0] = 'MediaNext'; $script:VkName[0xB1] = 'MediaPrev'
$script:VkName[0xB2] = 'MediaStop'; $script:VkName[0xB3] = 'MediaPlayPause'; $script:VkName[0xB4] = 'LaunchMail'
$script:VkName[0xB5] = 'LaunchMedia'; $script:VkName[0xB6] = 'LaunchApp1'; $script:VkName[0xB7] = 'LaunchApp2'
$script:VkName[0xBA] = ';'; $script:VkName[0xBB] = '='; $script:VkName[0xBC] = ','; $script:VkName[0xBD] = '-'
$script:VkName[0xBE] = '.'; $script:VkName[0xBF] = '/'; $script:VkName[0xC0] = '`'; $script:VkName[0xDB] = '['
$script:VkName[0xDC] = '\'; $script:VkName[0xDD] = ']'; $script:VkName[0xDE] = "'"; $script:VkName[0xE2] = 'OEM102'

$script:KeyAlias = @{}
foreach ($vk in $script:VkName.Keys) { $script:KeyAlias[$script:VkName[$vk].ToLowerInvariant()] = $script:VkName[$vk] }
@{
    return = 'Enter'; ret = 'Enter'; cr = 'Enter'; escape = 'Esc'; del = 'Delete'; ins = 'Insert'
    pgup = 'PageUp'; prior = 'PageUp'; pgdn = 'PageDown'; next = 'PageDown'; npage = 'PageDown'; ppage = 'PageUp'
    uparrow = 'Up'; downarrow = 'Down'; leftarrow = 'Left'; rightarrow = 'Right'
    arrowup = 'Up'; arrowdown = 'Down'; arrowleft = 'Left'; arrowright = 'Right'
    spacebar = 'Space'; back = 'Backspace'; bksp = 'Backspace'; bspace = 'Backspace'; bs = 'Backspace'
    prtsc = 'PrintScreen'; print = 'PrintScreen'; snapshot = 'PrintScreen'; printscr = 'PrintScreen'; prtscr = 'PrintScreen'
    backslash = '\'; slash = '/'; comma = ','; period = '.'; dot = '.'; minus = '-'; hyphen = '-'; plus = '+'
    equal = '='; equals = '='; semicolon = ';'; quote = "'"; apostrophe = "'"; backquote = '`'; backtick = '`'; grave = '`'
    bracketleft = '['; leftbracket = '['; openbracket = '['; bracketright = ']'; rightbracket = ']'; closebracket = ']'
    apps = 'Menu'; application = 'Menu'; contextmenu = 'Menu'; capital = 'CapsLock'; scroll = 'ScrollLock'
    numpadadd = 'NumAdd'; numpadsubtract = 'NumSubtract'; numpadmultiply = 'NumMultiply'; numpaddivide = 'NumDivide'
    numpaddecimal = 'NumDecimal'; numpadenter = 'Enter'; kpenter = 'Enter'; enter = 'Enter'
}.GetEnumerator() | ForEach-Object { $script:KeyAlias[$_.Key] = $_.Value }
foreach ($i in 0..9) { $script:KeyAlias["numpad$i"] = "Num$i"; $script:KeyAlias["numpad_$i"] = "Num$i"; $script:KeyAlias["kp$i"] = "Num$i" }

$script:ModAlias = @{
    ctrl = 'Ctrl'; control = 'Ctrl'; ctl = 'Ctrl'; lctrl = 'Ctrl'; rctrl = 'Ctrl'
    alt = 'Alt'; option = 'Alt'; opt = 'Alt'; lalt = 'Alt'; ralt = 'Alt'; menu = 'Alt'
    shift = 'Shift'; lshift = 'Shift'; rshift = 'Shift'
    win = 'Win'; windows = 'Win'; super = 'Win'; meta = 'Win'; cmd = 'Win'; command = 'Win'; lwin = 'Win'; rwin = 'Win'; logo = 'Win'
    leader = 'Leader'
}
$script:ModOrder = @('Leader', 'Ctrl', 'Alt', 'Shift', 'Win')

function Join-KmChord {
    param([string[]]$Mods, [string]$Key)
    $set = @($Mods | Where-Object { $_ } | Select-Object -Unique)
    $ordered = @($script:ModOrder | Where-Object { $set -contains $_ })
    return (@($ordered) + $Key) -join '+'
}

function ConvertTo-KmKey {
    param([string]$Name, [switch]$Strict)
    $n = $Name.Trim()
    if (-not $n) { return $null }
    if ($n -match '^(?i)(phys|physical|mapped|raw)[:(](.+?)\)?$') { $n = $Matches[2] }
    if ($n -match '^(?i)Char\(.(.).\)$') { $n = $Matches[1] }
    if ($n.Length -eq 1) { return $n.ToUpperInvariant() }
    if ($n -match '^(?i)f([1-9]|1\d|2[0-4])$') { return "F$($Matches[1])" }
    $low = $n.ToLowerInvariant() -replace '[ _]', ''
    if ($script:KeyAlias.ContainsKey($low)) { return $script:KeyAlias[$low] }
    if ($low -match '^(digit|key)([0-9a-z])$') { return $Matches[2].ToUpperInvariant() }
    if ($Strict) { return $null }
    if ($n -match '^[A-Za-z][A-Za-z0-9]*$') { return $n.Substring(0, 1).ToUpperInvariant() + $n.Substring(1) }
    return $n
}

# One chord or a sequence ("ctrl+k ctrl+s", "Ctrl+x,Ctrl+e") in canonical form,
# e.g. "Ctrl+Shift+O" or "Ctrl+K, Ctrl+S". $null when the text is not a chord.
# -Strict (for JSON property names): a bare key must be a named key, never a word.
function ConvertTo-KmChord {
    param([string]$Text, [switch]$Strict)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $t = $Text.Trim() -replace '\s*\+\s*(?=\S)', '+'
    if ($t.Length -gt 60) { return $null }
    $parts = @($t -split '\s+(?=\S)|,(?=\s*(?i:ctrl|alt|shift|win|meta|cmd)[+-])' | Where-Object { $_.Trim() })
    $out = foreach ($p in $parts) {
        $rest = $p.Trim(); $mods = @()
        while ($rest -match '^(?i)(ctrl|control|ctl|lctrl|rctrl|alt|option|opt|lalt|ralt|shift|lshift|rshift|win|windows|super|meta|cmd|command|lwin|rwin|logo|leader)[+-](.+)$') {
            $mods += $script:ModAlias[$Matches[1].ToLowerInvariant()]; $rest = $Matches[2]
        }
        if ($rest -match '^(?i)(ctrl|control|alt|shift|win|super|meta|cmd)$') { return $null }
        $k = ConvertTo-KmKey $rest -Strict:($Strict -and $mods.Count -eq 0)
        if (-not $k) { return $null }
        if ($Strict -and $mods.Count -eq 0 -and $k.Length -eq 1) { return $null }
        if ($k -match '\s') { return $null }
        Join-KmChord $mods $k
    }
    return (@($out) -join ', ')
}

function ConvertFrom-KmVk {
    param([uint32]$Mods, [int]$Vk)
    $m = @()
    if ($Mods -band 2) { $m += 'Ctrl' }; if ($Mods -band 1) { $m += 'Alt' }
    if ($Mods -band 4) { $m += 'Shift' }; if ($Mods -band 8) { $m += 'Win' }
    $k = if ($script:VkName.ContainsKey($Vk)) { $script:VkName[$Vk] } else { 'VK_0x{0:X2}' -f $Vk }
    return Join-KmChord $m $k
}

# "Ctrl+Shift+O" -> @{ Mods = 6; Vk = 0x4F }, or $null for a sequence / unknown key.
function ConvertTo-KmVk {
    param([string]$Canonical)
    if (-not $Canonical -or $Canonical.Contains(', ')) { return $null }
    $bits = $Canonical -split '\+'
    $keyName = $bits[-1]; if ($Canonical.EndsWith('++')) { $keyName = '+' }
    [uint32]$m = 0
    foreach ($b in $bits[0..($bits.Count - 2)]) { switch ($b) { 'Alt' { $m = $m -bor 1 } 'Ctrl' { $m = $m -bor 2 } 'Shift' { $m = $m -bor 4 } 'Win' { $m = $m -bor 8 } 'Leader' { return $null } } }
    foreach ($vk in $script:VkName.Keys) { if ($script:VkName[$vk] -ceq $keyName) { return @{ Mods = $m; Vk = [int]$vk } } }
    return $null
}

# --------------------------------------------------------------------------- helpers
$script:Rows = [System.Collections.Generic.List[object]]::new()

function Add-KmRow {
    param(
        [string]$Chord_, [string]$Scope, [string]$App, [string]$Context = '', [string]$Action = '',
        [string]$Owner = '', [string]$OwnerPid = '', [string]$Source, [string]$Path = '', [string]$Notes = ''
    )
    if (-not $Chord_) { return }
    $script:Rows.Add([pscustomobject][ordered]@{
            Chord = $Chord_; Scope = $Scope; App = $App; Context = $Context; Action = $Action
            Owner = $Owner; OwnerPid = $OwnerPid; Conflict = ''; Source = $Source; Path = $Path; Notes = $Notes
        })
}

function Invoke-KmCapture {
    param([string]$File, [string[]]$ArgList = @(), [int]$Seconds = $TimeoutSec)
    $psi = [System.Diagnostics.ProcessStartInfo]::new($File)
    foreach ($a in $ArgList) { $psi.ArgumentList.Add($a) }
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.RedirectStandardInput = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.Environment['WSL_UTF8'] = '1'
    $proc = [System.Diagnostics.Process]::Start($psi)
    $proc.StandardInput.Close()
    $stdout = $proc.StandardOutput.ReadToEndAsync(); $null = $proc.StandardError.ReadToEndAsync()
    if (-not $proc.WaitForExit($Seconds * 1000)) {
        try { $proc.Kill($true) } catch { $null = $_ }
        Write-Warning "$File timed out after $Seconds s"
        return ''
    }
    return $stdout.Result
}

# JSON with comments and trailing commas (VS Code, Windows Terminal, Zed).
function Read-KmJsonc {
    param([string]$Path)
    $src = [System.IO.File]::ReadAllText($Path)
    $sb = [System.Text.StringBuilder]::new($src.Length)
    $inStr = $false; $i = 0
    while ($i -lt $src.Length) {
        $c = $src[$i]
        if ($inStr) {
            [void]$sb.Append($c)
            if ($c -eq '\' -and $i + 1 -lt $src.Length) { [void]$sb.Append($src[$i + 1]); $i += 2; continue }
            if ($c -eq '"') { $inStr = $false }
            $i++; continue
        }
        if ($c -eq '"') { $inStr = $true; [void]$sb.Append($c); $i++; continue }
        if ($c -eq '/' -and $i + 1 -lt $src.Length -and $src[$i + 1] -eq '/') { while ($i -lt $src.Length -and $src[$i] -ne "`n") { $i++ }; continue }
        if ($c -eq '/' -and $i + 1 -lt $src.Length -and $src[$i + 1] -eq '*') {
            $end = $src.IndexOf('*/', $i + 2); $i = if ($end -lt 0) { $src.Length } else { $end + 2 }; continue
        }
        [void]$sb.Append($c); $i++
    }
    $clean = [regex]::Replace($sb.ToString(), ',(\s*[}\]])', '$1')
    return $clean | ConvertFrom-Json -AsHashtable -Depth 100
}

function Format-KmAction {
    param($Value)
    if ($null -eq $Value) { return '' }
    if ($Value -is [string]) { return $Value }
    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($k in 'action', 'command', 'name', 'id') {
            if ($Value.Contains($k) -and $Value[$k] -is [string]) {
                $extra = @($Value.Keys | Where-Object { $_ -ne $k })
                if (-not $extra) { return $Value[$k] }
                $args_ = ($extra | ForEach-Object { "$_=$(($Value[$_] | ConvertTo-Json -Compress -Depth 4))" }) -join ' '
                return "$($Value[$k]) $args_"
            }
        }
    }
    $j = $Value | ConvertTo-Json -Compress -Depth 5
    if ($j.Length -gt 200) { $j = $j.Substring(0, 197) + '...' }
    return $j
}

# Walks a parsed JSON settings file for key bindings in any of the common shapes:
#   { "key": "ctrl+k", "command": "x", "when": "..." }      VS Code, WT, Cursor
#   { "keys": ["ctrl+t"], "command": {...} }                 Windows Terminal
#   { "ctrl-shift-o": "pane.split:right" }                   herdr, Claude Code, Zed
#   { "context": "Chat", "bindings": { ... } }               Claude Code, Zed
function Find-KmJsonBinding {
    param($Node, [string]$Ctx, [System.Collections.Generic.List[object]]$Into)
    if ($Node -is [System.Collections.IDictionary]) {
        $spec = $null
        foreach ($k in 'keys', 'key', 'keystroke', 'shortcut', 'hotkey') { if ($Node.Contains($k)) { $spec = $Node[$k]; break } }
        $act = $null
        foreach ($k in 'command', 'action', 'id', 'name') { if ($Node.Contains($k)) { $act = $Node[$k]; break } }
        if ($null -ne $spec -and $null -ne $act -and ($spec -is [string] -or $spec -is [array])) {
            $where = $Ctx
            if ($Node.Contains('when') -and $Node['when']) { $where = (@($Ctx, "when $($Node['when'])") | Where-Object { $_ }) -join ' / ' }
            foreach ($s in @($spec)) {
                if ($s -isnot [string]) { continue }
                $cc = ConvertTo-KmChord $s
                if ($cc) { $Into.Add([pscustomobject]@{ Chord = $cc; Action = (Format-KmAction $act); Context = $where; Raw = $s }) }
            }
            return
        }
        $here = $Ctx
        if ($Node.Contains('context') -and $Node['context'] -is [string]) { $here = $Node['context'] }
        foreach ($k in @($Node.Keys)) {
            if ($k -is [string] -and $k.StartsWith('$')) { continue }
            $v = $Node[$k]
            $cc = if ($k -is [string]) { ConvertTo-KmChord $k -Strict } else { $null }
            if ($cc -and ($null -eq $v -or $v -is [string] -or $v -is [System.Collections.IDictionary] -or $v -is [array])) {
                $Into.Add([pscustomobject]@{ Chord = $cc; Action = (Format-KmAction $v); Context = $here; Raw = $k }); continue
            }
            if ($v -is [System.Collections.IDictionary] -or $v -is [array]) {
                $sub = if ($k -in 'bindings', 'keybindings', 'actions', 'keys', 'properties', 'context') { $here }
                elseif ($here) { "$here/$k" } else { "$k" }
                Find-KmJsonBinding $v $sub $Into
            }
        }
    }
    elseif ($Node -is [array] -or $Node -is [System.Collections.IList]) {
        foreach ($item in $Node) { Find-KmJsonBinding $item $Ctx $Into }
    }
}

function Add-KmJsonFile {
    param([string]$Path, [string]$App, [string]$Scope, [string]$Owner, [string]$Source, [string]$Ctx = '', [string]$Notes = '')
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try { $doc = Read-KmJsonc $Path } catch { Write-Warning "$App - cannot parse $Path ($($_.Exception.Message))"; return }
    $found = [System.Collections.Generic.List[object]]::new()
    Find-KmJsonBinding $doc $Ctx $found
    foreach ($b in $found) { Add-KmRow -Chord_ $b.Chord -Scope $Scope -App $App -Context $b.Context -Action $b.Action -Owner $Owner -Source $Source -Path $Path -Notes $Notes }
    return $found.Count
}

# --------------------------------------------------------------------------- collectors
function Invoke-KmProbe {
    $keys = [System.Collections.Generic.List[int]]::new()
    foreach ($vk in $script:VkName.Keys) { if ($vk -notin 0x14, 0x90) { $keys.Add([int]$vk) } }
    $bareOk = { param($vk) $script:ProbeBareAll -or ($vk -ge 0x70 -and $vk -le 0x87) -or $vk -in 0x13, 0x2C, 0x91, 0x5F, 0x0C -or ($vk -ge 0xA6 -and $vk -le 0xB7) }
    $taken = 0; $odd = @{}
    foreach ($mods in 0..15) {
        foreach ($vk in $keys) {
            if ($mods -eq 0 -and -not (& $bareOk $vk)) { continue }
            $r = [KmNative]::Probe([uint32]$mods, [uint32]$vk)
            if ($r -eq 0) { continue }
            $cc = ConvertFrom-KmVk $mods $vk
            if ($r -eq 1) {
                $taken++
                Add-KmRow -Chord_ $cc -Scope 'Global hotkey' -App '(unknown - run with -Identify)' -Source 'probe' -Notes 'held by another program (RegisterHotKey)'
            }
            else { $odd[$r] = 1 + [int]$odd[$r] }
        }
    }
    foreach ($e in $odd.Keys) { Write-Verbose "probe: Win32 error $e on $($odd[$e]) chords (usually reserved keys such as F12)" }
    Write-Host ("  probe: {0} global hotkeys held by other programs" -f $taken)
}

function Invoke-KmWindows {
    $builtin = [ordered]@{
        'Win+A' = 'Quick Settings'; 'Win+B' = 'Focus the system tray'; 'Win+C' = 'Copilot'; 'Win+D' = 'Show or hide the desktop'
        'Win+E' = 'File Explorer'; 'Win+G' = 'Game Bar'; 'Win+H' = 'Voice typing'; 'Win+I' = 'Settings'; 'Win+K' = 'Cast'
        'Win+L' = 'Lock the PC'; 'Win+M' = 'Minimize all'; 'Win+Shift+M' = 'Restore minimized windows'; 'Win+N' = 'Notifications and calendar'
        'Win+P' = 'Display projection'; 'Win+R' = 'Run'; 'Win+S' = 'Search'; 'Win+T' = 'Cycle taskbar apps'; 'Win+U' = 'Accessibility settings'
        'Win+V' = 'Clipboard history'; 'Win+W' = 'Widgets'; 'Win+X' = 'Quick Link menu'; 'Win+Z' = 'Snap layouts'
        'Win+.' = 'Emoji panel'; 'Win+;' = 'Emoji panel'; 'Win+Tab' = 'Task View'; 'Win+Up' = 'Maximize window'; 'Win+Down' = 'Restore or minimize window'
        'Win+Left' = 'Snap left'; 'Win+Right' = 'Snap right'; 'Win+Home' = 'Minimize all but the active window'
        'Win+Shift+S' = 'Snipping Tool region capture'; 'Win+PrintScreen' = 'Screenshot to Pictures'; 'PrintScreen' = 'Snipping Tool (when enabled)'
        'Win+Ctrl+D' = 'New virtual desktop'; 'Win+Ctrl+F4' = 'Close virtual desktop'; 'Win+Ctrl+Left' = 'Previous virtual desktop'; 'Win+Ctrl+Right' = 'Next virtual desktop'
        'Win+Ctrl+Shift+B' = 'Restart the graphics driver'; 'Win+Alt+R' = 'Game Bar: record'; 'Win+Alt+PrintScreen' = 'Game Bar: screenshot'
        'Win+Alt+D' = 'Date and time'; 'Win+Alt+K' = 'Mute microphone (supported calls)'; 'Win+Space' = 'Switch input language'
        'Win+Ctrl+Enter' = 'Narrator'; 'Win+=' = 'Magnifier zoom in'; 'Win+-' = 'Magnifier zoom out'; 'Win+Esc' = 'Close Magnifier'
        'Win+Pause' = 'System information'; 'Win+/' = 'IME reconversion'; 'Win+Shift+C' = 'Copilot (keyboard)'
        'Ctrl+Shift+Esc' = 'Task Manager'; 'Ctrl+Alt+Delete' = 'Security screen'; 'Alt+Tab' = 'Switch windows'; 'Alt+Shift+Tab' = 'Switch windows (back)'
        'Alt+F4' = 'Close the window'; 'Ctrl+Esc' = 'Start'; 'Alt+Space' = 'Window menu'; 'Alt+Esc' = 'Cycle windows in order opened'
        'Win+Ctrl+Shift+Alt+L' = 'Office: LinkedIn (Office key)'; 'Ctrl+Win+C' = 'Color filters'
    }
    foreach ($i in 1..9) { $builtin["Win+$i"] = "Taskbar app $i"; $builtin["Win+Shift+$i"] = "New window of taskbar app $i" }
    foreach ($k in $builtin.Keys) {
        $cc = ConvertTo-KmChord $k
        Add-KmRow -Chord_ $cc -Scope 'Windows built-in' -App 'Windows' -Action $builtin[$k] -Owner 'explorer.exe' -Source 'windows' -Notes 'standard Windows 11 shortcut; some are handled outside RegisterHotKey'
    }
}

function Invoke-KmShellLinks {
    $shell = New-Object -ComObject WScript.Shell
    $roots = @(
        [Environment]::GetFolderPath('StartMenu'), [Environment]::GetFolderPath('CommonStartMenu'),
        [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory'),
        (Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
    $n = 0
    foreach ($r in $roots) {
        foreach ($f in Get-ChildItem -LiteralPath $r -Recurse -Filter *.lnk -File -ErrorAction SilentlyContinue) {
            try { $lnk = $shell.CreateShortcut($f.FullName) } catch { continue }
            if (-not $lnk.Hotkey) { continue }
            $cc = ConvertTo-KmChord ($lnk.Hotkey -replace '\s', '')
            if (-not $cc) { continue }
            $n++
            Add-KmRow -Chord_ $cc -Scope 'Global hotkey' -App $f.BaseName -Action "Launch $($lnk.TargetPath) $($lnk.Arguments)".Trim() -Owner 'explorer.exe' -Source 'shelllinks' -Path $f.FullName -Notes 'shortcut key on a .lnk; Explorer registers it'
        }
    }
    Write-Host "  shelllinks: $n"
}

function Invoke-KmPowerToys {
    $base = Join-Path $env:LOCALAPPDATA 'Microsoft\PowerToys'
    if (-not (Test-Path -LiteralPath $base)) { Write-Host '  powertoys: not installed'; return }
    $enabled = @{}
    try { $g = Read-KmJsonc (Join-Path $base 'settings.json'); if ($g.Contains('enabled')) { $enabled = $g['enabled'] } } catch { $null = $_ }
    $n = 0
    foreach ($f in Get-ChildItem -LiteralPath $base -Directory) {
        $file = Join-Path $f.FullName 'settings.json'
        if (-not (Test-Path -LiteralPath $file)) { continue }
        try { $doc = Read-KmJsonc $file } catch { continue }
        $module = $f.Name
        $state = if ($enabled.Contains($module)) { if ($enabled[$module]) { 'module on' } else { 'module OFF: shortcut inactive' } } else { '' }
        $stack = [System.Collections.Generic.Stack[object]]::new()
        $stack.Push(@($doc, ''))
        while ($stack.Count) {
            $pair = $stack.Pop(); $node = $pair[0]; $path = $pair[1]
            if ($node -is [System.Collections.IDictionary]) {
                if ($node.Contains('code') -and ($node.Contains('win') -or $node.Contains('ctrl') -or $node.Contains('alt'))) {
                    $vk = [int]$node['code']
                    if ($vk -gt 0) {
                        [uint32]$m = 0
                        if ($node['alt']) { $m = $m -bor 1 }; if ($node['ctrl']) { $m = $m -bor 2 }
                        if ($node['shift']) { $m = $m -bor 4 }; if ($node['win']) { $m = $m -bor 8 }
                        if ($path -notmatch '(?i)default') {
                            $n++
                            $label = ($path -replace '^\.?properties\.', '' -replace '\.value$', '').Trim('.')
                            Add-KmRow -Chord_ (ConvertFrom-KmVk $m $vk) -Scope 'Global hotkey' -App "PowerToys $module" -Action $label -Owner 'PowerToys' -Source 'powertoys' -Path $file -Notes $state
                        }
                    }
                    continue
                }
                foreach ($k in @($node.Keys)) { $stack.Push(@($node[$k], "$path.$k")) }
            }
            elseif ($node -is [System.Collections.IList]) { for ($i = 0; $i -lt $node.Count; $i++) { $stack.Push(@($node[$i], "$path[$i]")) } }
        }
    }
    # Keyboard Manager remaps: "91;13" is a list of virtual-key codes.
    $kbm = Join-Path $base 'Keyboard Manager\default.json'
    if (Test-Path -LiteralPath $kbm) {
        $doc = Read-KmJsonc $kbm
        $toChord = {
            param([string]$codes)
            $m = @(); $k = $null
            foreach ($c in ($codes -split ';' | Where-Object { $_ })) {
                switch ([int]$c) {
                    { $_ -in 17, 162, 163 } { $m += 'Ctrl'; continue }
                    { $_ -in 18, 164, 165 } { $m += 'Alt'; continue }
                    { $_ -in 16, 160, 161 } { $m += 'Shift'; continue }
                    { $_ -in 91, 92 } { $m += 'Win'; continue }
                    default { $k = if ($script:VkName.ContainsKey([int]$c)) { $script:VkName[[int]$c] } else { 'VK_0x{0:X2}' -f [int]$c } }
                }
            }
            if (-not $k) { return (($m | Select-Object -Unique) -join '+') }
            Join-KmChord $m $k
        }
        $sections = @(
            @('remapKeys', 'Key remap'), @('remapShortcuts', 'Shortcut remap'),
            @('remapKeysToText', 'Key to text'), @('remapShortcutsToText', 'Shortcut to text')
        )
        foreach ($s in $sections) {
            if (-not $doc.Contains($s[0])) { continue }
            foreach ($bucket in $doc[$s[0]].Keys) {
                foreach ($e in @($doc[$s[0]][$bucket])) {
                    if (-not $e.Contains('originalKeys')) { continue }
                    $from = & $toChord ([string]$e['originalKeys'])
                    $to = if ($e.Contains('runProgramFilePath') -and $e['runProgramFilePath']) { "Run $($e['runProgramFilePath']) $($e['runProgramArgs'])".Trim() }
                    elseif ($e.Contains('unicodeText') -and $e['unicodeText'] -and $e['unicodeText'] -ne '*Unsupported*') { "Type '$($e['unicodeText'])'" }
                    elseif ($e.Contains('newRemapKeys')) { "Send $(& $toChord ([string]$e['newRemapKeys']))" }
                    elseif ($e.Contains('newRemapString')) { "Type '$($e['newRemapString'])'" }
                    else { 'remap' }
                    $ctx = if ($e.Contains('targetApp') -and $e['targetApp']) { "only in $($e['targetApp'])" } else { $bucket }
                    $n++
                    Add-KmRow -Chord_ $from -Scope 'Global remap' -App 'PowerToys Keyboard Manager' -Context "$($s[1]) ($ctx)" -Action $to -Owner 'PowerToys' -Source 'powertoys' -Path $kbm -Notes $(if ($enabled.Contains('Keyboard Manager') -and -not $enabled['Keyboard Manager']) { 'module OFF' } else { '' })
                }
            }
        }
    }
    Write-Host "  powertoys: $n"
}

function Invoke-KmWezTerm {
    $exe = Get-Command wezterm.exe, wezterm -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $exe) { Write-Host '  wezterm: not installed'; return }
    $text = Invoke-KmCapture $exe.Source @('show-keys')
    $cfg = if ($env:WEZTERM_CONFIG_FILE) { $env:WEZTERM_CONFIG_FILE } else { Join-Path $HOME '.wezterm.lua' }
    $table = 'default'; $n = 0
    $modRx = '(?:CTRL|SHIFT|ALT|SUPER|LEADER|META|WIN|CMD|OPT|NONE)'
    foreach ($line in ($text -split "`r?`n")) {
        if ($line -match '^Leader:\s*(\S+)\s*(.*?)\s*(\d+s)?\s*$') {
            $mods = @($Matches[2] -split '\s*\|\s*' | Where-Object { $_ } | ForEach-Object { $script:ModAlias[$_.ToLowerInvariant()] })
            $k = ConvertTo-KmKey $Matches[1]
            if ($k) { $n++; Add-KmRow -Chord_ (Join-KmChord $mods $k) -Scope 'App' -App 'WezTerm' -Context 'leader' -Action 'Leader key (prefix for Leader+... bindings)' -Owner 'wezterm-gui.exe' -Source 'wezterm' -Path $cfg }
            continue
        }
        if ($line -match '^Key Table:\s*(\S+)') { $table = $Matches[1]; continue }
        if ($line -match '^Default key table') { $table = 'default'; continue }
        if ($line -match "^\s+(?<m>$modRx(?:\s*\|\s*$modRx)*)?\s+(?<k>\S+)\s+->\s+(?<a>.+?)\s*$") {
            $mods = @(); if ($Matches['m']) { $mods = @($Matches['m'] -split '\s*\|\s*' | Where-Object { $_ -and $_ -ne 'NONE' } | ForEach-Object { $script:ModAlias[$_.ToLowerInvariant()] }) }
            $rawKey = $Matches['k']; $act = $Matches['a']
            $k = ConvertTo-KmKey $rawKey
            if (-not $k) { continue }
            if ($rawKey -cmatch '^[A-Z]$') { $mods += 'Shift' }
            $n++
            Add-KmRow -Chord_ (Join-KmChord $mods $k) -Scope 'App' -App 'WezTerm' -Context $table -Action $act -Owner 'wezterm-gui.exe' -Source 'wezterm' -Path $cfg
        }
    }
    Write-Host "  wezterm: $n"
}

function Invoke-KmWindowsTerminal {
    $n = 0
    $files = [System.Collections.Generic.List[object]]::new()
    foreach ($pkg in Get-AppxPackage -Name 'Microsoft.WindowsTerminal*' -ErrorAction SilentlyContinue) {
        $d = Join-Path $pkg.InstallLocation 'defaults.json'
        if (Test-Path -LiteralPath $d) { $files.Add(@($d, "$($pkg.Name) defaults", 'default')) }
        $s = Join-Path $env:LOCALAPPDATA "Packages\$($pkg.PackageFamilyName)\LocalState\settings.json"
        if (Test-Path -LiteralPath $s) { $files.Add(@($s, "$($pkg.Name) settings", 'yours')) }
    }
    $loose = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows Terminal\settings.json'
    if (Test-Path -LiteralPath $loose) { $files.Add(@($loose, 'unpackaged settings', 'yours')) }
    foreach ($f in $files) {
        try { $doc = Read-KmJsonc $f[0] } catch { Write-Warning "Windows Terminal: cannot parse $($f[0])"; continue }
        $byId = @{}
        foreach ($a in @($doc['actions'])) {
            if ($a -is [System.Collections.IDictionary] -and $a.Contains('id') -and $a.Contains('command')) { $byId[[string]$a['id']] = Format-KmAction $a['command'] }
        }
        $found = [System.Collections.Generic.List[object]]::new()
        foreach ($section in 'actions', 'keybindings') { if ($doc.Contains($section)) { Find-KmJsonBinding $doc[$section] '' $found } }
        foreach ($b in $found) {
            $act = if ($byId.ContainsKey($b.Action)) { $byId[$b.Action] } else { $b.Action }
            $n++
            Add-KmRow -Chord_ $b.Chord -Scope 'App' -App 'Windows Terminal' -Context $f[2] -Action $act -Owner 'WindowsTerminal.exe' -Source 'windowsterminal' -Path $f[0] -Notes $f[1]
        }
    }
    Write-Host "  windowsterminal: $n"
}

function Invoke-KmEditors {
    $n = 0
    $editors = @(
        @('VS Code', "$env:APPDATA\Code\User\keybindings.json", 'Code.exe'),
        @('VS Code Insiders', "$env:APPDATA\Code - Insiders\User\keybindings.json", 'Code - Insiders.exe'),
        @('Cursor', "$env:APPDATA\Cursor\User\keybindings.json", 'Cursor.exe'),
        @('Windsurf', "$env:APPDATA\Windsurf\User\keybindings.json", 'Windsurf.exe'),
        @('VSCodium', "$env:APPDATA\VSCodium\User\keybindings.json", 'VSCodium.exe'),
        @('Zed', "$env:APPDATA\Zed\keymap.json", 'zed.exe')
    )
    foreach ($e in $editors) {
        $c = Add-KmJsonFile -Path $e[1] -App $e[0] -Scope 'App' -Owner $e[2] -Source 'editors' -Notes 'your overrides only; built-in defaults are not listed'
        if ($c) { $n += $c }
    }
    Write-Host "  editors: $n"
}

function Invoke-KmHerdr {
    $n = 0
    $keys = Join-Path $HOME '.config\herdr-app\keys.json'
    $c = Add-KmJsonFile -Path $keys -App 'herdr' -Scope 'App' -Owner 'herdr-app.exe' -Source 'herdr'
    if ($c) { $n += $c }
    foreach ($toml in @((Join-Path $HOME '.config\herdr\config.toml'), (Join-Path $env:APPDATA 'herdr\config.toml'))) {
        if (-not (Test-Path -LiteralPath $toml)) { continue }
        $section = ''
        foreach ($line in Get-Content -LiteralPath $toml) {
            if ($line -match '^\s*\[([^\]]+)\]') { $section = $Matches[1]; continue }
            if ($section -notmatch '(?i)key') { continue }
            if ($line -match '^\s*([\w.-]+)\s*=\s*"([^"]+)"') {
                $cc = ConvertTo-KmChord $Matches[2]
                if ($cc) { $n++; Add-KmRow -Chord_ $cc -Scope 'App' -App 'herdr TUI' -Context $section -Action $Matches[1] -Owner 'herdr.exe' -Source 'herdr' -Path $toml }
            }
            elseif ($line -match '^\s*"?([^"=]+?)"?\s*=\s*"([^"]+)"') {
                $cc = ConvertTo-KmChord $Matches[1]
                if ($cc) { $n++; Add-KmRow -Chord_ $cc -Scope 'App' -App 'herdr TUI' -Context $section -Action $Matches[2] -Owner 'herdr.exe' -Source 'herdr' -Path $toml }
            }
        }
    }
    Write-Host "  herdr: $n"
}

function Invoke-KmClaude {
    $c = Add-KmJsonFile -Path (Join-Path $HOME '.claude\keybindings.json') -App 'Claude Code' -Scope 'App' -Owner 'claude.exe' -Source 'claude' -Notes 'your keybindings.json; built-in defaults are not listed'
    Write-Host "  claude: $([int]$c)"
}

function Invoke-KmPSReadLine {
    $pwsh = (Get-Process -Id $PID).Path
    $cmd = 'Import-Module PSReadLine -ErrorAction SilentlyContinue; Get-PSReadLineKeyHandler -Bound | ForEach-Object { "{0}`t{1}`t{2}" -f $_.Key, $_.Function, $_.Group }'
    $text = Invoke-KmCapture $pwsh @('-NoLogo', '-Command', $cmd)
    $n = 0
    foreach ($line in ($text -split "`r?`n")) {
        $f = $line -split "`t"
        if ($f.Count -lt 3) { continue }
        $raw = $f[0]
        # PSReadLine spells Ctrl+Shift+c as "Ctrl+C": a capital letter carries the Shift.
        $spelled = [regex]::Replace($raw, '(^|[+,])([A-Z])(?=,|$)', { param($mt) "$($mt.Groups[1].Value)Shift+$($mt.Groups[2].Value)" })
        $cc = ConvertTo-KmChord ($spelled -replace ',(?=\S)', ' ')
        if (-not $cc) { $cc = $raw }
        $n++
        Add-KmRow -Chord_ $cc -Scope 'Shell' -App 'PowerShell (PSReadLine)' -Context $f[2] -Action $f[1] -Owner 'pwsh.exe' -Source 'psreadline' -Path $PROFILE
    }
    Write-Host "  psreadline: $n"
}

function Invoke-KmAutoHotkey {
    $n = 0
    $procs = Get-CimInstance Win32_Process -Filter "Name LIKE 'AutoHotkey%'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        $script_ = $null
        if ($p.CommandLine -match '"([^"]+\.ahk)"') { $script_ = $Matches[1] }
        elseif ($p.CommandLine -match '(\S+\.ahk)') { $script_ = $Matches[1] }
        if (-not $script_ -or -not (Test-Path -LiteralPath $script_)) { continue }
        foreach ($line in Get-Content -LiteralPath $script_) {
            if ($line -notmatch '^\s*(?<hk>[~*$]*(?:[<>]?[#!^+])*[^\s:;]+?)::(?<act>.*)$' -or $line -match '^\s*:') { continue }
            $hk = $Matches['hk'] -replace '^[~*$]+', ''
            $act = $Matches['act'].Trim()
            $m = @()
            while ($hk -match '^[<>]?([#!^+])(.+)$') {
                switch ($Matches[1]) { '#' { $m += 'Win' } '!' { $m += 'Alt' } '^' { $m += 'Ctrl' } '+' { $m += 'Shift' } }
                $hk = $Matches[2]
            }
            $k = ConvertTo-KmKey $hk
            if (-not $k) { continue }
            $n++
            Add-KmRow -Chord_ (Join-KmChord $m $k) -Scope 'Global hotkey' -App 'AutoHotkey' -Context (Split-Path -Leaf $script_) -Action $(if ($act) { $act } else { '(block below)' }) -Owner $p.Name -OwnerPid $p.ProcessId -Source 'autohotkey' -Path $script_
        }
    }
    Write-Host "  autohotkey: $n"
}

function ConvertFrom-KmTmuxKey {
    param([string]$Key)
    $m = @(); $k = $Key
    while ($k -match '^([CMS])-(.+)$') {
        switch -CaseSensitive ($Matches[1]) { 'C' { $m += 'Ctrl' } 'M' { $m += 'Alt' } 'S' { $m += 'Shift' } }
        $k = $Matches[2]
    }
    if ($k -match "^'(.+)'$" -or $k -match '^"(.+)"$') { $k = $Matches[1] }
    if ($k.Length -gt 1) { $k = $k -replace '^\\', '' }
    $named = ConvertTo-KmKey $k -Strict
    if (-not $named) { $named = if ($k.Length -eq 1) { $k } else { $k } }
    elseif ($k.Length -eq 1 -and $k -cmatch '[A-Z]') { $m += 'Shift' }
    return Join-KmChord $m $named
}

function ConvertFrom-KmZshKey {
    param([string]$Seq)
    $s = $Seq.Trim('"')
    $out = [System.Collections.Generic.List[string]]::new()
    $i = 0
    while ($i -lt $s.Length) {
        $alt = $false
        if ($s.Substring($i).StartsWith('^[') -and $i + 2 -lt $s.Length) { $alt = $true; $i += 2 }
        elseif ($s.Substring($i).StartsWith('\e') -and $i + 2 -lt $s.Length) { $alt = $true; $i += 2 }
        $m = @(); if ($alt) { $m += 'Alt' }
        if ($s[$i] -eq '^' -and $i + 1 -lt $s.Length) {
            $c = $s[$i + 1]; $i += 2
            $k = switch -CaseSensitive ($c) { '?' { 'Backspace' } 'I' { 'Tab' } 'M' { 'Enter' } 'J' { 'Enter' } '[' { 'Esc' } default { [string]$c } }
            if ($k.Length -eq 1) { $m += 'Ctrl'; $k = $k.ToUpperInvariant() }
            $out.Add((Join-KmChord $m $k))
        }
        elseif ($s[$i] -eq '\' -and $i + 1 -lt $s.Length) { $out.Add((Join-KmChord $m ([string]$s[$i + 1]))); $i += 2 }
        else { $c = [string]$s[$i]; $i++; if ($c -cmatch '[A-Z]') { $m += 'Shift' }; $out.Add((Join-KmChord $m $c.ToUpperInvariant())) }
    }
    return ($out -join ', ')
}

function Invoke-KmWsl {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { Write-Host '  wsl: not installed'; return }
    $n = 0
    $tmuxCmd = 'command -v tmux >/dev/null 2>&1 || exit 0; tmux list-keys 2>/dev/null || tmux -L tskeymap -f "$HOME/.tmux.conf" new-session -d \; list-keys \; kill-server 2>/dev/null'
    $text = Invoke-KmCapture 'wsl.exe' @('-e', 'sh', '-c', $tmuxCmd)
    $prefix = 'C-b'
    if ($text -match '(?m)^bind-key\s+(?:-\w+\s+)*-T\s+root\s+(\S+)\s+send-prefix') { $null = $Matches }
    $pfx = Invoke-KmCapture 'wsl.exe' @('-e', 'sh', '-c', 'tmux show-options -gv prefix 2>/dev/null || tmux -L tskeymap -f "$HOME/.tmux.conf" new-session -d \; show-options -gv prefix \; kill-server 2>/dev/null')
    if ($pfx.Trim()) { $prefix = ($pfx.Trim() -split "`n")[0].Trim() }
    $prefixChord = ConvertFrom-KmTmuxKey $prefix
    if ($text) { Add-KmRow -Chord_ $prefixChord -Scope 'Terminal' -App 'tmux (WSL)' -Context 'prefix' -Action 'tmux prefix key' -Owner 'tmux' -Source 'wsl' -Path '~/.tmux.conf' }
    foreach ($line in ($text -split "`r?`n")) {
        if ($line -notmatch '^bind-key\s+(?<flags>(?:-[rn]\s+|-N\s+"[^"]*"\s+)*)-T\s+(?<t>\S+)\s+(?<k>\S+)\s+(?<a>.+)$') { continue }
        $t = $Matches['t']; $k = ConvertFrom-KmTmuxKey $Matches['k']; $a = $Matches['a'].Trim()
        $cc = switch ($t) { 'prefix' { "$prefixChord, $k" } 'root' { $k } default { $k } }
        $n++
        Add-KmRow -Chord_ $cc -Scope 'Terminal' -App 'tmux (WSL)' -Context "table $t" -Action $a -Owner 'tmux' -Source 'wsl' -Path '~/.tmux.conf'
    }
    $z = Invoke-KmCapture 'wsl.exe' @('-e', 'sh', '-c', 'command -v zsh >/dev/null 2>&1 && zsh -ic "bindkey -L" 2>/dev/null </dev/null')
    foreach ($line in ($z -split "`r?`n")) {
        if ($line -notmatch '^bindkey\s+(?:-M\s+\S+\s+|-R\s+)*(".*?"|\S+)\s+(\S+)\s*$') { continue }
        $seq = $Matches[1]; $w = $Matches[2]
        if ($w -in 'self-insert', 'undefined-key') { continue }
        $cc = ConvertFrom-KmZshKey $seq
        if (-not $cc) { continue }
        $n++
        Add-KmRow -Chord_ $cc -Scope 'Shell' -App 'zsh (WSL)' -Context 'main keymap' -Action $w -Owner 'zsh' -Source 'wsl' -Path '~/.zshrc' -Notes "raw $seq"
    }
    Write-Host "  wsl: $n"
}

function Invoke-KmDeepScan {
    $roots = @($env:APPDATA, $env:LOCALAPPDATA) | Where-Object { $_ }
    $skipDirs = '(?i)\\(Google|Microsoft\\Edge|Mozilla|BraveSoftware|Opera Software|Vivaldi|node_modules|Cache|Caches|Code Cache|GPUCache|CrashDumps|Temp|npm-cache|uv|pip|Packages|Microsoft\\Windows|Microsoft\\PowerToys|Code|Cursor|Windsurf|Zed|herdr-app|terminal-stack|Docker|JetBrains\\.*\\(caches|index)|\.git)(\\|$)'
    $nameRx = '(?i)hot.?key|short.?cut|key.?bind|accelerator|global.?key|activation.?key|trigger.?key'
    $n = 0
    foreach ($r in $roots) {
        $files = Get-ChildItem -LiteralPath $r -Recurse -Depth 4 -File -Include *.json, *.ini, *.cfg, *.config, *.xml, *.toml, *.yaml, *.yml -ErrorAction SilentlyContinue |
            Where-Object { $_.Length -lt 512KB -and $_.FullName -notmatch $skipDirs }
        foreach ($f in $files) {
            $app = ($f.FullName.Substring($r.Length).TrimStart('\') -split '\\')[0]
            $text = try { [System.IO.File]::ReadAllText($f.FullName) } catch { continue }
            if ($text -notmatch $nameRx) { continue }
            $hits = [regex]::Matches($text, '(?im)["<]?(?<n>[\w.\- ]*(?:hot.?key|short.?cut|key.?bind|accelerator|activation.?key)[\w.\- ]*)["]?\s*(?:[:=]|>)\s*"?(?<v>[^"\r\n<,}]{1,60})')
            foreach ($h in $hits) {
                $cc = ConvertTo-KmChord $h.Groups['v'].Value.Trim()
                if (-not $cc -or $cc -notmatch '\+') { continue }
                $n++
                Add-KmRow -Chord_ $cc -Scope 'Global hotkey (setting)' -App $app -Action $h.Groups['n'].Value.Trim() -Source 'deepscan' -Path $f.FullName -Notes 'a hotkey-like setting; the app may or may not register it'
            }
        }
    }
    Write-Host "  deepscan: $n"
}

# --------------------------------------------------------------------------- identify owners
function Resolve-KmHookDll {
    if ($HookDll) { if (Test-Path -LiteralPath $HookDll) { return (Resolve-Path -LiteralPath $HookDll).Path }; throw "No hook DLL at $HookDll" }
    $src = Join-Path $PSScriptRoot 'hkspy'
    if (-not (Test-Path -LiteralPath (Join-Path $src 'Cargo.toml'))) { throw "The hook source is missing: $src" }
    $hash = (Get-FileHash -Algorithm SHA256 -InputStream ([System.IO.MemoryStream]::new([System.Text.Encoding]::UTF8.GetBytes(
                    ((Get-Content -Raw -LiteralPath (Join-Path $src 'src\lib.rs')) + (Get-Content -Raw -LiteralPath (Join-Path $src 'Cargo.toml'))))))).Hash.Substring(0, 12)
    $cache = Join-Path $env:LOCALAPPDATA 'keymap'
    $dll = Join-Path $cache "hkspy-$hash.dll"
    if (Test-Path -LiteralPath $dll) { return $dll }
    $cargo = Get-Command cargo -ErrorAction SilentlyContinue
    if (-not $cargo) {
        throw "Naming owners needs a small hook DLL, built once with Rust. Install Rust (winget install Rustlang.Rustup), or pass -HookDll <path>. Without -Identify everything else still works."
    }
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    Write-Host "  building the hook DLL once (cargo) ..."
    $target = Join-Path $cache 'target'
    $log = & $cargo.Source build --release --quiet --manifest-path (Join-Path $src 'Cargo.toml') --target-dir $target 2>&1
    $built = Join-Path $target 'release\hkspy.dll'
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $built)) { throw "cargo build failed:`n$($log -join "`n")" }
    Copy-Item -LiteralPath $built -Destination $dll -Force
    return $dll
}

function Invoke-KmIdentify {
    param([object[]]$Targets)
    $deny = @('Win+L', 'Ctrl+Alt+Delete', 'Ctrl+Shift+Esc', 'Ctrl+Shift+Win+B')
    $press = @(); $skipped = @()
    foreach ($t in $Targets) {
        $v = ConvertTo-KmVk $t.Chord
        if (-not $v -or $deny -contains $t.Chord -or ($v.Mods -band 15) -eq 15) { $skipped += $t; continue }
        $press += [pscustomobject]@{ Row = $t; Mods = $v.Mods; Vk = $v.Vk }
    }
    foreach ($s in $skipped) { $s.Notes = ($s.Notes + '; not pressed (system chord)').Trim('; ') }
    if (-not $press) { return }

    $elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    Write-Host ''
    Write-Host "Naming owners: $($press.Count) global hotkeys will each be pressed once." -ForegroundColor Cyan
    Write-Host '  A hook swallows each press, so the owning program does not act on it.'
    if (-not $elevated) { Write-Host '  Exception: an owner running as administrator (this is not) is not intercepted, and its action runs.' -ForegroundColor Yellow }
    Write-Host '  32-bit owners are not intercepted either. Do not type until it finishes (a few seconds).'
    if (-not $Force) {
        if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) { Write-Warning 'Not pressing anything: add -Force to allow it without a prompt.'; return }
        $ans = Read-Host 'Press them now? [y/N]'
        if ($ans -notmatch '^(?i)y') { Write-Host '  skipped.'; return }
    }

    $dll = Resolve-KmHookDll
    $log = Join-Path ([System.IO.Path]::GetTempPath()) "keymap-hook-$PID.log"
    Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue
    $map = [System.IO.MemoryMappedFiles.MemoryMappedFile]::CreateNew('Local\hkspy-config', 4096)
    $hook = [IntPtr]::Zero
    try {
        $view = $map.CreateViewAccessor()
        $view.Write(0, [uint32]0x5950534B); $view.Write(4, [uint32]1)
        $bytes = [System.Text.Encoding]::Unicode.GetBytes($log + [char]0)
        $view.WriteArray(8, $bytes, 0, $bytes.Length)
        $view.Dispose()

        $h = [KmNative]::LoadLibraryW($dll)
        if ($h -eq [IntPtr]::Zero) { throw "LoadLibrary failed for $dll" }
        $proc = [KmNative]::GetProcAddress($h, 'hook_proc')
        $hook = [KmNative]::SetWindowsHookExW(3, $proc, $h, 0)
        if ($hook -eq [IntPtr]::Zero) { throw 'SetWindowsHookEx failed' }

        $wait = 0
        while ([KmNative]::ModifierHeld() -and $wait -lt 50) { Start-Sleep -Milliseconds 100; $wait++ }
        [KmNative]::Pump(400)
        $blocked = 0
        foreach ($p in $press) {
            if ([KmNative]::Press([uint32]$p.Mods, [uint16]$p.Vk) -eq 0) { $blocked++ }
            [KmNative]::Pump(180)
        }
        [KmNative]::Pump(900)
        if ($blocked) { Write-Warning "$blocked presses were refused: an elevated window has focus. Focus a normal window, or run this elevated." }
    }
    finally {
        if ($hook -ne [IntPtr]::Zero) { [void][KmNative]::UnhookWindowsHookEx($hook) }
        $map.Dispose()
    }

    $hits = @{}
    if (Test-Path -LiteralPath $log) {
        foreach ($line in Get-Content -LiteralPath $log -Encoding utf8) {
            $f = $line -split "`t"
            if ($f.Count -lt 9) { continue }
            $hits["$([int]$f[4])/$([int]$f[5])"] = [pscustomobject]@{ Pid = $f[0]; Class = $f[6]; Title = $f[7]; Exe = $f[8] }
        }
        Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue
    }
    $named = 0
    foreach ($p in $press) {
        $hit = $hits["$($p.Mods)/$($p.Vk)"]
        if ($hit) {
            $named++
            $leaf = Split-Path -Leaf $hit.Exe
            $p.Row.Owner = $leaf; $p.Row.OwnerPid = $hit.Pid; $p.Row.Path = $hit.Exe
            $p.Row.App = Get-KmAppName $hit.Exe
            $p.Row.Notes = "named by hook; window class '$($hit.Class)'" + $(if ($hit.Title) { ", title '$($hit.Title)'" } else { '' })
        }
        else {
            $p.Row.App = '(not identified)'
            $p.Row.Notes = 'pressed, but no WM_HOTKEY reached the hook: the owner is elevated, 32-bit, or not a window message handler'
        }
    }
    Write-Host "  identify: named $named of $($press.Count)"
}

function Get-KmAppName {
    param([string]$Exe)
    try {
        $vi = (Get-Item -LiteralPath $Exe -ErrorAction Stop).VersionInfo
        foreach ($s in $vi.FileDescription, $vi.ProductName) { if ($s -and $s.Trim()) { return $s.Trim() } }
    }
    catch { $null = $_ }
    return [System.IO.Path]::GetFileNameWithoutExtension($Exe)
}

# --------------------------------------------------------------------------- conflicts
function Test-KmSameOwner {
    param([string]$GlobalOwner, [string]$AppOwner)
    if (-not $GlobalOwner -or -not $AppOwner) { return $false }
    $g = [System.IO.Path]::GetFileNameWithoutExtension($GlobalOwner); $a = [System.IO.Path]::GetFileNameWithoutExtension($AppOwner)
    return ($g -like "$a*" -or $a -like "$g*")
}

function Set-KmConflict {
    $globals = @{}
    foreach ($r in $script:Rows) { if ($r.Source -eq 'probe') { $globals[$r.Chord] = $r } }
    $declared = @{}
    foreach ($r in $script:Rows) { if ($r.Scope -like 'Global*' -or $r.Scope -eq 'Windows built-in') { if (-not $declared.ContainsKey($r.Chord)) { $declared[$r.Chord] = [System.Collections.Generic.List[object]]::new() }; $declared[$r.Chord].Add($r) } }

    # A probed chord with no named owner borrows one from a collector that declares it.
    foreach ($g in $globals.Values) {
        if ($g.Owner) { continue }
        $decl = if ($declared.ContainsKey($g.Chord)) { @($declared[$g.Chord] | Where-Object { $_.Source -ne 'probe' }) } else { @() }
        $pick = @($decl | Where-Object { $_.Source -ne 'windows' } | Select-Object -First 1)
        if (-not $pick) { $pick = @($decl | Select-Object -First 1) }
        if ($pick) {
            $g.App = "$($pick[0].App) (inferred)"; $g.Action = $pick[0].Action; $g.Owner = $pick[0].Owner
            $g.Notes = "owner inferred from $($pick[0].Source); -Identify confirms it"
        }
    }

    foreach ($r in $script:Rows) {
        if ($r.Source -eq 'probe' -or $r.Chord.Contains(', ') -or $r.Chord -like 'Leader+*') { continue }
        if (-not $globals.ContainsKey($r.Chord)) { continue }
        $g = $globals[$r.Chord]
        if ($r.Scope -like 'Global*' -or $r.Scope -eq 'Windows built-in') {
            if ($r.Notes -match 'OFF') { continue }
            if ($g.Owner -and $r.Owner -and -not (Test-KmSameOwner $g.Owner $r.Owner) -and $g.Notes -like 'named by hook*') {
                $r.Conflict = "Declared here, but $($g.App) ($($g.Owner)) holds it"
            }
            continue
        }
        if (Test-KmSameOwner $g.Owner $r.Owner) { continue }
        $who = if ($g.Owner) { "$($g.App) ($($g.Owner))" } else { 'another program (run with -Identify to name it)' }
        $r.Conflict = "Never reaches $($r.App): held system-wide by $who"
        $line = "swallows $($r.App)" + $(if ($r.Action) { ": $($r.Action)" } else { '' })
        $g.Conflict = (@($g.Conflict, $line) | Where-Object { $_ }) -join ' | '
    }

    # Same chord bound to two different actions in one app and context.
    $groups = $script:Rows | Where-Object { $_.Scope -in 'App', 'Shell', 'Terminal' } | Group-Object App, Context, Chord | Where-Object { $_.Count -gt 1 }
    foreach ($grp in $groups) {
        $acts = @($grp.Group.Action | Select-Object -Unique)
        if ($acts.Count -lt 2) { continue }
        foreach ($r in $grp.Group) {
            $others = ($acts | Where-Object { $_ -ne $r.Action }) -join '; '
            $r.Conflict = (@($r.Conflict, "bound twice here; also: $others") | Where-Object { $_ }) -join ' | '
        }
    }
}

# --------------------------------------------------------------------------- run
$want = [System.Collections.Generic.List[string]]::new()
foreach ($c in $Collect) { foreach ($x in ($c -split ',')) { $x = $x.Trim().ToLowerInvariant(); if ($x) { $want.Add($x) } } }
if ($want -contains 'all') { $want.Clear(); foreach ($k in $script:AllCollectors.Keys) { if ($k -ne 'deepscan') { $want.Add($k) } } }
if ($DeepScan -and -not $want.Contains('deepscan')) { $want.Add('deepscan') }
$drop = @($Skip | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim().ToLowerInvariant() } | Where-Object { $_ })
foreach ($x in @($want)) {
    if (-not $script:AllCollectors.Contains($x)) { throw "Unknown collector '$x'. Known: $($script:AllCollectors.Keys -join ', ')" }
    if ($drop -contains $x) { [void]$want.Remove($x) }
}
$script:ProbeBareAll = [bool]$ProbeAllBare

$filter = @()
foreach ($c in @($Chord)) {
    # `pwsh -File` hands a list over as one comma-joined string; a comma that ends
    # a chord ("ctrl+,") is a key, so split only before a letter.
    foreach ($x in ($c -split ';|,(?=\s*[A-Za-z])')) { if ($x.Trim()) { $cc = ConvertTo-KmChord $x; if (-not $cc) { throw "Not a chord: '$x'" }; $filter += $cc } }
}

$interactiveDefault = $PSBoundParameters.Count -eq 0 -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected
$started = Get-Date
Write-Host "keymap: collecting ($($want -join ', '))" -ForegroundColor Cyan
$dispatch = @{
    probe = { Invoke-KmProbe }; windows = { Invoke-KmWindows }; shelllinks = { Invoke-KmShellLinks }
    powertoys = { Invoke-KmPowerToys }; wezterm = { Invoke-KmWezTerm }; windowsterminal = { Invoke-KmWindowsTerminal }
    editors = { Invoke-KmEditors }; herdr = { Invoke-KmHerdr }; claude = { Invoke-KmClaude }
    psreadline = { Invoke-KmPSReadLine }; autohotkey = { Invoke-KmAutoHotkey }; wsl = { Invoke-KmWsl }; deepscan = { Invoke-KmDeepScan }
}
foreach ($x in $want) {
    try { & $dispatch[$x] }
    catch { Write-Warning "$x failed: $($_.Exception.Message)" }
}

$probed = @($script:Rows | Where-Object Source -EQ 'probe')
if ($filter) { $probed = @($probed | Where-Object { $filter -contains $_.Chord }) }
$doIdentify = $Identify
if (-not $doIdentify -and $interactiveDefault -and $probed.Count) {
    $ans = Read-Host "Name the programs behind $($probed.Count) global hotkeys? Each is pressed once and swallowed [y/N]"
    if ($ans -match '^(?i)y') { $doIdentify = $true; $Force = $true }
}
if ($doIdentify -and $probed.Count) { Invoke-KmIdentify $probed }
elseif ($doIdentify) { Write-Host '  identify: nothing to name (no matching global hotkeys are held)' }

Set-KmConflict

$out = @($script:Rows)
if ($filter) { $out = @($out | Where-Object { $filter -contains $_.Chord -or ($_.Chord -split ', ' | Where-Object { $filter -contains $_ }) }) }
if ($ConflictsOnly) { $out = @($out | Where-Object Conflict) }
$out = @($out | Sort-Object @{ e = { switch -Wildcard ($_.Scope) { 'Global*' { 0 } 'Windows*' { 1 } default { 2 } } } }, App, Context, Chord)

if (-not $OutFile) {
    $folder = (Get-Location).Path
    if ($folder -eq $PSScriptRoot -or $folder -like "$env:WINDIR*") { $folder = [Environment]::GetFolderPath('Desktop') }
    $OutFile = Join-Path $folder ("keymap-{0}-{1:yyyyMMdd-HHmm}.csv" -f $env:COMPUTERNAME, (Get-Date))
}
$parent = Split-Path -Parent ([System.IO.Path]::GetFullPath($OutFile))
if ($parent -and -not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$out | Export-Csv -LiteralPath $OutFile -NoTypeInformation -Encoding utf8

$conflicts = @($out | Where-Object Conflict)
Write-Host ''
Write-Host ("{0} shortcuts written to {1}  ({2:n1}s)" -f $out.Count, (Resolve-Path -LiteralPath $OutFile).Path, ((Get-Date) - $started).TotalSeconds) -ForegroundColor Green
$out | Group-Object Source | Sort-Object Name | ForEach-Object { Write-Host ('  {0,-16} {1}' -f $_.Name, $_.Count) }
if ($conflicts) {
    Write-Host ''
    Write-Host "$($conflicts.Count) conflicts:" -ForegroundColor Yellow
    foreach ($r in ($conflicts | Where-Object Source -NE 'probe' | Select-Object -First 25)) {
        Write-Host ('  {0,-22} {1,-24} {2}' -f $r.Chord, $r.App, $r.Conflict)
    }
}
$unknown = @($out | Where-Object { $_.Source -eq 'probe' -and -not $_.Owner })
if ($unknown -and -not $doIdentify) { Write-Host ''; Write-Host "$($unknown.Count) global hotkeys have no named owner. Run again with -Identify to name them." }
if ($PassThru) { $out }
