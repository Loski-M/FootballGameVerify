from __future__ import annotations

from dataclasses import dataclass
import math

from python_sim.config import MatchConfig
from python_sim.models import BallFlightType, MatchState, PassType, Player, Role, Team, TeamPhase


@dataclass(slots=True)
class PassPreview:
    pass_type: PassType
    flight_type: BallFlightType
    target_x: float
    target_y: float
    landing_x: float
    landing_y: float
    ball_speed: float
    vertical_speed: float
    flight_time: float
    time_to_landing: float
    peak_height: float
    desired_lead: float
    run_dir_x: float
    run_dir_y: float
    lane_static_penalty: float
    lane_dynamic_penalty: float
    terminal_pressure: float
    is_blocked: bool


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def distance_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    l2 = (bx - ax) ** 2 + (by - ay) ** 2
    if l2 == 0:
        return distance(px, py, ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / l2))
    proj_x = ax + t * (bx - ax)
    proj_y = ay + t * (by - ay)
    return distance(px, py, proj_x, proj_y)


def preview_pass_option(
    match: MatchState,
    team: Team,
    passer: Player,
    receiver: Player,
    config: MatchConfig,
) -> PassPreview:
    nearest_defender_dist = _nearest_opponent_distance(match, passer)
    pass_type = _choose_pass_type(team, passer, receiver, nearest_defender_dist, config)
    ground_preview = _preview_ground_option(match, team, passer, receiver, pass_type, nearest_defender_dist, config)

    if not _can_consider_lofted(passer, receiver, team, pass_type, config):
        return ground_preview

    lofted_preview = _preview_lofted_option(match, team, passer, receiver, pass_type, nearest_defender_dist, config)
    if lofted_preview is None:
        return ground_preview

    ground_risk = _preview_risk(ground_preview, config)
    lofted_risk = _preview_risk(lofted_preview, config)

    if not lofted_preview.is_blocked:
        if ground_preview.is_blocked:
            return lofted_preview
        lofted_bias = config.lofted_pass_gk_decision_bias if passer.role == Role.GK else config.lofted_pass_decision_bias
        if ground_preview.lane_dynamic_penalty > lofted_preview.lane_dynamic_penalty * 1.4 and lofted_risk + lofted_bias < ground_risk:
            return lofted_preview
        if distance(passer.state.x, passer.state.y, receiver.state.x, receiver.state.y) >= config.lofted_pass_min_distance * 1.35:
            if lofted_risk + lofted_bias * 0.7 < ground_risk:
                return lofted_preview

    return ground_preview


def control_height_for_role(role: Role, config: MatchConfig) -> float:
    if role == Role.GK:
        return config.ball_control_max_height_goalkeeper
    return config.ball_control_max_height_outfield


def time_until_height(z: float, vz: float, height: float, gravity: float) -> float | None:
    if z <= height and vz <= 0.0:
        return 0.0
    a = -0.5 * gravity
    b = vz
    c = z - height
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    root = math.sqrt(disc)
    t1 = (-b - root) / (2.0 * a)
    t2 = (-b + root) / (2.0 * a)
    candidates = [t for t in (t1, t2) if t > 1e-6]
    if not candidates:
        return None
    return max(candidates)


