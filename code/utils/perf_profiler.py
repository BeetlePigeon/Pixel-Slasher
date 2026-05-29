import time
from collections import defaultdict, deque
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from functools import wraps


@dataclass(frozen=True)
class PerfFrameSample:
    total_ms: float
    max_call_ms: float
    calls: int


class PerfProfiler:
    def __init__(self, history_frames=240):
        self.enabled = True
        self.history_frames = history_frames

        self.current_frame = {}
        self.history = defaultdict(
            lambda: deque(maxlen=self.history_frames)
        )

    def begin_frame(self):
        if not self.enabled:
            return

        self.current_frame = {}

    def end_frame(self):
        if not self.enabled:
            return

        for name, data in self.current_frame.items():
            self.history[name].append(
                PerfFrameSample(
                    total_ms=data["total_ms"],
                    max_call_ms=data["max_call_ms"],
                    calls=data["calls"],
                )
            )

    def record(self, name, elapsed_ms):
        if not self.enabled:
            return

        data = self.current_frame.setdefault(
            name,
            {
                "total_ms": 0.0,
                "max_call_ms": 0.0,
                "calls": 0,
            },
        )

        data["total_ms"] += elapsed_ms
        data["max_call_ms"] = max(
            data["max_call_ms"],
            elapsed_ms,
        )
        data["calls"] += 1

    @contextmanager
    def scope(self, name):
        if not self.enabled:
            yield
            return

        start_time = time.perf_counter()

        try:
            yield
        finally:
            elapsed_ms = (
                time.perf_counter()
                - start_time
            ) * 1000.0

            self.record(
                name,
                elapsed_ms,
            )

    def get_summary_rows(self, limit=12):
        rows = []

        for name, samples in self.history.items():
            if not samples:
                continue

            sample_count = len(samples)

            avg_total_ms = (
                sum(sample.total_ms for sample in samples)
                / sample_count
            )

            peak_total_ms = max(
                sample.total_ms
                for sample in samples
            )

            peak_call_ms = max(
                sample.max_call_ms
                for sample in samples
            )

            avg_calls = (
                sum(sample.calls for sample in samples)
                / sample_count
            )

            last = samples[-1]

            rows.append({
                "name": name,
                "avg_total_ms": avg_total_ms,
                "peak_total_ms": peak_total_ms,
                "peak_call_ms": peak_call_ms,
                "avg_calls": avg_calls,
                "last_total_ms": last.total_ms,
                "last_calls": last.calls,
            })

        rows.sort(
            key=lambda row: (
                row["avg_total_ms"],
                row["peak_total_ms"],
            ),
            reverse=True,
        )

        return rows[:limit]


def get_profiler_from_object(value):
    if value is None:
        return None

    # Common case: world.game.perf_profiler
    game = getattr(value, "game", None)

    if game is not None:
        return getattr(game, "perf_profiler", None)

    # Method case: self.game.perf_profiler
    nested_game = getattr(
        getattr(value, "game", None),
        "game",
        None,
    )

    if nested_game is not None:
        return getattr(nested_game, "perf_profiler", None)

    return None


def get_profiler_from_args(args, kwargs):
    if args:
        profiler = get_profiler_from_object(args[0])

        if profiler is not None:
            return profiler

    world = kwargs.get("world")

    if world is not None:
        return get_profiler_from_object(world)

    return None


def profiled(name):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            profiler = get_profiler_from_args(
                args,
                kwargs,
            )

            if profiler is None:
                return func(*args, **kwargs)

            with profiler.scope(name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def profile_scope(world, name):
    profiler = get_profiler_from_object(world)

    if profiler is None:
        return nullcontext()

    return profiler.scope(name)