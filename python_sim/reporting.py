from __future__ import annotations

from python_sim.models import MatchState


def format_match_report(match: MatchState) -> str:
    lines: list[str] = []
    team_a, team_b = match.teams
    stats_a = match.stats[team_a.team_id]
    stats_b = match.stats[team_b.team_id]

    lines.append(f"Final Score: {team_a.name} {stats_a.goals} - {stats_b.goals} {team_b.name}")
    lines.append("")
    lines.append("Stats:")
    lines.append(
        f"- {team_a.name}: shots={stats_a.shots}, on_target={stats_a.shots_on_target}, "
        f"passes={stats_a.passes_completed}/{stats_a.passes_attempted}, "
        f"tackles={stats_a.tackles_won}, possession={stats_a.possession_seconds:.1f}s"
    )
    lines.append(
        f"- {team_b.name}: shots={stats_b.shots}, on_target={stats_b.shots_on_target}, "
        f"passes={stats_b.passes_completed}/{stats_b.passes_attempted}, "
        f"tackles={stats_b.tackles_won}, possession={stats_b.possession_seconds:.1f}s"
    )
    lines.append("")
    lines.append("Events:")
    for event in match.events:
        lines.append(f"- {event.time_seconds:6.1f}s {event.message}")
    return "\n".join(lines)

