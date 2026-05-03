"""
Optiline— Balanceador de Linha de Produção
=============================================
Três heurísticas: Regra do Maior Candidato, Kilbridge & Wester, Pesos Posicionais (RPW).
Entrada: tarefas, tempos, precedências e Takt Time.
Saída: atribuição de tarefas, métricas e gráficos. Exporta CSV e XLSX.

Executar:
    pip install streamlit pandas numpy plotly networkx openpyxl xlsxwriter
    streamlit run app.py
"""

import io
import math
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import networkx as nx

st.set_page_config(page_title="Balanceador de Linha de Produção",
                   page_icon="⚙️", layout="wide")

# =============================================================================
# UTILITÁRIOS DE DADOS
# =============================================================================

def parse_pred(s):
    if pd.isna(s) or str(s).strip() in ("", "-"):
        return []
    return [p.strip().upper() for p in str(s).split(",") if p.strip()]


def build_structures(df):
    df = df.dropna(subset=["Tarefa"]).copy()
    df["Tarefa"] = df["Tarefa"].astype(str).str.strip().str.upper()
    df["Tempo"] = pd.to_numeric(df["Tempo"], errors="coerce").fillna(0.0)
    df["Predecessores"] = df["Predecessores"].fillna("-").astype(str)

    tasks = df["Tarefa"].tolist()
    times = dict(zip(df["Tarefa"], df["Tempo"].astype(float)))
    predecessors = {t: [] for t in tasks}
    successors   = {t: [] for t in tasks}

    for _, row in df.iterrows():
        t = row["Tarefa"]
        preds = [p for p in parse_pred(row["Predecessores"]) if p in tasks]
        predecessors[t] = preds
        for p in preds:
            successors[p].append(t)

    return tasks, times, predecessors, successors, df


def normalize_df(df):
    df = df.copy()
    if "Tarefa" in df.columns:
        df["Tarefa"] = df["Tarefa"].astype(str)
    if "Tempo" in df.columns:
        df["Tempo"] = pd.to_numeric(df["Tempo"], errors="coerce").astype(float)
    if "Predecessores" in df.columns:
        df["Predecessores"] = df["Predecessores"].fillna("-").astype(str)
    cols = [c for c in ["Tarefa", "Tempo", "Predecessores"] if c in df.columns]
    return df[cols]


def validate(tasks, times, predecessors, takt_time):
    if not tasks:
        return False, "Adicione ao menos uma tarefa."
    if len(tasks) != len(set(tasks)):
        return False, "Há nomes de tarefa duplicados."
    for t, preds in predecessors.items():
        for p in preds:
            if p not in tasks:
                return False, f"Predecessor '{p}' da tarefa '{t}' não existe."
    if takt_time <= 0:
        return False, "Takt Time deve ser maior que zero."
    mx = max(times.values()) if times else 0
    if mx > takt_time:
        return False, (f"Takt Time ({takt_time:.2f}) é menor que a maior "
                       f"tarefa ({mx:.2f}). Aumente o TT ou fracione a tarefa.")
    G = nx.DiGraph()
    G.add_nodes_from(tasks)
    for t, pl in predecessors.items():
        for p in pl:
            G.add_edge(p, t)
    cycles = list(nx.simple_cycles(G))
    if cycles:
        return False, f"Ciclo nas precedências: {' → '.join(cycles[0])}"
    return True, ""


# =============================================================================
# NÚCLEO DE ALOCAÇÃO (comum aos três métodos)
# =============================================================================

def _allocate(ordered_tasks, times, predecessors, takt_time):
    """Aloca tarefas em estações usando a ordem fornecida + restrições."""
    stations, cur, cur_t, assigned = [], [], 0.0, set()
    rem = list(ordered_tasks)
    while rem:
        picked = None
        for t in rem:
            if (all(p in assigned for p in predecessors.get(t, []))
                    and cur_t + times[t] <= takt_time + 1e-9):
                picked = t
                break
        if picked is not None:
            cur.append(picked)
            cur_t += times[picked]
            assigned.add(picked)
            rem.remove(picked)
        else:
            if cur:
                stations.append(cur)
                cur, cur_t = [], 0.0
            else:
                # tarefa viável por precedência mas não cabe no TT → força nova estação
                for t in rem:
                    if all(p in assigned for p in predecessors.get(t, [])):
                        stations.append([t])
                        assigned.add(t)
                        rem.remove(t)
                        break
                else:
                    break  # ciclo não resolvível (já validado antes)
    if cur:
        stations.append(cur)
    return stations


