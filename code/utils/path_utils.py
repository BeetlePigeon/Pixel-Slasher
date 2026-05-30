import heapq
from utils.perf_profiler import profiled, record_counter_for_world
from utils.placement_utils import is_tile_valid_for_entity_placement
from utils.tile_vec_utils import Vec2i, chebyshev_tile_distance, manhattan_tile_distance, tile_center, tiles_crossed_by_segment
from data.tables_dirs import CARDINAL_DIRS, CHEBY_DIRS


class PathSearchBudget:
    def __init__(self, max_expansions):
        self.remaining = max_expansions

    def consume(self) -> bool:
        if self.remaining <= 0:
            return False

        self.remaining -= 1
        return True


def get_corner_cutting_policy(world, entity):
    policy = world.movement_collision.get(entity, {})
    return policy.get("corner_cutting", "strict")


def tile_is_navigable_for_entity(world, entity, tile: Vec2i) -> bool:
    # Pathfinding searches possible logical-center tiles.
    # A candidate is navigable only if the entity's full movement
    # footprint can be placed there.
    record_counter_for_world(
        world,
        "path.nav_checks",
    )

    return is_tile_valid_for_entity_placement(
        world,
        tile,
        entity=entity,
        include_dynamic=True,
    )


def diagonal_step_allowed(world, entity, current_tile: Vec2i, direction: Vec2i) -> bool:
    if direction.x == 0 or direction.y == 0:
        return True

    target_tile = current_tile + direction

    if not tile_is_navigable_for_entity(world, entity, target_tile):
        return False

    side_x_tile = Vec2i(
        current_tile.x + direction.x,
        current_tile.y,
    )

    side_y_tile = Vec2i(
        current_tile.x,
        current_tile.y + direction.y,
    )

    side_x_open = tile_is_navigable_for_entity(
        world,
        entity,
        side_x_tile,
    )

    side_y_open = tile_is_navigable_for_entity(
        world,
        entity,
        side_y_tile,
    )

    corner_policy = get_corner_cutting_policy(world, entity)

    if corner_policy == "strict":
        return side_x_open and side_y_open

    if corner_policy == "allow_if_one_side_open":
        return side_x_open or side_y_open

    if corner_policy == "allow":
        return True

    raise ValueError(f"Unknown corner_cutting policy: {corner_policy}")


def step_is_navigable_for_entity(
    world,
    entity,
    current_tile: Vec2i,
    direction: Vec2i,
) -> bool:
    next_tile = current_tile + direction

    if not tile_is_navigable_for_entity(world, entity, next_tile):
        return False

    if not diagonal_step_allowed(
        world,
        entity,
        current_tile,
        direction,
    ):
        return False

    return True


def iter_path_neighbors(world, entity, tile: Vec2i, can_move_8way: bool):
    directions = CHEBY_DIRS if can_move_8way else CARDINAL_DIRS

    tests = 0
    accepted = 0

    try:
        for direction in directions:
            tests += 1

            if not step_is_navigable_for_entity(
                world,
                entity,
                tile,
                direction,
            ):
                continue

            accepted += 1

            yield tile + direction

    finally:
        record_counter_for_world(
            world,
            "path.neighbor_tests",
            tests,
        )

        record_counter_for_world(
            world,
            "path.neighbor_ok",
            accepted,
        )


def reconstruct_path(came_from, start_tile: Vec2i, goal_tile: Vec2i):
    path = []
    current = goal_tile

    while current != start_tile:
        path.append(current)
        current = came_from[current]

    path.reverse()
    return path


def record_path_find_result(
    world,
    result_name,
    expansions,
):
    record_counter_for_world(
        world,
        "path.find_calls",
    )

    record_counter_for_world(
        world,
        "path.expansions",
        expansions,
    )

    record_counter_for_world(
        world,
        f"path.result.{result_name}",
    )


@profiled("path.find")
def find_static_tile_path(
    world,
    entity,
    start_tile: Vec2i,
    goal_tile: Vec2i,
    can_move_8way: bool,
    search_budget: PathSearchBudget,
    max_path_length,
):
    expansions = 0

    if start_tile == goal_tile:
        record_path_find_result(
            world,
            "start_is_goal",
            expansions,
        )
        return []

    if not tile_is_navigable_for_entity(world, entity, goal_tile):
        record_path_find_result(
            world,
            "goal_invalid",
            expansions,
        )
        return None

    if max_path_length is not None:
        # Chebyshev distance is a lower bound for 8-way movement.
        # If even the best possible direct path is too long, do not search.
        if chebyshev_tile_distance(start_tile, goal_tile) > max_path_length:
            record_path_find_result(
                world,
                "too_long_precheck",
                expansions,
            )
            return None

    frontier = []
    push_counter = 0

    heapq.heappush(
        frontier,
        (
            chebyshev_tile_distance(start_tile, goal_tile),
            0,
            start_tile.y,
            start_tile.x,
            push_counter,
            start_tile,
        ),
    )

    came_from = {}
    cost_so_far = {
        start_tile: 0,
    }

    while frontier:
        _, current_cost, _, _, _, current_tile = heapq.heappop(frontier)

        if not search_budget.consume():
            record_path_find_result(
                world,
                "budget_exhausted",
                expansions,
            )
            return None

        expansions += 1

        if max_path_length is not None and current_cost >= max_path_length:
            continue

        if current_tile == goal_tile:
            path = reconstruct_path(
                came_from,
                start_tile,
                goal_tile,
            )

            if max_path_length is not None and len(path) > max_path_length:
                record_path_find_result(
                    world,
                    "too_long_result",
                    expansions,
                )
                return None

            record_path_find_result(
                world,
                "success",
                expansions,
            )
            return path

        for neighbor in iter_path_neighbors(
            world,
            entity,
            current_tile,
            can_move_8way,
        ):
            new_cost = current_cost + 1

            if neighbor in cost_so_far and new_cost >= cost_so_far[neighbor]:
                continue

            cost_so_far[neighbor] = new_cost
            came_from[neighbor] = current_tile

            heuristic = chebyshev_tile_distance(
                neighbor,
                goal_tile,
            )

            priority = new_cost + heuristic

            push_counter += 1

            heapq.heappush(
                frontier,
                (
                    priority,
                    new_cost,
                    neighbor.y,
                    neighbor.x,
                    push_counter,
                    neighbor,
                ),
            )

    record_path_find_result(
        world,
        "no_path",
        expansions,
    )

    return None


