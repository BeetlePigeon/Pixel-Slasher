from support import Vec2i, build_circle_direction_lut, build_aim_direction_luts


# Tile-space direction vectors normalized for equal movement speed.
DIRECTION_VECTORS = {
    # visual cardinal directions
    Vec2i(1, -1): Vec2i(2896, -2896),   # visual right
    Vec2i(-1, 1): Vec2i(-2896, 2896),   # visual left
    Vec2i(-1, -1): Vec2i(-2896, -2896), # visual up
    Vec2i(1, 1): Vec2i(2896, 2896),     # visual down
    # visual diagonal directions / tile-axis directions
    Vec2i(1, 0): Vec2i(4096, 0),        # visual down-right
    Vec2i(-1, 0): Vec2i(-4096, 0),      # visual up-left
    Vec2i(0, 1): Vec2i(0, 4096),        # visual down-left
    Vec2i(0, -1): Vec2i(0, -4096),      # visual up-right
}

SPIRAL_DIRS = [
    Vec2i(1, 0),
    Vec2i(1, -1),
    Vec2i(0, -1),
    Vec2i(-1, -1),
    Vec2i(-1, 0),
    Vec2i(-1, 1),
    Vec2i(0, 1),
    Vec2i(1, 1),
]


CARDINAL_DIRS = (
    Vec2i(1, 0),
    Vec2i(-1, 0),
    Vec2i(0, 1),
    Vec2i(0, -1),
)

DIAGONAL_DIRS = (
    Vec2i(1, 1),
    Vec2i(1, -1),
    Vec2i(-1, 1),
    Vec2i(-1, -1),
)

CHEBY_DIRS = (
    Vec2i(1, 0),
    Vec2i(-1, 0),
    Vec2i(0, 1),
    Vec2i(0, -1),
    Vec2i(1, 1),
    Vec2i(1, -1),
    Vec2i(-1, 1),
    Vec2i(-1, -1),
)

CIRCLE_DIRECTION_LUT = build_circle_direction_lut()
AIM_DIRECTION_LUTS = build_aim_direction_luts()