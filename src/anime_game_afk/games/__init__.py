"""游戏适配层

Entry points resolve game-specific behaviour through a registered
:class:`ContentPack` (see :mod:`anime_game_afk.games.content_pack`) rather
than importing game modules directly.
"""

from anime_game_afk.games.content_pack import (
    ContentPack,
    available_packs,
    get_content_pack,
)

__all__ = ["ContentPack", "get_content_pack", "available_packs"]
