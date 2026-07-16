from __future__ import annotations

import json
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]


class VariantGenerationPromptContractTests(unittest.TestCase):
    def test_main_skill_routes_generation_to_dedicated_reference(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("references/variant-generation-prompt.md", skill)
        self.assertIn("默认三题至少使用两个不同的主要变式轴", skill)
        self.assertIn("不能执行写回", skill)

    def test_prompt_contains_required_generation_and_quality_contracts(self) -> None:
        prompt = (SKILL_ROOT / "references" / "variant-generation-prompt.md").read_text(
            encoding="utf-8"
        )

        required_phrases = (
            "生成前事实卡",
            "浙江小学数学期末评价",
            "不得声称检索或参考了某一年的具体真题",
            "默认生成 3 道时，至少使用 2 个不同的主要变式轴",
            "强制质量门",
            "证据诚实",
            "wumu-jihe-html",
            '"questionId"',
            '"variants"',
            '"question"',
            '"answerAnalysis"',
            '"designIntent"',
            '"diagram"',
            "不得执行 `variant_catalog.py write`",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)

    def test_quality_evals_cover_targeted_variation_and_stop_conditions(self) -> None:
        payload = json.loads((SKILL_ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
        evals = {item["id"]: item for item in payload["evals"]}

        self.assertIn("买5箱送1箱", evals[18]["prompt"])
        self.assertIn("不要三道都只换数字", evals[18]["prompt"])
        self.assertIn("年级、学期和教材都空着", evals[19]["prompt"])
        self.assertIn("必须重新配图", evals[20]["prompt"])


if __name__ == "__main__":
    unittest.main()
