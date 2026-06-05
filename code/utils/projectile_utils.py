from constants import TILE_UNITS


def build_projectile_influence_receiver(info):
    influence_info = info["influence_receiver"]

    return {
        "accepts": set(influence_info["accepts"]),
        "scales": {
            influence_type: tuple(scale)
            for influence_type, scale in influence_info["scales"].items()
        },
        "max_delta": (
            TILE_UNITS
            // influence_info["max_delta_tile_units_divisor"]
        ),
    }