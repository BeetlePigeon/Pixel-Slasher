from dataclasses import dataclass, field


@dataclass
class AreaRuntime:
    area_id: str
    area_def: dict
    tilemap: list
    tile_images: dict
    static_collision_tiles: set = field(default_factory=set)
    entity_ids: set = field(default_factory=set)

    def track_entity(self, eid):
        self.entity_ids.add(eid)

    def untrack_entity(self, eid):
        self.entity_ids.discard(eid)