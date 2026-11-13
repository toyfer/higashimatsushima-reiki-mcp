import contextlib
from email.message import Message
import http.client
import io
import json
import urllib.error
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import daily_check
from daily_check import extract_current_date, extract_honbun_links


class RetryClassificationTest(unittest.TestCase):
    def test_transient_failures_are_retryable(self) -> None:
        self.assertTrue(daily_check.is_retryable(urllib.error.URLError("dns")))
        self.assertTrue(daily_check.is_retryable(TimeoutError("slow")))
        self.assertTrue(daily_check.is_retryable(ConnectionResetError("reset")))
        # A truncated chunked body raises HTTPException, not URLError (issue #80).
        self.assertTrue(daily_check.is_retryable(http.client.IncompleteRead(b"partial")))
        self.assertTrue(daily_check.is_retryable(http.client.BadStatusLine("garbage")))

    def test_server_errors_are_retryable_and_client_errors_are_not(self) -> None:
        for status in (500, 502, 503, 504):
            self.assertTrue(daily_check.is_retryable(urllib.error.HTTPError("u", status, "e", {}, None)))
        for status in (400, 403, 404, 410):
            self.assertFalse(daily_check.is_retryable(urllib.error.HTTPError("u", status, "e", {}, None)))

    def test_unrelated_errors_are_not_retryable(self) -> None:
        self.assertFalse(daily_check.is_retryable(ValueError("parsing")))


class FetchTextRetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_urlopen = daily_check.urllib.request.urlopen
        self.original_sleep = daily_check.time.sleep
        self.sleeps: list[float] = []
        daily_check.time.sleep = lambda seconds: self.sleeps.append(seconds)  # type: ignore[assignment]

    def tearDown(self) -> None:
        daily_check.urllib.request.urlopen = self.original_urlopen  # type: ignore[assignment]
        daily_check.time.sleep = self.original_sleep  # type: ignore[assignment]

    def test_server_error_is_retried_then_succeeds(self) -> None:
        calls: list[str] = []

        def fake_urlopen(request, timeout=30):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise urllib.error.HTTPError("u", 503, "unavailable", {}, None)
            if len(calls) == 2:
                raise http.client.IncompleteRead(b"half")
            return contextlib.nullcontext(FakeResponse(b"<html>ok</html>"))

        daily_check.urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]
        text, digest = daily_check.fetch_text("https://example.test/menu")
        self.assertEqual(text, "<html>ok</html>")
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(self.sleeps), 2)
        self.assertTrue(all(seconds > 0 for seconds in self.sleeps))
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_client_error_is_not_retried(self) -> None:
        calls: list[str] = []

        def fake_urlopen(request, timeout=30):
            calls.append(request.full_url)
            raise urllib.error.HTTPError("u", 404, "missing", {}, None)

        daily_check.urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]
        with self.assertRaises(urllib.error.HTTPError):
            daily_check.fetch_text("https://example.test/menu")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.sleeps, [])


