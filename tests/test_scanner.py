import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "can-i-delete-this" / "scripts"))
import scanner


class TestMarkerFor(unittest.TestCase):

    def test_known_extensions(self):
        self.assertEqual(scanner.marker_for("a/b/Foo.kt"), "//")
        self.assertEqual(scanner.marker_for("a/b/foo.py"), "#")
        self.assertEqual(scanner.marker_for("a/b/foo.ex"), "#")
        self.assertEqual(scanner.marker_for("a/b/foo.sql"), "--")

    def test_unsupported_extension_is_none(self):
        """미지원 언어를 추측하지 않는다. 몇 개를 건너뛰었는지 세는 것은 scan.py의 일이다."""
        self.assertIsNone(scanner.marker_for("a/b/foo.rst"))
        self.assertIsNone(scanner.marker_for("a/b/Makefile"))
        self.assertIsNone(scanner.marker_for("noextension"))


class TestFindBlocks(unittest.TestCase):

    def test_three_code_shaped_comment_lines_are_a_block(self):
        text = (
            "fun live() {\n"
            "    return 1\n"
            "}\n"
            "// fun dead(order: Order) {\n"
            "//     order.charge()\n"
            "//     return null\n"
            "// }\n"
        )
        blocks = scanner.find_blocks(text, "//")
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0].start, blocks[0].end), (4, 7))
        self.assertEqual(blocks[0].lines, 4)
        self.assertEqual(blocks[0].code_lines, 4)

    def test_two_lines_is_below_the_floor(self):
        text = "// x = compute()\n// return x\n"
        self.assertEqual(scanner.find_blocks(text, "//"), [])

    def test_a_todo_line_splits_a_run_into_two_blocks(self):
        """TODO를 버리고 이어붙이지 않는다. 앞뒤는 서로 다른 덩어리다."""
        text = (
            "// a = one()\n"
            "// b = two()\n"
            "// c = three()\n"
            "// TODO: revisit this\n"
            "// d = four()\n"
            "// e = five()\n"
            "// f = six()\n"
        )
        blocks = scanner.find_blocks(text, "//")
        self.assertEqual(len(blocks), 2)
        self.assertEqual((blocks[0].start, blocks[0].end), (1, 3))
        self.assertEqual((blocks[1].start, blocks[1].end), (5, 7))

    def test_license_header_is_not_a_block(self):
        text = (
            "# Copyright 2020 Example Inc.\n"
            "# SPDX-License-Identifier: MIT\n"
            "# Licensed under the terms above.\n"
            "# See https://example.com/license for details.\n"
        )
        self.assertEqual(scanner.find_blocks(text, "#"), [])

    def test_prose_comments_are_not_a_block(self):
        text = (
            "# This function is intentionally conservative because the\n"
            "# upstream service has been flaky since the migration and we\n"
            "# would rather retry than lose a message in transit.\n"
            "# Ask the platform team before changing any of this.\n"
        )
        self.assertEqual(scanner.find_blocks(text, "#"), [])

    def test_annotation_only_comments_are_not_a_block(self):
        text = "// @Suppress(\"unused\")\n// @Inject\n// @VisibleForTesting\n"
        self.assertEqual(scanner.find_blocks(text, "//"), [])

    def test_url_only_comments_are_not_a_block(self):
        text = (
            "# https://example.com/a?x=1\n"
            "# https://example.com/b?y=2\n"
            "# www.example.com/c\n"
        )
        self.assertEqual(scanner.find_blocks(text, "#"), [])

    def test_ratio_floor_rejects_a_mostly_prose_run(self):
        """코드 3줄 + 산문 2줄 = 0.6, 문턱 0.7 미달."""
        text = (
            "// x = one()\n"
            "// y = two()\n"
            "// z = three()\n"
            "// we kept this around while the migration was in flight\n"
            "// and nobody has looked at it since then honestly\n"
        )
        # The marker here is "//", so a "#" run over the same text finds
        # nothing whatever the ratio does; only this assertion tests the gate.
        self.assertEqual(scanner.find_blocks(text, "//"), [])

    def test_ratio_floor_accepts_a_mostly_code_run(self):
        """코드 4줄 + 산문 1줄 = 0.8, 문턱 통과."""
        text = (
            "// x = one()\n"
            "// y = two()\n"
            "// z = three()\n"
            "// w = four()\n"
            "// disabled during the incident\n"
        )
        blocks = scanner.find_blocks(text, "//")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].code_lines, 4)

    def test_blank_comment_lines_cannot_carry_a_run_past_the_count_gate(self):
        """세 관문 중 가운데(코드처럼 보이는 줄이 min_lines 이상)만이 이 런을
        떨어뜨린다. 런 길이는 5줄이라 길이 관문을 넘고, 빈 주석 줄은 분모에서
        빠지니 비율은 2/2 = 1.0으로 비율 관문도 넘는다. 코드 줄이 2개뿐이라
        가운데 관문에서 떨어진다. 이 관문을 지우면 블록이 하나 생긴다."""
        text = (
            "// x = one()\n"
            "//\n"
            "//\n"
            "//\n"
            "// y = two()\n"
        )
        self.assertEqual(scanner.find_blocks(text, "//"), [])

    def test_the_count_gate_is_the_sole_rejector_of_that_run(self):
        """위 테스트가 실제로 가운데 관문을 겨냥하고 있는지 전제를 직접 확인한다.
        길이·비율 관문은 통과해야 한다."""
        run = [(1, " x = one()"), (2, ""), (3, ""), (4, ""), (5, " y = two()")]
        self.assertGreaterEqual(len(run), scanner.MIN_BLOCK_LINES)
        content = [t for _, t in run if t.strip()]
        code = [t for t in content if scanner.looks_like_code(t)]
        self.assertEqual(len(code), len(content))
        self.assertGreaterEqual(len(code), len(content) * scanner.CODE_SHAPE_RATIO)
        self.assertLess(len(code), scanner.MIN_BLOCK_LINES)

    def test_blank_comment_lines_do_not_count_against_the_ratio(self):
        """주석 처리된 코드 안의 빈 줄은 산문이 아니다. 비율 분모에서 제외한다."""
        text = (
            "// fun dead() {\n"
            "//\n"
            "//     return compute()\n"
            "//\n"
            "// }\n"
        )
        blocks = scanner.find_blocks(text, "//")
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0].start, blocks[0].end), (1, 5))
        self.assertEqual(blocks[0].lines, 5)
        self.assertEqual(blocks[0].code_lines, 3)

    def test_a_non_comment_line_ends_a_run(self):
        text = (
            "// a = one()\n"
            "// b = two()\n"
            "// c = three()\n"
            "real = code()\n"
            "// d = four()\n"
            "// e = five()\n"
        )
        blocks = scanner.find_blocks(text, "//")
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0].start, blocks[0].end), (1, 3))

    def test_python_and_sql_markers(self):
        py = "# a = one()\n# b = two()\n# c = three()\n"
        self.assertEqual(len(scanner.find_blocks(py, "#")), 1)
        sql = "-- select a from t;\n-- where b = 1;\n-- order by c;\n"
        self.assertEqual(len(scanner.find_blocks(sql, "--")), 1)

    def test_indented_comments_are_found(self):
        text = (
            "class Foo {\n"
            "    // fun dead(o: Order) {\n"
            "    //     o.charge()\n"
            "    // }\n"
            "}\n"
        )
        blocks = scanner.find_blocks(text, "//")
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0].start, blocks[0].end), (2, 4))

    def test_no_comments_at_all(self):
        self.assertEqual(scanner.find_blocks("x = 1\ny = 2\n", "//"), [])

    def test_empty_text(self):
        self.assertEqual(scanner.find_blocks("", "//"), [])


