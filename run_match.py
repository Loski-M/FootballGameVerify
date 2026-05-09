from python_sim.config import MatchConfig
from python_sim.reporting import format_match_report
from python_sim.sample_data import build_sample_match
from python_sim.simulation import MatchSimulator


def main() -> None:
    config = MatchConfig()
    match = build_sample_match(config)
    simulator = MatchSimulator(config, rng_seed=13)
    result = simulator.run(match)
    print(format_match_report(result))


if __name__ == "__main__":
    main()
