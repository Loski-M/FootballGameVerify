from dataclasses import dataclass


@dataclass(slots=True)
class MatchConfig:
    pitch_width: float = 40.0
    pitch_height: float = 24.0
    goal_width: float = 6.0
    tick_seconds: float = 0.2
    match_duration_seconds: float = 180.0
    decision_interval_seconds: float = 0.4
    player_radius: float = 0.6
    ball_control_radius: float = 1.0
    pass_speed: float = 12.0
    shot_speed: float = 18.0
    ball_friction: float = 0.92
    dribble_push: float = 1.1
    support_distance: float = 8.0
    shot_range: float = 13.0
    possession_radius: float = 1.2
    tackle_radius: float = 1.2
    press_radius: float = 4.5
    shot_block_radius: float = 1.2
    fatigue_decay_per_second: float = 0.015
    recovery_decay_per_second: float = 0.006
