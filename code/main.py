import sys
import os
import pygame
import time
from settings import *
from gamestate import StateGameplay
from inputhandler import Input
from inputbuffer import InputBuffer
from assets import Assets
from entity import EntityManager
from skills import SKILL_DEFS, validate_skill_defs
from world import World
from dataclasses import replace

# Debug controls:
# WASD / L Click: Move
# R Click: Spiral Projectile
# SPACE: Test Projectile
# 1: Teleport
# 2: Wide Projectiles
# 3: Magnet
# 4: Dash
# 5: *FREE*
# 6: Debug Slash
# 7: Debug Channel Projectile
# 8: Debug Channel Projectile
# 9: Meteor
# 0: *FREE*
# LSHIFT: Toggle Camera Mode
# B: Debug Stun Player
# N: Debug Freeze Player
# H: Debug Make Enemy Damage Player
# V: Debug Screen Shake
# F5: Resize
# F6: Toggle VSync
# F7: Cycle FPS Cap
# F8: Toggle Control Scheme
# F9: Toggle Modern Movement Aim Source
# F10: Zoom Camera Out
# F11: Zoom Camera In


class Game:
    def __init__(self):
        self.done = False
        self.clock = pygame.time.Clock()
        self.previous_time = time.time()
        self.fps = 0
        self.sim_accumulator = 0.0
        self.debug_frame_ms_history = []
        self.debug_sim_ticks_history = []
        self.debug_frame_history_max = 180

        # Window and Display
        os.environ['SDL_VIDEO_CENTERED'] = '1'
        pygame.init()
        self.monitor_info = pygame.display.Info()
        self.internal_width = INTERNAL_WIDTH
        self.internal_height = INTERNAL_HEIGHT
        self.internal_size = INTERNAL_RES
        self.render_surface = pygame.Surface(self.internal_size)
        self.scale = 1
        self.toggle = True
        self.vsync_enabled = True
        self.fps_caps = [30, 180, 0]  # 0 = uncapped. Later add values that match common monitor refresh rates. Along with tooltip explaining in Video Settings Menu.
        self.fps_cap_index = 0
        self.fps_cap = self.fps_caps[self.fps_cap_index]
        self.debug_font = pygame.font.Font(None, 18)
        # Debug screen resize and mouse canonical position
        self.debug_scales = [1, 2, 3]
        self.debug_scale_index = 0
        # End debug
        self.window_size = self.internal_size
        self.window = pygame.display.set_mode(self.internal_size, vsync=1)
        pygame.display.set_caption('Pixel Slasher')

        # Load Assets
        self.sounds = self.load_sounds()
        self.assets = Assets()
        self.assets.load()

        # Input
        self.input_handler = Input()
        self.input_buffer = InputBuffer()
        self.mouse_pos_internal = (0, 0)

        # Entities
        self.entities = EntityManager()

        # Validate Game Data
        validate_skill_defs(SKILL_DEFS)

        # World
        self.world = World(self, self.entities)

        # Game State Machine
        self.states = {
            'STARTUP': StateGameplay(self),
        }
        self.state_name = 'STARTUP'  # Beginning state when user opens the application.
        self.state = self.states[self.state_name]
        self.state.startup({})


    def draw_debug_overlay(self):
        lines = [
            f"FPS: {self.fps:.1f}",
            f"Entities next_id: {self.entities.next_id}",
            f"Transforms: {len(self.world.transform)}",
            f"MotionState: {len(self.world.motion_state)}",
            f"Sprites: {len(self.world.sprite)}",
            f"Projectiles: {len(self.world.projectile)}",
            f"Emitters: {len(self.world.influence_emitter)}",
            f"Receivers: {len(self.world.influence_receiver)}",
            f"Lifetime: {len(self.world.lifetime)}",
            f"Scale: {self.scale}x",
            f"VSync: {'on' if self.vsync_enabled else 'off'}",
            f"FPS cap: {'uncapped' if self.fps_cap == 0 else self.fps_cap}",
            f"Camera: {self.world.camera['transition_mode']}",
            f"Controls: {self.world.control_scheme}",
            f"Move skill aim: {self.world.gameplay_settings['modern_movement_skill_aim_source']}",
            f"Animations: {len(self.world.animation)}",
            f"Action State: {self.world.action_state}",
            f"Ticks: {self.world.tick}",
            f"Statuses: {self.world.status_effects.get(self.world.player, {})}",
            (
                f"Zoom: "
                f"{self.world.camera['zoom_current_fp'] / 1024:.2f}x "
                f"-> {self.world.camera['zoom_target_num']}/"
                f"{self.world.camera['zoom_target_den']} "
                f"({'smooth' if self.world.camera['zoom_smooth'] else 'snap'})"
            ),
        ]

        y = 4

        for line in lines:
            text_surface = self.debug_font.render(line, False, "white")
            self.render_surface.blit(text_surface, (4, y))
            y += 14


    def record_debug_frame_sample(self, raw_frame_dt, sim_ticks_this_frame):
        frame_ms = raw_frame_dt * 1000.0

        self.debug_frame_ms_history.append(frame_ms)
        self.debug_sim_ticks_history.append(sim_ticks_this_frame)

        if len(self.debug_frame_ms_history) > self.debug_frame_history_max:
            self.debug_frame_ms_history.pop(0)

        if len(self.debug_sim_ticks_history) > self.debug_frame_history_max:
            self.debug_sim_ticks_history.pop(0)


    def draw_debug_frame_graph(self):
        history = self.debug_frame_ms_history

        if not history:
            return

        graph_x = 4
        graph_y = self.internal_height - 64
        graph_w = min(180, self.internal_width - 8)
        graph_h = 44

        pygame.draw.rect(
            self.render_surface,
            "black",
            (graph_x - 1, graph_y - 1, graph_w + 2, graph_h + 16),
        )

        pygame.draw.rect(
            self.render_surface,
            "white",
            (graph_x, graph_y, graph_w, graph_h),
            1,
        )

        # Reference lines:
        # 16.67 ms = 60 FPS
        # 33.33 ms = 30 FPS
        max_ms = 50.0

        def ms_to_y(ms):
            clamped = min(max_ms, max(0.0, ms))
            return graph_y + graph_h - int((clamped / max_ms) * graph_h)

        y_60 = ms_to_y(1000.0 / 60.0)
        y_30 = ms_to_y(1000.0 / 30.0)

        pygame.draw.line(
            self.render_surface,
            "gray",
            (graph_x, y_60),
            (graph_x + graph_w, y_60),
            1,
        )

        pygame.draw.line(
            self.render_surface,
            "gray",
            (graph_x, y_30),
            (graph_x + graph_w, y_30),
            1,
        )

        start_index = max(0, len(history) - graph_w)

        for i, frame_ms in enumerate(history[start_index:]):
            x = graph_x + i
            y = ms_to_y(frame_ms)

            color = "green"

            if frame_ms > 33.33:
                color = "red"
            elif frame_ms > 16.67:
                color = "yellow"

            pygame.draw.line(
                self.render_surface,
                color,
                (x, graph_y + graph_h - 1),
                (x, y),
                1,
            )

        latest_ms = history[-1]
        worst_ms = max(history)
        latest_ticks = (
            self.debug_sim_ticks_history[-1]
            if self.debug_sim_ticks_history
            else 0
        )

        label = (
            f"Frame ms: {latest_ms:.1f} | "
            f"Peak: {worst_ms:.1f} | "
            f"Sim ticks: {latest_ticks}"
        )

        text_surface = self.debug_font.render(
            label,
            False,
            "white",
        )

        self.render_surface.blit(
            text_surface,
            (graph_x, graph_y + graph_h + 3),
        )


    def set_debug_scale(self, scale: int):
        self.scale = scale

        self.window_size = (
            self.internal_width * self.scale,
            self.internal_height * self.scale,
        )

        self.window = pygame.display.set_mode(
            self.window_size,
            vsync=1 if self.vsync_enabled else 0,
        )


    def cycle_debug_scale(self):
        self.debug_scale_index = (
                                         self.debug_scale_index + 1
                                 ) % len(self.debug_scales)

        new_scale = self.debug_scales[self.debug_scale_index]
        self.set_debug_scale(new_scale)

    def set_camera_zoom_index(self, zoom_index):
        camera = self.world.camera
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
        camera = self.world.camera

        self.set_camera_zoom_index(
            camera["zoom_index"] + 1,
        )

    def zoom_camera_out(self):
        camera = self.world.camera

        self.set_camera_zoom_index(
            camera["zoom_index"] - 1,
        )

    def set_camera_zoom_smooth(self, enabled):
        camera = self.world.camera
        camera["zoom_smooth"] = enabled

        if not enabled:
            camera["zoom_current_fp"] = camera["zoom_target_fp"]


    def toggle_vsync(self):
        self.vsync_enabled = not self.vsync_enabled

        self.window = pygame.display.set_mode(
            self.window_size,
            vsync=1 if self.vsync_enabled else 0,
        )


    def cycle_fps_cap(self):
        self.fps_cap_index = (
                                     self.fps_cap_index + 1
                             ) % len(self.fps_caps)

        self.fps_cap = self.fps_caps[self.fps_cap_index]


    def load_sounds(self):
        return  {'SOUND_EFFECTS':
                    {
                        'MENU_STARTUP_SOUND': pygame.mixer.Sound('../audio/effects/ui/startup.wav'),
                        'MENU_HAPTIC_SOUND_HOVER': pygame.mixer.Sound('../audio/effects/ui/menu_sound_hover.wav'),
                        'MENU_HAPTIC_SOUND_CLICK': pygame.mixer.Sound('../audio/effects/ui/menu_sound_click.wav'),
                        'MENU_HAPTIC_SOUND_SLIDER_HOVER': pygame.mixer.Sound('../audio/effects/ui/menu_sound_slider_hover.wav'),
                        'MENU_HAPTIC_SOUND_SLIDER_MOVE': pygame.mixer.Sound('../audio/effects/ui/menu_sound_slider_move.wav'),
                        'MENU_HAPTIC_SOUND_SLIDER_RELEASE': pygame.mixer.Sound(
                            '../audio/effects/ui/menu_sound_slider_release.wav'),
                        'MENU_HAPTIC_SOUND_SLIDER_LIMIT_REACHED': pygame.mixer.Sound(
                            '../audio/effects/ui/menu_sound_slider_limit_reached.wav'),
                    },
                'MUSIC':
                    {
                        'BGM_0': pygame.mixer.Sound('../audio/music/bgm0.wav')
                    }
            }


    def to_game_input_state(self, input_state):
        return replace(
            input_state,
            mouse_pos=self.window_to_internal_mouse_pos(input_state.mouse_pos),
        )


    def window_to_internal_mouse_pos(self, window_pos):
        window_x, window_y = window_pos

        scaled_width = self.internal_size[0] * self.scale
        scaled_height = self.internal_size[1] * self.scale

        x_offset = (self.window_size[0] - scaled_width) // 2
        y_offset = (self.window_size[1] - scaled_height) // 2

        internal_x = (window_x - x_offset) // self.scale
        internal_y = (window_y - y_offset) // self.scale

        # Clamp to internal surface bounds.
        internal_x = max(0, min(self.internal_width - 1, internal_x))
        internal_y = max(0, min(self.internal_height - 1, internal_y))

        return internal_x, internal_y


    def flip_state(self):
        next_state = self.state.next_state
        self.state.done = False
        self.state_name = next_state
        persistent = self.state.persist
        self.state = self.states[self.state_name]
        self.state.startup(persistent)


    def update_state(self, dt, input_state):
        if self.state.quit:
            self.done = True
        elif self.state.done:
            self.flip_state()
        self.state.update(dt, input_state)


    def draw(self, render_alpha):
        self.render_surface.fill('black')
        self.state.draw(self.render_surface, render_alpha)
        self.draw_debug_overlay()
        self.draw_debug_frame_graph()
        scaled_width = self.internal_size[0] * self.scale
        scaled_height = self.internal_size[1] * self.scale
        x_offset = (self.window_size[0] - scaled_width) // 2
        y_offset = (self.window_size[1] - scaled_height) // 2
        scaled_surface = pygame.transform.scale_by(self.render_surface, self.scale)
        self.window.blit(scaled_surface, (x_offset, y_offset))
        pygame.display.flip()


    def run(self):
        while not self.done:
            raw_frame_dt = self.clock.tick(self.fps_cap) / 1000.0
            self.fps = self.clock.get_fps()

            frame_dt = raw_frame_dt

            if frame_dt > MAX_FRAME_DT:
                frame_dt = MAX_FRAME_DT

            input_state = self.input_handler.collect()
            input_state = self.to_game_input_state(input_state)
            self.mouse_pos_internal = input_state.mouse_pos

            if input_state.quit:
                self.done = True

            # Store edge-triggered input until the next simulation tick.
            self.input_buffer.add_frame_input(input_state)

            # Debug/window hotkeys can still act immediately on raw input.
            if pygame.K_F5 in input_state.keys_pressed:
                self.cycle_debug_scale()
            if pygame.K_F6 in input_state.keys_pressed:
                self.toggle_vsync()
            if pygame.K_F7 in input_state.keys_pressed:
                self.cycle_fps_cap()
            if pygame.K_F10 in input_state.keys_pressed:
                self.zoom_camera_out()
            if pygame.K_F11 in input_state.keys_pressed:
                self.zoom_camera_in()
            # End debug

            self.sim_accumulator += frame_dt

            used_edges_this_frame = False
            sim_ticks_this_frame = 0

            while self.sim_accumulator >= SIM_DT:
                sim_input_state = self.input_buffer.build_sim_input_state(
                    input_state,
                    include_edges=not used_edges_this_frame,
                )

                self.update_state(SIM_DT, sim_input_state)
                sim_ticks_this_frame += 1

                if not used_edges_this_frame:
                    self.input_buffer.clear_edges()

                used_edges_this_frame = True
                self.sim_accumulator -= SIM_DT

            self.record_debug_frame_sample(
                raw_frame_dt,
                sim_ticks_this_frame,
            )

            render_alpha = self.sim_accumulator / SIM_DT
            render_alpha = max(0.0, min(1.0, render_alpha))

            self.draw(render_alpha)


if __name__ == '__main__':
    game = Game()
    game.run()
    pygame.quit()
    sys.exit()
