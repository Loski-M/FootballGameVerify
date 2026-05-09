from python_sim.config import MatchConfig
from python_sim.sample_data import build_sample_match
from python_sim.simulation import MatchSimulator
from python_sim.visualizer import show_match_replay


def main() -> None:
    config = MatchConfig()
    match = build_sample_match(config)
    simulator = MatchSimulator(config, rng_seed=13)
    result = simulator.run(match)
    show_match_replay(result, config)


if __name__ == "__main__":
    main()
