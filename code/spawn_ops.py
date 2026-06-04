from utils.occupancy_utils import is_tile_static_blocked
from utils.tile_vec_utils import tile_from_cpos


def can_spawn_at(world, cpos, static_tiles="reject"):
    tile = tile_from_cpos(cpos)
    blocked = is_spawn_tile_blocked(world, tile)

    if not blocked:
        return True

    if static_tiles == "allow":
        return True

    if static_tiles == "reject":
        return False

    raise ValueError(f"Unknown spawn collision policy: {static_tiles}")


def is_spawn_tile_blocked(world, tile):
    return is_tile_static_blocked(world, tile)