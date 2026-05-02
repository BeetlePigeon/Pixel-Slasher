from pathlib import Path
import pygame


class Assets:
    def __init__(self):
        self.images = {}

        base_path = Path(__file__).resolve().parent
        self.graphics_path = base_path.parent / "graphics"

    def load_image(self, *path_parts):
        path = self.graphics_path.joinpath(*path_parts)
        return pygame.image.load(path).convert_alpha()

    def load(self):
        self.images["player"] = self.load_image("characters", "player.png")
        self.images["block"] = self.load_image("tiles", "block.png")
        self.images["water"] = self.load_image("tiles", "water.png")
        self.images["button"] = self.load_image("ui", "button.png")