from motion_controllers import ChaseEntityController, PathFollowController
from support import Vec2i
from utils.action_order_utils import (
    get_entity_skill_range_tiles,
    min_distance_to_tiles,
)
from utils.occupancy_utils import (
    is_tile_static_blocked,
    mark_dynamic_occupancy_dirty,
    rebuild_dynamic_occupancy,
)
from utils.tile_vec_utils import (
    chebyshev_tile_distance,
    tile_center,
    tile_from_cpos,
)


CHASE_STRESS_RADIAL_OPEN_COLLAPSE = "chase_stress_radial_open_collapse"
DEFAULT_CHASE_STRESS_PLAYER_TILE = Vec2i(19, 19)
DEFAULT_CHASE_STRESS_ENEMY_COUNT = 60
DEFAULT_CHASE_STRESS_RADIUS = 16


def clear_non_player_entities(world):
    for entity in sorted(set(world.transform)):
        if entity == world.player:
            continue

        world.remove_entity(entity)
        world.entities.dead.discard(entity)

    world.events.clear()
    world.move_intent.clear()
    world.buffered_move_intent.clear()
    world.move_target.clear()
    world.intent.clear()
    world.action_order.clear()
    world.resolved_skill_intents.clear()
    world.damage_requests.clear()
    world.heal_requests.clear()
    world.interact_request.clear()
    world.clear_movement_planning_runtime()

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)


def set_entity_tile(world, entity, tile):
    cpos = tile_center(tile)
    transform = world.transform[entity]
    transform.tile = tile
    transform.cpos = cpos
    transform.prev_cpos = cpos
    transform.position_mode = "grid"


def configure_player(world, player_tile):
    set_entity_tile(world, world.player, player_tile)

    motion_state = world.motion_state.get(world.player)
    if motion_state is not None:
        motion_state["controller"] = None
        motion_state["last_delta"] = Vec2i(0, 0)
        motion_state["influence_mode"] = "normal"

    world.move_intent.pop(world.player, None)
    world.buffered_move_intent.pop(world.player, None)
    world.move_target.pop(world.player, None)
    world.action_order.pop(world.player, None)

    world.focus_camera_on_player()


def build_square_ring_tiles(center_tile, radius):
    tiles = []

    left = center_tile.x - radius
    right = center_tile.x + radius
    top = center_tile.y - radius
    bottom = center_tile.y + radius

    for x in range(left, right + 1):
        tiles.append(Vec2i(x, top))

    for y in range(top + 1, bottom + 1):
        tiles.append(Vec2i(right, y))

    for x in range(right - 1, left - 1, -1):
        tiles.append(Vec2i(x, bottom))

    for y in range(bottom - 1, top, -1):
        tiles.append(Vec2i(left, y))

    return tiles


def candidate_ring_tiles(center_tile, radius):
    tiles = build_square_ring_tiles(center_tile, radius)
    if not tiles:
        return []

    offset = len(tiles) // 8
    return tiles[offset:] + tiles[:offset]


def tile_conflicts_with_selected(tile, selected_tiles):
    return any(
        chebyshev_tile_distance(tile, selected_tile) < 2
        for selected_tile in selected_tiles
    )


def choose_ring_spawn_tiles(world, center_tile, radius, enemy_count):
    ring_tiles = candidate_ring_tiles(center_tile, radius)
    if not ring_tiles:
        raise RuntimeError("No ring tiles generated.")

    selected = []
    attempts = 0
    cursor = 0

    while len(selected) < enemy_count and attempts < len(ring_tiles) * 4:
        tile = ring_tiles[cursor % len(ring_tiles)]
        cursor += max(1, len(ring_tiles) // max(1, enemy_count))
        attempts += 1

        if is_tile_static_blocked(world, tile):
            continue

        if tile_conflicts_with_selected(tile, selected):
            continue

        selected.append(tile)

    if len(selected) < enemy_count:
        raise RuntimeError(
            f"Only placed {len(selected)} enemies on radius {radius}; "
            f"requested {enemy_count}. Increase radius or lower enemy count."
        )

    return selected


def configure_radial_open_collapse(
    world,
    enemy_count=DEFAULT_CHASE_STRESS_ENEMY_COUNT,
    radius=DEFAULT_CHASE_STRESS_RADIUS,
    player_tile=DEFAULT_CHASE_STRESS_PLAYER_TILE,
):
    world.load_area("destacker_arena", "default")

    clear_non_player_entities(world)
    configure_player(world, player_tile)

    enemy_tiles = choose_ring_spawn_tiles(
        world,
        center_tile=player_tile,
        radius=radius,
        enemy_count=enemy_count,
    )

    enemies = []
    for index, tile in enumerate(enemy_tiles):
        enemy = world.spawn_training_dummy(tile)

        world.ai_agent[enemy]["think_interval_ticks"] = 1
        world.ai_agent[enemy]["next_think_tick"] = world.tick + (index % 6)
        world.ai_agent[enemy]["target_entity"] = None

        enemies.append(enemy)

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)

    return enemies


def get_chase_stress_enemies(world):
    return tuple(
        sorted(
            entity
            for entity in world.ai_agent
            if entity in world.transform
        )
    )


def summarize_chase_stress_state(world):
    enemies = get_chase_stress_enemies(world)
    player = world.player
    player_tiles = get_entity_skill_range_tiles(world, player)

    chase_controller_count = 0
    path_follow_controller_count = 0
    distances = []

    for enemy in enemies:
        motion_state = world.motion_state.get(enemy, {})
        controller = motion_state.get("controller")

        if isinstance(controller, ChaseEntityController):
            chase_controller_count += 1

        if isinstance(controller, PathFollowController):
            path_follow_controller_count += 1

        enemy_tile = tile_from_cpos(world.transform[enemy].cpos)

        if player_tiles:
            distances.append(
                min_distance_to_tiles(enemy_tile, player_tiles)
            )

    avg_distance = sum(distances) / len(distances) if distances else 0.0
    max_distance = max(distances) if distances else 0

    return {
        "enemy_count": len(enemies),
        "active_chase_controllers": chase_controller_count,
        "active_path_follow_controllers": path_follow_controller_count,
        "avg_distance_to_player_body": avg_distance,
        "max_distance_to_player_body": max_distance,
    }