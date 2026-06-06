from constants import TILE_UNITS
import copy
from effect_ops import spawn_effect_carrier
from support import Vec2i, Transform
from utils.tile_vec_utils import tile_from_cpos
from spawn_ops import can_spawn_at
from motion_controllers import (
    LinearProjectileController,
    SpiralProjectileController,
)
from projectile_info_registry import PROJECTILE_INFO
from utils.projectile_utils import build_projectile_influence_receiver




def spawn_projectile(
    world,
    projectile_id,
    cpos,
    aim_vector,
    source,
    skill_id,
):
    projectile_info = PROJECTILE_INFO[projectile_id]

    spawn_info = projectile_info.get("spawn", {})
    if not can_spawn_at(
        world,
        cpos,
        static_tiles=spawn_info.get("static_tiles", "reject"),
    ):
        return None

    eid = world.entities.create()

    world.transform[eid] = Transform(
        tile=tile_from_cpos(cpos),
        cpos=cpos,
        prev_cpos=cpos,
        position_mode="free",
    )

    motion_state = build_projectile_motion_state(
        projectile_info,
        aim_vector,
    )
    if motion_state is not None:
        world.motion_state[eid] = motion_state

    world.projectile[eid] = build_projectile_component(
        projectile_info,
        source,
        skill_id,
    )

    world.movement_collision[eid] = copy.deepcopy(
        projectile_info["movement_collision"],
    )

    world.space_occupier[eid] = {
        "blocks_movement": projectile_info.get("blocks_movement", False),
        "movement_footprint": projectile_info["movement_footprint"],
    }

    world.contact_filter[eid] = build_projectile_contact_filter(
        projectile_info,
        source,
    )

    if "influence_receiver" in projectile_info:
        world.influence_receiver[eid] = (
            build_projectile_influence_receiver(projectile_info)
        )

    if "lifetime_ticks" in projectile_info:
        world.lifetime[eid] = {
            "remaining_ticks": projectile_info["lifetime_ticks"],
        }

    if "sprite" in projectile_info:
        sprite_info = projectile_info["sprite"]
        world.sprite[eid] = {
            "image": world.game.assets.images[sprite_info["image"]],
            "anchor": sprite_info["anchor"],
            "z": sprite_info["z"],
        }

    return eid


def build_projectile_motion_state(projectile_info, aim_vector):
    motion_info = projectile_info.get("motion", {})
    motion_type = motion_info.get("type", "linear")

    if motion_type in {"none", "static"}:
        return None

    if motion_type == "linear":
        if aim_vector is None:
            raise ValueError(
                "Linear projectile requires aim_vector"
            )

        return {
            "controller": LinearProjectileController(
                aim_vector=aim_vector,
                speed=motion_info["speed"],
            ),
            "last_delta": Vec2i(0, 0),
            "influence_mode": motion_info.get(
                "influence_mode",
                "normal",
            ),
        }

    raise NotImplementedError(
        f"Projectile motion type not implemented: {motion_type}"
    )


def build_projectile_component(
    projectile_info,
    source,
    skill_id,
):
    projectile = {
        "source": source,
        "skill_id": skill_id,
        "effect_triggers": copy.deepcopy(
            projectile_info.get("effect_triggers", []),
        ),
        "impact_responses": copy.deepcopy(
            projectile_info.get("impact_responses", {}),
        ),
        "contact_runtime": {},
    }

    if "contact_footprint" in projectile_info:
        projectile["contact_footprint"] = projectile_info[
            "contact_footprint"
        ]

    if "contact_cadence" in projectile_info:
        projectile["contact_cadence"] = copy.deepcopy(
            projectile_info["contact_cadence"],
        )

    return projectile


def build_projectile_contact_filter(projectile_info, source):
    contact_filter = {
        "ignore_entities": set(),
    }

    if projectile_info.get("ignore_source", True):
        contact_filter["ignore_entities"].add(source)

    if "collides_with_teams" in projectile_info:
        contact_filter["collides_with_teams"] = set(
            projectile_info["collides_with_teams"],
        )

    if "collision_group" in projectile_info:
        contact_filter["collision_group"] = projectile_info[
            "collision_group"
        ]

    if "ignore_collision_groups" in projectile_info:
        contact_filter["ignore_collision_groups"] = set(
            projectile_info["ignore_collision_groups"],
        )

    return contact_filter


def spawn_spiral_projectile(
    world,
    cpos,
    lifetime_ticks,
    radius_per_tick,
    spawn_angle_step_offset,
    angle_step_fp,
):
    if not can_spawn_at(world, cpos, static_tiles="reject"):
        return None

    eid = world.entities.create()

    projectile_image = world.game.assets.images["test_projectile"]

    world.transform[eid] = Transform(
        tile=tile_from_cpos(cpos),
        cpos=cpos,
        prev_cpos=cpos,
        position_mode="free",
    )

    world.motion_state[eid] = {
        "controller": SpiralProjectileController(
            origin=cpos,
            age=0,
            radius_per_tick=radius_per_tick,
            angle_step_fp=angle_step_fp,
            spawn_angle_step_offset=spawn_angle_step_offset,
        ),
        "last_delta": Vec2i(0, 0),
        "influence_mode": "ignore_all",
    }

    world.projectile[eid] = {}
    world.movement_collision[eid] = {
        "static_tiles": "destroy",
        "dynamic_blockers": "allow",
    }
    world.space_occupier[eid] = {
        "blocks_movement": False,
        "movement_footprint": "single_tile",
    }
    world.influence_receiver[eid] = {
        "accepts": {},
        "scales": {
            "wind": (1, 1),     # Rational fraction: (1, 1) = 1/1 = 100%, (2, 3) = 2/3 = 66.67%
            "magnet": (1, 1),
        },
        "max_delta": TILE_UNITS // 8,
    }

    world.lifetime[eid] = {
        "remaining_ticks": lifetime_ticks,
    }

    world.sprite[eid] = {
        "image": projectile_image,
        "anchor": "center",
        "z": 0,
    }

    return eid


def spawn_magnet_orb(
    world,
    cpos,
    radius,
    strength,
    lifetime_ticks,
):
    if not can_spawn_at(world, cpos, static_tiles="reject"):
        return None

    eid = world.entities.create()

    orb_image = world.game.assets.images["magnet"]

    world.transform[eid] = Transform(
        tile=tile_from_cpos(cpos),
        cpos=cpos,
        prev_cpos=cpos,
        position_mode="free",
    )

    world.influence_emitter[eid] = {
        "type": "magnet",
        "radius": radius,
        "strength": strength,
    }

    world.lifetime[eid] = {
        "remaining_ticks": lifetime_ticks,
    }

    world.sprite[eid] = {
        "image": orb_image,
        "anchor": "center",
        "z": 0,
    }

    return eid


def spawn_meteor(
    world,
    cpos,
    source,
    skill_id,
    effect_delivery_templates,
    effect_carrier_lifecycle,
    visual,
):
    return spawn_effect_carrier(
        world,
        cpos,
        source=source,
        skill_id=skill_id,
        effect_delivery_templates=effect_delivery_templates,
        effect_carrier_lifecycle=effect_carrier_lifecycle,
        visual=visual,
        static_tiles_placement_handling="reject",
    )