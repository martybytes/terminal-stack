# terminal-stack agent rules

- Implement changes only in a workspace development clone of this repository.
- Never edit the installed runtime clone (`~/.local/share/terminal-stack` or
  `%LOCALAPPDATA%\terminal-stack\stack`) directly.
- Never deploy uncommitted runtime-clone contents with `chezmoi apply` or
  `scripts/sync-windows.ps1`.
- Validate in the development clone, commit and push the change, then use
  `ts-update` to bring the clean commit into the runtime clone and deploy it.
- Do not use `chezmoi re-add` on templated terminal-stack targets; it can replace
  template directives with machine-rendered content.
