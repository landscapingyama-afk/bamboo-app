"""ジャングルジムプラグイン・製作手順ガイド"""

from __future__ import annotations

import math
from typing import List, Tuple

import streamlit as st

from core.constants import (
    BD, BL, BM, GC, BAMBOO_ALLOWABLE_STRESS, BAMBOO_E, WARNING_STRESS_RATIO,
)
from core.models import Dimensions, Material, CheckMessage
from core.structural import check_bending
from core.svg import make_svg, ell, bamboo_slat, bamboo_top, dim_h, dim_v, load_marker
from plugins.base import ToolPlugin, register_plugin


# ──────────────────────── ジャングルジム ──────────────────────────
@register_plugin
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

    def render_guide(self, diameter_cm: float) -> None:
        render_junglegym_construction_guide(diameter_cm)


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
