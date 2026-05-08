# game setup
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