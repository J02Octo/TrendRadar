# coding=utf-8
"""
TrendRadar 自定义网页数据源

用途：
- 直接抓取指定网页中的文章标题和链接
- 不使用 RSS
- 返回与 NewsNow 平台相同的 results 数据结构
- 当前主要用于“阅读与思想”分类

设计原则：
1. 每个网站使用独立的文章 URL 规则；
2. 尽量只保留真正的文章正文页；
3. 排除栏目页、作者页、订阅页、隐私页等导航内容；
4. 支持一个来源配置多个候选列表页；
5. 抓取结果继续兼容 TrendRadar 原有 NewsNow 数据结构。
"""

import re
from html.parser import HTMLParser
from html import unescape
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
    """
    提取网页中的链接。

    相比原版本增加：
    - a 标签内部 img 的 alt/title；
    - 嵌套标签文本；
    - 更适合卡片式新闻网站。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.links: List[Dict] = []

        self._current_href: Optional[str] = None
        self._current_title: Optional[str] = None
        self._current_text: List[str] = []
        self._anchor_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_dict = dict(attrs)

        if tag == "a":
            href = attr_dict.get("href")

            if not href:
                return

            self._current_href = href
            self._current_title = (
                attr_dict.get("title")
                or attr_dict.get("aria-label")
            )
            self._current_text = []
            self._anchor_depth = 1

            return

        if self._current_href is not None:
            self._anchor_depth += 1

            # 很多文章列表的 a 标签本身没有文字，
            # 标题可能只存在图片 alt / title 中。
            if tag == "img":
                image_text = (
                    attr_dict.get("alt")
                    or attr_dict.get("title")
                )

                if image_text:
                    self._current_text.append(
                        image_text
                    )

    def handle_data(self, data):
        if self._current_href is not None:
            text = data.strip()

            if text:
                self._current_text.append(text)

    def handle_endtag(self, tag):
        if self._current_href is None:
            return

        self._anchor_depth -= 1

        if tag.lower() != "a":
            return

        text = " ".join(self._current_text)

        text = re.sub(
            r"\s+",
            " ",
            unescape(text),
        ).strip()

        title = (
            self._current_title
            or text
        )

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
        self._anchor_depth = 0


# ==============================================================
# 各来源独立规则
# ==============================================================

SOURCE_RULES = {

    # ==========================================================
    # 三联生活周刊
    #
    # 当前正文格式：
    # https://www.lifeweek.com.cn/article/273664
    #
    # 首页部分内容可能由前端动态加载，
    # 因此增加 articleList / column 作为 fallback。
    # ==========================================================
    "lifeweek-reading": {

        "list_urls": [
            "https://www.lifeweek.com.cn/",
            (
                "https://www.lifeweek.com.cn/"
                "articleList?tag=三联生活周刊"
            ),
            "https://www.lifeweek.com.cn/column",
        ],

        "include_paths": [
            r"^/article/\d+/?$",
        ],

        "exclude_paths": [
            r"^/articleList",
            r"^/column",
            r"^/magazine",
            r"^/news",
            r"^/search",
            r"^/user",
        ],

        "exclude_titles": [
            r"^首页$",
            r"登录",
            r"注册",
            r"订阅",
            r"查看更多",
            r"查看本期",
            r"购买纸刊",
            r"购买数字刊",
            r"三联生活周刊app",
            r"用户协议",
            r"隐私政策",
            r"商务合作",
            r"关于我们",
            r"加入我们",
            r"投稿",
        ],
    },

    # ==========================================================
    # 单读 / 单向空间
    # ==========================================================
    "owspace": {

        "list_urls": [
            "https://www.owspace.com/read.html",
        ],

        "include_paths": [
            r"/index\.php",
            r"\.html$",
        ],

        "exclude_paths": [
            r"/about",
            r"/activity",
            r"/shop",
            r"/login",
            r"/register",
        ],

        "exclude_titles": [
            r"^首页$",
            r"活动",
            r"商店",
            r"关于",
            r"登录",
            r"注册",
            r"更多",
            r"联系我们",
            r"隐私",
        ],
    },

    # ==========================================================
    # Aeon
    #
    # 正文：
    # /essays/article-slug
    # ==========================================================
    "aeon": {

        "list_urls": [
            "https://aeon.co/essays",
        ],

        "include_paths": [
            r"^/essays/[^/]+/?$",
        ],

        "exclude_paths": [
            r"^/essays/?$",
            r"^/videos",
            r"^/about",
            r"^/contact",
        ],

        "exclude_titles": [
            r"newsletter",
            r"subscribe",
            r"about",
            r"privacy",
            r"terms",
            r"contact",
            r"popular",
            r"latest",
        ],
    },

    # ==========================================================
    # Works in Progress
    #
    # 正文：
    # /issue/article-slug/
    #
    # Issue 汇总页：
    # /issue-25/
    #
    # 二者必须区分。
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
    # Noema
    #
    # 正文：
    # /how-ai-will-change-us/
    #
    # 同时网站还有：
    # /author/...
    # /article-type/...
    # /article-topic/...
    #
    # 必须过滤。
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
    # Farnam Street
    #
    # 首页更多是品牌导航；
    # /blog/ 才是文章索引。
    #
    # 文章正文通常为：
    # /article-slug/
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
        ],

        "exclude_titles": [
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
        """
        验证链接是否属于允许域名。

        支持：
        example.com
        www.example.com
        sub.example.com
        """

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
        """
        规范化文章 URL：

        - 去掉 fragment；
        - 保留 query；
        - 避免同一文章因为 #xxx 重复。
        """

        try:
            parsed = urlparse(url)

            normalized = parsed._replace(
                fragment="",
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
        """
        清理标题中的多余空格、HTML 字符等。
        """

        title = unescape(
            str(title)
        )

        title = re.sub(
            r"\s+",
            " ",
            title,
        ).strip()

        # 去掉部分网站常见的尾部站名
        title = re.sub(
            (
                r"\s*[-|–—]\s*"
                r"(NOEMA|Noema Magazine|"
                r"Farnam Street|"
                r"三联生活网)"
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
        """
        基础标题质量检查。
        """

        if not title:
            return False

        # 太短通常是菜单
        if len(title) < 6:
            return False

        # 太长通常是整段摘要被抓成 title
        if len(title) > 180:
            return False

        # 纯数字 / 标点
        if not re.search(
            r"[A-Za-z\u4e00-\u9fff]",
            title,
        ):
            return False

        return True

    # ==========================================================
    # 获取列表页
    # ==========================================================

    def _fetch_page(
        self,
        url: str,
    ) -> Tuple[
        Optional[str],
        Optional[str],
    ]:
        """
        下载单个列表页。

        Returns:
            html, error
        """

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

            return response.text, None

        except Exception as e:
            return None, str(e)

    # ==========================================================
    # 获取单个来源
    # ==========================================================

    def fetch_source(
        self,
        source: Dict,
    ) -> Tuple[
        Optional[Dict],
        Optional[str],
    ]:
        """
        抓取单个网页源。

        Returns:
            (结果, 错误)
        """

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
        # config.yaml 中 URL 始终优先；
        # SOURCE_RULES 可追加 fallback。
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

            if len(result) >= max_items:
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

                if len(result) >= max_items:
                    break

                raw_href = (
                    item.get(
                        "href",
                        "",
                    )
                    .strip()
                )

                title = self._clean_title(
                    item.get(
                        "title",
                        "",
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

        return result, None

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
        """
        批量抓取自定义网页源。

        Returns:
            results,
            id_to_name,
            failed_ids
        """

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
