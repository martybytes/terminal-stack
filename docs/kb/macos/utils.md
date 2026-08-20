# macOS — utilities

Terminal utilities that only exist on a Mac. The stack's cross-platform
`clipcopy` / `catclip` helpers resolve to `pbcopy` here, so clipboard muscle
memory from Linux/Windows keeps working — see `doc common/clipboard`.

| Command | What it does |
|---|---|
| `cmd \| pbcopy` | pipe command output to the clipboard |
| `pbpaste` | clipboard to stdout — `pbpaste \| jq .` etc. |
| `open .` | current directory in Finder |
| `open -a "App" file` | open a file with a specific app |
| `open https://example.com` | URL in the default browser |
| `mdfind query` | Spotlight search from the CLI (`-name file.txt` for filenames) |
| `caffeinate -i cmd` | keep the Mac awake while a command runs |
| `ditto src dst` | copy preserving metadata/resource forks (what Finder uses) |
| `xattr -d com.apple.quarantine app` | clear the "downloaded from the internet" gate |

## defaults — read/write hidden settings

```bash
defaults read com.apple.finder                    # dump a whole domain
defaults read com.apple.finder AppleShowAllFiles  # one key
defaults write com.apple.finder AppleShowAllFiles -bool true
killall Finder                                    # most changes need an app restart
```

Deleting a key restores the default: `defaults delete <domain> <key>`.
