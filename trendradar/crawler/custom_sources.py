# coding=utf-8
"""
TrendRadar 自定义网页数据源

用途：
- 直接抓取指定网页中的文章标题和链接
- 不使用 RSS
- 返回与 NewsNow 平台相同的 results 数据结构
- 当前主要用于“阅读”分类
"""

import re
from html.parser import HTMLParser
from html import unescape
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


class AnchorParser(HTMLParser):
    """提取页面中所有 a 标签"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: List[Dict] = []
        self._current_href: Optional[str] = None
        self._current_title: Optional[str] = None
        self._current_text: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        attr_dict = dict(attrs)
        href = attr_dict.get("href")

        if not href:
            return

        self._current_href = href
        self._current_title = attr_dict.get("title")
        self._current_text = []

    def handle_data(self, data):
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a":
            return

        if self._current_href is None:
            return

        text = " ".join(self._current_text)
        text = re.sub(r"\s+", " ", unescape(text)).strip()

        title = self._current_title or text

        if title:
            self.links.append(
                {
                    "href": self._current_href,
                    "title": title.strip(),
                }
            )

        self._current_href = None
        self._current_title = None
        self._current_text = []


SOURCE_RULES = {
    "lifeweek-reading": {
        "include_paths": [
            r"/article/",
            r"/content/",
        ],
        "exclude_titles": [
            r"登录",
            r"注册",
            r"订阅",
            r"查看更多",
            r"首页",
        ],
    },

    "owspace": {
        "include_paths": [
            r"/index\.php",
            r"\.html$",
        ],
        "exclude_titles": [
            r"首页",
            r"活动",
            r"商店",
            r"关于",
            r"登录",
            r"注册",
        ],
    },

    "aeon": {
        "include_paths": [
            r"^/essays/",
        ],
        "exclude_titles": [
            r"newsletter",
            r"subscribe",
            r"about",
            r"privacy",
            r"terms",
        ],
    },

    "works-in-progress": {
        "include_paths": [
            r"^/issue/",
        ],
        "exclude_titles": [
            r"subscribe",
            r"newsletter",
            r"podcast",
            r"about",
            r"archive",
        ],
    },

    "noema": {
        "include_paths": [
            r"^/.+/$",
        ],
        "exclude_titles": [
            r"about",
            r"subscribe",
            r"newsletter",
            r"contact",
            r"privacy",
            r"terms",
            r"podcast",
            r"video",
        ],
    },

    "farnam-street": {
        "include_paths": [
            r"^/.+/$",
        ],
        "exclude_titles": [
            r"newsletter",
            r"about",
            r"membership",
            r"courses",
            r"privacy",
            r"contact",
            r"podcast",
        ],
    },
}


class CustomSourceFetcher:
    """自定义网页源抓取器"""

    def __init__(
        self,
        proxy_url: Optional[str] = None,
        timeout: int = 15,
        max_items_per_source: int = 20,
    ):
        self.proxy_url = proxy_url
        self.timeout = timeout
        self.max_items_per_source = max_items_per_source

    def _get_proxies(self):
        if not self.proxy_url:
            return None

        return {
            "http": self.proxy_url,
            "https": self.proxy_url,
        }

    @staticmethod
    def _domain_allowed(url: str, expected_domain: str) -> bool:
        try:
            parsed = urlparse(url)

            if parsed.scheme != "https":
                return False

            host = (parsed.hostname or "").lower()
            expected = expected_domain.lower()

            return host == expected or host.endswith("." + expected)

        except Exception:
            return False

    @staticmethod
    def _path_matches(path: str, patterns: List[str]) -> bool:
        if not patterns:
            return True

        return any(
            re.search(pattern, path, flags=re.IGNORECASE)
            for pattern in patterns
        )

    @staticmethod
    def _title_excluded(title: str, patterns: List[str]) -> bool:
        return any(
            re.search(pattern, title, flags=re.IGNORECASE)
            for pattern in patterns
        )

    def fetch_source(
        self,
        source: Dict,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """
        抓取单个网页源

        Returns:
            (结果, 错误)
        """

        source_id = source.get("id", "").strip()
        name = source.get("name", source_id)
        list_url = source.get("url", "").strip()
        expected_domain = source.get("expected_domain", "").strip()

        if not source_id or not list_url:
            return None, "缺少 id 或 url"

        rule = SOURCE_RULES.get(source_id, {})

        include_paths = source.get(
            "include_paths",
            rule.get("include_paths", []),
        )

        exclude_titles = source.get(
            "exclude_titles",
            rule.get("exclude_titles", []),
        )

        max_items = int(
            source.get(
                "max_items",
                self.max_items_per_source,
            )
        )

        try:
            response = requests.get(
                list_url,
                headers=DEFAULT_HEADERS,
                proxies=self._get_proxies(),
                timeout=self.timeout,
            )

            response.raise_for_status()

            parser = AnchorParser()
            parser.feed(response.text)

            result = {}
            seen_urls = set()

            rank = 1

            for item in parser.links:
                raw_href = item["href"]
                title = re.sub(r"\s+", " ", item["title"]).strip()

                if len(title) < 6:
                    continue

                if len(title) > 180:
                    continue

                if raw_href.startswith(
                    (
                        "#",
                        "javascript:",
                        "mailto:",
                        "tel:",
                    )
                ):
                    continue

                article_url = urljoin(list_url, raw_href)

                try:
                    parsed = urlparse(article_url)
                except Exception:
                    continue

                if parsed.scheme not in ("http", "https"):
                    continue

                if expected_domain:
                    if not self._domain_allowed(
                        article_url,
                        expected_domain,
                    ):
                        continue

                if not self._path_matches(
                    parsed.path,
                    include_paths,
                ):
                    continue

                if self._title_excluded(
                    title,
                    exclude_titles,
                ):
                    continue

                if article_url in seen_urls:
                    continue

                seen_urls.add(article_url)

                result[title] = {
                    "ranks": [rank],
                    "url": article_url,
                    "mobileUrl": "",
                }

                rank += 1

                if len(result) >= max_items:
                    break

            if not result:
                return None, f"{name} 未解析到有效文章"

            print(
                f"[自定义源] {name} 获取成功，共 {len(result)} 条"
            )

            return result, None

        except Exception as e:
            return None, str(e)

    def crawl_sources(
        self,
        sources: List[Dict],
    ) -> Tuple[Dict, Dict, List]:
        """
        批量抓取自定义网页源

        Returns:
            results,
            id_to_name,
            failed_ids
        """

        results = {}
        id_to_name = {}
        failed_ids = []

        for source in sources:
            if not source.get("enabled", True):
                continue

            source_id = source.get("id", "").strip()
            name = source.get("name", source_id)

            if not source_id:
                continue

            id_to_name[source_id] = name

            data, error = self.fetch_source(source)

            if data:
                results[source_id] = data
            else:
                failed_ids.append(source_id)
                print(
                    f"[自定义源] {name} 获取失败: {error}"
                )

        return results, id_to_name, failed_ids
