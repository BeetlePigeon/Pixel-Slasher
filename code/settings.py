import math
from support import Vec2i

INTERNAL_WIDTH = 640
INTERNAL_HEIGHT = 360
INTERNAL_RES = (INTERNAL_WIDTH, INTERNAL_HEIGHT)

FPS = 60
SIM_FPS = 60
SIM_DT = 1.0 / SIM_FPS
MAX_FRAME_DT = 0.25

ANIMATION_RATE = 60
TILE_UNITS = 4096
MAX_COLLISION_STEP = TILE_UNITS // 4
TILE_DIMENSION = 32     # Width/Height in pixels
MOVE_BUFFER_TICKS = 8

ZOOM_FP_SCALE = 1024 # Camera

WINDOW_TITLEBAR_SAFE_Y = 48

DIRECTIONAL_MOVEMENT_MODE = "continuous"
#DIRECTIONAL_MOVEMENT_MODE = "node_follow"
# Alternative for rollback:
#DIRECTIONAL_MOVEMENT_MODE = "grid_move"

REQUIRED_SKILL_FIELDS = {
    "id",
    "name",

    "cooldown_ticks",
    "trigger_mode",

    "blocked_by_motion_tags",
    "blocked_by_action_tags",
    "cancels_action_tags",

    "required_components",
    "required_params",
    "allowed_param_values",

    "aim",
    "cast",
    "channel",

    "params",

    "handler",
}

ALLOWED_TRIGGER_MODES = {
    "press",
    "held_repeat",
}


ALLOWED_AIM_TIMINGS = {
    "cast_start",
    "live",
}

MOVEMENT_CANCELING_ACTION_TAGS = {
    "movement_locked",
    "stun",
    "root",
}

PATH_POLICIES = {
    "traditional_click_move": {
        "max_expansions": 1000,
        "max_path_length": 30,
        "smooth_max_path_length": 20,
        "target_snap_radius": 2,
        # While LMB is held, allow the active path to refresh periodically.
        # 15 ticks = 0.25 seconds at 60 sim FPS.
        "refresh_ticks": 10,
        # If a path query fails, don't retry the same start/target immediately
        # while the mouse is still held.
        "failed_retry_ticks": 30,

        "direct_fallback_on_fail": True,
        "direct_fallback_max_tiles": 30,
        "direct_fallback_min_tiles": 1,
    },
}

# game configuration settings
data_file = {
    # Audio Options
    'master_volume': 100,
    'music_volume': 100,
    'sound_effect_volume': 100,

    # Video Options
    'gamma': 50,
    'screen_resolution': [1920, 1080],
    'fullscreen': False,
}


# SPATIAL RESOLUTION CONSTANTS
CIRCLE_LUT_SIZE = 64
DIR_SCALE = 4096
ANGLE_SCALE = 256
AIM_LUT_SIZES = (8, 16, 32, 64, 128, 256)

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

ALL_DIRS_8WAY = CARDINAL_DIRS + DIAGONAL_DIRS

def build_aim_direction_luts():
    return {
        size: build_direction_lut(size)
        for size in AIM_LUT_SIZES
    }


def build_direction_lut(size: int):
    directions = []

    for i in range(size):
        angle = (2 * math.pi * i) / size

        directions.append(
            Vec2i(
                round(math.cos(angle) * DIR_SCALE),
                round(math.sin(angle) * DIR_SCALE),
            )
        )

    return tuple(directions)


def build_circle_direction_lut():
    directions = []

    for i in range(CIRCLE_LUT_SIZE):
        angle = (2 * math.pi * i) / CIRCLE_LUT_SIZE

        directions.append(
            Vec2i(
                round(math.cos(angle) * DIR_SCALE),
                round(-math.sin(angle) * DIR_SCALE),
            )
        )

    return tuple(directions)


CIRCLE_DIRECTION_LUT = build_circle_direction_lut()
AIM_DIRECTION_LUTS = build_aim_direction_luts()