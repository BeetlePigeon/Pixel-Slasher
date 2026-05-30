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


@dataclass(frozen=True)
class PerfCounterSample:
    total: float
    max_value: float
    records: int


class PerfProfiler:
    def __init__(self, history_frames=240):
        self.enabled = True
        self.history_frames = history_frames

        self.current_frame = {}
        self.current_counters = {}

        self.history = defaultdict(
            lambda: deque(maxlen=self.history_frames)
        )
        self.counter_history = defaultdict(
            lambda: deque(maxlen=self.history_frames)
        )

    def begin_frame(self):
        if not self.enabled:
            return

        self.current_frame = {}
        self.current_counters = {}

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

        for name, data in self.current_counters.items():
            self.counter_history[name].append(
                PerfCounterSample(
                    total=data["total"],
                    max_value=data["max_value"],
                    records=data["records"],
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

    def record_counter(self, name, value=1.0):
        if not self.enabled:
            return

        data = self.current_counters.setdefault(
            name,
            {
                "total": 0.0,
                "max_value": 0.0,
                "records": 0,
            },
        )

        data["total"] += value
        data["max_value"] = max(
            data["max_value"],
            value,
        )
        data["records"] += 1

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

    def get_counter_summary_rows(self, limit=12):
        rows = []

        for name, samples in self.counter_history.items():
            if not samples:
                continue

            sample_count = len(samples)

            avg_total = (
                sum(sample.total for sample in samples)
                / sample_count
            )

            peak_total = max(
                sample.total
                for sample in samples
            )

            peak_value = max(
                sample.max_value
                for sample in samples
            )

            avg_records = (
                sum(sample.records for sample in samples)
                / sample_count
            )

            last = samples[-1]

            rows.append({
                "name": name,
                "avg_total": avg_total,
                "peak_total": peak_total,
                "peak_value": peak_value,
                "avg_records": avg_records,
                "last_total": last.total,
                "last_records": last.records,
            })

        rows.sort(
            key=lambda row: (
                row["avg_total"],
                row["peak_total"],
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


def record_counter_for_world(world, name, value=1.0):
    profiler = get_profiler_from_object(world)

    if profiler is None:
        return

    profiler.record_counter(
        name,
        value,
    )