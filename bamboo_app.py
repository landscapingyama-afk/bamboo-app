"""
竹あそび - 竹製遊具 設計・安全チェックアプリ
================================================
動作確認Pythonバージョン：3.9 以上
  （`from __future__ import annotations` により 3.9 でも型ヒントの前方参照が動作します。
    Python 3.10 以降では当該インポートは不要ですが、互換性のため残しています。）

改善点：
  - SVGサニタイゼーション
  - エラーハンドリング（全計算関数）
  - 入力値バリデーション（遊具ごと）
  - 単位系の統一（Dimensionsデータクラス）
  - 拡張可能なプラグイン構造（ToolPluginを継承して遊具を追加）
"""

from __future__ import annotations

import html
import math
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple, Optional

import csv
import io

import streamlit as st

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# 定数・カラー定義
# ══════════════════════════════════════════════════════════════════
BF   = "#2d6a2d"
BD   = "#1a3a1a"
BL   = "#5aaa4a"
BM   = "#1a4a1a"
WF   = "#8B6914"
WD   = "#5a4008"
GC   = "#B4B2A9"
DC   = "#888780"
ROPE = "#BA7517"

BAMBOO_WALL_RATIO        = 0.20
BAMBOO_ALLOWABLE_STRESS  = 10e6   # Pa（竹の許容曲げ応力：種類・乾燥状態で変動）
BAMBOO_E                 = 10e9   # Pa（竹の弾性係数：種類・乾燥状態で変動）

# ── 竹の種類ごとの材料特性テーブル ─────────────────────────────────
# 出典：木材・竹材の強度試験データ（農林水産省、各大学研究報告）を参考に
#       安全側（保守的）な値を採用。実際の竹は個体差・含水率で±30%変動する。
BAMBOO_SPECS: dict[str, dict] = {
    "孟宗竹（乾燥・標準）":  {"E": 10e9, "sigma": 10e6, "note": "最も流通量が多い。乾燥させると強度が安定する。"},
    "孟宗竹（生竹・未乾燥）": {"E":  7e9, "sigma":  7e6, "note": "含水率が高く弾性係数・強度ともに低下する。乾燥後の使用を強く推奨。"},
    "真竹（乾燥）":           {"E": 11e9, "sigma": 11e6, "note": "肉厚で靭性が高い。工芸・構造用途に適する。"},
    "淡竹（ハチク・乾燥）":   {"E":  9e9, "sigma":  9e6, "note": "細身で軽量。細い部材への使用に向く。"},
}

# ── 安全チェック閾値 ──────────────────────────────────────────────
# 体重区分（kg）
WEIGHT_HEAVY      = 60    # この体重超は太い竹が必要
WEIGHT_MEDIUM     = 40    # この体重以上は標準太竹が必要
WEIGHT_CHILD_MAX  = 40    # 子供用とみなす上限体重

# 竹直径区分（cm）
DIAM_MIN_HEAVY    = 10    # 重量者（>WEIGHT_HEAVY）に必要な最低直径
DIAM_MIN_MEDIUM   = 8     # 中量者（>=WEIGHT_MEDIUM）に必要な最低直径
DIAM_ABSOLUTE_MIN = 6     # 全体の絶対最低直径
DIAM_RECOMMENDED  = 8     # 安全率を考慮した推奨最低直径

# 高さ・幅閾値（m）
MAX_HEIGHT_CHILD  = 1.2   # 子供用遊具の最大推奨高さ
MAX_SPAN_NO_POST  = 1.5   # 中間支柱なしで許容する最大幅スパン
MAX_HEIGHT_ADULT  = 2.0   # 大人体重ユーザー向け最大推奨高さ

# 構造計算閾値
WARNING_STRESS_RATIO = 0.70  # 許容応力に対する警告発令比率（70%超で「警告」）
# 旧 WARNING_STRESS_MPA = 7.0 は固定値だったが、竹種による allowable_stress に連動するよう変更
# たわみ制限は span/200（check_deflection内で計算）

# SlidePlugin 固有
MAX_SLOPE_DEG     = 35    # 滑り台の最大推奨傾斜角（°）
# 出典：一般的な滑り台の安全基準（急斜面防止）

# SwingPlugin 固有
DYNAMIC_LOAD_FACTOR   = 3.5   # 動的荷重係数（揺れ・飛び乗り時の静荷重倍率）
# 出典：遊具安全基準（EN 1176等）では3〜5倍が一般的。保守的に3.5を採用
ROPE_DANGER_LOAD_KG   = 150   # この動的荷重超でロープを「危険」と判定
WEIGHT_ROPE_WARNING   = 50    # この体重超で耐荷重200kgロープを「警告」推奨
SEAT_HEIGHT_RATIO     = 0.22  # 座面の地面からの高さ比（フレーム高さに対する比）
# SwingPluginのROPE_HEIGHT_RATIOと同値（safety_check用）
MAX_SEAT_HEIGHT_M     = 0.5   # 座面の最大推奨高さ（m）
MAX_FRAME_HEIGHT_M    = 2.5   # ブランコフレームの最大推奨高さ（m）

# ── SVGプリミティブ描画係数 ────────────────────────────────────────
# bamboo_slat（竹板材の側面描画）用
SLAT_HIGHLIGHT_POS   = 0.45   # ハイライト線の幅方向位置（端から何割内側か）
SLAT_END_RY_RATIO    = 0.38   # 端面楕円の短径比（竹の断面つぶれ具合）
SLAT_END_OPACITY     = 0.45   # 端面楕円の不透明度

# bamboo_top（竹の上面・断面描画）用
TOP_INNER_RATIO      = 0.52   # 内側楕円の半径比（竹の内腔サイズ）
TOP_HIGHLIGHT_OFFSET = 0.22   # ハイライト点の中心からのオフセット比
TOP_HIGHLIGHT_SIZE   = 0.16   # ハイライト点の半径比


# ══════════════════════════════════════════════════════════════════
# データクラス群
# ══════════════════════════════════════════════════════════════════
@dataclass
class Dimensions:
    """すべての寸法をメートル単位で管理するデータクラス"""
    height_m:   float
    width_m:    float
    length_m:   float
    diameter_m: float

    @property
    def diameter_cm(self) -> float:
        return self.diameter_m * 100

    @property
    def height_cm(self) -> float:
        return self.height_m * 100

    @property
    def width_cm(self) -> float:
        return self.width_m * 100

    @property
    def length_cm(self) -> float:
        return self.length_m * 100

    @property
    def section_I(self) -> float:
        """中空円管の断面二次モーメント [m^4]"""
        di = self.diameter_m * (1.0 - 2 * BAMBOO_WALL_RATIO)
        return math.pi * (self.diameter_m**4 - di**4) / 64

    @property
    def section_Z(self) -> float:
        """断面係数 [m^3]"""
        return self.section_I / (self.diameter_m / 2)


@dataclass
class Material:
    name:      str
    length_cm: int
    count:     int
    is_wood:   bool = False
    is_rope:   bool = False


@dataclass
class CheckMessage:
    level:  str          # "危険" | "警告" | "注意"
    msg:    str
    advice: str = ""


@dataclass
class StructuralResult:
    ok:     bool
    value:  float
    error:  str = ""


