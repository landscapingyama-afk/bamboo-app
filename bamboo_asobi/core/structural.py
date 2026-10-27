"""構造計算（エラーハンドリング付き）"""

from __future__ import annotations

import logging
import math
from typing import Optional

from core.constants import BAMBOO_ALLOWABLE_STRESS, BAMBOO_E, BAMBOO_WALL_RATIO
from core.models import Dimensions, StructuralResult

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# 構造計算（エラーハンドリング付き）
# ══════════════════════════════════════════════════════════════════
# 【計算モデルの前提と限界】
#   - モデル：単純支持梁 + スパン中央集中荷重（最も基本的な簡易モデル）
#   - 実際との相違点：
#       1. 荷重は点荷重ではなく分布荷重（実際は安全側になる場合が多い）
#       2. 接合部の弱さは考慮していない（実際は接合部が先に破損しやすい）
#       3. 竹は異方性材料であり、節・乾燥状態・個体差で強度が大幅に変動する
#       4. 動的荷重は係数（DYNAMIC_LOAD_FACTOR）で近似しているにすぎない
#   - 結論：本計算は安全チェックの参考値であり、構造設計の根拠とはならない。
#           実際の製作前に必ず専門家（建築士・構造技術者）の確認を受けること。


def check_bending(
    diameter_m: float, span_m: float, load_kg: float,
    dims: Optional["Dimensions"] = None,
    allowable_stress: float = BAMBOO_ALLOWABLE_STRESS,
) -> StructuralResult:
    """竹断面の曲げ応力チェック。
    dims が渡された場合は dims.section_Z を使用（推奨）。
    後方互換のため diameter_m 単体での呼び出しも維持。
    """
    try:
        if diameter_m <= 0 or span_m <= 0 or load_kg < 0:
            return StructuralResult(False, 0.0, "入力値が不正です")
        Z = dims.section_Z if dims is not None else _hollow_I_legacy(diameter_m) / (diameter_m / 2)
        M = (load_kg * 9.81) * span_m / 4
        stress = M / (Z + 1e-12)
        return StructuralResult(stress <= allowable_stress, stress / 1e6)
    except Exception as e:
        logger.error("check_bending error: %s", e)
        return StructuralResult(False, 0.0, f"計算エラー: {e}")


def check_deflection(
    diameter_m: float, span_m: float, load_kg: float,
    dims: Optional["Dimensions"] = None,
    bamboo_e: float = BAMBOO_E,
) -> StructuralResult:
    """竹断面のたわみチェック。
    dims が渡された場合は dims.section_I を使用（推奨）。
    後方互換のため diameter_m 単体での呼び出しも維持。
    """
    try:
        if diameter_m <= 0 or span_m <= 0 or load_kg < 0:
            return StructuralResult(False, 0.0, "入力値が不正です")
        I     = dims.section_I if dims is not None else _hollow_I_legacy(diameter_m)
        F     = load_kg * 9.81
        delta = F * span_m**3 / (48 * bamboo_e * I + 1e-12)
        limit = span_m / 200
        return StructuralResult(delta <= limit, delta * 1000)
    except Exception as e:
        logger.error("check_deflection error: %s", e)
        return StructuralResult(False, 0.0, f"計算エラー: {e}")


def _hollow_I_legacy(diameter_m: float) -> float:
    """後方互換用。新規コードは Dimensions.section_I を使うこと。
    # TODO: 次期バージョンで削除予定。呼び出し元は check_bending / check_deflection 内のみ。
    """
    di = diameter_m * (1.0 - 2 * BAMBOO_WALL_RATIO)
    return math.pi * (diameter_m**4 - di**4) / 64
