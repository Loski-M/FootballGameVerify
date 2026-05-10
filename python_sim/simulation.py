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

        desired_x, desired_y, speed = self._resolve_pass_target(owner, target, match)

        desired_angle = angle_to(owner.state.x, owner.state.y, desired_x, desired_y)
        facing_gap = abs(normalize_angle(desired_angle - owner.state.facing_angle)) / math.pi

        quality = owner.derived.pass_quality / 100.0
        dist_m = math.hypot(desired_x - owner.state.x, desired_y - owner.state.y)
        speed_factor = clamp(
            (speed - self.config.pass_speed_min) / max(1.0, self.config.pass_speed_max - self.config.pass_speed_min),
            0.0, 1.0,
        )

        # Quality error scales down for short passes — close passes are easier
        quality_distance_scale = min(1.0, dist_m / 8.0)
        error_std = (
            self.config.pass_error_base
            + (1.0 - quality) * self.config.pass_error_quality_factor * quality_distance_scale
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

        # Determine goal x and defending goalkeeper
        attacking_team = self._team_by_id(match, owner.team_id)
        goal_x = self.config.pitch_width if attacking_team.attack_direction == 1 else 0.0

        defending_team_id = "A" if owner.team_id == "B" else "B"
        defending_team = self._team_by_id(match, defending_team_id)
        keeper = next(player for player in defending_team.players if player.role.name == "GK")
        keeper_y = keeper.state.y

        # Determine aim point: aim away from the side the GK is covering
        goal_min = self.config.pitch_height / 2 - self.config.goal_width / 2
        goal_max = self.config.pitch_height / 2 + self.config.goal_width / 2
        mid_goal = self.config.pitch_height / 2

        gk_offset = keeper_y - mid_goal
        dead_zone = self.config.goal_width * 0.15
        if abs(gk_offset) < dead_zone:
            # GK centered: fall back to far-post logic based on shooter position
            aim_y = goal_max - 0.5 if owner.state.y < mid_goal else goal_min + 0.5
        elif gk_offset > 0:
            # GK covering upper side, aim lower
            aim_y = goal_min + 0.5
        else:
            # GK covering lower side, aim upper
            aim_y = goal_max - 0.5

        desired_angle = angle_to(owner.state.x, owner.state.y, goal_x, aim_y)
        facing_gap = abs(normalize_angle(desired_angle - owner.state.facing_angle)) / math.pi

        # Variable shot speed based on shooting ability
        shot_ability = owner.derived.shot_quality / 100.0
        shot_speed = self.config.shot_speed * (0.75 + 0.25 * shot_ability)

        # Error margin depends on shot quality, facing, distance, and difficulty
        dist_to_goal = abs(goal_x - owner.state.x)
        dist_factor = dist_to_goal / max(1.0, self.config.shot_range)
        angle_from_gk = abs(aim_y - keeper_y) / max(0.5, self.config.goal_width / 2)
        speed_ratio = shot_speed / self.config.shot_speed
        shot_difficulty = (
            1.0
            + max(0.0, speed_ratio - 1.0) * 1.2
            + dist_factor * 0.8
            + min(angle_from_gk, 1.5) * 0.15
        )
        error_margin = (
            max(0.15, 1.0 - shot_ability) + facing_gap * 0.7
        ) * 3.0 * shot_difficulty

        goal_y = aim_y + self.rng.uniform(-error_margin, error_margin)

        dx = goal_x - owner.state.x
        dy = goal_y - owner.state.y
        dist = math.hypot(dx, dy) or 1.0
        match.ball.owner_player_id = None
        match.ball.owner_team_id = None
        owner.state.has_ball = False
        owner.state.target_facing_angle = angle_to(owner.state.x, owner.state.y, goal_x, goal_y)
        match.ball.vx = dx / dist * shot_speed
        match.ball.vy = dy / dist * shot_speed
        match.ball.last_touch_team_id = owner.team_id
        match.ball.last_touch_player_id = owner.player_id
        match.ball.last_touch_action = PlayerAction.SHOOT
        match.restart_reason = ""
        self._log(match, f"{owner.name} shoots")

    def _project_ball_to_goal_line(self, match: MatchState, goal_x: float) -> tuple[float, float]:
        bx, by = match.ball.x, match.ball.y
        vx, vy = match.ball.vx, match.ball.vy

        if abs(vx) < 0.01:
            return (by, 999.0)

        time_to_goal = (goal_x - bx) / vx
        if time_to_goal <= 0.0:
            return (by, 999.0)

        cross_y = by + vy * time_to_goal
        return (cross_y, time_to_goal)

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

        if not (goal_min <= match.ball.y <= goal_max):
            return None

        # Determine which goal is being attacked
        if match.ball.x <= 0.0:
            scoring_team = "B"
        elif match.ball.x >= self.config.pitch_width:
            scoring_team = "A"
        else:
            return None

        # Post check: ball within 0.3m of goal edge has 20% post-hit chance
        post_margin = 0.3
        is_near_post = (
            abs(match.ball.y - goal_min) <= post_margin
            or abs(match.ball.y - goal_max) <= post_margin
        )
        if is_near_post and self.rng.random() < 0.20:
            self._handle_post_rebound(match)
            return None

        # Crossbar check: 10% chance (modelling 3D height in 2D simulation)
        if self.rng.random() < 0.10:
            self._handle_crossbar_rebound(match)
            return None

        return scoring_team

    def _handle_post_rebound(self, match: MatchState) -> None:
        speed = math.hypot(match.ball.vx, match.ball.vy)
        rebound_factor = self.rng.uniform(0.7, 0.9)
        new_speed = speed * rebound_factor

        # Reflect direction (both x and y reverse) with random deflection
        base_angle = math.atan2(-match.ball.vy, -match.ball.vx)
        deflection = self.rng.uniform(-0.35, 0.35)
        new_angle = base_angle + deflection

        match.ball.vx = math.cos(new_angle) * new_speed
        match.ball.vy = math.sin(new_angle) * new_speed
        match.ball.owner_player_id = None
        match.ball.owner_team_id = None
        match.ball.last_touch_action = None
        self._clear_pass_intent(match)
        self._log(match, "Shot hits the post!")

    def _handle_crossbar_rebound(self, match: MatchState) -> None:
        speed = math.hypot(match.ball.vx, match.ball.vy)
        rebound_factor = self.rng.uniform(0.7, 0.9)
        new_speed = speed * rebound_factor

        # Reflect with wider random spread (crossbar produces unpredictable bounces)
        base_angle = math.atan2(-match.ball.vy, -match.ball.vx)
        deflection = self.rng.uniform(-0.6, 0.6)
        new_angle = base_angle + deflection

        match.ball.vx = math.cos(new_angle) * new_speed
        match.ball.vy = math.sin(new_angle) * new_speed
        match.ball.owner_player_id = None
        match.ball.owner_team_id = None
        match.ball.last_touch_action = None
        self._clear_pass_intent(match)
        self._log(match, "Shot hits the crossbar!")

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
        if abs(match.ball.x - goal_x) > 2.5:
            return False

        # Project where the ball will cross the goal line
        cross_y, time_to_goal = self._project_ball_to_goal_line(match, goal_x)

        # Check if cross point is within or just outside the goal area
        goal_min = self.config.pitch_height / 2 - self.config.goal_width / 2
        goal_max = self.config.pitch_height / 2 + self.config.goal_width / 2
        if cross_y < goal_min - 1.0 or cross_y > goal_max + 1.0:
            return False

        # New save formula based on reaction time and angle difficulty
        shot_speed = math.hypot(match.ball.vx, match.ball.vy)
        save_quality = keeper.derived.save_quality
        gk_reach = save_quality / 100.0 * self.config.goal_width / 2

        if gk_reach < 0.01:
            gk_reach = 0.01

        angle_difficulty = abs(cross_y - keeper.state.y) / gk_reach
        speed_factor = shot_speed / max(1.0, self.config.shot_speed)

        save_chance = clamp(
            0.1 + save_quality / 250.0 - angle_difficulty * 0.4 * speed_factor,
            0.05, 0.85,
        )

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

    def _resolve_pass_target(self, owner: Player, target: Player, match: MatchState) -> tuple[float, float, float]:
        """Returns (target_x, target_y, adjusted_speed).

        Lead distance is DESIGNED first (how far ahead of the receiver the ball
        should arrive), then pass speed is computed for the actual lead-point
        distance — fixing the old approach where speed was based on the
        receiver's *current* position and the lead point was an afterthought.
        """
        pass_type = owner.state.intent.pass_type
        intended_speed = owner.state.intent.pass_speed if owner.state.intent.pass_speed > 0 else self.config.pass_speed

        if pass_type is None or pass_type == PassType.TO_FEET:
            return (target.state.x, target.state.y, intended_speed)

        # 1. Design the lead distance: how far ahead of the receiver
        receiver_speed = math.hypot(target.state.vx, target.state.vy)
        desired_lead = (
            self.config.lead_distance_base
            + receiver_speed * self.config.lead_distance_speed_factor
        )
        if pass_type == PassType.THROUGH_PASS:
            desired_lead += self.config.lead_distance_through_extra

        # 2. Direction: along receiver's velocity, or toward opponent goal if stationary
        if receiver_speed > 0.5:
            run_dir_x = target.state.vx / receiver_speed
            run_dir_y = target.state.vy / receiver_speed
        else:
            owner_team = self._team_by_id(match, owner.team_id)
            run_dir_x = owner_team.attack_direction
            run_dir_y = 0.0

        # 3. Lead point
        lead_x = target.state.x + run_dir_x * desired_lead
        lead_y = target.state.y + run_dir_y * desired_lead

        if pass_type == PassType.THROUGH_PASS:
            owner_team = self._team_by_id(match, owner.team_id)
            lead_x += owner_team.attack_direction * 2.0

        # Out of bounds fallback
        margin = 2.0
        if (lead_x < -margin or lead_x > self.config.pitch_width + margin or
                lead_y < -margin or lead_y > self.config.pitch_height + margin):
            return (target.state.x, target.state.y, intended_speed)

        # 4. Actual distance to the lead point
        actual_dist = math.hypot(lead_x - owner.state.x, lead_y - owner.state.y)

        # 5. Recalculate ball speed for the ACTUAL lead-point distance
        speed = self.config.pass_speed_min + actual_dist * self.config.pass_speed_distance_per_m
        if pass_type == PassType.THROUGH_PASS:
            speed += self.config.pass_speed_type_through_bonus
        elif pass_type == PassType.LEAD_PASS:
            speed += self.config.pass_speed_type_lead_bonus

        quality = owner.derived.pass_quality / 100.0
        max_speed = self.config.pass_speed_min + (self.config.pass_speed_max - self.config.pass_speed_min) * quality
        min_reach_speed = math.sqrt(2.0 * self.config.ball_deceleration * actual_dist * 1.05)
        ball_speed = clamp(speed, max(self.config.pass_speed_min, min_reach_speed), max_speed)
        ball_speed = max(ball_speed, intended_speed * 0.9)

        # 6. Flight time to lead point
        a = self.config.ball_deceleration
        max_reach = ball_speed * ball_speed / (2.0 * a)
        if actual_dist >= max_reach:
            flight_time = ball_speed / a
        else:
            flight_time = (ball_speed - math.sqrt(ball_speed * ball_speed - 2.0 * a * actual_dist)) / a

        # 7. Timing check: if ball and receiver are badly mismatched, adjust
        if receiver_speed > 0.5 and flight_time > 0.05:
            receiver_time_to_lead = desired_lead / receiver_speed
            if receiver_time_to_lead > flight_time * 2.5:
                # Ball arrives too early — push lead point further
                adjusted_lead = receiver_speed * flight_time * 0.85
                adjusted_lead = clamp(adjusted_lead, desired_lead * 0.5, desired_lead * 2.0)
                lead_x = target.state.x + run_dir_x * adjusted_lead
                lead_y = target.state.y + run_dir_y * adjusted_lead
            elif flight_time > receiver_time_to_lead * 2.5:
                # Ball too late — fall back to feet
                return (target.state.x, target.state.y, ball_speed)

        # 8. Nudge away from defenders
        predicted_x, predicted_y = self._nudge_away_from_defenders(match, owner, lead_x, lead_y)

        return (
            clamp(predicted_x, 1.5, self.config.pitch_width - 1.5),
            clamp(predicted_y, 1.5, self.config.pitch_height - 1.5),
            ball_speed,
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
