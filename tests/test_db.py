from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from voodoo_sim.db import (
    initialize_database,
    list_benchmarks,
    list_profiles,
    save_benchmark,
    save_profile,
)


def make_memory_engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_profiles_and_benchmarks_persist_in_sqlite():
    engine = make_memory_engine()
    initialize_database(engine)

    profile_id = save_profile(
        name="57 MHz test",
        core_clock_mhz=57,
        memory_clock_mhz=50,
        vcore_v=2.5,
        ambient_temp_c=25.0,
        cooling_mode="Passiva",
        is_stable=True,
        stability_risk=0.03,
        engine=engine,
    )
    assert profile_id > 0
    profiles = list_profiles(engine)
    assert len(profiles) == 1
    assert profiles[0].name == "57 MHz test"

    benchmark_id = save_benchmark(
        core_clock_mhz=57,
        memory_clock_mhz=50,
        vcore_v=2.5,
        ambient_temp_c=25.0,
        cooling_mode="Passiva",
        resolution="640x480",
        workload="Equilibrada",
        score=1100.0,
        fps_estimate=35.2,
        temp_peak_c=50.0,
        temp_steady_c=62.0,
        estimated_power_w=13.6,
        crash_probability=0.03,
        status="Concluído",
        engine=engine,
    )
    assert benchmark_id > 0
    history = list_benchmarks(engine=engine)
    assert len(history) == 1
    assert history[0].status == "Concluído"
    assert history[0].score == 1100.0
