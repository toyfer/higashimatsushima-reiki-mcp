import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class PagesGuardFailClosedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = read(PAGES)

    def test_manual_sample_run_no_longer_fails_open(self) -> None:
        self.assertNotIn("Continuing because this is a manual run", self.pages)
        self.assertIn('ALLOW_SAMPLE_OVERWRITE: ${{ inputs.allow_sample_overwrite }}', self.pages)
        self.assertIn("allow_sample_overwrite:", self.pages)
        self.assertIn("mode=skip", self.pages)
        self.assertIn("skip_sample=true", self.pages)

    def test_fetch_and_parse_failures_fail_closed_for_every_event(self) -> None:
        guard = self.pages.split("Guard against sample downgrade of a full deployment", 1)[1].split("- name: Check whether", 1)[0]
        self.assertNotIn('if [ "$EVENT_NAME" = "workflow_dispatch" ]; then\n              echo "::warning::Published health.json could not be fetched', guard)
        self.assertEqual(guard.count("exit 1"), 2)
        self.assertIn("Could not fetch published api/health.json. Refusing to build or deploy", guard)
        self.assertIn("was unparsable or law_count was invalid. Refusing to build or deploy", guard)

    def test_overwrite_requires_explicit_opt_in(self) -> None:
        self.assertIn('[ "$ALLOW_SAMPLE_OVERWRITE" = "true" ]', self.pages)
        self.assertIn("allow_sample_overwrite=true was set explicitly", self.pages)

    def test_full_build_still_bypasses_the_sample_guard(self) -> None:
        guard = self.pages.split("Guard against sample downgrade of a full deployment", 1)[1].split("- name: Check whether", 1)[0]
        self.assertIn('[ "$FULL_BUILD" = "true" ]', guard)
        self.assertIn('echo "mode=full"', guard)
        self.assertIn("python scripts/daily_check.py --mode collect --delay 0.35", self.pages)
        self.assertIn("python scripts/build_static_api.py --delay \"$BUILD_DELAY\" --fail-on-error", self.pages)
        self.assertIn("delay_seconds:", self.pages)
        self.assertIn("default: '0.35'", self.pages)

    def test_no_secret_is_needed_for_the_guard(self) -> None:
        self.assertNotIn("secrets.", self.pages)
        self.assertNotIn("npm", self.pages)

    def test_pages_rebuilds_search_index_when_builder_changes(self) -> None:
        self.assertIn("'scripts/search_index.py'", self.pages)

    def test_guard_compares_against_the_published_commit(self) -> None:
        guard = self.pages.split("Guard against sample downgrade of a full deployment", 1)[1].split("- name: Check whether", 1)[0]
        # Issue #74: a cancelled earlier push must not hide its parser change.
        self.assertIn("commit_sha", guard)
        self.assertIn("git diff --name-only \"$published_commit\" \"$HEAD_SHA\"", guard)
        self.assertIn("builder or parser changed since the published build; using full build", guard)
        self.assertIn("git cat-file -e \"${published_commit}^{commit}\"", guard)

    def test_build_steps_record_the_commit(self) -> None:
        self.assertIn("BUILD_COMMIT: ${{ github.sha }}", self.pages)
        self.assertEqual(self.pages.count("BUILD_COMMIT: ${{ github.sha }}"), 2)

    def test_guard_still_fails_closed_on_an_unreadable_health_file(self) -> None:
        guard = self.pages.split("Guard against sample downgrade of a full deployment", 1)[1].split("- name: Check whether", 1)[0]
        self.assertEqual(guard.count("exit 1"), 2)


class PullRequestTestWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = read(TEST_WORKFLOW)

    def test_runs_on_pull_request_and_main_push(self) -> None:
        self.assertIn("pull_request:", self.workflow)
        self.assertIn("push:", self.workflow)
        self.assertIn("branches: [main]", self.workflow)

    def test_python_and_worker_jobs_are_separate(self) -> None:
        self.assertIn("name: Python tests", self.workflow)
        self.assertIn("name: Worker tests", self.workflow)
        self.assertIn("python-version: '3.12'", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("node-version: 22", self.workflow)
        self.assertIn("cache-dependency-path: worker/package-lock.json", self.workflow)
        self.assertIn("run: npm ci", self.workflow)
        self.assertIn("run: npm run check", self.workflow)
        self.assertIn("run: npm test", self.workflow)

    def test_test_workflow_never_deploys(self) -> None:
        self.assertNotIn("secrets.", self.workflow)
        self.assertNotIn("wrangler deploy", self.workflow)
        self.assertNotIn("deploy-pages", self.workflow)
        self.assertNotIn("upload-pages-artifact", self.workflow)
        self.assertNotIn("CLOUDFLARE", self.workflow)
        self.assertIn("contents: read", self.workflow)

    def test_lockfile_is_committed_for_npm_ci(self) -> None:
        lock = ROOT / "worker" / "package-lock.json"
        self.assertTrue(lock.exists())
        data = lock.read_text(encoding="utf-8")
        self.assertIn('"lockfileVersion": 3', data)
        self.assertIn('"wrangler"', data)

    def test_deploy_workflow_also_uses_npm_ci(self) -> None:
        deploy = read(ROOT / ".github" / "workflows" / "deploy-worker.yml")
        self.assertIn("run: npm ci", deploy)
        self.assertNotIn("run: npm install", deploy)

    def test_no_other_workflow_is_triggered_by_pull_request(self) -> None:
        for name in ("pages.yml", "deploy-worker.yml", "daily-reiki-check.yml"):
            text = read(ROOT / ".github" / "workflows" / name)
            header = text.split("\npermissions:", 1)[0]
            on_block = header.split("\non:", 1)[1] if "\non:" in header else header
            self.assertNotIn("pull_request:", on_block, name)
            self.assertNotIn("pull_request_target", on_block, name)


if __name__ == "__main__":
    unittest.main()


class PagesTriggerRobustnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = read(PAGES)
        cls.daily = read(ROOT / ".github" / "workflows" / "daily-reiki-check.yml")

    def test_every_event_gets_a_numeric_delay(self) -> None:
        self.assertIn("BUILD_DELAY: ${{ inputs.delay_seconds || '0.35' }}", self.pages)
        self.assertNotIn("BUILD_DELAY: ${{ inputs.delay_seconds }}\n", self.pages)

    def test_history_is_deep_enough_to_diff_a_merged_pull_request(self) -> None:
        self.assertIn("fetch-depth: 0", self.pages)

    def test_daily_check_hands_its_status_to_the_build(self) -> None:
        self.assertIn("status_artifact:", self.pages)
        self.assertIn("name: ${{ inputs.status_artifact }}", self.pages)
        self.assertIn("inputs.status_artifact == ''", self.pages)
        self.assertIn("status_artifact: reiki-status-${{ github.run_id }}", self.daily)
