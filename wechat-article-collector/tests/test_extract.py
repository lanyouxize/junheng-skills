#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract.py 单元测试：图文/视频/坏页三态 + JS 变量与 data-src 解析。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from extract import extract_article, _clean_text  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEXT_URL = "https://mp.weixin.qq.com/s/AbCdEf123?scene=1&src=11"
VIDEO_URL = "https://mp.weixin.qq.com/s/ViDeO999"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestExtractTextArticle(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fields = extract_article(_load("article_text.html"), TEXT_URL)

    def test_title_from_og_meta(self) -> None:
        self.assertEqual(self.fields["title"], "猫咪排毛攻略：膳食纤维的科学运用")

    def test_account_and_author(self) -> None:
        self.assertEqual(self.fields["account"], "宠 ingredients 研究所")
        self.assertEqual(self.fields["author"], "澜宥汐泽")

    def test_publish_time_epoch_to_utc_iso(self) -> None:
        # fixture ct=1729593600 -> 2024-10-22T10:40:00Z（UTC）
        self.assertEqual(self.fields["publish_time"], "2024-10-22T10:40:00Z")

    def test_biz_extracted(self) -> None:
        self.assertEqual(self.fields["account_id"], "MzA4MjM0NTAxNg==")

    def test_digest(self) -> None:
        self.assertIn("化毛膏", self.fields["digest"])

    def test_body_html_and_text(self) -> None:
        self.assertIn("甜菜粕", self.fields["body_html"])
        self.assertIn("甜菜粕", self.fields["body_text"])

    def test_word_count_mixed_cjk_latin(self) -> None:
        self.assertGreater(self.fields["word_count"], 50)

    def test_images_data_src_only_and_cdn_filtered(self) -> None:
        urls = [img["url"] for img in self.fields["images"]]
        self.assertEqual(len(urls), 3)
        self.assertTrue(all(url.startswith("https://mmbiz.qpic.cn/") for url in urls))
        self.assertNotIn("https://stats.example.com/pixel.gif?t=1", urls)
        self.assertIn("https://mmbiz.qpic.cn/mmbiz_png/img001/640?wx_fmt=png", urls)

    def test_protocol_relative_src_resolved(self) -> None:
        urls = [img["url"] for img in self.fields["images"]]
        self.assertIn("https://mmbiz.qpic.cn/mmbiz_jpg/img002/640?wx_fmt=jpeg", urls)

    def test_cover(self) -> None:
        self.assertEqual(self.fields["cover"], "https://mmbiz.qpic.cn/mmbiz_jpg/abc123/640?wx_fmt=jpeg")

    def test_media_type_text(self) -> None:
        self.assertEqual(self.fields["media_type"], "text")
        self.assertEqual(self.fields["video_url"], "")


class TestExtractVideoArticle(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fields = extract_article(_load("article_video.html"), VIDEO_URL)

    def test_media_type_video_meta(self) -> None:
        self.assertEqual(self.fields["media_type"], "video-meta")

    def test_video_url_from_iframe_data_src(self) -> None:
        self.assertIn("v.qq.com", self.fields["video_url"])

    def test_author_optional_missing(self) -> None:
        self.assertEqual(self.fields["author"], "")


class TestExtractBrokenPage(unittest.TestCase):
    def test_missing_js_content_yields_empty_body(self) -> None:
        fields = extract_article(_load("article_broken.html"), TEXT_URL)
        self.assertEqual(fields["body_html"], "")
        self.assertEqual(fields["body_text"], "")
        self.assertEqual(fields["word_count"], 0)


class TestExtractReal2026Layout(unittest.TestCase):
    """2026 版真实页面回归：JS 变量已是表达式，不再是纯字面量。

    fixture 取自 2026-10-22 实测抓取（`article_real_1022.html`，已裁剪 <style>/<link>
    与无关 <script>，正文与变量声明原样保留）。四个字段曾全部取错：
    account_id 尾巴带 `" || "`、author 被写成发布时间、publish_time 空、digest 是
    `htmlDecode("")` 未求值。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.fields = extract_article(
            _load("article_real_1022.html"),
            "https://mp.weixin.qq.com/s/020L1QcxymelCEiYnHl4kQ",
        )

    def test_biz_or_fallback_chain_takes_first_literal(self) -> None:
        # 页面写法：var biz = "MzkwNzgyNDk1Nw==" || "";
        self.assertEqual(self.fields["account_id"], "MzkwNzgyNDk1Nw==")

    def test_nickname_wrapped_in_htmldecode(self) -> None:
        # 页面写法：var nickname = htmlDecode("浙江农林大学宠物科学研究所");
        self.assertEqual(self.fields["account"], "浙江农林大学宠物科学研究所")

    def test_title_strips_html_false_chain(self) -> None:
        # 页面写法：var msg_title = '...'.html(false);
        self.assertEqual(self.fields["title"], "犬的脂肪酸需求：幼犬、成犬与老犬的差异解析")

    def test_publish_time_from_create_time_not_minified_ct(self) -> None:
        # create_time = "1792666226" * 1；ct 已被压缩代码污染，不可用。
        # 1792666226 = 2026-10-22T10:50:26Z（页面显示 18:50，+08:00）
        self.assertEqual(self.fields["publish_time"], "2026-10-22T10:50:26Z")

    def test_author_empty_and_not_the_publish_date(self) -> None:
        # 该文无作者；旧兜底会把 .rich_media_meta_text 的发布时间当作者写入
        self.assertEqual(self.fields["author"], "")

    def test_digest_empty_after_htmldecode_unwrap(self) -> None:
        # 页面写法：var msg_desc = htmlDecode("");
        self.assertEqual(self.fields["digest"], "")

    def test_body_and_images_survive_trimming(self) -> None:
        self.assertIn("脂肪酸", self.fields["body_text"])
        self.assertGreater(self.fields["word_count"], 1000)
        self.assertEqual(len(self.fields["images"]), 9)
        self.assertEqual(self.fields["media_type"], "text")


class TestCleanText(unittest.TestCase):
    """_clean_text 解码微信自有转义并剥离残留标签。"""

    def test_strips_topic_link_escaped_html(self) -> None:
        # 真实 url2 的 digest：微信字面转义 \\x26 即 &，topic-link 转义 HTML 包裹 #主题
        raw = (
            r"\x26lt;a class=\x26quot;wx_topic_link\x26quot; "
            r"href=\x26quot;https://mp.weixin.qq.com/...\x26quot;\x26gt;"
            r"#主题\x26lt;/a\x26gt;加速脂肪氧化"
        )
        out = _clean_text(raw)
        self.assertNotIn("wx_topic_link", out)
        self.assertNotIn("#主题", out)
        self.assertNotIn("<", out)
        self.assertNotIn(">", out)
        self.assertEqual(out, "加速脂肪氧化")

    def test_preserves_normal_digest(self) -> None:
        self.assertEqual(_clean_text("正常摘要，无转义标签。"), "正常摘要，无转义标签。")

    def test_unescape_entities(self) -> None:
        # 经 \\x26 -> & 后 unescape：&amp; -> &，&lt; -> < 再被去标签清掉
        self.assertEqual(_clean_text(r"\x26amp;"), "&")

    def test_empty_input(self) -> None:
        self.assertEqual(_clean_text(""), "")
        self.assertEqual(_clean_text(None), "")  # type: ignore[arg-type]

    def test_collapses_whitespace(self) -> None:
        self.assertEqual(_clean_text("  a   b  \n c "), "a b c")


class TestExtractAuthorProvinceLayout(unittest.TestCase):
    """2026 版真实页面回归：.rich_media_meta_text 首项为省份定位，不得污染 author。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fields = extract_article(
            _load("article_author_province.html"),
            "https://mp.weixin.qq.com/s/ProvinceFixture",
        )

    def test_author_not_polluted_by_province(self) -> None:
        # 首项"湖南"是省份定位、次项"10月21日"是发布时间，author 必须为空
        self.assertEqual(self.fields["author"], "")

    def test_digest_untouched(self) -> None:
        self.assertEqual(self.fields["digest"], "这是一条正常摘要，不含转义标签。")

    def test_title_survives_clean(self) -> None:
        self.assertEqual(self.fields["title"], "省份定位污染作者列回归 fixture")


if __name__ == "__main__":
    unittest.main()
