import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

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


if __name__ == "__main__":
    unittest.main()
