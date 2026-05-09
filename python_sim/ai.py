from __future__ import annotations

import math
import random

from python_sim.config import MatchConfig
from python_sim.models import (
    Intent,
    MatchState,
    Player,
    PlayerAction,
    PassType,
    ReceiveMode,
    Role,
    Team,
    TeamPhase,
)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def distance_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    l2 = (bx - ax)**2 + (by - ay)**2
    if l2 == 0:
        return distance(px, py, ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / l2))
    proj_x = ax + t * (bx - ax)
    proj_y = ay + t * (by - ay)
    return distance(px, py, proj_x, proj_y)


def normalize_angle(angle: float) -> float:
    while angle > math.pi:
        angle -= math.tau
    while angle < -math.pi:
        angle += math.tau
    return angle


def angle_to(ax: float, ay: float, bx: float, by: float) -> float:
    return math.atan2(by - ay, bx - ax)


def get_opponent_team(match: MatchState, team_id: str) -> Team:
    for team in match.teams:
        if team.team_id != team_id:
            return team
    raise ValueError("Opponent team not found")


def get_owner_player(match: MatchState) -> Player | None:
    if not match.ball.owner_player_id:
        return None
    for team in match.teams:
        for player in team.players:
            if player.player_id == match.ball.owner_player_id:
                return player
    return None


def update_team_phase(match: MatchState, team: Team, config: MatchConfig) -> None:
    if match.dead_ball:
        team.state.phase = TeamPhase.RESTART
        return
    has_ball = match.ball.owner_team_id == team.team_id
    if has_ball:
        team.state.possession_time += config.tick_seconds
        in_transition = match.time_seconds - team.state.last_gain_time < 2.0
        team.state.phase = TeamPhase.POSSESSION_BUILD_UP if in_transition else TeamPhase.POSSESSION_ATTACK
    else:
        pressure = team.tactics.base_pressure
        ball_x = match.ball.x
        own_goal_x = 0 if team.attack_direction == 1 else config.pitch_width
        dist_to_own_goal = abs(ball_x - own_goal_x)
        if pressure > 0.18 and dist_to_own_goal > config.pitch_width * 0.55:
            team.state.phase = TeamPhase.HIGH_PRESS
        else:
            team.state.phase = TeamPhase.DEFENSIVE_SHAPE


def decide_all_players(match: MatchState, team: Team, config: MatchConfig, rng: random.Random) -> None:
    owner = get_owner_player(match)
    for player in team.players:
        player.state.decision_cooldown -= config.tick_seconds
        
        # If dead ball and this is the taker, hold the cooldown at 0 to signal restart is ready
        if match.dead_ball and owner and player.player_id == owner.player_id:
            if player.state.decision_cooldown <= 0:
                player.state.decision_cooldown = 0.0
                continue
                
        if player.state.decision_cooldown > 0:
            continue
            
        player.state.decision_cooldown = config.decision_interval_seconds + rng.uniform(-0.1, 0.1)
        if match.dead_ball:
            player.state.intent = decide_restart_position(match, team, player, config)
            continue
        if owner and owner.player_id == player.player_id:
            player.state.intent = decide_ball_owner(match, team, player, config, rng)
        else:
            player.state.intent = decide_off_ball(match, team, player, config)