class FakeResponse:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class DailyCheckTest(unittest.TestCase):
    def test_extract_current_date(self) -> None:
        html = "<html><body>東松島市例規 （内容現在 令和8年6月26日）</body></html>"
        self.assertEqual(extract_current_date(html), "令和8年6月26日")

    def test_extract_honbun_links(self) -> None:
        page_url = "https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_taikei/r_taikei_01.html"
        html = """
        <a href="../reiki_honbun/r122RG00000002.html">東松島市の休日を定める条例</a>
        <a href="../reiki_honbun/r122RG00000003.html">東松島市公告式条例</a>
        <a href="r_taikei_02.html">第2編 議会</a>
        """
        laws = extract_honbun_links(page_url, html)
        self.assertEqual([law["id"] for law in laws], ["r122RG00000002", "r122RG00000003"])
        self.assertEqual(laws[0]["title"], "東松島市の休日を定める条例")
        self.assertTrue(laws[0]["url"].endswith("/reiki_honbun/r122RG00000002.html"))


    def test_collect_from_taikei_reports_truncation(self) -> None:
        pages = {
            daily_check.TAIKEI_URL: '<a href="r_taikei_01.html">next</a><a href="../reiki_honbun/r122RG00000002.html">law</a>',
            "https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_taikei/r_taikei_01.html": '<a href="r_taikei_02.html">next2</a>',
            "https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_taikei/r_taikei_02.html": "",
        }
        original = daily_check.fetch_text

        def fake_fetch(url: str):
            return pages[url], "hash"

        daily_check.fetch_text = fake_fetch  # type: ignore[assignment]
        try:
            result = daily_check.collect_from_taikei(max_pages=2, delay_seconds=0)
        finally:
            daily_check.fetch_text = original  # type: ignore[assignment]
        self.assertTrue(result["truncated"])
        self.assertFalse(result["crawl_complete"])
        self.assertEqual(result["pending_page_count"], 1)

    def test_collect_from_taikei_reports_complete(self) -> None:
        pages = {
            daily_check.TAIKEI_URL: '<a href="../reiki_honbun/r122RG00000002.html">law</a>',
        }
        original = daily_check.fetch_text

        def fake_fetch(url: str):
            return pages[url], "hash"

        daily_check.fetch_text = fake_fetch  # type: ignore[assignment]
        try:
            result = daily_check.collect_from_taikei(max_pages=10, delay_seconds=0)
        finally:
            daily_check.fetch_text = original  # type: ignore[assignment]
        self.assertFalse(result["truncated"])
        self.assertTrue(result["crawl_complete"])
        self.assertEqual(result["pending_page_count"], 0)


MENU_HTML = "<html><body>東松島市例規 （内容現在 令和8年6月26日）</body></html>"


def _laws(count: int) -> list[dict[str, str]]:
    return [
        {"id": f"r122RG{i:08d}", "title": f"条例{i}", "url": f"https://example.invalid/{i}", "source_page": "https://example.invalid/menu"}
        for i in range(1, count + 1)
    ]


def _collection(count: int, *, truncated: bool = False, page_errors=None) -> dict:
    return {
        "visited_pages": ["https://example.invalid/taikei"],
        "visited_page_count": 1,
        "pending_page_count": 1 if truncated else 0,
        "pending_pages": ["https://example.invalid/pending"] if truncated else [],
        "crawl_complete": not truncated and not page_errors,
        "truncated": truncated,
        "laws": _laws(count),
        "law_count": count,
        "page_errors": page_errors or [],
    }


