from settings import TILE_UNITS
from support import (
    Vec2i,
    Transform,
    tile_from_cpos,
    LinearProjectileController,
    SpiralProjectileController,
    ANGLE_SCALE,
)


def is_spawn_tile_blocked(world, tile):
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return True

    if tile.x < 0 or tile.x >= len(world.tilemap[tile.y]):
        return True

    return (tile.x, tile.y) in world.static_collision_tiles


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


def spawn_meteor_marker(
    world,
    cpos,
    source,
    skill_id,
    radius_tiles,
    damage,
    impact_tick,
    lifetime_ticks,
    telegraph_highlight_ticks,
    telegraph_highlight_color,
    impact_highlight_ticks,
    impact_highlight_color,
):
    if not can_spawn_at(world, cpos, static_tiles="reject"):
        return None

    eid = world.entities.create()

    marker_image = world.game.assets.images["magnet"]

    world.transform[eid] = Transform(
        tile=tile_from_cpos(cpos),
        cpos=cpos,
        prev_cpos=cpos,
        position_mode="free",
    )

    world.runtime_skill[eid] = {
        "type": "meteor_marker",
        "source": source,
        "skill_id": skill_id,

        "age": 0,
        "impact_tick": impact_tick,
        "duration": lifetime_ticks,
        "impacted": False,

        "radius_tiles": radius_tiles,
        "damage": damage,

        "telegraph_highlight_ticks": telegraph_highlight_ticks,
        "telegraph_highlight_color": telegraph_highlight_color,
        "impact_highlight_ticks": impact_highlight_ticks,
        "impact_highlight_color": impact_highlight_color,
    }

    world.sprite[eid] = {
        "image": marker_image,
        "anchor": "center",
        "z": 0,
    }

    return eid