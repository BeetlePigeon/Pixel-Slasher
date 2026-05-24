from support import Vec2i


class Camera:
    def __init__(self, world):
        self.world = world

        self.camera_base_offset = (0, 0)
        self.camera_offset = (0, 0)
        self.camera_projection = None
        self.camera_shake_offset = Vec2i(0, 0)
        self.camera = {
            "mode": "follow",
            "target": None,
            "fixed_cpos": None,
            "screen_offset": Vec2i(0, 0),
            "current_cpos": None,
            "prev_cpos": None,
            "transition_mode": "snap",
            "transition_ticks": 0,
            "transition_duration": 0,
            "default_transition_duration": 24,
            "transition_start_cpos": None,
            "snap_next_update": False,
            "shake_ticks": 0,
            "shake_duration": 0,
            "shake_strength": 0,
            "shake_max_strength": 20,
            "zoom_levels": [
                (1, 2),
                (3, 4),
                (1, 1),
                (5, 4),
                (3, 2),
                (2, 1),
            ],
            "zoom_index": 2,

            # Target zoom selected by gameplay/settings/UI.
            "zoom_num": 1,
            "zoom_den": 1,
            "zoom_target_num": 1,
            "zoom_target_den": 1,

            # Current visual zoom, fixed-point.
            # 1024 = 1.0x
            "zoom_current_fp": 1024,
            "zoom_target_fp": 1024,

            # Official camera behavior.
            "zoom_smooth": False,
            "zoom_step_fp": 64,
        }