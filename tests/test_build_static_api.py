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



    def test_articles_wrong_type_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_root = Path(tmp) / "api"
            index = [write_law(api_root, "r122RG00000002", "v1")]
            path = api_root / "laws" / "r122RG00000002.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["articles"] = None
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            problems = validate_built_api(api_root, index, "v1")
            self.assertTrue(any(p.startswith("bad_articles_type:") for p in problems))

    def test_paragraphs_and_items_wrong_type_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_root = Path(tmp) / "api"
            index = [write_law(api_root, "r122RG00000002", "v1")]
            path = api_root / "laws" / "r122RG00000002.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["articles"][0]["paragraphs"] = {}
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            problems = validate_built_api(api_root, index, "v1")
            self.assertTrue(any(p.startswith("bad_paragraphs_type:") for p in problems))
            data = json.loads(path.read_text(encoding="utf-8"))
            data["articles"][0]["paragraphs"] = [{"number": 1, "text": "本文", "items": "oops"}]
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            problems = validate_built_api(api_root, index, "v1")
            self.assertTrue(any(p.startswith("bad_items_type:") for p in problems))

    def test_index_laws_wrong_type_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_root = Path(tmp) / "api"
            index = [write_law(api_root, "r122RG00000002", "v1")]
            (api_root / "laws" / "index.json").write_text(
                json.dumps({"data_version": "v1", "laws": {"id": "r122RG00000002"}}), encoding="utf-8"
            )
            problems = validate_built_api(api_root, index, "v1")
            self.assertIn("index_laws_type_mismatch", problems)


class FailOnErrorTest(unittest.TestCase):
    def run_build(self, laws, fail_on_error: bool) -> tuple[int, dict | None]:
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
                code = builder.main()
                health_path = root / "site" / "api" / "health.json"
                health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else None
                return code, health
            finally:
                builder.fetch_text = original_fetch  # type: ignore[assignment]
                sys.argv = original_argv

    def test_invalid_status_entry_fails_with_fail_on_error(self) -> None:
        code, _health = self.run_build([{"id": "BAD", "url": "", "title": "x"}], fail_on_error=True)
        self.assertEqual(code, 3)

    def test_invalid_status_entry_makes_health_not_ok_without_flag(self) -> None:
        laws = [{"id": "BAD", "url": "", "title": "x"}, {"id": "r100RG00000001", "url": "https://example.invalid/1", "title": "有効な条例"}]
        code, health = self.run_build(laws, fail_on_error=False)
        self.assertNotEqual(code, 0)
        self.assertIsNotNone(health)
        assert health is not None
        self.assertFalse(health["ok"])
        self.assertEqual(health["failure_count"], 1)
        self.assertEqual(health["expected_count"], 2)


