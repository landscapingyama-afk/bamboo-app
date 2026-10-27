"""ブランコプラグイン・製作手順ガイド"""

from __future__ import annotations

import math
from typing import List, Tuple

import streamlit as st

from core.constants import (
    BF, BD, BM, GC, ROPE, BAMBOO_ALLOWABLE_STRESS, BAMBOO_E,
    WARNING_STRESS_RATIO, DYNAMIC_LOAD_FACTOR, ROPE_DANGER_LOAD_KG,
    WEIGHT_ROPE_WARNING, SEAT_HEIGHT_RATIO, MAX_SEAT_HEIGHT_M,
    MAX_FRAME_HEIGHT_M,
)
from core.models import Dimensions, Material, CheckMessage
from core.structural import check_bending, check_deflection
from core.svg import make_svg, ell, bamboo_slat, bamboo_top, dim_h, dim_v, load_marker
from plugins.base import ToolPlugin, register_plugin


# ─────────────────────────── ブランコ ─────────────────────────────
@register_plugin
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

    def render_guide(self, diameter_cm: float) -> None:
        render_swing_construction_guide(diameter_cm)


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