# ══════════════════════════════════════════════════════════════════
# SVGサニタイゼーション
# ══════════════════════════════════════════════════════════════════
def sanitize_svg_content(value: str) -> str:
    """
    SVGコンテンツの基本サニタイゼーション。
    - script / on* イベント属性を除去
    - javascript: URI を除去
    """
    import re
    # <script> タグを除去
    value = re.sub(r'<script[\s\S]*?</script>', '', value, flags=re.IGNORECASE)
    # on* イベント属性を除去（例：onclick="..."）
    value = re.sub(r'\bon\w+\s*=\s*["\'][^"\']*["\']', '', value, flags=re.IGNORECASE)
    # javascript: URI を除去
    value = re.sub(r'javascript\s*:', 'removed:', value, flags=re.IGNORECASE)
    return value


def make_svg(vw: float, vh: float, body: str, title: str = "") -> str:
    """SVGラッパーを生成する。bodyはサニタイズしてから埋め込む。"""
    safe_body  = sanitize_svg_content(body)
    safe_title = html.escape(title)
    t = (f'<text x="{vw/2:.2f}" y="24" text-anchor="middle"'
         f' font-size="12" font-weight="500" fill="#333">{safe_title}</text>'
         ) if safe_title else ""
    return (f'<svg viewBox="0 0 {vw} {vh}" xmlns="http://www.w3.org/2000/svg"'
            f' style="width:100%;height:auto;">{t}{safe_body}</svg>')


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
    """後方互換用。新規コードは Dimensions.section_I を使うこと。"""
    di = diameter_m * (1.0 - 2 * BAMBOO_WALL_RATIO)
    return math.pi * (diameter_m**4 - di**4) / 64


# ══════════════════════════════════════════════════════════════════
# SVGプリミティブ描画ヘルパー
# ══════════════════════════════════════════════════════════════════
def fmt(v: float) -> str:
    return f"{v:.2f}m" if v >= 1 else f"{round(v*100)}cm"


def ell(cx, cy, rx, ry, fill, stroke, sw=0.7, op=1.0) -> str:
    o = f' opacity="{op}"' if op < 1 else ""
    return (f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}"'
            f' fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{o}/>')


def bamboo_slat(x1, y1, x2, y2, r) -> str:
    dx, dy = x2 - x1, y2 - y1
    L = math.sqrt(dx*dx + dy*dy)
    if L < 0.1:
        return ""
    ux, uy = dx/L, dy/L
    nx, ny = -uy*r, ux*r
    pts = (f"{x1+nx:.2f},{y1+ny:.2f} {x2+nx:.2f},{y2+ny:.2f}"
           f" {x2-nx:.2f},{y2-ny:.2f} {x1-nx:.2f},{y1-ny:.2f}")
    poly = f'<polygon points="{pts}" fill="{BF}" stroke="{BD}" stroke-width="0.55"/>'
    hi   = (f'<line x1="{x1+nx*SLAT_HIGHLIGHT_POS:.2f}" y1="{y1+ny*SLAT_HIGHLIGHT_POS:.2f}"'
            f' x2="{x2+nx*SLAT_HIGHLIGHT_POS:.2f}" y2="{y2+ny*SLAT_HIGHLIGHT_POS:.2f}"'
            f' stroke="{BL}" stroke-width="0.45" opacity="0.5"/>')
    e1 = ell(x1, y1, r, r*SLAT_END_RY_RATIO, BM, BD, SLAT_END_OPACITY)
    e2 = ell(x2, y2, r, r*SLAT_END_RY_RATIO, BM, BD, SLAT_END_OPACITY)
    return poly + hi + e1 + e2


def bamboo_top(cx, cy, rx, ry) -> str:
    return (ell(cx, cy, rx, ry, BF, BD, 0.7) +
            ell(cx, cy, rx*TOP_INNER_RATIO, ry*TOP_INNER_RATIO, BM, BD, 0.4, 0.65) +
            ell(cx-rx*TOP_HIGHLIGHT_OFFSET, cy-ry*TOP_HIGHLIGHT_OFFSET,
                rx*TOP_HIGHLIGHT_SIZE, ry*TOP_HIGHLIGHT_SIZE, BL, "none", 0, 0.45))


def wood_rect(x, y, w, h) -> str:
    r  = (f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}"'
          f' fill="{WF}" stroke="{WD}" stroke-width="0.8" rx="1.5"/>')
    l1 = (f'<line x1="{x+2:.2f}" y1="{y+h*0.35:.2f}"'
          f' x2="{x+w-2:.2f}" y2="{y+h*0.35:.2f}"'
          f' stroke="{WD}" stroke-width="0.3" opacity="0.35"/>')
    l2 = (f'<line x1="{x+2:.2f}" y1="{y+h*0.68:.2f}"'
          f' x2="{x+w-2:.2f}" y2="{y+h*0.68:.2f}"'
          f' stroke="{WD}" stroke-width="0.3" opacity="0.35"/>')
    return r + l1 + l2


def dim_h(x1, x2, y, val) -> str:
    mx = (x1+x2)/2
    return (f'<line x1="{x1:.2f}" y1="{y:.2f}" x2="{x2:.2f}" y2="{y:.2f}"'
            f' stroke="{DC}" stroke-width="0.7"/>'
            f'<line x1="{x1:.2f}" y1="{y-4:.2f}" x2="{x1:.2f}" y2="{y+4:.2f}"'
            f' stroke="{DC}" stroke-width="0.7"/>'
            f'<line x1="{x2:.2f}" y1="{y-4:.2f}" x2="{x2:.2f}" y2="{y+4:.2f}"'
            f' stroke="{DC}" stroke-width="0.7"/>'
            f'<text x="{mx:.2f}" y="{y+13:.2f}" text-anchor="middle"'
            f' font-size="10" fill="{DC}">{fmt(val)}</text>')


def dim_v(x, y1, y2, val) -> str:
    my = (y1+y2)/2
    return (f'<line x1="{x:.2f}" y1="{y1:.2f}" x2="{x:.2f}" y2="{y2:.2f}"'
            f' stroke="{DC}" stroke-width="0.7"/>'
            f'<line x1="{x-4:.2f}" y1="{y1:.2f}" x2="{x+4:.2f}" y2="{y1:.2f}"'
            f' stroke="{DC}" stroke-width="0.7"/>'
            f'<line x1="{x-4:.2f}" y1="{y2:.2f}" x2="{x+4:.2f}" y2="{y2:.2f}"'
            f' stroke="{DC}" stroke-width="0.7"/>'
            f'<text x="{x-10:.2f}" y="{my:.2f}" text-anchor="middle"'
            f' dominant-baseline="central" font-size="10" fill="{DC}"'
            f' transform="rotate(-90,{x-10:.2f},{my:.2f})">{fmt(val)}</text>')