def _preview_ground_option(
    match: MatchState,
    team: Team,
    passer: Player,
    receiver: Player,
    pass_type: PassType,
    nearest_defender_dist: float,
    config: MatchConfig,
) -> PassPreview:
    target_x, target_y, desired_lead, run_dir_x, run_dir_y, _ = _design_receive_target(
        match, team, passer, receiver, pass_type, config, lofted=False
    )
    actual_dist = distance(passer.state.x, passer.state.y, target_x, target_y)
    ball_speed = _choose_pass_speed(passer, actual_dist, pass_type, nearest_defender_dist, config)
    flight_time = _travel_time(actual_dist, ball_speed, config.ball_deceleration)
    lane_static_penalty = _evaluate_static_lane(match, passer, target_x, target_y)
    lane_dynamic_penalty, is_blocked = _evaluate_dynamic_intercept(
        match,
        passer,
        target_x,
        target_y,
        actual_dist,
        ball_speed,
        flight_time,
        config,
    )
    terminal_pressure = _evaluate_terminal_pressure(match, passer, target_x, target_y, config)
    return PassPreview(
        pass_type=pass_type,
        flight_type=BallFlightType.GROUND,
        target_x=target_x,
        target_y=target_y,
        landing_x=target_x,
        landing_y=target_y,
        ball_speed=ball_speed,
        vertical_speed=0.0,
        flight_time=flight_time,
        time_to_landing=flight_time,
        peak_height=0.0,
        desired_lead=desired_lead,
        run_dir_x=run_dir_x,
        run_dir_y=run_dir_y,
        lane_static_penalty=lane_static_penalty,
        lane_dynamic_penalty=lane_dynamic_penalty,
        terminal_pressure=terminal_pressure,
        is_blocked=is_blocked,
    )


def _preview_lofted_option(
    match: MatchState,
    team: Team,
    passer: Player,
    receiver: Player,
    pass_type: PassType,
    nearest_defender_dist: float,
    config: MatchConfig,
) -> PassPreview | None:
    landing_x, landing_y, desired_lead, run_dir_x, run_dir_y, receiver_speed = _design_receive_target(
        match, team, passer, receiver, pass_type, config, lofted=True
    )
    actual_dist = distance(passer.state.x, passer.state.y, landing_x, landing_y)
    if actual_dist < max(config.lofted_pass_min_distance * 0.75, 7.0):
        return None

    base_vertical = config.lofted_pass_vertical_speed + actual_dist * config.lofted_pass_vertical_speed_distance_factor
    time_to_landing = max(0.65, 2.0 * base_vertical / config.gravity)
    max_planar_speed = config.pass_speed_max * 1.1
    if actual_dist / time_to_landing > max_planar_speed:
        time_to_landing = actual_dist / max_planar_speed
        base_vertical = config.gravity * time_to_landing * 0.5

    vertical_speed = clamp(base_vertical, 6.5, 14.0)
    time_to_landing = max(time_to_landing, 2.0 * vertical_speed / config.gravity)
    planar_speed = actual_dist / max(0.1, time_to_landing)
    peak_height = vertical_speed * vertical_speed / (2.0 * config.gravity)

    lane_static_penalty = _evaluate_static_lane(match, passer, landing_x, landing_y) * (1.0 - config.lofted_pass_lane_relief)
    lane_dynamic_penalty = 0.0
    terminal_pressure = _evaluate_terminal_pressure(match, passer, landing_x, landing_y, config)

    receiver_eta = distance(receiver.state.x, receiver.state.y, landing_x, landing_y) / max(
        0.1, receiver.derived.move_speed * max(0.55, receiver.state.stamina)
    )
    opp_eta = min(
        (
            distance(opp.state.x, opp.state.y, landing_x, landing_y) / max(0.1, opp.derived.move_speed * max(0.55, opp.state.stamina))
            for opp in _opponents(match, passer.team_id)
        ),
        default=99.0,
    )

    receiver_space = _nearest_opponent_distance(match, receiver)
    terminal_pressure = max(
        0.0,
        terminal_pressure - receiver_space * 0.15 * config.lofted_pass_receiver_space_weight,
    )

    is_blocked = False
    if opp_eta + 0.1 < time_to_landing and receiver_eta > opp_eta + 0.15:
        is_blocked = True
    elif opp_eta < time_to_landing + 0.25:
        lane_dynamic_penalty += (time_to_landing + 0.25 - opp_eta) * 2.4

    if receiver_speed > 0.5 and desired_lead > 0.0:
        receiver_time_to_landing = desired_lead / receiver_speed
        if receiver_time_to_landing > time_to_landing * 1.8:
            lane_dynamic_penalty += 1.0

    return PassPreview(
        pass_type=pass_type,
        flight_type=BallFlightType.LOFTED,
        target_x=landing_x,
        target_y=landing_y,
        landing_x=landing_x,
        landing_y=landing_y,
        ball_speed=planar_speed,
        vertical_speed=vertical_speed,
        flight_time=time_to_landing,
        time_to_landing=time_to_landing,
        peak_height=peak_height,
        desired_lead=desired_lead,
        run_dir_x=run_dir_x,
        run_dir_y=run_dir_y,
        lane_static_penalty=lane_static_penalty,
        lane_dynamic_penalty=lane_dynamic_penalty,
        terminal_pressure=terminal_pressure,
        is_blocked=is_blocked,
    )


