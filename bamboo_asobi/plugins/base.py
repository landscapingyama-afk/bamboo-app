"""ToolPlugin 基底クラス・プラグイン自動登録デコレータ"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional

from core.constants import (
    BAMBOO_ALLOWABLE_STRESS, BAMBOO_E,
    WEIGHT_HEAVY, WEIGHT_MEDIUM, WEIGHT_CHILD_MAX,
    DIAM_MIN_HEAVY, DIAM_MIN_MEDIUM, DIAM_ABSOLUTE_MIN, DIAM_RECOMMENDED,
    MAX_HEIGHT_CHILD, MAX_SPAN_NO_POST,
)
from core.models import Dimensions, Material, CheckMessage


# ══════════════════════════════════════════════════════════════════
# プラグイン自動登録デコレータ
# ══════════════════════════════════════════════════════════════════
# 使い方：ToolPlugin サブクラスに @register_plugin を付けるだけで
#         REGISTRY へ自動登録される。main() や REGISTRY への手動追記は不要。
REGISTRY: dict[str, "ToolPlugin"] = {}

def register_plugin(cls: type) -> type:
    """クラス定義時に自動で REGISTRY へ登録するデコレータ。"""
    instance = cls()
    REGISTRY[instance.name] = instance
    return cls


# ══════════════════════════════════════════════════════════════════
# ToolPlugin 基底クラス（遊具を追加するときはこれを継承する）
# ══════════════════════════════════════════════════════════════════
class ToolPlugin(ABC):
    """
    新しい遊具を追加するには、このクラスを継承して
    @register_plugin デコレータを付けるだけでOKです（REGISTRY への手動登録不要）。

    例:
        @register_plugin
        class MyTool(ToolPlugin):
            name = "シーソー"
            width_label  = "幅 (m)"
            length_label = "長さ (m)"   # None にするとサイドバーで非表示
            length_default = 2.0

            def validate(self, dims, weight) -> list[str]: ...
            def safety_check(self, dims, weight, **kwargs) -> tuple[list[CheckMessage], bool]: ...
            def draw(self, dims) -> tuple[str, str, list[Material]]: ...
            def render_guide(self, diameter_cm: float) -> None: ...  # 省略可（何もしない）
    """

    # ── クラス変数（サブクラスで上書き）──────────────────────────
    name:           str = ""
    width_label:    str = "幅 (m)"
    length_label:   Optional[str] = "長さ (m)"   # None にするとUIで非表示
    length_default: float = 1.0

    # ── 抽象メソッド ──────────────────────────────────────────────
    @abstractmethod
    def validate(self, dims: Dimensions, weight: float) -> List[str]:
        """入力バリデーション。エラーメッセージのリストを返す（空なら合格）"""

    @abstractmethod
    def safety_check(
        self, dims: Dimensions, weight: float,
        allowable_stress: float = BAMBOO_ALLOWABLE_STRESS,
        bamboo_e: float = BAMBOO_E,
    ) -> Tuple[List[CheckMessage], bool]:
        """安全チェック。(メッセージリスト, danger_flag) を返す"""

    @abstractmethod
    def draw(
        self, dims: Dimensions
    ) -> Tuple[str, str, List[Material]]:
        """図面生成。(svg_side, svg_top, materials) を返す"""

    def render_guide(self, diameter_cm: float) -> None:
        """製作手順ガイドを描画する。
        ガイドが不要な遊具はオーバーライド不要（何もしない）。
        ガイドがある遊具はこのメソッドをオーバーライドして実装する。
        """
        pass

    # ── QA警告定数（全遊具共通・render_safety_messages で折りたたみ表示）──
    _QA_NOTES: List[str] = [
        "【QA①】数値の過信禁止：この計算は材料の均質性を前提としています。節の直上への集中荷重は避けてください。",
        "【QA②】接合部の点検：図面上の赤色マーカー部分はロープ・ビスの緩み一つで崩壊につながります。使用前に必ず確認してください。",
        "【QA③】環境要因：雨天後の竹は強度が変化します。使用のたびに目視確認を行ってください。",
    ]

    # ── 共通安全チェックヘルパー ──────────────────────────────────
    def _common_checks(
        self, dims: Dimensions, weight: float
    ) -> Tuple[List[CheckMessage], bool]:
        msgs: List[CheckMessage] = []
        danger = False
        D = dims.diameter_cm
        diameter_danger = False   # 直径起因の「危険」が発火したか

        if weight > WEIGHT_HEAVY and D < DIAM_MIN_HEAVY:
            msgs.append(CheckMessage("危険",
                f"体重 {weight}kg に対して竹が細すぎます（直径{DIAM_MIN_HEAVY}cm以上を推奨）",
                f"直径{DIAM_MIN_HEAVY}cm以上の太い竹に変更してください。"))
            danger = True
            diameter_danger = True
        elif weight >= WEIGHT_MEDIUM and D < DIAM_MIN_MEDIUM:
            msgs.append(CheckMessage("危険",
                f"体重 {weight}kg に対して竹が細すぎます（直径{DIAM_MIN_MEDIUM}cm以上を推奨）",
                f"直径{DIAM_MIN_MEDIUM}cm以上の竹に変更してください。"))
            danger = True
            diameter_danger = True
        elif D < DIAM_ABSOLUTE_MIN:
            msgs.append(CheckMessage("危険",
                f"竹が細すぎます（最低{DIAM_ABSOLUTE_MIN}cm、安全のため{DIAM_RECOMMENDED}cm以上推奨）",
                f"最低でも直径{DIAM_ABSOLUTE_MIN}cm、できれば{DIAM_RECOMMENDED}cm以上の竹を使用してください。"))
            danger = True
            diameter_danger = True

        # 「危険」が発火済みの場合は下位の「警告」を重複出力しない
        if not diameter_danger and D < DIAM_RECOMMENDED:
            msgs.append(CheckMessage("警告",
                f"安全率を考慮し、直径{DIAM_RECOMMENDED}cm以上の竹を強く推奨します",
                f"竹材店や竹林で直径{DIAM_RECOMMENDED}cm以上・肉厚・節間30cm以下の竹を選んでください。"))

        if weight < WEIGHT_CHILD_MAX and dims.height_m > MAX_HEIGHT_CHILD:
            msgs.append(CheckMessage("警告",
                f"子供用（{weight}kg）として高さが高すぎます（転落時の怪我リスク大）",
                f"高さを{MAX_HEIGHT_CHILD}m以下に設定し直してください。"))

        if dims.width_m > MAX_SPAN_NO_POST:
            msgs.append(CheckMessage("警告",
                "幅が広すぎます。中間支柱を追加してください",
                "幅の中間点に支柱を1本追加してスパンを半分にしてください。"))

        msgs.append(CheckMessage("注意",
            "節間が短く（30cm以下）、肉厚で割れ・虫食いのない乾燥竹を使用してください"))
        msgs.append(CheckMessage("注意",
            "荷重がかかる点（支点・座面・接合部）の直下または直上に節が来るよう配置してください",
            "竹の節（ふし）は竹の中で最も強い部分です。重さがかかる場所の直下・直上に節が来るように配置してください。"))

        # QA警告は _QA_NOTES として別途 render_safety_messages で折りたたみ表示する
        return msgs, danger