# ══════════════════════════════════════════════════════════════════
# ToolPlugin 基底クラス（遊具を追加するときはこれを継承する）
# ══════════════════════════════════════════════════════════════════
class ToolPlugin(ABC):
    """
    新しい遊具を追加するには、このクラスを継承して
    REGISTRY に登録するだけでOKです。

    例:
        class MyTool(ToolPlugin):
            name = "シーソー"
            width_label  = "幅 (m)"
            length_label = "長さ (m)"   # None にするとサイドバーで非表示
            length_default = 2.0

            def validate(self, dims, weight) -> list[str]: ...
            def safety_check(self, dims, weight) -> tuple[list[CheckMessage], bool]: ...
            def draw(self, dims) -> tuple[str, str, list[Material]]: ...

        REGISTRY["シーソー"] = MyTool()
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

    # ── 共通安全チェックヘルパー ──────────────────────────────────
    def _common_checks(
        self, dims: Dimensions, weight: float
    ) -> Tuple[List[CheckMessage], bool]:
        msgs: List[CheckMessage] = []
        danger = False
        D = dims.diameter_cm

        if weight > WEIGHT_HEAVY and D < DIAM_MIN_HEAVY:
            msgs.append(CheckMessage("危険",
                f"体重 {weight}kg に対して竹が細すぎます（直径{DIAM_MIN_HEAVY}cm以上を推奨）",
                f"直径{DIAM_MIN_HEAVY}cm以上の太い竹に変更してください。"))
            danger = True
        elif weight >= WEIGHT_MEDIUM and D < DIAM_MIN_MEDIUM:
            msgs.append(CheckMessage("危険",
                f"体重 {weight}kg に対して竹が細すぎます（直径{DIAM_MIN_MEDIUM}cm以上を推奨）",
                f"直径{DIAM_MIN_MEDIUM}cm以上の竹に変更してください。"))
            danger = True
        elif D < DIAM_ABSOLUTE_MIN:
            msgs.append(CheckMessage("危険",
                f"竹が細すぎます（最低{DIAM_ABSOLUTE_MIN}cm、安全のため{DIAM_RECOMMENDED}cm以上推奨）",
                f"最低でも直径{DIAM_ABSOLUTE_MIN}cm、できれば{DIAM_RECOMMENDED}cm以上の竹を使用してください。"))
            danger = True

        if D < DIAM_RECOMMENDED:
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

        return msgs, danger


# ══════════════════════════════════════════════════════════════════
# 遊具プラグイン実装
# ══════════════════════════════════════════════════════════════════

# ─────────────────────────── 滑り台 ───────────────────────────────
class SlidePlugin(ToolPlugin):
    name           = "滑り台"
    width_label    = "幅 (m)"
    length_label   = "長さ（斜面の水平長） (m)"
    length_default = 2.5

    # ── 描画係数（サブクラスで上書き可能）────────────────────────
    DRAW_SCALE_MARGIN  = 0.88   # フィット後に掛けるマージン係数
    PITCH_RATIO        = 1.2    # 横材のピッチ（竹径の何倍間隔か）
    SLAT_ELLIPSE_RX    = 0.45   # 横材端面楕円の長径比
    HANDRAIL_OFFSET    = 1.8    # 手すり竹の横方向オフセット比
    HANDRAIL_WIDTH     = 0.55   # 手すり竹の幅比

    def validate(self, dims: Dimensions, weight: float) -> List[str]:
        errors = []
        if dims.length_m < dims.height_m:
            errors.append("滑り台の水平長は高さ以上にしてください（傾斜が急すぎます）")
        if dims.height_m < 0.3:
            errors.append("高さが低すぎます（0.3m以上）")
        if dims.width_m < 0.3:
            errors.append("幅が狭すぎます（0.3m以上）")
        return errors

    def safety_check(
        self, dims: Dimensions, weight: float,
        allowable_stress: float = BAMBOO_ALLOWABLE_STRESS,
        bamboo_e: float = BAMBOO_E,
    ) -> Tuple[List[CheckMessage], bool]:
        msgs, danger = self._common_checks(dims, weight)
        D  = dims.diameter_m
        Dc = dims.diameter_cm

        # 傾斜チェック
        angle = math.degrees(math.atan(dims.height_m / max(dims.length_m, 0.01)))
        if angle > MAX_SLOPE_DEG:
            msgs.append(CheckMessage("危険",
                f"傾斜が急すぎます（{round(angle)}°、{MAX_SLOPE_DEG}°以下を推奨）",
                f"長さを長くするか高さを低くして傾斜を{MAX_SLOPE_DEG}°以下にしてください。"))
            danger = True

        # 滑り面横材の構造チェック
        res_s = check_bending(D, dims.width_m, weight, dims, allowable_stress)
        res_d = check_deflection(D, dims.width_m, weight, dims, bamboo_e)

        if res_s.error:
            msgs.append(CheckMessage("注意", f"曲げ計算スキップ: {res_s.error}"))
        elif not res_s.ok:
            msgs.append(CheckMessage("危険",
                f"滑り面横材が折れる可能性があります（計算応力 {res_s.value:.1f} MPa > 許容 {allowable_stress/1e6:.0f} MPa）",
                f"竹の直径を太くする（現在{Dc}cm → 2〜3cm増）か、横材本数を増やしてください。"))
            danger = True
        elif res_s.value > allowable_stress / 1e6 * WARNING_STRESS_RATIO:
            warn_thresh = allowable_stress / 1e6 * WARNING_STRESS_RATIO
            msgs.append(CheckMessage("警告",
                f"滑り面横材の応力が許容値の{round(WARNING_STRESS_RATIO*100)}%を超えています（{res_s.value:.1f} MPa > {warn_thresh:.1f} MPa）",
                f"竹を1〜2cm太くするか横材を増やしてください。"))
        else:
            msgs.append(CheckMessage("注意",
                f"滑り面横材 曲げ応力：{res_s.value:.1f} MPa（許容{allowable_stress/1e6:.0f} MPa以内 ✓）"))

        if res_d.error:
            msgs.append(CheckMessage("注意", f"たわみ計算スキップ: {res_d.error}"))
        elif not res_d.ok:
            msgs.append(CheckMessage("警告",
                f"滑り面横材のたわみが大きすぎます（{res_d.value:.1f} mm）",
                "竹を太くするか横材を増やしてたわみを減らしてください。"))

        if weight >= WEIGHT_MEDIUM and dims.height_m > MAX_HEIGHT_ADULT:
            msgs.append(CheckMessage("警告",
                "高さが高すぎます（転落リスク）",
                f"高さを{MAX_HEIGHT_ADULT}m以下に設定し直してください。"))

        return msgs, danger

    def draw(self, dims: Dimensions) -> Tuple[str, str, List[Material]]:
        D  = dims.diameter_m
        Dc = dims.diameter_cm
        H  = dims.height_m
        W  = dims.width_m
        L  = dims.length_m

        slope_len = math.sqrt(L**2 + H**2)
        pitch = D * self.PITCH_RATIO
        num   = max(1, math.floor(slope_len / pitch))
        aL    = num * D

        PL, PR, PT, PB = 60, 26, 44, 50
        VW, VH = 340, 290
        DW, DH = VW-PL-PR, VH-PT-PB
        sc  = min(DW/aL, DH/H) * self.DRAW_SCALE_MARGIN
        T   = D * sc
        sl  = aL * sc
        sh  = H  * sc

        sx = PL + (DW-sl)/2
        ex = sx + sl
        gy = PT + DH
        sy = gy - sh

        dxs = ex - sx
        dys = gy - sy
        sL2 = math.sqrt(dxs**2 + dys**2)
        ux, uy = dxs/sL2, dys/sL2
        nx, ny = -uy, ux
        fH  = max(T*0.9, 5)

        s  = (f'<line x1="{sx-14:.2f}" y1="{gy:.2f}" x2="{ex+14:.2f}" y2="{gy:.2f}"'
              f' stroke="{GC}" stroke-width="2.5" stroke-linecap="round"/>')
        lw = max(T*0.9, 4)
        s += wood_rect(sx - lw, sy, lw, sh)
        p1x = sx + nx*(-fH); p1y = sy + ny*(-fH)
        p2x = ex + nx*(-fH); p2y = gy + ny*(-fH)
        s += (f'<polygon points="{p1x:.2f},{p1y:.2f} {p2x:.2f},{p2y:.2f}'
              f' {ex:.2f},{gy:.2f} {sx:.2f},{sy:.2f}"'
              f' fill="{WF}" stroke="{WD}" stroke-width="0.8"/>')
        for i in range(num):
            t2 = (i + 0.5) / num
            cx = sx + dxs*t2; cy = sy + dys*t2
            bx = cx + nx*(T/2); by = cy + ny*(T/2)
            s += ell(bx, by, T*self.SLAT_ELLIPSE_RX, T/2, BF, BD, 0.6)
            s += ell(bx, by, T*self.SLAT_ELLIPSE_RX*0.5, T/2*0.5, BM, BD, 0.35, 0.6)
        s += bamboo_slat(sx, sy+ny*T*self.HANDRAIL_OFFSET, ex, gy+ny*T*self.HANDRAIL_OFFSET, T*self.HANDRAIL_WIDTH)
        s += dim_h(sx, ex, gy+28, aL)
        s += dim_v(sx-36, sy, gy, H)
        svg_side = make_svg(VW, VH, s, f"側面図（横材 {num}本）")

        TPL, TPR, TPT, TPB = 60, 26, 44, 50
        TVW = 340
        TDW = TVW - TPL - TPR
        tsc = min(TDW/W, 200/aL) * self.DRAW_SCALE_MARGIN
        TT  = D  * tsc
        tw  = W  * tsc
        tl  = aL * tsc
        TVH = math.ceil(tl + TPT + TPB + 60)
        tx  = TPL + (TDW-tw)/2
        ty  = TPT

        ftk = max(TT*0.7, 4)
        t2  = ""
        t2 += wood_rect(tx, ty, ftk, tl)
        t2 += wood_rect(tx+tw-ftk, ty, ftk, tl)
        t2 += wood_rect(tx, ty, tw, ftk*0.6)
        t2 += wood_rect(tx, ty+tl-ftk*0.6, tw, ftk*0.6)
        for i in range(num):
            tr = (i + 0.5) / num
            cy = ty + tr * tl
            t2 += (f'<rect x="{tx+ftk*0.8:.2f}" y="{cy-TT/2:.2f}"'
                   f' width="{tw-ftk*1.6:.2f}" height="{TT:.2f}" rx="{TT/2:.2f}"'
                   f' fill="{BF}" stroke="{BD}" stroke-width="0.6"/>')
            t2 += (f'<line x1="{tx+ftk*0.8+3:.2f}" y1="{cy:.2f}"'
                   f' x2="{tx+tw-ftk*0.8-3:.2f}" y2="{cy:.2f}"'
                   f' stroke="{BL}" stroke-width="0.4" opacity="0.4"/>')
            t2 += bamboo_top(tx+ftk*0.8-TT*0.1, cy, TT/2, TT*0.42)
            t2 += bamboo_top(tx+tw-ftk*0.8+TT*0.1, cy, TT/2, TT*0.42)
        rr = TT * 0.7
        t2 += (f'<rect x="{tx+ftk:.2f}" y="{ty:.2f}" width="{rr*2:.2f}" height="{tl:.2f}"'
               f' rx="{rr:.2f}" fill="{BF}" stroke="{BD}" stroke-width="0.7"/>')
        t2 += (f'<rect x="{tx+tw-ftk-rr*2:.2f}" y="{ty:.2f}" width="{rr*2:.2f}" height="{tl:.2f}"'
               f' rx="{rr:.2f}" fill="{BF}" stroke="{BD}" stroke-width="0.7"/>')
        t2 += dim_h(tx, tx+tw, ty+tl+28, W)
        t2 += dim_v(tx-36, ty, ty+tl, aL)
        svg_top = make_svg(TVW, TVH, t2, f"上面図（横材 {num}本）")

        materials = [
            Material(f"滑り面横材 直径{Dc:.0f}cm", round(W*100),         num),
            Material(f"手すり竹   直径{Dc:.0f}cm", round(slope_len*100), 2),
            Material("木材フレーム（側板）",         round(aL*100),        2, is_wood=True),
            Material("木材フレーム（端板）",         round(W*100),         2, is_wood=True),
        ]
        return svg_side, svg_top, materials


# ─────────────────────────── ブランコ ─────────────────────────────
class SwingPlugin(ToolPlugin):
    name           = "ブランコ"
    width_label    = "幅 (m)"
    length_label   = "奥行き / 三脚広がり (m)"
    length_default = 1.0

    # ── 描画係数（サブクラスで上書き可能）────────────────────────
    DRAW_SCALE_MARGIN  = 0.85   # フィット後に掛けるマージン係数
    SEAT_RATIO         = 0.28   # 座面竹の幅（全幅に対する比率）
    SPREAD_RATIO       = 0.45   # 三脚脚の広がり比（フレーム高さに対する比）
    ROPE_HEIGHT_RATIO  = 0.22   # ロープ下端の高さ比（フレーム高さに対する比）
    ROPE_WIDTH_RATIO   = 0.22   # ロープ幅（竹径スケールに対する比）
    SEAT_EXTEND_RATIO  = 1.3    # 座面竹の張り出し比（seat_half に対する比）

    def validate(self, dims: Dimensions, weight: float) -> List[str]:
        errors = []
        if dims.height_m < 0.8:
            errors.append("ブランコのフレーム高さは0.8m以上にしてください")
        if dims.width_m < 0.5:
            errors.append("幅が狭すぎます（0.5m以上）")
        return errors

    def safety_check(
        self, dims: Dimensions, weight: float,
        allowable_stress: float = BAMBOO_ALLOWABLE_STRESS,
        bamboo_e: float = BAMBOO_E,
    ) -> Tuple[List[CheckMessage], bool]:
        msgs, danger = self._common_checks(dims, weight)
        D  = dims.diameter_m
        Dc = dims.diameter_cm

        dyn_load = weight * DYNAMIC_LOAD_FACTOR

        # 横渡し竹の構造チェック（動的荷重）
        res_s = check_bending(D, dims.width_m, dyn_load, dims, allowable_stress)
        res_d = check_deflection(D, dims.width_m, dyn_load, dims, bamboo_e)

        if res_s.error:
            msgs.append(CheckMessage("注意", f"曲げ計算スキップ: {res_s.error}"))
        elif not res_s.ok:
            msgs.append(CheckMessage("危険",
                f"横渡し竹が動的荷重で折れる可能性があります（計算応力 {res_s.value:.1f} MPa）",
                f"横渡し竹を直径{Dc+2:.0f}cm以上に太くしてください。"))
            danger = True
        elif res_s.value > allowable_stress / 1e6 * WARNING_STRESS_RATIO:
            warn_thresh = allowable_stress / 1e6 * WARNING_STRESS_RATIO
            msgs.append(CheckMessage("警告",
                f"横渡し竹の動的応力が許容値の{round(WARNING_STRESS_RATIO*100)}%を超えています（{res_s.value:.1f} MPa > {warn_thresh:.1f} MPa）",
                "横渡し竹を1〜2cm太くしてください。"))
        else:
            msgs.append(CheckMessage("注意",
                f"横渡し竹 動的曲げ応力（×{DYNAMIC_LOAD_FACTOR}）：{res_s.value:.1f} MPa（許容{allowable_stress/1e6:.0f} MPa以内 ✓）"))

        if res_d.ok is False and not res_d.error:
            msgs.append(CheckMessage("警告",
                f"横渡し竹のたわみが大きすぎます（{res_d.value:.1f} mm）",
                "竹を太くするか本数を増やしてください。"))

        # ロープ荷重チェック
        if dyn_load > ROPE_DANGER_LOAD_KG:
            msgs.append(CheckMessage("危険",
                f"動的荷重が約{round(dyn_load)}kgに達します。耐荷重300kg以上のロープが必要",
                "登山用クライミングロープ（直径10mm以上）を使用してください。"))
            danger = True
        elif weight > WEIGHT_ROPE_WARNING:
            msgs.append(CheckMessage("警告",
                f"体重 {weight}kg のため動的荷重は約{round(dyn_load)}kg。耐荷重200kg以上のロープが必要",
                "登山用・アウトドア用の耐荷重200kg以上のロープ（直径8mm以上）を選んでください。"))
        else:
            msgs.append(CheckMessage("注意",
                f"ロープ動的荷重：約{round(dyn_load)}kg。耐荷重200kg以上のものを確認してください"))

        msgs.append(CheckMessage("警告",
            "接合部は竹本体より先に破損します。二重結束で固定し、毎回使用前に緩みを確認してください",
            "「8の字結び＋3回巻き」が基本です。使用前に毎回ロープを引っ張って確認してください。"))
        msgs.append(CheckMessage("警告",
            "脚を地面に30cm以上埋めるか、杭で固定してください（前後転倒防止）",
            "スコップで地面に30cm以上の穴を掘って脚を埋め、周囲を土でしっかり踏み固めてください。"))

        seat_height = dims.height_m * SEAT_HEIGHT_RATIO
        if seat_height > MAX_SEAT_HEIGHT_M:
            msgs.append(CheckMessage("警告",
                f"座面が高めです（地面から約{round(seat_height*100)}cm）",
                f"高さの設定を下げて座面が地面から{round(MAX_SEAT_HEIGHT_M*100-10)}〜{round(MAX_SEAT_HEIGHT_M*100)}cm程度になるよう調整してください。"))
        if dims.height_m > MAX_FRAME_HEIGHT_M:
            msgs.append(CheckMessage("警告",
                "フレームが高すぎます（強度・安定性に注意）",
                f"フレーム高さを{MAX_FRAME_HEIGHT_M}m以下に設定し直してください。"))

        msgs.append(CheckMessage("注意",
            f"ブランコは揺れ・飛び乗り時に静止荷重の3〜5倍（最大約{round(dyn_load)}kg相当）の力がかかります"))

        return msgs, danger

    def draw(self, dims: Dimensions) -> Tuple[str, str, List[Material]]:
        D  = dims.diameter_m
        Dc = dims.diameter_cm
        H  = dims.height_m
        W  = dims.width_m
        L  = dims.length_m
        SEAT_RATIO = self.SEAT_RATIO

        PL, PR, PT, PB = 70, 30, 50, 60
        VW, VH = 360, 320
        DW, DH = VW-PL-PR, VH-PT-PB
        sc = min(DW/W, DH/H) * self.DRAW_SCALE_MARGIN
        T  = D * sc
        fw = W * sc
        fh = H * sc

        ox  = PL + (DW-fw)/2
        gy  = PT + DH
        ty  = gy - fh
        lx  = ox
        rx  = ox + fw
        apex_y   = ty
        spread_x = fh * self.SPREAD_RATIO

        s = (f'<line x1="{ox-20:.2f}" y1="{gy:.2f}" x2="{ox+fw+20:.2f}" y2="{gy:.2f}"'
             f' stroke="{GC}" stroke-width="2.5" stroke-linecap="round"/>')
        for offx in [-spread_x*0.5, spread_x*0.3, spread_x*0.55]:
            s += bamboo_slat(lx, apex_y, lx+offx, gy, T/2)
        for offx in [spread_x*0.5, -spread_x*0.3, -spread_x*0.55]:
            s += bamboo_slat(rx, apex_y, rx+offx, gy, T/2)
        s += ell(lx, apex_y, T*0.8, T*0.8, BM, BD, 1.0)
        s += ell(rx, apex_y, T*0.8, T*0.8, BM, BD, 1.0)
        s += bamboo_slat(lx, apex_y, rx, apex_y, T/2)

        rope_top_x = (lx+rx)/2
        rope_bot_y = gy - fh*self.ROPE_HEIGHT_RATIO
        sw_w = max(1.5, T*self.ROPE_WIDTH_RATIO)
        seat_half = fw*(SEAT_RATIO/2)
        s += (f'<line x1="{rope_top_x:.2f}" y1="{apex_y:.2f}"'
              f' x2="{rope_top_x-seat_half:.2f}" y2="{rope_bot_y:.2f}"'
              f' stroke="{ROPE}" stroke-width="{sw_w:.2f}" stroke-dasharray="5,3"/>')
        s += (f'<line x1="{rope_top_x:.2f}" y1="{apex_y:.2f}"'
              f' x2="{rope_top_x+seat_half:.2f}" y2="{rope_bot_y:.2f}"'
              f' stroke="{ROPE}" stroke-width="{sw_w:.2f}" stroke-dasharray="5,3"/>')
        s += bamboo_slat(rope_top_x-seat_half*self.SEAT_EXTEND_RATIO, rope_bot_y,
                         rope_top_x+seat_half*self.SEAT_EXTEND_RATIO, rope_bot_y, T/2)
        s += dim_h(ox, ox+fw, gy+30, W)
        s += dim_v(ox-44, apex_y, gy, H)
        svg_side = make_svg(VW, VH, s, "側面図（三脚ブランコ）")

        TVW, TVH = 360, 320
        TDW, TDH = TVW-PL-PR, TVH-PT-PB
        tsc = min(TDW/W, TDH/L) * self.DRAW_SCALE_MARGIN
        TT  = D * tsc
        tw  = W * tsc
        td  = L * tsc
        tx  = PL + (TDW-tw)/2
        ty2 = PT + (TDH-td)/2
        mid_y = ty2 + td/2

        t2 = ""
        t2 += (f'<rect x="{tx:.2f}" y="{mid_y-TT/2:.2f}" width="{tw:.2f}" height="{TT:.2f}"'
               f' rx="{TT/2:.2f}" fill="{BF}" stroke="{BD}" stroke-width="0.8"/>')
        for cx, pts in [
            (tx,    [(-td*0.30, 0), (td*0.20,-td*0.45), (td*0.20, td*0.45)]),
            (tx+tw, [( td*0.30, 0), (-td*0.20,-td*0.45), (-td*0.20, td*0.45)]),
        ]:
            for (dx, dy) in pts:
                t2 += bamboo_slat(cx, mid_y, cx+dx, mid_y+dy, TT/2)
            for (dx, dy) in pts:
                t2 += bamboo_top(cx+dx, mid_y+dy, TT/2, TT*0.42)
            t2 += bamboo_top(cx, mid_y, TT*0.9, TT*0.42)

        seat_cx = tx + tw/2
        t2 += (f'<rect x="{seat_cx-TT/2:.2f}" y="{mid_y-td*0.08:.2f}"'
               f' width="{TT:.2f}" height="{td*0.16:.2f}"'
               f' rx="{TT/2:.2f}" fill="{BF}" stroke="{BD}" stroke-width="0.6"/>')
        t2 += dim_h(tx-td*0.3, tx+tw+td*0.3, ty2+td+30, W)
        t2 += dim_v(tx-td*0.3-40, ty2, ty2+td, L)
        svg_top = make_svg(TVW, TVH, t2, "上面図（三脚ブランコ）")

        pole_len = math.sqrt(H**2 + (L/2)**2)
        rope_len = round(H * 0.8 * 100)
        materials = [
            Material(f"支柱竹（三脚用） 直径{Dc:.0f}cm", round(pole_len*100),        6),
            Material(f"横渡し竹         直径{Dc:.0f}cm", round(W*100),               1),
            Material(f"座面竹           直径{Dc:.0f}cm", round(W*SEAT_RATIO*100),    1),
            Material("ロープ",                           rope_len,                    2, is_rope=True),
        ]
        return svg_side, svg_top, materials


# ──────────────────────── ジャングルジム ──────────────────────────
class JungleGymPlugin(ToolPlugin):
    name           = "ジャングルジム"
    width_label    = "底面の直径 (m)"
    length_label   = None   # ジャングルジムは奥行きパラメータ不要
    length_default = 1.0

    # ── 描画係数（サブクラスで上書き可能）────────────────────────
    DRAW_SCALE_MARGIN  = 0.85   # フィット後に掛けるマージン係数
    N_POLES            = 6      # 脚の本数
    RING_RATIOS        = (0.33, 0.62)  # 横輪の高さ比（下段・上段）
    RING_RY_RATIO      = 0.55   # 横輪楕円の短径比（竹径スケールに対する比）
    RING_WIDTH_RATIO   = 0.9    # 横輪の線幅比
    RING_HL_RATIO      = 0.3    # 横輪ハイライト線幅比
    RING_TOP_RY_RATIO  = 0.28   # 上面図横輪の線幅比
    APEX_SCALE         = 1.2    # 頂点ジョイントの半径倍率

    def validate(self, dims: Dimensions, weight: float) -> List[str]:
        errors = []
        if dims.height_m < 0.5:
            errors.append("高さが低すぎます（0.5m以上）")
        if dims.width_m < 0.5:
            errors.append("底面直径が小さすぎます（0.5m以上）")
        return errors

    def safety_check(
        self, dims: Dimensions, weight: float,
        allowable_stress: float = BAMBOO_ALLOWABLE_STRESS,
        bamboo_e: float = BAMBOO_E,
    ) -> Tuple[List[CheckMessage], bool]:
        msgs, danger = self._common_checks(dims, weight)
        D  = dims.diameter_m
        Dc = dims.diameter_cm

        pole_len = math.sqrt((dims.width_m/2)**2 + dims.height_m**2)
        res_s = check_bending(D, pole_len, weight, dims, allowable_stress)

        if res_s.error:
            msgs.append(CheckMessage("注意", f"曲げ計算スキップ: {res_s.error}"))
        elif not res_s.ok:
            msgs.append(CheckMessage("危険",
                f"主柱竹が折れる可能性があります（計算応力 {res_s.value:.1f} MPa）",
                f"主柱の竹を直径{Dc+2:.0f}cm以上に太くしてください。"))
            danger = True
        elif res_s.value > allowable_stress / 1e6 * WARNING_STRESS_RATIO:
            warn_thresh = allowable_stress / 1e6 * WARNING_STRESS_RATIO
            msgs.append(CheckMessage("警告",
                f"主柱竹の応力が許容値の{round(WARNING_STRESS_RATIO*100)}%を超えています（{res_s.value:.1f} MPa > {warn_thresh:.1f} MPa）",
                "主柱を1〜2cm太くするか高さを少し低くしてください。"))
        else:
            msgs.append(CheckMessage("注意",
                f"主柱竹 曲げ応力：{res_s.value:.1f} MPa（許容{allowable_stress/1e6:.0f} MPa以内 ✓）"))

        msgs.append(CheckMessage("警告",
            "接合部は竹本体より先に破損します。二重結束で固定し、毎回使用前に緩みを確認してください",
            "「8の字結び＋3回巻き」が基本です。"))
        msgs.append(CheckMessage("警告",
            "各脚の先端を地面に20cm以上埋めるか、重石で固定してください（横転防止）",
            "各脚を地面に20cm以上差し込んで踏み固めてください。"))

        if weight >= 40 and dims.height_m > 2.0:
            msgs.append(CheckMessage("警告",
                "高さが高すぎます（転落リスク）",
                "高さを2.0m以下に設定し直してください。"))

        return msgs, danger

    def draw(self, dims: Dimensions) -> Tuple[str, str, List[Material]]:
        D  = dims.diameter_m
        Dc = dims.diameter_cm
        H  = dims.height_m
        W  = dims.width_m
        n_poles = self.N_POLES

        PL, PR, PT, PB = 70, 30, 50, 60
        VW, VH = 360, 340
        DW, DH = VW-PL-PR, VH-PT-PB
        sc = min(DW/W, DH/H) * self.DRAW_SCALE_MARGIN
        T  = D * sc
        fw = W * sc
        fh = H * sc

        cx_s = PL + DW/2
        gy   = PT + DH
        ay   = gy - fh

        s = (f'<line x1="{cx_s-fw/2-20:.2f}" y1="{gy:.2f}"'
             f' x2="{cx_s+fw/2+20:.2f}" y2="{gy:.2f}"'
             f' stroke="{GC}" stroke-width="2.5" stroke-linecap="round"/>')

        angles = [i * (360/n_poles) for i in range(n_poles)]
        feet   = [cx_s + (fw/2)*math.cos(math.radians(a)) for a in angles]
        # 後ろの脚を先に描画（奥行き表現）
        for i, fx in enumerate(feet):
            if 60 <= angles[i] <= 300:
                s += bamboo_slat(cx_s, ay, fx, gy, T/2)
        for i, fx in enumerate(feet):
            if not (60 <= angles[i] <= 300):
                s += bamboo_slat(cx_s, ay, fx, gy, T/2)

        for ratio in self.RING_RATIOS:
            ring_y = ay + fh*ratio
            ring_r = (fw/2)*ratio
            s += (f'<ellipse cx="{cx_s:.2f}" cy="{ring_y:.2f}"'
                  f' rx="{ring_r:.2f}" ry="{T*self.RING_RY_RATIO:.2f}"'
                  f' fill="none" stroke="{BD}" stroke-width="{T*self.RING_WIDTH_RATIO:.2f}" opacity="0.85"/>')
            s += (f'<ellipse cx="{cx_s:.2f}" cy="{ring_y:.2f}"'
                  f' rx="{ring_r:.2f}" ry="{T*self.RING_RY_RATIO:.2f}"'
                  f' fill="none" stroke="{BL}" stroke-width="{T*self.RING_HL_RATIO:.2f}" opacity="0.4"/>')

        s += ell(cx_s, ay, T*self.APEX_SCALE, T*self.APEX_SCALE, BM, BD, 1.2)
        s += dim_h(cx_s-fw/2, cx_s+fw/2, gy+30, W)
        s += dim_v(cx_s-fw/2-44, ay, gy, H)
        svg_side = make_svg(VW, VH, s, f"側面図（円錐型 {n_poles}本）")

        TVW, TVH = 360, 360
        TDW, TDH = TVW-PL-PR, TVH-PT-PB
        tsc = min(TDW/W, TDH/W) * self.DRAW_SCALE_MARGIN
        TT  = D * tsc
        tr  = W * tsc/2
        tcx = PL + TDW/2
        tcy = PT + TDH/2

        t2 = ""
        t2 += (f'<circle cx="{tcx:.2f}" cy="{tcy:.2f}" r="{tr:.2f}"'
               f' fill="none" stroke="{GC}" stroke-width="1.5" stroke-dasharray="6,4"/>')
        for i in range(n_poles):
            ang = math.radians(i*60)
            fx  = tcx + tr*math.cos(ang)
            fy  = tcy + tr*math.sin(ang)
            t2 += bamboo_slat(tcx, tcy, fx, fy, TT/2)
        for ratio in self.RING_RATIOS:
            rr2 = tr*ratio
            t2 += (f'<circle cx="{tcx:.2f}" cy="{tcy:.2f}" r="{rr2:.2f}"'
                   f' fill="none" stroke="{BD}" stroke-width="{TT*self.RING_WIDTH_RATIO:.2f}" opacity="0.8"/>')
            t2 += (f'<circle cx="{tcx:.2f}" cy="{tcy:.2f}" r="{rr2:.2f}"'
                   f' fill="none" stroke="{BL}" stroke-width="{TT*self.RING_TOP_RY_RATIO:.2f}" opacity="0.4"/>')
        t2 += bamboo_top(tcx, tcy, TT*self.APEX_SCALE, TT*0.42)
        for i in range(n_poles):
            ang = math.radians(i*60)
            t2 += bamboo_top(tcx+tr*math.cos(ang), tcy+tr*math.sin(ang), TT/2, TT*0.42)
        t2 += dim_h(tcx-tr, tcx+tr, tcy+tr+30, W)
        svg_top = make_svg(TVW, TVH, t2, f"上面図（円錐型 {n_poles}本）")

        pole_len   = math.sqrt((W/2)**2 + H**2)
        OVERLAP_CM = 12
        r1_chord   = 2*(W/2)*self.RING_RATIOS[0]*math.sin(math.pi/n_poles)
        r2_chord   = 2*(W/2)*self.RING_RATIOS[1]*math.sin(math.pi/n_poles)
        rope_len   = round(Dc*math.pi*4 + 40)
        materials  = [
            Material(f"主柱竹（傾斜）  直径{Dc:.0f}cm", round(pole_len*100),              n_poles),
            Material(f"横渡し竹（下段）直径{Dc:.0f}cm", round(r1_chord*100)+OVERLAP_CM,  n_poles),
            Material(f"横渡し竹（上段）直径{Dc:.0f}cm", round(r2_chord*100)+OVERLAP_CM,  n_poles),
            Material("結束ロープ（頂点用）",             rope_len,                         1, is_rope=True),
        ]
        return svg_side, svg_top, materials


# ══════════════════════════════════════════════════════════════════
# プラグインレジストリ（ここに追加するだけで遊具が増える）
# ══════════════════════════════════════════════════════════════════
REGISTRY: dict[str, ToolPlugin] = {
    plugin.name: plugin for plugin in [
        SlidePlugin(),
        SwingPlugin(),
        JungleGymPlugin(),
        # ← ここに新しい ToolPlugin サブクラスのインスタンスを追加するだけ
    ]
}


# ══════════════════════════════════════════════════════════════════
# CSS / UIヘルパー
# ══════════════════════════════════════════════════════════════════
GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Zen+Maru+Gothic:wght@400;500;700&family=M+PLUS+Rounded+1c:wght@400;700&display=swap');
html, body, [class*="css"], .stMarkdown, p, div, span, label, button {
    font-family: 'Zen Maru Gothic', 'M PLUS Rounded 1c', 'Hiragino Maru Gothic Pro', sans-serif !important;
}
.block-container { padding: 1.2rem 1.5rem 2rem; max-width: 1200px; }
@media(max-width:768px) { .block-container { padding: 0.5rem 0.5rem 1rem; } }
h1 {
    font-family: 'Zen Maru Gothic', sans-serif !important;
    font-size: 2.2rem !important; font-weight: 700 !important;
    color: #3d7a3d !important; letter-spacing: 0.06em;
    text-shadow: 1px 2px 6px #b8e6b860;
    padding-bottom: 0.2em; border-bottom: 3px solid #a8d5a2; margin-bottom: 1rem !important;
}
h2, h3 { font-family: 'Zen Maru Gothic', sans-serif !important; font-weight: 700 !important; color: #2e6e2e !important; letter-spacing: 0.04em; }
.alert-box {
    border-radius: 14px; padding: 10px 14px; margin: 4px 0;
    font-size: 0.88rem; line-height: 1.55; font-family: 'Zen Maru Gothic', sans-serif;
    display: flex; align-items: flex-start; gap: 8px; border-left: 5px solid;
}
.alert-box .icon { font-size: 1.1rem; flex-shrink: 0; margin-top: 1px; }
.alert-box .text { flex: 1; }
.alert-kiken   { background: #ffe0e6; border-left-color: #e05577; color: #7a1a2e; }
.alert-keikoku { background: #fff0d8; border-left-color: #e8903a; color: #7a4010; }
.alert-chui    { background: #e2f0ff; border-left-color: #5aa3d8; color: #1a3a5a; }
.summary-danger  { background: linear-gradient(135deg,#ffd6de,#ffb3c4); border: 2px solid #e05577; border-radius: 16px; padding: 14px 18px; color: #6a0a20; font-weight: 700; font-size: 1.02rem; margin: 10px 0 6px; text-align: center; letter-spacing: 0.03em; }
.summary-warning { background: linear-gradient(135deg,#ffe9c0,#ffd98a); border: 2px solid #e8903a; border-radius: 16px; padding: 14px 18px; color: #5a3000; font-weight: 700; font-size: 1.02rem; margin: 10px 0 6px; text-align: center; letter-spacing: 0.03em; }
.summary-ok      { background: linear-gradient(135deg,#d4f5d4,#b3e8b3); border: 2px solid #5aaa4a; border-radius: 16px; padding: 14px 18px; color: #1a5a1a; font-weight: 700; font-size: 1.02rem; margin: 10px 0 6px; text-align: center; letter-spacing: 0.03em; }
.disclaimer-box { background: #f5eeff; border: 1.5px solid #c09ae0; border-radius: 14px; padding: 12px 16px; color: #4a1a7a; font-size: 0.87rem; line-height: 1.6; margin-bottom: 1rem; }
.important-box  { background: linear-gradient(135deg,#fff0f5,#ffe0ec); border: 2px solid #e05577; border-radius: 14px; padding: 12px 16px; color: #7a1a2e; font-size: 0.87rem; line-height: 1.7; margin: 10px 0; }
.important-box strong { color: #c0002a; font-size: 0.95rem; }
.alert-advice { margin-top: 7px; padding: 7px 11px; background: rgba(255,255,255,0.65); border-radius: 8px; border-left: 3px solid rgba(0,0,0,0.15); font-size: 0.83rem; color: inherit; line-height: 1.55; }
details { border-radius: 12px; overflow: hidden; margin: 4px 0; }
details summary { cursor: pointer; list-style: none; padding: 0; }
details summary::-webkit-details-marker { display: none; }
.stButton > button { font-family: 'Zen Maru Gothic', sans-serif !important; border-radius: 30px !important; background: linear-gradient(135deg, #5aaa4a, #3d8a3d) !important; color: white !important; font-weight: 700 !important; font-size: 1.05rem !important; border: none !important; letter-spacing: 0.05em; padding: 0.5rem 1rem !important; transition: box-shadow 0.2s; }
.stButton > button:hover { box-shadow: 0 4px 16px #3d8a3d60 !important; }
div[data-testid="stAlert"] { border-radius: 12px !important; font-family: 'Zen Maru Gothic', sans-serif !important; }
button[data-testid="collapsedControl"] { display: none !important; }
</style>
"""


