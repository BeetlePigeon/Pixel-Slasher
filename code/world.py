class World:
    def __init__(self, game, entities):
        self.game = game
        self.entities = entities

        # Camera
        self.camera_offset = (400, 100)

        # Components
        self.position = {}
        self.velocity = {}
        self.sprite = {}
        self.intent = {}
        self.skills = {}
        self.input_controlled = {}
        self.active_skill = {}

        # Tiles
        self.tile_size = 32
        self.tile_images = {
            0: self.game.assets.images["block"],
            1: self.game.assets.images["water"]
        }

        self.tilemap = [
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        ]

        # Spawn initial entities
        self.player = self.spawn_player()

    def spawn_player(self):
        eid = self.entities.create()

        self.position[eid] = [5.0, 5.0]
        self.velocity[eid] = [0.0, 0.0]

        self.input_controlled[eid] = True

        self.sprite[eid] = {
            "image": self.game.assets.images["player"],
            "offset": (0, 0),
            "z": 0
        }

        self.active_skill[eid] = None

        return eid