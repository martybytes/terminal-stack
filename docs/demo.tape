# docs/demo.tape — the README's terminal demo, recorded with Charm VHS.
#
#   brew install vhs ttyd ffmpeg     # or: https://github.com/charmbracelet/vhs
#   vhs docs/demo.tape               # writes docs/demo.gif
#
# Keep it SHORT and keep it REAL. Every command here is one a new user actually
# runs, in the order they meet them, and all four are read-only: `--help` and
# `--version` print, `doctor` diagnoses without repairing, and `lsr` lists. A
# demo that mutates the recording machine is one nobody re-records.
#
# Re-record after any change to `tstack --help`, which is rendered from
# tstack/commands.conf and so changes whenever the command surface does.

Output docs/demo.gif

Set Shell zsh
Set FontFamily "JetBrainsMono Nerd Font"
Set FontSize 18
Set Width 1100
Set Height 680
Set Padding 22
Set Theme "Catppuccin Mocha"
Set TypingSpeed 55ms
Set PlaybackSpeed 1.0

# VHS starts a NON-LOGIN shell, which never sources ~/.zshrc -- and `tstack` is a
# zsh function defined there, not a binary on PATH. Without this the whole
# recording is `zsh: command not found: tstack`. Sourcing it here is what makes
# the demo show the same shell a user actually gets.
Hide
Type "source ~/.zshrc >/dev/null 2>&1" Enter
Type "clear" Enter
Show

Sleep 600ms

# One command fronts the whole stack.
Type "tstack" Sleep 400ms Enter
Sleep 3s

Type "clear" Enter
Sleep 300ms

# Where am I installed, and on what commit?
Type "tstack --version" Sleep 400ms Enter
Sleep 2500ms

Type "clear" Enter
Sleep 300ms

# The health check every install path runs for you.
Type "tstack doctor" Sleep 400ms Enter
Sleep 4s

Type "clear" Enter
Sleep 300ms

# A small quality-of-life example: directories by most recent activity.
Type "lsr" Sleep 400ms Enter
Sleep 3s
