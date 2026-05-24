from constants import TILE_DIMENSION, TILE_UNITS
from camera import Camera
from tile_vec_utils import tile_center
from support import Vec2i, Transform


class World:
    def __init__(self, game, entities):
        self.game = game
        self.entities = entities
        self.tick = 0
        self.failed_path_queries = {}
        self.control_scheme = "modern"      # "modern" -> WoW Style | "traditional" -> D2 Style
        self.gameplay_settings = {
            "modern_movement_skill_aim_source": "facing",       # "facing" -> Uses player facing direction | "mouse" -> Uses mouse direction
            "movement_skill_aim_resolution": 16,
            "projectile_aim_resolution": 128,
        }

        ## Camera
        self.world_camera = Camera(self)

        ## Components
        self.snapshot = {
            "cpos": {},
            "tile": {},
        }
        self.transform = {}
        self.motion_state = {}
        self.action_state = {}
        self.status_effects = {}
        self.facing = {}
        self.events = []
        self.move_intent = {}
        self.buffered_move_intent = {}
        self.move_target = {}
        self.aim_state = {}
        self.intent = {}
        self.input_controlled = {}
        self.skills = {}
        self.active_skill = {}
        self.skill_cooldown = {}
        self.placement_blocker = set()
        self.resolved_skill_intents = []
        self.sprite = {}
        self.animation = {}
        self.locomotion = {}
        self.projectile = {}
        self.lifetime = {}
        self.health = {}
        self.effect_delivery = {}
        self.team = {}
        self.hittable = {}
        self.damage_requests = []
        self.movement_collision = {}
        self.influence_emitter = {}
        self.influence_receiver = {}
        self.influence_delta = {}

        self.debug_tile_highlights = []

        ## Tiles
        self.tile_size = TILE_DIMENSION
        self.tile_images = {
            0: self.game.assets.images["block"],    # Blocked / No floor
            1: self.game.assets.images["water"]     # Walkable
        }

        self.tilemap = [
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
             1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        ]
        self.static_collision_tiles = self.build_static_collision_tiles()

        ## Environment
#        self.create_wind_field_emitter()

        ## Actors
        self.player = self.spawn_player()
        self.spawn_training_dummy(Vec2i(7, 5))
        self.spawn_training_dummy(Vec2i(7, 6))

        ## Focus Camera
        self.world_camera.camera["target"] = self.player
        self.world_camera.camera["current_cpos"] = self.transform[self.player].cpos
        self.world_camera.camera["prev_cpos"] = self.transform[self.player].cpos

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
        self.motion_state.pop(eid, None)
        self.action_state.pop(eid, None)
        self.status_effects.pop(eid, None)
        self.facing.pop(eid, None)

        self.move_intent.pop(eid, None)
        self.buffered_move_intent.pop(eid, None)
        self.move_target.pop(eid, None)
        self.aim_state.pop(eid, None)
        self.projectile.pop(eid, None)
        self.sprite.pop(eid, None)
        self.animation.pop(eid, None)
        self.locomotion.pop(eid, None)
        self.lifetime.pop(eid, None)
        self.health.pop(eid, None)
        self.effect_delivery.pop(eid, None)
        self.team.pop(eid, None)
        self.hittable.pop(eid, None)
        self.movement_collision.pop(eid, None)
        self.influence_emitter.pop(eid, None)
        self.influence_receiver.pop(eid, None)
        self.influence_delta.pop(eid, None)
        self.placement_blocker.discard(eid)
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
        player_tile = Vec2i(5, 5)
        player_cpos = tile_center(player_tile)

        player_transform = Transform(
            tile=player_tile,
            cpos=tile_center(player_tile),
            prev_cpos=player_cpos,
            position_mode="grid",
        )
        self.transform[eid] = player_transform
        self.facing[eid] = Vec2i(1, -1)
        self.movement_collision[eid] = {
            "static_tiles": "slide",

            # Default/fallback ratio.
            "slide_min_tangent_ratio": (1, 2),

            # Direct grid movement: WASD / buffered WASD.
            "grid_slide_min_tangent_ratio": (1, 2),

            # Traditional click-to-move target movement.
            "mouse_slide_min_tangent_ratio": (5, 2),
            "corner_cutting": "allow_if_one_side_open",
        }
        self.motion_state[eid] = {
            "controller": None,
            "last_delta": Vec2i(0, 0),
            "influence_mode": "normal",
        }
        self.influence_receiver[eid] = {
            "accepts": {"wind", "magnet",},
            "scales": {
                "wind": (1, 1),
                "magnet": (1, 1),
            },
            "max_delta": TILE_UNITS // 16,
        }
        self.locomotion[eid] = {
            "step_duration": 10,
            "can_move_8way": True,
        }
        self.placement_blocker.add(eid)
        self.skills[(eid, 0)] = "test_projectile"
        self.skills[(eid, 1)] = "teleport"
        self.skills[(eid, 2)] = "burst_projectile"
        self.skills[(eid, 3)] = "magnet_orb"
        self.skills[(eid, 4)] = "dash"
        self.skills[(eid, 5)] = "spiral_projectile"
        self.skills[(eid, 6)] = "debug_slash"
#        self.skills[(eid, 7)] = "debug_channel_projectile"
        self.skills[(eid, 8)] = "guard_counter"
        self.skills[(eid, 9)] = "debug_channel_projectile"
        self.skills[(eid, 10)] = "meteor"
#        self.skills[(eid, 11)] = "squidward"

        player_image = self.game.assets.images["player"]
        self.sprite[eid] = {
            "image": player_image,
            "anchor": "bottom_center",
            "z": 0
        }
        self.animation[eid] = {
            "set": "player",
            "state": "idle",
            "direction": "right",
            "frame": 0,
            "timer": 0,
        }
        self.team[eid] = "player"
        self.health[eid] = {
            "current": 100,
            "max": 100,
        }
        self.hittable[eid] = {
            "enabled": True,
        }
        return eid


    def spawn_training_dummy(self, tile):
        eid = self.entities.create()

        cpos = tile_center(tile)

        self.transform[eid] = Transform(
            tile=tile,
            cpos=cpos,
            prev_cpos=cpos,
            position_mode="grid",
        )
        self.movement_collision[eid] = {
            "static_tiles": "slide",
            "slide_min_tangent_ratio": (1, 2),
            "corner_cutting": "allow_if_one_side_open",
        }
        self.motion_state[eid] = {
            "controller": None,
            "last_delta": Vec2i(0, 0),
            "influence_mode": "normal",
        }
        self.influence_receiver[eid] = {
            "accepts": {"wind", "magnet"},
            "scales": {
                "wind": (1, 1),
                "magnet": (1, 1),
            },
            "max_delta": TILE_UNITS // 16,
        }

        self.team[eid] = "enemy"
        self.health[eid] = {
            "current": 10,
            "max": 10,
        }
        self.hittable[eid] = {
            "enabled": True,
        }

        # Reuse player art for now. Replace later with enemy/dummy art.
        dummy_image = self.game.assets.images["player"]

        self.sprite[eid] = {
            "image": dummy_image,
            "anchor": "bottom_center",
            "z": 0,
        }

        self.animation[eid] = {
            "set": "player",
            "state": "idle",
            "direction": "right",
            "frame": 0,
            "timer": 0,
        }

        self.placement_blocker.add(eid)

        return eid