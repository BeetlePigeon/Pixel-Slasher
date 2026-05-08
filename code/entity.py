class EntityManager:
    def __init__(self):
        self.next_id = 1
        self.dead = set()

    def create(self):
        eid = self.next_id
        self.next_id += 1
        return eid

    def destroy(self, eid):
        self.dead.add(eid)

    def cleanup(self, world):
        for eid in sorted(self.dead):
            world.remove_entity(eid)
        self.dead.clear()