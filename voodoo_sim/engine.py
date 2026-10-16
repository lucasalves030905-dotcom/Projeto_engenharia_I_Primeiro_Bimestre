"""Parametric simulator for the 3dfx Voodoo Graphics (SST-1).

Important: thermal, power, voltage and FPS outputs are an illustrative engineering
model, not measurements of any particular historical board or an electrical emulator.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Literal


CoolingMode = Literal["Passiva", "Fluxo de ar moderado", "Ventilação forte"]

BASE_CORE_MHZ = 50
BASE_MEMORY_MHZ = 50
# The 2.5 V value is a convenient normalization point for this simulator only.
# It is NOT claimed as a universal, officially adjustable SST-1 Vcore.
MODEL_REFERENCE_VCORE = 2.5
BASE_POWER_W = 12.5  # midpoint of the approximate 10-15 W range used by this project
BASE_FPS_640X480 = 32.0  # synthetic workload anchor, not a historical benchmark result
PIXEL_FILL_RATE_MPIX_S = 50.0
AGGREGATE_MEMORY_BANDWIDTH_GB_S = 0.8  # theoretical model for two independent 64-bit paths
SAFE_TEMP_C = 68.0  # configurable model threshold, not a universal vendor limit

THERMAL_RESISTANCE_C_PER_W: dict[CoolingMode, float] = {
    "Passiva": 2.7,
    "Fluxo de ar moderado": 2.0,
    "Ventilação forte": 1.4,
}
THERMAL_TIME_CONSTANT_S: dict[CoolingMode, float] = {
    "Passiva": 65.0,
    "Fluxo de ar moderado": 45.0,
    "Ventilação forte": 30.0,
}


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    core_clock_mhz: int = BASE_CORE_MHZ
    memory_clock_mhz: int = BASE_MEMORY_MHZ
    vcore_v: float = MODEL_REFERENCE_VCORE
    ambient_temp_c: float = 25.0
    cooling_mode: CoolingMode = "Passiva"
    resolution: tuple[int, int] = (640, 480)
    workload: Literal["Leve", "Equilibrada", "Pesada"] = "Equilibrada"
    duration_s: int = 120

    def __post_init__(self) -> None:
        if not 40 <= self.core_clock_mhz <= 75:
            raise ValueError("Core clock deve ficar entre 40 e 75 MHz neste modelo.")
        if not 40 <= self.memory_clock_mhz <= 70:
            raise ValueError("Memory clock deve ficar entre 40 e 70 MHz neste modelo.")
        if not 2.0 <= self.vcore_v <= 3.2:
            raise ValueError("A tensão modelada deve ficar entre 2,0 e 3,2 V.")
        if not 10.0 <= self.ambient_temp_c <= 40.0:
            raise ValueError("A temperatura ambiente deve ficar entre 10 e 40 °C.")
        if self.cooling_mode not in THERMAL_RESISTANCE_C_PER_W:
            raise ValueError("Modo de refrigeração desconhecido.")
        if self.resolution not in {(512, 384), (640, 400), (640, 480), (800, 600)}:
            raise ValueError("Resolução não suportada pelo cenário de simulação.")
        if self.workload not in {"Leve", "Equilibrada", "Pesada"}:
            raise ValueError("Carga de trabalho desconhecida.")
        if not 30 <= self.duration_s <= 300:
            raise ValueError("Duração deve ficar entre 30 e 300 segundos.")


@dataclass(frozen=True, slots=True)
class OperatingPoint:
    estimated_power_w: float
    steady_state_temp_c: float
    peak_temp_c: float
    estimated_crash_probability: float
    performance_ratio: float
    performance_score: float
    estimated_fps: float
    fill_rate_mpix_s: float
    estimated_bandwidth_gb_s: float
    temperature_seconds: tuple[float, ...]
    temperature_c: tuple[float, ...]
    power_seconds: tuple[float, ...]
    power_w: tuple[float, ...]
    thermal_headroom_c: float


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    crashed: bool
    status: str
    operating_point: OperatingPoint
    seed: int | None = None


def _workload_factor(workload: str) -> float:
    return {"Leve": 1.15, "Equilibrada": 1.0, "Pesada": 0.78}[workload]


def estimate_power_w(config: SimulationConfig) -> float:
    """Estimate board power using a simplified dynamic-power relationship.

    P ~= P0 * weighted_frequency_ratio * (V/Vref)^2.
    The coefficients are modeling assumptions, not recovered SST-1 circuit parameters.
    """
    core_ratio = config.core_clock_mhz / BASE_CORE_MHZ
    memory_ratio = config.memory_clock_mhz / BASE_MEMORY_MHZ
    frequency_factor = 0.68 * core_ratio + 0.32 * memory_ratio
    voltage_factor = (config.vcore_v / MODEL_REFERENCE_VCORE) ** 2
    return max(1.0, BASE_POWER_W * frequency_factor * voltage_factor)


def estimate_crash_probability(
    config: SimulationConfig, steady_state_temp_c: float | None = None
) -> float:
    """Return a heuristic per-run failure probability, not a validated failure rate."""
    core_ratio = config.core_clock_mhz / BASE_CORE_MHZ
    memory_ratio = config.memory_clock_mhz / BASE_MEMORY_MHZ
    if steady_state_temp_c is None:
        power = estimate_power_w(config)
        thermal_r = THERMAL_RESISTANCE_C_PER_W[config.cooling_mode]
        steady_state_temp_c = config.ambient_temp_c + power * thermal_r

    # Logistic score: small default risk; risk rises faster above stock clocks/heat.
    stress = -5.0
    stress += 14.0 * max(0.0, core_ratio - 1.0)
    stress += 12.0 * max(0.0, memory_ratio - 1.0)
    stress += 0.10 * max(0.0, steady_state_temp_c - 55.0)
    stress += 2.5 * max(0.0, 1.0 - config.vcore_v / MODEL_REFERENCE_VCORE)
    stress -= 3.5 * max(0.0, config.vcore_v / MODEL_REFERENCE_VCORE - 1.0)
    # Very high modeled temperature adds a stronger penalty after the safety threshold.
    stress += 0.18 * max(0.0, steady_state_temp_c - SAFE_TEMP_C)
    probability = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, stress))))
    return min(0.995, max(0.001, probability))


def estimate_operating_point(config: SimulationConfig) -> OperatingPoint:
    """Calculate synthetic performance, estimated power, and a transient thermal curve."""
    core_ratio = config.core_clock_mhz / BASE_CORE_MHZ
    memory_ratio = config.memory_clock_mhz / BASE_MEMORY_MHZ
    power = estimate_power_w(config)
    resistance = THERMAL_RESISTANCE_C_PER_W[config.cooling_mode]
    tau = THERMAL_TIME_CONSTANT_S[config.cooling_mode]
    steady_temp = config.ambient_temp_c + power * resistance

    seconds = tuple(range(0, config.duration_s + 1, max(1, config.duration_s // 60)))
    if seconds[-1] != config.duration_s:
        seconds = (*seconds, config.duration_s)
    temps = tuple(
        config.ambient_temp_c + (steady_temp - config.ambient_temp_c) * (1.0 - math.exp(-t / tau))
        for t in seconds
    )
    # Power is nearly constant for the single synthetic load; sampled to share the x-axis.
    powers = tuple(power for _ in seconds)

    # Mixed workload with a memory-bottleneck term. It scales nearly linearly when both
    # clocks move together, while one unchanged subsystem limits some of the gain.
    mixed_ratio = 0.65 * (0.68 * core_ratio + 0.32 * memory_ratio)
    mixed_ratio += 0.35 * min(core_ratio, memory_ratio)
    performance_ratio = max(0.25, mixed_ratio)

    width, height = config.resolution
    resolution_factor = ((640 * 480) / (width * height)) ** 0.70
    fps = BASE_FPS_640X480 * performance_ratio * resolution_factor * _workload_factor(config.workload)
    # Keep the model plausible and avoid nonsensical outputs at extreme control combinations.
    fps = max(1.0, min(240.0, fps))
    score = 1000.0 * performance_ratio
    fill_rate = PIXEL_FILL_RATE_MPIX_S * core_ratio
    bandwidth = AGGREGATE_MEMORY_BANDWIDTH_GB_S * memory_ratio
    risk = estimate_crash_probability(config, steady_temp)

    return OperatingPoint(
        estimated_power_w=power,
        steady_state_temp_c=steady_temp,
        peak_temp_c=max(temps),
        estimated_crash_probability=risk,
        performance_ratio=performance_ratio,
        performance_score=score,
        estimated_fps=fps,
        fill_rate_mpix_s=fill_rate,
        estimated_bandwidth_gb_s=bandwidth,
        temperature_seconds=seconds,
        temperature_c=temps,
        power_seconds=seconds,
        power_w=powers,
        thermal_headroom_c=SAFE_TEMP_C - steady_temp,
    )


def run_benchmark(config: SimulationConfig, seed: int | None = None) -> BenchmarkResult:
    """Run a reproducible (when seed is supplied) probabilistic stability trial."""
    point = estimate_operating_point(config)
    rng = random.Random(seed)
    crashed = rng.random() < point.estimated_crash_probability
    return BenchmarkResult(
        crashed=crashed,
        status="Crash simulado" if crashed else "Concluído",
        operating_point=point,
        seed=seed,
    )
