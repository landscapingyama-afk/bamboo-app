"""
互換用エントリーポイント
========================
本体は bamboo_asobi/ パッケージへモジュール分割されました。
`streamlit run bamboo_asobi/main.py` での起動を推奨しますが、
既存のデプロイ設定（`streamlit run bamboo_app.py`）も引き続き動作するよう残しています。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "bamboo_asobi"))

from main import main  # noqa: E402

main()