# =============================================================================
# HEURÍSTICA 1 — REGRA DO MAIOR CANDIDATO
# =============================================================================

def balance_largest_candidate(tasks, times, predecessors, takt_time):
    """Ordena por T_ek decrescente; desempate: nome."""
    ordered = sorted(tasks, key=lambda t: (-times[t], t))
    stations = _allocate(ordered, times, predecessors, takt_time)
    return stations, None   # sem estrutura auxiliar


# =============================================================================
# HEURÍSTICA 2 — KILBRIDGE & WESTER
# =============================================================================

def _column_depths(tasks, predecessors):
    """Retorna dict tarefa → profundidade topológica (coluna)."""
    G = nx.DiGraph()
    G.add_nodes_from(tasks)
    for t, pl in predecessors.items():
        for p in pl:
            if p in tasks:
                G.add_edge(p, t)
    depths = {}
    try:
        for t in nx.topological_sort(G):
            p_list = list(G.predecessors(t))
            depths[t] = 0 if not p_list else max(depths[p] for p in p_list) + 1
    except nx.NetworkXUnfeasible:
        depths = {t: 0 for t in tasks}
    return depths


def balance_kilbridge_wester(tasks, times, predecessors, takt_time):
    """
    Ordena por coluna (topológica) e, dentro de cada coluna, por T_ek decrescente.
    Tarefas que aparecem em mais de uma coluna são listadas com a coluna mínima.
    """
    depths = _column_depths(tasks, predecessors)
    # Para cada tarefa, anota a(s) coluna(s); usa a menor coluna possível na lista
    ordered = sorted(tasks, key=lambda t: (depths[t], -times[t], t))
    stations = _allocate(ordered, times, predecessors, takt_time)
    return stations, depths


# =============================================================================
# HEURÍSTICA 3 — PESOS POSICIONAIS (RPW / Helgeson-Birnie, 1961)
# =============================================================================

def _all_successors(task, successors):
    seen, stack = set(), list(successors.get(task, []))
    while stack:
        x = stack.pop()
        if x not in seen:
            seen.add(x)
            stack.extend(successors.get(x, []))
    return seen


def balance_rpw(tasks, times, predecessors, successors, takt_time):
    pw = {t: times[t] + sum(times[d] for d in _all_successors(t, successors))
          for t in tasks}
    ordered = sorted(tasks, key=lambda t: (-pw[t], t))
    stations = _allocate(ordered, times, predecessors, takt_time)
    return stations, pw


# =============================================================================
# MÉTRICAS
# =============================================================================

def compute_metrics(stations, times, takt_time):
    n = len(stations)
    total = sum(times.values())
    st_t = [sum(times[t] for t in s) for s in stations]
    smax = max(st_t) if st_t else 0
    eff = total / (n * takt_time) * 100 if n else 0
    smoothness = math.sqrt(sum((smax - x) ** 2 for x in st_t)) if st_t else 0
    return {
        "n_stations":    n,
        "total_time":    total,
        "station_times": st_t,
        "tc_effective":  smax,
        "efficiency":    eff,
        "balance_delay": 100 - eff,
        "smoothness":    smoothness,
        "theoretical_min": int(math.ceil(total / takt_time)) if takt_time else 0,
        "idle_total":    n * takt_time - total if n else 0,
    }


# =============================================================================
# DIAGRAMA DE PRECEDÊNCIA
# =============================================================================

STATION_PALETTE = [
    "#2E86AB", "#A23B72", "#F18F01", "#3CB371", "#C73E1D",
    "#6A4C93", "#1982C4", "#FFCA3A", "#8AC926", "#FF595E",
    "#6D597A", "#B56576", "#E56B6F", "#EAAC8B", "#355070",
]


