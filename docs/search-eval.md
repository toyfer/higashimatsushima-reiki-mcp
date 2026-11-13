# Search golden set

`tools/search_eval.mjs` runs the Worker in-process against the published Pages index and checks that real queries still behave the way they are supposed to. It exists because a ranking or matching change can be green in unit tests and still return the wrong ordinance: the unit tests use small fixtures, the golden set uses 1,192 ordinances and 20,631 chunks.

## When it runs

`.github/workflows/search-eval.yml` starts on the completion of "Deploy static ordinance API to GitHub Pages" and on manual dispatch.

The trigger is post-publish on purpose. The evaluation needs a published index, so a pull request run could fail only because the index still describes the previous commit. After a successful publish, a red run is unambiguous: the live code and the live corpus disagree.

A failing case fails the run. The markdown summary is written to the step summary and uploaded as the `search-eval` artifact, so the failing case names and counts are visible without opening the log.

## Running it locally

```bash
node tools/search_eval.mjs
node tools/search_eval.mjs tests/fixtures/search_golden.json
PAGES_BASE=http://localhost:8788 node tools/search_eval.mjs
```

Network access to Pages is required; there is no offline mode. `PAGES_BASE` points the run at a local mirror or a preview deployment. The exit code is 0 only when every case passes.

## Case fields

| Field | Meaning |
|---|---|
| `name` | Unique case name used in the log and the summary |
| `query` | The search query |
| `args` | Extra `search_laws_by_content` arguments: `limit`, `law_id`, `scope`, `operator`, `exact`, `group_by` |
| `expect_error` | The call must be rejected, for example a one-character query |
| `must_include` / `must_exclude` | Law IDs that must, or must not, appear in the results |
| `must_include_labels` / `must_exclude_labels` | Substring that must, or must not, appear in a result `label`, which is how appendix tables and supplements are pinned |
| `must_include_status` | A `content_status` that must appear, for example `external_resource_only` |
| `expect_completeness` | `complete` or `partial` |
| `max_fetches` | Upper bound on `pages_fetches` for the case; `law_id` scoped searches must stay at 1 |
| `note` | Why the case exists |

Every case also fails when a result is labelled `exact` but carries no highlights, because that pair is self-contradictory for a caller.

## Adding a case

Pick a real query from a question the office actually receives, then decide what the correct answer must contain and must not contain. Both halves matter: `600万円` passing is not enough if it also returns the ordinance that says `3,600万円`.

```bash
node -e '
const { readFile } = require("node:fs/promises");
' # or simply run the query through search_laws_by_content first and read the law IDs
```

Run the case against the current index before committing it. A case that already fails is a finding, not a test: open an issue, fix the behaviour, and only then add the case as a lock.

## Limits

Thirteen cases do not cover 20,631 chunks. The set is a regression lock on the behaviours that have already gone wrong (bigram coincidence, numeric boundaries, appendix resources, law-scoped fetches), not a quality score. Adding a case whenever a question gets answered wrongly is what keeps it useful.
