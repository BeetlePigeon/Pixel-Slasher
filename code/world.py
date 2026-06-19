from copy import deepcopy
from constants import TILE_DIMENSION, TILE_UNITS
from area_runtime import AreaRuntime
from camera import Camera
from data.tables_area_defs import (
    AREA_DEFS,
    STARTING_AREA_ID,
    STARTING_SPAWN_ID,
)
from data.tables_player_defs import DEFAULT_PLAYER_STATE
from utils.tile_vec_utils import tile_center, vec2i_from_pair
from utils.occupancy_utils import mark_dynamic_occupancy_dirty, rebuild_dynamic_occupancy
from support import Vec2i, Transform
from map_loader import load_area_map


class World:
    def __init__(self, game, entities):
        self.game = game
        self.entities = entities
        self.tick = 0
        self.failed_path_queries = {}
        self.path_build_state = {}
        self.hovered_selectable = None

        control_settings = self.game.settings["controls"]
        self.control_scheme = control_settings["control_scheme"]
        self.gameplay_settings = {
            "modern_movement_skill_aim_source": (
                control_settings["modern_movement_skill_aim_source"]
            ),
            "movement_skill_aim_resolution": (
                control_settings["movement_skill_aim_resolution"]
            ),
            "projectile_aim_resolution": (
                control_settings["projectile_aim_resolution"]
            ),
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
        self.pointer_action_state = {}
        self.keyboard_action_state = {}
        self.action_order = {}
        self.next_action_order_id = 1
        self.intent = {}
        self.input_controlled = {}
        self.skills = {}
        self.active_skill = {}
        self.skill_cooldown = {}
        self.resolved_skill_intents = []
        self.sprite = {}
        self.animation = {}
        self.locomotion = {}
        self.projectile = {}
        self.lifetime = {}
        self.health = {}
        self.effect_deliveries = {}
        self.effect_carrier_lifecycle = {}
        self.team = {}
        self.ai_agent = {}
        self.contact_filter = {}
        self.hittable = {}
        self.selectable = {}
        self.interactable = {}
        self.combat_body = {}
        self.damage_requests = []
        self.heal_requests = []
        self.interact_request = []
        self.combat_attack = {}
        self.movement_collision = {}

        # Per-tick movement planning runtime.
        #
        # movement_proposal stores the raw movement intent sampled for an entity
        # before final admission.
        #
        # movement_approval stores the result that movement_apply_system will
        # eventually consume.
        #
        # These are transient runtime maps, not persistent save data.
        self.movement_proposal = {}
        self.movement_approval = {}
        self.debug_enemy_movement = {}

        # Movement occupancy is passive physical presence:
        # which gameplay tile footprint an entity uses for movement,
        # terrain interaction, placement, and dynamic movement blocking.
        #
        # transform.cpos remains the logical center / action origin.
        # space_occupier.movement_footprint defines centered tile offsets
        # around tile_from_cpos(transform.cpos).
        #
        # space_occupier.blocks_movement controls whether this entity is
        # inserted into dynamic movement occupancy as a blocker.
        #
        # Do not use movement_footprint as the final projectile/attack
        # contact body. Contact/hurt shapes belong to combat_body or future
        # projectile contact data.
        self.space_occupier = {}

        # Derived dynamic spatial caches.
        #
        # Movement footprints are split into:
        # - center tiles
        # - body tiles, meaning center + wings
        #
        # Dynamic movement blocks center/body overlap, not wing/wing overlap.
        self.dynamic_center_occupancy = {}
        self.dynamic_body_occupancy = {}

        self.dynamic_reserved_centers = {}
        self.dynamic_reserved_bodies = {}

        # Compatibility aliases for older debug/query code.
        self.dynamic_occupancy = {}
        self.dynamic_blocking_occupancy = {}
        self.dynamic_reservations = {}

        self.dynamic_occupancy_dirty = True

        self.influence_emitter = {}
        self.influence_receiver = {}
        self.influence_delta = {}
        self.area_member = {}

        self.debug_tile_highlights = []

        ##START
        ## Area / Player Runtime
        self.area_defs = AREA_DEFS
        self.current_area = None
        self.area_snapshots = {}

        self.player_state = deepcopy(DEFAULT_PLAYER_STATE)
        self.player = None

        self.tile_size = TILE_DIMENSION
        self.tile_images = {}
        self.tilemap = []
        self.static_collision_tiles = set()

        self.load_area(
            STARTING_AREA_ID,
            STARTING_SPAWN_ID,
        )

        ## Environment
#        self.create_wind_field_emitter()


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


    def iter_entity_component_maps(self):
        # Component maps keyed directly by entity id.
        #
        # If a new per-entity component dict is added to World, add it here so
        # entity cleanup stays centralized.
        return (
            self.transform,
            self.motion_state,
            self.action_state,
            self.status_effects,
            self.facing,
            self.move_intent,
            self.buffered_move_intent,
            self.path_build_state,
            self.move_target,
            self.aim_state,
            self.intent,
            self.pointer_action_state,
            self.keyboard_action_state,
            self.action_order,
            self.input_controlled,
            self.active_skill,
            self.sprite,
            self.animation,
            self.locomotion,
            self.projectile,
            self.lifetime,
            self.health,
            self.effect_deliveries,
            self.effect_carrier_lifecycle,
            self.team,
            self.ai_agent,
            self.contact_filter,
            self.hittable,
            self.selectable,
            self.interactable,
            self.combat_body,
            self.combat_attack,
            self.movement_collision,
            self.movement_proposal,
            self.movement_approval,
            self.space_occupier,
            self.influence_emitter,
            self.influence_receiver,
            self.influence_delta,
            self.area_member,
        )


    def iter_entity_snapshot_maps(self):
        # Snapshot maps are grouped separately because self.snapshot is a dict of
        # per-entity maps rather than a single component map.
        return self.snapshot.values()


    def clear_movement_planning_runtime(self):
        self.movement_proposal.clear()
        self.movement_approval.clear()
        self.debug_enemy_movement.clear()


    def remove_entity(self, eid):
        self.untrack_area_entity(eid)

        for component_map in self.iter_entity_component_maps():
            component_map.pop(eid, None)

        for snapshot_map in self.iter_entity_snapshot_maps():
            snapshot_map.pop(eid, None)

        # Skills and cooldowns are keyed by tuples such as:
        #   (entity_id, slot)
        #
        # They cannot be cleaned with a simple component_map.pop(eid).
        for key in list(self.skills):
            if key[0] == eid:
                self.skills.pop(key, None)

        for key in list(self.skill_cooldown):
            if key[0] == eid:
                self.skill_cooldown.pop(key, None)

        mark_dynamic_occupancy_dirty(self)


    def build_tile_images(self, tile_image_assets):
        tile_images = {}

        for tile_id, asset_key in tile_image_assets.items():
            tile_images[tile_id] = self.game.assets.images[asset_key]

        return tile_images


    def load_area(self, area_id, spawn_id):
        if area_id not in self.area_defs:
            raise ValueError(f"Unknown area id: {area_id!r}")

        area_def = self.area_defs[area_id]
        area_map = load_area_map(area_def["map_file"])

        if area_map["id"] != area_id:
            raise ValueError(
                f"Area def {area_id!r} points to map file "
                f"{area_def['map_file']!r}, but that map has id "
                f"{area_map['id']!r}"
            )

        if spawn_id not in area_map["spawn_points"]:
            raise ValueError(
                f"Area {area_id!r} has no spawn point {spawn_id!r}"
            )

        self.unload_current_area()

        tilemap = [
            list(row)
            for row in area_map["tilemap"]
        ]

        tile_images = self.build_tile_images(
            area_map["tile_image_assets"]
        )

        self.current_area = AreaRuntime(
            area_id=area_id,
            area_def=area_def,
            tilemap=tilemap,
            tile_images=tile_images,
            static_collision_tiles=set(area_map["static_collision_tiles"]),
            spawn_points=dict(area_map["spawn_points"]),
            transitions=list(area_map["transitions"]),
        )

        self.tilemap = self.current_area.tilemap
        self.tile_images = self.current_area.tile_images
        self.static_collision_tiles = set(
            self.current_area.static_collision_tiles
        )

        spawn_def = self.current_area.spawn_points[spawn_id]
        self.player = self.spawn_player(spawn_def)

        for entity_def in area_map["placed_entities"]:
            self.spawn_area_entity_from_def(entity_def)

        mark_dynamic_occupancy_dirty(self)
        rebuild_dynamic_occupancy(self)

        self.focus_camera_on_player()


    def unload_current_area(self):
        if self.player is not None:
            self.capture_player_state_from_entity(self.player)
            self.remove_entity(self.player)
            self.entities.dead.discard(self.player)
            self.player = None

        if self.current_area is not None:
            for eid in sorted(self.current_area.entity_ids):
                self.remove_entity(eid)
                self.entities.dead.discard(eid)

        self.current_area = None
        self.tile_images = {}
        self.tilemap = []
        self.static_collision_tiles = set()
        mark_dynamic_occupancy_dirty(self)


    def capture_player_state_from_entity(self, player):
        health = self.health.get(player)
        if health is not None:
            self.player_state["health"] = dict(health)

        skills = {}

        for key, skill_id in self.skills.items():
            entity, slot = key
            if entity == player:
                skills[slot] = skill_id

        self.player_state["skills"] = skills


    def track_area_entity(self, eid):
        if self.current_area is None:
            return

        self.current_area.track_entity(eid)
        self.area_member[eid] = self.current_area.area_id


    def untrack_area_entity(self, eid):
        if self.current_area is not None:
            self.current_area.untrack_entity(eid)

        self.area_member.pop(eid, None)


    def spawn_area_entity_from_def(self, entity_def):
        entity_type = entity_def["type"]

        if entity_type == "training_dummy":
            tile = vec2i_from_pair(entity_def["tile"])
            return self.spawn_training_dummy(tile)

        if entity_type == "debug_interactable":
            tile = vec2i_from_pair(entity_def["tile"])
            interact_kind = entity_def.get("interact_kind", "debug_chest")
            return self.spawn_debug_interactable(tile, interact_kind)

        raise ValueError(f"Unsupported placed entity type: {entity_type!r}")


    def spawn_debug_interactable(self, tile, interact_kind):
        eid = self.entities.create()
        cpos = tile_center(tile)

        self.transform[eid] = Transform(
            tile=tile,
            cpos=cpos,
            prev_cpos=cpos,
            position_mode="grid",
        )

        self.selectable[eid] = {
            "kind": "interactable",
            "enabled": True,
            "screen_priority": 10,
            "click_box": {
                "type": "rect",
                "anchor": "bottom_center",
                "offset": (0, -4),
                "size": (34, 34),
            },
        }

        self.interactable[eid] = {
            "kind": interact_kind,
            "handler": "debug_print",
            "used_count": 0,
        }

        # Non-blocking for this test object. Later doors/chests can become
        # physical blockers with approach-to-adjacent logic.
        self.space_occupier[eid] = {
            "blocks_movement": False,
            "movement_footprint": "single_tile",
        }

        self.sprite[eid] = {
            "image": self.game.assets.images["block"],
            "anchor": "bottom_center",
            "z": 0,
        }

        self.track_area_entity(eid)
        mark_dynamic_occupancy_dirty(self)
        return eid


    def focus_camera_on_player(self):
        self.world_camera.camera["target"] = self.player
        self.world_camera.camera["current_cpos"] = (
            self.transform[self.player].cpos
        )
        self.world_camera.camera["prev_cpos"] = (
            self.transform[self.player].cpos
        )


    def spawn_player(self, spawn_def):
        eid = self.entities.create()

        player_tile = vec2i_from_pair(spawn_def["tile"])
        player_cpos = tile_center(player_tile)

        player_transform = Transform(
            tile=player_tile,
            cpos=player_cpos,
            prev_cpos=player_cpos,
            position_mode="grid",
        )

        self.transform[eid] = player_transform
        self.facing[eid] = vec2i_from_pair(spawn_def["facing"])

        self.movement_collision[eid] = {
            "static_tiles": "slide",
            "dynamic_blockers": "slide",

            # Default/fallback ratio.
            "slide_min_tangent_ratio": (1, 2),
            # Direct grid movement: WASD / buffered WASD.
            "grid_slide_min_tangent_ratio": (1, 2),
            # Traditional click-to-move target movement.
            "mouse_slide_min_tangent_ratio": (2, 3),
            "corner_cutting": "allow",
        }

        self.space_occupier[eid] = {
            "blocks_movement": True,
            "movement_footprint": "plus5",
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

        self.locomotion[eid] = {
            "speed_cpos_per_tick": 410,
            "can_move_8way": True,
        }

        for slot, skill_id in self.player_state["skills"].items():
            if skill_id is not None:
                self.skills[(eid, slot)] = skill_id

        player_image = self.game.assets.images["player"]

        self.sprite[eid] = {
            "image": player_image,
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

        self.team[eid] = "player"

        self.health[eid] = dict(self.player_state["health"])

        self.hittable[eid] = {
            "enabled": True,
        }
        self.combat_body[eid] = {
            "collision_footprint": "plus5",
        }
        self.combat_attack[eid] = {
            "range_tiles": 2,
        }
        mark_dynamic_occupancy_dirty(self)

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
        self.facing[eid] = Vec2i(1, 0)
        self.movement_collision[eid] = {
            "static_tiles": "slide",
            "dynamic_blockers": "slide",

            "slide_min_tangent_ratio": (1, 2),
            "corner_cutting": "strict",
        }
        self.space_occupier[eid] = {
            "blocks_movement": True,
            "movement_footprint": "plus5",
        }
        self.motion_state[eid] = {
            "controller": None,
            "last_delta": Vec2i(0, 0),
            "influence_mode": "normal",
        }
        self.locomotion[eid] = {
            "speed_cpos_per_tick": 410,
            "can_move_8way": True,
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
        self.ai_agent[eid] = {
            "type": "melee_pawn",
            "enabled": True,
            "state": "idle",
            "target_entity": None,

            "think_interval_ticks": 1,
            "next_think_tick": self.tick + (eid % 6),

            "params": {
                "detect_radius_tiles": 22,
                "lose_radius_tiles": 26,
                "desired_range_tiles": 1,
                "path_policy": "actor_move",
            },

            # Runtime memory for behavior-specific state.
            "blackboard": {},
        }
        self.health[eid] = {
            "current": 30,
            "max": 30,
        }
        self.hittable[eid] = {
            "enabled": True,
        }
        self.selectable[eid] = {
            "kind": "enemy",
            "enabled": True,
            "screen_priority": 0,
            "click_box": {
                "type": "rect",
                "anchor": "bottom_center",
                "offset": (0, -4),
                "size": (36, 26),
            },
        }
        self.combat_body[eid] = {
            "collision_footprint": "plus5",
        }
        self.combat_attack[eid] = {
            "range_tiles": 2,
        }

        dummy_image = self.game.assets.images["player"]

        self.skills[(eid, 0)] = "debug_slash"

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

        self.track_area_entity(eid)

        mark_dynamic_occupancy_dirty(self)

        return eid