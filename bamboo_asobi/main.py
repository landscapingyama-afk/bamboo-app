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
import io
import logging
import os
import sys

# `streamlit run main.py` をどのディレクトリから実行しても
# core / plugins / ui パッケージを import できるようにする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st  # noqa: E402

from core.constants import (  # noqa: E402
    BAMBOO_SPECS, BAMBOO_CONDITION_FACTORS, BAMBOO_CONDITION_NOTES,
    STRUCTURAL_SAFETY_FACTOR,
)
from core.models import Dimensions  # noqa: E402
from plugins import REGISTRY  # noqa: E402  （import 時に全プラグインが登録される）
from ui.safety_messages import render_safety_messages  # noqa: E402
from ui.styles import GLOBAL_CSS  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


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

    st.warning(
        "⚠️ **【全遊具共通・重要な安全注意事項】**\n\n"
        "**■ 竹の切り口・ささくれによるケガ防止**\n"
        "竹の切断面・断面には繊維のトゲ（ささくれ）が残ります。"
        "竹の繊維は非常に強靭で、刺さると深く入り抜けにくく、放置すると化膿・感染症の原因になる重大事故につながります。"
        "竹を使用したすべての遊具において、**全ての切り口・断面・節まわりは必ずサンドペーパー（#120→#240）で十分に磨き**、"
        "素手で触れて引っかかりがなくなるまで仕上げてください。特に子どもの手が届く部分は入念に処理してください。\n\n"
        "**■ 使用前・定期点検でのささくれ確認**\n"
        "使用前および月1回の定期点検時に、すべての竹の表面を素手で撫でて確認してください。"
        "ささくれ・割れ・剥離が生じていれば即座に使用を禁止し、研磨または竹を交換してください。\n\n"
        "**■ 大人の付き添いと定期点検**\n"
        "すべての遊具は使用中に大人が必ず付き添い、子どもだけでの使用を禁止してください。"
        "月1回以上の定期点検（竹の劣化・虫食い・腐れ・接合部の緩み・ガタつき）を習慣にし、"
        "異常を発見したら即座に使用を禁止して修理または撤去してください。"
    )

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

        # ── 製作手順ガイド（各プラグインの render_guide() に委譲）──
        # render_guide() のデフォルト実装は pass なので、
        # ガイドのない遊具では何も表示されない。
        st.divider()
        plugin.render_guide(diameter)

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
