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
        self.assertEqual(scanner.find_blocks(text, "#"), [])
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


if __name__ == "__main__":
    unittest.main()
