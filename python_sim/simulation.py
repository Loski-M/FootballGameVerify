from __future__ import annotations

import math
from .models import Role
import random

from python_sim.ai import angle_to, clamp, decide_all_players, distance, get_owner_player, normalize_angle, role_home_position, update_team_phase
from python_sim.config import MatchConfig
from python_sim.models import (
    BallSnapshot,
    BallState,
    FrameSnapshot,
    MatchEvent,
    MatchState,
    PassType,
    Player,
    PlayerAction,
    PlayerSnapshot,
    Team,
    TeamSnapshot,
)


class MatchSimulator:
    def __init__(self, config: MatchConfig, rng_seed: int = 7) -> None:
        self.config = config
        self.rng = random.Random(rng_seed)

    def run(self, match: MatchState) -> MatchState:
        self._log(match, "Kickoff")
        self._record_frame(match)
        while match.time_seconds < self.config.match_duration_seconds:
            self._tick(match)
            self._record_frame(match)
        self._log(match, "Full time")
        self._record_frame(match)
        return match

    def _tick(self, match: MatchState) -> None:
        for team in match.teams:
            update_team_phase(match, team, self.config)
        for team in match.teams:
            decide_all_players(match, team, self.config, self.rng)
        if match.dead_ball:
            self._handle_restart(match)
        else:
            self._resolve_owner_action(match)
            self._move_off_ball_players(match)
            self._move_free_ball(match)
            self._resolve_loose_ball(match)
        self._update_facing(match)
        self._apply_separation(match)
        self._update_stamina(match)
        self._update_possession_stats(match)
        match.time_seconds += self.config.tick_seconds

    def _resolve_owner_action(self, match: MatchState) -> None:
        owner = get_owner_player(match)
        if owner is None:
            return
        intent = owner.state.intent
        if intent.action == PlayerAction.PASS and intent.target_player_id:
            self._execute_pass(match, owner, intent.target_player_id)
        elif intent.action == PlayerAction.SHOOT:
            self._execute_shot(match, owner)
        else:
            self._execute_dribble(match, owner)

    def _execute_dribble(self, match: MatchState, owner: Player) -> None:
        old_x, old_y = owner.state.x, owner.state.y
        step = owner.derived.move_speed * self.config.tick_seconds * (0.9 + owner.state.stamina * 0.2)
        target_x = owner.state.intent.target_x
        target_y = owner.state.intent.target_y
        dx = target_x - owner.state.x
        dy = target_y - owner.state.y
        dist = math.hypot(dx, dy)
        if dist > 0.01:
            owner.state.x += dx / dist * min(step, dist)
            owner.state.y += dy / dist * min(step, dist)
            owner.state.target_facing_angle = angle_to(owner.state.x, owner.state.y, target_x, target_y)
        owner.state.x = clamp(owner.state.x, 0.0, self.config.pitch_width)
        owner.state.y = clamp(owner.state.y, 0.0, self.config.pitch_height)
        owner.state.vx = (owner.state.x - old_x) / self.config.tick_seconds
        owner.state.vy = (owner.state.y - old_y) / self.config.tick_seconds
        match.ball.x = owner.state.x
        match.ball.y = owner.state.y
        match.ball.vx = 0.0
        match.ball.vy = 0.0
        match.ball.last_touch_team_id = owner.team_id
        match.ball.last_touch_player_id = owner.player_id
        match.ball.last_touch_action = PlayerAction.DRIBBLE
        match.restart_reason = ""
        self._maybe_tackle_owner(match, owner)

    def _execute_pass(self, match: MatchState, owner: Player, target_player_id: str) -> None:
        target = self._find_player(match, target_player_id)
        if target is None:
            self._execute_dribble(match, owner)
            return
        team_stats = match.stats[owner.team_id]
        team_stats.passes_attempted += 1

        desired_x, desired_y = self._resolve_pass_target(owner, target, match)

        speed = owner.state.intent.pass_speed if owner.state.intent.pass_speed > 0 else self.config.pass_speed

        desired_angle = angle_to(owner.state.x, owner.state.y, desired_x, desired_y)
        facing_gap = abs(normalize_angle(desired_angle - owner.state.facing_angle)) / math.pi

        quality = owner.derived.pass_quality / 100.0
        dist_m = math.hypot(desired_x - owner.state.x, desired_y - owner.state.y)
        speed_factor = clamp(
            (speed - self.config.pass_speed_min) / max(1.0, self.config.pass_speed_max - self.config.pass_speed_min),
            0.0, 1.0,
        )

        error_std = (
            self.config.pass_error_base
            + (1.0 - quality) * self.config.pass_error_quality_factor
            + dist_m * self.config.pass_error_distance_per_m
            + speed_factor * self.config.pass_error_speed_factor
            + facing_gap * self.config.pass_error_facing_factor
        )
        error_std = max(self.config.pass_error_base, error_std)

        u1 = self.rng.uniform(0.001, 0.999)
        u2 = self.rng.uniform(0.001, 0.999)
        gauss_x = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        gauss_y = math.sqrt(-2.0 * math.log(u1)) * math.sin(2.0 * math.pi * u2)

        tx = clamp(desired_x + gauss_x * error_std, 0.5, self.config.pitch_width - 0.5)
        ty = clamp(desired_y + gauss_y * error_std, 0.5, self.config.pitch_height - 0.5)

        dx = tx - owner.state.x
        dy = ty - owner.state.y
        dist = math.hypot(dx, dy) or 1.0
        match.ball.owner_player_id = None
        match.ball.owner_team_id = None
        owner.state.has_ball = False
        owner.state.target_facing_angle = angle_to(owner.state.x, owner.state.y, tx, ty)
        match.ball.vx = dx / dist * speed
        match.ball.vy = dy / dist * speed
        match.ball.last_touch_team_id = owner.team_id
        match.ball.last_touch_player_id = owner.player_id
        match.ball.last_touch_action = PlayerAction.PASS
        match.restart_reason = ""
        match.passer_player_id = owner.player_id
        match.receiver_player_id = target_player_id
        pass_suffix = f" ({owner.state.intent.pass_type.value})" if owner.state.intent.pass_type else ""
        self._log(match, f"{owner.name} attempts a pass to {target.name}{pass_suffix}")

    def _clear_pass_intent(self, match: MatchState) -> None:
        match.passer_player_id = None
        match.receiver_player_id = None

    def _execute_shot(self, match: MatchState, owner: Player) -> None:
        team_stats = match.stats[owner.team_id]
        team_stats.shots += 1
        
        # Determine target corner (far post relative to owner's y)
        goal_x = self.config.pitch_width if self._team_by_id(match, owner.team_id).attack_direction == 1 else 0.0
        half_h = self.config.pitch_height / 2
        aim_y = half_h + self.config.goal_width / 2 - 0.5 if owner.state.y < half_h else half_h - self.config.goal_width / 2 + 0.5
        
        desired_angle = angle_to(owner.state.x, owner.state.y, goal_x, aim_y)
        facing_gap = abs(normalize_angle(desired_angle - owner.state.facing_angle)) / math.pi
        
        # Calculate error margin based on quality and facing
        error_margin = (max(0.15, 1.0 - owner.derived.shot_quality / 100.0) + facing_gap * 0.7) * 3.0
        goal_y = aim_y + self.rng.uniform(-error_margin, error_margin)
        
        dx = goal_x - owner.state.x
        dy = goal_y - owner.state.y
        dist = math.hypot(dx, dy) or 1.0
        match.ball.owner_player_id = None
        match.ball.owner_team_id = None
        owner.state.has_ball = False
        owner.state.target_facing_angle = angle_to(owner.state.x, owner.state.y, goal_x, goal_y)
        match.ball.vx = dx / dist * self.config.shot_speed
        match.ball.vy = dy / dist * self.config.shot_speed
        match.ball.last_touch_team_id = owner.team_id
        match.ball.last_touch_player_id = owner.player_id
        match.ball.last_touch_action = PlayerAction.SHOOT
        match.restart_reason = ""
        self._log(match, f"{owner.name} shoots")

    def _move_off_ball_players(self, match: MatchState) -> None:
        owner = get_owner_player(match)
        for team in match.teams:
            for player in team.players:
                if owner and owner.player_id == player.player_id:
                    continue
                old_x, old_y = player.state.x, player.state.y
                intent = player.state.intent
                speed_factor = 1.0 if intent.action != PlayerAction.RECOVER else 0.92
                speed = player.derived.move_speed * player.state.stamina * self.config.tick_seconds * speed_factor
                dx = intent.target_x - player.state.x
                dy = intent.target_y - player.state.y
                dist = math.hypot(dx, dy)
                if dist > 0.05:
                    step = min(speed, dist)
                    player.state.x += dx / dist * step
                    player.state.y += dy / dist * step
                    player.state.target_facing_angle = angle_to(player.state.x, player.state.y, intent.target_x, intent.target_y)
                player.state.x = clamp(player.state.x, 0.0, self.config.pitch_width)
                player.state.y = clamp(player.state.y, 0.0, self.config.pitch_height)
                player.state.vx = (player.state.x - old_x) / self.config.tick_seconds
                player.state.vy = (player.state.y - old_y) / self.config.tick_seconds
                if player.state.intercept_x is not None and distance(player.state.x, player.state.y, player.state.intercept_x, player.state.intercept_y) < 0.8:
                    player.state.intercept_locked_until = max(player.state.intercept_locked_until, match.time_seconds + 0.2)

    def _move_free_ball(self, match: MatchState) -> None:
        if match.ball.owner_player_id is not None:
            return
        match.ball.x += match.ball.vx * self.config.tick_seconds
        match.ball.y += match.ball.vy * self.config.tick_seconds
        # Uniform deceleration: reduce speed linearly each tick
        speed = math.hypot(match.ball.vx, match.ball.vy)
        if speed > 0.0:
            decel = self.config.ball_deceleration * self.config.tick_seconds
            if speed <= decel:
                match.ball.vx = 0.0
                match.ball.vy = 0.0
            else:
                factor = (speed - decel) / speed
                match.ball.vx *= factor
                match.ball.vy *= factor

        if match.ball.y < 0.0 or match.ball.y > self.config.pitch_height:
            self._set_throw_in(match)
            return

        if self._try_goalkeeper_save(match):
            return

        goal = self._check_goal(match)
        if goal:
            self._handle_goal(match, goal)
            return

        if match.ball.x < 0.0 or match.ball.x > self.config.pitch_width:
            self._set_goal_line_restart(match)
            return

    def _resolve_loose_ball(self, match: MatchState) -> None:
        if match.ball.owner_player_id is not None:
            return
        candidates: list[tuple[float, Player]] = []
        for team in match.teams:
            for player in team.players:
                d = distance(player.state.x, player.state.y, match.ball.x, match.ball.y)
                if d <= self.config.ball_control_radius:
                    candidates.append((d - player.derived.ball_control * 0.002, player))
        if not candidates:
            return
        candidates.sort(key=lambda item: item[0])
        player = candidates[0][1]
        match.ball.owner_player_id = player.player_id
        match.ball.owner_team_id = player.team_id
        player.state.has_ball = True
        self._clear_pass_intent(match)
        player.state.intercept_x = None
        player.state.intercept_y = None
        player.state.intercept_locked_until = 0.0
        for team in match.teams:
            if team.team_id == player.team_id:
                team.state.last_gain_time = match.time_seconds
        if (
            match.ball.last_touch_action == PlayerAction.PASS
            and match.ball.last_touch_team_id == player.team_id
        ):
            match.stats[player.team_id].passes_completed += 1
        player.state.target_facing_angle = angle_to(player.state.x, player.state.y, self._opponent_goal_x(match, player.team_id), self.config.pitch_height / 2)
        self._log(match, f"{player.name} controls the ball")

    def _maybe_tackle_owner(self, match: MatchState, owner: Player) -> None:
        opponents = [p for t in match.teams if t.team_id != owner.team_id for p in t.players]
        for opponent in opponents:
            d = distance(owner.state.x, owner.state.y, opponent.state.x, opponent.state.y)
            if d > self.config.tackle_radius:
                continue
            tackle_score = opponent.derived.press_quality * opponent.state.stamina
            resist_score = owner.derived.ball_control * owner.state.stamina
            if tackle_score + self.rng.uniform(-8, 8) > resist_score + 6:
                match.ball.owner_player_id = opponent.player_id
                match.ball.owner_team_id = opponent.team_id
                owner.state.has_ball = False
                opponent.state.has_ball = True
                opponent.state.intercept_x = None
                opponent.state.intercept_y = None
                opponent.state.intercept_locked_until = 0.0
                match.ball.x = opponent.state.x
                match.ball.y = opponent.state.y
                match.ball.vx = 0.0
                match.ball.vy = 0.0
                match.ball.last_touch_team_id = opponent.team_id
                match.ball.last_touch_player_id = opponent.player_id
                match.ball.last_touch_action = None
                match.stats[opponent.team_id].tackles_won += 1
                self._team_by_id(match, opponent.team_id).state.last_gain_time = match.time_seconds
                self._clear_pass_intent(match)
                self._log(match, f"{opponent.name} wins the ball from {owner.name}")
                return

    def _check_goal(self, match: MatchState) -> str | None:
        goal_min = self.config.pitch_height / 2 - self.config.goal_width / 2
        goal_max = self.config.pitch_height / 2 + self.config.goal_width / 2
        if goal_min <= match.ball.y <= goal_max:
            if match.ball.x <= 0.0:
                return "B"
            if match.ball.x >= self.config.pitch_width:
                return "A"
        return None

    def _handle_goal(self, match: MatchState, scoring_team_id: str) -> None:
        self._clear_pass_intent(match)
        match.stats[scoring_team_id].goals += 1
        if (
            match.ball.last_touch_action == PlayerAction.SHOOT
            and match.ball.last_touch_team_id == scoring_team_id
        ):
            match.stats[scoring_team_id].shots_on_target += 1
        self._log(match, f"GOAL for {self._team_by_id(match, scoring_team_id).name}")
        self._reset_after_goal(match, kickoff_team_id="A" if scoring_team_id == "B" else "B")

    def _reset_after_goal(self, match: MatchState, kickoff_team_id: str) -> None:
        half_h = self.config.pitch_height / 2
        for team in match.teams:
            for player in team.players:
                player.state.has_ball = False
                player.state.decision_cooldown = 0.0
                player.state.intercept_x = None
                player.state.intercept_y = None
                player.state.intercept_locked_until = 0.0
                player.state.vx = 0.0
                player.state.vy = 0.0
                # Teleport both teams to defensive home positions (kickoff formation)
                home_x, home_y = role_home_position(team, player.role, self.config, attacking=False)
                player.state.x = home_x
                player.state.y = home_y
                # Both teams face opponent goal
                player.state.facing_angle = 0.0 if team.attack_direction == 1 else math.pi
                player.state.target_facing_angle = player.state.facing_angle

        match.ball = BallState(
            x=self.config.pitch_width / 2,
            y=half_h,
            owner_team_id=None,
            owner_player_id=None,
            last_touch_team_id=None,
            last_touch_player_id=None,
        )
        match.dead_ball = True
        match.restart_team_id = kickoff_team_id
        match.restart_reason = "Kickoff"
        self._team_by_id(match, kickoff_team_id).state.last_gain_time = match.time_seconds

    def _update_stamina(self, match: MatchState) -> None:
        for team in match.teams:
            has_ball = match.ball.owner_team_id == team.team_id
            for player in team.players:
                intense = player.state.intent.action in (PlayerAction.PRESS, PlayerAction.DRIBBLE, PlayerAction.SHOOT)
                decay = self.config.fatigue_decay_per_second * self.config.tick_seconds * (1.2 if intense else 1.0)
                if not intense and not has_ball:
                    decay -= self.config.recovery_decay_per_second * self.config.tick_seconds
                player.state.stamina = clamp(player.state.stamina - decay, 0.55, 1.0)

    def _update_possession_stats(self, match: MatchState) -> None:
        if match.ball.owner_team_id:
            match.stats[match.ball.owner_team_id].possession_seconds += self.config.tick_seconds

    def _team_by_id(self, match: MatchState, team_id: str) -> Team:
        for team in match.teams:
            if team.team_id == team_id:
                return team
        raise ValueError(f"Unknown team id: {team_id}")

    def _find_player(self, match: MatchState, player_id: str) -> Player | None:
        for team in match.teams:
            for player in team.players:
                if player.player_id == player_id:
                    return player
        return None

    def _log(self, match: MatchState, message: str) -> None:
        match.events.append(MatchEvent(time_seconds=match.time_seconds, message=message))

    def _try_goalkeeper_save(self, match: MatchState) -> bool:
        if match.ball.last_touch_action != PlayerAction.SHOOT:
            return False
        defending_team_id = "A" if match.ball.vx < 0 else "B"
        team = self._team_by_id(match, defending_team_id)
        keeper = next(player for player in team.players if player.role.name == "GK")
        goal_x = 0.0 if defending_team_id == "A" else self.config.pitch_width
        if abs(match.ball.x - goal_x) > 2.2:
            return False
        if abs(match.ball.y - self.config.pitch_height / 2) > self.config.goal_width / 2 + 1.0:
            return False
        save_chance = clamp(0.35 + keeper.derived.save_quality / 200.0, 0.35, 0.88)
        if self.rng.random() > save_chance:
            return False
        shooting_team_id = "A" if defending_team_id == "B" else "B"
        match.stats[shooting_team_id].shots_on_target += 1
        match.ball.owner_player_id = keeper.player_id
        match.ball.owner_team_id = keeper.team_id
        keeper.state.has_ball = True
        match.ball.x = keeper.state.x
        match.ball.y = keeper.state.y
        match.ball.vx = 0.0
        match.ball.vy = 0.0
        match.ball.last_touch_team_id = keeper.team_id
        match.ball.last_touch_player_id = keeper.player_id
        match.ball.last_touch_action = None
        self._clear_pass_intent(match)
        team.state.last_gain_time = match.time_seconds
        self._log(match, f"{keeper.name} saves the shot")
        return True

    def _handle_restart(self, match: MatchState) -> None:
        self._move_off_ball_players(match)
        
        # If it's a kickoff and ball has no owner, give it to a player near the center
        if match.restart_reason == "Kickoff" and match.ball.owner_player_id is None and match.restart_team_id:
            team = self._team_by_id(match, match.restart_team_id)
            # Find closest player (except GK)
            candidates = sorted([p for p in team.players if p.role != Role.GK], key=lambda p: distance(p.state.x, p.state.y, match.ball.x, match.ball.y))
            taker = candidates[0]
            taker.state.x = match.ball.x - 0.5 if team.attack_direction == 1 else match.ball.x + 0.5
            taker.state.y = match.ball.y
            taker.state.has_ball = True
            taker.state.decision_cooldown = 10.0
            
            match.ball.owner_player_id = taker.player_id
            match.ball.owner_team_id = taker.team_id
            
        if match.ball.owner_player_id is None:
            return
            
        taker = self._find_player(match, match.ball.owner_player_id)
        if taker is None:
            return
        taker.state.has_ball = True
        match.ball.x = taker.state.x
        match.ball.y = taker.state.y
        match.ball.vx = 0.0
        match.ball.vy = 0.0
        # Let restart settle for one tick, then resume normal play.
        if taker.state.decision_cooldown <= 0.0:
            match.dead_ball = False
            # We keep restart_reason for one active tick so the AI knows it's a kickoff explicitly
            # It will clear when a pass/action sets last_touch_action

    def _set_throw_in(self, match: MatchState) -> None:
        restart_team = "A" if match.ball.last_touch_team_id == "B" else "B"
        x = clamp(match.ball.x, 1.0, self.config.pitch_width - 1.0)
        y = 0.0 if match.ball.y < 0 else self.config.pitch_height
        self._setup_restart(match, restart_team, x, y, "ThrowIn")

    def _set_goal_line_restart(self, match: MatchState) -> None:
        goal_min = self.config.pitch_height / 2 - self.config.goal_width / 2
        goal_max = self.config.pitch_height / 2 + self.config.goal_width / 2
        if goal_min <= match.ball.y <= goal_max:
            return
            
        y_corner = 0.5 if match.ball.y < self.config.pitch_height / 2 else self.config.pitch_height - 0.5
        
        if match.ball.x < 0.0:
            defending_team = "A"
            attacking_team = "B"
            if match.ball.last_touch_team_id == defending_team:
                self._setup_restart(match, attacking_team, 0.5, y_corner, "Corner")
            else:
                self._setup_restart(match, defending_team, 3.0, self.config.pitch_height / 2, "GoalKick")
        else:
            defending_team = "B"
            attacking_team = "A"
            if match.ball.last_touch_team_id == defending_team:
                self._setup_restart(match, attacking_team, self.config.pitch_width - 0.5, y_corner, "Corner")
            else:
                self._setup_restart(match, defending_team, self.config.pitch_width - 3.0, self.config.pitch_height / 2, "GoalKick")

    def _setup_restart(self, match: MatchState, team_id: str, x: float, y: float, reason: str) -> None:
        self._clear_pass_intent(match)
        match.dead_ball = True
        match.restart_team_id = team_id
        match.restart_reason = reason
        taker = min(
            self._team_by_id(match, team_id).players,
            key=lambda player: distance(player.state.x, player.state.y, x, y),
        )
        for team in match.teams:
            for player in team.players:
                player.state.has_ball = False
                player.state.decision_cooldown = min(player.state.decision_cooldown, self.config.tick_seconds)
        taker.state.x = x
        taker.state.y = y
        taker.state.has_ball = True
        taker.state.decision_cooldown = 10.0 if reason == "Kickoff" else 5.0
        taker.state.target_facing_angle = angle_to(taker.state.x, taker.state.y, self._opponent_goal_x(match, team_id), self.config.pitch_height / 2)
        match.ball.owner_team_id = team_id
        match.ball.owner_player_id = taker.player_id
        match.ball.x = x
        match.ball.y = y
        match.ball.vx = 0.0
        match.ball.vy = 0.0
        match.ball.last_touch_action = None
        self._team_by_id(match, team_id).state.last_gain_time = match.time_seconds
        self._log(match, f"{reason} for {self._team_by_id(match, team_id).name}")

    def _update_facing(self, match: MatchState) -> None:
        for team in match.teams:
            for player in team.players:
                delta = normalize_angle(player.state.target_facing_angle - player.state.facing_angle)
                max_turn = player.derived.turn_rate * self.config.tick_seconds
                delta = clamp(delta, -max_turn, max_turn)
                player.state.facing_angle = normalize_angle(player.state.facing_angle + delta)

    def _apply_separation(self, match: MatchState) -> None:
        min_gap = self.config.player_radius * 2.2
        for team in match.teams:
            players = team.players
            for i in range(len(players)):
                for j in range(i + 1, len(players)):
                    a = players[i]
                    b = players[j]
                    dx = b.state.x - a.state.x
                    dy = b.state.y - a.state.y
                    dist = math.hypot(dx, dy)
                    if dist <= 0.001 or dist >= min_gap:
                        continue
                    push = (min_gap - dist) * 0.5
                    nx = dx / dist
                    ny = dy / dist
                    a.state.x = clamp(a.state.x - nx * push, 0.0, self.config.pitch_width)
                    a.state.y = clamp(a.state.y - ny * push, 0.0, self.config.pitch_height)
                    b.state.x = clamp(b.state.x + nx * push, 0.0, self.config.pitch_width)
                    b.state.y = clamp(b.state.y + ny * push, 0.0, self.config.pitch_height)

    def _opponent_goal_x(self, match: MatchState, team_id: str) -> float:
        team = self._team_by_id(match, team_id)
        return self.config.pitch_width if team.attack_direction == 1 else 0.0

    def _record_frame(self, match: MatchState) -> None:
        latest_event = match.events[-1].message if match.events else ""
        frame = FrameSnapshot(
            time_seconds=match.time_seconds,
            ball=BallSnapshot(
                x=match.ball.x,
                y=match.ball.y,
                owner_team_id=match.ball.owner_team_id,
                owner_player_id=match.ball.owner_player_id,
            ),
            teams=[
                TeamSnapshot(team_id=team.team_id, name=team.name, phase=team.state.phase)
                for team in match.teams
            ],
            players=[
                PlayerSnapshot(
                    player_id=player.player_id,
                    name=player.name,
                    team_id=player.team_id,
                    role=player.role,
                    x=player.state.x,
                    y=player.state.y,
                    has_ball=player.state.has_ball,
                    action=player.state.intent.action,
                    stamina=player.state.stamina,
                    facing_angle=player.state.facing_angle,
                    target_x=player.state.intent.target_x,
                    target_y=player.state.intent.target_y,
                    receive_mode=player.state.receive_mode,
                    intercept_x=player.state.intercept_x,
                    intercept_y=player.state.intercept_y,
                )
                for team in match.teams
                for player in team.players
            ],
            latest_event=latest_event if not match.dead_ball else f"{latest_event} [{match.restart_reason}]",
        )
        match.frames.append(frame)

    def _resolve_pass_target(self, owner: Player, target: Player, match: MatchState) -> tuple[float, float]:
        pass_type = owner.state.intent.pass_type
        if pass_type is None or pass_type == PassType.TO_FEET:
            return (target.state.x, target.state.y)

        ball_speed = owner.state.intent.pass_speed if owner.state.intent.pass_speed > 0 else self.config.pass_speed
        base_dist = math.hypot(target.state.x - owner.state.x, target.state.y - owner.state.y)

        # Flight time with uniform deceleration: d = v0*t - 0.5*a*t^2
        a = self.config.ball_deceleration
        max_reach = ball_speed * ball_speed / (2.0 * a)
        if base_dist >= max_reach:
            estimated_flight_time = ball_speed / a  # ball stops at max distance
        else:
            estimated_flight_time = (ball_speed - math.sqrt(ball_speed * ball_speed - 2.0 * a * base_dist)) / a

        receiver_speed = math.hypot(target.state.vx, target.state.vy)

        # Prediction quality: passer's attack_awareness affects lead time accuracy
        pred_quality = owner.attrs.attack_awareness / 100.0
        receiver_factor = self.config.lead_time_receiver_speed_factor * (0.5 + pred_quality * self.config.lead_prediction_quality_factor)

        lead_time = (
            self.config.lead_time_min
            + estimated_flight_time * self.config.lead_time_flight_fraction
            + receiver_speed * receiver_factor
        )

        if pass_type == PassType.THROUGH_PASS:
            lead_time += self.config.lead_time_through_extra

        predicted_x = target.state.x + target.state.vx * lead_time
        predicted_y = target.state.y + target.state.vy * lead_time

        if pass_type == PassType.THROUGH_PASS:
            owner_team = self._team_by_id(match, owner.team_id)
            forward_offset = owner_team.attack_direction * min(3.5, base_dist * 0.25)
            predicted_x += forward_offset

        # If the predicted lead point is far outside the pitch, fall back to TO_FEET
        margin = 2.0
        if (predicted_x < -margin or predicted_x > self.config.pitch_width + margin or
                predicted_y < -margin or predicted_y > self.config.pitch_height + margin):
            return (target.state.x, target.state.y)

        predicted_x, predicted_y = self._nudge_away_from_defenders(match, owner, predicted_x, predicted_y)

        return (
            clamp(predicted_x, 1.5, self.config.pitch_width - 1.5),
            clamp(predicted_y, 1.5, self.config.pitch_height - 1.5),
        )

    def _nudge_away_from_defenders(
        self, match: MatchState, owner: Player, target_x: float, target_y: float
    ) -> tuple[float, float]:
        opponents = [p for t in match.teams if t.team_id != owner.team_id for p in t.players]
        best_nudge_x, best_nudge_y = target_x, target_y
        best_score = -9999.0
        offsets = [(0.0, 0.0), (1.5, 0.0), (-1.5, 0.0), (0.0, 1.5), (0.0, -1.5),
                   (1.0, 1.0), (-1.0, 1.0), (1.0, -1.0), (-1.0, -1.0)]
        for dx, dy in offsets:
            cx = clamp(target_x + dx, 1.5, self.config.pitch_width - 1.5)
            cy = clamp(target_y + dy, 1.5, self.config.pitch_height - 1.5)
            penalty = 0.0
            for opp in opponents:
                d = math.hypot(cx - opp.state.x, cy - opp.state.y)
                if d < self.config.lead_defender_nudge_radius:
                    penalty += (self.config.lead_defender_nudge_radius - d) * 2.0
            offset_penalty = math.hypot(dx, dy) * 0.15
            score = -(penalty + offset_penalty)
            if score > best_score:
                best_score = score
                best_nudge_x, best_nudge_y = cx, cy
        return best_nudge_x, best_nudge_y