def _choose_pass_type(
    team: Team,
    passer: Player,
    receiver: Player,
    nearest_defender_dist: float,
    config: MatchConfig,
) -> PassType:
    dist = distance(passer.state.x, passer.state.y, receiver.state.x, receiver.state.y)
    forward_value = (receiver.state.x - passer.state.x) * team.attack_direction
    lateral_gap = abs(receiver.state.y - passer.state.y)
    if (
        receiver.role == Role.PIVOT
        and forward_value > 3.0
        and dist > 5.0
        and nearest_defender_dist > 1.8
        and team.state.phase == TeamPhase.POSSESSION_ATTACK
    ):
        return PassType.THROUGH_PASS
    if dist <= 6.0:
        return PassType.TO_FEET
    if forward_value > 2.0 or lateral_gap > 4.0 or dist > 10.0:
        return PassType.LEAD_PASS
    return PassType.TO_FEET


def _choose_pass_speed(
    passer: Player,
    dist: float,
    pass_type: PassType,
    nearest_defender_dist: float,
    config: MatchConfig,
) -> float:
    speed = config.pass_speed_min + dist * config.pass_speed_distance_per_m
    if pass_type == PassType.THROUGH_PASS:
        speed += config.pass_speed_type_through_bonus
    elif pass_type == PassType.LEAD_PASS:
        speed += config.pass_speed_type_lead_bonus
    if nearest_defender_dist < 3.0:
        speed += (3.0 - nearest_defender_dist) * config.pass_speed_pressure_malus
    quality = passer.derived.pass_quality / 100.0
    max_speed = config.pass_speed_min + (config.pass_speed_max - config.pass_speed_min) * quality
    min_reach_speed = math.sqrt(2.0 * config.ball_deceleration * dist * 1.05) if dist > 0.0 else config.pass_speed_min
    return clamp(speed, max(config.pass_speed_min, min_reach_speed), max_speed)


def _infer_run_direction(match: MatchState, team: Team, receiver: Player) -> tuple[float, float, float]:
    if receiver.state.intercept_x is not None and match.time_seconds < receiver.state.intercept_locked_until:
        dx = receiver.state.intercept_x - receiver.state.x
        dy = receiver.state.intercept_y - receiver.state.y
        mag = math.hypot(dx, dy)
        if mag > 0.25:
            return (dx / mag, dy / mag, math.hypot(receiver.state.vx, receiver.state.vy))

    intent_dx = receiver.state.intent.target_x - receiver.state.x
    intent_dy = receiver.state.intent.target_y - receiver.state.y
    intent_mag = math.hypot(intent_dx, intent_dy)
    if intent_mag > 0.35:
        return (intent_dx / intent_mag, intent_dy / intent_mag, math.hypot(receiver.state.vx, receiver.state.vy))

    receiver_speed = math.hypot(receiver.state.vx, receiver.state.vy)
    if receiver_speed > 0.5:
        return (receiver.state.vx / receiver_speed, receiver.state.vy / receiver_speed, receiver_speed)

    return (float(team.attack_direction), 0.0, receiver_speed)


