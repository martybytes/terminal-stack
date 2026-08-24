# terminal-stack agent rules

- Implement changes only in a workspace development clone of this repository.
- Never edit the installed runtime clone (`~/.local/share/terminal-stack` or
  `%LOCALAPPDATA%\terminal-stack\stack`) directly.
- Never deploy uncommitted runtime-clone contents with `chezmoi apply` or
  `scripts/sync-windows.ps1`.
- Validate in the development clone, commit and push the change, then use
  `ts-update` to bring the clean commit into the runtime clone and deploy it.
- Every completed turn that changes repository behavior must update the relevant
  user documentation and `doc` knowledge-base topic, run appropriate validation,
  commit all in-scope changes, and push the current branch so the user can test
  with `ts-update`. Do not leave completed implementation only in the development
  clone unless the user explicitly says not to commit or push.
- Do not use `chezmoi re-add` on templated terminal-stack targets; it can replace
  template directives with machine-rendered content.