def decide_restart_position(match: MatchState, team: Team, player: Player, config: MatchConfig) -> Intent:
    if match.restart_team_id == team.team_id and player.player_id == match.ball.owner_player_id:
        return Intent(PlayerAction.PASS, match.ball.x, match.ball.y)
        
    if match.restart_reason == "Kickoff":
        # Separation logic while returning to half
        teammates_close = [p for p in team.players if p.player_id != player.player_id and player.player_id != match.ball.owner_player_id and distance(p.state.x, p.state.y, player.state.x, player.state.y) < 2.5]
        if teammates_close:
            closest = min(teammates_close, key=lambda p: distance(p.state.x, p.state.y, player.state.x, player.state.y))
            angle_away = angle_to(closest.state.x, closest.state.y, player.state.x, player.state.y)
            tx = player.state.x + math.cos(angle_away) * 3.0
            ty = player.state.y + math.sin(angle_away) * 3.0
            tx = clamp(tx, 0.0, config.pitch_width)
            ty = clamp(ty, 0.0, config.pitch_height)
            return Intent(PlayerAction.RECOVER, tx, ty)

        # Everyone retreats to their own half, except the taker who is already at the ball
        home_x, home_y = role_home_position(team, player.role, config, attacking=False)
        tx, ty = home_x, home_y
        if team.attack_direction == 1:
            tx = clamp(tx, 1.0, config.pitch_width / 2 - 2.0)
        else:
            tx = clamp(tx, config.pitch_width / 2 + 2.0, config.pitch_width - 1.0)
        return Intent(PlayerAction.RECOVER, tx, ty)
        
    if match.restart_reason == "Corner":
        if player.role == Role.GK:
            tx, ty = role_home_position(team, player.role, config, attacking=False)
            return Intent(PlayerAction.RECOVER, tx, ty)
            
        is_attacking = (match.restart_team_id == team.team_id)
        goal_x = config.pitch_width if (team.attack_direction == 1 if is_attacking else team.attack_direction == -1) else 0.0
        
        if is_attacking:
            if player.role == Role.ANCHOR:
                tx = goal_x - team.attack_direction * 12.0
                ty = config.pitch_height / 2
            else:
                # 3 players scattered in the box
                offset_y = -3.0 if player.role == Role.LEFT else (3.0 if player.role == Role.RIGHT else 0.0)
                tx = goal_x - team.attack_direction * 4.0
                ty = config.pitch_height / 2 + offset_y
        else:
            if player.role == Role.PIVOT:
                tx = goal_x + team.attack_direction * 12.0
                ty = config.pitch_height / 2
            else:
                offset_y = -2.0 if player.role == Role.LEFT else (2.0 if player.role == Role.RIGHT else 0.0)
                tx = goal_x + team.attack_direction * 3.0
                ty = config.pitch_height / 2 + offset_y
                
        return Intent(PlayerAction.RECOVER, clamp(tx, 0, config.pitch_width), clamp(ty, 0, config.pitch_height))

    target_x, target_y = structured_target(match, team, player, config, has_ball=match.restart_team_id == team.team_id)
    return Intent(PlayerAction.RECOVER, target_x, target_y)


def decide_ball_owner(
    match: MatchState,
    team: Team,
    player: Player,
    config: MatchConfig,
    rng: random.Random,
) -> Intent:
    if player.role == Role.GK:
        pass_target, _ = score_best_pass(match, team, player, config)
        if pass_target is not None:
            return Intent(PlayerAction.PASS, pass_target.state.x, pass_target.state.y, pass_target.player_id, PassType.TO_FEET)
        return Intent(PlayerAction.DRIBBLE, player.state.x + team.attack_direction * 1.5, player.state.y)
    nearest_defender = nearest_opponent(match, player)
    defender_dist = (
        distance(player.state.x, player.state.y, nearest_defender.state.x, nearest_defender.state.y)
        if nearest_defender
        else 99.0
    )
    
    # Force a pass if this is the start of a kickoff
    if match.restart_reason == "Kickoff" and match.ball.last_touch_action is None:
        pass_target, _ = score_best_pass(match, team, player, config)
        if pass_target is not None:
            pass_type = choose_pass_type(team, player, pass_target, config)
            return Intent(PlayerAction.PASS, pass_target.state.x, pass_target.state.y, pass_target.player_id, pass_type)
        else:
            # Fallback
            mate = [p for p in team.players if p.player_id != player.player_id][0]
            return Intent(PlayerAction.PASS, mate.state.x, mate.state.y, mate.player_id, PassType.TO_FEET)

    shoot_score = score_shot(match, team, player, defender_dist, config)
    pass_target, pass_score = score_best_pass(match, team, player, config)
    dribble_score = score_dribble(match, team, player, defender_dist, config)

    noisy = [
        (PlayerAction.SHOOT, shoot_score + rng.uniform(-0.3, 0.3), None),
        (PlayerAction.PASS, pass_score + rng.uniform(-0.3, 0.3), pass_target),
        (PlayerAction.DRIBBLE, dribble_score + rng.uniform(-0.3, 0.3), None),
    ]
    best_action, _, target = max(noisy, key=lambda item: item[1])
    if best_action == PlayerAction.PASS and target is not None:
        pass_type = choose_pass_type(team, player, target, config)
        return Intent(PlayerAction.PASS, target.state.x, target.state.y, target.player_id, pass_type)
    if best_action == PlayerAction.SHOOT:
        goal_x = config.pitch_width if team.attack_direction == 1 else 0.0
        half_h = config.pitch_height / 2
        aim_y = half_h + config.goal_width / 2 - 0.5 if player.state.y < half_h else half_h - config.goal_width / 2 + 0.5
        return Intent(PlayerAction.SHOOT, goal_x, aim_y)
        
    forward_x = player.state.x + team.attack_direction * config.support_distance * 0.4
    forward_x = clamp(forward_x, 0.0, config.pitch_width)
    
    # Angle the dribble towards the goal if we are past the midway mark
    goal_x = config.pitch_width if team.attack_direction == 1 else 0.0
    dist_x = abs(goal_x - player.state.x)
    if dist_x < config.pitch_width * 0.4:
        target_y = player.state.y + (config.pitch_height / 2 - player.state.y) * 0.4
    else:
        target_y = player.state.y
        
    return Intent(PlayerAction.DRIBBLE, forward_x, target_y)


