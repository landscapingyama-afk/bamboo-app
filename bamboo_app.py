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

import csv
import html
import io
import math
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple, Optional

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

# ── 構造安全率（QA推奨）────────────────────────────────────────────
# 竹の個体差・計算モデルの誤差・動的効果の残余リスクを考慮し、
# 許容応力を安全率で除したものを「実効許容応力」として使用する。
# EN 1176（遊具安全基準）・JIS A 8304 参考。
STRUCTURAL_SAFETY_FACTOR = 3.0

# ── 竹の状態係数テーブル ─────────────────────────────────────────
# 経年劣化・損傷状態が強度に与える影響を係数で表す。
# 係数は STRUCTURAL_SAFETY_FACTOR と掛け合わせて実効許容応力に反映される。
# None = 計算拒否（使用禁止）
BAMBOO_CONDITION_FACTORS: dict[str, Optional[float]] = {
    "新品・良好（割れ・虫食いなし）":   1.0,
    "1〜2年経過（目視異常なし）":        0.8,
    "微細なひび・変色あり（要注意）":    0.5,
    "割れあり / 虫食いあり（使用禁止）": None,
}

BAMBOO_CONDITION_NOTES: dict[str, str] = {
    "新品・良好（割れ・虫食いなし）":   "乾燥済みで表面・断面に異常なし。標準強度で計算します。",
    "1〜2年経過（目視異常なし）":        "経年劣化を考慮し強度を20%割り引いて計算します。月1回点検を推奨。",
    "微細なひび・変色あり（要注意）":    "強度を50%割り引いて計算します。早期交換を強く推奨。",
    "割れあり / 虫食いあり（使用禁止）": "計算の余地なく使用禁止です。直ちに新しい竹に交換してください。",
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
# SVGサニタイゼーション（ホワイトリスト方式）
# ══════════════════════════════════════════════════════════════════
# 【設計方針】
#   ブロックリスト方式（危険なものを除去）は foreignObject・use・animate・
#   data:URI などの迂回ルートを完全に塞げない。
#   ホワイトリスト方式（許可したタグ・属性のみ通す）に変更し、
#   未知の攻撃ベクタに対しても安全を確保する。

# 許可するSVGタグ（アプリ内で実際に使用するもののみ）
_SVG_ALLOWED_TAGS: set = {
    "svg", "g", "circle", "ellipse", "line", "path",
    "polygon", "polyline", "rect", "text", "tspan",
}

# 許可する属性（タグ共通）
_SVG_ALLOWED_ATTRS: set = {
    # 座標・寸法
    "cx", "cy", "r", "rx", "ry",
    "x", "y", "x1", "y1", "x2", "y2",
    "width", "height", "viewBox", "xmlns",
    "points", "d",
    # スタイル
    "fill", "stroke", "stroke-width", "stroke-dasharray",
    "stroke-linecap", "stroke-linejoin", "opacity",
    "font-size", "font-weight", "font-family",
    "text-anchor", "dominant-baseline",
    # 変換
    "transform",
    # メタ（href・xlink:href は意図的に除外して data:/javascript: を封鎖）
    "style",
}

_TAG_RE    = re.compile(r'<(/?)(\w[\w\-]*)((?:\s+[^>]*?)?)\s*(/?)>', re.DOTALL)
_ATTR_RE   = re.compile(r'([\w\-]+)\s*=\s*(?:"([^"]*?)"|\'([^\']*?)\'|(\S+))', re.DOTALL)


def _sanitize_attrs(attr_str: str) -> str:
    """属性文字列からホワイトリスト外の属性を除去して返す。"""
    out_parts = []
    for m in _ATTR_RE.finditer(attr_str):
        name = m.group(1).lower()
        val  = m.group(2) or m.group(3) or m.group(4) or ""
        if name not in _SVG_ALLOWED_ATTRS:
            continue
        # 属性値に javascript: / data: が含まれていれば除去
        if re.search(r'(javascript|data)\s*:', val, re.IGNORECASE):
            continue
        out_parts.append(f'{name}="{html.escape(val)}"')
    return (" " + " ".join(out_parts)) if out_parts else ""


def sanitize_svg_content(value: str) -> str:
    """
    SVGコンテンツをホワイトリスト方式でサニタイズする。
    許可リスト外のタグ・属性・プロトコルを完全に除去する。
    処理順序：
      1. コンテンツごと除去すべき危険タグ（script/style等）を内容ごと削除
      2. ホワイトリスト外のタグを除去（属性のみクリーンな許可タグを残す）
    """
    # Step1: 危険タグはコンテンツ（タグ間テキスト）ごと除去
    _DANGEROUS_WITH_CONTENT = re.compile(
        r'<(script|style|set|handler|listener)[\s\S]*?</\1\s*>',
        re.IGNORECASE
    )
    value = _DANGEROUS_WITH_CONTENT.sub('', value)
    # 自己終了タグ形式の危険タグも除去
    value = re.sub(
        r'<(script|style|set|handler|listener|animate|animatetransform|animatemotion'
        r'|discard|use|image|foreignobject|iframe|embed|object|link|meta|base|form'
        r'|input|button|video|audio)(\s[^>]*)?>',
        '', value, flags=re.IGNORECASE
    )

    # Step2: ホワイトリスト外タグを除去（許可タグの属性もクリーンにする）
    def replace_tag(m: re.Match) -> str:
        close   = m.group(1)
        tag     = m.group(2).lower()
        attrs   = m.group(3)
        self_cl = m.group(4)
        if tag not in _SVG_ALLOWED_TAGS:
            return ""
        safe_attrs = _sanitize_attrs(attrs)
        if self_cl:
            return f"<{close}{tag}{safe_attrs}/>"
        return f"<{close}{tag}{safe_attrs}>"

    return _TAG_RE.sub(replace_tag, value)


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


def load_marker(cx: float, cy: float, r: float = 10, label: str = "荷重集中・接合注意",
                label_side: str = "right") -> str:
    """
    荷重集中点・接合部の静的警告マーカーを返す（animate不使用）。
    赤い半透明の円＋ラベルを描画する。
    cx, cy: SVG座標上の中心位置
    r: マーカー半径（px）
    label_side: "right"（右にラベル）または "left"（左にラベル・右端切れ防止）
    """
    if label_side == "left":
        lx = cx - r - 3
        anchor = "end"
    else:
        lx = cx + r + 3
        anchor = "start"
    return (
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}"'
        f' fill="#e53935" opacity="0.32" stroke="#b71c1c" stroke-width="1.2"/>'
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r*0.35:.2f}"'
        f' fill="#b71c1c" opacity="0.75"/>'
        f'<text x="{lx:.2f}" y="{cy+4:.2f}" text-anchor="{anchor}"'
        f' font-size="9" fill="#b71c1c" font-weight="bold">{label}</text>'
    )


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

        # ── QAチームからの最終警告（全遊具共通）──
        msgs.append(CheckMessage("注意",
            "【QA最終警告①】数値の過信禁止：この計算は材料の均質性を前提としています。節の直上への集中荷重は避けてください。"))
        msgs.append(CheckMessage("注意",
            "【QA最終警告②】接合部の点検：図面上の赤色マーカー部分はロープ・ビスの緩み一つで崩壊につながります。使用前に必ず確認してください。"))
        msgs.append(CheckMessage("注意",
            "【QA最終警告③】環境要因：雨天後の竹は強度が変化します。使用のたびに目視確認を行ってください。"))

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
                "竹を1〜2cm太くするか横材を増やしてください。"))
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
        # ── 階段（上り用・縦桟+踏み板・約30度傾けて設置）──
        # 階段は左側支柱（sx,gy）から斜め左下へ広がる
        # 傾き約30度：縦桟の下端は上端より左にずれる
        stair_h = sh   # 縦桟の高さ（滑り台と同じ高さ）
        stair_lean = stair_h * math.tan(math.radians(30))  # 30度傾きによる水平オフセット
        stair_w = max(lw * 0.65, 3.5)   # 縦桟の太さ
        # 左縦桟：上端(sx-lw, sy)  下端(sx-lw-stair_lean, gy)
        lc_tx = sx - lw;           lc_ty = sy
        lc_bx = sx - lw - stair_lean; lc_by = gy
        # 右縦桟：上端(sx-lw+stair_w, sy)  下端(sx-lw+stair_w-stair_lean, gy)
        rc_tx = lc_tx + stair_w;   rc_ty = sy
        rc_bx = lc_bx + stair_w;  rc_by = gy
        # 縦桟（線として描画）
        s += (f'<line x1="{lc_tx:.2f}" y1="{lc_ty:.2f}" x2="{lc_bx:.2f}" y2="{lc_by:.2f}"'
              f' stroke="{WF}" stroke-width="{stair_w:.2f}" stroke-linecap="round"/>')
        s += (f'<line x1="{rc_tx:.2f}" y1="{rc_ty:.2f}" x2="{rc_bx:.2f}" y2="{rc_by:.2f}"'
              f' stroke="{WD}" stroke-width="{stair_w*0.7:.2f}" stroke-linecap="round"/>')
        # 踏み板（各段：横方向、縦桟の途中点を結ぶ）
        stair_steps = max(2, min(4, round(H / 0.3)))
        step_h_px = max(T * 0.22, 2)
        for si in range(stair_steps):
            frac = (si + 1) / (stair_steps + 1)
            # 左縦桟上の点
            px_l = lc_tx + (lc_bx - lc_tx) * frac
            py_l = lc_ty + (lc_by - lc_ty) * frac
            # 右縦桟上の点
            px_r = rc_tx + (rc_bx - rc_tx) * frac
            py_r = rc_ty + (rc_by - rc_ty) * frac
            s += (f'<line x1="{px_l:.2f}" y1="{py_l:.2f}" x2="{px_r:.2f}" y2="{py_r:.2f}"'
                  f' stroke="{WF}" stroke-width="{step_h_px:.2f}" stroke-linecap="round"/>')
        # ── 荷重集中点マーカー（支点・フレーム接合部）──
        s += load_marker(sx, gy, r=9, label="支点・接合注意")
        s += load_marker(ex, gy, r=9, label="支点・接合注意", label_side="left")
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

        # パイプ長さ = 滑り台の幅（端板と同じ）、本数 = 横材本数と同数
        pipe_len_cm = round(W * 100)
        # 垂木ブロック幅（1個あたり）：8cm×8cm を基準とする（参考値）
        bracket_w_cm = 8   # 片側8cm固定（両端で+16cm がパイプ余長）
        # 竹の長さ = パイプ長さ - 垂木ブロック幅 × 2（両端の固定代）
        bamboo_len_cm = pipe_len_cm - bracket_w_cm * 2
        materials = [
            Material(f"滑り面横材 直径{Dc:.0f}cm",          bamboo_len_cm,        num),
            Material(f"直管パイプ（芯材・φ推奨{max(19,round(Dc*0.27))}mm）",
                     pipe_len_cm, num, is_wood=False),
            Material(f"手すり竹   直径{Dc:.0f}cm",          round(slope_len*100), 2),
            Material("木材フレーム（側板）",                  round(aL*100),        2, is_wood=True),
            Material("木材フレーム（端板）",                  round(W*100),         2, is_wood=True),
            Material(f"垂木ブロック(パイプ固定用)高さ{Dc:.0f}cm(参考:8cm×8cm)", bracket_w_cm, num*2, is_wood=True),
            Material("コーススレッドビス 65mm以上",           65,                   num*4, is_wood=True),
            Material("単管パイプ φ48.6mm（支柱固定用）",     150,                  2, is_wood=False),
            Material("直交クランプ（支柱連結用）",            10,                   4, is_wood=False),
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
        # ── 荷重集中点マーカー（頂点接合・ロープ取付・脚接地）──
        s += load_marker(lx, apex_y, r=10, label="頂点接合注意")
        s += load_marker(rx, apex_y, r=10, label="頂点接合注意")
        s += load_marker(rope_top_x, apex_y, r=8, label="ロープ取付")
        s += load_marker(lx, gy, r=8, label="脚接地・固定注意")
        s += load_marker(rx, gy, r=8, label="脚接地・固定注意")
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
        # ── 荷重集中点マーカー（頂点・脚接地部）──
        # 頂点はラベル付き、脚接地はラベルなし赤丸のみ（重なり防止）
        s += load_marker(cx_s, ay, r=11, label="頂点接合注意")
        for fx in feet:
            # ラベルなし赤丸のみ
            s += (f'<circle cx="{fx:.2f}" cy="{gy:.2f}" r="8"'
                  f' fill="#e53935" opacity="0.32" stroke="#b71c1c" stroke-width="1.2"/>'
                  f'<circle cx="{fx:.2f}" cy="{gy:.2f}" r="2.8"'
                  f' fill="#b71c1c" opacity="0.75"/>')
        s += dim_h(cx_s-fw/2, cx_s+fw/2, gy+30, W)
        s += dim_v(cx_s-fw/2-44, ay, gy, H)
        # 脚接地の注記を1箇所にまとめて表示
        s += (f'<text x="{cx_s:.2f}" y="{gy+52:.2f}" text-anchor="middle"'
              f' font-size="9" fill="#b71c1c" font-weight="bold">'
              f'●脚接地部・固定注意（全{n_poles}箇所）</text>')
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
        # 段結束用麻紐：1箇所あたり3〜4m × 24箇所（1段12箇所×2段）
        hemp_per_knot_cm = 350   # 1箇所あたり350cm（3〜4mの中央値）
        hemp_total_knots = n_poles * 2 * 2   # 支柱数×各支柱2箇所×2段 = 24
        materials  = [
            Material(f"主柱竹（傾斜）  直径{Dc:.0f}cm", round(pole_len*100),              n_poles),
            Material(f"横渡し竹（下段）直径{Dc:.0f}cm", round(r1_chord*100)+OVERLAP_CM,  n_poles),
            Material(f"横渡し竹（上段）直径{Dc:.0f}cm", round(r2_chord*100)+OVERLAP_CM,  n_poles),
            Material("結束ロープ（頂点用）（縄）",        rope_len,                         1, is_rope=True),
            Material(f"麻紐（1・2段結束用）3〜4m×{hemp_total_knots}箇所", hemp_per_knot_cm, hemp_total_knots, is_rope=True),
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
html, body, [class*="css"], .stMarkdown, p, div, label, button {
    font-family: 'Zen Maru Gothic', 'M PLUS Rounded 1c', 'Hiragino Maru Gothic Pro', sans-serif !important;
}
/* ── アイコンフォント保護（最重要）──
   Streamlit の Material Symbols Rounded フォントによるアイコン表示を守る。
   data-testid="stIconMaterial" の span が実際のアイコン文字（keyboard_arrow_right 等）を
   描画しており、ここに日本語フォントが継承されると英字がそのまま表示される。 */
[data-testid="stIconMaterial"],
[data-testid="stExpanderIconCheck"],
[data-testid="stExpanderIconError"],
[data-testid="stExpanderIconSpinner"],
[data-testid="stExpanderIcon"],
[data-testid="stSpinnerIcon"],
[data-testid="stImageIcon"] {
    font-family: 'Material Symbols Rounded', 'Material Icons', sans-serif !important;
}
.block-container { padding: 1.2rem 1.5rem 2rem; max-width: 1200px; }
@media(max-width:768px) {
  .block-container { padding: 0.5rem 0.5rem 1rem; }
  /* スマートフォンではStreamlitのヘッダーバー分だけ上にスペースを確保 */
  .block-container > div:first-child { padding-top: 3.5rem !important; }
}
h1 {
    font-family: 'Zen Maru Gothic', sans-serif !important;
    font-size: 2.2rem !important; font-weight: 700 !important;
    color: #3d7a3d !important; letter-spacing: 0.06em;
    text-shadow: 1px 2px 6px #b8e6b860;
    padding-bottom: 0.2em; border-bottom: 3px solid #a8d5a2; margin-bottom: 1rem !important;
    /* モバイルでヘッダーバーに隠れないよう上余白を確保 */
    padding-top: 0.2rem !important;
}
@media(max-width:768px) {
  h1 { font-size: 1.7rem !important; padding-top: 0.5rem !important; }
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

# ══════════════════════════════════════════════════════════════════
# 製作手順ガイド用 SVGイラスト
# ══════════════════════════════════════════════════════════════════

def _svg_step1_pipe() -> str:
    """① 直管パイプを用意する"""
    return '''<svg viewBox="0 0 320 120" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;height:auto;">
  <!-- パイプ本体（筒） -->
  <rect x="30" y="48" width="240" height="24" rx="4" fill="#b0bec5" stroke="#607d8b" stroke-width="1.5"/>
  <!-- 左端面（楕円） -->
  <ellipse cx="30" cy="60" rx="6" ry="12" fill="#eceff1" stroke="#607d8b" stroke-width="1.5"/>
  <!-- 右端面（楕円） -->
  <ellipse cx="270" cy="60" rx="6" ry="12" fill="#eceff1" stroke="#607d8b" stroke-width="1.5"/>
  <!-- 内腔（左） -->
  <ellipse cx="30" cy="60" rx="3" ry="7" fill="#90a4ae" stroke="none"/>
  <!-- 内腔（右） -->
  <ellipse cx="270" cy="60" rx="3" ry="7" fill="#90a4ae" stroke="none"/>
  <!-- ハイライト線 -->
  <line x1="30" y1="52" x2="270" y2="52" stroke="#cfd8dc" stroke-width="1.2" opacity="0.7"/>
  <!-- ラベル -->
  <text x="150" y="105" text-anchor="middle" font-size="12" fill="#37474f" font-family="sans-serif">直管パイプ</text>
  <text x="150" y="18" text-anchor="middle" font-size="11" fill="#546e7a" font-family="sans-serif">竹の内径に合うサイズを選ぶ</text>
</svg>'''


def _svg_step2_cut() -> str:
    """② パイプカッターで切断"""
    return '''<svg viewBox="0 0 320 130" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;height:auto;">
  <!-- パイプ左部分 -->
  <rect x="20" y="52" width="120" height="22" rx="3" fill="#b0bec5" stroke="#607d8b" stroke-width="1.5"/>
  <ellipse cx="20" cy="63" rx="5" ry="11" fill="#eceff1" stroke="#607d8b" stroke-width="1.5"/>
  <!-- パイプ右部分（切断後） -->
  <rect x="168" y="52" width="110" height="22" rx="3" fill="#b0bec5" stroke="#607d8b" stroke-width="1.5"/>
  <ellipse cx="278" cy="63" rx="5" ry="11" fill="#eceff1" stroke="#607d8b" stroke-width="1.5"/>
  <!-- 切断位置マーク -->
  <line x1="148" y1="38" x2="148" y2="90" stroke="#e53935" stroke-width="2" stroke-dasharray="4,3"/>
  <!-- パイプカッター本体 -->
  <rect x="136" y="44" width="24" height="36" rx="5" fill="#ff8f00" stroke="#e65100" stroke-width="1.5"/>
  <!-- カッター刃 -->
  <ellipse cx="148" cy="80" rx="12" ry="5" fill="#424242" stroke="#212121" stroke-width="1"/>
  <!-- ハンドル -->
  <line x1="160" y1="56" x2="178" y2="42" stroke="#795548" stroke-width="3" stroke-linecap="round"/>
  <!-- 切断寸法矢印 -->
  <line x1="20" y1="100" x2="148" y2="100" stroke="#607d8b" stroke-width="1"/>
  <polygon points="20,97 20,103 10,100" fill="#607d8b"/>
  <polygon points="148,97 148,103 158,100" fill="#607d8b"/>
  <text x="84" y="115" text-anchor="middle" font-size="11" fill="#37474f" font-family="sans-serif">滑り台の幅に合わせてカット</text>
  <text x="160" y="18" text-anchor="middle" font-size="11" fill="#546e7a" font-family="sans-serif">パイプカッターで切断</text>
</svg>'''


def _svg_step3_frame() -> str:
    """③ 垂木をカットしてビスで固定"""
    return '''<svg viewBox="0 0 320 140" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;height:auto;">
  <!-- 長い木材フレーム（横） -->
  <rect x="20" y="70" width="280" height="20" rx="3" fill="#8d6e63" stroke="#5d4037" stroke-width="1.5"/>
  <line x1="20" y1="76" x2="300" y2="76" stroke="#a1887f" stroke-width="0.8" opacity="0.5"/>
  <!-- 垂木ブロック1 -->
  <rect x="38" y="48" width="22" height="24" rx="2" fill="#a1887f" stroke="#5d4037" stroke-width="1.2"/>
  <!-- 垂木ブロック2 -->
  <rect x="98" y="48" width="22" height="24" rx="2" fill="#a1887f" stroke="#5d4037" stroke-width="1.2"/>
  <!-- 垂木ブロック3 -->
  <rect x="158" y="48" width="22" height="24" rx="2" fill="#a1887f" stroke="#5d4037" stroke-width="1.2"/>
  <!-- 垂木ブロック4 -->
  <rect x="218" y="48" width="22" height="24" rx="2" fill="#a1887f" stroke="#5d4037" stroke-width="1.2"/>
  <!-- ビス（各ブロック） -->
  <circle cx="49" cy="62" r="3" fill="#bdbdbd" stroke="#757575" stroke-width="0.8"/>
  <circle cx="109" cy="62" r="3" fill="#bdbdbd" stroke="#757575" stroke-width="0.8"/>
  <circle cx="169" cy="62" r="3" fill="#bdbdbd" stroke="#757575" stroke-width="0.8"/>
  <circle cx="229" cy="62" r="3" fill="#bdbdbd" stroke="#757575" stroke-width="0.8"/>
  <!-- 間隔矢印 -->
  <line x1="60" y1="108" x2="98" y2="108" stroke="#607d8b" stroke-width="1"/>
  <polygon points="60,105 60,111 50,108" fill="#607d8b"/>
  <polygon points="98,105 98,111 108,108" fill="#607d8b"/>
  <text x="79" y="122" text-anchor="middle" font-size="10" fill="#37474f" font-family="sans-serif">等間隔</text>
  <text x="160" y="18" text-anchor="middle" font-size="11" fill="#546e7a" font-family="sans-serif">垂木を等間隔に並べてビス固定</text>
  <!-- ラベル -->
  <text x="265" y="58" font-size="10" fill="#5d4037" font-family="sans-serif">垂木</text>
  <text x="265" y="84" font-size="10" fill="#5d4037" font-family="sans-serif">フレーム</text>
</svg>'''


def _svg_step4_node() -> str:
    """④ 竹の節をハンマーで抜く"""
    return '''<svg viewBox="0 0 320 140" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;height:auto;">
  <!-- 竹本体（筒・断面） -->
  <rect x="30" y="50" width="200" height="36" rx="6" fill="#4caf50" stroke="#2e7d32" stroke-width="1.8"/>
  <!-- 竹の内腔 -->
  <rect x="34" y="55" width="192" height="26" rx="4" fill="#81c784" stroke="none" opacity="0.5"/>
  <!-- 節（リング） -->
  <rect x="115" y="50" width="12" height="36" rx="2" fill="#388e3c" stroke="#1b5e20" stroke-width="1.2"/>
  <text x="121" y="45" text-anchor="middle" font-size="10" fill="#1b5e20" font-family="sans-serif">節</text>
  <!-- ハンマー -->
  <rect x="240" y="30" width="36" height="22" rx="4" fill="#424242" stroke="#212121" stroke-width="1.5"/>
  <line x1="252" y1="52" x2="230" y2="72" stroke="#795548" stroke-width="5" stroke-linecap="round"/>
  <!-- 叩く矢印 -->
  <line x1="235" y1="58" x2="200" y2="58" stroke="#e53935" stroke-width="2"/>
  <polygon points="200,54 200,62 188,58" fill="#e53935"/>
  <!-- 左端面 -->
  <ellipse cx="30" cy="68" rx="6" ry="18" fill="#66bb6a" stroke="#2e7d32" stroke-width="1.5"/>
  <ellipse cx="30" cy="68" rx="3" ry="10" fill="#a5d6a7" stroke="none"/>
  <text x="160" y="110" text-anchor="middle" font-size="11" fill="#1b5e20" font-family="sans-serif">ハンマーで端から叩いて節を抜く</text>
  <text x="160" y="20" text-anchor="middle" font-size="11" fill="#546e7a" font-family="sans-serif">竹の節を除去する</text>
</svg>'''


def _svg_step5_roller() -> str:
    """⑤ パイプを通した竹をフレームに並べる（正確な構造：竹はフレーム内、パイプ飛び出し部を垂木ブロックで固定）"""
    return '''<svg viewBox="0 0 340 200" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:340px;height:auto;">
  <text x="170" y="13" text-anchor="middle" font-size="11" fill="#546e7a" font-weight="bold" font-family="sans-serif">竹ローラーをフレームに組み付け</text>

  <!-- ======== フレーム左側板 ======== -->
  <rect x="60" y="32" width="14" height="108" rx="3" fill="#8B6914" stroke="#5a4008" stroke-width="1.5"/>
  <!-- ======== フレーム右側板 ======== -->
  <rect x="266" y="32" width="14" height="108" rx="3" fill="#8B6914" stroke="#5a4008" stroke-width="1.5"/>

  <!-- ======== 竹ローラー4本（フレーム内側に収まる）======== -->
  <!-- ローラー1 cy=46 -->
  <rect x="74" y="39" width="192" height="14" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="1.5"/>
  <ellipse cx="74"  cy="46" rx="4" ry="7" fill="#66bb6a" stroke="#2e7d32" stroke-width="1"/>
  <ellipse cx="266" cy="46" rx="4" ry="7" fill="#66bb6a" stroke="#2e7d32" stroke-width="1"/>
  <!-- ローラー2 cy=60 -->
  <rect x="74" y="53" width="192" height="14" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="1.5"/>
  <ellipse cx="74"  cy="60" rx="4" ry="7" fill="#66bb6a" stroke="#2e7d32" stroke-width="1"/>
  <ellipse cx="266" cy="60" rx="4" ry="7" fill="#66bb6a" stroke="#2e7d32" stroke-width="1"/>
  <!-- ローラー3 cy=74 -->
  <rect x="74" y="67" width="192" height="14" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="1.5"/>
  <ellipse cx="74"  cy="74" rx="4" ry="7" fill="#66bb6a" stroke="#2e7d32" stroke-width="1"/>
  <ellipse cx="266" cy="74" rx="4" ry="7" fill="#66bb6a" stroke="#2e7d32" stroke-width="1"/>
  <!-- ローラー4 cy=88 -->
  <rect x="74" y="81" width="192" height="14" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="1.5"/>
  <ellipse cx="74"  cy="88" rx="4" ry="7" fill="#66bb6a" stroke="#2e7d32" stroke-width="1"/>
  <ellipse cx="266" cy="88" rx="4" ry="7" fill="#66bb6a" stroke="#2e7d32" stroke-width="1"/>

  <!-- ======== パイプ（フレーム内側から垂木ブロックまで・フレーム外に出ない）======== -->
  <!-- フレーム内側x=74から垂木ブロック右端x=78まで（左側）、右側も同様 -->
  <!-- 左：フレーム内側74〜垂木ブロック右端78 -->
  <line x1="74" y1="46" x2="78" y2="46" stroke="#90a4ae" stroke-width="4" stroke-linecap="round"/>
  <line x1="74" y1="60" x2="78" y2="60" stroke="#90a4ae" stroke-width="4" stroke-linecap="round"/>
  <line x1="74" y1="74" x2="78" y2="74" stroke="#90a4ae" stroke-width="4" stroke-linecap="round"/>
  <line x1="74" y1="88" x2="78" y2="88" stroke="#90a4ae" stroke-width="4" stroke-linecap="round"/>
  <!-- 右：垂木ブロック左端262〜フレーム内側266 -->
  <line x1="262" y1="46" x2="266" y2="46" stroke="#90a4ae" stroke-width="4" stroke-linecap="round"/>
  <line x1="262" y1="60" x2="266" y2="60" stroke="#90a4ae" stroke-width="4" stroke-linecap="round"/>
  <line x1="262" y1="74" x2="266" y2="74" stroke="#90a4ae" stroke-width="4" stroke-linecap="round"/>
  <line x1="262" y1="88" x2="266" y2="88" stroke="#90a4ae" stroke-width="4" stroke-linecap="round"/>

  <!-- ======== 垂木ブロック（立方体・横幅14px）片側5個・両側10個 ======== -->
  <!-- ローラー4本: y中心=46,60,74,88。上ブロックy=32、下ブロックy=102 -->
  <!-- 間の3個: y=46,60,74（各ローラーに対応）                          -->

  <!-- ===== 左側 5個 ===== -->
  <!-- 左 ブロック1（最上）y=32 -->
  <rect x="62" y="32" width="14" height="14" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.5"/>
  <polygon points="76,32 82,26 82,40 76,46" fill="#c49a3a" stroke="#5a4008" stroke-width="1"/>
  <polygon points="62,32 68,26 82,26 76,32" fill="#d4aa4a" stroke="#5a4008" stroke-width="1"/>
  <text x="69" y="42" text-anchor="middle" font-size="6" fill="white" font-weight="bold" font-family="sans-serif">垂木</text>
  <!-- 左 ブロック2 y=54 -->
  <rect x="62" y="54" width="14" height="14" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.5"/>
  <polygon points="76,54 82,48 82,62 76,68" fill="#c49a3a" stroke="#5a4008" stroke-width="1"/>
  <polygon points="62,54 68,48 82,48 76,54" fill="#d4aa4a" stroke="#5a4008" stroke-width="1"/>
  <text x="69" y="64" text-anchor="middle" font-size="6" fill="white" font-weight="bold" font-family="sans-serif">垂木</text>
  <!-- 左 ブロック3 y=68 -->
  <rect x="62" y="68" width="14" height="14" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.5"/>
  <polygon points="76,68 82,62 82,76 76,82" fill="#c49a3a" stroke="#5a4008" stroke-width="1"/>
  <polygon points="62,68 68,62 82,62 76,68" fill="#d4aa4a" stroke="#5a4008" stroke-width="1"/>
  <text x="69" y="78" text-anchor="middle" font-size="6" fill="white" font-weight="bold" font-family="sans-serif">垂木</text>
  <!-- 左 ブロック4 y=82 -->
  <rect x="62" y="82" width="14" height="14" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.5"/>
  <polygon points="76,82 82,76 82,90 76,96" fill="#c49a3a" stroke="#5a4008" stroke-width="1"/>
  <polygon points="62,82 68,76 82,76 76,82" fill="#d4aa4a" stroke="#5a4008" stroke-width="1"/>
  <text x="69" y="92" text-anchor="middle" font-size="6" fill="white" font-weight="bold" font-family="sans-serif">垂木</text>
  <!-- 左 ブロック5（最下）y=102 -->
  <rect x="62" y="102" width="14" height="14" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.5"/>
  <polygon points="76,102 82,96 82,110 76,116" fill="#c49a3a" stroke="#5a4008" stroke-width="1"/>
  <polygon points="62,102 68,96 82,96 76,102" fill="#d4aa4a" stroke="#5a4008" stroke-width="1"/>
  <text x="69" y="112" text-anchor="middle" font-size="6" fill="white" font-weight="bold" font-family="sans-serif">垂木</text>

  <!-- ===== 右側 5個 ===== -->
  <!-- 右 ブロック1（最上）y=32 -->
  <rect x="264" y="32" width="14" height="14" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.5"/>
  <polygon points="278,32 284,26 284,40 278,46" fill="#c49a3a" stroke="#5a4008" stroke-width="1"/>
  <polygon points="264,32 270,26 284,26 278,32" fill="#d4aa4a" stroke="#5a4008" stroke-width="1"/>
  <text x="271" y="42" text-anchor="middle" font-size="6" fill="white" font-weight="bold" font-family="sans-serif">垂木</text>
  <!-- 右 ブロック2 y=54 -->
  <rect x="264" y="54" width="14" height="14" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.5"/>
  <polygon points="278,54 284,48 284,62 278,68" fill="#c49a3a" stroke="#5a4008" stroke-width="1"/>
  <polygon points="264,54 270,48 284,48 278,54" fill="#d4aa4a" stroke="#5a4008" stroke-width="1"/>
  <text x="271" y="64" text-anchor="middle" font-size="6" fill="white" font-weight="bold" font-family="sans-serif">垂木</text>
  <!-- 右 ブロック3 y=68 -->
  <rect x="264" y="68" width="14" height="14" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.5"/>
  <polygon points="278,68 284,62 284,76 278,82" fill="#c49a3a" stroke="#5a4008" stroke-width="1"/>
  <polygon points="264,68 270,62 284,62 278,68" fill="#d4aa4a" stroke="#5a4008" stroke-width="1"/>
  <text x="271" y="78" text-anchor="middle" font-size="6" fill="white" font-weight="bold" font-family="sans-serif">垂木</text>
  <!-- 右 ブロック4 y=82 -->
  <rect x="264" y="82" width="14" height="14" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.5"/>
  <polygon points="278,82 284,76 284,90 278,96" fill="#c49a3a" stroke="#5a4008" stroke-width="1"/>
  <polygon points="264,82 270,76 284,76 278,82" fill="#d4aa4a" stroke="#5a4008" stroke-width="1"/>
  <text x="271" y="92" text-anchor="middle" font-size="6" fill="white" font-weight="bold" font-family="sans-serif">垂木</text>
  <!-- 右 ブロック5（最下）y=102 -->
  <rect x="264" y="102" width="14" height="14" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.5"/>
  <polygon points="278,102 284,96 284,110 278,116" fill="#c49a3a" stroke="#5a4008" stroke-width="1"/>
  <polygon points="264,102 270,96 284,96 278,102" fill="#d4aa4a" stroke="#5a4008" stroke-width="1"/>
  <text x="271" y="112" text-anchor="middle" font-size="6" fill="white" font-weight="bold" font-family="sans-serif">垂木</text>

  <!-- ビス（最上〜最下を締める） -->
  <line x1="69" y1="46" x2="69" y2="102" stroke="#9e9e9e" stroke-width="1.5" stroke-dasharray="3,2"/>
  <polygon points="66,68 72,68 69,74" fill="#757575" opacity="0.8"/>
  <line x1="271" y1="46" x2="271" y2="102" stroke="#9e9e9e" stroke-width="1.5" stroke-dasharray="3,2"/>
  <polygon points="268,68 274,68 271,74" fill="#757575" opacity="0.8"/>

  <!-- 凡例 -->
  <rect x="80" y="115" width="10" height="8" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1"/>
  <text x="94" y="123" font-size="8" fill="#5a4008" font-family="sans-serif">垂木ブロック（パイプ固定）</text>
  <line x1="80" y1="135" x2="90" y2="135" stroke="#90a4ae" stroke-width="4" stroke-linecap="round"/>
  <text x="94" y="139" font-size="8" fill="#546e7a" font-family="sans-serif">パイプ（竹の外に飛び出してフレームに固定）</text>

  <text x="170" y="158" text-anchor="middle" font-size="9" fill="#2e7d32" font-weight="bold" font-family="sans-serif">パイプ入り竹をフレームに並べ、垂木ブロックでパイプを両側から固定</text>
  <text x="170" y="171" text-anchor="middle" font-size="8" fill="#c62828" font-family="sans-serif">竹はパイプを軸に自由に回転（ローラー動作）する</text>
</svg>'''


def _svg_step6_handrail() -> str:
    """⑥ 手すり竹を取り付ける"""
    return '''<svg viewBox="0 0 320 160" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;height:auto;">
  <!-- フレーム左 -->
  <rect x="18" y="60" width="12" height="70" rx="3" fill="#8d6e63" stroke="#5d4037" stroke-width="1.2"/>
  <!-- フレーム右 -->
  <rect x="290" y="60" width="12" height="70" rx="3" fill="#8d6e63" stroke="#5d4037" stroke-width="1.2"/>
  <!-- ローラー竹（3本） -->
  <rect x="30" y="68" width="260" height="14" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="1.2"/>
  <rect x="30" y="86" width="260" height="14" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="1.2"/>
  <rect x="30" y="104" width="260" height="14" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="1.2"/>
  <!-- 手すり竹（左） -->
  <rect x="14" y="28" width="260" height="22" rx="11" fill="#2e7d32" stroke="#1b5e20" stroke-width="2"/>
  <ellipse cx="14" cy="39" rx="6" ry="11" fill="#388e3c" stroke="#1b5e20" stroke-width="1.5"/>
  <ellipse cx="274" cy="39" rx="6" ry="11" fill="#388e3c" stroke="#1b5e20" stroke-width="1.5"/>
  <!-- ドリル穴マーク -->
  <circle cx="34" cy="39" r="4" fill="#1b5e20" stroke="#fff" stroke-width="0.8" opacity="0.8"/>
  <circle cx="254" cy="39" r="4" fill="#1b5e20" stroke="#fff" stroke-width="0.8" opacity="0.8"/>
  <!-- ビス -->
  <line x1="34" y1="35" x2="34" y2="52" stroke="#bdbdbd" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="254" y1="35" x2="254" y2="52" stroke="#bdbdbd" stroke-width="2.5" stroke-linecap="round"/>
  <text x="155" y="142" text-anchor="middle" font-size="11" fill="#1b5e20" font-family="sans-serif">手すり竹をドリル穴あけ→ビス固定</text>
  <text x="155" y="18" text-anchor="middle" font-size="11" fill="#546e7a" font-family="sans-serif">手すり竹を両側に取り付ける</text>
</svg>'''


def _svg_step7_slope() -> str:
    """⑦ 支柱の組み方・地面固定方法（案①単管打ち込み／案②ウォーターウェイト）"""
    return '''<svg viewBox="0 0 340 240" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:340px;height:auto;">
  <text x="170" y="14" text-anchor="middle" font-size="11" fill="#546e7a" font-family="sans-serif">支柱の地面固定（案①単管打込み　案②ウォーターウェイト）</text>

  <!-- ============================================================ -->
  <!-- 案①：単管パイプ打ち込み式（左側）                          -->
  <!-- ============================================================ -->
  <text x="82" y="30" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">案① 単管パイプ打込み式</text>

  <!-- 地面 -->
  <rect x="10" y="152" width="150" height="30" fill="#d7ccc8"/>
  <line x1="10" y1="152" x2="160" y2="152" stroke="#795548" stroke-width="2"/>
  <!-- 地中（打込み部） -->
  <rect x="10" y="152" width="150" height="30" fill="#bcaaa4" opacity="0.5"/>

  <!-- 斜面フレーム -->
  <polygon points="28,52 44,52 135,140 119,140" fill="#a1887f" stroke="#5d4037" stroke-width="1.5" opacity="0.85"/>
  <!-- ローラー面（緑） -->
  <line x1="42" y1="56" x2="130" y2="138" stroke="#4caf50" stroke-width="6" stroke-linecap="round" opacity="0.85"/>

  <!-- 木製支柱（高い方） -->
  <rect x="26" y="52" width="16" height="100" rx="3" fill="#8d6e63" stroke="#5d4037" stroke-width="1.5"/>
  <!-- 木製支柱（低い方） -->
  <rect x="119" y="120" width="16" height="32" rx="3" fill="#8d6e63" stroke="#5d4037" stroke-width="1.5"/>

  <!-- 単管パイプ（地中打込み・高支柱側） -->
  <rect x="31" y="140" width="6" height="36" rx="2" fill="#78909c" stroke="#455a64" stroke-width="1.5"/>
  <!-- 地中部分（打ち込まれた部分）破線で表現 -->
  <line x1="34" y1="152" x2="34" y2="176" stroke="#455a64" stroke-width="2" stroke-dasharray="3,2"/>
  <text x="44" y="168" font-size="7" fill="#455a64" font-family="sans-serif">地中50cm↓</text>

  <!-- 単管パイプ（低支柱側） -->
  <rect x="124" y="140" width="6" height="36" rx="2" fill="#78909c" stroke="#455a64" stroke-width="1.5"/>
  <line x1="127" y1="152" x2="127" y2="176" stroke="#455a64" stroke-width="2" stroke-dasharray="3,2"/>

  <!-- 直交クランプ（高支柱） -->
  <rect x="23" y="138" width="22" height="8" rx="2" fill="#607d8b" stroke="#37474f" stroke-width="1.2"/>
  <text x="20" y="135" font-size="7" fill="#37474f" font-family="sans-serif">クランプ</text>

  <!-- 筋交い -->
  <line x1="44" y1="100" x2="119" y2="136" stroke="#a1887f" stroke-width="3" stroke-linecap="round"/>
  <text x="74" y="130" font-size="8" fill="#5d4037" font-family="sans-serif" transform="rotate(-20,74,130)">筋交い</text>

  <!-- 傾斜角マーク -->
  <path d="M 119 128 A 22 22 0 0 0 100 142" fill="none" stroke="#e53935" stroke-width="1.2"/>
  <text x="92" y="156" font-size="8" fill="#c62828" font-family="sans-serif">≦35°</text>

  <!-- 案①ラベルボックス -->
  <rect x="10" y="186" width="150" height="44" rx="4" fill="#e3f2fd" stroke="#1565c0" stroke-width="1.2"/>
  <text x="85" y="200" text-anchor="middle" font-size="8" fill="#0d47a1" font-weight="bold" font-family="sans-serif">単管φ48.6mm・50cm以上打込み</text>
  <text x="85" y="213" text-anchor="middle" font-size="8" fill="#37474f" font-family="sans-serif">直交クランプで支柱と連結</text>
  <text x="85" y="226" text-anchor="middle" font-size="8" fill="#1b5e20" font-family="sans-serif">✓ 一時設置・撤去が容易</text>

  <!-- ============================================================ -->
  <!-- 案②：ウォーターウェイト式（右側）                          -->
  <!-- ============================================================ -->
  <text x="258" y="30" text-anchor="middle" font-size="9" fill="#e65100" font-weight="bold" font-family="sans-serif">案② ウォーターウェイト式</text>

  <!-- 地面（平坦・硬い） -->
  <rect x="175" y="152" width="155" height="30" fill="#d7ccc8"/>
  <line x1="175" y1="152" x2="330" y2="152" stroke="#795548" stroke-width="2"/>
  <text x="252" y="170" text-anchor="middle" font-size="7" fill="#795548" font-family="sans-serif">平坦・硬い地面限定</text>

  <!-- 斜面フレーム -->
  <polygon points="192,52 208,52 300,140 284,140" fill="#a1887f" stroke="#5d4037" stroke-width="1.5" opacity="0.85"/>
  <!-- ローラー面（緑） -->
  <line x1="206" y1="56" x2="295" y2="138" stroke="#4caf50" stroke-width="6" stroke-linecap="round" opacity="0.85"/>

  <!-- 木製支柱（高い方） -->
  <rect x="190" y="52" width="16" height="100" rx="3" fill="#8d6e63" stroke="#5d4037" stroke-width="1.5"/>
  <!-- 木製支柱（低い方） -->
  <rect x="284" y="120" width="16" height="32" rx="3" fill="#8d6e63" stroke="#5d4037" stroke-width="1.5"/>

  <!-- ウォーターウェイト（高支柱側・両側） -->
  <!-- 左タンク -->
  <rect x="174" y="126" width="18" height="28" rx="4" fill="#29b6f6" stroke="#0277bd" stroke-width="1.5"/>
  <text x="183" y="142" text-anchor="middle" font-size="6.5" fill="#01579b" font-weight="bold" font-family="sans-serif">水</text>
  <text x="183" y="151" text-anchor="middle" font-size="6" fill="#01579b" font-family="sans-serif">20L+</text>
  <!-- 右タンク -->
  <rect x="206" y="126" width="18" height="28" rx="4" fill="#29b6f6" stroke="#0277bd" stroke-width="1.5"/>
  <text x="215" y="142" text-anchor="middle" font-size="6.5" fill="#01579b" font-weight="bold" font-family="sans-serif">水</text>
  <text x="215" y="151" text-anchor="middle" font-size="6" fill="#01579b" font-family="sans-serif">20L+</text>

  <!-- ウォーターウェイト（低支柱側） -->
  <rect x="268" y="126" width="18" height="28" rx="4" fill="#29b6f6" stroke="#0277bd" stroke-width="1.5"/>
  <text x="277" y="142" text-anchor="middle" font-size="6.5" fill="#01579b" font-weight="bold" font-family="sans-serif">水</text>
  <rect x="300" y="126" width="18" height="28" rx="4" fill="#29b6f6" stroke="#0277bd" stroke-width="1.5"/>
  <text x="309" y="142" text-anchor="middle" font-size="6.5" fill="#01579b" font-weight="bold" font-family="sans-serif">水</text>

  <!-- ロープで縛り付け（波線） -->
  <path d="M 174 136 Q 183 130 192 136 Q 200 142 206 136" fill="none" stroke="#e65100" stroke-width="1.5" stroke-dasharray="2,1"/>
  <text x="190" y="125" text-anchor="middle" font-size="7" fill="#e65100" font-family="sans-serif">ロープ固定</text>

  <!-- 筋交い -->
  <line x1="208" y1="100" x2="284" y2="136" stroke="#a1887f" stroke-width="3" stroke-linecap="round"/>
  <text x="238" y="130" font-size="8" fill="#5d4037" font-family="sans-serif" transform="rotate(-20,238,130)">筋交い</text>

  <!-- 傾斜角マーク -->
  <path d="M 284 128 A 22 22 0 0 0 265 142" fill="none" stroke="#e53935" stroke-width="1.2"/>
  <text x="256" y="156" font-size="8" fill="#c62828" font-family="sans-serif">≦35°</text>

  <!-- 案②ラベルボックス -->
  <rect x="175" y="186" width="155" height="44" rx="4" fill="#fff3e0" stroke="#e65100" stroke-width="1.2"/>
  <text x="252" y="200" text-anchor="middle" font-size="8" fill="#e65100" font-weight="bold" font-family="sans-serif">各支柱に水タンク20kg以上×両側</text>
  <text x="252" y="213" text-anchor="middle" font-size="8" fill="#37474f" font-family="sans-serif">ロープ・ベルトで支柱にしっかり固定</text>
  <text x="252" y="226" text-anchor="middle" font-size="8" fill="#c62828" font-family="sans-serif">⚠ 平坦・硬い地面・大人付添い限定</text>
</svg>'''


def _svg_step8_complete() -> str:
    """⑧ 完成図（側面図スタイル：支柱＋斜面フレーム＋ローラー竹＋手すり＋階段）"""
    return '''<svg viewBox="0 0 340 220" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:340px;height:auto;">
  <text x="170" y="14" text-anchor="middle" font-size="11" fill="#546e7a" font-family="sans-serif">全体を組み上げて完成</text>

  <!-- 地面 -->
  <rect x="0" y="190" width="340" height="30" fill="#d7ccc8"/>
  <line x1="0" y1="190" x2="340" y2="190" stroke="#795548" stroke-width="2"/>

  <!-- 支柱（垂直・左高） -->
  <rect x="52" y="48" width="14" height="142" rx="3" fill="#8B6914" stroke="#5a4008" stroke-width="1.5"/>

  <!-- 斜面フレーム（支柱上端→右下へ） -->
  <polygon points="52,48 66,48 300,190 286,190" fill="#8B6914" stroke="#5a4008" stroke-width="1.2"/>

  <!-- ローラー竹（斜面上） -->
  <line x1="62" y1="54" x2="292" y2="188" stroke="#4caf50" stroke-width="10" stroke-linecap="round" opacity="0.9"/>

  <!-- 手すり竹（左） -->
  <line x1="48" y1="32" x2="285" y2="175" stroke="#2e7d32" stroke-width="9" stroke-linecap="round" opacity="0.88"/>

  <!-- 階段（縦桟2本・約30度傾き） -->
  <!-- 左縦桟：上端(52,48)→下端(20,190) -->
  <line x1="52" y1="48" x2="20" y2="190" stroke="#8B6914" stroke-width="7" stroke-linecap="round"/>
  <!-- 右縦桟：上端(66,48)→下端(34,190) -->
  <line x1="66" y1="48" x2="34" y2="190" stroke="#5a4008" stroke-width="5" stroke-linecap="round"/>
  <!-- 踏み板3段 -->
  <line x1="24" y1="145" x2="55" y2="145" stroke="#a07832" stroke-width="7" stroke-linecap="round"/>
  <line x1="31" y1="107" x2="62" y2="107" stroke="#a07832" stroke-width="7" stroke-linecap="round"/>
  <line x1="38" y1="69"  x2="66" y2="69"  stroke="#a07832" stroke-width="7" stroke-linecap="round"/>

  <!-- 支点マーカー -->
  <circle cx="59" cy="190" r="7" fill="#e53935" opacity="0.35" stroke="#b71c1c" stroke-width="1.2"/>
  <circle cx="59" cy="190" r="3" fill="#b71c1c" opacity="0.75"/>
  <circle cx="293" cy="190" r="7" fill="#e53935" opacity="0.35" stroke="#b71c1c" stroke-width="1.2"/>
  <circle cx="293" cy="190" r="3" fill="#b71c1c" opacity="0.75"/>

  <!-- 寸法 -->
  <line x1="59" y1="202" x2="293" y2="202" stroke="#546e7a" stroke-width="1.2"/>
  <polygon points="59,200 59,204 53,202" fill="#546e7a"/>
  <polygon points="293,200 293,204 299,202" fill="#546e7a"/>
  <text x="176" y="213" text-anchor="middle" font-size="8" fill="#546e7a" font-family="sans-serif">2.24m</text>
  <line x1="40" y1="48" x2="40" y2="190" stroke="#546e7a" stroke-width="1.2"/>
  <line x1="36" y1="48"  x2="44" y2="48"  stroke="#546e7a" stroke-width="1.2"/>
  <line x1="36" y1="190" x2="44" y2="190" stroke="#546e7a" stroke-width="1.2"/>
  <text x="30" y="123" text-anchor="middle" font-size="8" fill="#546e7a" font-family="sans-serif" transform="rotate(-90,30,123)">1.20m</text>

  <!-- 完成ラベル -->
  <rect x="130" y="55" width="150" height="22" rx="4" fill="#e8f5e9" stroke="#388e3c" stroke-width="1.2"/>
  <text x="205" y="70" text-anchor="middle" font-size="10" fill="#1b5e20" font-weight="bold" font-family="sans-serif">竹コースター滑り台　完成！</text>
</svg>'''


_STEP_SVGS = [
    _svg_step1_pipe,
    _svg_step2_cut,
    _svg_step3_frame,
    _svg_step4_node,
    _svg_step5_roller,
    _svg_step6_handrail,
    _svg_step7_slope,
    _svg_step8_complete,
]


# ── SVG：③ 垂木の両側挟み込み固定（画像確認に基づく正確な構造）──
def _svg_step3_clamp() -> str:
    """③ 垂木でパイプ両端を固定→竹がパイプを軸に回転するローラー構造（正確版）"""
    return '''<svg viewBox="0 0 340 240" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:340px;height:auto;">
  <text x="170" y="14" text-anchor="middle" font-size="11" fill="#546e7a" font-weight="bold" font-family="sans-serif">垂木ブロックでパイプを固定・竹はパイプ軸を中心に回転</text>

  <!-- ============================================================ -->
  <!-- 左：断面図（フレーム正面）垂木ブロックが上下からパイプを挟む -->
  <!-- 竹外径r=22, パイプr=7, 中心cy=100                           -->
  <!-- 垂木ブロック：上1個＋下1個で縦にパイプを挟み込む            -->
  <!-- ============================================================ -->
  <text x="82" y="30" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">断面図（フレーム正面）</text>

  <!-- 木材フレーム底板 -->
  <rect x="18" y="126" width="128" height="14" rx="3" fill="#8d6e63" stroke="#5d4037" stroke-width="1.5"/>

  <!-- 竹断面（中央・パイプ中心が見える） -->
  <ellipse cx="82" cy="100" rx="22" ry="22" fill="#4caf50" stroke="#2e7d32" stroke-width="2" opacity="0.88"/>
  <ellipse cx="82" cy="100" rx="13" ry="13" fill="#81c784" stroke="#388e3c" stroke-width="1" opacity="0.7"/>

  <!-- 垂木ブロック左（立方体・高さ=竹外径44px・竹左端x=60に密着） -->
  <!-- 正面: x=38〜60, y=78〜122  奥行き右上に8px -->
  <rect x="38" y="78" width="22" height="44" rx="2" fill="#bcaaa4" stroke="#5d4037" stroke-width="2"/>
  <polygon points="60,78 68,70 68,114 60,122" fill="#d7ccc8" stroke="#5d4037" stroke-width="1"/>
  <polygon points="38,78 46,70 68,70 60,78" fill="#e0d5cf" stroke="#5d4037" stroke-width="1"/>
  <!-- 竹の左端をブロックで隠す -->
  <rect x="59" y="79" width="3" height="42" fill="#bcaaa4"/>
  <text x="49" y="102" text-anchor="middle" font-size="7" fill="#4e342e" font-weight="bold" font-family="sans-serif">垂木</text>

  <!-- 垂木ブロック右（立方体・竹右端x=104に密着） -->
  <!-- 正面: x=104〜126, y=78〜122 -->
  <rect x="104" y="78" width="22" height="44" rx="2" fill="#bcaaa4" stroke="#5d4037" stroke-width="2"/>
  <polygon points="126,78 134,70 134,114 126,122" fill="#d7ccc8" stroke="#5d4037" stroke-width="1"/>
  <polygon points="104,78 112,70 134,70 126,78" fill="#e0d5cf" stroke="#5d4037" stroke-width="1"/>
  <rect x="104" y="79" width="3" height="42" fill="#bcaaa4"/>
  <text x="115" y="102" text-anchor="middle" font-size="7" fill="#4e342e" font-weight="bold" font-family="sans-serif">垂木</text>

  <!-- パイプ断面（竹の中心を貫通・固定） -->
  <ellipse cx="82" cy="100" rx="7" ry="7" fill="#90a4ae" stroke="#455a64" stroke-width="2"/>
  <ellipse cx="82" cy="100" rx="3.5" ry="3.5" fill="#cfd8dc" stroke="#607d8b" stroke-width="1"/>
  <text x="82" y="88" text-anchor="middle" font-size="7.5" fill="#455a64" font-family="sans-serif">パイプ固定</text>

  <!-- 左右から挟む矢印 -->
  <line x1="24" y1="100" x2="38" y2="100" stroke="#e53935" stroke-width="2"/>
  <polygon points="38,96 38,104 44,100" fill="#e53935"/>
  <line x1="140" y1="100" x2="126" y2="100" stroke="#e53935" stroke-width="2"/>
  <polygon points="126,96 126,104 120,100" fill="#e53935"/>
  <text x="82" y="65" text-anchor="middle" font-size="7.5" fill="#c62828" font-family="sans-serif">左右から挟む</text>

  <!-- 回転矢印 -->
  <path d="M 98 82 A 20 20 0 0 1 102 98" fill="none" stroke="#1565c0" stroke-width="2"/>
  <polygon points="101,98 108,91 96,88" fill="#1565c0"/>
  <text x="82" y="130" text-anchor="middle" font-size="8" fill="#1565c0" font-family="sans-serif">竹が回転</text>

  <!-- 高さ寸法線（垂木高さ＝竹外径） -->
  <line x1="22" y1="78" x2="22" y2="122" stroke="#e53935" stroke-width="1.2"/>
  <line x1="18" y1="78" x2="26" y2="78" stroke="#e53935" stroke-width="1.2"/>
  <line x1="18" y1="122" x2="26" y2="122" stroke="#e53935" stroke-width="1.2"/>
  <text x="1" y="97" font-size="7" fill="#c62828" font-family="sans-serif">高さ</text>
  <text x="1" y="107" font-size="7" fill="#c62828" font-family="sans-serif">＝竹径</text>

  <!-- ビス（ブロックを底板へ） -->
  <line x1="49" y1="122" x2="49" y2="131" stroke="#9e9e9e" stroke-width="3" stroke-linecap="round"/>
  <polygon points="45,131 53,131 49,138" fill="#757575"/>
  <line x1="115" y1="122" x2="115" y2="131" stroke="#9e9e9e" stroke-width="3" stroke-linecap="round"/>
  <polygon points="111,131 119,131 115,138" fill="#757575"/>

  <text x="82" y="155" text-anchor="middle" font-size="8" fill="#2e7d32" font-family="sans-serif">竹（フリー回転）</text>

  <!-- ============================================================ -->
  <!-- 右：側面図（垂木ブロックをフレーム板の上に載せ・縦を半分）  -->
  <!-- フレーム板 y=122〜136、垂木ブロック高さ=18px（半分）         -->
  <!-- ============================================================ -->
  <text x="258" y="30" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">側面図（横から）</text>

  <!-- 木材フレーム（底板・左右） -->
  <rect x="170" y="118" width="170" height="12" rx="2" fill="#8d6e63" stroke="#5d4037" stroke-width="1.5"/>

  <!-- 垂木ブロック左（フレーム板の上に載る・高さ18px=元の半分） -->
  <rect x="173" y="100" width="20" height="18" rx="3" fill="#bcaaa4" stroke="#5d4037" stroke-width="2"/>
  <!-- 垂木ブロック右 -->
  <rect x="317" y="100" width="20" height="18" rx="3" fill="#bcaaa4" stroke="#5d4037" stroke-width="2"/>

  <!-- パイプ（竹より長い・垂木ブロックを貫通） -->
  <rect x="170" y="104" width="170" height="8" rx="3" fill="#90a4ae" stroke="#455a64" stroke-width="1.5"/>

  <!-- 竹（ブロックとブロックの間・パイプより短い） -->
  <rect x="196" y="91" width="118" height="27" rx="8" fill="#4caf50" stroke="#2e7d32" stroke-width="2"/>
  <rect x="202" y="97" width="106" height="15" rx="5" fill="#81c784" stroke="#388e3c" stroke-width="1" opacity="0.55"/>
  <text x="255" y="107" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">竹（回転）</text>

  <!-- パイプ飛び出し ← 矢印 -->
  <line x1="170" y1="97" x2="193" y2="97" stroke="#455a64" stroke-width="1" stroke-dasharray="3,2"/>
  <polygon points="170,95 170,99 164,97" fill="#455a64"/>
  <text x="148" y="87" font-size="7" fill="#455a64" font-family="sans-serif">飛出し</text>
  <!-- パイプ飛び出し → 矢印 -->
  <line x1="317" y1="97" x2="340" y2="97" stroke="#455a64" stroke-width="1" stroke-dasharray="3,2"/>
  <polygon points="340,95 340,99 346,97" fill="#455a64"/>
  <text x="320" y="87" font-size="7" fill="#455a64" font-family="sans-serif">飛出し</text>

  <!-- ビス -->
  <line x1="183" y1="118" x2="183" y2="126" stroke="#9e9e9e" stroke-width="3" stroke-linecap="round"/>
  <polygon points="179,126 187,126 183,133" fill="#757575"/>
  <line x1="327" y1="118" x2="327" y2="126" stroke="#9e9e9e" stroke-width="3" stroke-linecap="round"/>
  <polygon points="323,126 331,126 327,133" fill="#757575"/>

  <!-- 竹長さ寸法 -->
  <line x1="196" y1="83" x2="314" y2="83" stroke="#2e7d32" stroke-width="1.2"/>
  <polygon points="196,81 196,85 190,83" fill="#2e7d32"/>
  <polygon points="314,81 314,85 320,83" fill="#2e7d32"/>
  <text x="255" y="80" text-anchor="middle" font-size="7" fill="#1b5e20" font-family="sans-serif">竹の長さ（パイプより短い）</text>

  <!-- ============================================================ -->
  <!-- 下部：説明ボックス                                           -->
  <!-- ============================================================ -->
  <rect x="10" y="162" width="320" height="68" rx="5" fill="#fff8e1" stroke="#f57f17" stroke-width="1.5"/>
  <text x="170" y="178" text-anchor="middle" font-size="9" fill="#e65100" font-weight="bold" font-family="sans-serif">【重要】固定するのはパイプ。竹はパイプを軸にフリー回転。</text>
  <text x="170" y="193" text-anchor="middle" font-size="8.5" fill="#37474f" font-family="sans-serif">パイプは竹の両端から飛び出させ、飛び出し部を垂木ブロックで挟んでビス固定。</text>
  <text x="170" y="208" text-anchor="middle" font-size="8.5" fill="#c62828" font-family="sans-serif">垂木ブロック高さ＝竹の外径。これにより竹がローラーとして外れずに回転する。</text>
  <text x="170" y="223" text-anchor="middle" font-size="8.5" fill="#37474f" font-family="sans-serif">竹の長さ ＝ パイプの長さ − 垂木ブロック幅 × 2</text>
</svg>'''


# ── SVG：⑥ 手すり固定方法（貫通穴→ビス固定・Step Aのみ）──
def _svg_step6_handrail_v2() -> str:
    """⑥ 手すり竹：斜面全体図＋Step A（貫通穴→ビス固定）のみ表示（垂木ブロック非表示）"""
    return '''<svg viewBox="0 0 340 270" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:340px;height:auto;">
  <text x="170" y="14" text-anchor="middle" font-size="11" fill="#546e7a" font-weight="bold" font-family="sans-serif">手すり竹の取付け方法</text>

  <!-- 上段：全体図 -->
  <text x="170" y="30" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">全体図（斜面に沿って設置）</text>

  <!-- 地面 -->
  <rect x="10" y="148" width="320" height="16" fill="#d7ccc8"/>
  <line x1="10" y1="148" x2="330" y2="148" stroke="#795548" stroke-width="1.5"/>

  <!-- 支柱（左高・右低） -->
  <rect x="28"  y="48"  width="12" height="100" rx="2" fill="#8d6e63" stroke="#5d4037" stroke-width="1.2"/>
  <rect x="232" y="112" width="12" height="36"  rx="2" fill="#8d6e63" stroke="#5d4037" stroke-width="1.2"/>

  <!-- 斜面フレーム -->
  <polygon points="28,48 40,48 244,112 232,112" fill="#a1887f" stroke="#5d4037" stroke-width="1.2" opacity="0.85"/>

  <!-- ローラー竹 -->
  <line x1="40" y1="53" x2="234" y2="110" stroke="#4caf50" stroke-width="10" stroke-linecap="round" opacity="0.9"/>
  <text x="137" y="93" text-anchor="middle" font-size="8" fill="#1b5e20" font-family="sans-serif" transform="rotate(-16,137,93)">ローラー竹</text>

  <!-- 手すり竹（左） -->
  <line x1="24" y1="33" x2="232" y2="96" stroke="#2e7d32" stroke-width="9" stroke-linecap="round" opacity="0.9"/>
  <text x="80" y="50" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif" transform="rotate(-16,80,50)">手すり竹（左）</text>

  <!-- 手すり竹（右・奥） -->
  <line x1="42" y1="36" x2="248" y2="99" stroke="#1b5e20" stroke-width="7" stroke-linecap="round" opacity="0.55"/>
  <text x="190" y="78" font-size="8" fill="#1b5e20" font-family="sans-serif" transform="rotate(-16,190,78)">手すり竹（右）</text>

  <!-- 高さ矢印 -->
  <line x1="50" y1="56" x2="42" y2="38" stroke="#e53935" stroke-width="1.2"/>
  <polygon points="39,40 45,34 48,42" fill="#e53935"/>
  <text x="2" y="52" font-size="7.5" fill="#c62828" font-family="sans-serif">15〜20cm</text>

  <!-- ビス固定点 -->
  <circle cx="26"  cy="34" r="4" fill="#f57f17" stroke="#e65100" stroke-width="1.2"/>
  <circle cx="232" cy="97" r="4" fill="#f57f17" stroke="#e65100" stroke-width="1.2"/>
  <text x="250" y="100" font-size="7.5" fill="#e65100" font-family="sans-serif">ビス固定</text>

  <!-- 下段：断面詳細（Step Aのみ・中央に大きく） -->
  <text x="170" y="174" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">断面詳細：ドリルで貫通穴 → 長ビスで固定</text>

  <!-- 垂木ブロック（断面） -->
  <rect x="110" y="234" width="120" height="18" rx="3" fill="#8d6e63" stroke="#5d4037" stroke-width="1.5"/>
  <text x="170" y="247" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">フレーム・取付け面</text>

  <!-- 手すり竹（断面・中央大きめ） -->
  <ellipse cx="170" cy="214" rx="24" ry="24" fill="#2e7d32" stroke="#1b5e20" stroke-width="2"/>
  <ellipse cx="170" cy="214" rx="12" ry="12" fill="#388e3c" stroke="#1b5e20" stroke-width="1"/>

  <!-- ドリルビット -->
  <line x1="170" y1="176" x2="170" y2="192" stroke="#424242" stroke-width="6" stroke-linecap="round"/>
  <polygon points="163,192 177,192 170,200" fill="#616161"/>

  <!-- 貫通穴（竹上・下） -->
  <ellipse cx="170" cy="192" rx="5" ry="3" fill="#1b5e20"/>
  <ellipse cx="170" cy="234" rx="5" ry="3" fill="#1b5e20"/>

  <!-- ドリル矢印 -->
  <polygon points="165,179 175,179 170,186" fill="#e53935"/>
  <text x="200" y="185" font-size="8" fill="#c62828" font-family="sans-serif">ドリルで貫通穴</text>

  <!-- ビス2本（竹の太さに応じ2箇所） -->
  <line x1="153" y1="193" x2="153" y2="250" stroke="#9e9e9e" stroke-width="4" stroke-linecap="round"/>
  <polygon points="149,250 157,250 153,258" fill="#757575"/>
  <line x1="187" y1="193" x2="187" y2="250" stroke="#9e9e9e" stroke-width="4" stroke-linecap="round"/>
  <polygon points="183,250 191,250 187,258" fill="#757575"/>

  <!-- 2箇所固定ラベル -->
  <text x="170" y="263" text-anchor="middle" font-size="8.5" fill="#e65100" font-weight="bold" font-family="sans-serif">竹の太さに応じてビス2箇所以上で固定する</text>
  <text x="170" y="272" text-anchor="middle" font-size="8" fill="#37474f" font-family="sans-serif">コーススレッド90mm以上を使用</text>
</svg>'''

# ══════════════════════════════════════════════════════════════════
# ブランコ製作手順ガイド用 SVG イラスト
# ══════════════════════════════════════════════════════════════════

def _svg_swing_step1_cut() -> str:
    """① 竹を8本切り出す"""
    return '''<svg viewBox="0 0 340 215" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:340px;height:auto;">
  <text x="170" y="16" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">竹を8本切り出す</text>
  <!-- 地面 -->
  <rect x="0" y="180" width="340" height="35" fill="#d7ccc8"/>
  <line x1="0" y1="180" x2="340" y2="180" stroke="#795548" stroke-width="1.5"/>

  <!-- グループA：支柱用6本（薄緑） -->
  <rect x="6"  y="58" width="30" height="118" rx="9" fill="#4caf50" stroke="#2e7d32" stroke-width="1.8"/>
  <rect x="40" y="58" width="30" height="118" rx="9" fill="#4caf50" stroke="#2e7d32" stroke-width="1.8"/>
  <rect x="74" y="58" width="30" height="118" rx="9" fill="#4caf50" stroke="#2e7d32" stroke-width="1.8"/>
  <rect x="108" y="58" width="30" height="118" rx="9" fill="#4caf50" stroke="#2e7d32" stroke-width="1.8"/>
  <rect x="142" y="58" width="30" height="118" rx="9" fill="#4caf50" stroke="#2e7d32" stroke-width="1.8"/>
  <rect x="176" y="58" width="30" height="118" rx="9" fill="#4caf50" stroke="#2e7d32" stroke-width="1.8"/>
  <!-- 節ライン（支柱6本） -->
  <line x1="6"   y1="115" x2="36"  y2="115" stroke="#2e7d32" stroke-width="1.4" opacity="0.5"/>
  <line x1="40"  y1="115" x2="70"  y2="115" stroke="#2e7d32" stroke-width="1.4" opacity="0.5"/>
  <line x1="74"  y1="115" x2="104" y2="115" stroke="#2e7d32" stroke-width="1.4" opacity="0.5"/>
  <line x1="108" y1="115" x2="138" y2="115" stroke="#2e7d32" stroke-width="1.4" opacity="0.5"/>
  <line x1="142" y1="115" x2="172" y2="115" stroke="#2e7d32" stroke-width="1.4" opacity="0.5"/>
  <line x1="176" y1="115" x2="206" y2="115" stroke="#2e7d32" stroke-width="1.4" opacity="0.5"/>
  <!-- 番号（支柱6本） -->
  <text x="21"  y="52" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">①</text>
  <text x="55"  y="52" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">②</text>
  <text x="89"  y="52" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">③</text>
  <text x="123" y="52" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">④</text>
  <text x="157" y="52" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">⑤</text>
  <text x="191" y="52" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">⑥</text>
  <!-- ブレース（支柱グループ囲み） -->
  <rect x="4" y="54" width="206" height="128" rx="6" fill="none" stroke="#388e3c" stroke-width="1.5" stroke-dasharray="5,3"/>
  <text x="103" y="196" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">支柱用 3本×2箇所＝6本</text>

  <!-- グループB：横材用1本（濃緑） -->
  <rect x="216" y="58" width="30" height="118" rx="9" fill="#2e7d32" stroke="#1b5e20" stroke-width="2"/>
  <line x1="216" y1="115" x2="246" y2="115" stroke="#1b5e20" stroke-width="1.4" opacity="0.5"/>
  <text x="231" y="52" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">⑦</text>
  <rect x="214" y="54" width="36" height="128" rx="6" fill="none" stroke="#1b5e20" stroke-width="1.5" stroke-dasharray="5,3"/>
  <text x="232" y="196" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">横材 1本</text>

  <!-- グループC：椅子用1本（黄緑） -->
  <rect x="262" y="58" width="30" height="118" rx="9" fill="#8bc34a" stroke="#558b2f" stroke-width="2"/>
  <line x1="262" y1="115" x2="292" y2="115" stroke="#558b2f" stroke-width="1.4" opacity="0.5"/>
  <text x="277" y="52" text-anchor="middle" font-size="8" fill="#33691e" font-weight="bold" font-family="sans-serif">⑧</text>
  <rect x="260" y="54" width="36" height="128" rx="6" fill="none" stroke="#558b2f" stroke-width="1.5" stroke-dasharray="5,3"/>
  <text x="278" y="196" text-anchor="middle" font-size="8" fill="#33691e" font-weight="bold" font-family="sans-serif">椅子 1本</text>

  <!-- ノコギリ -->
  <rect x="300" y="84" width="34" height="7" rx="2" fill="#90a4ae" stroke="#455a64" stroke-width="1"/>
  <polygon points="300,91 334,91 334,98 300,98" fill="#78909c" stroke="#455a64" stroke-width="0.8"/>
  <polyline points="300,98 305,104 310,98 315,104 320,98 325,104 330,98 334,98" fill="none" stroke="#37474f" stroke-width="1.2"/>
  <line x1="299" y1="95" x2="296" y2="95" stroke="#e53935" stroke-width="1.8"/>
  <polygon points="296,92 296,98 289,95" fill="#e53935"/>
</svg>'''


def _svg_swing_step2_bind() -> str:
    """② 上部のみ結束→三角錐状に広げて地中固定"""
    return '''<svg viewBox="0 0 340 260" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:340px;height:auto;">
  <text x="170" y="15" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">上部のみ結束→三角錐に広げて固定</text>

  <!-- ===== 左パネル：上部結束（正面図） ===== -->
  <text x="78" y="34" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">① 上端のみ結ぶ</text>
  <!-- 竹3本（縦・並列） -->
  <rect x="46"  y="46" width="18" height="110" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="1.8"/>
  <rect x="70"  y="46" width="18" height="110" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="1.8"/>
  <rect x="94"  y="46" width="18" height="110" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="1.8"/>
  <!-- 節ライン -->
  <line x1="46"  y1="95" x2="64"  y2="95" stroke="#2e7d32" stroke-width="1.2" opacity="0.45"/>
  <line x1="70"  y1="95" x2="88"  y2="95" stroke="#2e7d32" stroke-width="1.2" opacity="0.45"/>
  <line x1="94"  y1="95" x2="112" y2="95" stroke="#2e7d32" stroke-width="1.2" opacity="0.45"/>
  <!-- 上部結束ロープのみ -->
  <rect x="42" y="52" width="78" height="10" rx="4" fill="#BA7517" stroke="#8B4513" stroke-width="1.5" opacity="0.95"/>
  <!-- 結束ラベル -->
  <text x="78" y="76" text-anchor="middle" font-size="8" fill="#e65100" font-weight="bold" font-family="sans-serif">上端のみ！</text>
  <!-- 中・下にはロープなし（×印） -->
  <line x1="56" y1="113" x2="66" y2="123" stroke="#e53935" stroke-width="2"/>
  <line x1="66" y1="113" x2="56" y2="123" stroke="#e53935" stroke-width="2"/>
  <line x1="86" y1="113" x2="96" y2="123" stroke="#e53935" stroke-width="2"/>
  <line x1="96" y1="113" x2="86" y2="123" stroke="#e53935" stroke-width="2"/>
  <text x="78" y="144" text-anchor="middle" font-size="7.5" fill="#c62828" font-family="sans-serif">中・下は結ばない</text>
  <!-- 矢印（次へ） -->
  <line x1="120" y1="95" x2="140" y2="95" stroke="#37474f" stroke-width="2"/>
  <polygon points="140,91 140,99 148,95" fill="#37474f"/>

  <!-- ===== 右パネル：三角錐展開（斜視図） ===== -->
  <text x="240" y="34" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">② 三角錐に広げる（斜視）</text>
  <!-- 地面 -->
  <rect x="148" y="190" width="185" height="38" fill="#d7ccc8"/>
  <line x1="148" y1="190" x2="333" y2="190" stroke="#795548" stroke-width="2"/>
  <!-- 地中（3穴） -->
  <ellipse cx="185" cy="190" rx="13" ry="5" fill="#a1887f" stroke="#795548" stroke-width="1.2"/>
  <rect x="172" y="190" width="26" height="28" fill="#a1887f"/>
  <ellipse cx="240" cy="190" rx="13" ry="5" fill="#a1887f" stroke="#795548" stroke-width="1.2"/>
  <rect x="227" y="190" width="26" height="28" fill="#a1887f"/>
  <ellipse cx="300" cy="190" rx="13" ry="5" fill="#a1887f" stroke="#795548" stroke-width="1.2"/>
  <rect x="287" y="190" width="26" height="28" fill="#a1887f"/>
  <!-- 竹1本目（手前・正面） -->
  <line x1="240" y1="60" x2="240" y2="205" stroke="#4caf50" stroke-width="11" stroke-linecap="round"/>
  <!-- 竹2本目（左後ろ） -->
  <line x1="240" y1="60" x2="185" y2="205" stroke="#2e7d32" stroke-width="10" stroke-linecap="round"/>
  <!-- 竹3本目（右後ろ） -->
  <line x1="240" y1="60" x2="300" y2="205" stroke="#388e3c" stroke-width="10" stroke-linecap="round"/>
  <!-- 地上部分の補助線（底面三角形） -->
  <line x1="185" y1="190" x2="300" y2="190" stroke="#795548" stroke-width="1.5" stroke-dasharray="5,3" opacity="0.7"/>
  <line x1="185" y1="190" x2="240" y2="190" stroke="#795548" stroke-width="1.5" stroke-dasharray="5,3" opacity="0.7"/>
  <!-- 頂点（上部結束） -->
  <circle cx="240" cy="57" r="13" fill="#BA7517" stroke="#8B4513" stroke-width="2.5"/>
  <text x="240" y="62" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">結束</text>
  <!-- 広がり角度矢印 -->
  <path d="M 240 80 Q 260 110 260 140" fill="none" stroke="#e53935" stroke-width="1.5" stroke-dasharray="4,3"/>
  <polygon points="257,140 263,140 260,148" fill="#e53935"/>
  <text x="268" y="130" font-size="7.5" fill="#c62828" font-family="sans-serif">広げる</text>
  <!-- 地中埋込み深さ -->
  <line x1="156" y1="190" x2="156" y2="218" stroke="#e53935" stroke-width="1.5"/>
  <line x1="152" y1="190" x2="160" y2="190" stroke="#e53935" stroke-width="1.5"/>
  <line x1="152" y1="218" x2="160" y2="218" stroke="#e53935" stroke-width="1.5"/>
  <text x="148" y="207" text-anchor="middle" font-size="7" fill="#c62828" font-family="sans-serif">30cm</text>

  <!-- ===== 下部：説明ボックス ===== -->
  <rect x="4" y="220" width="140" height="36" rx="4" fill="#e8f5e9" stroke="#388e3c" stroke-width="1.2"/>
  <text x="74" y="235" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">結ぶのは上端1箇所のみ！</text>
  <text x="74" y="248" text-anchor="middle" font-size="7.5" fill="#37474f" font-family="sans-serif">竹を束にしたまま広げない</text>
  <rect x="148" y="232" width="185" height="24" rx="4" fill="#fff8e1" stroke="#f57f17" stroke-width="1.2"/>
  <text x="240" y="248" text-anchor="middle" font-size="8" fill="#e65100" font-weight="bold" font-family="sans-serif">⚠️ 3本の足先を均等に広げ地中に埋める</text>
</svg>'''


def _svg_swing_step3_erect() -> str:
    """③ 三角錐×2基を立ち上げ・地中固定（正面＋斜視の2パネル）"""
    return '''<svg viewBox="0 0 360 270" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:360px;height:auto;">
  <text x="180" y="15" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">三角錐(トライポッド)×2基を立ち上げ固定</text>

  <!-- ============================================================ -->
  <!-- 左パネル：正面図（完成状態）                                  -->
  <!-- ============================================================ -->
  <text x="78" y="32" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">正面から見た図</text>

  <!-- 地面 -->
  <rect x="4" y="188" width="156" height="46" fill="#d7ccc8"/>
  <line x1="4" y1="188" x2="160" y2="188" stroke="#795548" stroke-width="2"/>

  <!-- 左トライポッド（正面図） -->
  <!-- 前足（正面・太く） -->
  <line x1="50" y1="185" x2="50" y2="60" stroke="#4caf50" stroke-width="11" stroke-linecap="round"/>
  <!-- 右後ろ足 -->
  <line x1="68" y1="185" x2="50" y2="60" stroke="#2e7d32" stroke-width="9" stroke-linecap="round" opacity="0.85"/>
  <!-- 左後ろ足 -->
  <line x1="32" y1="185" x2="50" y2="60" stroke="#388e3c" stroke-width="9" stroke-linecap="round" opacity="0.75"/>
  <!-- 頂点結束 -->
  <circle cx="50" cy="57" r="11" fill="#BA7517" stroke="#8B4513" stroke-width="2"/>
  <text x="50" y="61" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結束</text>

  <!-- 右トライポッド（正面図） -->
  <line x1="118" y1="185" x2="118" y2="60" stroke="#4caf50" stroke-width="11" stroke-linecap="round"/>
  <line x1="136" y1="185" x2="118" y2="60" stroke="#2e7d32" stroke-width="9" stroke-linecap="round" opacity="0.85"/>
  <line x1="100" y1="185" x2="118" y2="60" stroke="#388e3c" stroke-width="9" stroke-linecap="round" opacity="0.75"/>
  <circle cx="118" cy="57" r="11" fill="#BA7517" stroke="#8B4513" stroke-width="2"/>
  <text x="118" y="61" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結束</text>

  <!-- 地中埋込み（左） -->
  <ellipse cx="50" cy="188" rx="22" ry="6" fill="#a1887f" stroke="#795548" stroke-width="1.2"/>
  <rect x="28" y="188" width="44" height="30" fill="#a1887f" opacity="0.8"/>
  <!-- 地中埋込み（右） -->
  <ellipse cx="118" cy="188" rx="22" ry="6" fill="#a1887f" stroke="#795548" stroke-width="1.2"/>
  <rect x="96" y="188" width="44" height="30" fill="#a1887f" opacity="0.8"/>

  <!-- 深さ寸法 -->
  <line x1="10" y1="188" x2="10" y2="218" stroke="#e53935" stroke-width="1.5"/>
  <line x1="6"  y1="188" x2="14" y2="188" stroke="#e53935" stroke-width="1.5"/>
  <line x1="6"  y1="218" x2="14" y2="218" stroke="#e53935" stroke-width="1.5"/>
  <text x="18" y="200" font-size="7" fill="#c62828" font-weight="bold" font-family="sans-serif">30cm</text>
  <text x="18" y="210" font-size="7" fill="#c62828" font-family="sans-serif">以上</text>

  <!-- 人物（立ち上げ作業・左） -->
  <circle cx="22" cy="115" r="9" fill="#FFCC80" stroke="#8d6e63" stroke-width="1.5"/>
  <line x1="22" y1="124" x2="22" y2="155" stroke="#e53935" stroke-width="3.5" stroke-linecap="round"/>
  <line x1="22" y1="134" x2="10"  y2="126" stroke="#e53935" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="22" y1="134" x2="38"  y2="128" stroke="#e53935" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="22" y1="155" x2="15"  y2="175" stroke="#e53935" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="22" y1="155" x2="29"  y2="175" stroke="#e53935" stroke-width="2.5" stroke-linecap="round"/>

  <!-- 人物（立ち上げ作業・右） -->
  <circle cx="146" cy="115" r="9" fill="#FFCC80" stroke="#8d6e63" stroke-width="1.5"/>
  <line x1="146" y1="124" x2="146" y2="155" stroke="#1a237e" stroke-width="3.5" stroke-linecap="round"/>
  <line x1="146" y1="134" x2="130" y2="126" stroke="#1a237e" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="146" y1="134" x2="158" y2="128" stroke="#1a237e" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="146" y1="155" x2="139" y2="175" stroke="#1a237e" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="146" y1="155" x2="153" y2="175" stroke="#1a237e" stroke-width="2.5" stroke-linecap="round"/>

  <!-- 警告マーク（中央上） -->
  <polygon points="84,36 73,56 95,56" fill="#f57f17" stroke="#e65100" stroke-width="1.5"/>
  <text x="84" y="52" text-anchor="middle" font-size="10" fill="white" font-weight="bold" font-family="sans-serif">!</text>
  <text x="84" y="70" text-anchor="middle" font-size="7.5" fill="#c62828" font-weight="bold" font-family="sans-serif">2〜3人で!</text>

  <!-- ============================================================ -->
  <!-- 右パネル：斜視図（トライポッド単体の3D感）                   -->
  <!-- ============================================================ -->
  <text x="268" y="32" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">斜視図（1基のみ）</text>

  <!-- 地面（右パネル） -->
  <rect x="172" y="188" width="182" height="46" fill="#d7ccc8"/>
  <line x1="172" y1="188" x2="354" y2="188" stroke="#795548" stroke-width="2"/>

  <!-- トライポッド3本足（斜視） -->
  <!-- 前足（正面へ） -->
  <line x1="268" y1="60" x2="268" y2="195" stroke="#4caf50" stroke-width="12" stroke-linecap="round"/>
  <!-- 右後ろ足 -->
  <line x1="268" y1="60" x2="318" y2="195" stroke="#2e7d32" stroke-width="10" stroke-linecap="round" opacity="0.9"/>
  <!-- 左後ろ足 -->
  <line x1="268" y1="60" x2="218" y2="195" stroke="#388e3c" stroke-width="10" stroke-linecap="round" opacity="0.8"/>

  <!-- 底面三角形（地面）点線 -->
  <line x1="268" y1="195" x2="318" y2="195" stroke="#795548" stroke-width="1.5" stroke-dasharray="5,3" opacity="0.8"/>
  <line x1="268" y1="195" x2="218" y2="195" stroke="#795548" stroke-width="1.5" stroke-dasharray="5,3" opacity="0.8"/>
  <line x1="218" y1="195" x2="318" y2="195" stroke="#795548" stroke-width="1.5" stroke-dasharray="5,3" opacity="0.8"/>

  <!-- 各足先の穴 -->
  <ellipse cx="268" cy="195" rx="12" ry="5" fill="#a1887f" stroke="#795548" stroke-width="1.2"/>
  <rect x="256" y="195" width="24" height="26" fill="#a1887f" opacity="0.8"/>
  <ellipse cx="318" cy="195" rx="12" ry="5" fill="#a1887f" stroke="#795548" stroke-width="1.2"/>
  <rect x="306" y="195" width="24" height="26" fill="#a1887f" opacity="0.8"/>
  <ellipse cx="218" cy="195" rx="12" ry="5" fill="#a1887f" stroke="#795548" stroke-width="1.2"/>
  <rect x="206" y="195" width="24" height="26" fill="#a1887f" opacity="0.8"/>

  <!-- 頂点結束（右パネル） -->
  <circle cx="268" cy="56" r="13" fill="#BA7517" stroke="#8B4513" stroke-width="2.5"/>
  <text x="268" y="60" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">結束</text>

  <!-- 角度ラベル -->
  <path d="M 268 90 Q 295 115 305 148" fill="none" stroke="#e53935" stroke-width="1.5" stroke-dasharray="4,3"/>
  <polygon points="302,148 308,148 305,156" fill="#e53935"/>
  <text x="312" y="135" font-size="7.5" fill="#c62828" font-family="sans-serif">均等に</text>
  <text x="312" y="145" font-size="7.5" fill="#c62828" font-family="sans-serif">広げる</text>

  <!-- 足ラベル（前・右後・左後） -->
  <text x="260" y="210" font-size="7" fill="#1b5e20" font-weight="bold" font-family="sans-serif">前</text>
  <text x="322" y="210" font-size="7" fill="#1b5e20" font-weight="bold" font-family="sans-serif">右後</text>
  <text x="205" y="210" font-size="7" fill="#1b5e20" font-weight="bold" font-family="sans-serif">左後</text>

  <!-- ============================================================ -->
  <!-- 下部：注意ボックス                                            -->
  <!-- ============================================================ -->
  <rect x="4" y="238" width="352" height="28" rx="5" fill="#fff8e1" stroke="#f57f17" stroke-width="1.5"/>
  <text x="180" y="251" text-anchor="middle" font-size="8.5" fill="#e65100" font-weight="bold" font-family="sans-serif">⚠️ 重い！必ず2〜3人で作業。各足先を均等に広げて砂利と土で突き固める</text>
  <text x="180" y="263" text-anchor="middle" font-size="8" fill="#37474f" font-family="sans-serif">1基ずつ立ち上げ、両方固定してからぐらつきがないか確認する</text>
</svg>'''


def _svg_swing_step4_beam() -> str:
    """④ 太い竹を水平に渡す"""
    return '''<svg viewBox="0 0 320 220" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;height:auto;">
  <text x="160" y="16" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">太い竹を水平に渡す（梁）</text>
  <!-- 地面 -->
  <rect x="0" y="170" width="320" height="50" fill="#d7ccc8"/>
  <line x1="0" y1="170" x2="320" y2="170" stroke="#795548" stroke-width="2"/>
  <!-- 地中 -->
  <rect x="53" y="170" width="44" height="30" fill="#a1887f"/>
  <rect x="223" y="170" width="44" height="30" fill="#a1887f"/>
  <!-- 左の逆V支柱 -->
  <line x1="75" y1="196" x2="120" y2="75" stroke="#4caf50" stroke-width="13" stroke-linecap="round"/>
  <line x1="75" y1="196" x2="108" y2="75" stroke="#4caf50" stroke-width="13" stroke-linecap="round" opacity="0.7"/>
  <!-- 右の逆V支柱 -->
  <line x1="245" y1="196" x2="200" y2="75" stroke="#4caf50" stroke-width="13" stroke-linecap="round"/>
  <line x1="245" y1="196" x2="212" y2="75" stroke="#4caf50" stroke-width="13" stroke-linecap="round" opacity="0.7"/>
  <!-- 頂点結束 -->
  <circle cx="114" cy="72" r="11" fill="#BA7517" stroke="#8B4513" stroke-width="2"/>
  <circle cx="206" cy="72" r="11" fill="#BA7517" stroke="#8B4513" stroke-width="2"/>
  <!-- 水平梁（太い竹） -->
  <rect x="100" y="56" width="120" height="20" rx="8" fill="#2e7d32" stroke="#1b5e20" stroke-width="2"/>
  <rect x="104" y="60" width="112" height="10" rx="4" fill="#4caf50" opacity="0.5"/>
  <!-- 梁の端面（左右） -->
  <ellipse cx="100" cy="66" rx="8" ry="10" fill="#1b5e20" stroke="#0a3a0a" stroke-width="1.5" opacity="0.9"/>
  <ellipse cx="220" cy="66" rx="8" ry="10" fill="#1b5e20" stroke="#0a3a0a" stroke-width="1.5" opacity="0.9"/>
  <!-- 結束ロープ（梁を支柱に固定） -->
  <ellipse cx="114" cy="66" rx="14" ry="18" fill="none" stroke="#BA7517" stroke-width="4" opacity="0.9"/>
  <ellipse cx="206" cy="66" rx="14" ry="18" fill="none" stroke="#BA7517" stroke-width="4" opacity="0.9"/>
  <!-- 水平確認（水準器イメージ） -->
  <rect x="120" y="50" width="80" height="12" rx="4" fill="#e3f2fd" stroke="#1565c0" stroke-width="1.5"/>
  <circle cx="160" cy="56" r="4" fill="#1565c0"/>
  <text x="160" y="45" text-anchor="middle" font-size="8" fill="#1565c0" font-weight="bold" font-family="sans-serif">水平に設置！</text>
  <!-- 寸法 -->
  <line x1="100" y1="100" x2="220" y2="100" stroke="#e53935" stroke-width="1.2"/>
  <polygon points="100,97 100,103 94,100" fill="#e53935"/>
  <polygon points="220,97 220,103 226,100" fill="#e53935"/>
  <text x="160" y="115" text-anchor="middle" font-size="8.5" fill="#c62828" font-family="sans-serif">梁の長さ（幅に合わせる）</text>
  <text x="160" y="210" text-anchor="middle" font-size="8.5" fill="#37474f" font-family="sans-serif">梁は太くて丈夫な竹を選ぶ（直径8cm以上推奨）</text>
</svg>'''


def _svg_swing_step5_rope() -> str:
    """⑤ ロープを2本渡す"""
    return '''<svg viewBox="0 0 320 230" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;height:auto;">
  <text x="160" y="16" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">ロープを2本渡す</text>
  <!-- 地面 -->
  <rect x="0" y="178" width="320" height="52" fill="#d7ccc8"/>
  <line x1="0" y1="178" x2="320" y2="178" stroke="#795548" stroke-width="2"/>
  <!-- 支柱（簡略化） -->
  <line x1="70" y1="178" x2="115" y2="72" stroke="#4caf50" stroke-width="12" stroke-linecap="round"/>
  <line x1="250" y1="178" x2="205" y2="72" stroke="#4caf50" stroke-width="12" stroke-linecap="round"/>
  <!-- 頂点 -->
  <circle cx="115" cy="70" r="10" fill="#BA7517" stroke="#8B4513" stroke-width="2"/>
  <circle cx="205" cy="70" r="10" fill="#BA7517" stroke="#8B4513" stroke-width="2"/>
  <!-- 梁 -->
  <rect x="103" y="54" width="114" height="18" rx="7" fill="#2e7d32" stroke="#1b5e20" stroke-width="2"/>
  <!-- ロープ1本目（前） -->
  <line x1="128" y1="70" x2="128" y2="155" stroke="#BA7517" stroke-width="5" stroke-linecap="round"/>
  <!-- ロープ2本目（後ろ） -->
  <line x1="192" y1="70" x2="192" y2="155" stroke="#BA7517" stroke-width="5" stroke-linecap="round"/>
  <!-- 梁への結束点 -->
  <circle cx="128" cy="70" r="7" fill="#e65100" stroke="#bf360c" stroke-width="1.5"/>
  <circle cx="192" cy="70" r="7" fill="#e65100" stroke="#bf360c" stroke-width="1.5"/>
  <!-- ロープ梁巻きつき強調 -->
  <path d="M 121 54 Q 128 46 135 54" fill="none" stroke="#BA7517" stroke-width="3"/>
  <path d="M 185 54 Q 192 46 199 54" fill="none" stroke="#BA7517" stroke-width="3"/>
  <!-- ロープ下端 -->
  <circle cx="128" cy="155" r="6" fill="#e65100" stroke="#bf360c" stroke-width="1.5"/>
  <circle cx="192" cy="155" r="6" fill="#e65100" stroke="#bf360c" stroke-width="1.5"/>
  <!-- ロープ間隔寸法 -->
  <line x1="128" y1="140" x2="192" y2="140" stroke="#37474f" stroke-width="1.2" stroke-dasharray="4,3"/>
  <text x="160" y="136" text-anchor="middle" font-size="8" fill="#37474f" font-family="sans-serif">40〜50cm</text>
  <!-- 説明ボックス -->
  <rect x="10" y="184" width="300" height="40" rx="4" fill="#fff8e1" stroke="#f57f17" stroke-width="1.2"/>
  <text x="160" y="198" text-anchor="middle" font-size="8.5" fill="#e65100" font-weight="bold" font-family="sans-serif">⚠️ ロープは梁に3回以上巻きつけてほどけないよう固定</text>
  <text x="160" y="214" text-anchor="middle" font-size="8.5" fill="#37474f" font-family="sans-serif">耐荷重200kg以上のロープを使用すること</text>
</svg>'''


def _svg_swing_step6_seat() -> str:
    """⑥ 椅子となる竹を括り付けて完成"""
    return '''<svg viewBox="0 0 320 240" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;height:auto;">
  <text x="160" y="16" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">椅子竹を括り付けて完成！</text>
  <!-- 地面 -->
  <rect x="0" y="185" width="320" height="55" fill="#d7ccc8"/>
  <line x1="0" y1="185" x2="320" y2="185" stroke="#795548" stroke-width="2"/>
  <!-- 支柱（左右） -->
  <line x1="65" y1="185" x2="110" y2="65" stroke="#4caf50" stroke-width="12" stroke-linecap="round"/>
  <line x1="255" y1="185" x2="210" y2="65" stroke="#4caf50" stroke-width="12" stroke-linecap="round"/>
  <!-- 頂点 -->
  <circle cx="110" cy="63" r="10" fill="#BA7517" stroke="#8B4513" stroke-width="2"/>
  <circle cx="210" cy="63" r="10" fill="#BA7517" stroke="#8B4513" stroke-width="2"/>
  <!-- 梁 -->
  <rect x="98" y="48" width="124" height="18" rx="7" fill="#2e7d32" stroke="#1b5e20" stroke-width="2"/>
  <!-- ロープ（前・後ろ） -->
  <line x1="130" y1="64" x2="130" y2="158" stroke="#BA7517" stroke-width="5" stroke-linecap="round"/>
  <line x1="190" y1="64" x2="190" y2="158" stroke="#BA7517" stroke-width="5" stroke-linecap="round"/>
  <!-- 梁結束 -->
  <circle cx="130" cy="64" r="7" fill="#e65100" stroke="#bf360c" stroke-width="1.5"/>
  <circle cx="190" cy="64" r="7" fill="#e65100" stroke="#bf360c" stroke-width="1.5"/>
  <!-- 座面竹（水平・太め） -->
  <rect x="116" y="150" width="88" height="16" rx="7" fill="#4caf50" stroke="#2e7d32" stroke-width="2"/>
  <rect x="120" y="154" width="80" height="7" rx="3" fill="#81c784" opacity="0.6"/>
  <!-- ロープと座面の結束 -->
  <ellipse cx="130" cy="158" rx="8" ry="5" fill="none" stroke="#BA7517" stroke-width="3.5"/>
  <ellipse cx="190" cy="158" rx="8" ry="5" fill="none" stroke="#BA7517" stroke-width="3.5"/>
  <!-- 子供シルエット -->
  <circle cx="160" cy="126" r="11" fill="#FFCC80" stroke="#8d6e63" stroke-width="1.5"/>
  <line x1="160" y1="137" x2="160" y2="155" stroke="#1565c0" stroke-width="4" stroke-linecap="round"/>
  <line x1="160" y1="144" x2="144" y2="138" stroke="#1565c0" stroke-width="3" stroke-linecap="round"/>
  <line x1="160" y1="144" x2="176" y2="138" stroke="#1565c0" stroke-width="3" stroke-linecap="round"/>
  <line x1="160" y1="155" x2="152" y2="168" stroke="#1565c0" stroke-width="3" stroke-linecap="round"/>
  <line x1="160" y1="155" x2="168" y2="168" stroke="#1565c0" stroke-width="3" stroke-linecap="round"/>
  <!-- 大人シルエット（見守り） -->
  <circle cx="295" cy="150" r="9" fill="#FFCC80" stroke="#8d6e63" stroke-width="1.5"/>
  <line x1="295" y1="159" x2="295" y2="185" stroke="#6a1b9a" stroke-width="4" stroke-linecap="round"/>
  <line x1="295" y1="168" x2="281" y2="162" stroke="#6a1b9a" stroke-width="3" stroke-linecap="round"/>
  <line x1="295" y1="168" x2="306" y2="162" stroke="#6a1b9a" stroke-width="3" stroke-linecap="round"/>
  <line x1="295" y1="185" x2="289" y2="200" stroke="#6a1b9a" stroke-width="3" stroke-linecap="round"/>
  <line x1="295" y1="185" x2="301" y2="200" stroke="#6a1b9a" stroke-width="3" stroke-linecap="round"/>
  <text x="295" y="141" text-anchor="middle" font-size="8" fill="#4a148c" font-family="sans-serif">見守り</text>
  <!-- 完成ラベル -->
  <text x="160" y="226" text-anchor="middle" font-size="9" fill="#2d6a2d" font-weight="bold" font-family="sans-serif">🎉 完成！使用前に必ず大人が動作確認をしてください</text>
</svg>'''


def _svg_swing_safety() -> str:
    """安全点検チェックポイントのSVG"""
    return '''<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:320px;height:auto;">
  <text x="160" y="16" text-anchor="middle" font-size="11" font-weight="bold" fill="#c62828" font-family="sans-serif">⚠️ 安全点検ポイント</text>
  <!-- 支柱と梁の全体図（簡略） -->
  <line x1="60" y1="175" x2="95" y2="70" stroke="#4caf50" stroke-width="10" stroke-linecap="round"/>
  <line x1="260" y1="175" x2="225" y2="70" stroke="#4caf50" stroke-width="10" stroke-linecap="round"/>
  <rect x="82" y="55" width="156" height="16" rx="6" fill="#2e7d32" stroke="#1b5e20" stroke-width="2"/>
  <line x1="115" y1="69" x2="115" y2="145" stroke="#BA7517" stroke-width="4"/>
  <line x1="205" y1="69" x2="205" y2="145" stroke="#BA7517" stroke-width="4"/>
  <rect x="100" y="138" width="120" height="14" rx="5" fill="#4caf50" stroke="#2e7d32" stroke-width="1.5"/>
  <!-- チェックポイント1: 頂点結束 -->
  <circle cx="95" cy="70" r="9" fill="#e53935" opacity="0.8" stroke="#b71c1c" stroke-width="1.5"/>
  <text x="95" y="73" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">1</text>
  <line x1="95" y1="61" x2="32" y2="44" stroke="#c62828" stroke-width="1"/>
  <text x="30" y="40" text-anchor="end" font-size="7.5" fill="#c62828" font-family="sans-serif">頂点の結束</text>
  <!-- チェックポイント2: 梁とロープ -->
  <circle cx="115" cy="69" r="9" fill="#e53935" opacity="0.8" stroke="#b71c1c" stroke-width="1.5"/>
  <text x="115" y="72" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">2</text>
  <line x1="115" y1="60" x2="80" y2="38" stroke="#c62828" stroke-width="1"/>
  <text x="78" y="34" text-anchor="end" font-size="7.5" fill="#c62828" font-family="sans-serif">梁×ロープ結束</text>
  <!-- チェックポイント3: 地面固定 -->
  <circle cx="60" cy="170" r="9" fill="#e53935" opacity="0.8" stroke="#b71c1c" stroke-width="1.5"/>
  <text x="60" y="173" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">3</text>
  <line x1="51" y1="170" x2="22" y2="175" stroke="#c62828" stroke-width="1"/>
  <text x="20" y="171" text-anchor="end" font-size="7.5" fill="#c62828" font-family="sans-serif">地面固定</text>
  <!-- チェックポイント4: 座面結束 -->
  <circle cx="115" cy="145" r="9" fill="#e53935" opacity="0.8" stroke="#b71c1c" stroke-width="1.5"/>
  <text x="115" y="148" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">4</text>
  <line x1="106" y1="148" x2="50" y2="160" stroke="#c62828" stroke-width="1"/>
  <text x="48" y="156" text-anchor="end" font-size="7.5" fill="#c62828" font-family="sans-serif">座面結束</text>
  <!-- チェックポイント5: 竹割れ -->
  <circle cx="225" cy="70" r="9" fill="#e53935" opacity="0.8" stroke="#b71c1c" stroke-width="1.5"/>
  <text x="225" y="73" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">5</text>
  <line x1="234" y1="66" x2="280" y2="44" stroke="#c62828" stroke-width="1"/>
  <text x="282" y="40" font-size="7.5" fill="#c62828" font-family="sans-serif">竹の割れ確認</text>
  <!-- 説明 -->
  <text x="160" y="192" text-anchor="middle" font-size="8.5" fill="#37474f" font-family="sans-serif">使用前・使用後に必ず全ポイントを目視・手動で確認！</text>
</svg>'''


def render_swing_construction_guide(diameter_cm: float):
    """
    ブランコの製作手順ガイドを表示する。
    diameter_cm: サイドバーで設定した竹の直径（cm）。
    """
    st.subheader("🔨 竹ブランコ　製作手順ガイド")

    st.warning(
        "⚠️ **製作前に必ずお読みください**\n\n"
        "このガイドは竹製ブランコの一般的な製作手順を示すものです。"
        "竹は天然材料のため個体差が大きく、本ガイド通りに製作しても安全を保証するものではありません。"
        "**製作・設置・使用前に、必ず建築士・構造専門家による安全確認を受けてください。**\n\n"
        "ブランコは揺れによる動的荷重が静荷重の3〜5倍になります。"
        "**必ず大人が付き添い、子どもだけで使用させないでください。**"
    )

    steps = [
        {
            "title": "① 竹を8本切り出す",
            "icon": "🪚",
            "svg": _svg_swing_step1_cut,
            "desc": (
                "乾燥した太め（直径**8cm以上**）の丈夫な竹を**合計8本**切り出します。\n\n"
                "- **支柱用**：3本 × 2箇所（左脚・右脚）＝ **6本**\n"
                "- **水平梁用**（横材）：**1本**（太くて丈夫なものを選ぶ）\n"
                "- **椅子（座面）用**：**1本**\n\n"
                "**乾燥した竹**を使用してください。生竹（切り出して1ヶ月未満）は強度が約30%低下します。"
            ),
            "points": [
                "竹を叩いたとき高く乾いた音がするものを選ぶ（生竹は鈍い音）。",
                "割れ・虫食い・カビがある竹は絶対に使用しない。",
                "節間が30cm以下・肉厚のものを選ぶ（強度が高い）。",
                "支柱竹は荷重がかかる部分（支点・接合部）の直上・直下に節が来るように切る。",
                "横材用は特に太くて真っ直ぐなものを選ぶ（直径10cm以上推奨）。",
                "防護手袋・保護メガネを着用して作業すること。",
            ],
        },
        {
            "title": "② 上端のみ結束し、三角錐状に広げて地中固定する",
            "icon": "🪢",
            "svg": _svg_swing_step2_bind,
            "desc": (
                "竹3本を束ね、**上端1箇所だけ**を耐候性ロープでしっかり結束します。\n\n"
                "結束後、上端を中心に3本の竹を**三角錐（トライポッド）状**に均等に広げ、"
                "それぞれの竹の先端を地面に掘った穴（深さ30cm以上）に差し込んで固定します。\n\n"
                "中・下は結ばず、**竹3本が独立して地面に刺さる**ことで安定します。"
                "これを左右2セット作ります。"
            ),
            "points": [
                "結ぶのは上端の1箇所のみ！中・下は結ばない。",
                "上端はロープを5回以上しっかり巻きつけてほどけないよう固定する。",
                "3本の足先を均等な角度（約120°間隔）に広げ、バランスよく配置する。",
                "各竹の足先を深さ30cm以上の穴に差し込み、砂利と土で突き固める。",
                "設置後に全力で揺らしてぐらつかないか必ず確認する。",
                "ポリエステル・ナイロン製の耐候性ロープを使用する（天然繊維ロープは雨で劣化）。",
            ],
        },
        {
            "title": "③ 穴を掘り、立ち上げて固定する",
            "icon": "⛏️",
            "svg": _svg_swing_step3_erect,
            "desc": (
                "地面に深さ**30cm以上**の穴を2箇所掘り、"
                "竹束（脚）の先端を埋めて固定します。\n\n"
                "竹束は**重い**ため、**2〜3人で協力**して立ち上げてください。"
                "1人で無理に立てようとすると倒れて怪我をする危険があります。\n\n"
                "穴に竹を立てたら、砂利と土を交互に入れながら**突き固め**てください。"
            ),
            "points": [
                "⚠️ 必ず2〜3人で作業すること。1人での立ち上げは危険！",
                "穴は30cm以上の深さを確保する（軟弱地盤は40cm以上）。",
                "砂利と土を交互に充填し、棒などで突き固める（タンピング）。",
                "立ち上げ後に竹束を強く揺らし、ぐらつきがないか確認する。",
                "傾斜地・水はけが悪い場所・軟弱な地盤には設置しない。",
                "地中に石やコンクリートがある場合は専門家に相談すること。",
            ],
        },
        {
            "title": "④ 太い竹を水平に渡す（梁）",
            "icon": "🪵",
            "svg": _svg_swing_step4_beam,
            "desc": (
                "左右の逆V字フレームの頂点に、**太くて丈夫な竹**を水平に渡します。"
                "この竹が「梁」となり、ロープとブランコの荷重を支えます。\n\n"
                "梁は直径**8cm以上**の太い竹を選び、"
                "両端をロープでしっかり固定してください。"
                "水平器を使って**水平になっているか**確認することが重要です。"
            ),
            "points": [
                "梁には支柱より太い竹（直径8〜12cm以上）を選ぶ。",
                "梁の長さは左右フレームの外側まで十分に余裕を持たせる。",
                "各接合部はロープを5回以上巻き付け、複数箇所で結束する。",
                "水平器やスマートフォンの水準アプリで水平を確認する。",
                "梁の中央部分を手で押してたわみがないか確認する。",
            ],
        },
        {
            "title": "⑤ ロープを2本渡す",
            "icon": "🔗",
            "svg": _svg_swing_step5_rope,
            "desc": (
                "梁に**耐荷重200kg以上**のロープを2本、"
                "座面幅（約40〜50cm）間隔で取り付けます。\n\n"
                "ロープは梁に**3回以上しっかり巻きつけ**、"
                "ほどけないよう固定してください。"
                "ロープの長さは座面の高さが地面から**30〜45cm**になるよう調整します。"
            ),
            "points": [
                "耐荷重200kg以上（体重 × 動的係数3.5を考慮）のロープを使用する。",
                "ロープは梁に3回以上巻き付けてから結ぶ。",
                "座面高さ（地面からの距離）は30〜45cmを目安にする。",
                "左右のロープ長さを揃えて水平になるよう調整する。",
                "ロープと竹の接触部分は摩耗しやすいため、当て布や保護材を入れる。",
                "紫外線・雨に強いポリエステルロープを推奨。",
            ],
        },
        {
            "title": "⑥ 座面となる竹を括り付けて完成",
            "icon": "🎉",
            "svg": _svg_swing_step6_seat,
            "desc": (
                "2本のロープの下端に、**座面用の竹**（幅広の板竹または丸竹）を"
                "しっかり括り付けて完成です。\n\n"
                "座面竹はロープの両側で**ほどけないよう固定**してください。"
                "**完成後は必ず大人が先に試乗して安全を確認**してから子どもに使わせてください。"
            ),
            "points": [
                "座面竹はロープを3回以上巻きつけ、ほどけないよう結ぶ。",
                "座面竹の切り口はヤスリで削り、バリ・割れ目がないようにする。",
                "座面の幅は使用者の体に合わせて調整する（目安：30〜40cm）。",
                "完成後は大人が体重をかけて揺らし、全結束点に異常がないか確認する。",
                "使用中は必ず大人が付き添う。一人で使用させない。",
                "雨の日・強風時は使用しない。使用後はロープを屋根下に保管する。",
            ],
        },
    ]

    import base64

    def _render_svg(svg_str: str):
        b64 = base64.b64encode(svg_str.encode("utf-8")).decode("utf-8")
        st.markdown(
            f'<img src="data:image/svg+xml;base64,{b64}" '
            f'style="width:100%;max-width:380px;height:auto;display:block;" />',
            unsafe_allow_html=True,
        )

    for step in steps:
        with st.expander(f"{step['icon']} {step['title']}", expanded=False):
            col_img, col_text = st.columns([1, 1])
            with col_img:
                _render_svg(step["svg"]())
            with col_text:
                st.markdown(step["desc"])
                st.markdown("**📌 ポイント：**")
                for pt in step["points"]:
                    st.markdown(f"- {pt}")

    # ── 安全点検チェックリスト ──
    st.divider()
    with st.expander("🔴 安全点検チェックリスト（使用前・月1回必須）", expanded=False):
        col_check, col_svg = st.columns([1, 1])
        with col_svg:
            _render_svg(_svg_swing_safety())
        with col_check:
            st.markdown("""
**✅ 使用前の点検（毎回実施）**
- ❶ 頂点の結束ロープがほどけていない
- ❷ 梁とロープの結束が緩んでいない
- ❸ 支柱のぐらつき・傾きがない
- ❹ 座面竹の結束が緩んでいない
- ❺ 竹に新しい割れ・虫食いがない
- ❻ ロープに摩耗・毛羽立ちがない
- ❼ 使用前に大人が試乗して異常がないか確認

**🚫 こんなときは使用禁止**
- 竹に縦割れが入っている
- ロープが毛羽立ち・変色している
- 支柱がぐらつく
- 雨天・強風時
- 大人が付き添えないとき
""")
    st.info(
        "💡 **月1回の定期点検**を習慣にしましょう。\n\n"
        f"現在の設定：竹の直径 **{diameter_cm:.1f}cm**。"
        "竹の劣化・ロープの摩耗・地面固定の緩みを確認し、"
        "異常があれば即座に使用禁止にして修理・撤去してください。"
    )


# ══════════════════════════════════════════════════════════════════
# ジャングルジム製作手順ガイド用 SVG イラスト
# ══════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════
# ジャングルジム製作手順ガイド用 SVG イラスト（写真に忠実・改訂版）
# ══════════════════════════════════════════════════════════════════

def _svg_jg_step1_hexagon() -> str:
    """1 hexagon base + 6 pillars converging to apex (tipi style)"""
    import math as _m
    cx, cy_g, R = 180, 195, 80
    def hp(i):
        a = _m.radians(90 + 60*i)
        return cx + R*_m.cos(a), cy_g - R*_m.sin(a)*0.28  # y圧縮を小さくして④を地面上に
    pts = [hp(i) for i in range(6)]
    apex = (180, 40)
    do = [3,4,5,0,1,2]
    gh = "".join(
        f'<line x1="{pts[i][0]:.1f}" y1="{pts[i][1]:.1f}"'
        f' x2="{pts[(i+1)%6][0]:.1f}" y2="{pts[(i+1)%6][1]:.1f}"'
        f' stroke="#4caf50" stroke-width="13" stroke-linecap="round" opacity="0.92"/>'
        for i in do)
    ops = [0.52,0.60,0.70,0.80,0.90,0.99]
    pl = "".join(
        f'<line x1="{pts[i][0]:.1f}" y1="{pts[i][1]:.1f}"'
        f' x2="{apex[0]}" y2="{apex[1]}"'
        f' stroke="#2e7d32" stroke-width="11" stroke-linecap="round" opacity="{ops[j]}"/>'
        for j,i in enumerate(do))
    lb = "".join(
        f'<circle cx="{pts[i][0]:.1f}" cy="{pts[i][1]:.1f}" r="14"'
        f' fill="#4caf50" stroke="#1b5e20" stroke-width="2"/>'
        f'<text x="{pts[i][0]:.1f}" y="{pts[i][1]+4:.1f}" text-anchor="middle"'
        f' font-size="9" fill="white" font-weight="bold" font-family="sans-serif">{i+1}</text>'
        for i in range(6))
    # ④の実際のy座標を確認して地面ラインを設定
    y4 = pts[3][1]  # ④(i=3)のy座標
    ground_y = y4 + 18  # ④の円の下端より少し下
    return f'''<svg viewBox="0 0 360 300" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:360px;height:auto;">
  <text x="180" y="16" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">竹を六角形に配置し支柱6本を頂点で結束</text>
  <rect x="0" y="{ground_y:.0f}" width="360" height="12" fill="#d7ccc8"/>
  <line x1="0" y1="{ground_y:.0f}" x2="360" y2="{ground_y:.0f}" stroke="#795548" stroke-width="2"/>
  {gh}
  {pl}
  {lb}
  <circle cx="{apex[0]}" cy="{apex[1]}" r="18" fill="#BA7517" stroke="#8B4513" stroke-width="2.5"/>
  <text x="{apex[0]}" y="{apex[1]-3}" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">上部</text>
  <text x="{apex[0]}" y="{apex[1]+8}" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">結束</text>
  <rect x="170" y="82" width="20" height="118" rx="3" fill="#8d6e63" stroke="#5d4037" stroke-width="1.5" opacity="0.80"/>
  <line x1="170" y1="98"  x2="190" y2="98"  stroke="#5d4037" stroke-width="2.5"/>
  <line x1="170" y1="116" x2="190" y2="116" stroke="#5d4037" stroke-width="2.5"/>
  <line x1="170" y1="134" x2="190" y2="134" stroke="#5d4037" stroke-width="2.5"/>
  <line x1="170" y1="152" x2="190" y2="152" stroke="#5d4037" stroke-width="2.5"/>
  <line x1="170" y1="170" x2="190" y2="170" stroke="#5d4037" stroke-width="2.5"/>
  <line x1="170" y1="188" x2="190" y2="188" stroke="#5d4037" stroke-width="2.5"/>
  <text x="198" y="138" font-size="8" fill="#5d4037" font-weight="bold" font-family="sans-serif">はしご</text>
  <text x="198" y="149" font-size="7.5" fill="#5d4037" font-family="sans-serif">中央に設置</text>
  <text x="198" y="159" font-size="7.5" fill="#5d4037" font-family="sans-serif">上部作業が楽！</text>
  <rect x="4" y="{ground_y+16:.0f}" width="352" height="54" rx="4" fill="#e8f5e9" stroke="#388e3c" stroke-width="1.2"/>
  <text x="180" y="{ground_y+32:.0f}" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">支柱6本を角に配置。まとめて頂点でロープを5回以上巻き結束</text>
  <text x="180" y="{ground_y+46:.0f}" text-anchor="middle" font-size="8" fill="#37474f" font-family="sans-serif">60度間隔で均等に広がっているか確認する</text>
  <text x="180" y="{ground_y+60:.0f}" text-anchor="middle" font-size="8" fill="#c62828" font-weight="bold" font-family="sans-serif">①②③④⑤⑥：各角の支柱位置（④は正面手前）</text>
</svg>'''


def _svg_jg_step2_tier1() -> str:
    """2 tier1: 12 knots, diagonal placement"""
    import math as _m
    cx, cy_g, R = 180, 202, 78
    def hp(i):
        a = _m.radians(90 + 60*i)
        return cx + R*_m.cos(a), cy_g - R*_m.sin(a)*0.38
    pts = [hp(i) for i in range(6)]
    apex = (180, 44)
    do = [3,4,5,0,1,2]
    ops2 = [0.52,0.60,0.70,0.80,0.90,0.99]
    pl = "".join(
        f'<line x1="{pts[i][0]:.1f}" y1="{pts[i][1]:.1f}"'
        f' x2="{apex[0]}" y2="{apex[1]}"'
        f' stroke="#2e7d32" stroke-width="10" stroke-linecap="round" opacity="{ops2[j]*0.5:.2f}"/>'
        for j,i in enumerate(do))
    t1 = ""
    k1 = ""
    for j,i in enumerate(do):
        x1,y1 = pts[i]; x2,y2 = pts[(i+1)%6]
        off = j * 4
        y1t = y1 - 36 - off; y2t = y2 - 40 - off
        t1 += (f'<line x1="{x1:.1f}" y1="{y1t:.1f}" x2="{x2:.1f}" y2="{y2t:.1f}"'
               f' stroke="#4caf50" stroke-width="10" stroke-linecap="round" opacity="0.95"/>')
        k1 += (f'<circle cx="{x1:.1f}" cy="{y1t:.1f}" r="9" fill="#e53935" stroke="#b71c1c" stroke-width="1.5" opacity="0.92"/>'
               f'<text x="{x1:.1f}" y="{y1t+3:.1f}" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結</text>'
               f'<circle cx="{x2:.1f}" cy="{y2t:.1f}" r="9" fill="#e53935" stroke="#b71c1c" stroke-width="1.5" opacity="0.92"/>'
               f'<text x="{x2:.1f}" y="{y2t+3:.1f}" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結</text>')
    return f'''<svg viewBox="0 0 360 480" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:360px;height:auto;">
  <text x="180" y="16" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">1段目：斜め配置で各支柱2箇所ずつ計12箇所結束</text>

  <!-- ══ 上段：斜め設置のしくみ（側面図）══ -->
  <text x="180" y="34" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">斜め設置のしくみ（側面図）</text>
  <line x1="60"  y1="218" x2="130" y2="52"  stroke="#2e7d32" stroke-width="9" stroke-linecap="round"/>
  <line x1="300" y1="218" x2="230" y2="52"  stroke="#2e7d32" stroke-width="9" stroke-linecap="round"/>
  <circle cx="180" cy="50" r="12" fill="#BA7517" stroke="#8B4513" stroke-width="2"/>
  <text x="180" y="54" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">頂点</text>
  <!-- 1段目竹（斜め） -->
  <line x1="46"  y1="158" x2="316" y2="136" stroke="#4caf50" stroke-width="11" stroke-linecap="round"/>
  <circle cx="60"  cy="158" r="9" fill="#e53935" stroke="#b71c1c" stroke-width="1.5" opacity="0.9"/>
  <text x="60"  y="162" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結</text>
  <circle cx="300" cy="136" r="9" fill="#e53935" stroke="#b71c1c" stroke-width="1.5" opacity="0.9"/>
  <text x="300" y="140" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結</text>
  <!-- 2段目竹（斜め・薄） -->
  <line x1="46"  y1="110" x2="316" y2="88"  stroke="#81c784" stroke-width="11" stroke-linecap="round" opacity="0.78"/>
  <circle cx="60"  cy="110" r="9" fill="#e53935" stroke="#b71c1c" stroke-width="1.5" opacity="0.9"/>
  <text x="60"  y="114" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結</text>
  <circle cx="300" cy="88"  r="9" fill="#e53935" stroke="#b71c1c" stroke-width="1.5" opacity="0.9"/>
  <text x="300" y="92"  text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結</text>
  <!-- 高さ差の寸法矢印 -->
  <line x1="26" y1="110" x2="26" y2="158" stroke="#e53935" stroke-width="1.5"/>
  <line x1="22" y1="110" x2="30" y2="110" stroke="#e53935" stroke-width="1.5"/>
  <line x1="22" y1="158" x2="30" y2="158" stroke="#e53935" stroke-width="1.5"/>
  <!-- 地面 -->
  <line x1="30" y1="218" x2="330" y2="218" stroke="#795548" stroke-width="2"/>
  <!-- 説明ボックス -->
  <rect x="60" y="228" width="240" height="38" rx="4" fill="#fff8e1" stroke="#f57f17" stroke-width="1.2"/>
  <text x="180" y="243" text-anchor="middle" font-size="9" fill="#e65100" font-weight="bold" font-family="sans-serif">水平でなく竹径分傾ける！</text>
  <text x="180" y="259" text-anchor="middle" font-size="8.5" fill="#37474f" font-family="sans-serif">1周すると同じ高さに揃う</text>

  <!-- 区切り線 -->
  <line x1="20" y1="278" x2="340" y2="278" stroke="#c8e6c9" stroke-width="1.5" stroke-dasharray="6,4"/>

  <!-- ══ 下段：斜視図（1段目の状態）══ -->
  <text x="180" y="298" text-anchor="middle" font-size="9" fill="#1565c0" font-weight="bold" font-family="sans-serif">斜視図（1段目の状態）</text>
  <!-- 地面（下段） -->
  <rect x="0" y="448" width="360" height="20" fill="#d7ccc8"/>
  <line x1="0" y1="448" x2="360" y2="448" stroke="#795548" stroke-width="2"/>
  <!-- 支柱（下段・斜視・座標をY+290シフト） -->
  {chr(10).join(
    f'<line x1="{pts[i][0]:.1f}" y1="{pts[i][1]+290:.1f}"'
    f' x2="{apex[0]}" y2="{apex[1]+290}"'
    f' stroke="#2e7d32" stroke-width="10" stroke-linecap="round" opacity="{ops2[j]*0.5:.2f}"/>'
    for j,i in enumerate(do))}
  <!-- 頂点（下段） -->
  <circle cx="{apex[0]}" cy="{apex[1]+290}" r="14" fill="#BA7517" stroke="#8B4513" stroke-width="2"/>
  <text x="{apex[0]}" y="{apex[1]+294}" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結束</text>
  <!-- 1段目横竹（下段・斜め螺旋・Y+290シフト） -->
  {chr(10).join(
    f'<line x1="{pts[do[j]][0]:.1f}" y1="{pts[do[j]][1]-36-j*4+290:.1f}"'
    f' x2="{pts[(do[j]+1)%6][0]:.1f}" y2="{pts[(do[j]+1)%6][1]-40-j*4+290:.1f}"'
    f' stroke="#4caf50" stroke-width="10" stroke-linecap="round" opacity="0.95"/>'
    for j in range(6))}
  <!-- 結束マーク12箇所（下段・Y+290シフト） -->
  {chr(10).join(
    f'<circle cx="{pts[do[j]][0]:.1f}" cy="{pts[do[j]][1]-36-j*4+290:.1f}" r="9" fill="#e53935" stroke="#b71c1c" stroke-width="1.5" opacity="0.92"/>'
    f'<text x="{pts[do[j]][0]:.1f}" y="{pts[do[j]][1]-33-j*4+290:.1f}" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結</text>'
    f'<circle cx="{pts[(do[j]+1)%6][0]:.1f}" cy="{pts[(do[j]+1)%6][1]-40-j*4+290:.1f}" r="9" fill="#e53935" stroke="#b71c1c" stroke-width="1.5" opacity="0.92"/>'
    f'<text x="{pts[(do[j]+1)%6][0]:.1f}" y="{pts[(do[j]+1)%6][1]-37-j*4+290:.1f}" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結</text>'
    for j in range(6))}
  <!-- 凡例ボックス（下段） -->
  <rect x="60" y="456" width="240" height="18" rx="3" fill="#e8f5e9" stroke="#388e3c" stroke-width="1"/>
  <text x="180" y="469" text-anchor="middle" font-size="8" fill="#1b5e20" font-weight="bold" font-family="sans-serif">結束12箇所　麻紐3〜4m/1箇所</text>
</svg>'''


def _svg_jg_step3_tier2() -> str:
    """3 tier2 added: 24 knots total"""
    import math as _m
    cx, cy_g, R = 180, 202, 76
    def hp(i):
        a = _m.radians(90 + 60*i)
        return cx + R*_m.cos(a), cy_g - R*_m.sin(a)*0.38
    pts = [hp(i) for i in range(6)]
    apex = (180, 44)
    do = [3,4,5,0,1,2]
    ops3 = [0.28,0.33,0.38,0.44,0.50,0.56]
    pl = "".join(
        f'<line x1="{pts[i][0]:.1f}" y1="{pts[i][1]:.1f}"'
        f' x2="{apex[0]}" y2="{apex[1]}"'
        f' stroke="#2e7d32" stroke-width="10" stroke-linecap="round" opacity="{ops3[j]}"/>'
        for j,i in enumerate(do))
    def make_tier(y_off, color, kcolor):
        seg = ""; kn = ""
        for j,i in enumerate(do):
            x1,y1 = pts[i]; x2,y2 = pts[(i+1)%6]
            off = j*4
            y1t = y1 - y_off - off; y2t = y2 - y_off - 4 - off
            seg += (f'<line x1="{x1:.1f}" y1="{y1t:.1f}" x2="{x2:.1f}" y2="{y2t:.1f}"'
                    f' stroke="{color}" stroke-width="10" stroke-linecap="round" opacity="0.92"/>')
            kn  += (f'<circle cx="{x1:.1f}" cy="{y1t:.1f}" r="8" fill="{kcolor}" stroke="#b71c1c" stroke-width="1.4" opacity="0.92"/>'
                    f'<text x="{x1:.1f}" y="{y1t+3:.1f}" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結</text>'
                    f'<circle cx="{x2:.1f}" cy="{y2t:.1f}" r="8" fill="{kcolor}" stroke="#b71c1c" stroke-width="1.4" opacity="0.92"/>'
                    f'<text x="{x2:.1f}" y="{y2t+3:.1f}" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">結</text>')
        return seg, kn
    t1, k1 = make_tier(36, "#4caf50", "#e53935")
    t2, k2 = make_tier(90, "#81c784", "#f57f17")
    return f'''<svg viewBox="0 0 360 278" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:360px;height:auto;">
  <text x="180" y="16" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">2段目を設置して完成！（合計24箇所結束）</text>
  <rect x="0" y="232" width="360" height="34" fill="#d7ccc8"/>
  <line x1="0" y1="232" x2="360" y2="232" stroke="#795548" stroke-width="2"/>
  {pl}
  <circle cx="{apex[0]}" cy="{apex[1]}" r="15" fill="#BA7517" stroke="#8B4513" stroke-width="2.5"/>
  <text x="{apex[0]}" y="{apex[1]+4}" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">結束</text>
  {t1}
  {k1}
  {t2}
  {k2}
  <text x="12"  y="195" font-size="9" fill="#c62828" font-weight="bold" font-family="sans-serif">1段目</text>
  <text x="12"  y="145" font-size="9" fill="#e65100" font-weight="bold" font-family="sans-serif">2段目</text>
  <rect x="240" y="236" width="114" height="38" rx="4" fill="#f9fbe7" stroke="#aed581" stroke-width="1.2"/>
  <circle cx="252" cy="248" r="7" fill="#e53935" stroke="#b71c1c" stroke-width="1.2"/>
  <text x="264" y="251" font-size="8" fill="#c62828" font-family="sans-serif">1段目結束×12</text>
  <circle cx="252" cy="265" r="7" fill="#f57f17" stroke="#e65100" stroke-width="1.2"/>
  <text x="264" y="268" font-size="8" fill="#e65100" font-family="sans-serif">2段目結束×12</text>
  <text x="118" y="252" text-anchor="middle" font-size="9" fill="#e65100" font-weight="bold" font-family="sans-serif">合計24箇所結束</text>
  <text x="118" y="266" text-anchor="middle" font-size="8" fill="#37474f" font-family="sans-serif">麻紐3〜4m x 24箇所使用</text>
</svg>'''


def _svg_jg_step4_complete() -> str:
    """4 complete view with child climbing and adult watching"""
    import math as _m
    cx, cy_g, R = 180, 202, 76
    def hp(i):
        a = _m.radians(90 + 60*i)
        return cx + R*_m.cos(a), cy_g - R*_m.sin(a)*0.38
    pts = [hp(i) for i in range(6)]
    apex = (180, 44)
    do = [3,4,5,0,1,2]
    ops4 = [0.28,0.33,0.38,0.44,0.50,0.56]
    pl = "".join(
        f'<line x1="{pts[i][0]:.1f}" y1="{pts[i][1]:.1f}"'
        f' x2="{apex[0]}" y2="{apex[1]}"'
        f' stroke="#2e7d32" stroke-width="10" stroke-linecap="round" opacity="{ops4[j]}"/>'
        for j,i in enumerate(do))
    t1 = "".join(
        f'<line x1="{pts[i][0]:.1f}" y1="{pts[i][1]-36-j*4:.1f}"'
        f' x2="{pts[(i+1)%6][0]:.1f}" y2="{pts[(i+1)%6][1]-40-j*4:.1f}"'
        f' stroke="#4caf50" stroke-width="10" stroke-linecap="round" opacity="0.92"/>'
        for j,i in enumerate(do))
    t2 = "".join(
        f'<line x1="{pts[i][0]:.1f}" y1="{pts[i][1]-88-j*4:.1f}"'
        f' x2="{pts[(i+1)%6][0]:.1f}" y2="{pts[(i+1)%6][1]-92-j*4:.1f}"'
        f' stroke="#a5d6a7" stroke-width="10" stroke-linecap="round" opacity="0.94"/>'
        for j,i in enumerate(do))
    return f'''<svg viewBox="0 0 360 275" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:360px;height:auto;">
  <text x="180" y="16" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">完成！使用前に必ず安全点検を実施</text>
  <rect x="0" y="232" width="360" height="43" fill="#d7ccc8"/>
  <line x1="0" y1="232" x2="360" y2="232" stroke="#795548" stroke-width="2"/>
  {pl}
  <circle cx="{apex[0]}" cy="{apex[1]}" r="17" fill="#BA7517" stroke="#8B4513" stroke-width="2.5"/>
  <text x="{apex[0]}" y="{apex[1]+4}" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">結束</text>
  {t1}
  {t2}
  <circle cx="198" cy="120" r="10" fill="#FFCC80" stroke="#8d6e63" stroke-width="1.5"/>
  <line x1="198" y1="130" x2="198" y2="160" stroke="#1565c0" stroke-width="4" stroke-linecap="round"/>
  <line x1="198" y1="140" x2="184" y2="132" stroke="#1565c0" stroke-width="3" stroke-linecap="round"/>
  <line x1="198" y1="140" x2="212" y2="134" stroke="#1565c0" stroke-width="3" stroke-linecap="round"/>
  <line x1="198" y1="160" x2="190" y2="180" stroke="#1565c0" stroke-width="3" stroke-linecap="round"/>
  <line x1="198" y1="160" x2="206" y2="180" stroke="#1565c0" stroke-width="3" stroke-linecap="round"/>
  <circle cx="316" cy="185" r="10" fill="#FFCC80" stroke="#8d6e63" stroke-width="1.5"/>
  <line x1="316" y1="195" x2="316" y2="222" stroke="#6a1b9a" stroke-width="4" stroke-linecap="round"/>
  <line x1="316" y1="205" x2="302" y2="199" stroke="#6a1b9a" stroke-width="3" stroke-linecap="round"/>
  <line x1="316" y1="205" x2="328" y2="199" stroke="#6a1b9a" stroke-width="3" stroke-linecap="round"/>
  <line x1="316" y1="222" x2="308" y2="238" stroke="#6a1b9a" stroke-width="3" stroke-linecap="round"/>
  <line x1="316" y1="222" x2="324" y2="238" stroke="#6a1b9a" stroke-width="3" stroke-linecap="round"/>
  <text x="316" y="177" text-anchor="middle" font-size="8" fill="#4a148c" font-family="sans-serif">見守り必須</text>
  <text x="16" y="248" font-size="16" fill="#2e7d32" font-family="sans-serif">&#x2713;</text>
  <text x="34" y="252" font-size="8.5" fill="#1b5e20" font-weight="bold" font-family="sans-serif">全24箇所の結束の緩みなし</text>
  <text x="16" y="267" font-size="16" fill="#2e7d32" font-family="sans-serif">&#x2713;</text>
  <text x="34" y="270" font-size="8.5" fill="#1b5e20" font-weight="bold" font-family="sans-serif">竹の割れ・虫食いなし。大人が全体を揺らして確認</text>
</svg>'''

def render_junglegym_construction_guide(diameter_cm: float):
    """
    ジャングルジムの製作手順ガイドを表示する。
    diameter_cm: サイドバーで設定した竹の直径（cm）。
    """
    st.subheader("🔨 竹ジャングルジム　製作手順ガイド")

    st.warning(
        "⚠️ **製作前に必ずお読みください**\n\n"
        "このガイドは竹製ジャングルジムの一般的な製作手順を示すものです。"
        "竹は天然材料のため個体差が大きく、本ガイド通りに製作しても安全を保証するものではありません。"
        "**製作・設置・使用前に、必ず建築士・構造専門家による安全確認を受けてください。**\n\n"
        "子どもが高所に登る遊具です。**必ず大人が付き添い、子どもだけで使用させないでください。**"
    )

    steps = [
        {
            "title": "① 竹を六角形に置き、支柱6本を上部で結束する",
            "icon": "⬡",
            "svg": _svg_jg_step1_hexagon,
            "desc": (
                "まず地面に竹を**六角形**になるように6本配置します。"
                "その**6つの角（頂点）に支柱となる竹を1本ずつ立て**、"
                "上部（頂点）でほどけないようにしっかりと結束します。\n\n"
                "上部の結束作業は高所になるため、**中央にはしごや脚立を置く**と安全で作業しやすくなります。"
                "支柱6本が均等な角度で広がるよう調整してください。"
            ),
            "points": [
                "六角形の一辺の長さを揃えて地面に配置する（目安：使用者が登りやすい幅）。",
                "支柱6本の上部はまとめてロープで5回以上巻き、しっかり結束する。",
                "はしご・脚立を中央に置くと上部作業が安全にできる。",
                "支柱が均等な角度（約60°間隔）で広がっているか確認する。",
                "結束後、全力で揺らして頂点がずれないか確認する。",
                "割れ・虫食いのない乾燥竹（直径8cm以上）を使用すること。",
                "⚠️ **各支柱の足先を地中に30cm以上埋め込み固定すること。** 計算上、摩擦のみでは子どもが登ったときの横方向力に対して不十分なため、ブランコ同様の地中固定が必要です。",
            ],
        },
        {
            "title": "② 1段目：横竹を斜めに配置し、各支柱に2箇所ずつ結束（計12箇所）",
            "icon": "1️⃣",
            "svg": _svg_jg_step2_tier1,
            "desc": (
                "地面の6本の竹を使って1段目を作ります。"
                "横竹は**水平ではなく竹の直径分だけ斜め**に傾けて設置します。\n\n"
                "こうすることで六角形を1周したとき、"
                "**各ステップが同じ高さ**に揃い、登りやすくなります。\n\n"
                "横竹は各支柱と交差する点（辺の両端）で結束します。"
                "**1支柱につき2箇所 × 6支柱 ＝ 計12箇所**を結束してください。"
                "1箇所あたり麻紐（またはロープ）を**3〜4m**使用します。"
            ),
            "points": [
                "横竹は水平ではなく竹径分だけ斜め（約5〜10°傾斜）に設置する。",
                "1箇所あたり麻紐3〜4mをしっかり巻きつけて結ぶ。",
                "「本結び」や「巻き結び」などほどけにくい結び方を使用する。",
                "1支柱あたり2箇所（辺の両端）、6支柱で計12箇所結束する。",
                "結束後に全結束点を引っ張り、緩みがないか確認する。",
                "麻紐は天然素材で劣化しやすいため、ポリエステルロープ併用も検討する。",
            ],
        },
        {
            "title": "③ 2段目：さらに上の段に同様に横竹を設置（計24箇所）",
            "icon": "2️⃣",
            "svg": _svg_jg_step3_tier2,
            "desc": (
                "1段目と同様の要領で、**さらに上の位置に2段目**の横竹を設置します。\n\n"
                "2段目も同じく竹径分だけ斜めに傾けて配置し、"
                "各支柱に2箇所ずつ結束します。\n\n"
                "2段目の結束12箇所を加えると**合計24箇所の結束**となります。"
                "全ての結束点をしっかり固定して完成です。"
            ),
            "points": [
                "2段目の高さは子どもが安全に登れる高さに設定する（目安：1段目から40〜50cm上）。",
                "2段目も竹径分だけ斜め設置を忘れずに（1段目と同じ方向に傾ける）。",
                "1支柱あたり2箇所 × 6支柱 ＝ 12箇所追加結束する。",
                "1段目・2段目合わせて計24箇所全ての結束を確認する。",
                "全結束点を使用前に必ず手で引いて緩みがないか点検する。",
                "2段目上端の高さが1.2mを超える場合は転落リスクが高まるため注意する。",
            ],
        },
        {
            "title": "④ 完成・使用前安全点検",
            "icon": "🎉",
            "svg": _svg_jg_step4_complete,
            "desc": (
                "全ての結束が完了したら完成です。\n\n"
                "**使用前に必ず大人が全体を点検し、安全を確認**してから使用を開始してください。"
                "月1回以上の定期点検を習慣にしましょう。\n\n"
                "使用中は**必ず大人が付き添い**、子どもだけで使用させないでください。"
            ),
            "points": [
                "【使用前点検】頂点の結束・全24箇所の結束の緩みがないか確認する。",
                "【使用前点検】竹の割れ・虫食い・腐れがないか目視確認する。",
                "【使用前点検】大人が全体を揺らしてぐらつきがないか確認する。",
                "【使用前点検】突起・バリ・割れ端など怪我につながる箇所がないか確認する。",
                "【使用中】必ず大人が付き添う。複数の子どもが同時に登る場合は特に注意する。",
                "【月1回】竹の劣化・虫食い・結束の緩みを定期点検する。",
                "異常を発見したら即座に使用禁止にし、修理または撤去する。",
                "雨ざらしは竹の劣化を早める。使用後はシートで覆うか屋根下に保管する。",
            ],
        },
    ]

    import base64

    def _render_svg(svg_str: str):
        b64 = base64.b64encode(svg_str.encode("utf-8")).decode("utf-8")
        st.markdown(
            f'<img src="data:image/svg+xml;base64,{b64}" '
            f'style="width:100%;max-width:400px;height:auto;display:block;" />',
            unsafe_allow_html=True,
        )

    for step in steps:
        with st.expander(f"{step['icon']} {step['title']}", expanded=False):
            col_img, col_text = st.columns([1, 1])
            with col_img:
                _render_svg(step["svg"]())
            with col_text:
                st.markdown(step["desc"])
                st.markdown("**📌 ポイント：**")
                for pt in step["points"]:
                    st.markdown(f"- {pt}")

    # ── 安全点検チェックリスト ──
    st.divider()
    with st.expander("🔴 安全点検チェックリスト（使用前・月1回必須）", expanded=False):
        st.markdown(f"""
**✅ 使用前の点検（毎回実施）**
- ❶ 頂点の結束ロープがほどけていない
- ❷ 1段目・2段目 計24箇所の結束に緩みがない
- ❸ 竹に新しい割れ・虫食いがない
- ❹ 支柱がぐらつかない（大人が揺らして確認）
- ❺ 突起・バリ・割れ端など怪我につながる箇所がない
- ❻ 大人が付き添える状況である

**🚫 こんなときは使用禁止**
- 竹に縦割れが入っている
- 結束ロープが緩んでいる・毛羽立っている
- 支柱がぐらつく
- 雨天・強風時
- 大人が付き添えないとき
""")

    st.info(
        "💡 **月1回の定期点検**を習慣にしましょう。\n\n"
        f"現在の設定：竹の直径 **{diameter_cm:.1f}cm**。"
        "全24箇所の結束・竹の劣化・支柱の固定状態を確認し、"
        "異常があれば即座に使用禁止にして修理・撤去してください。"
    )


def _svg_step8_ladder() -> str:
    """⑧ 梯子（階段）正面図：縦桟2本＋踏み板＋上部ストッパー板（縦桟の奥・背面）"""
    return '''<svg viewBox="0 0 340 300" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:340px;height:auto;">
  <text x="170" y="14" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">階段（梯子）製作図</text>
  <text x="170" y="26" text-anchor="middle" font-size="8" fill="#1565c0" font-family="sans-serif">正面図・上部ストッパー板は縦桟の奥（背面）に取付</text>

  <!-- 地面 -->
  <rect x="0" y="268" width="340" height="18" fill="#d7ccc8"/>
  <line x1="0" y1="268" x2="340" y2="268" stroke="#795548" stroke-width="2"/>

  <!-- ===== 上部ストッパー板（縦桟の奥・背面に取付＝奥行き感で表現）===== -->
  <!-- 縦桟より奥にある板を3D風に描く。縦桟の上端よりやや上から、奥に引っ込んで見える -->
  <!-- 正面板（薄い色・奥にある印象） -->
  <rect x="52" y="38" width="174" height="18" rx="2" fill="#bf360c" stroke="#7f0000" stroke-width="1.5" opacity="0.85"/>
  <!-- 上面（奥行き感・右上にずらした台形） -->
  <polygon points="52,38 226,38 234,30 60,30" fill="#e64a19" stroke="#7f0000" stroke-width="1" opacity="0.9"/>
  <!-- 右側面（奥行き感） -->
  <polygon points="226,38 234,30 234,48 226,56" fill="#a33200" stroke="#7f0000" stroke-width="1" opacity="0.9"/>
  <text x="139" y="51" text-anchor="middle" font-size="8" fill="white" font-weight="bold" font-family="sans-serif">ストッパー板（縦桟の奥に取付）</text>

  <!-- ストッパー板の説明矢印 -->
  <line x1="245" y1="39" x2="260" y2="32" stroke="#e53935" stroke-width="1.5"/>
  <text x="295" y="30" text-anchor="middle" font-size="7.5" fill="#c62828" font-weight="bold" font-family="sans-serif">ローラーに引っかかる！</text>

  <!-- ===== 縦桟（左）・踏み板より手前に描く ===== -->
  <rect x="60" y="30" width="18" height="238" rx="3" fill="#8B6914" stroke="#5a4008" stroke-width="1.5"/>
  <!-- ===== 縦桟（右）===== -->
  <rect x="200" y="30" width="18" height="238" rx="3" fill="#8B6914" stroke="#5a4008" stroke-width="1.5"/>

  <!-- ===== 踏み板4段（縦桟の手前・横方向・1枚板）===== -->
  <!-- 段1（最下部） -->
  <rect x="58" y="228" width="162" height="12" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.4"/>
  <!-- 段2 -->
  <rect x="58" y="182" width="162" height="12" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.4"/>
  <!-- 段3 -->
  <rect x="58" y="136" width="162" height="12" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.4"/>
  <!-- 段4（最上段） -->
  <rect x="58" y="90" width="162" height="12" rx="2" fill="#a07832" stroke="#5a4008" stroke-width="1.4"/>

  <!-- ビス印（各踏み板左右） -->
  <circle cx="70" cy="234" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="208" cy="234" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="70" cy="188" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="208" cy="188" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="70" cy="142" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="208" cy="142" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="70" cy="96" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="208" cy="96" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>

  <!-- 寸法線（踏み板間隔） -->
  <line x1="234" y1="234" x2="234" y2="194" stroke="#1565c0" stroke-width="1.2"/>
  <line x1="230" y1="234" x2="238" y2="234" stroke="#1565c0" stroke-width="1.2"/>
  <line x1="230" y1="194" x2="238" y2="194" stroke="#1565c0" stroke-width="1.2"/>
  <text x="253" y="217" text-anchor="middle" font-size="7.5" fill="#1565c0" font-family="sans-serif">20〜25cm</text>
  <text x="253" y="227" text-anchor="middle" font-size="7.5" fill="#1565c0" font-family="sans-serif">等間隔</text>

  <!-- 注意ボックス -->
  <rect x="240" y="50" width="94" height="56" rx="4" fill="#fff8e1" stroke="#f57f17" stroke-width="1.2"/>
  <text x="287" y="65" text-anchor="middle" font-size="7.5" fill="#e65100" font-weight="bold" font-family="sans-serif">ストッパー板</text>
  <text x="287" y="77" text-anchor="middle" font-size="7" fill="#37474f" font-family="sans-serif">踏み板と反対側</text>
  <text x="287" y="88" text-anchor="middle" font-size="7" fill="#37474f" font-family="sans-serif">厚さ18mm以上</text>
  <text x="287" y="99" text-anchor="middle" font-size="7" fill="#c62828" font-weight="bold" font-family="sans-serif">ズレ防止に必須！</text>
</svg>'''


def _svg_step9_stairs() -> str:
    """⑧ 上り用階段の製作（縦桟が斜めに傾いた実物通りの形・側面図）"""
    return '''<svg viewBox="0 0 340 310" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:340px;height:auto;">
  <text x="170" y="14" text-anchor="middle" font-size="11" font-weight="bold" fill="#2d6a2d" font-family="sans-serif">上り用階段の製作・取り付け</text>
  <text x="170" y="26" text-anchor="middle" font-size="8" fill="#1565c0" font-family="sans-serif">（側面から見た図 ― 縦桟は斜めに傾けて設置）</text>

  <!-- 地面 -->
  <rect x="0" y="265" width="340" height="20" fill="#d7ccc8"/>
  <line x1="0" y1="265" x2="340" y2="265" stroke="#795548" stroke-width="2"/>

  <!-- ===== 滑り台本体（右側）===== -->
  <!-- 支柱（垂直） -->
  <rect x="230" y="80" width="14" height="185" rx="3" fill="#8B6914" stroke="#5a4008" stroke-width="1.5"/>
  <!-- 斜面フレーム（支柱上端から右下へ） -->
  <polygon points="230,80 244,80 330,265 316,265" fill="#8B6914" stroke="#5a4008" stroke-width="1.2"/>
  <!-- ローラー竹（斜面上） -->
  <line x1="237" y1="84" x2="323" y2="263" stroke="#4caf50" stroke-width="8" stroke-linecap="round" opacity="0.9"/>

  <!-- ===== 階段本体（左側・斜めに傾いて設置）===== -->
  <!-- 縦桟（左）：下端=地面左寄り、上端=支柱上部に密着・斜めカット -->
  <!-- 縦桟は斜めに傾く：上端(170,82) 下端(60,265) -->
  <line x1="170" y1="82" x2="60" y2="265" stroke="#8B6914" stroke-width="10" stroke-linecap="round"/>
  <!-- 縦桟（右）：上端(230,82) 下端(120,265) -->
  <line x1="230" y1="82" x2="120" y2="265" stroke="#8B6914" stroke-width="10" stroke-linecap="round"/>

  <!-- 斜めカット（上端）マーカー -->
  <circle cx="170" cy="82" r="9" fill="#e53935" opacity="0.85" stroke="#b71c1c" stroke-width="1.5"/>
  <text x="170" y="86" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">斜切</text>
  <circle cx="230" cy="82" r="9" fill="#e53935" opacity="0.85" stroke="#b71c1c" stroke-width="1.5"/>
  <text x="230" y="86" text-anchor="middle" font-size="7" fill="white" font-weight="bold" font-family="sans-serif">斜切</text>

  <!-- 踏み板（横・3段）：縦桟の傾きに合わせて斜め配置 -->
  <!-- 各踏み板は縦桟に直交（地面に水平）して渡す -->
  <!-- 段1（最下部）: 縦桟の80%位置 -->
  <line x1="92" y1="221" x2="152" y2="221" stroke="#a07832" stroke-width="9" stroke-linecap="round"/>
  <!-- 段2（中）: 縦桟の55%位置 -->
  <line x1="115" y1="168" x2="175" y2="168" stroke="#a07832" stroke-width="9" stroke-linecap="round"/>
  <!-- 段3（上）: 縦桟の30%位置 -->
  <line x1="138" y1="115" x2="198" y2="115" stroke="#a07832" stroke-width="9" stroke-linecap="round"/>

  <!-- ビス印（各踏み板・両端） -->
  <circle cx="95"  cy="221" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="149" cy="221" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="118" cy="168" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="172" cy="168" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="141" cy="115" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>
  <circle cx="195" cy="115" r="3" fill="#555" stroke="#333" stroke-width="0.8"/>

  <!-- 注意ラベル（上端斜め切断） -->
  <rect x="4" y="55" width="140" height="24" rx="4" fill="#fff8e1" stroke="#f57f17" stroke-width="1.2"/>
  <text x="74" y="66" text-anchor="middle" font-size="7.5" fill="#e65100" font-weight="bold" font-family="sans-serif">⚠️ 上端はローラー面の</text>
  <text x="74" y="76" text-anchor="middle" font-size="7.5" fill="#e65100" font-weight="bold" font-family="sans-serif">角度に合わせて斜めカット</text>

  <!-- 踏み板説明 -->
  <rect x="250" y="130" width="86" height="24" rx="4" fill="#e8f5e9" stroke="#388e3c" stroke-width="1.2"/>
  <text x="293" y="142" text-anchor="middle" font-size="7.5" fill="#1b5e20" font-weight="bold" font-family="sans-serif">踏み板：1枚板</text>
  <text x="293" y="152" text-anchor="middle" font-size="7" fill="#37474f" font-family="sans-serif">厚さ18mm以上</text>

  <!-- 完成ラベル -->
  <rect x="250" y="162" width="86" height="22" rx="4" fill="#e3f2fd" stroke="#1565c0" stroke-width="1.2"/>
  <text x="293" y="177" text-anchor="middle" font-size="7.5" fill="#1565c0" font-weight="bold" font-family="sans-serif">全ビスで固定！</text>

  <!-- 着色防腐剤ラベル -->
  <rect x="250" y="192" width="86" height="24" rx="4" fill="#fce4ec" stroke="#c62828" stroke-width="1.2"/>
  <text x="293" y="204" text-anchor="middle" font-size="7" fill="#c62828" font-weight="bold" font-family="sans-serif">防腐剤塗布</text>
  <text x="293" y="214" text-anchor="middle" font-size="7" fill="#37474f" font-family="sans-serif">ブラウン系推奨</text>
</svg>'''


def render_slide_construction_guide(diameter_cm: float):
    """
    滑り台の製作手順ガイドを表示する（全指摘反映・安全設計版）。
    diameter_cm: サイドバーで設定した竹の直径（cm）。
    """
    st.subheader("🔨 竹滑り台　製作手順ガイド")

    st.warning(
        "⚠️ **製作前に必ずお読みください**\n\n"
        "このガイドは竹コースター滑り台の一般的な製作手順を示すものです。"
        "竹は天然材料のため個体差が大きく、本ガイド通りに製作しても安全を保証するものではありません。"
        "**製作・設置・使用前に、必ず建築士・構造専門家による安全確認を受けてください。**"
    )

    steps = [
        {
            "title": "① コースターの芯（直管パイプ）を用意する",
            "icon": "🔩",
            "svg": _svg_step1_pipe,
            "desc": (
                "滑り面を構成するローラー竹の芯材として、金属製の**直管パイプ**を使用します。"
                "パイプを竹の内腔に通すことで芯が入り、強度と横ずれ防止の役割を果たします。\n\n"
                "**参考動画では竹の直径が約7cmのため、直管パイプ φ19mm（最細規格）を使用しています。**"
                "竹の直径が大きい場合はパイプ径も合わせて選んでください。"
            ),
            "points": [
                "パイプ外径は竹の内径より必ず小さいものを選ぶ（内径に余裕が必要）。",
                "【目安】竹径 約7cm → φ19mm / 竹径 約8〜10cm → φ25.4mm / 竹径 約10〜12cm → φ34mm",
                "亜鉛メッキ単管パイプは錆びにくく屋外使用に適している。",
                "パイプ長さ ＝ 竹の長さ ＋ 両端の垂木ブロック固定代（各側80mm）。竹より長くする必要がある。",
                "📐 **参考：垂木ブロック 8cm×8cm を使用する場合** → 片側8cm × 2 ＝ パイプが竹より16cm長くなります。",
            ],
        },
        {
            "title": "② パイプカッターで一定の長さに切断する",
            "icon": "✂️",
            "svg": _svg_step2_cut,
            "desc": (
                "**パイプカッター**を使ってパイプを正確に切断します。"
                "パイプは竹の長さより**長く**カットします。"
                "竹の両端からパイプが飛び出した部分を垂木ブロックで両側から固定することで、"
                "竹そのものがパイプを軸にして回転（ローラー）します。"
                "グラインダーでも切断可能ですが、パイプカッターの方が断面が垂直で安全です。"
            ),
            "points": [
                "パイプ長さ ＝ 竹の長さ ＋ 両端の垂木ブロック固定分（各側80mm）。",
                "📐 **参考：垂木ブロック 8cm×8cm を使用する場合** → 片側8cm、両端で＋16cm がパイプの余長になります。",
                "パイプが竹の両端から確実に飛び出していることを確認してからカットする。",
                "切断後は必ずヤスリでバリ取りを行う（子どもの手が触れる面は念入りに）。",
                "紙やすり（#120程度）で仕上げるとより安全。",
                "防護手袋・保護メガネを着用して作業すること。",
            ],
        },
        {
            "title": "③ 竹の節をハンマーや棒で叩いて抜く",
            "icon": "🔨",
            "svg": _svg_step4_node,
            "desc": (
                "竹の内部には節（ふし）があるため、パイプを通す前に除去します。"
                "竹を作業台に固定してから、**パイプや太い棒を竹の内腔に差し込み、ハンマーで端から叩く**と節が抜けます。"
                "**必ず保護具を着用して作業してください。**"
            ),
            "points": [
                "🧤 防護手袋・🥽 保護メガネ・👟 安全靴（または厚底靴）を必ず着用。",
                "竹は作業台またはクランプでしっかり固定してから叩く。",
                "節の破片が鋭利なため、周囲に人が立ち入らないよう注意する。",
                "節を除去後、内腔をヤスリで軽く整えるとパイプが通しやすい。",
            ],
        },
        {
            "title": "④ 垂木ブロックでパイプ両端を挟み込み、ビスで固定する",
            "icon": "🪵",
            "svg": _svg_step3_clamp,
            "desc": (
                "側面の木材フレームに**垂木ブロックをパイプの両側に配置**し、"
                "パイプを挟み込む形でビス固定します。"
                "切り込み加工は不要です。"
                "**ポイントはパイプを固定し、竹はパイプの周りを自由に回転できる状態にすること**です。"
                "竹はパイプに対してフリーに回転（ローラー）するため、"
                "ブロックが固定するのはパイプであり、竹ではありません。"
                "ブロックの高さは竹の直径と同程度が目安で、フレームにしっかり固定されることで"
                "パイプがずれず安定したローラー面になります。"
            ),
            "points": [
                "垂木ブロックはパイプの上下から挟んでフレームにビス固定する。",
                "竹はパイプを軸に自由に回転できる状態を保つ（竹を直接固定しない）。",
                "ブロックの高さの目安は竹の直径と同程度。",
                "ビスは下穴を空けてから打つと木材が割れにくい。",
                "ビスはコーススレッド65mm以上を使用し、各ブロック2本以上打つ。",
            ],
        },
        {
            "title": "⑤ パイプを通した竹をフレームに並べ、パイプ両端をビスで固定する",
            "icon": "🎋",
            "svg": _svg_step5_roller,
            "desc": (
                "節を除去した竹にパイプを通し、フレームの垂木ブロックの間に並べます。"
                "**パイプは竹の両端より長く、両端が垂木ブロックに届く長さ**にします。"
                "垂木ブロックでパイプ両端を挟んでビスで締め付けることでパイプが固定され、"
                "竹はパイプを軸に自由に回転（ローラー動作）します。"
                "竹同士の隙間は指（約12mm）が入らない程度に詰めてください。"
            ),
            "points": [
                "パイプは竹の両端から80mm（8cm）以上飛び出した長さにする（垂木ブロック8cm×8cm で固定するため）。",
                "📐 **参考：垂木ブロック 8cm×8cm** → パイプが竹より片側8cm、両端で合計16cm長い計算になります。",
                "竹はパイプに対してフリーに回転できる状態であることを確認する。",
                "竹を並べたら垂木ブロックのビスを本締めしてパイプを固定する。",
            ],
        },
        {
            "title": "⑥ 手すり用の竹を斜面に沿って取り付ける",
            "icon": "🖐️",
            "svg": _svg_step6_handrail_v2,
            "desc": (
                "ローラー面が完成したら、手すり竹を取り付けます。\n\n"
                "**固定手順：**\n"
                "① まず竹に**ドリルで貫通穴をあける**（ビットは使用するビスより細いサイズ）。\n"
                "② 貫通穴を通して**竹とフレーム設置面に長ビスを打ち込み**固定する。\n\n"
                "手すりの高さはローラー面から15〜20cm上が目安です。\n\n"
                "**垂木ブロックのカバー板：**\n"
                "垂木ブロックは突起しており触れると危険なため、フレームの**両サイドに1枚ずつ、計2枚の板でカバー**を取り付けます。"
                "板の両端は地面に垂直にまっすぐカットします。"
                "板の高さは垂木ブロックの高さに合わせてください。\n\n"
                "**縦桟（支柱）の製作：**\n"
                "階段用に左右2本の縦桟（板材）を用意します。"
                "上端はローラー設置面（斜面フレーム）の**傾斜角に合わせて斜めにカット**します。"
                "斜めにカットすることで縦桟がローラー面にぴったり密着し、"
                "階段全体がぐらつかずに安定します。\n\n"
                "**足ぶれ防止板：**\n"
                "最下段（地面付近）の縦桟の間に**横方向に板を1枚渡し**、"
                "足がずれないようにします。高さが80cm以上の場合は中間にも1枚追加してください。"
            ),
            "points": [
                "手すり竹はドリルで貫通穴をあけてから長ビス（コーススレッド90mm以上）で固定する。",
                "竹の太さに応じて2箇所以上でビス固定し、手すりがぐらつかないようにする。",
                "手すりは斜面に沿って平行に設置し、両端をしっかり固定する。",
                "手すりを強く押しても動かないことを確認してから使用を開始する。",
                "【垂木カバー板】フレーム左右両サイドに板を1枚ずつ（計2枚）取り付ける。板の両端は垂直にカット。",
                "【垂木カバー板】板の高さ＝垂木ブロックの高さ。ローラー面と同じ高さになるよう揃える。",
                "【縦桟】上端はローラー面（斜面）の傾斜角と同じ角度で斜めにカットする（ノコギリ使用、保護具着用）。",
                "【縦桟】斜めカットの角度は滑り台の傾斜角（arctan(高さ÷水平長さ)）と同じ。",
                "【足ぶれ防止板】最下部（地面付近）の縦桟の間に横方向の板を渡す。高さが80cm以上の場合は中間にも1枚追加する。",
                "⚠️【重要・ケガ防止】竹の繊維はノコギリやナイフで切断した断面・切り口にも繊維のトゲ（ささくれ）が残る。竹は繊維が長く非常に強靭なため、刺さると深く入り抜けにくく、放置すると化膿・感染症の原因になる重大事故につながる。",
                "⚠️【重要・ケガ防止】手すり竹の全ての切り口・断面はサンドペーパー（#120→#240）で十分に磨き、素手で触れて引っかかりがなくなるまで仕上げること。特に子どもの手が触れる部分（端部・節まわり）は入念に処理する。",
                "⚠️【重要・ケガ防止】使用前・定期点検時に手すり竹の表面全体を素手で撫でて確認し、ささくれ・割れ・剥離が生じていれば即座に使用を禁止して研磨または交換する。",
            ],
        },
        {
            "title": "⑦ 支柱を組み、地面に固定する",
            "icon": "📐",
            "svg": _svg_step7_slope,
            "desc": (
                "支柱の固定は転倒防止のための大切な工程です。\n\n"
                "**【推奨】単管パイプ打ち込み式**\n\n"
                "単管パイプ（φ48.6mm）をパイプハンマーで地面に**50cm以上**打ち込み、"
                "直交クランプで木製支柱と連結します。"
                "材料はホームセンターで揃い、撤去時はパイプを引き抜くだけです。\n\n"
                "固定後は支柱を大人が全力で揺らして動かないことを確認してください。"
                "傾斜角度は**35°以下**を守りましょう。\n\n"
                "**運用ルール（固定方法に関わらず必ず守ること）**\n\n"
                "設置・使用中は**大人が必ず傍に付き添います。**"
                "強風・雨天時は使用を中止し、毎回使用前に固定状態を目視で確認してください。"
            ),
            "points": [
                "単管パイプはφ48.6mm・長さ1m以上を使用し、地面に50cm以上打ち込む。",
                "直交クランプで支柱と単管を2箇所以上連結し、がたつきがないことを確認する。",
                "設置後に支柱を大人が全力で押して動かないことを必ず確認してから使用を開始する。",
                "使用中は大人が必ず傍に付き添う。子どもだけでの使用は禁止。",
                "強風・雨天時は使用を中止する。",
                "毎回使用前に支柱の固定状態・緩み・傾きを目視と手で確認する。",
            ],
        },
        {
            "title": "⑧ 階段を取り付け、全体を組み上げて使用前安全点検を行う",
            "icon": "🎉",
            "svg": _svg_step8_ladder,
            "svg2": _svg_step9_stairs,
            "svg3": _svg_step8_complete,
            "desc": (
                "製作した階段を滑り台に取り付けます。\n\n"
                "**踏み板（ステップ）の製作：**\n"
                "踏み板は**1枚板**を使用します。"
                "使用者の体重がかかっても足がぶれないよう、板はしっかりした厚さのもの（目安：厚さ18mm以上）を選んでください。"
                "踏み板間隔は均等に（目安：20〜25cm）し、子どもが登りやすい段数を確保します。\n\n"
                "**すべての踏み板と縦桟はコーススレッドビスでしっかり固定します。**\n\n"
                "完成したらブラウン系の**着色防腐剤を全面に塗布**して耐久性を上げましょう。\n\n"
                "**上部ストッパー板の取り付け：**\n"
                "階段の上端（ローラー接触面側）に、踏み板とは**反対側（ローラー側）に向けて厚みのある板**を取り付けます。"
                "この板がローラー部分に引っかかり、階段全体が前にずれるのを防ぐ**ストッパー**になります。\n\n"
                "**全体の組み立て完了後：**\n"
                "フレームを支柱に固定してすべてのパーツを組み上げたら完成です。"
                "**使用前に必ずチェックリストで安全点検を行い、"
                "大人が試乗して安全を確認してから使用を開始してください。**"
                "月1回以上の定期点検を習慣にしましょう。"
            ),
            "points": [
                "踏み板は厚さ18mm以上の板材を使用し、足をのせたときにたわまないことを確認する。",
                "踏み板間隔は均等に20〜25cm程度とし、子どもが無理なく1段ずつ登れる高さにする。",
                "踏み板はビス打ち前に下穴をあける（木材の割れ防止）。コーススレッド65mm以上を各端2本ずつ固定。",
                "縦桟の下端が地面に直接触れる場合は腐れ防止のため防腐剤を塗布するか、接地部を金属プレートで保護する。",
                "【上部ストッパー板】階段上端のローラー接触面側に厚みのある板（目安：厚さ18mm以上）をビスで固定する。",
                "【上部ストッパー板】板がローラー竹に引っかかってずれないことを手で押して確認する。",
                "ブラウン系の着色防腐剤を全面に塗布すると耐久性が大幅に向上する（塗布後は完全乾燥を待つ）。",
                "【使用前点検】ガタつき・竹の割れ・ビス緩み・突起・バリがないか確認。",
                "【使用前点検】支柱・手すり・階段を強く押してぐらつきがないか確認。",
                "【使用前点検】階段のストッパー板がローラーに確実に引っかかっているか確認。",
                "【使用前点検】必ず大人が先に試乗して安全を確かめる。",
                "【定期点検（月1回）】竹の劣化・虫食い・腐れ・接合部の緩みを確認。",
                "異常を発見したら即座に使用を禁止し、修理または撤去する。",
                "雨ざらしは竹の劣化を早めるため、使用後はシートで覆うか屋根下に保管する。",
            ],
        },
    ]

    import base64

    def _render_svg(svg_str: str):
        b64 = base64.b64encode(svg_str.encode("utf-8")).decode("utf-8")
        st.markdown(
            f'<img src="data:image/svg+xml;base64,{b64}" '
            f'style="width:100%;max-width:400px;height:auto;display:block;" />',
            unsafe_allow_html=True,
        )

    for step in steps:
        with st.expander(f"{step['icon']} {step['title']}", expanded=False):
            has_svg2 = "svg2" in step
            if has_svg2:
                # ⑧専用：左にイラスト3枚縦並び、右に説明文
                col_imgs, col_text = st.columns([1, 1])
                with col_imgs:
                    _render_svg(step["svg"]())    # 上：梯子正面図
                    _render_svg(step["svg2"]())   # 中：斜め階段図
                    _render_svg(step["svg3"]())   # 下：完成図
                with col_text:
                    st.markdown(step["desc"])
                    st.markdown("**📌 ポイント：**")
                    for pt in step["points"]:
                        st.markdown(f"- {pt}")
            else:
                col_img, col_text = st.columns([1, 1])
                with col_img:
                    _render_svg(step["svg"]())
                with col_text:
                    st.markdown(step["desc"])
                    st.markdown("**📌 ポイント：**")
                    for pt in step["points"]:
                        st.markdown(f"- {pt}")

    # ── 乾燥竹の判定基準 ──
    st.divider()
    with st.expander("🌿 乾燥竹の判定基準（使用可否チェック）", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("""
**✅ 使用してよい竹の目安**
- 切り出しから **2〜3ヶ月以上** 経過している
- 表面の色が **薄い黄緑〜黄褐色** に変化している
- 竹を叩くと **高く乾いた音** がする
- 断面に **光沢があり**、水分が出てこない
- 節が密で（節間30cm以下）、**肉厚** がある
- 割れ・虫食い・カビが **ない**
""")
        with col_b:
            st.markdown("""
**❌ 使用してはいけない竹**
- 切り出してから **1ヶ月未満** の生竹（強度30%低下）
- 表面に **縦割れ** が入っている
- 叩くと **鈍く低い音** がする（水分残存）
- 虫食い穴・カビ・腐れがある
- 肉薄で節の間隔が広すぎる（40cm以上）
- 強く押すと **たわみ** を感じる

⚠️ 生竹は乾燥竹に比べ強度が **約30%低下** します。
""")
        st.info(
            "💡 **簡易判定法：** 竹の切り口を指で触って湿っている場合は生竹です。"
            "乾燥が十分な竹は切り口が乾いており、触っても水分を感じません。"
        )

    st.info(
        "💡 **材料の確認（竹の直径によって変わります）**\n\n"
        f"現在の設定：竹の直径 **{diameter_cm:.1f}cm**。"
        "「図面を作る」ボタンで横材の本数・長さ・手すり竹の長さを確認してください。\n\n"
        "パイプは **材料リストの「滑り面横材」の長さ × 同本数** 用意してください。"
    )


def main():
    st.set_page_config(page_title="竹あそび", layout="wide")
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
    # モバイルでヘッダーバーにタイトルが隠れないようスペーサーを挿入
    st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)
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
                   f"　E = {spec['E']/1e9:.0f} GPa　基準許容応力 = {spec['sigma']/1e6:.0f} MPa")

        # 竹の状態選択（経年劣化・損傷による強度係数）
        bamboo_condition = st.selectbox(
            "竹の状態",
            list(BAMBOO_CONDITION_FACTORS.keys()),
            help="目視で確認した竹の状態を選択してください。割れ・虫食いがある場合は使用禁止です。"
        )
        cond_factor = BAMBOO_CONDITION_FACTORS[bamboo_condition]
        st.caption(f"ℹ️ {BAMBOO_CONDITION_NOTES[bamboo_condition]}")

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

        # ── 竹の状態チェック：使用禁止ならここで停止 ──
        if cond_factor is None:
            st.error("🚫 **使用禁止：竹に致命的な欠陥があります**")
            st.error(
                "選択された状態「割れあり / 虫食いあり」の竹は計算の余地なく使用禁止です。"
                "直ちに新しい竹に交換してください。計算を続行できません。"
            )
            st.stop()

        # ── 実効許容応力の計算（安全率 × 状態係数）──
        # 実効許容応力 = 基準許容応力 ÷ 安全率 × 状態係数
        # ÷ではなく × (1/安全率) とし、状態係数で追加割引する。
        effective_sigma = spec["sigma"] / STRUCTURAL_SAFETY_FACTOR * cond_factor
        effective_sigma_mpa = effective_sigma / 1e6

        st.info(
            f"🔢 **実効許容応力の計算**  "
            f"基準 {spec['sigma']/1e6:.0f} MPa"
            f" ÷ 安全率 {STRUCTURAL_SAFETY_FACTOR:.1f}"
            f" × 状態係数 {cond_factor:.1f}"
            f" = **{effective_sigma_mpa:.2f} MPa**"
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
                allowable_stress=effective_sigma,
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

        # ── 製作手順ガイド（滑り台・ブランコ・ジャングルジム）──
        if tool_name == "滑り台":
            st.divider()
            render_slide_construction_guide(diameter)
        elif tool_name == "ブランコ":
            st.divider()
            render_swing_construction_guide(diameter)
        elif tool_name == "ジャングルジム":
            st.divider()
            render_junglegym_construction_guide(diameter)

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
