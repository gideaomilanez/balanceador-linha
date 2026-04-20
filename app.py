"""
Balanceador de Linha de Produção — Streamlit
=============================================
Simulador para balanceamento de linhas de produção utilizando a heurística
do Peso Posicional (RPW / Ranked Positional Weight / Helgeson-Birnie, 1961).

Entrada: tarefas, tempos, precedências e Takt Time.

Inspirado no software acadêmico "Flexible Line Balancing" de Stephen Ebert
(University of Wisconsin-Stout), sem reutilização de código.

Nomenclatura:
  Takt Time (TT)      = ritmo imposto pela demanda; limite máximo por estação.
  Tempo de Ciclo (TC) = tempo real entre saídas consecutivas; igual ao tempo
                        da estação mais carregada após o balanceamento.
  Eficiência          = ΣTi / (n × TT) × 100
  Atraso de balanc.   = 100 − Eficiência
  Tempo ocioso total  = n × TT − ΣTi

Executar:
    pip install streamlit pandas numpy plotly networkx
    streamlit run app.py
"""

import math
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import networkx as nx

st.set_page_config(page_title="Balanceador de Linha de Produção",
                   page_icon="⚙️", layout="wide")

# =============================================================================
# LÓGICA (RPW)
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
    successors = {t: [] for t in tasks}

    for _, row in df.iterrows():
        t = row["Tarefa"]
        preds = [p for p in parse_pred(row["Predecessores"]) if p in tasks]
        predecessors[t] = preds
        for p in preds:
            successors[p].append(t)

    return tasks, times, predecessors, successors, df


def all_successors(task, successors):
    seen, stack = set(), list(successors.get(task, []))
    while stack:
        x = stack.pop()
        if x not in seen:
            seen.add(x)
            stack.extend(successors.get(x, []))
    return seen


def compute_rpw(tasks, times, successors):
    return {t: times[t] + sum(times[d] for d in all_successors(t, successors))
            for t in tasks}


def balance_rpw(tasks, times, predecessors, successors, takt_time):
    """Balanceia a linha com RPW respeitando o Takt Time como limite máximo."""
    pw = compute_rpw(tasks, times, successors)
    sorted_tasks = sorted(tasks, key=lambda t: (-pw[t], t))
    stations, cur, cur_t, assigned = [], [], 0.0, set()
    rem = list(sorted_tasks)
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
                break
    if cur:
        stations.append(cur)
    return stations, pw


