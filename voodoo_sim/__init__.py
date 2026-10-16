"""3dfx Voodoo SST-1 simulation package."""

from .engine import BenchmarkResult, OperatingPoint, SimulationConfig, estimate_operating_point, run_benchmark

__all__ = [
    "BenchmarkResult",
    "OperatingPoint",
    "SimulationConfig",
    "estimate_operating_point",
    "run_benchmark",
]
