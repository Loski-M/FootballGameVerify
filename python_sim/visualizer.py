from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from python_sim.config import MatchConfig
from python_sim.models import FrameSnapshot, MatchState


class MatchReplayViewer:
    def __init__(self, match: MatchState, config: MatchConfig) -> None:
        self.match = match
        self.config = config
        self.frames = match.frames
        self.index = 0
        self.playing = False
        self._slider_updating = False

        self.root = tk.Tk()
        self.root.title("Futsal Python Replay Viewer")

        self.scale = 18
        self.margin = 24
        self.pitch_w = int(config.pitch_width * self.scale)
        self.pitch_h = int(config.pitch_height * self.scale)
        canvas_w = self.pitch_w + self.margin * 2
        canvas_h = self.pitch_h + self.margin * 2

        self.canvas = tk.Canvas(self.root, width=canvas_w, height=canvas_h, bg="#0b5f2a", highlightthickness=0)
        self.canvas.grid(row=0, column=0, rowspan=3, padx=8, pady=8)

        side = ttk.Frame(self.root)
        side.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)

        self.info_var = tk.StringVar()
        self.event_var = tk.StringVar()
        self.players_var = tk.StringVar()

        ttk.Label(side, text="Match Info").grid(row=0, column=0, sticky="w")
        ttk.Label(side, textvariable=self.info_var, justify="left").grid(row=1, column=0, sticky="w", pady=(0, 10))

        ttk.Label(side, text="Latest Event").grid(row=2, column=0, sticky="w")
        ttk.Label(side, textvariable=self.event_var, justify="left", wraplength=320).grid(row=3, column=0, sticky="w", pady=(0, 10))

        ttk.Label(side, text="Players").grid(row=4, column=0, sticky="w")
        ttk.Label(side, textvariable=self.players_var, justify="left", wraplength=340).grid(row=5, column=0, sticky="w")

        controls = ttk.Frame(self.root)
        controls.grid(row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        controls.columnconfigure(3, weight=1)

        ttk.Button(controls, text="Prev", command=self.prev_frame).grid(row=0, column=0, padx=4)
        self.play_button = ttk.Button(controls, text="Play", command=self.toggle_play)
        self.play_button.grid(row=0, column=1, padx=4)
        ttk.Button(controls, text="Next", command=self.next_frame).grid(row=0, column=2, padx=4)

        self.slider = ttk.Scale(
            controls,
            from_=0,
            to=max(0, len(self.frames) - 1),
            orient="horizontal",
            command=self.on_slider,
        )
        self.slider.grid(row=0, column=3, sticky="ew", padx=8)

        self.frame_label = ttk.Label(controls, text="")
        self.frame_label.grid(row=0, column=4, padx=4)

        self.draw_static_pitch()
        self.render_frame(0, update_slider=False)

    def draw_static_pitch(self) -> None:
        m = self.margin
        w = self.pitch_w
        h = self.pitch_h
        self.canvas.create_rectangle(m, m, m + w, m + h, outline="white", width=2)
        self.canvas.create_line(m + w / 2, m, m + w / 2, m + h, fill="white", width=2)
        self.canvas.create_oval(m + w / 2 - 36, m + h / 2 - 36, m + w / 2 + 36, m + h / 2 + 36, outline="white")
        goal_h = self.config.goal_width * self.scale
        gy1 = m + h / 2 - goal_h / 2
        gy2 = m + h / 2 + goal_h / 2
        self.canvas.create_rectangle(m - 8, gy1, m, gy2, outline="white")
        self.canvas.create_rectangle(m + w, gy1, m + w + 8, gy2, outline="white")

    def world_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return self.margin + x * self.scale, self.margin + y * self.scale

    def render_frame(self, index: int, update_slider: bool = True) -> None:
        if not self.frames:
            return
        self.index = max(0, min(index, len(self.frames) - 1))
        frame = self.frames[self.index]
        if update_slider:
            self._slider_updating = True
            try:
                self.slider.set(self.index)
            finally:
                self._slider_updating = False
        self.canvas.delete("dynamic")

        bx, by = self.world_to_canvas(frame.ball.x, frame.ball.y)
        self.canvas.create_oval(bx - 4, by - 4, bx + 4, by + 4, fill="#ffd54a", outline="black", tags="dynamic")

        for player in frame.players:
            px, py = self.world_to_canvas(player.x, player.y)
            color = "#3498db" if player.team_id == "A" else "#e74c3c"
            outline = "#f1c40f" if player.has_ball else "white"
            tx, ty = self.world_to_canvas(player.target_x, player.target_y)
            self.canvas.create_line(px, py, tx, ty, fill="#b2dfdb", dash=(2, 2), tags="dynamic")
            if player.intercept_x is not None and player.intercept_y is not None:
                ix, iy = self.world_to_canvas(player.intercept_x, player.intercept_y)
                mode_color = {
                    "come_short": "#ffd166",
                    "meet_ball": "#06d6a0",
                    "run_onto": "#ef476f",
                }.get(player.receive_mode.value, "#ffffff")
                self.canvas.create_oval(ix - 4, iy - 4, ix + 4, iy + 4, outline=mode_color, width=2, tags="dynamic")
                self.canvas.create_line(px, py, ix, iy, fill=mode_color, dash=(3, 2), tags="dynamic")
            self.canvas.create_oval(px - 9, py - 9, px + 9, py + 9, fill=color, outline=outline, width=2, tags="dynamic")
            fx = px + math.cos(player.facing_angle) * 14
            fy = py + math.sin(player.facing_angle) * 14
            self.canvas.create_line(px, py, fx, fy, fill="#ffeb3b", width=2, arrow="last", tags="dynamic")
            self.canvas.create_text(px, py - 14, text=player.name.split("_")[-1], fill="white", font=("Arial", 8), tags="dynamic")
            action_text = player.action.value if player.receive_mode.value == "none" else f"{player.action.value}/{player.receive_mode.value}"
            self.canvas.create_text(px, py + 15, text=action_text, fill="#e8f5e9", font=("Arial", 7), tags="dynamic")

        team_info = " | ".join(f"{team.name}: {team.phase.value}" for team in frame.teams)
        owner = frame.ball.owner_player_id or "free ball"
        self.info_var.set(
            f"time: {frame.time_seconds:5.1f}s\n"
            f"ball owner: {owner}\n"
            f"phases: {team_info}"
        )
        self.event_var.set(frame.latest_event or "(no event)")

        player_lines = []
        for player in sorted(frame.players, key=lambda p: (p.team_id, p.role.value)):
            player_lines.append(
                f"{player.team_id} {player.name}: ({player.x:4.1f}, {player.y:4.1f}) "
                f"{player.action.value}/{player.receive_mode.value} face={player.facing_angle:5.2f} "
                f"stam={player.stamina:.2f}"
            )
        self.players_var.set("\n".join(player_lines))
        self.frame_label.config(text=f"{self.index + 1}/{len(self.frames)}")

    def prev_frame(self) -> None:
        self.render_frame(self.index - 1)

    def next_frame(self) -> None:
        self.render_frame(self.index + 1)

    def toggle_play(self) -> None:
        self.playing = not self.playing
        self.play_button.config(text="Pause" if self.playing else "Play")
        if self.playing:
            self.play_step()

    def play_step(self) -> None:
        if not self.playing:
            return
        if self.index >= len(self.frames) - 1:
            self.playing = False
            self.play_button.config(text="Play")
            return
        self.render_frame(self.index + 1)
        delay_ms = max(40, int(self.config.tick_seconds * 1000))
        self.root.after(delay_ms, self.play_step)

    def on_slider(self, value: str) -> None:
        if self._slider_updating:
            return
        self.render_frame(int(float(value)), update_slider=False)

    def show(self) -> None:
        self.root.mainloop()


def show_match_replay(match: MatchState, config: MatchConfig) -> None:
    viewer = MatchReplayViewer(match, config)
    viewer.show()