class ExpectedCountHealthTest(unittest.TestCase):
    def run_build(self, laws, extra_args=None, tamper_articles=False):
        import build_static_api as builder

        original_fetch = builder.fetch_text
        original_parse = builder.parse_honbun
        original_argv = sys.argv
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        status = root / "status.json"
        status.write_text(
            json.dumps({"laws": laws, "menu_sha256": "m", "current_date": "令和8年6月26日"}),
            encoding="utf-8",
        )

        def fake_fetch(url, timeout=30):
            if "reiki_menu" in url or url == builder.MENU_URL:
                return "<html>内容現在 令和8年6月26日</html>", "menuhash"
            return (
                "<html><head><title>t</title></head><body>"
                '<div id="primary"><p>○t</p><p>令和7年4月1日</p><p>条例第1号</p>'
                "<p>(趣旨)</p><p>第1条　本文。</p></div><!-- /本文 -->"
                '<div id="secondary"><h2 class="heading-lv2A">t</h2></div></body></html>'
            ), "h"

        def tampering_parse(html, **kwargs):
            data = original_parse(html, **kwargs)
            data["articles"] = None
            return data

        builder.fetch_text = fake_fetch  # type: ignore[assignment]
        if tamper_articles:
            builder.parse_honbun = tampering_parse  # type: ignore[assignment]
        argv = [
            "build_static_api.py",
            "--status",
            str(status),
            "--out",
            str(root / "site"),
            "--delay",
            "0",
        ] + list(extra_args or [])
        sys.argv = argv
        try:
            code = builder.main()
        finally:
            builder.fetch_text = original_fetch  # type: ignore[assignment]
            builder.parse_honbun = original_parse  # type: ignore[assignment]
            sys.argv = original_argv
        api = root / "site" / "api"
        health = json.loads((api / "health.json").read_text(encoding="utf-8"))
        meta = json.loads((api / "meta.json").read_text(encoding="utf-8"))
        return code, health, meta

    @staticmethod
    def sample_laws():
        return [
            {"id": "r100RG00000001", "url": "https://example.invalid/1", "title": "条例A"},
            {"id": "r100RG00000002", "url": "https://example.invalid/2", "title": "条例B"},
            {"id": "r100RG00000003", "url": "https://example.invalid/3", "title": "条例C"},
        ]

    def test_full_build_reports_expected_count_and_ok(self):
        code, health, meta = self.run_build(self.sample_laws())
        self.assertEqual(code, 0)
        self.assertEqual(health["expected_count"], 3)
        self.assertEqual(health["law_count"], 3)
        self.assertTrue(health["ok"])
        self.assertEqual(health["validation_problems"], [])
        self.assertEqual(meta["expected_count"], 3)

    def test_limit_keeps_full_expected_count_and_not_ok(self):
        code, health, meta = self.run_build(self.sample_laws(), extra_args=["--limit", "2"])
        self.assertEqual(health["expected_count"], 3)
        self.assertEqual(health["selected_count"], 2)
        self.assertEqual(health["law_count"], 2)
        self.assertFalse(health["ok"])
        self.assertEqual(meta["expected_count"], 3)

    def test_only_id_keeps_full_expected_count_and_not_ok(self):
        code, health, meta = self.run_build(
            self.sample_laws(), extra_args=["--only-id", "r100RG00000002"]
        )
        self.assertEqual(health["expected_count"], 3)
        self.assertEqual(health["selected_count"], 1)
        self.assertEqual(health["law_count"], 1)
        self.assertFalse(health["ok"])
        self.assertEqual(meta["expected_count"], 3)

    def test_invalid_container_type_makes_health_not_ok(self):
        code, health, meta = self.run_build(self.sample_laws()[:1], tamper_articles=True)
        self.assertEqual(code, 5)
        self.assertFalse(health["ok"])
        self.assertTrue(
            any(p.startswith("bad_articles_type:") for p in health["validation_problems"]),
            health["validation_problems"],
        )
        self.assertEqual(health["expected_count"], 1)


GOOD_PAGE = (
    "<html><head><title>t</title></head><body>"
    '<div id="primary"><p>○t</p><p>令和7年4月1日</p><p>条例第1号</p>'
    "<p>(趣旨)</p><p>第1条　本文。</p></div><!-- /本文 -->"
    '<div id="secondary"><h2 class="heading-lv2A">t</h2></div></body></html>'
)
# parse_honbun yields item_structure_mismatch for this shape (item before any paragraph).
MISMATCH_PAGE = (
    "<html><head><title>t</title></head><body>"
    '<div id="primary"><p>○t</p><p>令和7年4月1日</p><p>条例第1号</p>'
    "<p>第1条</p><p>（１）　一つ目の号である。</p><p>（２）　二つ目の号である。</p></div><!-- /本文 -->"
    '<div id="secondary"><h2 class="heading-lv2A">t</h2></div></body></html>'
)
EMPTY_PAGE = (
    "<html><head><title>t</title></head><body>"
    '<div id="primary"></div><!-- /本文 -->'
    '<div id="secondary"><h2 class="heading-lv2A">t</h2></div></body></html>'
)


