# Internal render resolution.
# The game draws to this fixed-size surface first, then the display code scales
# that surface to the actual window/fullscreen size.
INTERNAL_WIDTH = 640
INTERNAL_HEIGHT = 360
INTERNAL_RES = (INTERNAL_WIDTH, INTERNAL_HEIGHT)


# Target frame rate for display/debug timing.
# The actual simulation step uses SIM_FPS / SIM_DT below.
FPS = 60


# Fixed simulation rate.
# Game logic advances in fixed-size ticks so movement, cooldowns, actions,
# status durations, and effect timings are stable regardless of render FPS.
SIM_FPS = 60
SIM_DT = 1.0 / SIM_FPS


# Maximum real frame time that can be fed into the fixed-step accumulator.
# This prevents a large pause/stutter from trying to simulate too many ticks
# at once when the game resumes.
MAX_FRAME_DT = 0.25


# Animation sampling rate.
# Used as the default timing base for animation updates.
ANIMATION_RATE = 60


# Canonical world units per tile.
# Tile coordinates are coarse grid positions.
# cpos coordinates are fine-grained positions inside that grid.
# Example:
#     tile (0, 0) spans cpos x/y from 0 to TILE_UNITS - 1.
TILE_UNITS = 4096


# Maximum canonical-position step used by collision/movement tracing.
# Smaller steps reduce the chance of skipping through thin tile boundaries.
MAX_COLLISION_STEP = TILE_UNITS // 4


# Pixel width/height of one isometric tile image before camera zoom/display scale.
# This is render-space size, not world-space size.
TILE_DIMENSION = 32


# Number of ticks a directional movement input can be buffered.
# Mainly useful for grid/node-style movement. Continuous movement generally
# clears this instead of using a buffered direction after key release.
MOVE_BUFFER_TICKS = 8


# Fixed-point scale used for camera zoom.
# 1024 means 1.0x zoom.
# 512 means 0.5x zoom.
# 2048 means 2.0x zoom.
ZOOM_FP_SCALE = 1024


# Safe y-position for recreating a windowed display after fullscreen/borderless.
# Prevents the OS title bar from being placed above the monitor edge.
WINDOW_TITLEBAR_SAFE_Y = 48


# Number of directions stored in the circular direction lookup table.
# Used by spiral/projectile math and other systems that need evenly spaced
# directions around a circle.
CIRCLE_LUT_SIZE = 64


# Fixed-point length of normalized direction vectors.
# A vector with length DIR_SCALE represents one full-strength direction.
# Movement code scales these vectors by speed/distance.
DIR_SCALE = 4096


# Fixed-point angle step size used by spiral-style lookup indexing.
# In spiral_pos(), angle_fp // ANGLE_SCALE advances through CIRCLE_DIRECTION_LUT.
ANGLE_SCALE = 256


# Supported direction lookup table sizes for aim quantization.
# Smaller values produce chunkier aim directions.
# Larger values produce finer directional precision.
AIM_LUT_SIZES = (8, 16, 32, 64, 128, 256)


# Default direction resolution for aim offsets.
# Used when a skill wants to offset aim by lookup-table steps but does not
# specify its own resolution.
DEFAULT_AIM_OFFSET_RESOLUTION = 32