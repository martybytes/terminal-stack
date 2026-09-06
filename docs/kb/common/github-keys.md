# GitHub — generate an SSH key and add it

## 1. Generate (ed25519)

```bash
ssh-keygen -t ed25519 -C "you@host-$(date +%Y%m%d)" -f ~/.ssh/id_github
# -C is a label only; -f sets the filename. Add a passphrase when prompted.
```

## 2. Load into the agent (optional)

```bash
eval "$(ssh-agent -s)"          # macOS / Linux / WSL only
ssh-add ~/.ssh/id_github
```

**On Windows pwsh, skip the `eval`** — the agent is a Windows service on a named
pipe, and starting a second one there breaks the first. Just `ssh-add`:

```powershell
Get-Service ssh-agent           # Running? then:
ssh-add $HOME\.ssh\id_github
```

If that says `Error connecting to agent`, the agent is almost certainly fine and
`SSH_AUTH_SOCK` is pointing somewhere wrong: `doc troubleshooting`.

## 3. Copy the PUBLIC key

```bash
cat ~/.ssh/id_github.pub          # then copy the output
# Linux w/ clipboard: xclip -sel clip < ~/.ssh/id_github.pub
# macOS:               pbcopy      < ~/.ssh/id_github.pub
# WSL:                 clip.exe    < ~/.ssh/id_github.pub
```

## 4. Add it on GitHub

GitHub → Settings → **SSH and GPG keys** → **New SSH key** → paste the `.pub`.
Or with the GitHub CLI:

```bash
gh ssh-key add ~/.ssh/id_github.pub --title "host $(date +%Y-%m-%d)"
```

## 5. Point git at the key (per ~/.ssh/config)

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
    IdentityFile ~/.ssh/id_github
    IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
```

## 6. Test

```bash
ssh -T git@github.com            # expect: "Hi <user>! You've successfully authenticated"
```
