from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Role(str, Enum):
    GK = "GK"
    ANCHOR = "ANCHOR"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    PIVOT = "PIVOT"


class TeamPhase(str, Enum):
    POSSESSION_BUILD_UP = "PossessionBuildUp"
    POSSESSION_ATTACK = "PossessionAttack"
    DEFENSIVE_SHAPE = "DefensiveShape"
    HIGH_PRESS = "HighPress"
    RESTART = "Restart"


class PlayerAction(str, Enum):
    IDLE = "idle"
    SUPPORT = "support"
    SPREAD = "spread"
    PRESS = "press"
    RECOVER = "recover"
    DRIBBLE = "dribble"
    PASS = "pass"
    SHOOT = "shoot"


class ReceiveMode(str, Enum):
    NONE = "none"
    COME_SHORT = "come_short"
    MEET_BALL = "meet_ball"
    RUN_ONTO = "run_onto"


class PassType(str, Enum):
    TO_FEET = "to_feet"
    LEAD_PASS = "lead_pass"
    THROUGH_PASS = "through_pass"


@dataclass(slots=True)
class PlayerAttributes:
    passing: float
    shooting: float
    dribbling: float
    speed: float
    acceleration: float
    attack_awareness: float
    defence_awareness: float
    stamina: float
    goalkeeping: float = 20.0


@dataclass(slots=True)
class PlayerDerived:
    move_speed: float
    ball_control: float
    pass_quality: float
    shot_quality: float
    press_quality: float
    recover_quality: float
    save_quality: float
    turn_rate: float


@dataclass(slots=True)
class Intent:
    action: PlayerAction = PlayerAction.IDLE
    target_x: float = 0.0
    target_y: float = 0.0
    target_player_id: Optional[str] = None
    pass_type: Optional[PassType] = None
    pass_speed: float = 0.0


@dataclass(slots=True)
class PlayerState:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    facing_angle: float = 0.0
    target_facing_angle: float = 0.0
    stamina: float = 1.0
    decision_cooldown: float = 0.0
    has_ball: bool = False
    receive_mode: ReceiveMode = ReceiveMode.NONE
    intercept_x: Optional[float] = None
    intercept_y: Optional[float] = None
    intercept_locked_until: float = 0.0
    intent: Intent = field(default_factory=Intent)


@dataclass(slots=True)
class Player:
    player_id: str
    name: str
    team_id: str
    role: Role
    attrs: PlayerAttributes
    derived: PlayerDerived
    state: PlayerState


@dataclass(slots=True)
class TeamTactics:
    style: str
    base_pressure: float


@dataclass(slots=True)
class TeamState:
    phase: TeamPhase
    possession_time: float = 0.0
    last_gain_time: float = 0.0


@dataclass(slots=True)
class Team:
    team_id: str
    name: str
    attack_direction: int
    tactics: TeamTactics
    state: TeamState
    players: list[Player]


@dataclass(slots=True)
class BallState:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    owner_team_id: Optional[str] = None
    owner_player_id: Optional[str] = None
    last_touch_team_id: Optional[str] = None
    last_touch_player_id: Optional[str] = None
    last_touch_action: Optional[PlayerAction] = None


@dataclass(slots=True)
class MatchEvent:
    time_seconds: float
    message: str


@dataclass(slots=True)
class TeamStats:
    shots: int = 0
    shots_on_target: int = 0
    passes_attempted: int = 0
    passes_completed: int = 0
    tackles_won: int = 0
    possession_seconds: float = 0.0
    goals: int = 0


@dataclass(slots=True)
class PlayerSnapshot:
    player_id: str
    name: str
    team_id: str
    role: Role
    x: float
    y: float
    has_ball: bool
    action: PlayerAction
    stamina: float
    facing_angle: float
    target_x: float
    target_y: float
    receive_mode: ReceiveMode
    intercept_x: Optional[float]
    intercept_y: Optional[float]


@dataclass(slots=True)
class BallSnapshot:
    x: float
    y: float
    owner_team_id: Optional[str]
    owner_player_id: Optional[str]


@dataclass(slots=True)
class TeamSnapshot:
    team_id: str
    name: str
    phase: TeamPhase


@dataclass(slots=True)
class FrameSnapshot:
    time_seconds: float
    ball: BallSnapshot
    teams: list[TeamSnapshot]
    players: list[PlayerSnapshot]
    latest_event: str


@dataclass(slots=True)
class MatchState:
    teams: list[Team]
    ball: BallState
    time_seconds: float = 0.0
    events: list[MatchEvent] = field(default_factory=list)
    stats: dict[str, TeamStats] = field(default_factory=dict)
    frames: list[FrameSnapshot] = field(default_factory=list)
    dead_ball: bool = False
    restart_team_id: Optional[str] = None
    restart_reason: str = ""
    passer_player_id: Optional[str] = None
    receiver_player_id: Optional[str] = None
