"""安全チェック結果の表示ヘルパー"""

from __future__ import annotations

import html
from typing import List

import streamlit as st

from core.models import CheckMessage
from plugins.base import ToolPlugin


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

    # ── QA共通注意事項（折りたたみ・危険時は自動展開）──────────────
    with st.expander("📋 QA共通注意事項（必ずお読みください）", expanded=danger):
        for note in ToolPlugin._QA_NOTES:
            st.info(note)
