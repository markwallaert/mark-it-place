---
name: standup
description: Synthesize one or more daily standup markdown entries from Claude Code transcripts. Default is a cross-project unified entry per day; pass --project for a single-project entry scoped to the current cwd. Use when the user invokes /standup:standup, asks "fill in my standup," asks to "catch up the journal," or asks for a daily work summary.
---

# standup

Synthesize daily standup markdown from Claude Code transcripts.

- **Default (unified)**: one cross-project file per day at `<output-dir>/<YYYY-MM-DD>.md`.
- **`--project` mode**: one file per day per project at `<output-dir>/<project>/<YYYY-MM-DD>.md`, scoped to the current cwd.

Default output base: `~/Documents/standup/`.

## Algorithm (default — unified)

1. **Resolve `<base-output-dir>`** in priority order:
   1. `./.claude/standup.local.md` frontmatter `output_dir:` field (project-local override)
   2. `~/.claude/standup.local.md` frontmatter `output_dir:` field (home-level override)
   3. Default `~/Documents/standup/`
   - On any malformed frontmatter, log a warning naming the bad file and skip *that tier only* — continue resolution. Never abort.
2. Compute `<output-dir>` = `<base-output-dir>` itself — unified entries live at the base, not in a subdirectory. Ensure it exists. Per-project subdirectories (`--project` mode) sit alongside the dated files; the catch-up scan only matches `YYYY-MM-DD.md` files and ignores directories, so the two coexist.
3. **Check `~/.claude/projects/` exists.** If not, abort with `standup: no Claude Code transcripts found at ~/.claude/projects/`.
4. **Determine target dates from `$ARGUMENTS`:**
   - No args → run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/standup/bucket.py --catch-up <output-dir>`. Each line of stdout is a target date.
   - `--force` with no date → `[yesterday]` with overwrite enabled.
   - Single `YYYY-MM-DD` → `[that date]`.
   - Range `YYYY-MM-DD..YYYY-MM-DD` → `[start..min(end, yesterday)]`. If `start > yesterday`, list is empty.
   - `--force YYYY-MM-DD` → `[that date]` with overwrite enabled.
   - `yesterday` is today minus one day in user-local time.
5. **For each target date in chronological order:**
   1. Check `<output-dir>/<date>.md` — if it exists and `--force` is not set, log `<date>: already exists, skipped`. Continue.
   2. Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/standup/bucket.py --all-projects --date <date>`. Capture stdout.
   3. If stdout is empty, log `<date>: no transcripts, skipped`. Continue.
   4. Synthesize the unified markdown for `<date>` from the bundle, following the structure and voice rules below.
   5. Write to `<output-dir>/<date>.md`. On write failure, log `<date>: write failed`, abort that date, continue with others.
6. **Print summary report** (see format below).

If synthesis itself fails for a date (LLM error, malformed output), treat the same as a write failure: log, abort that date, continue.

Sequential. In main context. No subagent dispatch.

## `--project` mode

If `$ARGUMENTS` contains the token `--project` (in any position), strip it and run the algorithm below instead of the default flow.

1. **Resolve project name:** `Path.cwd().name` (use as-is; do NOT resolve symlinks). No project name is reserved — unified entries are files at the base dir and project entries are directories beside them, so the two namespaces cannot collide.
2. **Resolve `<base-output-dir>`** using the same chain as default mode.
3. Compute `<project-output-dir>` = `<base-output-dir>/<project>/`. Ensure it exists.
4. Compute `<encoded-cwd>` = absolute cwd with `/` → `-` (e.g., `/home/alice/projects/myapp` → `-home-alice-projects-myapp`). If the corresponding Claude Code transcripts directory does not exist, abort with: `standup: no Claude Code transcripts found for project <project> at <expected-path>`.
5. **Determine target dates** from the remaining args (`--project` already stripped) — same grammar as default mode (no args = catch-up, single date, range, `--force`).
   - For catch-up, scan `<project-output-dir>` instead of the base dir.
6. **For each target date in chronological order:**
   1. Check `<project-output-dir>/<date>.md` — if it exists and `--force` is not set, log skip. Continue.
   2. Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/standup/bucket.py --date <date> --project=<encoded-cwd>`. The `=` form is required: encoded-cwd values start with `-` and would be parsed as a flag with the space-separated form. Capture stdout.
   3. If stdout is empty, log skip. Continue.
   4. Synthesize the project markdown for `<date>` from the bundle, following the project output structure below.
   5. Write to `<project-output-dir>/<date>.md`. On write failure, log skip, continue.
7. **Print summary report**, with `Output dir: <project-output-dir>`.

Flag order is free: `/standup:standup --project <date>` and `/standup:standup <date> --project` are both valid.

## Bundle structure (default — unified)

```
## project <decoded-name>
<!-- cwd: <decoded-cwd> -->

