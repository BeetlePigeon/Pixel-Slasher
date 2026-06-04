from constants import TILE_UNITS
from effect_ops import spawn_effect_carrier
from support import Vec2i, Transform
from utils.tile_vec_utils import tile_from_cpos
from spawn_ops import can_spawn_at
from motion_controllers import (
    LinearProjectileController,
    SpiralProjectileController,
)


def spawn_test_projectile(
    world,
    cpos,
    aim_vector,
    speed,
    lifetime_ticks,
    source,
    skill_id,
    effect_triggers,
    collides_with_teams,
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
        "controller": LinearProjectileController(
            aim_vector=aim_vector,
            speed=speed,
        ),
        "last_delta": Vec2i(0, 0),
        "influence_mode": "normal",
    }
    world.projectile[eid] = {
        "source": source,
        "skill_id": skill_id,
        "effect_triggers": effect_triggers,
        "contact_footprint": "plus5",
        "contact_response": {
            "dynamic_actor": "destroy_self",
        },
    }
    world.movement_collision[eid] = {
        "static_tiles": "destroy",
        "dynamic_blockers": "allow",
    }
    world.space_occupier[eid] = {
        "blocks_movement": False,
        "movement_footprint": "plus5",
    }
    world.contact_filter[eid] = {
        "ignore_entities": {source},
        "collides_with_teams": set(collides_with_teams),
    }
    world.influence_receiver[eid] = {
        "accepts": {"wind", "magnet"},
        "scales": {
            "wind": (1, 1),
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