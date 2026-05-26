import pygame
from status_ops import apply_status_effect
from combat_ops import queue_damage_request
from camera_utils import set_camera_follow, set_camera_fixed, start_camera_shake
from world import World


class Debug:
    def __init__(self, game):
        self.game = game
        self.debug_frame_ms_history = []
        self.debug_sim_ticks_history = []
        self.debug_frame_history_max = 180


    def draw_debug_overlay(self):
        statuses = self.game.world.status_effects.get(self.game.world.player, {})
        stun = True if statuses.get("debug_stun") else False
        freeze = True if statuses.get("debug_freeze") else False
        lines = [
#            f"FPS: {self.game.fps:.1f}",
#            f"Entities next_id: {self.game.entities.next_id}",
#            f"Transforms: {len(self.game.world.transform)}",
            f"MotionState: {len(self.game.world.motion_state)}",
            f"Sprites: {len(self.game.world.sprite)}",
#            f"Projectiles: {len(self.game.world.projectile)}",
#            f"Emitters: {len(self.game.world.influence_emitter)}",
#            f"Receivers: {len(self.game.world.influence_receiver)}",
#            f"Lifetime: {len(self.game.world.lifetime)}",
            f"Display: {self.game.display.display_mode}",
            f"Scale: {self.game.display.scale}x",
            f"Windowed scale: {self.game.display.windowed_scale}x",
            f"VSync: {'on' if self.game.display.vsync_enabled else 'off'}",
            f"FPS cap: {'uncapped' if self.game.display.fps_cap == 0 else self.game.display.fps_cap}",
            f"Camera: {self.game.world.world_camera.camera['transition_mode']}",
            f"Controls: {self.game.world.control_scheme}",
            f"Move skill aim: {self.game.world.gameplay_settings['modern_movement_skill_aim_source']}",
#            f"Animations: {len(self.game.world.animation)}",
            f"Action State: {self.game.world.action_state}",
            f"Ticks: {self.game.world.tick}",
            f"Statuses: {len(statuses)}",
            f"Stun: {stun}",
            f"Freeze: {freeze}",
            (
                f"Zoom: "
                f"{self.game.world.world_camera.camera['zoom_current_fp'] / 1024:.2f}x "
                f"-> {self.game.world.world_camera.camera['zoom_target_num']}/"
                f"{self.game.world.world_camera.camera['zoom_target_den']} "
                f"({'smooth' if self.game.world.world_camera.camera['zoom_smooth'] else 'snap'})"
            ),
        ]
        y = 4

        for line in lines:
            text_surface = self.game.display.debug_font.render(line, False, "white")
            self.game.display.render_surface.blit(text_surface, (4, y))
            y += 14


    def get_first_enemy_entity(self):
        world = self.game.world

        for entity in sorted(world.team):
            if world.team.get(entity) == "enemy":
                return entity

        return None



    def toggle_control_scheme(self):
        world = self.game.world

        if world.control_scheme == "modern":
            world.control_scheme = "traditional"
        else:
            world.control_scheme = "modern"



    def process_top_level_debug_input(self, input_state):
        if pygame.K_F3 in input_state.keys_pressed:
            self.game.reload_skill_defs()
        if pygame.K_F4 in input_state.keys_pressed:
            current_area = self.game.world.current_area.area_id
            if current_area == "test_start_area":
                self.game.world.load_area("test_dungeon", "default")
            else:
                self.game.world.load_area("test_start_area", "default")
            print(current_area)
        if pygame.K_F5 in input_state.keys_pressed:
            self.game.display.cycle_windowed_scale()
        if pygame.K_F6 in input_state.keys_pressed:
            self.game.display.toggle_vsync()
        if pygame.K_F7 in input_state.keys_pressed:
            self.game.display.cycle_fps_cap()
        if pygame.K_F12 in input_state.keys_pressed:
            self.game.display.cycle_display_mode()
        if pygame.K_F10 in input_state.keys_pressed:
            self.game.display.zoom_camera_out()
        if pygame.K_F11 in input_state.keys_pressed:
            self.game.display.zoom_camera_in()


    def process_gamestate_debug_inputs(self, input_state):
        if pygame.K_F8 in input_state.keys_pressed:
            self.toggle_control_scheme()

        if pygame.K_F9 in input_state.keys_pressed:
            settings = self.game.world.gameplay_settings

            current = settings["modern_movement_skill_aim_source"]

            if current == "facing":
                settings["modern_movement_skill_aim_source"] = "mouse"
            else:
                settings["modern_movement_skill_aim_source"] = "facing"

        if pygame.K_LSHIFT in input_state.keys_pressed:
            camera = self.game.world.world_camera.camera

            if camera["mode"] == "follow":
                player = self.game.world.player
                fixed_cpos = self.game.world.transform[player].cpos
                set_camera_fixed(self.game.world, fixed_cpos, transition_mode="snap")
            else:
                set_camera_follow(self.game.world, self.game.world.player, transition_mode="smooth", transition_duration=26)

        if pygame.K_v in input_state.keys_pressed:
            start_camera_shake(
                self.game.world,
                duration_ticks=18,
                strength=4,
            )

        if pygame.K_b in input_state.keys_pressed:
            apply_status_effect(
                self.game.world,
                self.game.world.player,
                "debug_stun",
                tags={
                    "stun",
                    "movement_locked",
                    "skill_locked",
                },
                duration=90,
                cancels_action_tags={
                    "cast",
                    "channel",
                    "recovery",
                },
                cancels_motion_tags={
                    "dash",
                    "directional_move",
                    "path_follow",
                },
            )

        if pygame.K_n in input_state.keys_pressed:
            apply_status_effect(
                self.game.world,
                self.game.world.player,
                "debug_freeze",
                tags={
                    "freeze",
                    "movement_locked",
                    "skill_locked",
                    "settle_locked",
                },
                duration=90,
                pauses_action_tags={
                    "cast",
                    "recovery",
                },
                cancels_action_tags={
                    "channel",
                },
                cancels_motion_tags={
                    "dash",
                    "directional_move",
                    "path_follow",
                    "settle",
                },
            )

        if pygame.K_h in input_state.keys_pressed:
            attacker = self.get_first_enemy_entity()

            if attacker is not None:
                queue_damage_request(
                    self.game.world,
                    source=attacker,
                    target=self.game.world.player,
                    amount=1,
                    skill_id="debug_enemy_hit",
                )


    def record_debug_frame_sample(self, raw_frame_dt, sim_ticks_this_frame):
        frame_ms = raw_frame_dt * 1000.0

        self.debug_frame_ms_history.append(frame_ms)
        self.debug_sim_ticks_history.append(sim_ticks_this_frame)

        if len(self.debug_frame_ms_history) > self.debug_frame_history_max:
            self.debug_frame_ms_history.pop(0)

        if len(self.debug_sim_ticks_history) > self.debug_frame_history_max:
            self.debug_sim_ticks_history.pop(0)


    def draw_debug_frame_graph(self):
        history = self.debug_frame_ms_history

        if not history:
            return

        graph_x = 4
        graph_y = self.game.display.internal_height - 64
        graph_w = min(180, self.game.display.internal_width - 8)
        graph_h = 44

        pygame.draw.rect(
            self.game.display.render_surface,
            "black",
            (graph_x - 1, graph_y - 1, graph_w + 2, graph_h + 16),
        )

        pygame.draw.rect(
            self.game.display.render_surface,
            "white",
            (graph_x, graph_y, graph_w, graph_h),
            1,
        )

        # Reference lines:
        # 16.67 ms = 60 FPS
        # 33.33 ms = 30 FPS
        max_ms = 50.0

        def ms_to_y(ms):
            clamped = min(max_ms, max(0.0, ms))
            return graph_y + graph_h - int((clamped / max_ms) * graph_h)

        y_60 = ms_to_y(1000.0 / 60.0)
        y_30 = ms_to_y(1000.0 / 30.0)

        pygame.draw.line(
            self.game.display.render_surface,
            "gray",
            (graph_x, y_60),
            (graph_x + graph_w, y_60),
            1,
        )

        pygame.draw.line(
            self.game.display.render_surface,
            "gray",
            (graph_x, y_30),
            (graph_x + graph_w, y_30),
            1,
        )

        start_index = max(0, len(history) - graph_w)

        for i, frame_ms in enumerate(history[start_index:]):
            x = graph_x + i
            y = ms_to_y(frame_ms)

            color = "green"

            if frame_ms > 33.33:
                color = "red"
            elif frame_ms > 16.67:
                color = "yellow"

            pygame.draw.line(
                self.game.display.render_surface,
                color,
                (x, graph_y + graph_h - 1),
                (x, y),
                1,
            )

        latest_ms = history[-1]
        worst_ms = max(history)
        latest_ticks = (
            self.debug_sim_ticks_history[-1]
            if self.debug_sim_ticks_history
            else 0
        )

        label = (
            f"Frame ms: {latest_ms:.1f} | "
            f"Peak: {worst_ms:.1f} | "
            f"Sim ticks: {latest_ticks}"
        )

        text_surface = self.game.display.debug_font.render(
            label,
            False,
            "white",
        )

        self.game.display.render_surface.blit(
            text_surface,
            (graph_x, graph_y + graph_h + 3),
        )


    def add_debug_tile_highlight(self,
        world,
        tile,
        duration_ticks=12,
        color="yellow",
    ):
        world.debug_tile_highlights.append({
            "tile": tile,
            "remaining_ticks": duration_ticks,
            "color": color,
        })


    def debug_tile_highlight_system(self, world):
        active_highlights = []

        for highlight in world.debug_tile_highlights:
            highlight["remaining_ticks"] -= 1

            if highlight["remaining_ticks"] > 0:
                active_highlights.append(highlight)

        world.debug_tile_highlights = active_highlights