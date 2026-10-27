"""グローバルCSS"""


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