class TestLooksLikeCode(unittest.TestCase):

    def test_call_shape(self):
        self.assertTrue(scanner.looks_like_code(" order.charge()"))

    def test_punctuation_shape(self):
        self.assertTrue(scanner.looks_like_code(" x = 1"))
        self.assertTrue(scanner.looks_like_code(" }"))

    def test_keyword_shape(self):
        self.assertTrue(scanner.looks_like_code(" return null"))
        self.assertTrue(scanner.looks_like_code(" val x"))

    def test_prose_is_not_code(self):
        self.assertFalse(scanner.looks_like_code(" we kept this for later"))
        self.assertFalse(scanner.looks_like_code(""))


class TestExcerpt(unittest.TestCase):

    def test_block_carries_the_first_two_nonblank_lines(self):
        text = (
            "// fun dead(o: Order) {\n"
            "//\n"
            "//     o.charge()\n"
            "//     return null\n"
            "// }\n"
        )
        block = scanner.find_blocks(text, "//")[0]
        self.assertEqual(block.excerpt,
                          ("fun dead(o: Order) {", "o.charge()"))

    def test_excerpt_skips_blank_comment_lines(self):
        text = "//\n// x = one()\n// y = two()\n// z = three()\n"
        block = scanner.find_blocks(text, "//")[0]
        self.assertEqual(block.excerpt, ("x = one()", "y = two()"))

    def test_excerpt_lines_are_cut_at_the_character_limit(self):
        long_line = "x = " + "a" * 400
        text = "// {}\n// y = two()\n// z = three()\n".format(long_line)
        block = scanner.find_blocks(text, "//")[0]
        self.assertEqual(len(block.excerpt[0]), scanner.EXCERPT_MAX_CHARS)
        self.assertTrue(block.excerpt[0].startswith("x = aaa"))

    def test_excerpt_is_text_from_the_file_not_a_summary(self):
        """발췌는 파일에 실제로 있는 텍스트여야 한다."""
        text = "// alpha = 1\n// beta = 2\n// gamma = 3\n"
        block = scanner.find_blocks(text, "//")[0]
        for line in block.excerpt:
            self.assertIn(line, text)