def hierarchical_positions(tasks, predecessors):
    G = nx.DiGraph()
    G.add_nodes_from(tasks)
    for t, pl in predecessors.items():
        for p in pl:
            if p in tasks:
                G.add_edge(p, t)
    try:
        depths = {}
        for t in nx.topological_sort(G):
            p_list = list(G.predecessors(t))
            depths[t] = 0 if not p_list else max(depths[p] for p in p_list) + 1
    except nx.NetworkXUnfeasible:
        depths = {t: 0 for t in tasks}

    depth_groups = {}
    for t, d in depths.items():
        depth_groups.setdefault(d, []).append(t)

    pos = {}
    x_spacing, y_spacing = 2.2, 1.6
    for d, group in depth_groups.items():
        group_sorted = sorted(group)
        n = len(group_sorted)
        for i, t in enumerate(group_sorted):
            y = -(i - (n - 1) / 2) * y_spacing
            pos[t] = (d * x_spacing, y)
    return pos, G


def draw_precedence(tasks, times, predecessors,
                    task_to_station=None, title="Diagrama de Precedência"):
    if not tasks:
        fig = go.Figure()
        fig.add_annotation(text="Preencha as tarefas para visualizar o diagrama",
                           showarrow=False, font=dict(size=14, color="gray"))
        fig.update_layout(height=400,
                          xaxis=dict(visible=False), yaxis=dict(visible=False))
        return fig

    pos, G = hierarchical_positions(tasks, predecessors)
    node_radius = 0.42
    arrows = []
    for u, v in G.edges():
        x0, y0 = pos[u]; x1, y1 = pos[v]
        dx, dy = x1 - x0, y1 - y0
        L = math.sqrt(dx*dx + dy*dy) or 1
        ux, uy = dx/L, dy/L
        sx, sy = x0 + ux*node_radius, y0 + uy*node_radius
        ex, ey = x1 - ux*node_radius, y1 - uy*node_radius
        arrows.append(dict(ax=sx, ay=sy, x=ex, y=ey,
                           xref="x", yref="y", axref="x", ayref="y",
                           showarrow=True, arrowhead=3, arrowsize=1.4,
                           arrowwidth=1.8, arrowcolor="#4a4a4a"))

    if task_to_station is not None:
        node_colors = [STATION_PALETTE[task_to_station[t] % len(STATION_PALETTE)]
                       for t in G.nodes()]
    else:
        node_colors = ["#E8E8E8"] * len(G.nodes())

    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]
    node_hover = [
        f"<b>{n}</b><br>Tempo: {times[n]:.2f}"
        + (f"<br>Estação: E{task_to_station[n]+1}" if task_to_station else "")
        for n in G.nodes()
    ]

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        text=[n for n in G.nodes()], textposition="middle center",
        textfont=dict(color="white" if task_to_station else "#222",
                      size=15, family="Arial Black"),
        marker=dict(size=55, color=node_colors,
                    line=dict(width=2.5,
                              color="white" if task_to_station else "#4a4a4a")),
        hovertext=node_hover, hoverinfo="text", showlegend=False,
    )
    time_labels = go.Scatter(
        x=node_x, y=[y - 0.7 for y in node_y], mode="text",
        text=[f"<b>t={times[n]:g}</b>" for n in G.nodes()],
        textfont=dict(size=11, color="#333"),
        hoverinfo="skip", showlegend=False,
    )
    fig = go.Figure(data=[node_trace, time_labels])
    fig.update_layout(
        title=dict(text=title, x=0.01, font=dict(size=15)),
        showlegend=False, height=440,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                   scaleanchor="x", scaleratio=1),
        annotations=arrows,
        margin=dict(t=50, b=20, l=20, r=20), plot_bgcolor="white",
    )
    return fig


# =============================================================================
# EXPORTAÇÃO XLSX
# =============================================================================

