from support import (
    Vec2i,
    Transform,
    tile_center,
    tile_from_cpos,
    LinearProjectileController,
)
from settings import TILE_DIMENSION, TILE_UNITS


class World:
    def __init__(self, game, entities):
        self.game = game
        self.entities = entities

        ## Camera
        self.camera_offset = (0, 0)  # Camera offset in tile coords

        ## Components
        self.transform = {}
        self.motion_state = {}
        self.move_intent = {}
        self.locomotion = {}
        self.projectile = {}
        self.intent = {}
        self.skills = {}
        self.input_controlled = {}
        self.active_skill = {}
        self.sprite = {}

        ## Tiles
        self.tile_size = TILE_DIMENSION
        self.tile_images = {
            0: self.game.assets.images["block"],    # Blocked / No floor
            1: self.game.assets.images["water"]     # Walkable
        }
        self.tilemap = [
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        ]
        self.static_collision_tiles = self.build_static_collision_tiles()

        ## Initialize entities
        # Spawn player
        self.player = self.spawn_player()

    def remove_entity(self, eid):
        self.transform.pop(eid, None)
        self.motion_state.pop(eid, None)
        self.move_intent.pop(eid, None)
        self.locomotion.pop(eid, None)
        self.projectile.pop(eid, None)
        self.sprite.pop(eid, None)

    def build_static_collision_tiles(self):
        blocked = set()
        for y, row in enumerate(self.tilemap):
            for x, tile_id in enumerate(row):
                if tile_id == 0:
                    blocked.add((x, y))

        return blocked

    def spawn_player(self):
        eid = self.entities.create()
        player_tile = Vec2i(10, 4)

        player_transform = Transform(
            tile=player_tile,
            cpos=tile_center(player_tile),
        )
        self.transform[eid] = player_transform

        self.motion_state[eid] = {
            "controller": None,
            "last_delta": Vec2i(0, 0),
        }
        self.locomotion[eid] = {
            "step_duration": 30,
            "can_move_8way": True,
        }

        player_image = self.game.assets.images["player"]
        self.sprite[eid] = {
            "image": player_image,
            "offset": (-player_image.get_width() // 2, -player_image.get_height()),
            "z": 0
        }

        return eid

    def spawn_test_projectile(self, cpos, direction):
        eid = self.entities.create()

        self.transform[eid] = Transform(
            tile=tile_from_cpos(cpos),
            cpos=cpos,
        )

        self.motion_state[eid] = {
            "controller": LinearProjectileController(
                direction=direction,
                speed=TILE_UNITS // 8,
            ),
            "last_delta": Vec2i(0, 0),
        }

        self.sprite[eid] = {
            "image": self.game.assets.images["player"],  # temporary placeholder
            "offset": (-4, -4),
            "z": 0,
        }
        self.projectile[eid] = {}

        return eid