from dataclasses import dataclass
import pygame


@dataclass
class InputState:
    keys: any
    keys_pressed: set
    keys_released: set

    mouse_buttons: tuple
    mouse_pressed: set
    mouse_released: set

    mouse_pos: tuple
    quit: bool


class Input:
    def __init__(self):
        self.prev_keys = pygame.key.get_pressed()
        self.prev_mouse = pygame.mouse.get_pressed()

    def collect(self):
        quit_game = False

        keys_pressed = set()
        keys_released = set()

        mouse_pressed = set()
        mouse_released = set()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                quit_game = True

            if event.type == pygame.KEYDOWN:
                keys_pressed.add(event.key)
                if event.key == pygame.K_ESCAPE:
                    quit_game = True

            if event.type == pygame.KEYUP:
                keys_released.add(event.key)

            if event.type == pygame.MOUSEBUTTONDOWN:
                mouse_pressed.add(event.button)

            if event.type == pygame.MOUSEBUTTONUP:
                mouse_released.add(event.button)

        keys = pygame.key.get_pressed()
        mouse_buttons = pygame.mouse.get_pressed()

        return InputState(
            keys=keys,
            keys_pressed=keys_pressed,
            keys_released=keys_released,

            mouse_buttons=mouse_buttons,
            mouse_pressed=mouse_pressed,
            mouse_released=mouse_released,

            mouse_pos=pygame.mouse.get_pos(),
            quit=quit_game
        )