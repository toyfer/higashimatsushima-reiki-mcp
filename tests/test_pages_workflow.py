import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def read_workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def extract_top_level_block(text: str, key: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}:\s*\n(.*?)(?=^[A-Za-z0-9_-]+:|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    return match.group(1) if match else ""


class WorkflowSecurityAndSafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = read_workflow("pages.yml")
        cls.test_wf = read_workflow("test.yml")
        cls.daily = read_workflow("daily-reiki-check.yml")
        cls.deploy = read_workflow("deploy-worker.yml")

    def test_pr_test_workflow_is_read_only_and_never_deploys(self) -> None:
        on_block = extract_top_level_block(self.test_wf, "on")
        self.assertIn("pull_request:", on_block)
        self.assertIn("contents: read", self.test_wf)
        self.assertIn("python -m unittest discover", self.test_wf)
        self.assertIn("npm test", self.test_wf)
        for forbidden in ("secrets.", "wrangler deploy", "deploy-pages", "upload-pages-artifact", "CLOUDFLARE"):
            self.assertNotIn(forbidden, self.test_wf)

    def test_deploy_workflows_ignore_pull_requests(self) -> None:
        self.assertNotIn("secrets.", self.pages)
        for name, text in (
            ("pages.yml", self.pages),
            ("deploy-worker.yml", self.deploy),
            ("daily-reiki-check.yml", self.daily),
        ):
            on_block = extract_top_level_block(text, "on")
            self.assertIsNone(re.search(r"^\s*pull_request(?:_target)?:", on_block, re.MULTILINE), name)

    def test_pages_build_guards_against_sample_overwrite_and_broken_full_build(self) -> None:
        self.assertNotIn("Continuing because this is a manual run", self.pages)
        self.assertIn("allow_sample_overwrite", self.pages)
        self.assertIn("mode=skip", self.pages)
        self.assertIn("mode=full", self.pages)
        self.assertIn("--fail-on-error", self.pages)
        self.assertIn("BUILD_COMMIT:", self.pages)
        self.assertIn("scripts/daily_check.py", self.pages)
        self.assertIn("scripts/search_index.py", self.pages)

    def test_daily_check_separates_permissions_and_hands_off_status(self) -> None:
        jobs_block = extract_top_level_block(self.daily, "jobs")
        check_job, full_build_job = jobs_block.split("\n  full-build:", 1)
        self.assertNotIn("pages: write", check_job)
        self.assertNotIn("id-token: write", check_job)
        for perm in ("actions: read", "pages: write", "id-token: write"):
            self.assertIn(perm, full_build_job)
        self.assertIn("status_artifact:", self.daily)
        self.assertIn("status_artifact:", self.pages)

    def test_worker_uses_lockfile_v3_and_npm_ci(self) -> None:
        lock = ROOT / "worker" / "package-lock.json"
        self.assertTrue(lock.exists())
        lock_data = json.loads(lock.read_text(encoding="utf-8"))
        self.assertEqual(lock_data.get("lockfileVersion"), 3)
        for name, text in (("test.yml", self.test_wf), ("deploy-worker.yml", self.deploy)):
            self.assertIn("npm ci", text, name)
            self.assertNotIn("npm install", text, name)


if __name__ == "__main__":
    unittest.main()
