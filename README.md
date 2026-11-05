## Higashimatsushima ordinance daily check

This repository starts with a daily GitHub Actions check for the Higashimatsushima City ordinance pages.

Source: Higashimatsushima City ordinance menu at `https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_menu.html`.

### What runs every day

The workflow runs at 03:17 JST. GitHub Actions schedules are written in UTC, so the workflow uses `17 18 * * *`.

On schedule, it runs in `check` mode:

1. It fetches only the menu page.
2. It compares the menu page hash and the site current date with `data/status/latest.json`.
3. If nothing changed, it updates the check timestamp and exits without crawling ordinance pages.
4. If something changed, it crawls the systematic index pages, rebuilds the ordinance URL list, and fails instead of overwriting status when pages fail or the ordinance count drops sharply.
5. It commits the updated status files and opens an issue when the site changed.

### Manual run

Use **Actions > Daily Higashimatsushima ordinance check > Run workflow**.

| Input | Meaning |
|---|---|
| `mode=check` | Fetch the menu page. Crawl index pages only when the menu changed. |
| `mode=collect` | Always crawl index pages and rebuild the ordinance URL list. |
| `force_collect=true` | Same crawl trigger for `check` mode. |

### Local run

```bash
python3 -m unittest discover -s tests -v
python3 scripts/daily_check.py --mode check
python3 scripts/daily_check.py --mode collect --delay 0.35
```

Do not run `collect` repeatedly against the city site during development. Use `check` for normal verification.

### Files

| Path | Purpose |
|---|---|
| `.github/workflows/daily-reiki-check.yml` | Daily schedule, manual dispatch, status commit, change issue and failure issue |
| `scripts/daily_check.py` | Standard-library-only checker and index collector |
| `data/status/latest.json` | Last known menu hash, site current date and ordinance URL list |
| `data/status/latest-summary.md` | Human-readable latest check summary |
| `tests/test_daily_check.py` | Parser tests that do not touch the network |

### Limits of this first step

This step does not fetch every ordinance body every day. It detects changes from the menu page first, then collects index pages only when needed. Body fetching, article splitting, SQLite generation, D1 loading and the MCP server come after this foundation is stable.