def compute_metrics(stations, times, takt_time):
    n = len(stations)
    total = sum(times.values())
    st_t = [sum(times[t] for t in s) for s in stations]
    eff = total / (n * takt_time) * 100 if n else 0
    tc_effective = max(st_t) if st_t else 0  # tempo de ciclo efetivo da linha
    smoothness = math.sqrt(sum((max(st_t) - x) ** 2 for x in st_t)) if st_t else 0
    return {
        "n_stations": n,
        "total_time": total,
        "station_times": st_t,
        "tc_effective": tc_effective,
        "efficiency": eff,
        "balance_delay": 100 - eff,
        "smoothness": smoothness,
        "theoretical_min": int(math.ceil(total / takt_time)) if takt_time else 0,
        "idle_total": n * takt_time - total if n else 0,
    }


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
        fig.update_layout(height=400, xaxis=dict(visible=False),
                          yaxis=dict(visible=False))
        return fig

    pos, G = hierarchical_positions(tasks, predecessors)
    node_radius = 0.42

    arrows = []
    for u, v in G.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        dx, dy = x1 - x0, y1 - y0
        L = math.sqrt(dx * dx + dy * dy) or 1
        ux, uy = dx / L, dy / L
        sx, sy = x0 + ux * node_radius, y0 + uy * node_radius
        ex, ey = x1 - ux * node_radius, y1 - uy * node_radius
        arrows.append(dict(
            ax=sx, ay=sy, x=ex, y=ey,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=3, arrowsize=1.4,
            arrowwidth=1.8, arrowcolor="#4a4a4a",
        ))

    if task_to_station is not None:
        node_colors = [STATION_PALETTE[task_to_station[t] % len(STATION_PALETTE)]
                       for t in G.nodes()]
    else:
        node_colors = ["#E8E8E8"] * len(G.nodes())

    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]
    node_text = [n for n in G.nodes()]
    node_hover = [
        f"<b>{n}</b><br>Tempo: {times[n]:.2f}"
        + (f"<br>Estação: E{task_to_station[n]+1}"
           if task_to_station is not None else "")
        for n in G.nodes()
    ]

    node_trace = go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        text=node_text, textposition="middle center",
        textfont=dict(color="white" if task_to_station is not None else "#222",
                      size=15, family="Arial Black"),
        marker=dict(size=55, color=node_colors,
                    line=dict(width=2.5,
                              color="white" if task_to_station is not None else "#4a4a4a")),
        hovertext=node_hover, hoverinfo="text", showlegend=False,
    )

    time_labels = go.Scatter(
        x=node_x, y=[y - 0.7 for y in node_y],
        mode="text",
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
# DADOS DE EXEMPLO
# =============================================================================

EXAMPLE = pd.DataFrame({
    "Tarefa":        ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"],
    "Tempo":         [5,   3,   4,   3,   6,   5,   2,   6,   1,   4,   7],
    "Predecessores": ["-", "A", "A", "B", "B,C", "D", "E", "F,G", "H", "I", "J"],
})

EMPTY = pd.DataFrame({
    "Tarefa": pd.Series(dtype="str"),
    "Tempo": pd.Series(dtype="float"),
    "Predecessores": pd.Series(dtype="str"),
})


def normalize_df(df):
    """Garante tipos corretos para o data_editor (Tarefa/Predecessores como
    string, Tempo como float). Necessário porque CSVs com tarefas numeradas
    (1, 2, 3...) são lidos pelo pandas como inteiro."""
    df = df.copy()
    if "Tarefa" in df.columns:
        df["Tarefa"] = df["Tarefa"].astype(str)
    if "Tempo" in df.columns:
        df["Tempo"] = pd.to_numeric(df["Tempo"], errors="coerce").astype(float)
    if "Predecessores" in df.columns:
        df["Predecessores"] = df["Predecessores"].fillna("-").astype(str)
    # Reordena colunas esperadas
    cols = [c for c in ["Tarefa", "Tempo", "Predecessores"] if c in df.columns]
    return df[cols]

# =============================================================================
# INTERFACE
# =============================================================================

st.title("⚙️ Balanceador de Linha de Produção")
st.caption("Simule a sua linha: preencha tarefas, tempos e precedências. "
           "O diagrama de precedência é desenhado automaticamente e a linha "
           "é balanceada pela heurística do Peso Posicional (RPW), usando o "
           "Takt Time como restrição máxima por estação.")

# --------- Sidebar: parâmetros de produção ---------
with st.sidebar:
    st.header("📊 Parâmetros de Produção")

    mode = st.radio(
        "Como definir o Takt Time?",
        ["A partir da demanda", "Valor direto"],
        help="Takt Time = Tempo disponível ÷ Demanda."
    )

    if mode == "A partir da demanda":
        avail = st.number_input("Tempo disponível por turno", min_value=1.0,
                                value=480.0, step=10.0,
                                help="Em minutos, segundos ou outra unidade.")
        demand = st.number_input("Demanda por turno (unidades)",
                                 min_value=1, value=60, step=1)
        takt_time = avail / demand
        st.metric("Takt Time (TT)", f"{takt_time:.3f}")
        st.caption("⚠️ Mesma unidade dos tempos das tarefas.")
    else:
        takt_time = st.number_input("Takt Time (TT)", min_value=0.01,
                                    value=30.0, step=1.0,
                                    help="Ritmo imposto pela demanda. "
                                         "Limite máximo de tempo por estação.")

    st.divider()
    st.subheader("Carregar dados")
    c1, c2 = st.columns(2)
    if c1.button("📋 Exemplo", use_container_width=True):
        st.session_state["data"] = normalize_df(EXAMPLE)
    if c2.button("🗑️ Limpar", use_container_width=True):
        st.session_state["data"] = normalize_df(EMPTY)

    up = st.file_uploader("Enviar CSV", type=["csv"])
    if up is not None:
        try:
            st.session_state["data"] = normalize_df(pd.read_csv(up))
        except Exception as e:
            st.error(f"Erro: {e}")

    with st.expander("ℹ️ Formato CSV"):
        st.code(
            "Tarefa,Tempo,Predecessores\n"
            "A,5,-\n"
            "B,3,A\n"
            "C,4,A\n"
            "D,3,\"B,C\"\n",
            language="csv"
        )

    st.divider()
    with st.expander("📖 Conceitos"):
        st.markdown(
            "- **Takt Time (TT)** — ritmo imposto pela demanda. Restrição "
            "máxima de tempo por estação.\n"
            "- **Tempo de Ciclo (TC)** — tempo entre saídas consecutivas da "
            "linha. Igual ao tempo da estação mais carregada após o "
            "balanceamento.\n"
            "- **Eficiência** — ΣTᵢ ÷ (n × TT) × 100%.\n"
            "- **Atraso de balanceamento** — 100% − Eficiência.\n"
            "- **Tempo ocioso total** — n × TT − ΣTᵢ.\n"
            "- **Peso Posicional (RPW)** — tempo da tarefa somado aos tempos "
            "de todos os sucessores. Método de Helgeson & Birnie (1961)."
        )

    with st.expander("ℹ️ Sobre"):
        st.markdown(
            "Simulador acadêmico construído para a disciplina de "
            "Tópicos Especiais em Engenharia de Produção — UFPE Campus "
            "Agreste.\n\n"
            "Inspirado no software *Flexible Line Balancing* de Stephen "
            "Ebert (University of Wisconsin-Stout), sem reutilização de "
            "código."
        )

# --------- Estado ---------
if "data" not in st.session_state:
    st.session_state["data"] = normalize_df(EXAMPLE)

# --------- Layout principal ---------
left, right = st.columns([1, 1.2], gap="large")

with left:
    st.subheader("📝 1. Simulação do Processo")
    st.caption("Preencha cada operação da sua linha. Predecessores separados "
               "por vírgula; use '-' para tarefas sem predecessor.")

    edited = st.data_editor(
        st.session_state["data"],
        num_rows="dynamic",
        use_container_width=True,
        height=380,
        column_config={
            "Tarefa": st.column_config.TextColumn(
                "Tarefa", required=True, width="small",
                help="Identificador único (ex.: 1, A, OP01)."),
            "Tempo": st.column_config.NumberColumn(
                "Tempo", min_value=0.0, required=True,
                format="%.2f", width="small"),
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
            q2.metric("Tempo total", f"{total:.2f}")
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

# --------- Balanceamento ---------
st.divider()
run = st.button("🚀 Balancear linha (Peso Posicional)", type="primary",
                use_container_width=True)

if run:
    if edited.empty or edited["Tarefa"].isna().all():
        st.error("Adicione tarefas antes de balancear.")
        st.stop()

    tasks, times, predecessors, successors, df = build_structures(edited)
    ok, msg = validate(tasks, times, predecessors, takt_time)
    if not ok:
        st.error(msg)
        st.stop()

    stations, pw = balance_rpw(tasks, times, predecessors, successors, takt_time)
    metrics = compute_metrics(stations, times, takt_time)
    task_to_station = {t: i for i, s in enumerate(stations) for t in s}

    st.divider()
    st.subheader("✅ 3. Resultado do Balanceamento")

    # ----- Bloco de comparação TT vs TC -----
    info_cols = st.columns(3)
    info_cols[0].metric("Takt Time (TT)", f"{takt_time:.2f}",
                        help="Restrição: tempo máximo permitido por estação.")
    info_cols[1].metric("Tempo de Ciclo efetivo (TC)",
                        f"{metrics['tc_effective']:.2f}",
                        delta=f"{metrics['tc_effective'] - takt_time:+.2f} vs TT",
                        delta_color="off",
                        help="Tempo da estação mais carregada. Define o ritmo "
                             "real da linha.")
    info_cols[2].metric("Folga (TT − TC)",
                        f"{takt_time - metrics['tc_effective']:.2f}",
                        help="Se > 0, a linha pode atender à demanda com sobra. "
                             "Se = 0, está no limite. Nunca é < 0.")

    # ----- Métricas principais -----
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Estações", metrics["n_stations"],
              delta=(metrics["n_stations"] - metrics["theoretical_min"] or None),
              delta_color="inverse",
              help=f"Mínimo teórico: {metrics['theoretical_min']}")
    m2.metric("Eficiência", f"{metrics['efficiency']:.2f}%",
              help="ΣTᵢ ÷ (n × TT) × 100")
    m3.metric("Atraso de balanceamento", f"{metrics['balance_delay']:.2f}%",
              help="100% − Eficiência")
    m4.metric("Tempo ocioso total", f"{metrics['idle_total']:.2f}",
              help="n × TT − ΣTᵢ")
    m5.metric("Suavidade (SI)", f"{metrics['smoothness']:.2f}",
              help="Quanto menor, mais equilibrada a linha.")

    # ----- Diagrama colorido + gráfico de barras -----
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
                    name=task, text=[f"{task}<br>{times[task]:g}"],
                    textposition="inside", textfont=dict(color="white", size=11),
                    marker=dict(color=STATION_PALETTE[i % len(STATION_PALETTE)],
                                line=dict(color="white", width=1.5)),
                    hovertemplate=(f"<b>{task}</b><br>Tempo: {times[task]:g}"
                                   f"<br>Estação: E{i+1}<extra></extra>"),
                    showlegend=False,
                ))
        fig_bar.add_hline(y=takt_time, line_dash="dash", line_color="red",
                          annotation_text=f"TT = {takt_time:.2f}",
                          annotation_position="top right")
        if abs(metrics['tc_effective'] - takt_time) > 1e-6:
            fig_bar.add_hline(y=metrics['tc_effective'], line_dash="dot",
                              line_color="green",
                              annotation_text=f"TC = {metrics['tc_effective']:.2f}",
                              annotation_position="bottom right")
        fig_bar.update_layout(
            barmode="stack", xaxis_title="Estação", yaxis_title="Tempo",
            height=440, plot_bgcolor="white",
            margin=dict(t=50, b=40, l=40, r=20),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # ----- Tabela de atribuição -----
    st.markdown("**📋 Atribuição detalhada**")
    rows = []
    for i, s in enumerate(stations, 1):
        st_t = sum(times[t] for t in s)
        rows.append({
            "Estação": f"E{i}",
            "Tarefas": " → ".join(s),
            "Tempo da estação": round(st_t, 2),
            "Ociosidade (TT − tempo)": round(takt_time - st_t, 2),
            "Uso (% do TT)": round(st_t / takt_time * 100, 1),
        })
    result_df = pd.DataFrame(rows)
    st.dataframe(result_df, use_container_width=True, hide_index=True)

    # ----- Pesos posicionais -----
    with st.expander("🧮 Pesos Posicionais — ordem de atribuição"):
        pw_df = pd.DataFrame({
            "Tarefa": list(pw.keys()),
            "Tempo": [times[t] for t in pw.keys()],
            "Peso Posicional": [round(v, 2) for v in pw.values()],
            "Estação": [f"E{task_to_station[t]+1}" for t in pw.keys()],
        }).sort_values("Peso Posicional", ascending=False).reset_index(drop=True)
        st.dataframe(pw_df, use_container_width=True, hide_index=True)
        st.caption("Peso Posicional = tempo da tarefa + soma dos tempos de "
                   "todos os sucessores. Tarefas com maior peso são alocadas "
                   "primeiro, respeitando precedência e Takt Time.")

    # ----- Exportação -----
    st.download_button(
        "⬇️ Baixar atribuição (CSV)",
        result_df.to_csv(index=False).encode("utf-8"),
        "balanceamento.csv", "text/csv",
        use_container_width=True,
    )