class TestBlockMarkers(unittest.TestCase):

    def test_c_family_has_block_markers(self):
        self.assertEqual(scanner.block_markers_for("a/Foo.kt"), ("/*", "*/"))
        self.assertEqual(scanner.block_markers_for("a/foo.ts"), ("/*", "*/"))

    def test_languages_without_block_comments_have_none(self):
        for path in ("a/foo.py", "a/foo.ex", "a/foo.rb", "a/foo.sh",
                      "a/foo.yml"):
            self.assertIsNone(scanner.block_markers_for(path), path)

    def test_unsupported_extension_has_none(self):
        self.assertIsNone(scanner.block_markers_for("a/foo.rst"))


class TestBlockComments(unittest.TestCase):

    BLOCK = ("/*", "*/")

    def test_block_comment_of_code_is_found(self):
        text = (
            "fun live() = 1\n"
            "/*\n"
            "fun dead(o: Order) {\n"
            "    o.charge()\n"
            "    return null\n"
            "}\n"
            "*/\n"
        )
        blocks = scanner.find_blocks(text, "//", block=self.BLOCK)
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0].start, blocks[0].end), (2, 7))
        self.assertEqual(blocks[0].excerpt,
                          ("fun dead(o: Order) {", "o.charge()"))

    def test_doc_comment_is_never_a_block(self):
        """KDoc은 설명이지 지우다 만 코드가 아니다. 이걸 걸러내지 않으면
        실측 기준 오탐이 진짜 후보의 두 배가 된다."""
        text = (
            "/**\n"
            " * fun example(o: Order) {\n"
            " *     o.charge()\n"
            " *     return null\n"
            " * }\n"
            " */\n"
            "fun live() = 1\n"
        )
        self.assertEqual(scanner.find_blocks(text, "//", block=self.BLOCK), [])

    def test_opener_must_start_the_line(self):
        """문자열 리터럴 안의 여는 마커가 유령 영역을 열면 안 된다."""
        text = (
            'val url = "http://example.com/*"\n'
            "val a = compute()\n"
            "val b = compute()\n"
            "val c = compute()\n"
        )
        self.assertEqual(scanner.find_blocks(text, "//", block=self.BLOCK), [])

    def test_leading_asterisks_are_stripped_from_the_body(self):
        text = (
            "/*\n"
            " * x = one()\n"
            " * y = two()\n"
            " * z = three()\n"
            " */\n"
        )
        block = scanner.find_blocks(text, "//", block=self.BLOCK)[0]
        self.assertEqual(block.excerpt, ("x = one()", "y = two()"))

    def test_single_line_block_comment_is_below_the_floor(self):
        text = "/* x = one() */\nval live = 1\n"
        self.assertEqual(scanner.find_blocks(text, "//", block=self.BLOCK), [])

    def test_prose_block_comment_is_not_a_block(self):
        text = (
            "/*\n"
            "we kept this around while the migration was in flight and\n"
            "nobody has looked at it since then, ask the platform team\n"
            "before changing any of this please\n"
            "*/\n"
        )
        self.assertEqual(scanner.find_blocks(text, "//", block=self.BLOCK), [])

    def test_todo_inside_a_block_comment_ends_the_run(self):
        text = (
            "/*\n"
            "a = one()\n"
            "b = two()\n"
            "c = three()\n"
            "TODO: revisit\n"
            "d = four()\n"
            "*/\n"
        )
        blocks = scanner.find_blocks(text, "//", block=self.BLOCK)
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0].start, blocks[0].end), (2, 4))

    def test_line_and_block_comments_are_merged_in_line_order(self):
        text = (
            "/*\n"
            "a = one()\n"
            "b = two()\n"
            "c = three()\n"
            "*/\n"
            "val live = 1\n"
            "// d = four()\n"
            "// e = five()\n"
            "// f = six()\n"
        )
        blocks = scanner.find_blocks(text, "//", block=self.BLOCK)
        self.assertEqual([(b.start, b.end) for b in blocks],
                          [(1, 5), (7, 9)])

    def test_block_argument_absent_means_line_comments_only(self):
        text = "/*\na = one()\nb = two()\nc = three()\n*/\n"
        self.assertEqual(scanner.find_blocks(text, "//"), [])

    def test_unterminated_block_comment_is_still_judged(self):
        """닫는 마커 없이 파일이 끝나도 모은 것은 판정한다."""
        text = "/*\na = one()\nb = two()\nc = three()\n"
        blocks = scanner.find_blocks(text, "//", block=self.BLOCK)
        self.assertEqual(len(blocks), 1)


if __name__ == "__main__":
    unittest.main()