class DailyCheckMainTest(unittest.TestCase):
    def run_main(self, previous, *, menu_error=None, collection=None):
        import urllib.error

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        previous_path = root / "previous.json"
        output_path = root / "out" / "latest.json"
        summary_path = root / "out" / "latest-summary.md"
        sentinel = json.dumps(previous, ensure_ascii=False, indent=2) + "\n" if previous is not None else None
        if sentinel is not None:
            previous_path.write_text(sentinel, encoding="utf-8")
            # Output starts as a copy of the previous status so tests can prove
            # that failure paths leave a healthy status untouched.
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(sentinel, encoding="utf-8")

        original_fetch = daily_check.fetch_text
        original_collect = daily_check.collect_from_taikei
        collect_calls: list[tuple] = []

        def fake_fetch(url, timeout=30):
            if menu_error is not None:
                raise menu_error
            return MENU_HTML, "menu-hash"

        def fake_collect(max_pages, delay_seconds):
            collect_calls.append((max_pages, delay_seconds))
            assert collection is not None
            return collection

        daily_check.fetch_text = fake_fetch  # type: ignore[assignment]
        daily_check.collect_from_taikei = fake_collect  # type: ignore[assignment]
        argv = [
            "--mode", "check",
            "--menu-url", "https://example.invalid/menu",
            "--previous", str(previous_path),
            "--output", str(output_path),
            "--summary", str(summary_path),
            "--max-pages", "10",
            "--delay", "0",
        ]
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = daily_check.main(argv)
        finally:
            daily_check.fetch_text = original_fetch  # type: ignore[assignment]
            daily_check.collect_from_taikei = original_collect  # type: ignore[assignment]
        output_text = output_path.read_text(encoding="utf-8") if output_path.exists() else None
        output = json.loads(output_text) if output_text else None
        return code, output, output_text, sentinel, collect_calls

    @staticmethod
    def previous_status(count: int = 100) -> dict:
        return {
            "menu_sha256": "menu-hash",
            "current_date": "令和8年6月26日",
            "law_count": count,
            "laws": _laws(count),
            "visited_page_count": 3,
            "pending_page_count": 0,
            "crawl_complete": True,
        }

    def test_unchanged_menu_reuses_previous_without_collecting(self) -> None:
        code, output, _text, _sentinel, calls = self.run_main(self.previous_status(), collection=None)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        assert output is not None
        self.assertFalse(output["changed"])
        self.assertEqual(output["law_count"], 100)
        self.assertEqual(len(output["laws"]), 100)

    def test_suspicious_drop_returns_5_and_preserves_output(self) -> None:
        previous = self.previous_status(100)
        previous["menu_sha256"] = "old-hash"
        code, _output, text, sentinel, _calls = self.run_main(previous, collection=_collection(80))
        self.assertEqual(code, 5)
        self.assertEqual(text, sentinel)

    def test_menu_fetch_failure_returns_2_and_preserves_output(self) -> None:
        import urllib.error

        code, _output, text, sentinel, _calls = self.run_main(
            self.previous_status(), menu_error=urllib.error.URLError("down"), collection=None
        )
        self.assertEqual(code, 2)
        self.assertEqual(text, sentinel)

    def test_empty_collection_returns_4_and_preserves_output(self) -> None:
        previous = self.previous_status(100)
        previous["menu_sha256"] = "old-hash"
        code, _output, text, sentinel, _calls = self.run_main(previous, collection=_collection(0))
        self.assertEqual(code, 4)
        self.assertEqual(text, sentinel)

    def test_page_errors_return_3_and_preserve_output(self) -> None:
        previous = self.previous_status(100)
        previous["menu_sha256"] = "old-hash"
        collection = _collection(100, page_errors=[{"url": "https://example.invalid/x", "error": "URLError"}])
        code, _output, text, sentinel, _calls = self.run_main(previous, collection=collection)
        self.assertEqual(code, 3)
        self.assertEqual(text, sentinel)

    def test_truncated_crawl_returns_6_and_preserves_output(self) -> None:
        previous = self.previous_status(100)
        previous["menu_sha256"] = "old-hash"
        code, _output, text, sentinel, _calls = self.run_main(previous, collection=_collection(50, truncated=True))
        self.assertEqual(code, 6)
        self.assertEqual(text, sentinel)


class FetchExceptionScopeTest(unittest.TestCase):
    def test_http_exception_is_part_of_the_crawl_error_scope(self) -> None:
        # HTTPException is not an OSError subclass, so it must be listed explicitly (issue #101).
        self.assertFalse(issubclass(http.client.HTTPException, OSError))
        self.assertIn(http.client.HTTPException, daily_check.FETCH_ERRORS)

    def test_collect_records_http_exception_as_page_error(self) -> None:
        original = daily_check.fetch_text

        def fake_fetch(url: str):
            raise http.client.IncompleteRead(b"partial")

        daily_check.fetch_text = fake_fetch  # type: ignore[assignment]
        try:
            result = daily_check.collect_from_taikei(max_pages=5, delay_seconds=0)
        finally:
            daily_check.fetch_text = original  # type: ignore[assignment]
        self.assertEqual(len(result["page_errors"]), 1)
        self.assertIn("IncompleteRead", result["page_errors"][0]["error"])
        self.assertFalse(result["crawl_complete"])

    def test_menu_http_exception_returns_exit_code_2(self) -> None:
        test = DailyCheckMainTest("test_empty_collection_returns_4_and_preserves_output")
        try:
            code, _output, text, sentinel, _calls = test.run_main(
                DailyCheckMainTest.previous_status(100),
                menu_error=http.client.IncompleteRead(b"partial"),
                collection=_collection(100),
            )
        finally:
            test.doCleanups()
        self.assertEqual(code, 2)
        self.assertEqual(text, sentinel)


if __name__ == "__main__":
    unittest.main()
