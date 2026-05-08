import sys
import os
import math
import pygame
from settings import *
import time
from gamestate import StateGameplay
from inputhandler import Input
from world import World
from assets import Assets
from entity import EntityManager


class Game:
    def __init__(self):
        self.done = False
        self.clock = pygame.time.Clock()
        self.previous_time = time.time()
        self.toggle = True
        self.fps = 0
        self.sim_accumulator = 0.0

        # Window and Display
        os.environ['SDL_VIDEO_CENTERED'] = '1'
        pygame.init()
        self.debug_font = pygame.font.Font(None, 18)
        self.monitor_info = pygame.display.Info()
        self.internal_width = INTERNAL_WIDTH
        self.internal_height = INTERNAL_HEIGHT
        self.internal_size = INTERNAL_RES
        self.render_surface = pygame.Surface(self.internal_size)
        self.scale = 1
        self.window_size = self.internal_size
        self.window = pygame.display.set_mode(self.internal_size, vsync=1)
        pygame.display.set_caption('Pixel Slasher')

        # Load Assets
        self.sounds = self.load_sounds()
        self.assets = Assets()
        self.assets.load()

        # Input Handler
        self.input_handler = Input()

        # Entities
        self.entities = EntityManager()

        # World
        self.world = World(self, self.entities)

        # States
        self.states = {
            'STARTUP': StateGameplay(self),
        }
        self.state_name = 'STARTUP'  # Beginning state when user opens the application.
        self.state = self.states[self.state_name]
        self.state.startup({})

    def resize_display(self, resolution):
        self.scale = resolution.scale
        size = (self.scale * self.internal_width, self.scale * self.internal_height)
        self.window = pygame.display.set_mode(size, vsync=1)
        self.window_size = size

    def resize_display2(self, resolution):
        if resolution.flags == pygame.FULLSCREEN:
            info = pygame.display.Info()
            size = (info.current_w, info.current_h)
            self.window = pygame.display.set_mode(size, flags=pygame.FULLSCREEN, vsync=1)
            self.window_size = size
            self.scale = max(1, min(math.floor(size[0] / self.internal_size[0]),
                             math.floor(size[1] / self.internal_size[1])))
        else:
            self.scale = max(1, min(math.floor(resolution.width / self.internal_size[0]),
                             math.floor(resolution.height / self.internal_size[1])))
            size = (resolution.width, resolution.height)
            self.window = pygame.display.set_mode(size, vsync=1)
            self.window_size = size

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
            f"Camera: {self.world.camera['transition_mode']}"
        ]

        y = 4

        for line in lines:
            text_surface = self.debug_font.render(line, False, "white")
            self.render_surface.blit(text_surface, (4, y))
            y += 14

    def draw(self):
        self.render_surface.fill('black')
        self.state.draw(self.render_surface)
        self.draw_debug_overlay()
        scaled_width = self.internal_size[0] * self.scale
        scaled_height = self.internal_size[1] * self.scale
        x_offset = (self.window_size[0] - scaled_width) // 2
        y_offset = (self.window_size[1] - scaled_height) // 2
        scaled_surface = pygame.transform.scale_by(self.render_surface, self.scale)
        self.window.blit(scaled_surface, (x_offset, y_offset))
        pygame.display.flip()

    def run(self):
        while not self.done:
            frame_dt = self.clock.tick(FPS) / 1000.0
            self.fps = self.clock.get_fps()

            if frame_dt > MAX_FRAME_DT:
                frame_dt = MAX_FRAME_DT

            input_state = self.input_handler.collect()
            if input_state.quit:
                self.done = True

            self.sim_accumulator += frame_dt

            while self.sim_accumulator >= SIM_DT:
                self.update_state(SIM_DT, input_state)
                self.sim_accumulator -= SIM_DT

            self.draw()


if __name__ == '__main__':
    game = Game()
    game.run()
    pygame.quit()
    sys.exit()
