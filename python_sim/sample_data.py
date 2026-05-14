from __future__ import annotations

from python_sim.config import MatchConfig
from python_sim.models import (
    BallState,
    Player,
    PlayerAttributes,
    PlayerDerived,
    PlayerState,
    Role,
    Team,
    TeamPhase,
    TeamState,
    TeamStats,
    TeamTactics,
    MatchState,
)


def build_derived(attrs: PlayerAttributes) -> PlayerDerived:
    return PlayerDerived(
        move_speed=2.8 + attrs.speed * 0.035 + attrs.acceleration * 0.01,
        ball_control=attrs.dribbling * 0.65 + attrs.attack_awareness * 0.35,
        pass_quality=attrs.passing * 0.7 + attrs.attack_awareness * 0.3,
        shot_quality=attrs.shooting * 0.75 + attrs.attack_awareness * 0.25,
        press_quality=attrs.defence_awareness * 0.65 + attrs.acceleration * 0.35,
        recover_quality=attrs.defence_awareness * 0.55 + attrs.speed * 0.45,
        save_quality=attrs.goalkeeping,
        turn_rate=1.8 + attrs.acceleration * 0.01 + attrs.dribbling * 0.004,
    )


def build_player(
    player_id: str,
    team_id: str,
    name: str,
    role: Role,
    attrs: PlayerAttributes,
    x: float,
    y: float,
) -> Player:
    return Player(
        player_id=player_id,
        name=name,
        team_id=team_id,
        role=role,
        attrs=attrs,
        derived=build_derived(attrs),
        state=PlayerState(x=x, y=y, stamina=1.0, facing_angle=0.0, target_facing_angle=0.0),
    )


def build_sample_match(config: MatchConfig) -> MatchState:
    half_h = config.pitch_height / 2
    right_x = config.pitch_width

    team_a_players = [
        build_player("A_GK", "A", "A_GK", Role.GK, PlayerAttributes(55, 30, 35, 48, 52, 45, 70, 74, 80), 3, half_h),
        build_player("A_AN", "A", "A_Anchor", Role.ANCHOR, PlayerAttributes(76, 52, 68, 63, 64, 72, 76, 80), 9, half_h),
        build_player("A_L", "A", "A_Left", Role.LEFT, PlayerAttributes(74, 66, 75, 78, 77, 73, 61, 76), 13, half_h - 5),
        build_player("A_R", "A", "A_Right", Role.RIGHT, PlayerAttributes(72, 64, 74, 77, 76, 71, 62, 76), 13, half_h + 5),
        build_player("A_P", "A", "A_Pivot", Role.PIVOT, PlayerAttributes(68, 82, 72, 72, 68, 82, 52, 72), 18, half_h),
    ]

    team_b_players = [
        build_player("B_GK", "B", "B_GK", Role.GK, PlayerAttributes(52, 28, 34, 46, 50, 43, 68, 75, 82), right_x - 3, half_h),
        build_player("B_AN", "B", "B_Anchor", Role.ANCHOR, PlayerAttributes(73, 55, 64, 61, 62, 68, 78, 79), right_x - 9, half_h),
        build_player("B_L", "B", "B_Left", Role.LEFT, PlayerAttributes(69, 67, 72, 79, 78, 70, 63, 74), right_x - 13, half_h + 5),
        build_player("B_R", "B", "B_Right", Role.RIGHT, PlayerAttributes(71, 69, 71, 78, 76, 72, 64, 74), right_x - 13, half_h - 5),
        build_player("B_P", "B", "B_Pivot", Role.PIVOT, PlayerAttributes(65, 84, 70, 70, 66, 81, 53, 71), right_x - 18, half_h),
    ]

    team_a = Team(
        team_id="A",
        name="Blue Comets",
        attack_direction=1,
        tactics=TeamTactics(style="Control", base_pressure=0.15),
        state=TeamState(phase=TeamPhase.POSSESSION_BUILD_UP),
        players=team_a_players,
    )
    team_b = Team(
        team_id="B",
        name="Red Arrows",
        attack_direction=-1,
        tactics=TeamTactics(style="Direct", base_pressure=0.2),
        state=TeamState(phase=TeamPhase.DEFENSIVE_SHAPE),
        players=team_b_players,
    )

    kickoff = team_a.players[1]
    kickoff.state.has_ball = True
    for player in team_a.players:
        player.state.facing_angle = 0.0
        player.state.target_facing_angle = 0.0
    for player in team_b.players:
        player.state.facing_angle = 3.141592653589793
        player.state.target_facing_angle = 3.141592653589793
    ball = BallState(
        x=config.pitch_width / 2,
        y=half_h,
        landing_x=config.pitch_width / 2,
        landing_y=half_h,
        owner_team_id=None,
        owner_player_id=None,
        last_touch_team_id=None,
        last_touch_player_id=None,
        last_touch_action=None,
    )

    match = MatchState(
        teams=[team_a, team_b],
        ball=ball,
        stats={"A": TeamStats(), "B": TeamStats()},
        dead_ball=True,
        restart_team_id="A",
        restart_reason="Kickoff",
    )
    
    return match