def alert_html(level: str, msg: str, advice: str = "") -> str:
    cfg = {
        "危険": ("alert-kiken",   "🚨", "危険"),
        "警告": ("alert-keikoku", "⚠️", "警告"),
        "注意": ("alert-chui",    "ℹ️", "注意"),
    }
    cls, icon, label = cfg.get(level, ("alert-chui", "ℹ️", level))
    adv_html = f'<div class="alert-advice">💡 改善方法：{html.escape(advice)}</div>' if advice else ""
    return (f'<div class="alert-box {cls}">'
            f'<span class="icon">{icon}</span>'
            f'<span class="text"><strong>{label}：</strong>{html.escape(msg)}{adv_html}</span>'
            f'</div>')


def make_accordion(
    label: str, content_html: str,
    header_color: str, border_color: str, open_: bool = False
) -> str:
    open_attr = "open" if open_ else ""
    return f"""
<details {open_attr} style="border:2px solid {border_color};border-radius:12px;margin-bottom:6px;overflow:hidden;">
  <summary style="background:{header_color};padding:10px 16px;font-family:'Zen Maru Gothic',sans-serif;font-weight:700;font-size:0.95rem;color:#333;cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center;">
    <span>{label}</span><span style="font-size:0.8rem;color:#888;">▼</span>
  </summary>
  <div style="padding:10px 12px 12px;background:#fff;">{content_html}</div>
</details>"""