def decide_off_ball(match: MatchState, team: Team, player: Player, config: MatchConfig) -> Intent:
    if match.ball.owner_team_id is None:
        intercept = choose_intercept_point(match, player, config)
        if intercept is not None:
            ix, iy, mode = intercept
            player.state.receive_mode = mode
            return Intent(PlayerAction.SUPPORT, ix, iy)
        player.state.receive_mode = ReceiveMode.NONE
    if match.ball.owner_team_id == team.team_id:
        target_x, target_y = structured_target(match, team, player, config, has_ball=True)
        action = PlayerAction.SUPPORT if player.role in (Role.ANCHOR, Role.PIVOT) else PlayerAction.SPREAD
        player.state.receive_mode = ReceiveMode.NONE
        return Intent(action, target_x, target_y)
    target_x, target_y, action = defending_target(match, team, player, config)
    player.state.receive_mode = ReceiveMode.NONE
    return Intent(action, target_x, target_y)


def choose_pass_type(team: Team, player: Player, target: Player, config: MatchConfig) -> PassType:
    forward_value = (target.state.x - player.state.x) * team.attack_direction
    lateral_gap = abs(target.state.y - player.state.y)
    if target.role == Role.PIVOT and forward_value > 4.0:
        return PassType.THROUGH_PASS
    if forward_value > 2.0 or lateral_gap > 4.0:
        return PassType.LEAD_PASS
    return PassType.TO_FEET


def choose_intercept_point(match: MatchState, player: Player, config: MatchConfig) -> tuple[float, float, ReceiveMode] | None:
    if player.role == Role.GK:
        closest_opp_dist = min((distance(match.ball.x, match.ball.y, p.state.x, p.state.y) for t in match.teams if t.team_id != player.team_id for p in t.players), default=99.0)
        dist_to_ball = distance(player.state.x, player.state.y, match.ball.x, match.ball.y)
        if dist_to_ball > closest_opp_dist - 0.5:
            return None
    if player.state.intercept_x is not None and match.time_seconds < player.state.intercept_locked_until:
        return (player.state.intercept_x, player.state.intercept_y, player.state.receive_mode)
    if abs(match.ball.vx) + abs(match.ball.vy) < 0.6:
        return None
    path = predict_ball_path(match.ball.x, match.ball.y, match.ball.vx, match.ball.vy, config, steps=14)
    best = None
    best_cost = 999.0
    for idx, (bx, by) in enumerate(path):
        t = (idx + 1) * config.tick_seconds
        run_dist = distance(player.state.x, player.state.y, bx, by)
        reach_time = run_dist / max(0.1, player.derived.move_speed * player.state.stamina)
        cost = abs(reach_time - t)
        if cost < best_cost and reach_time <= t + 0.5:
            best_cost = cost
            best = (bx, by, t)
    if best is None:
        return None
    bx, by, t = best
    offset = distance(player.state.x, player.state.y, bx, by)
    if offset < 1.5:
        mode = ReceiveMode.MEET_BALL
    elif (bx - player.state.x) * (1 if match.ball.vx >= 0 else -1) > 0:
        mode = ReceiveMode.RUN_ONTO
    else:
        mode = ReceiveMode.COME_SHORT
    player.state.intercept_x = bx
    player.state.intercept_y = by
    player.state.intercept_locked_until = match.time_seconds + min(1.0, max(0.4, t))
    player.state.receive_mode = mode
    return (bx, by, mode)


