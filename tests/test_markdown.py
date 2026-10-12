import unittest

from servio.markdown import render_markdown


class MathExtractionTest(unittest.TestCase):
    """Math must be pulled out of the Markdown stream without damaging it.

    Every case here is a shape that real generated documents use (see
    ``static/markdown/20260924/210230_什么是LL(1) 文法.md``, where an escaped
    dollar used to re-partition the whole answer).
    """

    def test_escaped_dollar_stays_inside_its_math_span(self):
        html = render_markdown("行内 $a$ 与结束符 $\\$$，随后 $b$ 继续。")

        self.assertNotIn("MATHPLACEHOLDER", html)
        self.assertNotIn("ESCAPEDDOLLAR", html)
        self.assertEqual(html.count("$ a $"), 1)
        self.assertEqual(html.count("$ b $"), 1)
        # ``\$`` is handed to MathJax escaped so it prints a literal dollar
        # instead of opening a new span.
        self.assertIn("$ \\$ $", html)

    def test_unbalanced_dollar_cannot_swallow_following_paragraphs(self):
        source = "第一段 价格 $a\n\n第二段 $b$ 与 $c$\n\n第三段。"

        html = render_markdown(source)

        self.assertNotIn("MATHPLACEHOLDER", html)
        self.assertEqual(html.count("<p>"), 3)
        self.assertIn("$ b $", html)
        self.assertIn("$ c $", html)

    def test_complex_display_block_is_preserved_verbatim(self):
        source = (
            "$$\n"
            "\\begin{cases}\n"
            "x & y,\\\\[4pt]\n"
            "z & w.\n"
            "\\end{cases}\n"
            "$$"
        )

        html = render_markdown(source)

        self.assertNotIn("MATHPLACEHOLDER", html)
        self.assertEqual(html.count("$$"), 2)
        self.assertIn("\\begin{cases}", html)
        self.assertIn("\\end{cases}", html)
        # ``\\[4pt]`` is LaTeX row spacing, not a display delimiter.
        self.assertIn("\\\\[4pt]", html)
        self.assertIn("x &amp; y,", html)

    def test_bracket_display_math_keeps_row_spacing(self):
        html = render_markdown(r"\[ \begin{cases} a \\[6pt] b \end{cases} \]")

        self.assertNotIn("MATHPLACEHOLDER", html)
        self.assertIn(r"\[ \begin{cases} a \\[6pt] b \end{cases} \]", html)

    def test_subscripts_are_not_rewritten(self):
        html = render_markdown("$X_1X_2$ 与 $e_1e_2\\cdots e_m$")

        self.assertIn("X_1X_2", html)
        self.assertIn("e_1e_2\\cdots e_m", html)
        self.assertNotIn("X_{1X}", html)
        self.assertNotIn("e_{1e}", html)

    def test_display_math_inside_a_list_item_keeps_the_list(self):
        source = "1. 对每个\n   $$\n   a=b\n   $$\n   结束\n\n2. 第二项\n"

        html = render_markdown(source)

        self.assertNotIn("MATHPLACEHOLDER", html)
        self.assertEqual(html.count("<li>"), 2)
        self.assertIn("$$ a=b $$", html)

    def test_display_math_inside_a_blockquote_survives_markdown_escaping(self):
        # The report that started this: a ``$$`` line inside a quote used to
        # miss the extraction, so Markdown ate the backslash of ``\#`` and
        # MathJax failed with "macro parameter character #".
        source = "> 因此新增的逆序对数量是：\n> $$c(a,b)=\\#\\{(i,j)\\ :\\ i\\in S_a\\}$$\n"

        html = render_markdown(source)

        self.assertNotIn("MATHPLACEHOLDER", html)
        self.assertEqual(html.count("$$"), 2)
        self.assertIn("$$ c(a,b)=\\#\\{(i,j)\\ :\\ i\\in S_a\\} $$", html)
        self.assertTrue(html.index("$$") > html.index("<blockquote>"))
        self.assertTrue(html.index("$$", html.index("$$") + 1) < html.index("</blockquote>"))

    def test_quoted_display_math_drops_the_markers_of_its_own_lines(self):
        source = "> 化简得：\n> $$\n> a &= b.\\\\\n> c &= d.\n> $$\n\n后文。\n"

        html = render_markdown(source)

        self.assertNotIn("MATHPLACEHOLDER", html)
        self.assertIn("$$ a &amp;= b.\\\\ c &amp;= d. $$", html)
        self.assertNotIn("> a", html)

    def test_math_in_table_cells_does_not_break_the_table(self):
        html = render_markdown("| 公式 |\n|---|\n| $|x|$ |\n")

        self.assertNotIn("MATHPLACEHOLDER", html)
        self.assertIn("<table>", html)
        self.assertEqual(html.count("<tr>"), 2)
        self.assertIn("$ |x| $", html)


if __name__ == "__main__":
    unittest.main()
