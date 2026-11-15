import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_static_api
from build_static_api import validate_built_api

GOOD_PAGE = (
    "<html><head><title>t</title></head><body>"
    '<div id="primary"><p>○t</p><p>令和7年4月1日</p><p>条例第1号</p>'
    "<p>(趣旨)</p><p>第1条　本文。</p></div><!-- /本文 -->"
    '<div id="secondary"><h2 class="heading-lv2A">t</h2>'
    '<span class="taikei-item">第1編 総規</span></div></body></html>'
)
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


def run_static_build(
    test_case: unittest.TestCase,
    laws: list[dict],
    *,
    extra_args=None,
    pages_by_suffix=None,
    default_page: str = GOOD_PAGE,
    tamper_articles: bool = False,
    inject_warning: str | None = None,
) -> tuple[int, Path, dict | None, dict | None]:
    original_fetch = build_static_api.fetch_text
    original_parse = build_static_api.parse_honbun
    original_argv = sys.argv
    tmp = tempfile.TemporaryDirectory()
    test_case.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    status = root / "status.json"
    status.write_text(
        json.dumps({"laws": laws, "menu_sha256": "m", "current_date": "令和8年6月26日"}),
        encoding="utf-8",
    )

    def fake_fetch(url: str, timeout: int = 30):
        if "reiki_menu" in url or url == build_static_api.MENU_URL:
            return "<html>内容現在 令和8年6月26日</html>", "menuhash"
        for suffix, html in (pages_by_suffix or {}).items():
            if url.endswith(suffix):
                return html, "h"
        return default_page, "h"

    def tampering_parse(html, **kwargs):
        data = original_parse(html, **kwargs)
        data["articles"] = None
        return data

    def warning_parse(html, **kwargs):
        data = original_parse(html, **kwargs)
        data["parse_warnings"] = list(data.get("parse_warnings") or []) + [inject_warning]
        return data

    build_static_api.fetch_text = fake_fetch  # type: ignore[assignment]
    if tamper_articles:
        build_static_api.parse_honbun = tampering_parse  # type: ignore[assignment]
    elif inject_warning:
        build_static_api.parse_honbun = warning_parse  # type: ignore[assignment]

    sys.argv = [
        "build_static_api.py",
        "--status",
        str(status),
        "--out",
        str(root / "site"),
        "--delay",
        "0",
    ] + list(extra_args or [])
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = build_static_api.main()
    finally:
        build_static_api.fetch_text = original_fetch  # type: ignore[assignment]
        build_static_api.parse_honbun = original_parse  # type: ignore[assignment]
        sys.argv = original_argv

    api = root / "site" / "api"
    health_path = api / "health.json"
    meta_path = api / "meta.json"
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else None
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
    return code, api, health, meta


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
            self.assertIn("missing_field:r122RG00000002:text_sha256", validate_built_api(api_root, index, "v1"))

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

    def test_index_version_and_type_mismatches_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api_root = Path(tmp) / "api"
            index = [write_law(api_root, "r122RG00000002", "v1")]
            self.assertIn("index_data_version_mismatch", validate_built_api(api_root, index, "other"))

            path = api_root / "laws" / "r122RG00000002.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["articles"] = None
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(any(p.startswith("bad_articles_type:") for p in validate_built_api(api_root, index, "v1")))

            data["articles"] = [{"label": "第1条", "paragraphs": {}}]
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(any(p.startswith("bad_paragraphs_type:") for p in validate_built_api(api_root, index, "v1")))

            data["articles"] = [{"label": "第1条", "paragraphs": [{"number": 1, "text": "本文", "items": "oops"}]}]
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(any(p.startswith("bad_items_type:") for p in validate_built_api(api_root, index, "v1")))

            (api_root / "laws" / "index.json").write_text(
                json.dumps({"data_version": "v1", "laws": {"id": "r122RG00000002"}}), encoding="utf-8"
            )
            self.assertIn("index_laws_type_mismatch", validate_built_api(api_root, index, "v1"))


