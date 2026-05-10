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

    # --- Variable pass speed ---
    pass_speed_min: float = 5.5
    pass_speed_max: float = 17.0
    pass_speed_distance_per_m: float = 0.4
    pass_speed_type_through_bonus: float = 2.0
    pass_speed_type_lead_bonus: float = 1.0
    pass_speed_pressure_malus: float = 2.5

    # --- Dynamic lead time ---
    lead_time_min: float = 0.25
    lead_time_flight_fraction: float = 0.85
    lead_time_receiver_speed_factor: float = 0.06
    lead_time_through_extra: float = 0.4
    lead_defender_nudge_radius: float = 2.8
    lead_defender_nudge_strength: float = 1.2

    # --- Pass error model ---
    pass_error_base: float = 0.12
    pass_error_quality_factor: float = 0.85
    pass_error_distance_per_m: float = 0.014
    pass_error_speed_factor: float = 0.03
    pass_error_facing_factor: float = 0.4
    ball_deceleration: float = 3.8  # m/s², uniform deceleration for ground passes
    lead_prediction_quality_factor: float = 0.5  # how much attack_awareness affects lead time accuracy
    # --- Open-space search ---
    open_space_radius: float = 5.0
    open_space_samples: int = 14
    open_space_defender_weight: float = 3.0
    # --- Dribbling ---
    dribble_forward_bias: float = 1.5
    # --- Off-ball support ---
    support_lane_weight: float = 1.5
    # --- Defending ---
    mark_intercept_ratio: float = 0.4

    dribble_push: float = 1.1
    support_distance: float = 8.0
    shot_range: float = 13.0
    possession_radius: float = 1.2
    tackle_radius: float = 1.2
    press_radius: float = 4.5
    shot_block_radius: float = 1.2
    fatigue_decay_per_second: float = 0.015
    recovery_decay_per_second: float = 0.006

    # --- Team coherence ---
    defensive_line_gap_max: float = 8.0     # max longitudinal gap from deepest teammate before pulling back
    attack_layer_gap_max: float = 12.0      # max distance between PIVOT and ANCHOR
    weak_side_width: float = 4.0            # lateral offset when ball is on the opposite flank
