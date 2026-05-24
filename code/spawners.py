import pygame
from settings import TILE_UNITS
from systems.effect_delivery_system import build_square_area_tiles
from support import (
    Vec2i,
    Transform,
    tile_from_cpos,
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


def spawn_meteor(
    world,
    cpos,
    source,
    skill_id,
    radius_tiles=1,
    damage=25,
    impact_tick=45,
    lifetime_ticks=60,
    telegraph_highlight_ticks=2,
    impact_highlight_ticks=10,
    telegraph_highlight_color="yellow",
    impact_highlight_color="red",
):
    eid = world.entities.create()

    tile = tile_from_cpos(cpos)

    world.transform[eid] = Transform(
        tile=tile,
        cpos=cpos,
    )

    center_tile = tile

    affected_tiles = build_square_area_tiles(
        center_tile,
        radius_tiles,
    )

    source_team = None

    if source is not None:
        source_team = world.team.get(source)

    world.effect_delivery[eid] = {
        "context": {
            "owner": source,
            "instigator": source,
            "source_kind": "skill",
            "source_id": skill_id,
            "team": source_team,
        },
        "delivery": {
            "type": "timed_tiles",
            "age": 0,
            "trigger_tick": impact_tick,
            "tiles": affected_tiles,
        },
        "target_filter": {
            "team_policy": "hostile_to_owner",
            "requires": {"hittable"},
        },
        "hit_policy": {
            "mode": "once",
        },
        "effects": [
            {
                "type": "damage",
                "params": {
                    "amount": damage,
                    "damage_type": "fire",
                },
            }
        ],
        "consume_policy": {
            "destroy_carrier_after_delivery": True,
        },
        "debug": {
            "telegraph_highlight_ticks": telegraph_highlight_ticks,
            "impact_highlight_ticks": impact_highlight_ticks,
            "telegraph_highlight_color": telegraph_highlight_color,
            "impact_highlight_color": impact_highlight_color,
        },
    }

    world.lifetime[eid] = {
        "remaining_ticks": lifetime_ticks,
    }

    marker_surface = pygame.Surface((world.tile_size, world.tile_size), pygame.SRCALPHA)
    marker_surface.fill((255, 180, 0, 80))

    world.sprite[eid] = {
        "image": marker_surface,
        "anchor": Vec2i(
            world.tile_size // 2,
            world.tile_size // 2,
        ),
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
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return True

    if tile.x < 0 or tile.x >= len(world.tilemap[tile.y]):
        return True

    return (tile.x, tile.y) in world.static_collision_tiles