# Debug controls:
# ESC: Quit
# `: Toggle Debug Mode
# WASD / L Click: Move
# R Click: Channel Projectile
# SPACE: Test Projectile
# LSHIFT: Toggle Camera Mode
# I: Print Profiler Rows
# P: Pause
# O: Single Tick Step
# B: Stun Player
# N: Freeze Player
# H: Make Enemy Damage Player
# V: Screen Shake
# [: Brightness Down
# ]: Brightness Up
# ;: Contrast Down
# ': Contrast Up
# ,: Gamma Down
# .: Gamma Up
# /: Reset Display Calibration
# 1: Teleport
# 2: Wide Projectiles
# 3: Magnet
# 4: Dash
# 5: Spiral Projectile
# 6: Debug Slash
# 7: *FREE*
# 8: Guard Counter
# 9: Meteor
# 0: *FREE*
# F1: Spawn Enemy
# F2: Toggle Entity Sizes
# F3: Live Reload Skill Definitions
# F4: Area Toggle
# F5: Cycle Windowed Scale
# F6: Toggle VSync
# F7: Cycle FPS Cap
# F8: Toggle Control Scheme
# F9: Toggle Modern Movement Aim Source
# F10: Zoom Out
# F11: Zoom In
# F12: Cycle Display Mode

import sys
import pygame
import time
from utils.perf_profiler import PerfProfiler
from constants import SIM_DT, MAX_FRAME_DT
from data.tables_player_defs import DEFAULT_PLAYER_STATE
from display import Display
from debug import Debug
from gamestate import StateGameplay
from inputhandler import Input
from inputbuffer import InputBuffer
from assets import Assets
from entity import EntityManager
from skill_handlers import HANDLERS
from utils.skill_utils import validate_skill_defs, validate_player_skill_loadout
from skill_registry import SKILL_DEFS, replace_skill_defs, build_skill_defs
from settings_manager import load_settings, save_settings
from world import World
from dataclasses import replace


class Game:
    def __init__(self):
        # Timing
        self.done = False
        self.clock = pygame.time.Clock()
        self.previous_time = time.time()
        self.fps = 0
        self.sim_accumulator = 0.0

        # Simulation Control Variables (Debug Only)
        self.simulation_paused = False
        self.single_step_requested = False

        # User Settings
        self.settings = load_settings()

        # In-game Performance Profiler
        self.perf_profiler = PerfProfiler(history_frames=240)

        # Window and Display
        self.display = Display(self)
        pygame.display.set_caption('Pixel Slasher')

        # Debug
        self.debug = Debug(self)
        self.debug_mode = True

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
        validate_skill_defs(SKILL_DEFS, handler_ids=HANDLERS)
        validate_player_skill_loadout(DEFAULT_PLAYER_STATE, SKILL_DEFS)

        # World
        self.world = World(self, self.entities)

        # Game State Machine
        self.states = {
            'STARTUP': StateGameplay(self),
        }
        self.state_name = 'STARTUP'  # Beginning state when user opens the application.
        self.state = self.states[self.state_name]
        self.state.startup({})


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


    def save_settings(self):
        save_settings(self.settings)


    def reload_skill_defs(self):
        try:
            new_skill_defs = build_skill_defs()

            validate_skill_defs(
                new_skill_defs,
                handler_ids=HANDLERS,
            )

            validate_player_skill_loadout(
                DEFAULT_PLAYER_STATE,
                new_skill_defs,
            )

        except Exception as error:
            print(f"[skill reload] failed: {error}")
            return False

        replace_skill_defs(new_skill_defs)

        print(
            f"[skill reload] loaded {len(SKILL_DEFS)} skills: "
            f"{sorted(SKILL_DEFS)}"
        )

        return True


    def window_to_internal_mouse_pos(self, window_pos):
        window_x, window_y = window_pos

        scaled_width = self.display.internal_size[0] * self.display.scale
        scaled_height = self.display.internal_size[1] * self.display.scale

        x_offset = (self.display.window_size[0] - scaled_width) // 2
        y_offset = (self.display.window_size[1] - scaled_height) // 2

        internal_x = (window_x - x_offset) // self.display.scale
        internal_y = (window_y - y_offset) // self.display.scale

        # Clamp to internal surface bounds.
        internal_x = max(0, min(self.display.internal_width - 1, internal_x))
        internal_y = max(0, min(self.display.internal_height - 1, internal_y))

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
        self.display.render_surface.fill('black')
        self.state.draw(self.display.render_surface, render_alpha)

        if self.debug_mode:
            self.debug.draw_debug_overlay()
            self.debug.draw_debug_frame_graph()
            self.debug.draw_debug_perf_overlay()
            self.debug.draw_debug_pause_overlay()

        scaled_width = self.display.internal_size[0] * self.display.scale
        scaled_height = self.display.internal_size[1] * self.display.scale
        x_offset = (self.display.window_size[0] - scaled_width) // 2
        y_offset = (self.display.window_size[1] - scaled_height) // 2
        present_surface = self.display.apply_visual_calibration(self.display.render_surface)
#        present_surface = self.display.render_surface
        scaled_surface = pygame.transform.scale_by(present_surface, self.display.scale)
        self.display.window.blit(scaled_surface, (x_offset, y_offset))
        pygame.display.flip()


    def run(self):
        while not self.done:
            raw_frame_dt = self.clock.tick(self.display.fps_cap) / 1000.0
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
            # While simulation is paused, do not accumulate gameplay edges
            # unless the user requested a single-step tick.
            if not self.simulation_paused or self.single_step_requested:
                self.input_buffer.add_frame_input(input_state)

            # Toggle debug mode with '~' key.
            if pygame.K_BACKQUOTE in input_state.keys_pressed:
                self.debug_mode = not self.debug_mode

            # Debug/window hotkeys can still act immediately on raw input when in debug mode.
            if self.debug_mode:
                self.debug.process_top_level_debug_input(input_state)

            self.perf_profiler.enabled = self.debug_mode

            used_edges_this_frame = False
            sim_ticks_this_frame = 0

            should_run_single_step = self.simulation_paused and self.single_step_requested

            if self.simulation_paused:
                self.sim_accumulator = 0.0
            else:
                self.sim_accumulator += frame_dt

            should_run_ticks = not self.simulation_paused or should_run_single_step

            if should_run_ticks:
                if should_run_single_step:
                    ticks_to_run = 1
                else:
                    ticks_to_run = 0
                    while self.sim_accumulator >= SIM_DT:
                        ticks_to_run += 1
                        self.sim_accumulator -= SIM_DT

                for _ in range(ticks_to_run):
                    self.perf_profiler.begin_frame()
                    sim_input_state = self.input_buffer.build_sim_input_state(input_state, include_edges=not used_edges_this_frame)
                    self.update_state(SIM_DT, sim_input_state)
                    self.perf_profiler.end_frame()
                    sim_ticks_this_frame += 1
                    if not used_edges_this_frame:
                        self.input_buffer.clear_edges()
                        used_edges_this_frame = True

            self.single_step_requested = False

            if self.debug_mode:
                self.debug.record_debug_frame_sample(raw_frame_dt, sim_ticks_this_frame)

            render_alpha = self.sim_accumulator / SIM_DT
            render_alpha = max(0.0, min(1.0, render_alpha))

            self.draw(render_alpha)


if __name__ == '__main__':
    game = Game()
    game.run()
    pygame.quit()
    sys.exit()
