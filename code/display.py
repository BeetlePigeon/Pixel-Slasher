import os
import pygame
try:
    import numpy as np
except ImportError:
    np = None
from constants import INTERNAL_HEIGHT, INTERNAL_WIDTH, INTERNAL_RES, WINDOW_TITLEBAR_SAFE_Y


class Display:
    def __init__(self, game):
        self.game = game
        os.environ['SDL_VIDEO_CENTERED'] = '1'
        pygame.init()
        self.monitor_info = pygame.display.Info()
        self.internal_width = INTERNAL_WIDTH
        self.internal_height = INTERNAL_HEIGHT
        self.internal_size = INTERNAL_RES
        self.render_surface = pygame.Surface(self.internal_size)
        self.display_modes = [
            "windowed",
            "borderless",
            "fullscreen",
        ]
        self.brightness = 0
        self.contrast = 0
        self.gamma = 100
        self.visual_calibration_lut = None
        self.warned_missing_numpy_for_calibration = False
        self.scale = 1
        self.window_flags = 0
        self.window_size = self.internal_size
        self.window = None
        self.toggle = True

        self.fps_caps = [30, 180, 0]  # 0 = uncapped.
        self.windowed_scales = self.build_windowed_scales()

        self.debug_font = pygame.font.Font(None, 18)

        self.load_display_settings_from_game_settings()
        self.load_visual_calibration_from_game_settings()
        self.rebuild_visual_calibration_lut()
        self.apply_display_settings()
        self.save_display_settings_to_game_settings()


    def get_centered_window_position(self, window_size):
        desktop_width, desktop_height = self.get_desktop_size()
        window_width, window_height = window_size

        x = max(
            0,
            (desktop_width - window_width) // 2,
        )

        y = max(
            WINDOW_TITLEBAR_SAFE_Y,
            (desktop_height - window_height) // 2,
        )

        return x, y

    def set_next_window_position(self, position):
        x, y = position

        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{x},{y}"


    def get_desktop_size(self):
        desktop_sizes = pygame.display.get_desktop_sizes()

        if desktop_sizes:
            return desktop_sizes[0]

        return (
            self.monitor_info.current_w,
            self.monitor_info.current_h,
        )


    def get_max_integer_scale_for_size(self, size):
        width, height = size

        scale_x = width // self.internal_width
        scale_y = height // self.internal_height

        return max(
            1,
            min(scale_x, scale_y),
        )


    def get_windowed_size_for_scale(self, scale):
        return (
            self.internal_width * scale,
            self.internal_height * scale,
        )


    def apply_display_settings(self):
        if self.display_mode == "windowed":
            self.scale = self.windowed_scale
            self.window_size = self.get_windowed_size_for_scale(
                self.windowed_scale,
            )
            self.window_flags = 0

            self.set_next_window_position(
                self.get_centered_window_position(
                    self.window_size,
                )
            )

        elif self.display_mode == "borderless":
            desktop_size = self.get_desktop_size()

            self.scale = self.get_max_integer_scale_for_size(
                desktop_size,
            )
            self.window_size = desktop_size
            self.window_flags = pygame.NOFRAME

            self.set_next_window_position((0, 0))

        elif self.display_mode == "fullscreen":
            desktop_size = self.get_desktop_size()

            self.scale = self.get_max_integer_scale_for_size(
                desktop_size,
            )
            self.window_size = desktop_size
            self.window_flags = pygame.FULLSCREEN

            self.set_next_window_position((0, 0))

        else:
            raise ValueError(
                f"Unknown display mode: {self.display_mode}"
            )

        self.window = pygame.display.set_mode(
            self.window_size,
            flags=self.window_flags,
            vsync=1 if self.vsync_enabled else 0,
        )

        # Pygame may return the actual display/window size.
        self.window_size = self.window.get_size()

    def set_windowed_scale(self, scale: int):
        self.windowed_scale = self.clamp_windowed_scale(scale)
        self.windowed_scale_index = self.windowed_scales.index(
            self.windowed_scale
        )

        if self.display_mode == "windowed":
            self.apply_display_settings()

        self.save_display_settings_to_game_settings()

    def cycle_windowed_scale(self):
        self.windowed_scale_index = (
                                            self.windowed_scale_index + 1
                                    ) % len(self.windowed_scales)

        new_scale = self.windowed_scales[
            self.windowed_scale_index
        ]

        self.set_windowed_scale(new_scale)

    def toggle_vsync(self):
        self.vsync_enabled = not self.vsync_enabled
        self.apply_display_settings()
        self.save_display_settings_to_game_settings()

    def cycle_display_mode(self):
        self.display_mode_index = (
                                          self.display_mode_index + 1
                                  ) % len(self.display_modes)

        self.display_mode = self.display_modes[
            self.display_mode_index
        ]

        self.apply_display_settings()
        self.save_display_settings_to_game_settings()


    def cycle_fps_cap(self):
        self.fps_cap_index = (
                                     self.fps_cap_index + 1
                             ) % len(self.fps_caps)

        self.fps_cap = self.fps_caps[self.fps_cap_index]
        self.save_display_settings_to_game_settings()

    def build_windowed_scales(self):
        desktop_width, desktop_height = self.get_desktop_size()

        max_scale = self.get_max_integer_scale_for_size(
            (
                desktop_width,
                desktop_height,
            )
        )

        # Allow at least the old useful 1x/2x behavior on small laptop displays.
        # The clamp still prevents obviously unusable huge scales.
        max_scale = max(
            2,
            max_scale,
        )

        return list(
            range(
                1,
                max_scale + 1,
            )
        )


    def load_display_settings_from_game_settings(self):
        display_settings = self.game.settings["display"]

        display_mode = display_settings.get("display_mode", "windowed")
        if display_mode not in self.display_modes:
            display_mode = "windowed"

        self.display_mode = display_mode
        self.display_mode_index = self.display_modes.index(display_mode)

        requested_scale = display_settings.get("windowed_scale", 1)
        self.windowed_scale = self.clamp_windowed_scale(requested_scale)
        self.windowed_scale_index = self.windowed_scales.index(
            self.windowed_scale
        )

        self.vsync_enabled = bool(
            display_settings.get("vsync_enabled", True)
        )

        requested_fps_cap = display_settings.get("fps_cap", self.fps_caps[0])
        if requested_fps_cap not in self.fps_caps:
            requested_fps_cap = self.fps_caps[0]

        self.fps_cap = requested_fps_cap
        self.fps_cap_index = self.fps_caps.index(self.fps_cap)


    def clamp_windowed_scale(self, scale):
        try:
            scale = int(scale)
        except (TypeError, ValueError):
            scale = 1

        if not self.windowed_scales:
            return 1

        return max(
            self.windowed_scales[0],
            min(
                self.windowed_scales[-1],
                scale,
            ),
        )


    def load_visual_calibration_from_game_settings(self):
        display_settings = self.game.settings["display"]

        self.brightness = display_settings.get("brightness", 0)
        self.contrast = display_settings.get("contrast", 0)
        self.gamma = display_settings.get("gamma", 100)

        self.brightness = self.clamp_int(
            self.brightness,
            -100,
            100,
            0,
        )

        self.contrast = self.clamp_int(
            self.contrast,
            -100,
            100,
            0,
        )

        self.gamma = self.clamp_int(
            self.gamma,
            50,
            200,
            100,
        )


    def clamp_int(self, value, minimum, maximum, fallback):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = fallback

        return max(
            minimum,
            min(maximum, value),
        )


    def rebuild_visual_calibration_lut(self):
        if np is None:
            self.visual_calibration_lut = None
            return

        values = np.arange(
            256,
            dtype=np.float32,
        )

        contrast_value = self.contrast * 255.0 / 100.0

        contrast_factor = (
                                  259.0 * (contrast_value + 255.0)
                          ) / (
                                  255.0 * (259.0 - contrast_value)
                          )

        values = contrast_factor * (values - 128.0) + 128.0

        brightness_offset = self.brightness * 255.0 / 100.0
        values = values + brightness_offset

        values = np.clip(
            values,
            0,
            255,
        )

        gamma_value = self.gamma / 100.0
        gamma_exponent = 1.0 / gamma_value

        values = 255.0 * np.power(
            values / 255.0,
            gamma_exponent,
        )

        values = np.clip(
            values,
            0,
            255,
        )

        self.visual_calibration_lut = values.astype(np.uint8)


    def visual_calibration_is_neutral(self):
        return (
                self.brightness == 0
                and self.contrast == 0
                and self.gamma == 100
        )

    def apply_visual_calibration(self, surface):
        if self.visual_calibration_is_neutral():
            return surface

        if np is None:
            if not self.warned_missing_numpy_for_calibration:
                print(
                    "[display] visual calibration requires numpy; "
                    "brightness/contrast/gamma disabled"
                )
                self.warned_missing_numpy_for_calibration = True

            return surface

        if self.visual_calibration_lut is None:
            self.rebuild_visual_calibration_lut()

        calibrated_surface = surface.copy()

        pixels = pygame.surfarray.pixels3d(calibrated_surface)
        source_pixels = pixels.copy()

        pixels[:, :, :] = self.visual_calibration_lut[source_pixels]

        del pixels

        return calibrated_surface


    def set_brightness(self, brightness):
        self.brightness = self.clamp_int(
            brightness,
            -100,
            100,
            0,
        )

        self.rebuild_visual_calibration_lut()
        self.save_display_settings_to_game_settings()


    def adjust_brightness(self, amount):
        self.set_brightness(
            self.brightness + amount,
        )


    def set_contrast(self, contrast):
        self.contrast = self.clamp_int(
            contrast,
            -100,
            100,
            0,
        )

        self.rebuild_visual_calibration_lut()
        self.save_display_settings_to_game_settings()


    def adjust_contrast(self, amount):
        self.set_contrast(
            self.contrast + amount,
        )


    def set_gamma(self, gamma):
        self.gamma = self.clamp_int(
            gamma,
            50,
            200,
            100,
        )

        self.rebuild_visual_calibration_lut()
        self.save_display_settings_to_game_settings()


    def adjust_gamma(self, amount):
        self.set_gamma(
            self.gamma + amount,
        )


    def reset_visual_calibration(self):
        self.brightness = 0
        self.contrast = 0
        self.gamma = 100

        self.rebuild_visual_calibration_lut()
        self.save_display_settings_to_game_settings()


    def save_display_settings_to_game_settings(self):
        display_settings = self.game.settings.setdefault(
            "display",
            {},
        )

        display_settings.update({
            "display_mode": self.display_mode,
            "windowed_scale": self.windowed_scale,
            "vsync_enabled": self.vsync_enabled,
            "fps_cap": self.fps_cap,
            "brightness": self.brightness,
            "contrast": self.contrast,
            "gamma": self.gamma,
        })

        self.game.save_settings()


    def set_camera_zoom_index(self, zoom_index):
        camera = self.game.world.world_camera.camera
        zoom_levels = camera["zoom_levels"]

        zoom_index = max(
            0,
            min(len(zoom_levels) - 1, zoom_index),
        )

        camera["zoom_index"] = zoom_index

        zoom_num, zoom_den = zoom_levels[zoom_index]

        camera["zoom_num"] = zoom_num
        camera["zoom_den"] = zoom_den
        camera["zoom_target_num"] = zoom_num
        camera["zoom_target_den"] = zoom_den
        camera["zoom_target_fp"] = (
                zoom_num * 1024 // max(1, zoom_den)
        )

        if not camera.get("zoom_smooth", True):
            camera["zoom_current_fp"] = camera["zoom_target_fp"]


    def zoom_camera_in(self):
        camera = self.game.world.world_camera.camera

        self.set_camera_zoom_index(
            camera["zoom_index"] + 1,
        )


    def zoom_camera_out(self):
        camera = self.game.world.world_camera.camera

        self.set_camera_zoom_index(
            camera["zoom_index"] - 1,
        )


    def set_camera_zoom_smooth(self, enabled):
        camera = self.game.world.world_camera.camera
        camera["zoom_smooth"] = enabled

        if not enabled:
            camera["zoom_current_fp"] = camera["zoom_target_fp"]