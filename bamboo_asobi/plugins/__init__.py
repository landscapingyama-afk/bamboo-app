"""遊具プラグイン

各モジュールを import した時点で @register_plugin により REGISTRY へ自動登録される。
新しい遊具を追加する場合は、このパッケージにモジュールを追加し、下の import 行に加える。
"""

from plugins.base import REGISTRY, ToolPlugin, register_plugin
from plugins import slide, swing, junglegym  # noqa: F401  （登録のための import）

__all__ = ["REGISTRY", "ToolPlugin", "register_plugin"]