class BuildStaticApiBehaviorTest(unittest.TestCase):
    @staticmethod
    def sample_laws():
        return [
            {"id": "r100RG00000001", "url": "https://example.invalid/1", "title": "条例A"},
            {"id": "r100RG00000002", "url": "https://example.invalid/2", "title": "条例B"},
            {"id": "r100RG00000003", "url": "https://example.invalid/3", "title": "条例C"},
        ]

    def test_invalid_status_entry_behavior_with_and_without_fail_on_error(self) -> None:
        code_fail, _api, _health, _meta = run_static_build(
            self, [{"id": "BAD", "url": "", "title": "x"}], extra_args=["--fail-on-error"]
        )
        self.assertEqual(code_fail, 3)

        laws = [{"id": "BAD", "url": "", "title": "x"}, {"id": "r100RG00000001", "url": "https://example.invalid/1", "title": "有効"}]
        code, _api, health, _meta = run_static_build(self, laws)
        self.assertNotEqual(code, 0)
        assert health is not None
        self.assertFalse(health["ok"])
        self.assertEqual(health["failure_count"], 1)
        self.assertEqual(health["expected_count"], 2)

    def test_full_build_publishes_consistent_versions_counts_and_title_index(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"BUILD_COMMIT": "f985ce0011"}):
            code, api, health, meta = run_static_build(self, self.sample_laws())
        self.assertEqual(code, 0)
        assert health is not None and meta is not None
        self.assertTrue(health["ok"])
        self.assertEqual((health["expected_count"], health["law_count"]), (3, 3))
        self.assertEqual(health["validation_problems"], [])
        self.assertEqual(health["commit_sha"], "f985ce0011")
        self.assertEqual(meta["commit_sha"], "f985ce0011")

        law = json.loads((api / "laws" / "r100RG00000001.json").read_text(encoding="utf-8"))
        manifest = json.loads((api / "search" / "manifest.json").read_text(encoding="utf-8"))
        title_index = json.loads((api / "search" / "title-index.json").read_text(encoding="utf-8"))
        self.assertEqual(law["data_version"], health["data_version"])
        self.assertEqual(law["content_current_date"], "令和8年6月26日")
        self.assertEqual(manifest["data_version"], health["data_version"])
        self.assertEqual(manifest["chunk_count"], health["search_chunk_count"])
        self.assertEqual(title_index["data_version"], health["data_version"])
        entry = title_index["laws"][0]
        for field in ("id", "title", "ordinance_number", "classification", "enacted_date", "article_count", "source_url"):
            self.assertIn(field, entry)
        self.assertEqual(entry["classification"], "第1編 総規")
        self.assertEqual(entry["article_count"], 1)
        self.assertNotIn("body_text", entry)

    def test_missing_build_commit_is_published_as_empty(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"BUILD_COMMIT": ""}):
            code, _api, health, meta = run_static_build(self, self.sample_laws()[:1])
        self.assertEqual(code, 0)
        assert health is not None and meta is not None
        self.assertEqual((health["commit_sha"], meta["commit_sha"]), ("", ""))

    def test_informational_warning_does_not_block_fail_on_error(self) -> None:
        code, _api, health, _meta = run_static_build(
            self,
            self.sample_laws(),
            extra_args=["--fail-on-error"],
            inject_warning="history_table_empty_or_unrecognized",
        )
        self.assertEqual(code, 0)
        assert health is not None
        self.assertTrue(health["ok"])
        self.assertGreater(health["warning_count"], 0)
        self.assertEqual(health["failure_count"], 0)

    def test_partial_builds_keep_full_expected_count_and_mark_not_ok(self) -> None:
        for extra in (["--limit", "2"], ["--only-id", "r100RG00000002"]):
            with self.subTest(extra=extra):
                _code, _api, health, meta = run_static_build(self, self.sample_laws(), extra_args=extra)
                assert health is not None and meta is not None
                self.assertFalse(health["ok"])
                self.assertEqual(health["expected_count"], 3)
                self.assertEqual(meta["expected_count"], 3)
                self.assertLess(health["selected_count"], 3)

    def test_invalid_container_type_makes_health_not_ok(self) -> None:
        code, _api, health, _meta = run_static_build(self, self.sample_laws()[:1], tamper_articles=True)
        self.assertEqual(code, 5)
        assert health is not None
        self.assertFalse(health["ok"])
        self.assertTrue(any(p.startswith("bad_articles_type:") for p in health["validation_problems"]))

    def test_blocking_parse_warnings_fail_build_with_and_without_flag(self) -> None:
        laws = [
            {"id": "r100RG00000001", "url": "https://example.invalid/good", "title": "正常な条例"},
            {"id": "r100RG00000002", "url": "https://example.invalid/bad", "title": "警告のある条例"},
        ]
        for expected_tag, page in (("item_structure_mismatch", MISMATCH_PAGE), ("no_articles_parsed", EMPTY_PAGE)):
            with self.subTest(expected_tag=expected_tag):
                code, _api, health, meta = run_static_build(
                    self, laws, pages_by_suffix={"/good": GOOD_PAGE, "/bad": page}
                )
                self.assertNotEqual(code, 0)
                assert health is not None and meta is not None
                self.assertFalse(health["ok"])
                self.assertEqual(health["failure_count"], 1)
                self.assertTrue(any(expected_tag in f["error"] for f in meta["failures"]), meta["failures"])

                code_strict, _api2, _health2, _meta2 = run_static_build(
                    self,
                    laws,
                    extra_args=["--fail-on-error"],
                    pages_by_suffix={"/good": GOOD_PAGE, "/bad": page},
                )
                self.assertEqual(code_strict, 3)


if __name__ == "__main__":
    unittest.main()