def iter_target_snap_candidates(
    world,
    entity,
    target_tile: Vec2i,
    start_tile: Vec2i,
    snap_radius: int,
):
    candidates = []

    candidate_tests = 0
    candidate_valid = 0

    for radius in range(snap_radius + 1):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                candidate = Vec2i(
                    target_tile.x + dx,
                    target_tile.y + dy,
                )

                distance_from_target = chebyshev_tile_distance(
                    candidate,
                    target_tile,
                )

                if distance_from_target != radius:
                    continue

                candidate_tests += 1

                if not tile_is_navigable_for_entity(
                    world,
                    entity,
                    candidate,
                ):
                    continue

                candidate_valid += 1

                distance_from_start = chebyshev_tile_distance(
                    candidate,
                    start_tile,
                )

                candidates.append((
                    distance_from_target,
                    distance_from_start,
                    manhattan_tile_distance(candidate, start_tile),
                    candidate.y,
                    candidate.x,
                    candidate,
                ))

    record_counter_for_world(
        world,
        "path.snap_tests",
        candidate_tests,
    )

    record_counter_for_world(
        world,
        "path.snap_valid",
        candidate_valid,
    )

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3],
            item[4],
        )
    )

    for candidate in candidates:
        yield candidate[5]


@profiled("path.find_to_target")
def find_static_tile_path_to_target(
    world,
    entity,
    start_tile: Vec2i,
    target_tile: Vec2i,
    can_move_8way: bool,
    max_expansions: int,
    max_path_length,
    target_snap_radius: int,
):
    search_budget = PathSearchBudget(max_expansions)

    candidate_goals_tried = 0

    for candidate_goal in iter_target_snap_candidates(
        world,
        entity,
        target_tile,
        start_tile,
        target_snap_radius,
    ):
        if search_budget.remaining <= 0:
            record_counter_for_world(
                world,
                "path.goals_tried",
                candidate_goals_tried,
            )

            record_counter_for_world(
                world,
                "path.to_target.budget_empty",
            )

            return None

        candidate_goals_tried += 1

        path = find_static_tile_path(
            world,
            entity=entity,
            start_tile=start_tile,
            goal_tile=candidate_goal,
            can_move_8way=can_move_8way,
            search_budget=search_budget,
            max_path_length=max_path_length,
        )

        if path is not None:
            record_counter_for_world(
                world,
                "path.goals_tried",
                candidate_goals_tried,
            )

            record_counter_for_world(
                world,
                "path.to_target.success",
            )

            return path

    record_counter_for_world(
        world,
        "path.goals_tried",
        candidate_goals_tried,
    )

    record_counter_for_world(
        world,
        "path.to_target.failed",
    )

    return None


@profiled("path.segment")
def path_segment_clear(world, entity, start_tile: Vec2i, end_tile: Vec2i) -> bool:
    start_cpos = tile_center(start_tile)
    end_cpos = tile_center(end_tile)

    crossed_tiles = tiles_crossed_by_segment(
        start_cpos,
        end_cpos,
    )

    for tile in crossed_tiles:
        if not tile_is_navigable_for_entity(world, entity, tile):
            return False

    return True


@profiled("path.smooth")
def smooth_static_tile_path(world, entity, start_tile: Vec2i, path_tiles):
    if not path_tiles:
        return []

    full_path = [start_tile] + list(path_tiles)

    smoothed = []
    anchor_index = 0

    while anchor_index < len(full_path) - 1:
        farthest_index = anchor_index + 1

        for test_index in range(len(full_path) - 1, anchor_index, -1):
            if path_segment_clear(
                world,
                entity,
                full_path[anchor_index],
                full_path[test_index],
            ):
                farthest_index = test_index
                break

        smoothed.append(full_path[farthest_index])
        anchor_index = farthest_index

    return smoothed


def path_tiles_to_cpos_nodes(path_tiles):
    return [
        tile_center(tile)
        for tile in path_tiles
    ]