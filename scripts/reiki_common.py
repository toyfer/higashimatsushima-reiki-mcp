from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

MENU_URL = "https://www.city.higashimatsushima.miyagi.jp/reiki/reiki_menu.html"
USER_AGENT = "higashimatsushima-reiki-mcp/0.2 (+daily public-page change check)"

_WS_RE = re.compile(r"\s+")


def clean_text(value: str) -> str:
    value = value.replace("\u3000", " ").replace("\xa0", " ")
    return _WS_RE.sub(" ", value).strip()


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._skip += 1
        if tag.lower() in {"br", "p", "div", "tr", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._skip:
            self._skip -= 1
        if tag.lower() in {"p", "div", "tr", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    lines = [clean_text(line) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)
