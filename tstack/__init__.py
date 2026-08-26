"""tstack - the terminal-stack management program.

One implementation, every platform. This package replaces the parallel bash and
PowerShell trees under bootstrap/ that were kept in agreement by hand and by a
manual pty diff (docs/verifying-changes.md section 3).

Entry point is tstack/main.py, invoked by the shell shims in dot_zshrc and
$PROFILE. Nothing here is deployed to $HOME: tstack/** is in .chezmoiignore, and
the shims run it from the clone.

The port is incremental. tstack/registry.py records which subcommands have moved
here and which still route to the shell implementation; see REVAMP-PLAN.md.
"""

__all__ = ["__version__"]

# Not a release version. The stack updates by `git pull`, so the clone's HEAD is
# the only version that means anything -- see tstack.paths.clone_version().
__version__ = "0.1.0"
