---
name: release-version
description: Bump project version, update all version files, add RELEASE.txt entry, commit, tag, and push.
---

# Skill: Release Version

Bump the project version, update all version references, write release notes, commit,
tag, and push.

## Usage

```
/release-version <version> [changelog line 1; changelog line 2; ...]
```

Examples:
- `/release-version 01.01.00` -- bump to 01.01.00, prompt for changelog
- `/release-version 01.02.00 SQLite Repository; move-log reconstruction` -- bump with provided changelog items

If no changelog items are provided, analyze uncommitted or recent commits since the last
tag to auto-generate the changelog.

Version notation `vXX.YY.ZZ`: `XX` = roadmap version (v01→01 … v05→05), `YY` = phase
within that version (`v01.02`→YY=02), `ZZ` = post-release fix on that phase. So roadmap
phase `vXX.YY` → release `vXX.YY.00`; a fix after it bumps `ZZ` (e.g. v01.02 → `01.02.00`,
a follow-up fix → `01.02.01`). Releases are cut per phase. **Never change the version
without explicit user confirmation.**

## Instructions

### Step 0: Parse arguments

1. Extract the target version from the first argument (e.g., `01.02.00`)
2. Remaining arguments (separated by `;`) become changelog bullet points
3. Validate version format matches `XX.YY.ZZ` (zero-padded)

### Step 1: Verify prerequisites

1. Confirm we are on the expected branch (the current working dev branch)
2. Confirm working tree is clean (`git status`) -- if dirty, ask the user whether to include uncommitted changes
3. Find the current version: check `VERSION`, `RELEASE.txt`, or the latest git tag
4. Verify the new version is greater than the current version

### Step 2: Generate changelog (if not provided)

If no changelog items were given as arguments:

1. Find the most recent version tag: `git describe --tags --abbrev=0`
2. Collect commits since that tag: `git log --oneline <tag>..HEAD`
3. Summarize the changes into concise bullet points (group related commits; reference the roadmap phase `vXX.YY` where relevant)
4. Show the generated changelog to the user and ask for confirmation

### Step 3: Update version files

1. **`VERSION`** (create if it doesn't exist): the bare version string, e.g. `01.02.00`
2. **`README.md`** (if present): update version reference
3. **FastAPI app version** in `server/main.py` (if present): update the `version=` string on the `FastAPI(...)` app
4. **`RELEASE.txt`** (create if it doesn't exist): prepend a new version block at the top (after any header):

   ```
   Version <version> (YYYY-MM-DD)
   ---------------------------
   - <changelog item 1>
   - <changelog item 2>
   ```

   Use today's date. Keep the existing entries below unchanged.

### Step 4: Commit

Stage only the version-related files — and only the ones that **exist**. Early releases run before
`server/main.py` or `README.md` are generated, and `git add` is **fatal** on a pathspec that matches
nothing (`fatal: pathspec '…' did not match any files`, exit 128), which would abort the release with
the version files already rewritten:

```bash
for f in VERSION README.md RELEASE.txt server/main.py; do
  if [ -e "$f" ]; then git add "$f"; fi
done
```

(Use the `if` form, not `[ -e "$f" ] && git add "$f"` — the latter leaves the loop's exit status at 1
whenever the *last* file is absent, which is exactly the common case here.)

```bash
git commit -m "$(cat <<'EOF'
Release v<version>

<1-2 sentence summary of what this release includes>

Co-Authored-By: <the running model's trailer> <noreply@anthropic.com>
EOF
)"
```

### Step 5: Tag

```bash
git tag -a v<version> -m "<one-line summary of the release>"
```

### Step 6: Push

Push the branch, then **only the tag just created** — never `--tags` or `--follow-tags`:

```bash
git push
git push origin "v<version>"
```

> `git push --tags` pushes *every* local tag, and `--follow-tags` pushes every annotated tag reachable
> from the pushed commits. This repo carries tags inherited from an earlier multi-build repo, all
> reachable from `main`'s history — either flag would publish another build's entire release history
> alongside this release. Push the one tag by name.

### Step 6.5: Emit tracking events

`--emitter skill:release-version --scope phase=..,version=..`: after the tag → `release.tagged`
(`tag`); after the push → `release.pushed` (`tag`, `remote`).

### Step 7: Report

```
Released v<version>
  Branch: <branch>
  Commit: <short hash>
  Tag:    v<version>
  Files updated:
    - VERSION
    - README.md
    - RELEASE.txt
    - server/main.py
```

## Important Rules

- **Never downgrade.** Refuse if the target version is less than or equal to the current version.
- **Clean tree first.** If there are uncommitted changes, ask the user before proceeding.
- **Annotated tags only.** Always use `git tag -a`, never lightweight tags.
- **Don't modify source files.** This skill only touches version metadata (VERSION, README.md, RELEASE.txt, and the FastAPI app version string), never game/server/agent/web logic.
- **Confirm changelog.** If auto-generating changelog from commits, show it to the user before committing.
- **Plain-text release notes.** Keep `RELEASE.txt` plain text.
