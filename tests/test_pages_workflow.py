import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def read_workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


class PagesWorkflowInvariantsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = read_workflow("pages.yml")
        cls.test_wf = read_workflow("test.yml")
        cls.daily = read_workflow("daily-reiki-check.yml")
        cls.deploy = read_workflow("deploy-worker.yml")
        cls.guard = cls.pages.split("Guard against sample downgrade of a full deployment", 1)[1].split(
            "- name: Check whether", 1
        )[0]

    def test_sample_guard_fails_closed(self) -> None:
        self.assertNotIn("Continuing because this is a manual run", self.pages)
        self.assertIn("ALLOW_SAMPLE_OVERWRITE: ${{ inputs.allow_sample_overwrite }}", self.pages)
        self.assertIn('[ "$ALLOW_SAMPLE_OVERWRITE" = "true" ]', self.guard)
        self.assertIn("mode=skip", self.guard)
        self.assertIn("skip_sample=true", self.guard)
        self.assertGreaterEqual(self.guard.count("exit 1"), 2)
        self.assertIn("commit_sha", self.guard)
        self.assertIn('git cat-file -e "${published_commit}^{commit}"', self.guard)
        self.assertIn('git diff --name-only "$published_commit" "$HEAD_SHA"', self.guard)
        for path in ("scripts/daily_check.py", "scripts/search_index.py"):
            self.assertIn(path, self.pages)
        self.assertIn("scripts/daily_check.py", self.guard)

    def test_full_build_and_delay_defaults(self) -> None:
        self.assertIn('[ "$FULL_BUILD" = "true" ]', self.guard)
        self.assertIn('echo "mode=full"', self.guard)
        self.assertIn("BUILD_DELAY: ${{ inputs.delay_seconds || '0.35' }}", self.pages)
        self.assertNotIn("BUILD_DELAY: ${{ inputs.delay_seconds }}\n", self.pages)
        self.assertIn("fetch-depth: 0", self.pages)
        self.assertEqual(self.pages.count("BUILD_COMMIT: ${{ github.sha }}"), 2)
        self.assertIn("--fail-on-error", self.pages)

    def test_daily_check_permissions_and_status_handoff(self) -> None:
        check_job = self.daily.split("\n  check:", 1)[1].split("\n  full-build:", 1)[0]
        full_build_perms = self.daily.split("  full-build:", 1)[1].split("uses:", 1)[0]
        self.assertNotIn("pages: write", check_job)
        self.assertNotIn("id-token: write", check_job)
        for perm in ("actions: read", "pages: write", "id-token: write"):
            self.assertIn(perm, full_build_perms)
        self.assertIn("status_artifact: reiki-status-${{ github.run_id }}", self.daily)
        self.assertIn("status_artifact:", self.pages)
        restore = self.pages.index("Restore status from the calling workflow")
        compare = self.pages.index("Check whether the ordinance index changed")
        self.assertLess(restore, compare)

    def test_pr_test_workflow_never_deploys(self) -> None:
        self.assertIn("pull_request:", self.test_wf)
        self.assertIn("branches: [main]", self.test_wf)
        self.assertIn("contents: read", self.test_wf)
        self.assertIn("python -m unittest discover -s tests -v", self.test_wf)
        self.assertIn("run: npm test", self.test_wf)
        for forbidden in ("secrets.", "wrangler deploy", "deploy-pages", "upload-pages-artifact", "CLOUDFLARE"):
            self.assertNotIn(forbidden, self.test_wf)

    def test_npm_ci_and_lockfile(self) -> None:
        lock = ROOT / "worker" / "package-lock.json"
        self.assertTrue(lock.exists())
        lock_data = json.loads(lock.read_text(encoding="utf-8"))
        self.assertEqual(lock_data.get("lockfileVersion"), 3)
        self.assertIn("wrangler", json.dumps(lock_data))
        for name, text in (("test.yml", self.test_wf), ("deploy-worker.yml", self.deploy)):
            self.assertIn("run: npm ci", text, name)
            self.assertNotIn("run: npm install", text, name)

    def test_deploy_workflows_ignore_pull_requests(self) -> None:
        self.assertNotIn("secrets.", self.pages)
        self.assertNotIn("npm", self.pages)
        for name, text in (
            ("pages.yml", self.pages),
            ("deploy-worker.yml", self.deploy),
            ("daily-reiki-check.yml", self.daily),
        ):
            on_block = text.split("\npermissions:", 1)[0]
            self.assertIsNone(re.search(r"^\s*pull_request(?:_target)?:", on_block, re.MULTILINE), name)


if __name__ == "__main__":
    unittest.main()
