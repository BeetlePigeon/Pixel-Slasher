import copy
from constants import TILE_UNITS
from systems.effect_delivery_system import build_square_area_tiles
from support import Vec2i, Transform
from utils.tile_vec_utils import tile_from_cpos
from utils.occupancy_utils import is_tile_static_blocked
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

    world.projectile[eid] = {}
    world.movement_collision[eid] = {
        "static_tiles": "destroy",
        "dynamic_blockers": "allow",
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
    effect_delivery_template,
    lifetime_ticks,
    visual,
):
    if not can_spawn_at(world, cpos, static_tiles="reject"):
        return None

    eid = world.entities.create()
    tile = tile_from_cpos(cpos)

    world.transform[eid] = Transform(
        tile=tile,
        cpos=cpos,
        prev_cpos=cpos,
        position_mode="free",
    )

    effect_delivery = copy.deepcopy(effect_delivery_template)

    delivery = effect_delivery["delivery"]
    delivery["age"] = 0

    shape = delivery.pop("shape")
    shape_type = shape["type"]

    if shape_type == "square":
        delivery["tiles"] = build_square_area_tiles(
            tile,
            shape["radius_tiles"],
        )
    else:
        raise NotImplementedError(
            f"Meteor effect delivery shape not implemented: {shape_type}"
        )

    effect_delivery["context"] = {
        "owner": source,
        "instigator": source,
        "source_kind": "skill",
        "source_id": skill_id,
    }

    world.effect_delivery[eid] = effect_delivery

    world.lifetime[eid] = {
        "remaining_ticks": lifetime_ticks,
    }

    image_id = visual["image"]
    world.sprite[eid] = {
        "image": world.game.assets.images[image_id],
        "anchor": visual["anchor"],
        "z": visual["z"],
    }
    return eid


def can_spawn_at(world, cpos, static_tiles="reject"):
    tile = tile_from_cpos(cpos)

    blocked = is_spawn_tile_blocked(world, tile)

    if not blocked:
        return True

    if static_tiles == "allow":
        return True

    if static_tiles == "reject":
        return False

    raise ValueError(f"Unknown spawn collision policy: {static_tiles}")


def is_spawn_tile_blocked(world, tile):
    return is_tile_static_blocked(world, tile)