def build_xlsx(result_df: pd.DataFrame,
               pw_df: pd.DataFrame | None,
               kw_cols: dict | None,
               metrics: dict,
               takt_time: float,
               method_name: str) -> bytes:
    """Gera workbook Excel com abas: Atribuição, Métricas, e opcionais."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        wb = writer.book

        # ---- formatos ----
        hdr = wb.add_format({"bold": True, "bg_color": "#2E86AB",
                             "font_color": "white", "border": 1, "align": "center"})
        cell = wb.add_format({"border": 1})
        num2 = wb.add_format({"border": 1, "num_format": "0.00"})
        pct  = wb.add_format({"border": 1, "num_format": "0.00%"})
        title_fmt = wb.add_format({"bold": True, "font_size": 13})

        # ---- aba Atribuição ----
        result_df.to_excel(writer, sheet_name="Atribuição", index=False)
        ws = writer.sheets["Atribuição"]
        for col_num, col_name in enumerate(result_df.columns):
            ws.write(0, col_num, col_name, hdr)
            ws.set_column(col_num, col_num, max(len(col_name) + 4,
                          result_df[col_name].astype(str).str.len().max() + 2))

        # ---- aba Métricas ----
        ws_m = wb.add_worksheet("Métricas")
        ws_m.write(0, 0, f"Método: {method_name}", title_fmt)
        rows_m = [
            ("Takt Time (TT)",            takt_time),
            ("Tempo de Ciclo efetivo (TC)", metrics["tc_effective"]),
            ("Folga TT − TC",             takt_time - metrics["tc_effective"]),
            ("Nº de estações",            metrics["n_stations"]),
            ("Mínimo teórico de estações", metrics["theoretical_min"]),
            ("Tempo total de trabalho",   metrics["total_time"]),
            ("Tempo ocioso total",        metrics["idle_total"]),
            ("Eficiência (%)",            metrics["efficiency"]),
            ("Atraso de balanceamento (%)", metrics["balance_delay"]),
            ("Índice de suavidade (IS)",  metrics["smoothness"]),
        ]
        ws_m.write(1, 0, "Indicador", hdr)
        ws_m.write(1, 1, "Valor",     hdr)
        ws_m.set_column(0, 0, 35)
        ws_m.set_column(1, 1, 18)
        for i, (label, val) in enumerate(rows_m, start=2):
            ws_m.write(i, 0, label, cell)
            ws_m.write(i, 1, val,   num2)

        # ---- aba Pesos Posicionais (RPW) ----
        if pw_df is not None:
            pw_df.to_excel(writer, sheet_name="Pesos Posicionais", index=False)
            ws_p = writer.sheets["Pesos Posicionais"]
            for col_num, col_name in enumerate(pw_df.columns):
                ws_p.write(0, col_num, col_name, hdr)
                ws_p.set_column(col_num, col_num, max(len(col_name)+4, 14))

        # ---- aba Colunas K&W ----
        if kw_cols is not None:
            kw_df = pd.DataFrame([
                {"Tarefa": t, "Coluna (K&W)": v+1}
                for t, v in kw_cols.items()
            ]).sort_values(["Coluna (K&W)", "Tarefa"])
            kw_df.to_excel(writer, sheet_name="Colunas K&W", index=False)
            ws_k = writer.sheets["Colunas K&W"]
            for col_num, col_name in enumerate(kw_df.columns):
                ws_k.write(0, col_num, col_name, hdr)
                ws_k.set_column(col_num, col_num, 16)

    return buf.getvalue()


# =============================================================================
# DADOS DE EXEMPLO E ESTADO
# =============================================================================

EXAMPLE = pd.DataFrame({
    "Tarefa":        ["1","2","3","4","5","6","7","8","9","10","11","12"],
    "Tempo":         [0.2, 0.4, 0.7, 0.1, 0.3, 0.11, 0.32, 0.6, 0.27, 0.38, 0.5, 0.12],
    "Predecessores": ["-", "-", "1", "1,2", "2", "3", "3", "3,4", "6,7,8", "5,8", "9,10", "11"],
})

EMPTY = pd.DataFrame({
    "Tarefa": pd.Series(dtype="str"),
    "Tempo":  pd.Series(dtype="float"),
    "Predecessores": pd.Series(dtype="str"),
})

# =============================================================================
# INTERFACE — SIDEBAR
# =============================================================================

with st.sidebar:
    st.header("📊 Parâmetros de Produção")

    mode = st.radio("Como definir o Takt Time?",
                    ["A partir da demanda", "Valor direto"])
    if mode == "A partir da demanda":
        avail  = st.number_input("Tempo disponível por turno", min_value=1.0,
                                 value=480.0, step=10.0)
        demand = st.number_input("Demanda por turno (unidades)",
                                 min_value=1, value=60, step=1)
        takt_time = avail / demand
        st.metric("Takt Time (TT)", f"{takt_time:.3f}")
        st.caption("⚠️ Mesma unidade dos tempos das tarefas.")
    else:
        takt_time = st.number_input("Takt Time (TT)", min_value=0.01,
                                    value=1.0, step=0.1)

    st.divider()
    st.subheader("🔧 Método heurístico")
    method = st.radio(
        "Selecione o método:",
        ["Regra do Maior Candidato",
         "Método de Kilbridge & Wester",
         "Método dos Pesos Posicionais (RPW)"],
        help=(
            "**Maior Candidato** — ordena por tempo decrescente.\n\n"
            "**Kilbridge & Wester** — organiza por colunas topológicas.\n\n"
            "**RPW** — ordena pelo peso posicional (tempo próprio + sucessores)."
        )
    )

    st.divider()
    st.subheader("Carregar dados")
    c1, c2 = st.columns(2)
    if c1.button("📋 Exemplo", use_container_width=True):
        st.session_state["data"] = normalize_df(EXAMPLE)
    if c2.button("🗑️ Limpar", use_container_width=True):
        st.session_state["data"] = normalize_df(EMPTY)

    up = st.file_uploader("Enviar CSV ou XLSX", type=["csv", "xlsx"])
    if up is not None:
        try:
            if up.name.endswith(".xlsx"):
                st.session_state["data"] = normalize_df(pd.read_excel(up))
            else:
                st.session_state["data"] = normalize_df(pd.read_csv(up))
        except Exception as e:
            st.error(f"Erro ao carregar arquivo: {e}")

    with st.expander("ℹ️ Formato esperado (CSV / XLSX)"):
        st.markdown("Colunas: **Tarefa**, **Tempo**, **Predecessores**")
        st.code(
            "Tarefa,Tempo,Predecessores\n"
            "A,5,-\n"
            "B,3,A\n"
            "C,4,A\n"
            'D,3,"B,C"\n',
            language="csv"
        )

    st.divider()
    with st.expander("📖 Conceitos"):
        st.markdown(
            "- **Takt Time (TT)** — ritmo imposto pela demanda. Limite máximo por estação.\n"
            "- **Tempo de Ciclo (TC)** — tempo entre saídas; igual ao tempo da estação mais carregada.\n"
            "- **Eficiência** — ΣTᵢ ÷ (n × TT) × 100%.\n"
            "- **Atraso de balanceamento** — 100% − Eficiência.\n"
            "- **Índice de Suavidade (IS)** — √Σ(S_max − Sₚ)² (Gerhardt, 2007).\n"
            "- **RPW** — peso posicional = tempo da tarefa + soma dos tempos de todos os sucessores (Helgeson & Birnie, 1961)."
        )
    with st.expander("ℹ️ Sobre"):
        st.markdown(
            "Simulador acadêmico — Tópicos Especiais em Gestão da Produção, "
            "UFPE Campus Agreste.\n\n"
            "Heurísticas: Regra do Maior Candidato, Kilbridge & Wester, RPW "
            "(conforme Groover, *Automação Industrial e Sistemas de Fabricação*, Cap. 15)."
        )

# =============================================================================
# ESTADO
# =============================================================================

if "data" not in st.session_state:
    st.session_state["data"] = normalize_df(EXAMPLE)

# =============================================================================
# LAYOUT PRINCIPAL
# =============================================================================

st.title("⚙️ OptiLine — Balanceador de Linha de Produção")
st.caption(
    "Preencha as tarefas, tempos e precedências. Selecione o método na barra "
    "lateral e clique em **Balancear linha**."
)

left, right = st.columns([1, 1.2], gap="large")

with left:
    st.subheader("📝 1. Dados do processo")
    st.caption("Predecessores separados por vírgula; use '-' para sem predecessor.")

    edited = st.data_editor(
        st.session_state["data"],
        num_rows="dynamic",
        use_container_width=True,
        height=380,
        column_config={
            "Tarefa": st.column_config.TextColumn(
                "Tarefa", required=True, width="small"),
            "Tempo": st.column_config.NumberColumn(
                "Tempo", min_value=0.0, required=True,
                format="%.3f", width="small"),
            "Predecessores": st.column_config.TextColumn(
                "Predecessores", width="medium",
                help="Ex.: A   ou   A,B   ou   -"),
        },
        key="editor",
    )

    if not edited.empty and edited["Tarefa"].notna().any():
        tmp_tasks, tmp_times, tmp_preds, tmp_succs, _ = build_structures(edited)
        total = sum(tmp_times.values())
        if takt_time > 0 and tmp_times:
            min_st = math.ceil(total / takt_time) if total > 0 else 0
            q1, q2, q3 = st.columns(3)
            q1.metric("Tarefas", len(tmp_tasks))
            q2.metric("Tempo total", f"{total:.3f}")
            q3.metric("Estações mín.", f"{min_st}",
                      help="Limite inferior teórico: ⌈ΣT ÷ TT⌉")

with right:
    st.subheader("🔗 2. Diagrama de Precedência")
    if not edited.empty and edited["Tarefa"].notna().any():
        tasks_v, times_v, preds_v, succs_v, _ = build_structures(edited)
        st.plotly_chart(
            draw_precedence(tasks_v, times_v, preds_v,
                            title="Diagrama atual (sem estações)"),
            use_container_width=True
        )
    else:
        st.info("Preencha a tabela à esquerda para ver o diagrama.")

# =============================================================================
# BOTÃO DE BALANCEAMENTO
# =============================================================================

st.divider()

method_labels = {
    "Regra do Maior Candidato":              "Regra do Maior Candidato",
    "Método de Kilbridge & Wester":          "Kilbridge & Wester",
    "Método dos Pesos Posicionais (RPW)":    "Pesos Posicionais (RPW)",
}
run = st.button(
    f"🚀 Balancear linha — {method_labels[method]}",
    type="primary", use_container_width=True
)

if run:
    if edited.empty or edited["Tarefa"].isna().all():
        st.error("Adicione tarefas antes de balancear.")
        st.stop()

    tasks, times, predecessors, successors, df = build_structures(edited)
    ok, msg = validate(tasks, times, predecessors, takt_time)
    if not ok:
        st.error(msg)
        st.stop()

    # ---- Executar heurística selecionada ----
    pw_data   = None   # dict de pesos posicionais (RPW)
    kw_depths = None   # dict tarefa → coluna (K&W)

    if method == "Regra do Maior Candidato":
        stations, _ = balance_largest_candidate(tasks, times, predecessors, takt_time)

    elif method == "Método de Kilbridge & Wester":
        stations, kw_depths = balance_kilbridge_wester(tasks, times, predecessors, takt_time)

    else:  # RPW
        stations, pw_data = balance_rpw(tasks, times, predecessors, successors, takt_time)

    metrics = compute_metrics(stations, times, takt_time)
    task_to_station = {t: i for i, s in enumerate(stations) for t in s}

    # ====================================================================
    # RESULTADOS
    # ====================================================================

    st.divider()
    st.subheader(f"✅ 3. Resultado — {method_labels[method]}")

    # ---- TT vs TC ----
    c1, c2, c3 = st.columns(3)
    c1.metric("Takt Time (TT)", f"{takt_time:.3f}")
    c2.metric("Tempo de Ciclo (TC)", f"{metrics['tc_effective']:.3f}",
              delta=f"{metrics['tc_effective'] - takt_time:+.3f} vs TT",
              delta_color="off")
    c3.metric("Folga (TT − TC)", f"{takt_time - metrics['tc_effective']:.3f}")

    # ---- Métricas principais ----
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Estações", metrics["n_stations"],
              delta=(metrics["n_stations"] - metrics["theoretical_min"] or None),
              delta_color="inverse",
              help=f"Mínimo teórico: {metrics['theoretical_min']}")
    m2.metric("Eficiência", f"{metrics['efficiency']:.2f}%")
    m3.metric("Atraso balanceamento", f"{metrics['balance_delay']:.2f}%")
    m4.metric("Tempo ocioso total", f"{metrics['idle_total']:.3f}")
    m5.metric("Índice de Suavidade", f"{metrics['smoothness']:.4f}",
              help="√Σ(S_max − Sₚ)²  (Gerhardt, 2007). Menor = melhor.")

    # ---- Diagrama + gráfico ----
    cA, cB = st.columns([1.2, 1], gap="large")

    with cA:
        st.markdown("**🔗 Diagrama com estações atribuídas**")
        st.plotly_chart(
            draw_precedence(tasks, times, predecessors, task_to_station,
                            title="Cor = estação de trabalho"),
            use_container_width=True
        )

    with cB:
        st.markdown("**📊 Carga por estação**")
        fig_bar = go.Figure()
        for i, s in enumerate(stations):
            for task in s:
                fig_bar.add_trace(go.Bar(
                    x=[f"E{i+1}"], y=[times[task]],
                    name=task,
                    text=[f"{task}<br>{times[task]:g}"],
                    textposition="inside",
                    textfont=dict(color="white", size=11),
                    marker=dict(color=STATION_PALETTE[i % len(STATION_PALETTE)],
                                line=dict(color="white", width=1.5)),
                    hovertemplate=(f"<b>{task}</b><br>Tempo: {times[task]:g}"
                                   f"<br>Estação: E{i+1}<extra></extra>"),
                    showlegend=False,
                ))
        fig_bar.add_hline(y=takt_time, line_dash="dash", line_color="red",
                          annotation_text=f"TT = {takt_time:.3f}",
                          annotation_position="top right")
        if abs(metrics['tc_effective'] - takt_time) > 1e-6:
            fig_bar.add_hline(y=metrics['tc_effective'], line_dash="dot",
                              line_color="green",
                              annotation_text=f"TC = {metrics['tc_effective']:.3f}",
                              annotation_position="bottom right")
        fig_bar.update_layout(
            barmode="stack", xaxis_title="Estação", yaxis_title="Tempo",
            height=440, plot_bgcolor="white",
            margin=dict(t=50, b=40, l=40, r=20),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # ---- Tabela de atribuição ----
    st.markdown("**📋 Atribuição detalhada**")
    rows = []
    for i, s in enumerate(stations, 1):
        st_t = sum(times[t] for t in s)
        row = {
            "Estação": f"E{i}",
            "Tarefas": " → ".join(s),
            "Tempo da estação": round(st_t, 4),
            "Ociosidade (TT − tempo)": round(takt_time - st_t, 4),
            "Uso (% do TT)": round(st_t / takt_time * 100, 2),
        }
        if kw_depths:
            row["Colunas (K&W)"] = ", ".join(
                str(kw_depths[t]+1) for t in s
            )
        rows.append(row)
    result_df = pd.DataFrame(rows)
    st.dataframe(result_df, use_container_width=True, hide_index=True)

    # ---- Painel auxiliar por método ----
    if pw_data is not None:
        with st.expander("🧮 Pesos Posicionais — ordem de atribuição"):
            pw_df = pd.DataFrame({
                "Tarefa": list(pw_data.keys()),
                "Tempo": [times[t] for t in pw_data.keys()],
                "Peso Posicional (RPW)": [round(v, 4) for v in pw_data.values()],
                "Estação": [f"E{task_to_station[t]+1}" for t in pw_data.keys()],
            }).sort_values("Peso Posicional (RPW)", ascending=False).reset_index(drop=True)
            st.dataframe(pw_df, use_container_width=True, hide_index=True)
            st.caption("RPW = tempo da tarefa + soma dos tempos de todos os sucessores.")
    else:
        pw_df = None

    if kw_depths is not None:
        with st.expander("🗂️ Colunas topológicas (Kilbridge & Wester)"):
            kw_table = pd.DataFrame([
                {"Tarefa": t,
                 "Coluna": kw_depths[t]+1,
                 "Tempo": times[t],
                 "Estação": f"E{task_to_station[t]+1}"}
                for t in sorted(tasks, key=lambda x: (kw_depths[x], x))
            ])
            st.dataframe(kw_table, use_container_width=True, hide_index=True)

    # ====================================================================
    # EXPORTAÇÃO
    # ====================================================================

    st.divider()
    st.subheader("⬇️ Exportar resultados")

    exp1, exp2 = st.columns(2)

    # --- CSV ---
    with exp1:
        st.download_button(
            "📄 Baixar atribuição (CSV)",
            result_df.to_csv(index=False).encode("utf-8"),
            f"balanceamento_{method_labels[method].replace(' ','_')}.csv",
            "text/csv",
            use_container_width=True,
        )

    # --- XLSX ---
    with exp2:
        xlsx_bytes = build_xlsx(
            result_df=result_df,
            pw_df=pw_df if pw_data else None,
            kw_cols=kw_depths,
            metrics=metrics,
            takt_time=takt_time,
            method_name=method_labels[method],
        )
        st.download_button(
            "📊 Baixar relatório completo (XLSX)",
            xlsx_bytes,
            f"balanceamento_{method_labels[method].replace(' ','_')}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.caption(
        "O arquivo XLSX contém abas: **Atribuição**, **Métricas**, "
        + ("**Pesos Posicionais**, " if pw_data else "")
        + ("**Colunas K&W**, " if kw_depths else "")
        + "prontas para uso em relatórios."
    )
