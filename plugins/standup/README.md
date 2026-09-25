# standup

A Claude Code plugin that synthesizes daily standup markdown from your Claude Code transcripts. Default is a cross-project unified entry per day; opt into per-project mode with `--project`.

## Install

Requires Python 3.9+ (`python3` on `PATH`; standard library only).

From the [mark-it-place](https://github.com/markwallaert/mark-it-place) marketplace, in a Claude Code session:

```
/plugin marketplace add markwallaert/mark-it-place
/plugin install standup@mark-it-place
```

Or load locally:

```bash
claude --plugin-dir /path/to/standup
```

## Usage

```
/standup:standup                          # Catch up: fill any gap days in unified up to yesterday
/standup:standup 2026-04-29               # One specific day (unified)
/standup:standup 2026-04-15..2026-04-29   # A date range (unified; end clamped to yesterday)
/standup:standup --force 2026-04-29       # Overwrite an existing entry
/standup:standup --force                  # Overwrite yesterday's entry
```

The `<plugin>:<skill>` form is required — Claude Code namespaces all plugin skills, so the bare `/standup` will not register.

By default, today is always skipped (partial-day problem). Pass today's date explicitly with `--force` to include it.

## Per-project mode

Use `--project` to scope to the current working directory only — one file per day per project, instead of the default cross-project unified entry.

```
/standup:standup --project                          # Catch up this project's entries
/standup:standup --project 2026-04-29               # One day, this project only
/standup:standup --project 2026-04-15..2026-04-29   # Range, this project only
/standup:standup --project --force 2026-04-29       # Overwrite
```

Flag order is free: `--project` and the date arg can come in either order.

## Output

```
~/Documents/standup/<YYYY-MM-DD>.md            # default (unified)
~/Documents/standup/<project>/<YYYY-MM-DD>.md  # --project mode
```

`<project>` is the basename of your current working directory. Different cwd basenames are different projects. Unified entries are dated files at the base; project entries are directories beside them, so the two never collide.

## Configuration

Override the output base directory by creating `./.claude/standup.local.md` in any project (or `~/.claude/standup.local.md` for a global default):

```markdown
---
output_dir: /Users/me/Documents/work-standup
---
```

`output_dir` is the *base* — unified entries are written into it directly; `--project` mode appends a `<project>/` subdirectory.

## What's in each entry

- **Focus** — one paragraph framing the day
- **Threads** — substantive bullets per topic, capturing decisions and reframes (not file lists). Default mode groups them under a heading per project, plus a `cross-project` section when threads genuinely span several.
- **Obstacles & considerations** — only when there's real material
- **Activity** — projects touched, session count, commits, volume. Commits cover every repo worked in that day, including repos edited from another project's session, with the per-repo split shown.

## How it works

`bucket.py` walks Claude Code transcripts and emits a clean text bundle for a target date — either across all projects (default) or scoped to one (`--project`). The skill body synthesizes that bundle into standup markdown. The catch-up scan reads the relevant output directory and fills any gap up to yesterday.

Subagent transcripts are intentionally *not* included — the parent transcript already has the dispatch and result, and including subagent internals would balloon volume without adding signal.

## Limitations

- Output is markdown only.
- DST transition days have a one-day off-by-one boundary (accepted).
