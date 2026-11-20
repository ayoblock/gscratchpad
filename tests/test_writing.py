"""写作模式宽度计算（纯函数）单元测试。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "vendor"))
os.environ.setdefault(
    "GI_TYPELIB_PATH",
    os.pathsep.join(
        [str(PROJECT / "vendor" / "gir" / "local"), "/usr/lib/x86_64-linux-gnu/girepository-1.0"]
    ),
)

from scratchpad.editor import WRITING_MIN_WIDTH, writing_target_width  # noqa: E402


class WritingTargetWidthTest(unittest.TestCase):
    def test_percentages(self) -> None:
        self.assertEqual(writing_target_width(1200, 85), 1020)
        self.assertEqual(writing_target_width(1200, 75), 900)
        self.assertEqual(writing_target_width(1200, 50), 600)

    def test_resized_viewport(self) -> None:
        self.assertEqual(writing_target_width(900, 85), 765)
        self.assertEqual(writing_target_width(1000, 50), 500)

    def test_minimum_width(self) -> None:
        # 400 × 50% = 200 → 抬到 360 下限
        self.assertEqual(writing_target_width(400, 50), WRITING_MIN_WIDTH)
        # 395 × 85% = 336 → 抬到 360，但仍不超过视口 395
        self.assertEqual(writing_target_width(395, 85), WRITING_MIN_WIDTH)

    def test_never_exceeds_viewport(self) -> None:
        # 视口比下限还窄时，取视口宽度（不能用 360 撑破窗口）
        self.assertEqual(writing_target_width(300, 85), 300)
        self.assertEqual(writing_target_width(120, 50), 120)

    def test_off_and_unlaid(self) -> None:
        self.assertEqual(writing_target_width(1200, 0), 0)
        self.assertEqual(writing_target_width(0, 85), 0)

    def test_rounding(self) -> None:
        # 1001 × 85% = 850.85 → 851（四舍五入，不是截断）
        self.assertEqual(writing_target_width(1001, 85), 851)


if __name__ == "__main__":
    unittest.main(verbosity=2)
