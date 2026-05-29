from support import Vec2i


MOVEMENT_FOOTPRINTS = {
    "single_tile": (
        Vec2i(0, 0),
    ),

    #  x
    # xxx
    #  x
    "plus5": (
        Vec2i(0, 0),
        Vec2i(0, -1),
        Vec2i(-1, 0),
        Vec2i(1, 0),
        Vec2i(0, 1),
    ),

    #   xxx
    #   xxx
    #   xxx
    "square3":  (
        Vec2i(0, 0),
        Vec2i(0, -1),
        Vec2i(-1, 0),
        Vec2i(-1, 1),
        Vec2i(-1, -1),
        Vec2i(1, 0),
        Vec2i(0, 1),
        Vec2i(1, 1),
        Vec2i(1, -1),
    ),

    #    x
    #   xxx
    #  xxxxx
    #   xxx
    #    x
    "diamond13": (
        Vec2i(0, -2),
        Vec2i(-1, -1),
        Vec2i(0, -1),
        Vec2i(1, -1),
        Vec2i(-2, 0),
        Vec2i(-1, 0),
        Vec2i(0, 0),
        Vec2i(1, 0),
        Vec2i(2, 0),
        Vec2i(-1, 1),
        Vec2i(0, 1),
        Vec2i(1, 1),
        Vec2i(0, 2),
    ),

    #  xxxxx
    #  xxxxx
    #  xxxxx
    #  xxxxx
    #  xxxxx
    "square5": (
        Vec2i(-2, -2),
        Vec2i(-2, -1),
        Vec2i(-2, 0),
        Vec2i(-2, 1),
        Vec2i(-2, 2),
        Vec2i(-1, -2),
        Vec2i(-1, -1),
        Vec2i(-1, 0),
        Vec2i(-1, 1),
        Vec2i(-1, 2),
        Vec2i(0, -2),
        Vec2i(0, -1),
        Vec2i(0, 0),
        Vec2i(0, 1),
        Vec2i(0, 2),
        Vec2i(1, -2),
        Vec2i(1, -1),
        Vec2i(1, 0),
        Vec2i(1, 1),
        Vec2i(1, 2),
        Vec2i(2, -2),
        Vec2i(2, -1),
        Vec2i(2, 0),
        Vec2i(2, 1),
        Vec2i(2, 2),
    ),
}


def validate_movement_footprint(name, offsets):
    offset_set = set(offsets)

    if Vec2i(0, 0) not in offset_set:
        raise ValueError(
            f"Movement footprint {name!r} must include Vec2i(0, 0)"
        )

    for offset in offsets:
        opposite = Vec2i(-offset.x, -offset.y)

        if opposite not in offset_set:
            raise ValueError(
                f"Movement footprint {name!r} is not centered: "
                f"{offset!r} has no opposite {opposite!r}"
            )


for footprint_name, footprint_offsets in MOVEMENT_FOOTPRINTS.items():
    validate_movement_footprint(
        footprint_name,
        footprint_offsets,
    )


def get_movement_footprint_offsets(footprint_name):
    if footprint_name not in MOVEMENT_FOOTPRINTS:
        raise ValueError(
            f"Unknown movement footprint: {footprint_name!r}"
        )

    return MOVEMENT_FOOTPRINTS[footprint_name]