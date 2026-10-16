from voodoo_sim.engine import (
    SimulationConfig,
    estimate_crash_probability,
    estimate_operating_point,
    run_benchmark,
)


def test_stock_baseline_is_finite_and_reference_score():
    config = SimulationConfig()
    point = estimate_operating_point(config)
    assert point.performance_score == 1000.0
    assert point.estimated_fps > 0
    assert point.estimated_power_w > 0
    assert point.peak_temp_c >= config.ambient_temp_c
    assert 0 < point.estimated_crash_probability < 1


def test_overclock_increases_modelled_performance_when_both_clocks_rise():
    stock = estimate_operating_point(SimulationConfig())
    overclock = estimate_operating_point(SimulationConfig(core_clock_mhz=57, memory_clock_mhz=57))
    assert overclock.performance_score > stock.performance_score
    assert overclock.estimated_fps > stock.estimated_fps


def test_stronger_cooling_reduces_temperature_for_same_configuration():
    passive = estimate_operating_point(SimulationConfig(cooling_mode="Passiva"))
    fan = estimate_operating_point(SimulationConfig(cooling_mode="Ventilação forte"))
    assert fan.steady_state_temp_c < passive.steady_state_temp_c
    assert fan.peak_temp_c < passive.peak_temp_c


def test_overclock_and_heat_increase_heuristic_risk():
    stock_cfg = SimulationConfig()
    stressed_cfg = SimulationConfig(core_clock_mhz=70, memory_clock_mhz=65, vcore_v=2.5)
    assert estimate_crash_probability(stressed_cfg) > estimate_crash_probability(stock_cfg)


def test_benchmark_seed_is_reproducible():
    config = SimulationConfig(core_clock_mhz=60, memory_clock_mhz=58)
    assert run_benchmark(config, seed=42).crashed == run_benchmark(config, seed=42).crashed


def test_invalid_clocks_are_rejected():
    try:
        SimulationConfig(core_clock_mhz=90)
    except ValueError:
        pass
    else:
        raise AssertionError("A configuração inválida deveria gerar ValueError")
