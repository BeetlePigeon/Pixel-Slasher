from settings import TILE_DIMENSION, TILE_UNITS
from support import (
    Vec2i,
    Transform,
    tile_center,
    tile_from_cpos,
    LinearProjectileController,
    SpiralProjectileController,
    ANGLE_SCALE
)


class World:
    def __init__(self, game, entities):
        self.game = game
        self.entities = entities
        self.tick = 0

        ## Camera
        self.camera_offset = (0, 0)
        self.camera = {
            "mode": "follow",
            "target": None,
            "fixed_cpos": None,
            "screen_offset": Vec2i(0, 0),

            "current_cpos": None,
            "transition_mode": "snap",
            "transition_ticks": 0,
            "transition_duration": 0,
            "default_transition_duration": 24,
            "transition_start_cpos": None,

            "shake_ticks": 0,
            "shake_duration": 0,
            "shake_strength": 0,
        }
        ## Components
        self.transform = {}
        self.motion_state = {}
        self.facing = {}
        self.move_intent = {}
        self.intent = {}
        self.input_controlled = {}
        self.skills = {}
        self.active_skill = {}
        self.skill_cooldown = {}
        self.resolved_skill_intents = []
        self.sprite = {}
        self.locomotion = {}
        self.projectile = {}
        self.lifetime = {}
        self.movement_collision = {}
        self.influence_emitter = {}
        self.influence_receiver = {}
        self.influence_delta = {}

        ## Tiles
        self.tile_size = TILE_DIMENSION
        self.tile_images = {
            0: self.game.assets.images["block"],    # Blocked / No floor
            1: self.game.assets.images["water"]     # Walkable
        }
        self.tilemap = [
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        ]
        self.static_collision_tiles = self.build_static_collision_tiles()
        self.create_wind_field_emitter()

        ## Initialize entities
        # Spawn player
        self.player = self.spawn_player()
        self.camera["target"] = self.player
        self.camera["current_cpos"] = self.transform[self.player].cpos

    def create_wind_field_emitter(self):
        eid = self.entities.create()

        self.influence_emitter[eid] = {
            "type": "wind",
            "mode": "cycle",
            "ticks_per_step": 480,
            "cycle": [
                Vec2i(0, TILE_UNITS // 24),  # visual down-left
#                Vec2i(0, 0),  # calm
#                Vec2i(0, -TILE_UNITS // 24),  # visual up-right
#                Vec2i(0, 0),  # calm
            ],
        }

        return eid

    def remove_entity(self, eid):
        self.transform.pop(eid, None)
        self.facing.pop(eid, None)
        self.motion_state.pop(eid, None)
        self.move_intent.pop(eid, None)
        self.locomotion.pop(eid, None)
        self.projectile.pop(eid, None)
        self.sprite.pop(eid, None)
        self.lifetime.pop(eid, None)
        self.movement_collision.pop(eid, None)
        self.influence_emitter.pop(eid, None)
        self.influence_receiver.pop(eid, None)
        self.influence_delta.pop(eid, None)
        for key in list(self.skill_cooldown):
            if key[0] == eid:
                self.skill_cooldown.pop(key, None)

    def build_static_collision_tiles(self):
        blocked = set()
        for y, row in enumerate(self.tilemap):
            for x, tile_id in enumerate(row):
                if tile_id == 0:
                    blocked.add((x, y))

        return blocked

    def spawn_player(self):
        eid = self.entities.create()
        player_tile = Vec2i(7, 4)

        player_transform = Transform(
            tile=player_tile,
            cpos=tile_center(player_tile),
            position_mode="grid",
        )
        self.transform[eid] = player_transform
        self.facing[eid] = Vec2i(1, -1)
        self.movement_collision[eid] = {
            "static_tiles": "block",
        }
        self.motion_state[eid] = {
            "controller": None,
            "last_delta": Vec2i(0, 0),
            "influence_mode": "normal",
        }
        self.locomotion[eid] = {
            "step_duration": 18,
            "can_move_8way": True,
        }
        self.skills[(eid, "TEST_PROJECTILE")] = {
            "id": "test_projectile",
            "cooldown_ticks": 12,
        }
        self.skills[(eid, 2)] = {
            "id": "spiral_projectile",
            "cooldown_ticks": 30,
        }
        self.skills[(eid, 3)] = {
            "id": "magnet_orb",
            "cooldown_ticks": 60,
        }
        self.skills[(eid, 4)] = {
            "id": "dash",
            "cooldown_ticks": 45,
        }
        player_image = self.game.assets.images["player"]
        self.sprite[eid] = {
            "image": player_image,
            "anchor": "bottom_center",
            "z": 0
        }

        return eid