class BlockingWarningBuildTest(unittest.TestCase):
    def run_build(self, page: str, fail_on_error: bool):
        import build_static_api as builder

        original_fetch = builder.fetch_text
        original_argv = sys.argv
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        status = root / "status.json"
        laws = [
            {"id": "r100RG00000001", "url": "https://example.invalid/good", "title": "正常な条例"},
            {"id": "r100RG00000002", "url": "https://example.invalid/bad", "title": "警告のある条例"},
        ]
        status.write_text(
            json.dumps({"laws": laws, "menu_sha256": "m", "current_date": "令和8年6月26日"}),
            encoding="utf-8",
        )

        def fake_fetch(url, timeout=30):
            if "reiki_menu" in url or url == builder.MENU_URL:
                return "<html>内容現在 令和8年6月26日</html>", "menuhash"
            if url.endswith("/good"):
                return GOOD_PAGE, "h"
            return page, "h"

        builder.fetch_text = fake_fetch  # type: ignore[assignment]
        argv = [
            "build_static_api.py",
            "--status",
            str(status),
            "--out",
            str(root / "site"),
            "--delay",
            "0",
        ] + (["--fail-on-error"] if fail_on_error else [])
        sys.argv = argv
        try:
            code = builder.main()
        finally:
            builder.fetch_text = original_fetch  # type: ignore[assignment]
            sys.argv = original_argv
        api = root / "site" / "api"
        health_path = api / "health.json"
        meta_path = api / "meta.json"
        health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else None
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
        return code, health, meta

    def test_item_structure_mismatch_fails_build_without_flag(self) -> None:
        code, health, meta = self.run_build(MISMATCH_PAGE, fail_on_error=False)
        self.assertNotEqual(code, 0)
        self.assertIsNotNone(health)
        assert health is not None and meta is not None
        self.assertFalse(health["ok"])
        self.assertEqual(health["failure_count"], 1)
        self.assertTrue(any("item_structure_mismatch" in f["error"] for f in meta["failures"]), meta["failures"])

    def test_item_structure_mismatch_fails_build_with_fail_on_error(self) -> None:
        code, _health, _meta = self.run_build(MISMATCH_PAGE, fail_on_error=True)
        self.assertEqual(code, 3)

    def test_no_articles_parsed_makes_health_not_ok(self) -> None:
        code, health, meta = self.run_build(EMPTY_PAGE, fail_on_error=False)
        self.assertNotEqual(code, 0)
        self.assertIsNotNone(health)
        assert health is not None and meta is not None
        self.assertFalse(health["ok"])
        self.assertTrue(any("no_articles_parsed" in f["error"] for f in meta["failures"]), meta["failures"])

    def test_no_articles_parsed_fails_with_fail_on_error(self) -> None:
        code, _health, _meta = self.run_build(EMPTY_PAGE, fail_on_error=True)
        self.assertEqual(code, 3)



class PublishedMetadataTest(unittest.TestCase):
    def build(self):
        import build_static_api as builder

        original_fetch = builder.fetch_text
        original_argv = sys.argv
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        status = root / "status.json"
        status.write_text(
            json.dumps(
                {
                    "laws": [{"id": "r100RG00000001", "url": "https://example.invalid/1", "title": "条例A"}],
                    "menu_sha256": "m",
                    "current_date": "令和8年6月26日",
                }
            ),
            encoding="utf-8",
        )

        def fake_fetch(url, timeout=30):
            if "reiki_menu" in url or url == builder.MENU_URL:
                return "<html>内容現在 令和8年6月26日</html>", "menuhash"
            return (
                "<html><head><title>条例A</title></head><body>"
                '<div id="primary"><p>○条例A</p><p>令和7年4月1日</p><p>条例第1号</p>'
                "<p>(趣旨)</p><p>第1条　本文。</p></div><!-- /本文 -->"
                '<div id="secondary"><h2 class="heading-lv2A">条例A</h2></div>'
                '<span class="taikei-item">第1編 総規</span></div></body></html>'
            ), "h"

        builder.fetch_text = fake_fetch  # type: ignore[assignment]
        sys.argv = [
            "build_static_api.py",
            "--status",
            str(status),
            "--out",
            str(root / "site"),
            "--delay",
            "0",
        ]
        try:
            code = builder.main()
        finally:
            builder.fetch_text = original_fetch  # type: ignore[assignment]
            sys.argv = original_argv
        self.assertEqual(code, 0)
        return root / "site" / "api"

    def test_law_json_carries_the_published_data_version(self) -> None:
        api = self.build()
        health = json.loads((api / "health.json").read_text(encoding="utf-8"))
        law = json.loads((api / "laws" / "r100RG00000001.json").read_text(encoding="utf-8"))
        self.assertEqual(law["data_version"], health["data_version"])
        self.assertEqual(law["content_current_date"], "令和8年6月26日")

    def test_title_index_carries_search_summary_fields(self) -> None:
        api = self.build()
        title_index = json.loads((api / "search" / "title-index.json").read_text(encoding="utf-8"))
        entry = title_index["laws"][0]
        for field in ("id", "title", "ordinance_number", "classification", "enacted_date", "article_count", "source_url"):
            self.assertIn(field, entry)
        self.assertEqual(entry["classification"], "第1編 総規")
        self.assertEqual(entry["article_count"], 1)
        self.assertNotIn("body_text", entry)


if __name__ == "__main__":
    unittest.main()
