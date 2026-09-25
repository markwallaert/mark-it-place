# mark-it-place

Public marketplace of curated, released Claude Code plugins. Each plugin is developed in
its own private source repo; this repo holds release snapshots only.

## Releasing a plugin

- Snapshot from a committed source SHA, never from the working tree and never with history:
  `git -C <source-repo> archive <sha> <allowlist…> | tar -x -C plugins/<name>`
- Allowlist runtime files only: `.claude-plugin/plugin.json`, the skills/commands/agents/hooks
  the plugin loads, their scripts, `README.md`, `LICENSE`. Dev material (`.claude/`,
  `CLAUDE.md`, `docs/`, `examples/`, tests, changelogs) stays in the source repo.
- Fixes go in the source repo first, then re-snapshot. Never edit `plugins/<name>/` directly.
- Bump `version` in the plugin's `plugin.json` only, not in the marketplace entry. Users
  receive an update only when it changes.
- Add or update the plugin's entry in `.claude-plugin/marketplace.json` and the table in
  `README.md`.
- Commit message: `<plugin> <version> (from <plugin>@<source-sha>)`.

## Leak scan (before every release commit)

Scan the snapshot for:
- hostnames, IPs, internal service names, home-directory paths
- the author's own project and repo names — examples and sample output leak real project
  names that match no host or path pattern
- references to files outside the allowlist (they won't exist for users)

Then run `claude plugin validate .` and test an install under a throwaway `CLAUDE_CONFIG_DIR`.

Pushes are human-directed. A local commit here is one push from public.
