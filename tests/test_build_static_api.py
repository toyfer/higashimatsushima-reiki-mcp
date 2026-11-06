import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_static_api
from build_static_api import validate_built_api


def write_law(api_root: Path, law_id: str, data_version: str) -> dict:
    law = {
        "id": law_id,
        "title": "テスト条例",
        "source_url": "https://example.invalid/x.html",
        "articles": [{"label": "第1条", "paragraphs": [{"number": 1, "text": "本文", "items": [{"label": "(1)", "text": "号"}]}]}],
        "text_sha256": "abc",
    }
    laws_dir = api_root / "laws"
    laws_dir.mkdir(parents=True, exist_ok=True)
    (laws_dir / f"{law_id}.json").write_text(json.dumps(law, ensure_ascii=False), encoding="utf-8")
    (laws_dir / "index.json").write_text(json.dumps({"data_version": data_version, "laws": [{"id": law_id}]}), encoding="utf-8")
    return {"id": law_id}


class ValidateBuiltApiTest(unittest.TestCase):
    def test_valid_output_has_no_problems(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_root = Path(tmp) / "api"
            index = [write_law(api_root, "r122RG00000002", "v1")]
            self.assertEqual(validate_built_api(api_root, index, "v1"), [])

    def test_missing_law_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_root = Path(tmp) / "api"
            index = [write_law(api_root, "r122RG00000002", "v1")]
            (api_root / "laws" / "r122RG00000002.json").unlink()
            problems = validate_built_api(api_root, index, "v1")
            self.assertTrue(any(p.startswith("missing_law_file:") for p in problems))

    def test_missing_required_field_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_root = Path(tmp) / "api"
            index = [write_law(api_root, "r122RG00000002", "v1")]
            path = api_root / "laws" / "r122RG00000002.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            del data["text_sha256"]
            path.write_text(json.dumps(data), encoding="utf-8")
            problems = validate_built_api(api_root, index, "v1")
            self.assertIn("missing_field:r122RG00000002:text_sha256", problems)

    def test_bad_item_structure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_root = Path(tmp) / "api"
            index = [write_law(api_root, "r122RG00000002", "v1")]
            path = api_root / "laws" / "r122RG00000002.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["articles"][0]["paragraphs"][0]["items"] = [{"label": "(1)"}]
            path.write_text(json.dumps(data), encoding="utf-8")
            problems = validate_built_api(api_root, index, "v1")
            self.assertTrue(any(p.startswith("bad_item:") for p in problems))

    def test_index_version_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_root = Path(tmp) / "api"
            index = [write_law(api_root, "r122RG00000002", "v1")]
            problems = validate_built_api(api_root, index, "other")
            self.assertIn("index_data_version_mismatch", problems)


class FailOnErrorTest(unittest.TestCase):
    def run_build(self, laws, fail_on_error: bool) -> int:
        import build_static_api as builder
        original_fetch = builder.fetch_text
        original_argv = sys.argv
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status = root / "status.json"
            status.write_text(json.dumps({"laws": laws, "menu_sha256": "m", "current_date": "令和8年6月26日"}), encoding="utf-8")
            calls = {"menu": 0}

            def fake_fetch(url, timeout=30):
                if "reiki_menu" in url or url == builder.MENU_URL:
                    return "<html>内容現在 令和8年6月26日</html>", "menuhash"
                return ("<html><head><title>t</title></head><body>"
                        '<div id="primary"><p>○t</p><p>令和7年4月1日</p><p>条例第1号</p>'
                        "<p>(趣旨)</p><p>第1条　本文。</p></div><!-- /本文 -->"
                        '<div id="secondary"><h2 class="heading-lv2A">t</h2></div></body></html>'), "h"

            builder.fetch_text = fake_fetch  # type: ignore[assignment]
            sys.argv = ["build_static_api.py", "--status", str(status), "--out", str(root / "site"), "--delay", "0"] + (["--fail-on-error"] if fail_on_error else [])
            try:
                return builder.main()
            finally:
                builder.fetch_text = original_fetch  # type: ignore[assignment]
                sys.argv = original_argv

    def test_invalid_status_entry_fails_with_fail_on_error(self) -> None:
        code = self.run_build([{"id": "BAD", "url": "", "title": "x"}], fail_on_error=True)
        self.assertEqual(code, 3)

    def test_invalid_status_entry_makes_health_not_ok_without_flag(self) -> None:
        # No valid laws at all -> exit 4 (no index). The invalid-entry path must not report success.
        code = self.run_build([{"id": "BAD", "url": "", "title": "x"}], fail_on_error=False)
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
