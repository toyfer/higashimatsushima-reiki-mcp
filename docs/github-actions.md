## Daily GitHub Actions setup

### Schedule

GitHub Actions `schedule` uses UTC by default. This workflow uses:

```yaml
on:
  schedule:
    - cron: '17 18 * * *'
```

That is 03:17 JST. The minute is deliberately not `0`, because top-of-hour schedules are more likely to be delayed.

Scheduled workflows only run from the default branch. Push these files to the repository default branch before expecting the daily run to appear.

### Deploy triggers

`pages.yml` has three automated paths to the published API, so a merged fix no longer waits for a manual dispatch:

| Trigger | Mode | Why |
|---|---|---|
| Push to `main` that touches a parser, index or builder script | full build | The pushed diff is inspected in the guard step, because a path filter cannot tell a script edit from a status-only update |
| `workflow_call` from `daily-reiki-check.yml` | full build | Fires only when the menu hash or the content date changed, so quiet days still cost one request |
| `schedule` | full build | Weekly insurance for body-only replacements that leave the menu hash and the content date untouched |

The weekly run is `17 19 * * 6` in UTC, which is Sunday 04:17 JST, one hour after the daily check so the two runs never queue behind each other. A scheduled run always builds the full API; it is not a cheap check.

A push that only refreshes `data/status/latest.json` still takes the 5-ordinance sample path.

### Index handoff between workflows

`daily-reiki-check.yml` publishes the check status and does not touch the published index. When it asks `pages.yml` for a full build it passes `status_artifact`, and `pages.yml` downloads that artifact in the build job instead of crawling the status a second time. `pages.yml` declares the artifact as an input only; it returns no outputs, so the caller keeps the artifact it produced and names it again on a later call.

| Input | Effect |
|---|---|
| `full_build` | `true` forces the full build even when the guard sees no script change |
| `allow_sample_overwrite` | `true` lets a 5-ordinance sample replace a larger published API |
| `delay_seconds` | Per-page crawl delay, `0.35` by default |
| `status_artifact` | Artifact name carrying `status/latest.json`; when set, the build job skips its own collection step |

Merging several pull requests in quick succession can still leave the published API stale: the run for the intermediate push is dropped by the `github-pages` concurrency group and the run for the last push may skip because its diff only touched documentation. After a batch of merges, dispatch `pages.yml` with `full_build=true` and confirm that `api/health.json` reports a new `data_version`.

### Sample downgrade guard

The 5-ordinance sample is only safe while nothing larger is published. Before building, the guard step reads the published `api/health.json` with a per-run cache buster and `Cache-Control: no-cache`, so a CDN copy from before the last full deployment cannot be mistaken for the current state.

| Published `law_count` | Event | Result |
|---|---|---|
| any | `schedule`, `workflow_call` or `workflow_dispatch` with `full_build=true`, or a push that changed a parser/builder script | full build |
| more than 5 | push or manual sample run without `allow_sample_overwrite` | skip the build and keep the published API |
| more than 5 | manual run with `allow_sample_overwrite=true` | sample build, with a warning in the run log |
| 5 or fewer | push or manual sample run | sample build |

If `health.json` is unreachable, or `law_count` cannot be parsed as a non-negative integer, the job fails instead of deploying. Failing closed is deliberate: an unreadable state must never be read as "nothing published yet".

### Why check mode is the daily default

Fetching every ordinance body every day would put unnecessary load on the city site and make most runs meaningless. The menu page carries the site current date. The checker stores the menu hash and current date in `data/status/latest.json`.

When the menu hash and current date are unchanged, the run ends after updating the check state. When either changes, the checker crawls systematic index pages and rebuilds the list of ordinance body URLs. It does not silently accept a broken crawl: page failures, an empty index, or a drop of more than 10 percent in ordinance count make the job fail before status is committed.

### Labels

Create these labels before the first run if you want the issue steps to attach them cleanly:

| Label | Used for |
|---|---|
| `reiki-update` | The ordinance site changed |
| `reiki-check-failure` | The daily check failed |

If a label step fails in your repository settings, remove the `labels` entries from the workflow or create the labels first.

### Permissions

The workflow needs:

| Permission | Reason |
|---|---|
| `contents: write` | Commit `data/status/latest.json` and `data/status/latest-summary.md` |
| `issues: write` | Open change and failure issues |

Repository settings must also allow GitHub Actions to create commits with `GITHUB_TOKEN`. If branch protection blocks direct pushes to the default branch, change the commit step into a pull-request step before enabling the daily schedule.

### First run order

1. Push the repository files to the default branch.
2. Run the workflow manually with `mode=collect` and `force_collect=false` once. This builds the first ordinance URL list.
3. Confirm `data/status/latest.json` contains `current_date`, `law_count` and `laws`.
4. Run it manually again with `mode=check`. It should report no crawl unless the menu changed.
5. After merging a parser, index or builder change, confirm the push-triggered full build ran, or dispatch the workflow manually with `full_build=true`.
6. Leave the schedule enabled.

### Troubleshooting

| Symptom | Check |
|---|---|
| Schedule does not run | The workflow file must be on the default branch. Scheduled runs can be delayed. Public repositories can have schedules disabled after long inactivity depending on repository state. |
| Commit step fails | Check Actions workflow permissions and branch protection. |
| Failure issue repeats | Open the latest run and check whether the city site fetch failed, index pages failed, or the count dropped sharply. |
| `law_count` is zero | The index HTML structure may have changed. Inspect `reiki_taikei/taikei_default.html` links before changing the parser. |
| Sample deploy skipped | The published API has more than 5 laws and this run was a push or a sample dispatch. This is the guard working; dispatch with `full_build=true` to refresh the full API. |
| Weekly build failed | A scheduled run always builds the full API. Check the failure count in the run summary before dispatching manually. |
