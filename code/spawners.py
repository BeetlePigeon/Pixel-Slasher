from settings import TILE_UNITS
from support import (
    Vec2i,
    Transform,
    tile_from_cpos,
    LinearProjectileController,
    SpiralProjectileController,
    ANGLE_SCALE,
)


def spawn_test_projectile(world, cpos, direction):
    eid = world.entities.create()

    projectile_image = world.game.assets.images["test_projectile"]

    world.transform[eid] = Transform(
        tile=tile_from_cpos(cpos),
        cpos=cpos,
        position_mode="free",
    )

    world.motion_state[eid] = {
        "controller": LinearProjectileController(
            direction=direction,
            speed=TILE_UNITS // 8,
        ),
        "last_delta": Vec2i(0, 0),
        "influence_mode": "normal",
    }

    world.projectile[eid] = {}
    world.movement_collision[eid] = {
        "static_tiles": "destroy",
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
        "remaining_ticks": 120,
    }

    world.sprite[eid] = {
        "image": projectile_image,
        "anchor": "center",
        "z": 0,
    }

    return eid

def spawn_spiral_projectile(world, cpos):
    eid = world.entities.create()

    projectile_image = world.game.assets.images["test_projectile"]

    world.transform[eid] = Transform(
        tile=tile_from_cpos(cpos),
        cpos=cpos,
        position_mode="free",
    )

    world.motion_state[eid] = {
        "controller": SpiralProjectileController(
            origin=cpos,
            age=0,
            radius_per_tick=TILE_UNITS // 32,
            angle_step_fp=ANGLE_SCALE // 8,
        ),
        "last_delta": Vec2i(0, 0),
        "influence_mode": "ignore_all",
    }

    world.projectile[eid] = {}
    world.movement_collision[eid] = {
        "static_tiles": "destroy",
    }
    world.influence_receiver[eid] = {
        "accepts": {"wind", "magnet"},
        "scales": {
            "wind": (1, 1),     # Rational fraction: (1, 1) = 1/1 = 100%, (2, 3) = 2/3 = 66.67%
            "magnet": (3, 1),
        },
        "max_delta": TILE_UNITS // 8,
    }

    world.lifetime[eid] = {
        "remaining_ticks": 180,
    }

    world.sprite[eid] = {
        "image": projectile_image,
        "anchor": "center",
        "z": 0,
    }

    return eid

def create_magnet_emitter(world, cpos):
    eid = world.entities.create()

    orb_image = world.game.assets.images["magnet"]

    world.transform[eid] = Transform(
        tile=tile_from_cpos(cpos),
        cpos=cpos,
        position_mode="free",
    )

    world.influence_emitter[eid] = {
        "type": "magnet",
        "radius": TILE_UNITS * 10,
        "strength": TILE_UNITS // 24,
    }

    world.lifetime[eid] = {
        "remaining_ticks": 1800,
    }

    world.sprite[eid] = {
        "image": orb_image,
        "anchor": "center",
        "z": 0,
    }

    return eid