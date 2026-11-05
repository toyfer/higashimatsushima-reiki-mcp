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
5. Leave the schedule enabled.

### Troubleshooting

| Symptom | Check |
|---|---|
| Schedule does not run | The workflow file must be on the default branch. Scheduled runs can be delayed. Public repositories can have schedules disabled after long inactivity depending on repository state. |
| Commit step fails | Check Actions workflow permissions and branch protection. |
| Failure issue repeats | Open the latest run and check whether the city site fetch failed, index pages failed, or the count dropped sharply. |
| `law_count` is zero | The index HTML structure may have changed. Inspect `reiki_taikei/taikei_default.html` links before changing the parser. |