def _design_receive_target(
    match: MatchState,
    team: Team,
    passer: Player,
    receiver: Player,
    pass_type: PassType,
    config: MatchConfig,
    lofted: bool,
) -> tuple[float, float, float, float, float, float]:
    run_dir_x, run_dir_y, receiver_speed = _infer_run_direction(match, team, receiver)
    if pass_type == PassType.TO_FEET:
        return (receiver.state.x, receiver.state.y, 0.0, run_dir_x, run_dir_y, receiver_speed)

    awareness = passer.attrs.attack_awareness / 100.0
    speed_factor = config.lead_distance_speed_factor * (0.5 + awareness * config.lead_prediction_quality_factor)
    desired_lead = config.lead_distance_base + receiver_speed * speed_factor
    if lofted:
        desired_lead *= 1.15
    if pass_type == PassType.THROUGH_PASS:
        desired_lead += config.lead_distance_through_extra * (0.9 if lofted else 1.0)

    target_x = receiver.state.x + run_dir_x * desired_lead
    target_y = receiver.state.y + run_dir_y * desired_lead
    if pass_type == PassType.THROUGH_PASS:
        target_x += team.attack_direction * (2.5 if lofted else 2.0)

    margin = 2.0
    if (
        target_x < -margin
        or target_x > config.pitch_width + margin
        or target_y < -margin
        or target_y > config.pitch_height + margin
    ):
        return (receiver.state.x, receiver.state.y, 0.0, run_dir_x, run_dir_y, receiver_speed)

    target_x, target_y = _nudge_away_from_defenders(match, passer, target_x, target_y, config)
    target_x = clamp(target_x, 1.5, config.pitch_width - 1.5)
    target_y = clamp(target_y, 1.5, config.pitch_height - 1.5)
    return (target_x, target_y, desired_lead, run_dir_x, run_dir_y, receiver_speed)


def _can_consider_lofted(
    passer: Player,
    receiver: Player,
    team: Team,
    pass_type: PassType,
    config: MatchConfig,
) -> bool:
    dist = distance(passer.state.x, passer.state.y, receiver.state.x, receiver.state.y)
    if passer.role == Role.GK:
        return True
    if passer.role == Role.ANCHOR:
        return dist >= config.lofted_pass_min_distance
    if dist < config.lofted_pass_min_distance * 1.15:
        return False
    if pass_type == PassType.THROUGH_PASS:
        return True
    forward_value = (receiver.state.x - passer.state.x) * team.attack_direction
    lateral_gap = abs(receiver.state.y - passer.state.y)
    return forward_value > 2.5 or lateral_gap > 8.0


def _opponents(match: MatchState, team_id: str) -> list[Player]:
    return [p for team in match.teams if team.team_id != team_id for p in team.players]


def _nearest_opponent_distance(match: MatchState, player: Player) -> float:
    return min(
        (distance(player.state.x, player.state.y, opp.state.x, opp.state.y) for opp in _opponents(match, player.team_id)),
        default=99.0,
    )


def _travel_time(dist: float, ball_speed: float, decel: float) -> float:
    if dist <= 0.0 or ball_speed <= 0.0:
        return 0.0
    max_reach = ball_speed * ball_speed / (2.0 * decel)
    if dist >= max_reach:
        return ball_speed / decel
    inside = max(0.0, ball_speed * ball_speed - 2.0 * decel * dist)
    return (ball_speed - math.sqrt(inside)) / decel


