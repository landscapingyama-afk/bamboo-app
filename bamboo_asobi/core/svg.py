"""SVGサニタイゼーション・SVGプリミティブ描画ヘルパー"""

from __future__ import annotations

import html
import math
import re

from core.constants import (
    BF, BD, BL, BM, WF, WD, DC,
    SLAT_HIGHLIGHT_POS, SLAT_END_RY_RATIO, SLAT_END_OPACITY,
    TOP_INNER_RATIO, TOP_HIGHLIGHT_OFFSET, TOP_HIGHLIGHT_SIZE,
)


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
