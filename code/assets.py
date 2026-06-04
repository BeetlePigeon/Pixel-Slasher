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
        # Entities
        self.images["player"] = self.load_image("characters", "player.png")
        self.images["test_projectile"] = self.load_image("projectiles", "test_projectile.png")
        self.images["magnet"] = self.load_image("projectiles", "magnet.png")
        self.images["meteor"] = self.load_image("projectiles", "meteor.png")
        self.images["enemy_normal"] = self.load_image("enemies", "enemy_normal.png")
        self.images["enemy_angry"] = self.load_image("enemies", "enemy_angry.png")

        # Tiles
        self.images["block"] = self.load_image("tiles", "block.png")
        self.images["water"] = self.load_image("tiles", "water.png")

        # UI
        self.images["button"] = self.load_image("ui", "button.png")

        # Debug
        self.images["highlighted_tile"] = self.load_image("debug", "highlighted_tile.png")