def _nudge_away_from_defenders(
    match: MatchState,
    passer: Player,
    target_x: float,
    target_y: float,
    config: MatchConfig,
) -> tuple[float, float]:
    best_x, best_y = target_x, target_y
    best_score = -9999.0
    offsets = [
        (0.0, 0.0),
        (1.5, 0.0),
        (-1.5, 0.0),
        (0.0, 1.5),
        (0.0, -1.5),
        (1.0, 1.0),
        (-1.0, 1.0),
        (1.0, -1.0),
        (-1.0, -1.0),
    ]
    for dx, dy in offsets:
        cx = clamp(target_x + dx, 1.5, config.pitch_width - 1.5)
        cy = clamp(target_y + dy, 1.5, config.pitch_height - 1.5)
        penalty = _evaluate_terminal_pressure(match, passer, cx, cy, config)
        offset_penalty = math.hypot(dx, dy) * 0.15
        score = -(penalty + offset_penalty)
        if score > best_score:
            best_score = score
            best_x, best_y = cx, cy
    return best_x, best_y


def _evaluate_terminal_pressure(
    match: MatchState,
    passer: Player,
    target_x: float,
    target_y: float,
    config: MatchConfig,
) -> float:
    pressure = 0.0
    for opp in _opponents(match, passer.team_id):
        d = distance(target_x, target_y, opp.state.x, opp.state.y)
        if d < config.lead_defender_nudge_radius:
            pressure += (config.lead_defender_nudge_radius - d) * config.lead_defender_nudge_strength
    return pressure


def _evaluate_static_lane(match: MatchState, passer: Player, target_x: float, target_y: float) -> float:
    penalty = 0.0
    for opp in _opponents(match, passer.team_id):
        d_to_lane = distance_to_segment(
            opp.state.x,
            opp.state.y,
            passer.state.x,
            passer.state.y,
            target_x,
            target_y,
        )
        if d_to_lane < 1.8:
            dist_to_passer = distance(passer.state.x, passer.state.y, opp.state.x, opp.state.y)
            proximity_factor = 1.0 + max(0.0, (5.0 - dist_to_passer) * 0.2)
            penalty += (1.8 - d_to_lane) * 3.5 * proximity_factor
    return penalty


def _evaluate_dynamic_intercept(
    match: MatchState,
    passer: Player,
    target_x: float,
    target_y: float,
    total_dist: float,
    ball_speed: float,
    flight_time: float,
    config: MatchConfig,
) -> tuple[float, bool]:
    if total_dist <= 0.01 or flight_time <= 0.01:
        return (0.0, False)

    dir_x = (target_x - passer.state.x) / total_dist
    dir_y = (target_y - passer.state.y) / total_dist
    penalty = 0.0
    hard_block = False
    dt = max(0.05, config.pass_intercept_sample_dt)
    samples = max(1, int(math.ceil(flight_time / dt)))

    for idx in range(1, samples + 1):
        t = min(flight_time, idx * dt)
        travel = ball_speed * t - 0.5 * config.ball_deceleration * t * t
        travel = clamp(travel, 0.0, total_dist)
        ratio = travel / total_dist
        bx = passer.state.x + dir_x * travel
        by = passer.state.y + dir_y * travel

        for opp in _opponents(match, passer.team_id):
            run_speed = max(0.1, opp.derived.move_speed * max(0.55, opp.state.stamina))
            eta = distance(opp.state.x, opp.state.y, bx, by) / run_speed
            if eta <= t + config.pass_intercept_time_margin:
                urgency = 1.0 + (1.0 - ratio) * 0.8
                penalty += config.pass_dynamic_lane_weight * urgency
                if ratio < 0.88 and eta <= t + config.pass_intercept_hard_block_margin:
                    hard_block = True
                    break
        if hard_block:
            break

    return (penalty, hard_block)


def _preview_risk(preview: PassPreview, config: MatchConfig) -> float:
    terminal_weight = (
        config.lofted_pass_terminal_pressure_weight
        if preview.flight_type == BallFlightType.LOFTED
        else config.pass_terminal_pressure_weight
    )
    return (
        preview.lane_static_penalty
        + preview.lane_dynamic_penalty
        + preview.terminal_pressure * terminal_weight
        + (3.0 if preview.is_blocked else 0.0)
    )
