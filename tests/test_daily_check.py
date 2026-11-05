import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import daily_check
from daily_check import extract_current_date, extract_honbun_links


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


if __name__ == "__main__":
    unittest.main()
