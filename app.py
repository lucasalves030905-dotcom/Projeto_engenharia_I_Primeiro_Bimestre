from __future__ import annotations

from datetime import timezone

import pandas as pd
import plotly.graph_objects as go
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import streamlit as st

from voodoo_sim.db import (
    clear_benchmark_history,
    delete_profile,
    get_engine,
    get_profile_by_name,
    initialize_database,
    list_benchmarks,
    list_profiles,
    save_benchmark,
    save_profile,
)
from voodoo_sim.engine import (
    MODEL_REFERENCE_VCORE,
    SAFE_TEMP_C,
    SimulationConfig,
    estimate_operating_point,
    run_benchmark,
)


st.set_page_config(
    page_title="SST-1 OC Lab | 3dfx Voodoo Graphics",
    page_icon="🕹️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# App-level styling. Plotly charts use the same dark palette to keep the interface cohesive.
st.markdown(
    """
    <style>
      :root { color-scheme: dark; }
      html, body, [class*="css"] { font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
      .stApp { background: radial-gradient(ellipse at 70% 0%, #172238 0%, #0b1019 38%, #080b11 100%); }
      [data-testid="stSidebar"] { background: #0c121d; border-right: 1px solid #243044; }
      [data-testid="stHeader"] { background: rgba(8,11,17,0.72); }
      .hero { border: 1px solid #2a3d57; border-radius: 18px; padding: 1.3rem 1.5rem; margin: 0 0 1.2rem 0;
              background: linear-gradient(115deg, rgba(24,43,68,.95), rgba(13,21,34,.75)); box-shadow: 0 14px 42px rgba(0,0,0,.18); }
      .hero-kicker { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: #63f6d2; letter-spacing: .16em; font-size: .74rem; text-transform: uppercase; }
      .hero-title { font-size: clamp(1.8rem, 3.1vw, 2.7rem); line-height: 1.07; color: #f3f7ff; font-weight: 700; margin: .4rem 0; }
      .hero-sub { color: #a9b8ce; margin: .2rem 0 0 0; font-size: .98rem; }
      .section-kicker { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: #63f6d2; letter-spacing: .12em; font-size: .75rem; text-transform: uppercase; margin: .2rem 0 .2rem 0; }
      .panel { border: 1px solid #253449; border-radius: 14px; padding: 1rem 1.05rem; background: rgba(14,22,35,.84); }
      .muted { color: #97a8bf; font-size: .88rem; }
      .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
      div[data-testid="stMetric"] { background: rgba(15,24,38,.82); border: 1px solid #26364b; padding: .9rem 1rem; border-radius: 13px; }
      div[data-testid="stMetricLabel"] { color: #9fb1c8; }
      div[data-testid="stMetricValue"] { color: #f1f6ff; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
      .stButton > button { border-radius: 10px; border: 1px solid #3a9b9a; background: linear-gradient(100deg, #1ac9a8, #62e0bf); color: #061219; font-weight: 700; min-height: 2.7rem; }
      .stButton > button:hover { border-color: #7dfbe1; color: #061219; box-shadow: 0 0 22px rgba(73,236,199,.18); }
      .stTabs [data-baseweb="tab-list"] { gap: .5rem; }
      .stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0 0; padding: .65rem .9rem; }
      hr { border-color: #26364b; }
      [data-testid="stAlert"] { border-radius: 12px; }
      footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


def local_time_label(value) -> str:
    """Format SQLAlchemy timestamps in the server's local time zone."""
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def plotly_dark(fig: go.Figure, height: int = 330) -> go.Figure:
    fig.update_layout(
        height=height,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(8,13,21,0.5)",
        margin=dict(l=10, r=14, t=42, b=10),
        font=dict(family="Inter, system-ui, sans-serif", color="#c8d5e7", size=12),
        title_font=dict(size=15, color="#edf4ff"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(gridcolor="#233147", zerolinecolor="#233147", linecolor="#233147"),
        yaxis=dict(gridcolor="#233147", zerolinecolor="#233147", linecolor="#233147"),
    )
    return fig


def get_saved_profiles():
    try:
        return list_profiles()
    except SQLAlchemyError as exc:
        st.error(f"Não foi possível ler os perfis do banco SQLite: {exc}")
        return []


# Initialize persistence once per rerun; engine itself is cached by the data layer.
try:
    initialize_database(get_engine())
    db_available = True
except (OSError, SQLAlchemyError) as exc:
    db_available = False
    st.error(f"Banco de dados indisponível. Verifique permissões do diretório data/. Detalhe: {exc}")

profiles = get_saved_profiles() if db_available else []
profile_names = [p.name for p in profiles]

# Initialize widget state once; profile loading writes to these keys before sliders render.
_widget_defaults = {
    "core_clock_mhz": 50,
    "memory_clock_mhz": 50,
    "vcore_v": MODEL_REFERENCE_VCORE,
    "ambient_temp_c": 25.0,
    "cooling_mode": "Passiva",
    "resolution_label": "640 × 480",
    "workload": "Equilibrada",
    "last_benchmark": None,
    "last_benchmark_id": None,
}
for _key, _value in _widget_defaults.items():
    if _key not in st.session_state:
        st.session_state[_key] = _value

resolution_options = {
    "512 × 384": (512, 384),
    "640 × 400": (640, 400),
    "640 × 480": (640, 480),
    "800 × 600 (experimental)": (800, 600),
}

with st.sidebar:
    st.markdown("<div class='section-kicker'>Hardware console / SST-1</div>", unsafe_allow_html=True)
    st.markdown("## Configuração")
    if not db_available:
        st.caption("Persistência desabilitada enquanto o banco estiver indisponível.")

    if profile_names:
        chosen_profile = st.selectbox("Perfil salvo", options=profile_names, key="chosen_profile")
        if st.button("Carregar perfil", use_container_width=True, key="load_profile_button"):
            try:
                selected = get_profile_by_name(chosen_profile)
                if selected is not None:
                    st.session_state["core_clock_mhz"] = selected.core_clock_mhz
                    st.session_state["memory_clock_mhz"] = selected.memory_clock_mhz
                    st.session_state["vcore_v"] = selected.vcore_v
                    st.session_state["ambient_temp_c"] = selected.ambient_temp_c
                    st.session_state["cooling_mode"] = selected.cooling_mode
                    st.rerun()
            except SQLAlchemyError as exc:
                st.error(f"Falha ao carregar o perfil: {exc}")
    else:
        st.caption("Salve um perfil na aba Perfis para carregá-lo aqui.")

    st.divider()
    st.markdown("**Frequências**")
    core_clock_mhz = st.slider("Core clock (MHz)", 40, 75, key="core_clock_mhz", step=1,
                               help="50 MHz é a frequência de referência. O restante é cenário hipotético de overclock.")
    memory_clock_mhz = st.slider("Memory clock (MHz)", 40, 70, key="memory_clock_mhz", step=1,
                                 help="Memória EDO DRAM; o controle permite explorar a sensibilidade do modelo.")
    st.markdown("**Tensão e ambiente**")
    vcore_v = st.slider("Vcore modelada (V)", 2.0, 3.2, key="vcore_v", step=0.05,
                        help="Parâmetro matemático. Não representa uma tensão universal da SST-1 nem controla hardware real.")
    ambient_temp_c = st.slider("Temperatura ambiente (°C)", 10.0, 40.0, key="ambient_temp_c", step=1.0)
    cooling_mode = st.selectbox("Refrigeração hipotética", ["Passiva", "Fluxo de ar moderado", "Ventilação forte"], key="cooling_mode")
    st.markdown("**Carga gráfica**")
    resolution_label = st.selectbox("Resolução do cenário", list(resolution_options), key="resolution_label")
    workload = st.select_slider("Complexidade da cena", options=["Leve", "Equilibrada", "Pesada"], key="workload")
    st.divider()
    st.caption("SIMULAÇÃO MATEMÁTICA • Não acessa nem altera uma GPU física.")

try:
    config = SimulationConfig(
        core_clock_mhz=core_clock_mhz,
        memory_clock_mhz=memory_clock_mhz,
        vcore_v=round(float(vcore_v), 2),
        ambient_temp_c=float(ambient_temp_c),
        cooling_mode=cooling_mode,
        resolution=resolution_options[resolution_label],
        workload=workload,
        duration_s=120,
    )
except ValueError as exc:
    st.error(f"Configuração inválida: {exc}")
    st.stop()

point = estimate_operating_point(config)
stock_config = SimulationConfig(
    core_clock_mhz=50,
    memory_clock_mhz=50,
    vcore_v=MODEL_REFERENCE_VCORE,
    ambient_temp_c=config.ambient_temp_c,
    cooling_mode=config.cooling_mode,
    resolution=config.resolution,
    workload=config.workload,
    duration_s=config.duration_s,
)
stock_point = estimate_operating_point(stock_config)
relative_fps_delta = (point.estimated_fps / stock_point.estimated_fps - 1.0) * 100.0 if stock_point.estimated_fps else 0.0
relative_score_delta = (point.performance_score / stock_point.performance_score - 1.0) * 100.0 if stock_point.performance_score else 0.0

st.markdown(
    """
    <div class="hero">
      <div class="hero-kicker">3dfx Interactive · 1996 · Engineering sandbox</div>
      <div class="hero-title">VOODOO <span style="color:#63f6d2">SST-1</span> / OC LAB</div>
      <p class="hero-sub">Laboratório de overclock, desempenho estimado e comportamento térmico da Voodoo Graphics.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Metric dashboard
m1, m2, m3, m4 = st.columns(4)
m1.metric("CORE CLOCK", f"{config.core_clock_mhz} MHz", f"{config.core_clock_mhz - 50:+d} MHz vs stock")
m2.metric("MEMORY CLOCK", f"{config.memory_clock_mhz} MHz", f"{config.memory_clock_mhz - 50:+d} MHz vs stock")
m3.metric("FPS ESTIMADO", f"{point.estimated_fps:.1f}", f"{relative_fps_delta:+.1f}% vs baseline")
m4.metric("PERFORMANCE INDEX", f"{point.performance_score:.0f}", f"{relative_score_delta:+.1f}% vs stock")

k1, k2, k3, k4 = st.columns(4)
k1.metric("TEMPERATURA · 120 s", f"{point.peak_temp_c:.1f} °C", f"Regime térmico: {point.steady_state_temp_c:.1f} °C")
k2.metric("POTÊNCIA ESTIMADA", f"{point.estimated_power_w:.1f} W", f"Energia/120 s: {point.estimated_power_w * config.duration_s / 3600:.3f} Wh")
k3.metric("RISCO DE FALHA", f"{point.estimated_crash_probability * 100:.1f}%", "Probabilidade heurística por execução")
k4.metric("FILL RATE MODELADO", f"{point.fill_rate_mpix_s:.1f} MPix/s", f"Largura de banda: {point.estimated_bandwidth_gb_s:.2f} GB/s")

if point.steady_state_temp_c >= SAFE_TEMP_C:
    st.error(f"Alerta térmico do modelo: temperatura de regime {point.steady_state_temp_c:.1f} °C alcança ou ultrapassa o limite configurável de {SAFE_TEMP_C:.0f} °C.")
elif point.steady_state_temp_c >= SAFE_TEMP_C - 5:
    st.warning(f"Margem térmica reduzida no modelo: {point.thermal_headroom_c:.1f} °C até o limite de referência.")
else:
    st.success(f"Margem térmica estimada: {point.thermal_headroom_c:.1f} °C até o limite de referência de {SAFE_TEMP_C:.0f} °C.")

panel_tab, history_tab, profiles_tab, model_tab = st.tabs(["Painel de engenharia", "Histórico de benchmarks", "Perfis de overclock", "Sobre o modelo"])

with panel_tab:
    left, right = st.columns([1.35, 1])
    with left:
        temp_fig = go.Figure()
        temp_fig.add_trace(go.Scatter(
            x=point.temperature_seconds,
            y=point.temperature_c,
            mode="lines",
            name="Temperatura estimada",
            line=dict(color="#63f6d2", width=3, shape="spline"),
            fill="tozeroy",
            fillcolor="rgba(99,246,210,0.08)",
        ))
        temp_fig.add_hline(y=SAFE_TEMP_C, line_dash="dash", line_color="#ff7777", annotation_text=f"Limite do modelo: {SAFE_TEMP_C:.0f} °C", annotation_position="top left")
        temp_fig.update_layout(title="Curva térmica prevista · 120 segundos", xaxis_title="Tempo (s)", yaxis_title="Temperatura (°C)")
        st.plotly_chart(plotly_dark(temp_fig, 350), use_container_width=True, config={"displayModeBar": False})
        st.caption("Curva de aquecimento calculada por um modelo RC simplificado; não é telemetria de uma placa real.")

    with right:
        power_fig = go.Figure()
        power_fig.add_trace(go.Scatter(
            x=point.power_seconds,
            y=point.power_w,
            mode="lines",
            name="Potência estimada",
            line=dict(color="#ffb454", width=3, shape="hv"),
            fill="tozeroy",
            fillcolor="rgba(255,180,84,0.08)",
        ))
        power_fig.update_layout(title="Consumo estimado durante a carga", xaxis_title="Tempo (s)", yaxis_title="Potência (W)")
        st.plotly_chart(plotly_dark(power_fig, 350), use_container_width=True, config={"displayModeBar": False})
        st.caption("A potência é mantida constante durante este cenário; a energia acumulada é potência × tempo.")

    st.markdown("<div class='section-kicker'>Stock vs. configuração atual</div>", unsafe_allow_html=True)
    cmp_left, cmp_right = st.columns([1, 1])
    with cmp_left:
        compare_fig = go.Figure()
        compare_fig.add_trace(go.Bar(name="Stock · 50/50 MHz", x=["FPS estimado"], y=[stock_point.estimated_fps], marker_color="#50647f"))
        compare_fig.add_trace(go.Bar(name="Configuração atual", x=["FPS estimado"], y=[point.estimated_fps], marker_color="#63f6d2"))
        compare_fig.update_layout(title="FPS no mesmo cenário", barmode="group", yaxis_title="FPS estimado", xaxis_title="")
        st.plotly_chart(plotly_dark(compare_fig, 280), use_container_width=True, config={"displayModeBar": False})
    with cmp_right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        st.markdown("**Leitura do cenário**")
        st.markdown(f"- **Desempenho relativo:** {point.performance_ratio:.3f}× a referência do modelo.")
        st.markdown(f"- **Variação de FPS:** {relative_fps_delta:+.1f}% contra 50/50 MHz, mantendo cena e resolução.")
        st.markdown(f"- **Temperatura de regime:** {point.steady_state_temp_c:.1f} °C estimados com refrigeração {config.cooling_mode.lower()}.")
        st.markdown(f"- **Probabilidade de falha:** {point.estimated_crash_probability * 100:.1f}% por tentativa; estimativa heurística.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    run_col, note_col = st.columns([1, 1.6])
    with run_col:
        run_clicked = st.button("▶ Executar benchmark simulado", use_container_width=True, key="run_benchmark_button")
    with note_col:
        st.markdown("<p class='muted'>A execução sorteia um resultado de estabilidade usando a probabilidade modelada e grava a configuração no SQLite. FPS e score são estimativas sintéticas, não resultados medidos em hardware.</p>", unsafe_allow_html=True)

    if run_clicked:
        result = run_benchmark(config)
        op = result.operating_point
        benchmark_id = None
        if db_available:
            try:
                benchmark_id = save_benchmark(
                    core_clock_mhz=config.core_clock_mhz,
                    memory_clock_mhz=config.memory_clock_mhz,
                    vcore_v=config.vcore_v,
                    ambient_temp_c=config.ambient_temp_c,
                    cooling_mode=config.cooling_mode,
                    resolution=f"{config.resolution[0]}x{config.resolution[1]}",
                    workload=config.workload,
                    score=None if result.crashed else op.performance_score,
                    fps_estimate=op.estimated_fps,
                    temp_peak_c=op.peak_temp_c,
                    temp_steady_c=op.steady_state_temp_c,
                    estimated_power_w=op.estimated_power_w,
                    crash_probability=op.estimated_crash_probability,
                    status=result.status,
                )
            except SQLAlchemyError as exc:
                st.error(f"O benchmark foi simulado, mas não foi possível gravar o histórico: {exc}")
        st.session_state["last_benchmark"] = {
            "result": result,
            "config": config,
            "created_label": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        st.session_state["last_benchmark_id"] = benchmark_id

    last = st.session_state.get("last_benchmark")
    if last:
        result = last["result"]
        last_config = last["config"]
        op = result.operating_point
        st.markdown("### Resultado da última execução")
        st.caption(f"Configuração registrada: Core {last_config.core_clock_mhz} MHz · Memória {last_config.memory_clock_mhz} MHz · Vcore do modelo {last_config.vcore_v:.2f} V · {last_config.resolution[0]}×{last_config.resolution[1]} · {last_config.cooling_mode}.")
        if result.crashed:
            st.error(f"CRASH SIMULADO — risco estimado de {op.estimated_crash_probability * 100:.1f}%. O score não foi considerado válido para o histórico.")
        else:
            st.success(f"BENCHMARK CONCLUÍDO — índice estimado {op.performance_score:.0f}, FPS modelado {op.estimated_fps:.1f}, temperatura de pico no intervalo {op.peak_temp_c:.1f} °C.")

with history_tab:
    st.markdown("<div class='section-kicker'>Execuções persistidas</div>", unsafe_allow_html=True)
    st.subheader("Histórico de benchmarks")
    if not db_available:
        st.warning("O histórico não está disponível porque o banco não pôde ser inicializado.")
    else:
        try:
            rows = list_benchmarks(limit=500)
            if not rows:
                st.info("Ainda não há execuções registradas. Use o botão de benchmark na aba Painel de engenharia.")
            else:
                records = []
                for row in rows:
                    records.append({
                        "Data/hora local": local_time_label(row.created_at_utc),
                        "Core (MHz)": row.core_clock_mhz,
                        "Memória (MHz)": row.memory_clock_mhz,
                        "Vcore modelo (V)": round(row.vcore_v, 2),
                        "Resolução": row.resolution,
                        "FPS estimado": round(row.fps_estimate, 1),
                        "Score válido": round(row.score, 0) if row.score is not None else "—",
                        "Pico térmico (°C)": round(row.temp_peak_c, 1),
                        "Regime (°C)": round(row.temp_steady_c, 1),
                        "Potência (W)": round(row.estimated_power_w, 1),
                        "Risco (%)": round(row.crash_probability * 100, 1),
                        "Status": row.status,
                    })
                st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)
                successful = [r for r in rows if r.score is not None]
                if successful:
                    hist_fig = go.Figure()
                    hist_fig.add_trace(go.Scatter(
                        x=[local_time_label(r.created_at_utc) for r in reversed(successful)],
                        y=[r.score for r in reversed(successful)],
                        mode="lines+markers",
                        name="Score simulado",
                        line=dict(color="#63f6d2", width=2),
                        marker=dict(size=7),
                    ))
                    hist_fig.update_layout(title="Evolução do score válido no modelo", xaxis_title="Execução", yaxis_title="Índice de desempenho")
                    st.plotly_chart(plotly_dark(hist_fig, 300), use_container_width=True, config={"displayModeBar": False})
                st.caption("O status 'Crash simulado' é uma amostra probabilística do modelo; não indica falha real da GPU.")

                with st.expander("Limpar histórico de benchmarks"):
                    confirm_delete = st.checkbox("Confirmo apagar permanentemente todo o histórico.", key="confirm_delete_history")
                    if st.button("Apagar histórico", disabled=not confirm_delete, key="delete_history_button"):
                        try:
                            count = clear_benchmark_history()
                            st.success(f"{count} registro(s) removido(s).")
                            st.rerun()
                        except SQLAlchemyError as exc:
                            st.error(f"Não foi possível limpar o histórico: {exc}")
        except SQLAlchemyError as exc:
            st.error(f"Falha ao consultar o histórico: {exc}")

with profiles_tab:
    st.markdown("<div class='section-kicker'>Presets persistidos</div>", unsafe_allow_html=True)
    st.subheader("Perfis de overclock")
    st.write("Os perfis armazenam a configuração e a classificação de estabilidade **estimada pelo modelo**. Essa classificação não substitui um teste real de hardware.")
    with st.form("save_profile_form", clear_on_submit=True):
        profile_name = st.text_input("Nome do perfil", max_chars=100, placeholder="Ex.: 57 MHz · ventilação moderada")
        mark_stable = point.estimated_crash_probability <= 0.05 and point.steady_state_temp_c < SAFE_TEMP_C
        st.caption(f"Configuração atual: {core_clock_mhz}/{memory_clock_mhz} MHz · {vcore_v:.2f} V modelados · risco previsto {point.estimated_crash_probability * 100:.1f}%.")
        st.caption(f"Classificação sugerida: {'ESTÁVEL NO MODELO' if mark_stable else 'RISCO ELEVADO NO MODELO'}.")
        save_profile_clicked = st.form_submit_button("Salvar configuração como perfil", use_container_width=True)
    if save_profile_clicked:
        if not db_available:
            st.error("O banco de dados está indisponível.")
        elif not profile_name.strip():
            st.warning("Informe um nome para o perfil.")
        else:
            try:
                save_profile(
                    name=profile_name,
                    core_clock_mhz=config.core_clock_mhz,
                    memory_clock_mhz=config.memory_clock_mhz,
                    vcore_v=config.vcore_v,
                    ambient_temp_c=config.ambient_temp_c,
                    cooling_mode=config.cooling_mode,
                    is_stable=mark_stable,
                    stability_risk=point.estimated_crash_probability,
                )
                st.success("Perfil salvo no SQLite.")
                st.rerun()
            except IntegrityError:
                st.error("Já existe um perfil com esse nome. Escolha outro nome.")
            except (ValueError, SQLAlchemyError) as exc:
                st.error(f"Não foi possível salvar o perfil: {exc}")

    try:
        saved_profiles = list_profiles() if db_available else []
        if saved_profiles:
            profile_records = [{
                "Nome": p.name,
                "Core (MHz)": p.core_clock_mhz,
                "Memória (MHz)": p.memory_clock_mhz,
                "Vcore modelo (V)": round(p.vcore_v, 2),
                "Refrigeração": p.cooling_mode,
                "Risco estimado (%)": round(p.stability_risk * 100, 1),
                "Classificação do modelo": "Estável no modelo" if p.is_stable else "Risco elevado no modelo",
                "Criado em": local_time_label(p.created_at_utc),
                "ID": p.id,
            } for p in saved_profiles]
            st.dataframe(pd.DataFrame(profile_records), use_container_width=True, hide_index=True)
            delete_options = {f"{p.name} (ID {p.id})": p.id for p in saved_profiles}
            selected_delete = st.selectbox("Perfil a excluir", list(delete_options), key="delete_profile_select")
            confirm_profile_delete = st.checkbox("Confirmo excluir o perfil selecionado.", key="confirm_delete_profile")
            if st.button("Excluir perfil", disabled=not confirm_profile_delete, key="delete_profile_button"):
                try:
                    delete_profile(delete_options[selected_delete])
                    st.success("Perfil excluído.")
                    st.rerun()
                except SQLAlchemyError as exc:
                    st.error(f"Falha ao excluir o perfil: {exc}")
        else:
            st.info("Nenhum perfil salvo até o momento.")
    except SQLAlchemyError as exc:
        st.error(f"Falha ao consultar perfis: {exc}")

with model_tab:
    st.markdown("<div class='section-kicker'>Transparência e limitações</div>", unsafe_allow_html=True)
    st.subheader("O que este simulador representa")
    st.markdown(
        """
        **Especificações históricas usadas como referência**

        - Chipset **SST-1**, lançado em 1996, com clock de referência de **50 MHz**.
        - Memória **EDO DRAM**; placas comuns tinham 4 MB (frame buffer + texturas) e existiam variantes de 6 MB.
        - A Voodoo Graphics era uma aceleradora **3D complementar**: normalmente dependia de uma placa 2D e de um cabo VGA pass-through.
        - Taxa teórica de fill-rate em torno de **50 megapixels/s** no clock nominal.

        **Equações do modelo**

        - **Potência:** `P = 12,5 W × (0,68 × ratio_core + 0,32 × ratio_mem) × (V / 2,5)²`.
        - **Temperatura de regime:** `T∞ = Tambiente + P × Rθ`, com resistência térmica diferente por perfil de refrigeração.
        - **Curva térmica:** `T(t) = Tambiente + (T∞ − Tambiente) × (1 − exp(−t/τ))`.
        - **Desempenho:** combinação ponderada dos ratios de clock, com um termo de gargalo para o subsistema mais lento e ajuste por resolução/carga.
        - **Estabilidade:** probabilidade heurística logística que aumenta com overclock, temperatura e tensão modelada insuficiente. O benchmark sorteia sucesso/falha segundo essa probabilidade.

        **O que não deve ser interpretado como medição**

        FPS e score são âncoras sintéticas para comparações relativas, não resultados de um jogo histórico nem de 3DMark. A fórmula de potência usa 12,5 W como ponto central da faixa aproximada de 10–15 W informada para este projeto. A referência de 2,5 V é uma normalização matemática, não um Vcore universal oficial do SST-1. O limite de 68 °C e os parâmetros térmicos são decisões configuráveis do simulador — não limites certificados pelo fabricante. Fabricante, PCB, memória, dissipador, ambiente, drivers e carga real mudam os resultados.
        """
    )
    st.markdown("**Fontes de referência**")
    st.markdown(
        "- [DOS Days — 3Dfx Voodoo Graphics](https://dosdays.co.uk/topics/Manufacturers/3dfx/3dfx_voodoo.php) — clock, memória, arquitectura, contexto e variantes.\n"
        "- [SST-1 Hardware Specification (3dfx, revisão 1.61; arquivo público)](https://www.bitsavers.org/components/3dfx/Voodoo1_SST-1_Spec_r1.61_199912.pdf) — documentação técnica do fabricante.\n"
        "- [Hardware.fr — Overclocking 3Dfx Voodoo Graphics](https://www.hardware.fr/articles/188-1/overclocking-3dfx-voodoo-graphics.html) — testes históricos relatados com clocks de 50, 57 e 60 MHz e desempenho dependente do benchmark.\n"
        "- [3DFx.eu — Voodoo1](https://3dfx.eu/voodoo1) — diferenças entre variantes e placas parceiras."
    )
    st.info("Este projeto é um simulador didático e de exploração de hipóteses. Não executa firmware, não emula o chip SST-1 em nível de ciclo e não escreve frequências ou tensões em hardware real.")

st.divider()
st.markdown(
    "<p class='muted'>SST-1 OC LAB · Streamlit + SQLAlchemy + SQLite + Plotly · Dados de entrada ajustáveis · Modelo explicável por equações.</p>",
    unsafe_allow_html=True,
)