### session <session-id>

[user] ...
[assistant] ...

### session <session-id>
...

## project <next-decoded-name>
<!-- cwd: <next-decoded-cwd> -->
...
```

The `<!-- cwd: ... -->` annotation immediately follows each `## project` header. Read each project's cwd from this annotation (regex: under each `## project <name>` line, the next line matches `<!-- cwd: (.*) -->` exactly). An empty cwd value (`<!-- cwd: -->`) means "skip the Commits aggregation for this project."

## Output structure (default — unified)

```markdown
# YYYY-MM-DD (unified)

## Focus
<one paragraph framing the day across all projects>

## Threads

### <project>

- **<thread title>** — <substantive paragraph>
- ...

### <other project>

- ...

### <repo worked in from another project's session>
_Worked from inside the <name> sessions; no separate transcripts._

- ...

### cross-project

- **<thread title>** — <substantive paragraph spanning several projects>

## Obstacles & considerations
- <only when there's real material; omit section entirely otherwise>

## Activity
- Projects touched: <comma-separated list, alphabetical>
- Sessions: <total `### session` headers across the bundle>
- Commits: <aggregated commit summary — see below>
- Volume: ~<N> turns of dialog (sum of `[user]` + `[assistant]` lines)
```

**Thread grouping rules:**

- One `###` section per project, in bundle order. Drop the inline `— _<project>_ —` tag; the heading carries it.
- A repo that was worked in *from another project's session* (config repos, dotfiles, sibling repos edited in passing) gets its own `###` section with a one-line italic note saying where the work happened, so nobody reads the heading as a missing transcript. Only add such a section when the bundle actually evidences work there.
- `### cross-project` is for threads that genuinely span projects and would be distorted by filing under one. Omit the section when there are none — do not manufacture cross-project framing.
- Omit any section with no threads. A single-project day is a single section, not a skeleton of empty ones.

### Commits aggregation (default — unified)

Count **every repo worked in that day**, not just the ones that happen to be a session's cwd. Two sources feed the repo list:

1. **Bundle projects** — each `## project` header whose `<!-- cwd: ... -->` annotation is non-empty.
2. **Repos evidenced in the bundle text** — a repo worked in from another project's session (a config repo, a dotfiles repo, a sibling project edited in passing). Claude Code records a session under its cwd, so work landing in these repos has no transcript directory of its own and would otherwise vanish from the count while its threads get written up.

For source 2, the bar is **evidence, not inference**: the bundle must show work actually landing there — files edited under that path, commits in it discussed, "uncommitted in <repo>, yours to commit" and the like. A repo merely *mentioned* does not qualify. Resolve each to an absolute path and confirm it is a git repo before counting; if it isn't, drop it silently. Never guess a path — if the bundle doesn't pin one down, leave the repo out and let the threads carry it.

For each repo in the combined list, attempt:

```sh
git -C <decoded-cwd> log --shortstat \
  --author="$(git -C <decoded-cwd> config user.name)" \
  --branches --remotes \
  --since="<date> 00:00:00" --until="<date> 23:59:59"
```

- If `git -C <decoded-cwd> config user.name` returns empty, **skip that repo's commits silently** — do not pass `--author=` with empty value (an empty regex matches every commit and would over-attribute).
- If `<decoded-cwd>` doesn't exist on disk, or it isn't a git repo, **skip silently** as well.
- Projects with an empty cwd annotation are skipped without attempting the call.
- Deduplicate by resolved path: two bundle projects (or a bundle project and an evidenced repo) can point at the same repo. Count it once.
- `--branches --remotes` walks **all local branches plus already-fetched `origin/*`**, not just the checked-out HEAD — so commits on un-checked-out feature branches are counted. Use `--branches --remotes`, **never `--all`**: `--all` also walks `refs/stash` and counts stash internals as commits. The explicit `00:00:00`/`23:59:59` local-time bounds prevent near-midnight commits from bucketing into the adjacent day.
- This count is a **best-effort local view**. It can still undercount commits pushed from another machine whose refs this checkout has not fetched (standup never runs `git fetch` — it stays a pure reader). When summarizing, do not claim the count is exhaustive across machines; phrase it as the local tally. Do **not** append a decorative `(local view)` marker to the output line.