def render_safety_messages(messages: List[CheckMessage], danger: bool):
    kiken   = [m for m in messages if m.level == "危険"]
    keikoku = [m for m in messages if m.level == "警告"]
    chui    = [m for m in messages if m.level == "注意"]

    wc = len(keikoku)
    if danger:
        st.markdown('<div class="summary-danger">🚫 この設計は危険です。赤の項目を必ず解消してから製作してください</div>',
                    unsafe_allow_html=True)
    elif wc >= 2:
        st.markdown('<div class="summary-warning">⚠️ 警告が複数あります。黄色の項目をすべて改善してから製作してください</div>',
                    unsafe_allow_html=True)
    elif wc == 1:
        st.markdown('<div class="summary-warning">⚠️ 警告事項があります。黄色の項目を改善してから製作してください</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="summary-ok">✅ 計算上は安全範囲です（ただし専門家確認を推奨）</div>',
                    unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        body = "".join(alert_html(m.level, m.msg, m.advice) for m in kiken) or "<p style='color:#888;margin:4px 0;'>危険項目はありません ✓</p>"
        st.markdown(make_accordion(f"🚨 危険　{len(kiken)}件", body, "#ffe0e6", "#e05577", bool(kiken)), unsafe_allow_html=True)
    with col2:
        body = "".join(alert_html(m.level, m.msg, m.advice) for m in keikoku) or "<p style='color:#888;margin:4px 0;'>警告項目はありません ✓</p>"
        st.markdown(make_accordion(f"⚠️ 警告　{len(keikoku)}件", body, "#fff0d8", "#e8903a", bool(keikoku)), unsafe_allow_html=True)
    with col3:
        body = "".join(alert_html(m.level, m.msg, m.advice) for m in chui) or "<p style='color:#888;margin:4px 0;'>注意項目はありません</p>"
        st.markdown(make_accordion(f"ℹ️ 注意　{len(chui)}件", body, "#e2f0ff", "#5aa3d8", False), unsafe_allow_html=True)

    important_body = """
<div class="important-box">
<strong>🔴 このアプリの計算はあくまで参考値です。</strong><br>
・設計に警告・危険が1つでもある場合は絶対に避けてください。<br>
・現場では必ず有資格者（建築士・構造専門家）の安全確認を受けてください。<br>
・竹は乾燥・節・割れ等で現物強度が大きく変化します。十分な安全マージンが必要です。<br>
・施工後も毎回点検し、劣化・割れ・緩みがあれば絶対に使わないでください。<br>
・太く肉厚な竹を選び、節を支点として配置し、定期的な点検を徹底してください。
</div>"""
    st.markdown(make_accordion("🔴 重要アドバイス（必ずお読みください）", important_body, "#f5eeff", "#c09ae0", False), unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# Streamlit メインUI
# ══════════════════════════════════════════════════════════════════
def main():
    st.set_page_config(page_title="竹あそび", layout="wide")
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
    st.title("🎋 竹あそび")
    st.markdown("""
<div class="disclaimer-box">
⚠️ <strong>免責事項：</strong>このアプリの計算は参考値です。
竹は天然材料であり個体差が大きく、計算通りの強度が保証されません。
実際に遊具を製作・使用する場合は、専門家（建築士・構造技術者）による確認を必ず行ってください。
本アプリは安全性を保証するものではありません。
</div>""", unsafe_allow_html=True)

    tool_names = list(REGISTRY.keys())

    with st.sidebar:
        st.header("⚙️ 設定")
        tool_name = st.selectbox("遊具の種類", tool_names)
        plugin    = REGISTRY[tool_name]

        # 竹の種類選択（ヤング係数・許容応力に反映）
        bamboo_kind = st.selectbox("竹の種類", list(BAMBOO_SPECS.keys()))
        spec = BAMBOO_SPECS[bamboo_kind]
        st.caption(f"ℹ️ {spec['note']}"
                   f"　E = {spec['E']/1e9:.0f} GPa　許容応力 = {spec['sigma']/1e6:.0f} MPa")

        diameter = st.number_input("竹の直径 (cm)", value=8.0, min_value=2.0, max_value=20.0, step=0.5)
        height   = st.number_input("高さ (m)",      value=1.2, min_value=0.3, max_value=3.0,  step=0.1)
        width    = st.number_input(plugin.width_label,  value=1.2, min_value=0.3, max_value=3.0, step=0.1)
        if plugin.length_label is not None:
            length = st.number_input(plugin.length_label, value=float(plugin.length_default),
                                     min_value=0.5, max_value=6.0, step=0.1)
        else:
            length = float(plugin.length_default)  # 使わないがDimensionsに渡す既定値
        weight   = st.number_input("使用者の最大体重 (kg)", value=30, min_value=5, max_value=120, step=5)
        draw_btn = st.button("図面を作る", use_container_width=True)

    if draw_btn:
        dims = Dimensions(
            height_m=height,
            width_m=width,
            length_m=length,
            diameter_m=diameter / 100,
        )

        # ── 入力バリデーション ──
        errors = plugin.validate(dims, float(weight))
        if errors:
            for e in errors:
                st.error(f"⛔ 入力エラー：{e}")
            st.stop()

        # ── 安全チェック ──
        try:
            messages, danger = plugin.safety_check(
                dims, float(weight),
                allowable_stress=spec["sigma"],
                bamboo_e=spec["E"],
            )
        except Exception as e:
            logger.error("safety_check failed: %s", e)
            st.error(f"安全チェック中にエラーが発生しました: {e}")
            st.stop()

        st.subheader("🔍 安全チェック結果")
        render_safety_messages(messages, danger)
        st.divider()

        # ── 図面描画 ──
        try:
            svg_side, svg_top, materials = plugin.draw(dims)
        except Exception as e:
            logger.error("draw failed: %s", e)
            st.error(f"図面の生成中にエラーが発生しました: {e}")
            st.stop()

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(svg_side, unsafe_allow_html=True)
        with col2:
            st.markdown(svg_top, unsafe_allow_html=True)

        st.divider()
        st.subheader(f"🎋 直径 {diameter}cm の竹　材料リスト")

        table_data    = []
        bamboo_total  = 0
        for m in materials:
            tag = "（縄）" if m.is_rope else "（木材）" if m.is_wood else ""
            table_data.append({"部材名": m.name + tag, "長さ (cm)": m.length_cm, "本数": m.count})
            if not m.is_rope and not m.is_wood:
                bamboo_total += m.count

        st.table(table_data)
        st.success(f"🎋 竹　合計：{bamboo_total} 本")

        # ── CSVエクスポート ──
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["部材名", "長さ (cm)", "本数"])
        writer.writeheader()
        writer.writerows(table_data)
        st.download_button(
            label="📥 材料リストをCSVで保存",
            data=buf.getvalue().encode("utf-8-sig"),  # BOM付きでExcel対応
            file_name=f"{tool_name}_材料リスト.csv",
            mime="text/csv",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