def predict_ball_path(
    x: float,
    y: float,
    vx: float,
    vy: float,
    config: MatchConfig,
    steps: int,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    px, py, pvx, pvy = x, y, vx, vy
    for _ in range(steps):
        px += pvx * config.tick_seconds
        py += pvy * config.tick_seconds
        pvx *= config.ball_friction
        pvy *= config.ball_friction
        points.append((clamp(px, 0.0, config.pitch_width), clamp(py, 0.0, config.pitch_height)))
    return points


def role_home_position(team: Team, role: Role, config: MatchConfig, attacking: bool) -> tuple[float, float]:
    half_h = config.pitch_height / 2
    left_x = 7 if team.attack_direction == 1 else config.pitch_width - 7
    mid_x = 12 if team.attack_direction == 1 else config.pitch_width - 12
    high_x = 18 if team.attack_direction == 1 else config.pitch_width - 18
    if attacking:
        left_x += team.attack_direction * 4
        mid_x += team.attack_direction * 4
        high_x += team.attack_direction * 4
    if role == Role.GK:
        return (3 if team.attack_direction == 1 else config.pitch_width - 3, half_h)
    if role == Role.ANCHOR:
        return (left_x, half_h)
    if role == Role.LEFT:
        return (mid_x, half_h - 5.5)
    if role == Role.RIGHT:
        return (mid_x, half_h + 5.5)
    return (high_x, half_h)


def structured_target(match: MatchState, team: Team, player: Player, config: MatchConfig, has_ball: bool) -> tuple[float, float]:
    ball_x = match.ball.x
    ball_y = match.ball.y
    half_h = config.pitch_height / 2
    if player.role == Role.GK:
        return role_home_position(team, player.role, config, attacking=False)

    # Separation logic for attacking
    teammates_close = [p for p in team.players if p.player_id != player.player_id and distance(p.state.x, p.state.y, player.state.x, player.state.y) < 3.0]
    if teammates_close:
        closest = min(teammates_close, key=lambda p: distance(p.state.x, p.state.y, player.state.x, player.state.y))
        angle_away = angle_to(closest.state.x, closest.state.y, player.state.x, player.state.y)
        tx = player.state.x + math.cos(angle_away) * 3.0
        ty = player.state.y + math.sin(angle_away) * 3.0
        return (clamp(tx, 0, config.pitch_width), clamp(ty, 0, config.pitch_height))

    home_x, home_y = role_home_position(team, player.role, config, attacking=has_ball)
    if has_ball:
        if player.role == Role.ANCHOR:
            tx, ty = (
                clamp(ball_x - team.attack_direction * 5.0, 5.0, config.pitch_width - 5.0),
                clamp((ball_y + half_h) / 2, 3.0, config.pitch_height - 3.0),
            )
        elif player.role == Role.LEFT:
            tx, ty = (
                clamp(max(home_x, ball_x + team.attack_direction * 1.5), 5.0, config.pitch_width - 5.0),
                clamp(half_h - 7.0, 2.0, config.pitch_height - 2.0),
            )
        elif player.role == Role.RIGHT:
            tx, ty = (
                clamp(max(home_x, ball_x + team.attack_direction * 1.5), 5.0, config.pitch_width - 5.0),
                clamp(half_h + 7.0, 2.0, config.pitch_height - 2.0),
            )
        elif player.role == Role.PIVOT:
            tx, ty = (
                clamp(ball_x + team.attack_direction * 5.5, 6.0, config.pitch_width - 6.0),
                clamp(half_h + (ball_y - half_h) * 0.2, 3.0, config.pitch_height - 3.0),
            )
        else:
            tx, ty = home_x, home_y
            
        # Support logic: if the team has the ball but I am not the owner, find an open passing lane
        if match.ball.owner_player_id != player.player_id:
            opp_team = get_opponent_team(match, team.team_id)
            best_x, best_y, best_score = tx, ty, -9999.0
            offsets = [(0, 0), (0, 3.5), (0, -3.5), (2.5, 3.5), (2.5, -3.5), (-2.5, 3.5), (-2.5, -3.5)]
            for dx, dy in offsets:
                cx = clamp(tx + dx, 2.0, config.pitch_width - 2.0)
                cy = clamp(ty + dy, 2.0, config.pitch_height - 2.0)
                lane_pen = 0.0
                for opp in opp_team.players:
                    dist_to_lane = distance_to_segment(opp.state.x, opp.state.y, ball_x, ball_y, cx, cy)
                    if dist_to_lane < 1.8:
                        lane_pen += (1.8 - dist_to_lane) * 3.0
                score = -lane_pen - math.hypot(dx, dy) * 0.2
                if score > best_score:
                    best_score = score
                    best_x, best_y = cx, cy
            tx, ty = best_x, best_y
            
        return (tx, ty)
    return (home_x, home_y)


def defending_target(
    match: MatchState,
    team: Team,
    player: Player,
    config: MatchConfig,
) -> tuple[float, float, PlayerAction]:
    owner = get_owner_player(match)
    half_h = config.pitch_height / 2
    if owner is None:
        if player.role == Role.GK:
            closest_opp_dist = min((distance(match.ball.x, match.ball.y, p.state.x, p.state.y) for t in match.teams if t.team_id != team.team_id for p in t.players), default=99.0)
            dist_to_ball = distance(player.state.x, player.state.y, match.ball.x, match.ball.y)
            if dist_to_ball < closest_opp_dist - 0.5:
                return (match.ball.x, match.ball.y, PlayerAction.PRESS)
            
            own_goal_x = 0.0 if team.attack_direction == 1 else config.pitch_width
            focus_x, focus_y = match.ball.x, match.ball.y
            angle_ball = angle_to(own_goal_x, half_h, focus_x, focus_y)
            dist_ball = distance(own_goal_x, half_h, focus_x, focus_y)
            out_dist = min(2.5, dist_ball * 0.25)
            gk_x = own_goal_x + math.cos(angle_ball) * out_dist
            gk_y = half_h + math.sin(angle_ball) * out_dist
            return (clamp(gk_x, 0.0, config.pitch_width), clamp(gk_y, 0.0, config.pitch_height), PlayerAction.RECOVER)
        return (match.ball.x, match.ball.y, PlayerAction.PRESS)
    
    if player.role == Role.GK:
        own_goal_x = 0.0 if team.attack_direction == 1 else config.pitch_width
        focus_x, focus_y = match.ball.x, match.ball.y
        angle_ball = angle_to(own_goal_x, half_h, focus_x, focus_y)
        dist_ball = distance(own_goal_x, half_h, focus_x, focus_y)
        out_dist = min(2.5, dist_ball * 0.25)
        gk_x = own_goal_x + math.cos(angle_ball) * out_dist
        gk_y = half_h + math.sin(angle_ball) * out_dist
        return (clamp(gk_x, 0.0, config.pitch_width), clamp(gk_y, 0.0, config.pitch_height), PlayerAction.RECOVER)
    
    team_mates = sorted(
        team.players,
        key=lambda p: distance(p.state.x, p.state.y, owner.state.x, owner.state.y),
    )
    press_count = 2 if team.state.phase == TeamPhase.HIGH_PRESS else 1
    # Priortize pressing over teammate separation if this player is the primary presser
    is_presser = any(m.player_id == player.player_id for m in team_mates[:press_count])
    if is_presser:
        return (owner.state.x, owner.state.y, PlayerAction.PRESS)

    # Check spatial separation logic: if another active non-GK teammate is too close, prioritize staying apart
    teammates_close = [p for p in team.players if p.player_id != player.player_id and distance(p.state.x, p.state.y, player.state.x, player.state.y) < 3.0]
    if teammates_close:
        # Move away from closest teammate
        closest = min(teammates_close, key=lambda p: distance(p.state.x, p.state.y, player.state.x, player.state.y))
        angle_away = angle_to(closest.state.x, closest.state.y, player.state.x, player.state.y)
        tx = player.state.x + math.cos(angle_away) * 3.0
        ty = player.state.y + math.sin(angle_away) * 3.0
        # Never leave your own half un-manned completely if you are the anchor
        return (clamp(tx, 0, config.pitch_width), clamp(ty, 0, config.pitch_height), PlayerAction.RECOVER)
    base_x, base_y = role_home_position(team, player.role, config, attacking=False)
    block_shift = -2.5 if team.attack_direction == 1 else 2.5
    if team.state.phase == TeamPhase.HIGH_PRESS:
        block_shift *= 0.4
    return (clamp(base_x + block_shift, 3.0, config.pitch_width - 3.0), base_y, PlayerAction.RECOVER)


def score_dribble(match: MatchState, team: Team, player: Player, defender_dist: float, config: MatchConfig) -> float:
    goal_x = config.pitch_width if team.attack_direction == 1 else 0.0
    dist_to_goal = abs(goal_x - player.state.x)
    
    # Very severe penalty for dribbling if already at the baseline
    if dist_to_goal < 2.0:
        return -10.0
        
    forward_bonus = 1.5 - dist_to_goal / config.pitch_width
    pressure_penalty = max(0.0, (3.2 - defender_dist) * 1.0)
    sideline_penalty = abs(player.state.y - config.pitch_height / 2) / config.pitch_height
    body_alignment = 1.0 - abs(normalize_angle(angle_to(player.state.x, player.state.y, player.state.intent.target_x, player.state.intent.target_y) - player.state.facing_angle)) / math.pi
    return player.derived.ball_control / 35.0 + forward_bonus - pressure_penalty - sideline_penalty + body_alignment * 0.4


def score_shot(match: MatchState, team: Team, player: Player, defender_dist: float, config: MatchConfig) -> float:
    goal_x = config.pitch_width if team.attack_direction == 1 else 0.0
    half_h = config.pitch_height / 2
    aim_y = half_h + config.goal_width / 2 - 0.5 if player.state.y < half_h else half_h - config.goal_width / 2 + 0.5
    dist = distance(player.state.x, player.state.y, goal_x, aim_y)
    if dist > config.shot_range * 1.35:
        return -5.0
    angle_factor = 1.0 - abs(player.state.y - aim_y) / (config.pitch_height / 2)
    pressure_penalty = max(0.0, (2.5 - defender_dist) * 1.1)
    close_bonus = 1.2 if dist < config.shot_range * 0.7 else 0.0
    facing_penalty = abs(normalize_angle(angle_to(player.state.x, player.state.y, goal_x, aim_y) - player.state.facing_angle)) / math.pi
    return (
        player.derived.shot_quality / 20.0
        + angle_factor * 2.2
        + close_bonus
        - dist / config.shot_range
        - pressure_penalty
        - facing_penalty * 1.6
    )


def score_best_pass(
    match: MatchState,
    team: Team,
    player: Player,
    config: MatchConfig,
) -> tuple[Player | None, float]:
    best_target = None
    best_score = -999.0
    owner_x = player.state.x
    opponents = get_opponent_team(match, team.team_id).players
    for mate in team.players:
        if mate.player_id == player.player_id:
            continue
        dist = distance(owner_x, player.state.y, mate.state.x, mate.state.y)
        if dist > config.support_distance * 1.8:
            continue
            
        # Passing lane block evaluation
        lane_penalty = 0.0
        for opp in opponents:
            d_to_lane = distance_to_segment(opp.state.x, opp.state.y, player.state.x, player.state.y, mate.state.x, mate.state.y)
            if d_to_lane < 1.8:
                # The closer the opponent is to the passing lane, the higher the penalty
                # Also, blocks closer to the passer are more dangerous.
                dist_to_passer = distance(player.state.x, player.state.y, opp.state.x, opp.state.y)
                proximity_factor = 1.0 + max(0.0, (5.0 - dist_to_passer) * 0.2)
                lane_penalty += (1.8 - d_to_lane) * 3.5 * proximity_factor
                
        forward_value = (mate.state.x - owner_x) * team.attack_direction
        open_value = nearest_defender_distance(match, mate)
        role_bias = -1.2 if mate.role == Role.GK else 0.0
        if mate.role == Role.PIVOT:
            role_bias += 0.5
        facing_penalty = abs(normalize_angle(angle_to(player.state.x, player.state.y, mate.state.x, mate.state.y) - player.state.facing_angle)) / math.pi
        score = (
            player.derived.pass_quality / 26.0
            + forward_value * 0.3
            + open_value * 0.35
            - dist * 0.08
            + role_bias
            - facing_penalty * 0.9
            - lane_penalty
        )
        if score > best_score:
            best_score = score
            best_target = mate
    return best_target, best_score


def nearest_defender_distance(match: MatchState, player: Player) -> float:
    nearest = nearest_opponent(match, player)
    if nearest is None:
        return 6.0
    return distance(player.state.x, player.state.y, nearest.state.x, nearest.state.y)


def nearest_opponent(match: MatchState, player: Player) -> Player | None:
    nearest = None
    best = 999.0
    for team in match.teams:
        if team.team_id == player.team_id:
            continue
        for opponent in team.players:
            d = distance(player.state.x, player.state.y, opponent.state.x, opponent.state.y)
            if d < best:
                best = d
                nearest = opponent
    return nearest
