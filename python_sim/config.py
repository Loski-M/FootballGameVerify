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
    pass_intercept_sample_dt: float = 0.1
    pass_intercept_time_margin: float = 0.15
    pass_intercept_hard_block_margin: float = 0.05
    pass_dynamic_lane_weight: float = 1.3
    pass_terminal_pressure_weight: float = 0.55
    pass_dribble_safety_margin: float = 0.35
    lofted_pass_min_distance: float = 12.5
    lofted_pass_lane_relief: float = 0.55
    lofted_pass_terminal_pressure_weight: float = 1.8
    lofted_pass_receiver_space_weight: float = 0.9
    lofted_pass_decision_bias: float = 1.45
    lofted_pass_gk_decision_bias: float = 0.7

    # --- Dynamic lead distance ---
    # Lead distance = base + receiver_speed * speed_factor + through_extra
    # This is the DESIGNED "how far ahead" of the receiver the ball should arrive,
    # replacing the old lead_time_* emergent approach.
    lead_distance_base: float = 1.5
    lead_distance_speed_factor: float = 0.35
    lead_distance_through_extra: float = 3.5
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
    gravity: float = 18.0
    lofted_pass_vertical_speed: float = 7.5
    lofted_pass_vertical_speed_distance_factor: float = 0.18
    lofted_pass_landing_speed_factor: float = 0.68
    ball_control_max_height_outfield: float = 1.2
    ball_control_max_height_goalkeeper: float = 2.4
    visual_ball_height_offset_px: float = 10.0
    visual_ball_height_scale_px_per_m: float = 6.0
    landing_marker_radius_px: float = 8.0
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
