"""滑り台プラグイン・製作手順ガイド"""

from __future__ import annotations

import math
from typing import List, Tuple

import streamlit as st

from core.constants import (
    BF, BD, BL, BM, WF, WD, GC, BAMBOO_ALLOWABLE_STRESS, BAMBOO_E,
    WEIGHT_MEDIUM, MAX_HEIGHT_ADULT, WARNING_STRESS_RATIO, MAX_SLOPE_DEG,
)
from core.models import Dimensions, Material, CheckMessage
from core.structural import check_bending, check_deflection
from core.svg import make_svg, ell, bamboo_slat, bamboo_top, wood_rect, dim_h, dim_v, load_marker
from plugins.base import ToolPlugin, register_plugin


# ─────────────────────────── 滑り台 ───────────────────────────────
@register_plugin
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

    def render_guide(self, diameter_cm: float) -> None:
        render_slide_construction_guide(diameter_cm)


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
                "垂木ブロックはパイプの左右から挟んでフレームにビス固定する。",
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
                "ローラー面が完成したら、垂木ブロックの上に手すり竹を取り付けます。\n\n"
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
