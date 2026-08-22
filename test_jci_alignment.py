"""jci_alignment のナレッジ組み立てを確認する。python -m unittest で実行。"""

import os
import tempfile
import unittest

import jci_alignment


class BuildSystemPromptTest(unittest.TestCase):
    def test_stance_and_axes_are_included(self):
        prompt = jci_alignment.build_system_prompt("あなたはJC担当です。", docs_dir="/存在しない")
        self.assertIn("あなたはJC担当です。", prompt)
        self.assertIn("仙台にとって何が最善か", prompt)
        self.assertIn("アワードで問われる評価軸", prompt)

    def test_says_docs_are_unregistered_when_dir_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            prompt = jci_alignment.build_system_prompt("base", docs_dir=d)
        self.assertIn("【JCI公式文書】未登録", prompt)
        self.assertIn("推測で答えず", prompt)

    def test_registered_docs_are_loaded_verbatim(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "2026_plan_of_action.md"), "w", encoding="utf-8") as f:
                f.write("重点方針：若者の地域参画を広げる")
            with open(os.path.join(d, "README.md"), "w", encoding="utf-8") as f:
                f.write("これは説明書なので読み込まれない")
            prompt = jci_alignment.build_system_prompt("base", docs_dir=d)
        self.assertIn("重点方針：若者の地域参画を広げる", prompt)
        self.assertIn("2026_plan_of_action.md", prompt)
        self.assertNotIn("これは説明書なので読み込まれない", prompt)
        self.assertNotIn("【JCI公式文書】未登録", prompt)

    def test_long_docs_are_truncated(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "long.md"), "w", encoding="utf-8") as f:
                f.write("あ" * (jci_alignment.MAX_DOC_CHARS + 500))
            docs = jci_alignment.load_official_docs(d)
        self.assertIn("（以下省略）", docs)
        self.assertLess(len(docs), jci_alignment.MAX_DOC_CHARS + 300)


class WorksheetTest(unittest.TestCase):
    def test_fits_in_a_line_message(self):
        text = jci_alignment.worksheet()
        self.assertLess(len(text), 5000)
        self.assertIn("整合チェック", text)


if __name__ == "__main__":
    unittest.main()
