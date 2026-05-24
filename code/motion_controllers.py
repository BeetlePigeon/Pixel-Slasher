import math
from dataclasses import dataclass
from support import Vec2i
from tile_vec_utils import (
    scale_normalized_dir,
    normalize_vector_to_dir_scale,
    lerp_vec,
    spiral_pos
)


@dataclass
class PathFollowController:
    nodes: list
    current_index: int
    speed: int
    created_tick: int
    target_tile: Vec2i

    motion_tag = "path_follow"

    def sample_delta_from(self, current_cpos: Vec2i) -> Vec2i:
        remaining_distance = self.speed
        next_cpos = current_cpos
        next_index = self.current_index

        while remaining_distance > 0 and next_index < len(self.nodes):
            target_cpos = self.nodes[next_index]
            to_target = target_cpos - next_cpos

            distance = math.isqrt(
                to_target.x * to_target.x
                + to_target.y * to_target.y
            )

            if distance == 0:
                next_index += 1
                continue

            if distance <= remaining_distance:
                next_cpos = target_cpos
                remaining_distance -= distance
                next_index += 1
                continue

            step = scale_normalized_dir(
                normalize_vector_to_dir_scale(to_target),
                remaining_distance,
            )

            next_cpos = next_cpos + step
            remaining_distance = 0

        self._pending_index = next_index
        return next_cpos - current_cpos

    def advance(self):
        self.current_index = getattr(
            self,
            "_pending_index",
            self.current_index,
        )

    def finished(self) -> bool:
        return self.current_index >= len(self.nodes)


@dataclass
class DirectionalMoveController:
    aim_vector: Vec2i
    raw_direction: Vec2i
    speed: int

    motion_tag = "directional_move"

    def sample_delta(self) -> Vec2i:
        return scale_normalized_dir(
            self.aim_vector,
            self.speed,
        )

    def advance(self):
        pass

    def finished(self) -> bool:
        return False


@dataclass
class GridMoveController:
    start: Vec2i
    end: Vec2i
    progress: int
    duration: int

    motion_tag = "grid_move"

    def sample_delta(self) -> Vec2i:  # LERP style
        prev = lerp_vec(self.start, self.end, self.progress, self.duration)
        next_ = lerp_vec(self.start, self.end, self.progress + 1, self.duration)
        return next_ - prev

    def advance(self):
        self.progress += 1

    def finished(self) -> bool:
        return self.progress >= self.duration


@dataclass
class DashController:
    aim_vector: Vec2i
    age: int
    duration: int
    distance: int
    slide_min_tangent_ratio: tuple

    motion_tag = "dash"

    def sample_delta(self) -> Vec2i:
        prev_dist = self.distance * self.age // self.duration
        next_dist = self.distance * (self.age + 1) // self.duration

        step_distance = next_dist - prev_dist

        return scale_normalized_dir(self.aim_vector, step_distance)

    def advance(self):
        self.age += 1

    def finished(self) -> bool:
        return self.age >= self.duration


@dataclass
class SettleToGridController:
    start: Vec2i
    end: Vec2i
    progress: int
    duration: int

    motion_tag = "settle"

    def sample_delta(self) -> Vec2i:
        prev = lerp_vec(self.start, self.end, self.progress, self.duration)
        next_ = lerp_vec(self.start, self.end, self.progress + 1, self.duration)
        return next_ - prev

    def advance(self):
        self.progress += 1

    def finished(self) -> bool:
        return self.progress >= self.duration


@dataclass
class LinearProjectileController:
    aim_vector: Vec2i
    speed: int

    def sample_delta(self) -> Vec2i:
        return scale_normalized_dir(
            self.aim_vector,
            self.speed,
        )

    def advance(self):
        pass

    def finished(self) -> bool:
        return False


@dataclass
class SpiralProjectileController:
    origin: Vec2i
    age: int
    radius_per_tick: int
    angle_step_fp: int
    spawn_angle_step_offset: int
    angle_index_fp: int = 0

    def sample_delta(self) -> Vec2i:
        prev = spiral_pos(
            self.origin,
            self.age,
            self.radius_per_tick,
            self.angle_step_fp,
            self.spawn_angle_step_offset,
            self.angle_index_fp,
        )
        next_ = spiral_pos(
            self.origin,
            self.age + 1,
            self.radius_per_tick,
            self.angle_step_fp,
            self.spawn_angle_step_offset,
            self.angle_index_fp,
        )
        return next_ - prev

    def advance(self):
        self.age += 1

    def finished(self) -> bool:
        return False