Aggregate the surviving results into a **single one-line** `Commits:` Activity bullet. Format: `Commits: N across M repos`, followed by an inline parenthetical giving the per-repo split once more than one repo carries commits — the split is what makes the total auditable. Examples:

- `Commits: 0`
- `Commits: 13 across 3 repos (webapp 7, api 4, dotfiles 2)`
- `Commits: 12 across 1 repo`

Never break into multiple lines or per-repo bullets.

**Projects touched** lists the same combined set — bundle projects plus evidenced repos — so the two Activity lines agree with each other.

## Output structure (`--project` mode)

```markdown
# YYYY-MM-DD

## Focus
<one paragraph framing the day — what the user was driving at, what shape it took>

## Threads
- **<thread title>** <substantive paragraph: decisions, reframes, pushbacks, what was nearly missed>
- ...

## Obstacles & considerations
- <only when there's real material; omit section entirely otherwise>
- ...

## Activity
- Projects touched: <comma-separated list, current project first>
- Sessions: <count of `### session` headers in the bundle>
- Commits: <N across N repos, terse one-line context if useful — see below>
- Volume: ~<N> turns of dialog (count `[user]` + `[assistant]` lines in the bundle)
```

Threads stay a **flat list** in this mode — the whole entry is one project, so the per-project headings of unified mode would be a skeleton around a single section. The one exception: if work landed in another repo from these sessions and carries real material, give it a `###` subsection under Threads with the same one-line note unified mode uses.

For the **Commits** field: run `git -C <cwd> log --shortstat --author="$(git -C <cwd> config user.name)" --branches --remotes --since="<date> 00:00:00" --until="<date> 23:59:59"` to get the user's commits in the current repo for the target date (all local branches + already-fetched `origin/*`, correctly date-bucketed; **never `--all`** — it would count `git stash` internals as commits). If empty, write `Commits: 0`. Otherwise summarize tersely (count + one-line context). Do NOT enumerate SHAs.

Extend the same count to **other repos this session evidenced work in** (a config repo edited from here, a sibling repo touched in passing), under the evidence bar and skip rules from the unified Commits section above. Same one-line format, with the per-repo split in parentheses once more than one repo carries commits.

For **Projects touched:** start with the current project, then the evidenced repos — the same set the Commits line counted. Don't fabricate.

## Voice rules

- **Substance = thinking, not inventory.** Capture *why* the user did something — decisions, reframes, pushbacks, considerations, what was nearly missed. Avoid filenames, SHAs, function names. The reader can `git log` for those.
- **Lists over tables.** The output gets pasted into trackers that don't render markdown well. Tables only when they're genuinely the right shape (rare).
- **Acceptable to name an artifact when it *is* the decision** — e.g., "dropped the `prompt_configurations` table" — the table name *is* the decision.
- **Thin days yield short entries.** No padding to hit a length. If a day has one real thread, the entry has one thread.
- **Slightly third-person observational tone.**
- **Default (unified) mode relaxes the length budget.** Multi-project days have more material; trimming substance to fit a single-project length is wrong. The "no padding" rule still applies — substance, not bulk.
- **Render encoded-cwd-verbatim project names as-is.** When `bucket.py` couldn't resolve a cwd or names collided, the `## project` header carries the encoded form (e.g., `-home-alice-projects-cool-app`). Don't invent a prettier name — the `/`→`-` encoding is irreversible.

## Summary report format

After processing all target dates, print to the user:

```
standup summary
- Wrote: <comma-separated dates>
- Skipped (no transcripts): <comma-separated dates>
- Skipped (already exists): <comma-separated dates>
- Skipped (write/synthesis failure): <comma-separated dates>
- Output dir: <output-dir or project-output-dir>
```

Omit any line that has no entries. Always include the Output dir line.

## Settings file format (reference)

`./.claude/standup.local.md` (project-local) or `~/.claude/standup.local.md` (home-level):

```markdown
---
output_dir: /custom/path/to/standup
---
```

The markdown body is unused in v1. Frontmatter is YAML.

## Boundary reminder

`bucket.py` does file walking, date filtering, role-based turn extraction (with `tool_result` exclusion as the ONE allowed content filter), session grouping, and catch-up scan. *Nothing* judgment-shaped lives there. If you're tempted to ask `bucket.py` to also classify turns, summarize, or pre-filter by content — stop. That's this skill's job.
