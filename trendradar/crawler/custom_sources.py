# coding=utf-8
"""
TrendRadar 自定义网页数据源

用途：
- 直接抓取指定网页中的文章标题和链接
- 不使用 RSS / API / 浏览器渲染
- 返回与 NewsNow 平台相同的 results 数据结构
- 当前用于“阅读与思想”分类
"""

import re
from html import unescape
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import requests


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
}


class AnchorParser(HTMLParser):
    """提取 <a> 中的 href 与可见标题。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: List[Dict] = []
        self._href: Optional[str] = None
        self._title: Optional[str] = None
        self._texts: List[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)

        if tag == "a":
            href = attrs.get("href")
            if not href:
                return

            self._href = href
            self._title = (
                attrs.get("title")
                or attrs.get("aria-label")
            )
            self._texts = []
            return

        if self._href is not None and tag == "img":
            alt = (
                attrs.get("alt")
                or attrs.get("title")
            )

            if alt:
                self._texts.append(alt)

    def handle_data(self, data):
        if self._href is None:
            return

        text = data.strip()

        if text:
            self._texts.append(text)

    def handle_endtag(self, tag):
        if (
            tag.lower() != "a"
            or self._href is None
        ):
            return

        text = " ".join(
            self._texts
        )

        text = re.sub(
            r"\s+",
            " ",
            unescape(text),
        ).strip()

        title = (
            self._title
            or text
        ).strip()

        if title:
            self.links.append(
                {
                    "href": self._href,
                    "title": title,
                }
            )

        self._href = None
        self._title = None
        self._texts = []


# ==============================================================
# 各来源独立规则
# ==============================================================

SOURCE_RULES = {

    # ==========================================================
    # 1. JSTOR Daily
    #
    # 方向：
    # 历史 / 社会 / 人文 / 科学 / 文化
    #
    # 正文一般是：
    # /article-slug/
    # ==========================================================
    "jstor-daily": {
        "list_urls": [
            "https://daily.jstor.org/",
            "https://daily.jstor.org/category/stories/",
        ],

        "include_paths": [
            r"^/[a-z0-9][a-z0-9\-]+/?$",
        ],

        "exclude_paths": [
            r"^/$",
            r"^/about",
            r"^/contact",
            r"^/category/",
            r"^/tag/",
            r"^/author/",
            r"^/newsletter",
            r"^/privacy",
            r"^/terms",
            r"^/search",
        ],

        "exclude_titles": [
            r"newsletter",
            r"subscribe",
            r"about",
            r"contact",
            r"privacy",
            r"terms",
            r"search",
            r"support",
            r"donate",
            r"popular",
            r"trending",
            r"most recent",
            r"long reads",
        ],
    },

    # ==========================================================
    # 2. Works in Progress
    #
    # 方向：
    # 科技 / 社会 / 经济 / 制度
    # ==========================================================
    "works-in-progress": {
        "list_urls": [
            "https://worksinprogress.co/",
        ],

        "include_paths": [
            r"^/issue/[^/]+/?$",
        ],

        "exclude_paths": [
            r"^/issue-\d+/?$",
            r"^/about",
            r"^/archive",
            r"^/podcast",
            r"^/subscribe",
        ],

        "exclude_titles": [
            r"subscribe",
            r"newsletter",
            r"podcast",
            r"about",
            r"archive",
            r"issue\s+\d+",
            r"read more",
            r"meet viktor",
        ],
    },

    # ==========================================================
    # 3. Noema
    #
    # 方向：
    # 社会 / 科技 / 未来 / 思想
    # ==========================================================
    "noema": {
        "list_urls": [
            "https://www.noemamag.com/",
            "https://www.noemamag.com/articles-search/",
            (
                "https://www.noemamag.com/"
                "article-type/essay/?current_page=1"
            ),
        ],

        "include_paths": [
            r"^/[a-z0-9][a-z0-9\-]+/?$",
        ],

        "exclude_paths": [
            r"^/$",
            r"^/author/",
            r"^/article-type/",
            r"^/article-topic/",
            r"^/articles-search",
            r"^/about",
            r"^/contact",
            r"^/privacy",
            r"^/terms",
            r"^/subscribe",
            r"^/newsletter",
            r"^/category/",
            r"^/tag/",
            r"^/podcast",
            r"^/video",
            r"^/print",
        ],

        "exclude_titles": [
            r"^about$",
            r"subscribe",
            r"newsletter",
            r"contact",
            r"privacy",
            r"terms",
            r"podcast",
            r"video",
            r"read noema",
            r"print",
            r"all topics",
            r"all types",
            r"newest",
            r"showing \d+",
            r"editors.? picks",
            r"most read",
            r"best of",
        ],
    },

    # ==========================================================
    # 4. Farnam Street
    #
    # 方向：
    # 思维 / 决策 / 认知 / 学习
    #
    # 增加 Sponsor / 广告过滤
    # ==========================================================
    "farnam-street": {
        "list_urls": [
            "https://fs.blog/blog/",
            "https://fs.blog/",
        ],

        "include_paths": [
            r"^/[a-z0-9][a-z0-9\-]+/?$",
        ],

        "exclude_paths": [
            r"^/$",
            r"^/blog/?$",
            r"^/about",
            r"^/category/",
            r"^/tag/",
            r"^/author/",
            r"^/courses",
            r"^/membership",
            r"^/newsletter",
            r"^/privacy",
            r"^/contact",
            r"^/podcast",
            r"^/shop",
            r"^/books",
            r"^/reading-list",
            r"^/mental-models/?$",
            r"^/decision-making/?$",
            r"^/sponsor",
            r"^/advertis",
        ],

        "exclude_titles": [
            r"^sponsor$",
            r"sponsored",
            r"advertis",
            r"newsletter",
            r"about",
            r"membership",
            r"courses",
            r"privacy",
            r"contact",
            r"podcast",
            r"explore",
            r"continue reading$",
            r"see older articles",
            r"articles by category",
            r"farnam street articles",
            r"accelerated learning",
            r"mental models$",
            r"decision making$",
            r"reading better",
            r"self improvement",
        ],
    },

    # ==========================================================
    # 5. Smithsonian Magazine
    #
    # 方向：
    # 历史 / 科学 / 文化 / 社会
    #
    # 正文通常位于：
    # /history/...
    # /science-nature/...
    # /arts-culture/...
    # /smart-news/...
    # ==========================================================
    "smithsonian": {
        "list_urls": [
            "https://www.smithsonianmag.com/",
            "https://www.smithsonianmag.com/history/",
            "https://www.smithsonianmag.com/science-nature/",
            "https://www.smithsonianmag.com/arts-culture/",
        ],

        "include_paths": [
            (
                r"^/"
                r"(history|science-nature|arts-culture|"
                r"smart-news|innovation|travel)"
                r"/[^/]+/?$"
            ),
        ],

        "exclude_paths": [
            r"^/about",
            r"^/contact",
            r"^/subscribe",
            r"^/privacy",
            r"^/terms",
            r"^/search",
            r"^/author/",
            r"^/tag/",
        ],

        "exclude_titles": [
            r"subscribe",
            r"newsletter",
            r"about",
            r"contact",
            r"privacy",
            r"terms",
            r"search",
            r"shop",
            r"magazine",
            r"latest",
            r"most popular",
            r"see all",
        ],
    },

    # ==========================================================
    # 6. Nautilus
    #
    # 方向：
    # 科学 / 哲学 / 心理 / 社会
    #
    # 正文 URL 通常：
    # /article-title-123456/
    # ==========================================================
    "nautilus": {
        "list_urls": [
            "https://nautil.us/all",
            "https://nautil.us/",
        ],

        "include_paths": [
            r"^/[a-z0-9][a-z0-9\-]*-\d+/?$",
        ],

        "exclude_paths": [
            r"^/$",
            r"^/all/?$",
            r"^/category/",
            r"^/author/",
            r"^/tag/",
            r"^/about",
            r"^/contact",
            r"^/membership",
            r"^/newsletter",
            r"^/podcast",
        ],

        "exclude_titles": [
            r"subscribe",
            r"newsletter",
            r"membership",
            r"about",
            r"contact",
            r"privacy",
            r"terms",
            r"podcast",
            r"view all",
            r"more stories",
        ],
    },

    # ==========================================================
    # 7. Greater Good
    #
    # UC Berkeley Greater Good Science Center
    #
    # 方向：
    # 心理 / 自我 / 社会观察 / 人际关系
    #
    # 正文：
    # /article/item/article-slug
    # ==========================================================
    "greater-good": {
        "list_urls": [
            "https://greatergood.berkeley.edu/article",
            "https://greatergood.berkeley.edu/",
        ],

        "include_paths": [
            r"^/article/item/[^/]+/?$",
        ],

        "exclude_paths": [
            r"^/article/?$",
            r"^/about",
            r"^/contact",
            r"^/events",
            r"^/profile/",
            r"^/topic/",
            r"^/privacy",
            r"^/terms",
        ],

        "exclude_titles": [
            r"newsletter",
            r"subscribe",
            r"about",
            r"contact",
            r"privacy",
            r"terms",
            r"events",
            r"podcast",
            r"courses",
            r"see all",
            r"more",
        ],
    },

    # ==========================================================
    # 8. Longreads
    #
    # 方向：
    # 长篇报道 / 随笔 / 深度文章
    #
    # 正文：
    # /YYYY/MM/DD/article-slug/
    # ==========================================================
    "longreads": {
        "list_urls": [
            "https://longreads.com/picks/",
            "https://longreads.com/",
        ],

        "include_paths": [
            r"^/\d{4}/\d{2}/\d{2}/[^/]+/?$",
        ],

        "exclude_paths": [
            r"^/picks/?$",
            r"^/category/",
            r"^/tag/",
            r"^/author/",
            r"^/about",
            r"^/contact",
            r"^/membership",
            r"^/newsletter",
            r"^/support",
        ],

        "exclude_titles": [
            r"newsletter",
            r"subscribe",
            r"about",
            r"support",
            r"membership",
            r"contact",
            r"privacy",
            r"terms",
            r"more features",
            r"weekly top 5",
            r"editors.? picks",
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
        self.max_items_per_source = (
            max_items_per_source
        )

    # ==========================================================
    # 网络
    # ==========================================================

    def _get_proxies(self):
        if not self.proxy_url:
            return None

        return {
            "http": self.proxy_url,
            "https": self.proxy_url,
        }

    # ==========================================================
    # URL 工具
    # ==========================================================

    @staticmethod
    def _domain_allowed(
        url: str,
        expected_domain: str,
    ) -> bool:
        try:
            parsed = urlparse(url)

            if parsed.scheme not in (
                "http",
                "https",
            ):
                return False

            host = (
                parsed.hostname
                or ""
            ).lower()

            expected = (
                expected_domain
                .lower()
                .strip()
            )

            return (
                host == expected
                or host.endswith(
                    "." + expected
                )
            )

        except Exception:
            return False

    @staticmethod
    def _normalize_url(
        url: str,
    ) -> str:
        try:
            parsed = urlparse(url)

            normalized = (
                parsed._replace(
                    fragment="",
                )
            )

            return urlunparse(
                normalized
            )

        except Exception:
            return url

    @staticmethod
    def _path_matches(
        path: str,
        patterns: List[str],
    ) -> bool:
        if not patterns:
            return True

        return any(
            re.search(
                pattern,
                path,
                flags=re.IGNORECASE,
            )
            for pattern in patterns
        )

    @staticmethod
    def _path_excluded(
        path: str,
        patterns: List[str],
    ) -> bool:
        if not patterns:
            return False

        return any(
            re.search(
                pattern,
                path,
                flags=re.IGNORECASE,
            )
            for pattern in patterns
        )

    @staticmethod
    def _title_excluded(
        title: str,
        patterns: List[str],
    ) -> bool:
        if not patterns:
            return False

        return any(
            re.search(
                pattern,
                title,
                flags=re.IGNORECASE,
            )
            for pattern in patterns
        )

    # ==========================================================
    # 标题处理
    # ==========================================================

    @staticmethod
    def _clean_title(
        title: str,
    ) -> str:
        title = unescape(
            str(title)
        )

        title = re.sub(
            r"\s+",
            " ",
            title,
        ).strip()

        # 去除部分站点常见的尾部网站名
        title = re.sub(
            (
                r"\s*[-|–—]\s*"
                r"(NOEMA|Noema Magazine|"
                r"Farnam Street|"
                r"JSTOR Daily|"
                r"Smithsonian Magazine|"
                r"Nautilus|"
                r"Greater Good|"
                r"Longreads)"
                r"\s*$"
            ),
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

        return title

    @staticmethod
    def _title_looks_valid(
        title: str,
    ) -> bool:
        if not title:
            return False

        # 太短通常是导航菜单
        if len(title) < 6:
            return False

        # 太长通常抓到了整段摘要
        if len(title) > 180:
            return False

        # 必须至少包含字母或中文
        if not re.search(
            r"[A-Za-z\u4e00-\u9fff]",
            title,
        ):
            return False

        return True

    # ==========================================================
    # 获取网页
    # ==========================================================

    def _fetch_page(
        self,
        url: str,
    ) -> Tuple[
        Optional[str],
        Optional[str],
    ]:
        try:
            response = requests.get(
                url,
                headers=DEFAULT_HEADERS,
                proxies=self._get_proxies(),
                timeout=self.timeout,
                allow_redirects=True,
            )

            response.raise_for_status()

            if not response.encoding:
                response.encoding = (
                    response.apparent_encoding
                    or "utf-8"
                )

            return (
                response.text,
                None,
            )

        except Exception as e:
            return (
                None,
                str(e),
            )

    # ==========================================================
    # 抓取单个来源
    # ==========================================================

    def fetch_source(
        self,
        source: Dict,
    ) -> Tuple[
        Optional[Dict],
        Optional[str],
    ]:

        source_id = (
            source.get(
                "id",
                "",
            )
            .strip()
        )

        name = source.get(
            "name",
            source_id,
        )

        configured_url = (
            source.get(
                "url",
                "",
            )
            .strip()
        )

        expected_domain = (
            source.get(
                "expected_domain",
                "",
            )
            .strip()
        )

        if (
            not source_id
            or not configured_url
        ):
            return (
                None,
                "缺少 id 或 url",
            )

        rule = SOURCE_RULES.get(
            source_id,
            {},
        )

        include_paths = source.get(
            "include_paths",
            rule.get(
                "include_paths",
                [],
            ),
        )

        exclude_paths = source.get(
            "exclude_paths",
            rule.get(
                "exclude_paths",
                [],
            ),
        )

        exclude_titles = source.get(
            "exclude_titles",
            rule.get(
                "exclude_titles",
                [],
            ),
        )

        max_items = int(
            source.get(
                "max_items",
                self.max_items_per_source,
            )
        )

        # ======================================================
        # 列表页
        #
        # config.yaml 中配置的 URL 优先；
        # SOURCE_RULES 可以追加 fallback。
        # ======================================================

        configured_list_urls = (
            source.get(
                "list_urls"
            )
        )

        if configured_list_urls:
            list_urls = list(
                configured_list_urls
            )

        else:
            list_urls = [
                configured_url
            ]

            for fallback_url in (
                rule.get(
                    "list_urls",
                    [],
                )
            ):
                if (
                    fallback_url
                    not in list_urls
                ):
                    list_urls.append(
                        fallback_url
                    )

        # ======================================================
        # 抓取
        # ======================================================

        result = {}

        seen_urls = set()
        seen_titles = set()

        errors = []

        rank = 1

        for list_url in list_urls:

            if (
                len(result)
                >= max_items
            ):
                break

            html, error = (
                self._fetch_page(
                    list_url
                )
            )

            if error:
                errors.append(
                    f"{list_url}: {error}"
                )
                continue

            if not html:
                continue

            parser = AnchorParser()

            try:
                parser.feed(html)

            except Exception as e:
                errors.append(
                    (
                        f"{list_url}: "
                        f"HTML解析失败: {e}"
                    )
                )
                continue

            for item in parser.links:

                if (
                    len(result)
                    >= max_items
                ):
                    break

                raw_href = (
                    item.get(
                        "href",
                        "",
                    )
                    .strip()
                )

                title = (
                    self._clean_title(
                        item.get(
                            "title",
                            "",
                        )
                    )
                )

                # ----------------------------------------------
                # 标题检查
                # ----------------------------------------------

                if not self._title_looks_valid(
                    title
                ):
                    continue

                if self._title_excluded(
                    title,
                    exclude_titles,
                ):
                    continue

                # ----------------------------------------------
                # href 检查
                # ----------------------------------------------

                raw_href_lower = (
                    raw_href.lower()
                )

                if raw_href_lower.startswith(
                    (
                        "#",
                        "javascript:",
                        "mailto:",
                        "tel:",
                        "data:",
                    )
                ):
                    continue

                article_url = urljoin(
                    list_url,
                    raw_href,
                )

                article_url = (
                    self._normalize_url(
                        article_url
                    )
                )

                try:
                    parsed = urlparse(
                        article_url
                    )

                except Exception:
                    continue

                if parsed.scheme not in (
                    "http",
                    "https",
                ):
                    continue

                # ----------------------------------------------
                # 域名验证
                # ----------------------------------------------

                if expected_domain:
                    if not self._domain_allowed(
                        article_url,
                        expected_domain,
                    ):
                        continue

                # ----------------------------------------------
                # 路径验证
                # ----------------------------------------------

                path = (
                    parsed.path
                    or "/"
                )

                if self._path_excluded(
                    path,
                    exclude_paths,
                ):
                    continue

                if not self._path_matches(
                    path,
                    include_paths,
                ):
                    continue

                # ----------------------------------------------
                # 去重
                # ----------------------------------------------

                normalized_title = (
                    title.lower()
                )

                if (
                    article_url
                    in seen_urls
                ):
                    continue

                if (
                    normalized_title
                    in seen_titles
                ):
                    continue

                seen_urls.add(
                    article_url
                )

                seen_titles.add(
                    normalized_title
                )

                # ----------------------------------------------
                # TrendRadar 标准数据结构
                # ----------------------------------------------

                result[title] = {
                    "ranks": [
                        rank
                    ],
                    "url": (
                        article_url
                    ),
                    "mobileUrl": "",
                }

                rank += 1

        # ======================================================
        # 最终检查
        # ======================================================

        if not result:

            error_detail = ""

            if errors:
                error_detail = (
                    "；".join(
                        errors[:3]
                    )
                )

            if error_detail:
                return (
                    None,
                    (
                        f"{name} 未解析到有效文章；"
                        f"{error_detail}"
                    ),
                )

            return (
                None,
                (
                    f"{name} "
                    "未解析到有效文章"
                ),
            )

        print(
            (
                f"[自定义源] "
                f"{name} 获取成功，"
                f"共 {len(result)} 条"
            )
        )

        return (
            result,
            None,
        )

    # ==========================================================
    # 批量抓取
    # ==========================================================

    def crawl_sources(
        self,
        sources: List[Dict],
    ) -> Tuple[
        Dict,
        Dict,
        List,
    ]:

        results = {}
        id_to_name = {}
        failed_ids = []

        for source in sources:

            if not source.get(
                "enabled",
                True,
            ):
                continue

            source_id = (
                source.get(
                    "id",
                    "",
                )
                .strip()
            )

            name = source.get(
                "name",
                source_id,
            )

            if not source_id:
                continue

            id_to_name[
                source_id
            ] = name

            data, error = (
                self.fetch_source(
                    source
                )
            )

            if data:

                results[
                    source_id
                ] = data

            else:

                failed_ids.append(
                    source_id
                )

                print(
                    (
                        f"[自定义源] "
                        f"{name} 获取失败: "
                        f"{error}"
                    )
                )

        return (
            results,
            id_to_name,
            failed_ids,
        )
