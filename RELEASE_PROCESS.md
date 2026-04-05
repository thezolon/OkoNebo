# OkoNebo Release Process

Describes how releases are cut, what constitutes a stable branch, and the post-release monitoring policy.

---

## Branch model

| Branch | Purpose |
|--------|---------|
| `main` | Active development; CI must be green |
| `release/vX.Y.Z` | Release candidate and post-release freeze line |

`release/*` branches are created from `main` once all planned tasks for the version are complete and all CI gates pass.

---

## Release candidate workflow

### 1. Create the release branch

```bash
git checkout main && git pull
git checkout -b release/vX.Y.Z
git push -u origin release/vX.Y.Z
```

### 2. Freeze policy

Once a `release/*` branch is created:

- **No new features** are merged into it.
- Only the following are allowed:
  - Blocking bug fixes (regression, crash, security)
  - Documentation corrections
  - Version-string bumps

Feature work continues on `main`.

### 3. Run the full harness

```bash
bash scripts/test_harness.sh
```

All stages must pass:

```
[harness] compile — OK
[harness] unit tests — OK
[harness] docker build — OK
[harness] health check — OK
[harness] integration smoke — OK
[harness] frontend smoke — OK
[harness] secret leak — OK
```

### 4. CI check

Push the branch and verify the CI workflow succeeds:
`https://github.com/thezolon/OkoNebo/actions`

Wait for green on all jobs before proceeding.

### 5. Final manual check

Walk through [INSTALL.md](INSTALL.md) on a clean machine (or a fresh Docker run with no `config.yaml`).
Confirm:
- First-run overlay appears and blocks the dashboard
- Saving a valid lat/lon dismisses the overlay and loads data
- Setup panel reflects saved values
- Diagnostics row shows a provider responding

---

## Tagging a release

After the release branch CI is green and manual check passes:

```bash
git checkout release/vX.Y.Z
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

### GitHub Release

Create a GitHub Release from the tag:
- Title: `vX.Y.Z`
- Body: contents of `RELEASE_NOTES_vX.Y.Z.md`

---

## Hotfix process

If a critical bug is discovered after tagging:

1. Branch from the release tag: `git checkout -b hotfix/vX.Y.Z+1 vX.Y.Z`
2. Apply the minimal fix.
3. Increment the patch version in `RELEASE_NOTES` and any version strings.
4. Run the full harness and CI.
5. Tag `vX.Y.Z+1` and publish a new GitHub Release.
6. Cherry-pick the fix back to `main`.

---

## Post-release triage (72-hour window)

For the first 72 hours after a release tag is pushed:

- **Monitor** GitHub Issues for new bug reports tagged with the release version.
- **Triage** all new issues within 4 hours during waking hours.
- **Severity criteria:**

| Severity | Criterion | Response |
|----------|-----------|----------|
| P0 — Critical | Dashboard does not load / data never appears / security regression | Hotfix immediately |
| P1 — High | Feature documented in release notes is broken for common configs | Hotfix within 24 h |
| P2 — Medium | Non-critical feature degraded, workaround exists | Fix on `main`, note in next release |
| P3 — Low | UI cosmetic, edge case, enhancement request | Backlog |

- After 72 hours without P0/P1 issues, the release is considered **stable**.
- Pin a "Release stable" comment to the GitHub Release page.

---

## Version string locations

When bumping the version for a new release, update these locations:

| File | Field |
|------|-------|
| `RELEASE_NOTES_vX.Y.Z.md` | Filename + heading |
| `README.md` | CI badge URL (if major) |
| `config.yaml.example` | `user_agent` string |
| `IMPLEMENTATION.md` | Version heading |
