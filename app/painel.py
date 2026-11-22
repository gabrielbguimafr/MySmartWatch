"""Painel de sono e HRV.

Rodar:  .venv\\Scripts\\python -m streamlit run app\\painel.py
Tudo roda localmente; os dados não saem do PC.
"""

import sys
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartdata.analise import hrv  # noqa: E402

st.set_page_config(page_title="Sono e HRV", page_icon="🌙", layout="wide")
# cores bem distintas entre si e legíveis nos temas claro e escuro, em todos os gráficos
px.defaults.color_discrete_sequence = px.colors.qualitative.Set2

# ------------------------------------------------------------------ catálogo
# chave -> (rótulo, unidade, origem, explicação)
METRICAS = {
    "fc_relogio": ("FC (calculada pelo relógio)", "bpm", "serie",
                   "FC por minuto que o próprio relógio grava durante o sono."),
    "fc_bpm": ("FC (dos batimentos)", "bpm", "janela",
               "60000 / RR médio da janela, calculada por nós a partir dos batimentos."),
    "rmssd_ms": ("RMSSD", "ms", "janela",
                 "Variação batimento a batimento. Reflete o sistema parassimpático (recuperação). "
                 "Maior = mais relaxado. É a métrica de HRV mais confiável em janelas curtas."),
    "ln_rmssd": ("ln(RMSSD)", "", "janela",
                 "Logaritmo do RMSSD: distribuição mais simétrica, boa para comparar dias."),
    "sdnn_ms": ("SDNN", "ms", "janela", "Desvio padrão dos intervalos RR: variabilidade total."),
    "pnn50_pct": ("pNN50", "%", "janela", "% de batimentos consecutivos que diferem mais de 50 ms."),
    "lf_hf": ("LF/HF", "", "janela",
              "Potência em baixa (0,04–0,15 Hz) sobre alta frequência (0,15–0,40 Hz). "
              "Tende a cair no sono profundo e subir no REM/despertares. Interpretação debatida."),
    "sd1_ms": ("SD1 (Poincaré)", "ms", "janela", "Dispersão de curto prazo (≈ RMSSD/√2)."),
    "sd2_ms": ("SD2 (Poincaré)", "ms", "janela", "Dispersão de longo prazo."),
    "spo2": ("SpO2", "%", "serie", "Saturação de oxigênio medida pelo relógio a cada ~12 min "
             "(decodificação nossa, marcada como hipótese)."),
    "respiracao": ("Respiração", "rpm", "serie",
                   "Frequência respiratória estimada pelo relógio (valores baixos: ver nota)."),
    "cobertura": ("Cobertura de batimentos", "fração", "janela",
                  "Fração da janela coberta por RR válidos. Abaixo do mínimo, a janela é descartada."),
}
TIPOS = ["Linha", "Linha + pontos", "Pontos", "Área", "Barras", "Degraus"]


def rotulo(m: str) -> str:
    nome, unidade, *_ = METRICAS[m]
    return f"{nome} ({unidade})" if unidade else nome


# ------------------------------------------------------------------ dados
@st.cache_data(show_spinner=False)
def lista_noites() -> pd.DataFrame:
    return hrv.noites()


@st.cache_data(show_spinner="Calculando HRV...")
def dados_noite(deitou: int, acordou: int, tolerancia: float, minutos: int, cobertura: float):
    n = hrv.carregar_noite(deitou, acordou, tolerancia)
    j = hrv.janelas(n, minutos, espectral=True, cobertura_min=cobertura)
    r = hrv.resumo_noite(n, minutos)
    return n, j, r


fuso = timezone(timedelta(hours=hrv.fuso_horas()))
tab_noites = lista_noites()
if tab_noites.empty:
    st.error("Nenhuma noite no banco. Rode tools/sincronizar.py e tools/carregar_banco.py.")
    st.stop()


def nome_noite(deitou: int, dur: float) -> str:
    d = pd.Timestamp(deitou, unit="s", tz="UTC").tz_convert(fuso)
    return f"{(d - pd.Timedelta(hours=12)).strftime('%d/%m')} → {d.strftime('%d/%m')} ({dur:.1f} h)"


opcoes = {nome_noite(int(r.deitou), r.duracao_h): (int(r.deitou), int(r.acordou))
          for r in tab_noites.itertuples()}

# ------------------------------------------------------------------ controles
with st.sidebar:
    st.header("O que mostrar")
    escolhidas = st.multiselect("Noites", list(opcoes), default=list(opcoes))
    metricas = st.multiselect("Métricas", list(METRICAS), default=["fc_relogio", "rmssd_ms", "spo2"],
                              format_func=rotulo)
    st.header("Como mostrar")
    tipo = st.selectbox("Tipo de gráfico", TIPOS)
    eixo_x = st.radio("Eixo do tempo", ["Horas desde que deitou", "Hora do dia (sobrepõe noites)",
                                        "Data e hora"])
    arranjo = st.radio("Organização", ["Um gráfico por métrica (noites em cores)",
                                       "Uma coluna por noite",
                                       "Tudo junto, normalizado (z-score)"])
    suavizar = st.slider("Suavização (média móvel, nº de pontos)", 1, 15, 1)
    altura = st.slider("Altura de cada gráfico", 200, 600, 320, step=20)
    st.header("Estágios do Mi Fitness")
    mostrar_hipno = st.checkbox("Mostrar hipnograma do app", value=True)
    sombrear = st.checkbox("Sombrear estágios atrás das curvas", value=True,
                           help="Com várias noites sobrepostas no mesmo gráfico, a sombra só aparece "
                                "na organização 'Uma coluna por noite' ou com uma noite selecionada.")
    st.header("Cálculo da HRV")
    minutos = st.select_slider("Janela (min)", [1, 2, 5, 10, 15, 30], value=5)
    tolerancia = st.slider("Tolerância de artefato (% de mudança entre RR)", 5, 50, 20) / 100
    cobertura = st.slider("Cobertura mínima da janela", 0.0, 1.0, 0.5, step=0.05)

if not escolhidas:
    st.info("Escolha pelo menos uma noite na barra lateral.")
    st.stop()

carregadas = {nome: dados_noite(*opcoes[nome], tolerancia, minutos, cobertura) for nome in escolhidas}


def eixo(ts: pd.Series | pd.DatetimeIndex, deitou: int):
    ts = pd.DatetimeIndex(pd.to_datetime(ts, utc=True))
    if eixo_x == "Horas desde que deitou":
        return np.asarray((ts - pd.Timestamp(deitou, unit="s", tz="UTC")).total_seconds() / 3600)
    local = ts.tz_convert(fuso).tz_localize(None)
    if eixo_x == "Data e hora":
        return local
    # hora do dia numa data de referência: tarde/noite no dia 1, madrugada/manhã no dia 2
    base = pd.Timestamp("2000-01-01")
    dia = np.where(local.hour >= 12, 0, 1)
    return base + pd.to_timedelta(dia, unit="D") + (local - local.normalize())


def longo(nomes_metricas) -> pd.DataFrame:
    partes = []
    for nome, (n, j, _) in carregadas.items():
        for m in nomes_metricas:
            origem = METRICAS[m][2]
            if origem == "janela":
                if j.empty or m not in j:
                    continue
                s = j[m].dropna()
                ts = s.index + pd.Timedelta(minutes=minutos / 2)  # centro da janela
            else:
                s = {"fc_relogio": n.fc_relogio, "spo2": n.spo2, "respiracao": n.respiracao}[m].dropna()
                ts = s.index
            if s.empty:
                continue
            valores = s.to_numpy(dtype=float)
            if suavizar > 1:
                valores = pd.Series(valores).rolling(suavizar, center=True, min_periods=1).mean().to_numpy()
            # quebra a linha onde faltam dados (lacuna > 3x o passo típico), em vez de ligar os pontos
            ts = pd.DatetimeIndex(ts)
            passo = pd.Series(ts).diff().median()
            # compara como Timedelta: asi8 pode estar em ms (pandas 3) e Timedelta.value em ns
            lacuna = (np.r_[False, np.asarray((ts[1:] - ts[:-1]) > 3 * passo)] if len(ts) > 2
                      else np.zeros(len(ts), bool))
            if lacuna.any():
                pos = np.flatnonzero(lacuna)
                meio = ts[pos - 1] + (ts[pos] - ts[pos - 1]) / 2
                ts = ts.append(pd.DatetimeIndex(meio))
                valores = np.r_[valores, np.full(len(pos), np.nan)]
                ordem = np.argsort(ts.to_numpy(), kind="stable")
                ts, valores = ts[ordem], valores[ordem]
            partes.append(pd.DataFrame({"x": eixo(ts, n.deitou), "valor": valores,
                                        "noite": nome, "metrica": rotulo(m)}))
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def desenhar(df: pd.DataFrame, cor: str, **kw) -> go.Figure:
    comum = dict(x="x", y="valor", color=cor, **kw)
    if tipo in ("Linha", "Linha + pontos", "Degraus"):
        fig = px.line(df, markers=tipo == "Linha + pontos",
                      line_shape="hv" if tipo == "Degraus" else "linear", **comum)
    elif tipo == "Pontos":
        fig = px.scatter(df, **comum)
    elif tipo == "Área":
        fig = px.area(df, **comum)
        fig.update_traces(stackgroup=None, fill="tozeroy")
    else:
        fig = px.bar(df, barmode="overlay", opacity=0.7, **comum)
    titulo_x = {"Horas desde que deitou": "horas desde que deitou",
                "Hora do dia (sobrepõe noites)": "hora", "Data e hora": ""}[eixo_x]
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), legend_title_text="", xaxis_title=titulo_x)
    if eixo_x == "Hora do dia (sobrepõe noites)":
        fig.update_xaxes(tickformat="%H:%M")
    return fig


COR_ESTAGIO = {"profundo": "#3b5bdb", "leve": "#74c0fc", "rem": "#f783ac", "acordado": "#ffd43b"}


def sombrear_estagios(fig: go.Figure, nome_noite: str, col: int | None = None) -> None:
    """Faixas coloridas com os estágios do Mi Fitness atrás das curvas."""
    n = carregadas[nome_noite][0]
    for e in n.estagios_app.itertuples():
        x0, x1 = eixo(pd.DatetimeIndex([e.inicio, e.fim]), n.deitou)
        kw = dict(row="all", col=col) if col else {}
        fig.add_vrect(x0=x0, x1=x1, fillcolor=COR_ESTAGIO.get(e.estagio, "gray"), opacity=0.28,
                      line_width=0, layer="below", **kw)


def figura_hipnograma() -> go.Figure | None:
    linhas = []
    for nome, (n, _, _) in carregadas.items():
        e = n.estagios_app
        if e.empty:
            continue
        # cada trecho vira dois pontos (início e fim) para desenhar degraus
        ts = pd.DatetimeIndex(list(e.inicio) + [e.fim.iloc[-1]])
        est = list(e.estagio) + [e.estagio.iloc[-1]]
        linhas.append(pd.DataFrame({"x": eixo(ts, n.deitou), "estagio": est, "noite": nome}))
    if not linhas:
        return None
    d = pd.concat(linhas, ignore_index=True)
    fig = px.line(d, x="x", y="estagio", color="noite", line_shape="hv",
                  category_orders={"estagio": hrv.ORDEM_ESTAGIOS, "noite": list(carregadas)},
                  facet_row="noite" if len(linhas) > 1 else None, title="Hipnograma calculado pelo Mi Fitness")
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig.update_yaxes(title_text="")
    fig.update_layout(height=140 + 110 * len(linhas), showlegend=False,
                      margin=dict(l=10, r=10, t=40, b=10), xaxis_title="")
    if eixo_x == "Hora do dia (sobrepõe noites)":
        fig.update_xaxes(tickformat="%H:%M")
    return fig


# ------------------------------------------------------------------ abas
st.title("Sono e variabilidade da frequência cardíaca")
abas = st.tabs(["Linha do tempo", "Estágios do app", "Comparar noites", "Distribuições", "Correlações",
                "Poincaré", "Qualidade dos dados", "Sobre as métricas"])

with abas[0]:
    if mostrar_hipno:
        fig = figura_hipnograma()
        if fig is None:
            st.caption("Sem hipnograma do Mi Fitness para estas noites (abra as noites no app e "
                       "rode tools/copiar_logs_mtp.ps1 + tools/carregar_banco.py).")
        else:
            st.plotly_chart(fig, width="stretch")
    if sombrear:
        st.caption("Faixas: " + " · ".join(f"<span style='color:{c}'>■</span> {e}"
                                           for e, c in COR_ESTAGIO.items()), unsafe_allow_html=True)
    if not metricas:
        st.info("Escolha métricas na barra lateral.")
    else:
        df = longo(metricas)
        if df.empty:
            st.warning("Sem dados para essas escolhas.")
        elif arranjo.startswith("Um gráfico"):
            if sombrear and len(carregadas) > 1:
                st.caption("Sombra dos estágios desligada aqui porque há várias noites no mesmo gráfico: "
                           "escolha uma noite ou a organização 'Uma coluna por noite'.")
            for m in metricas:
                d = df[df.metrica == rotulo(m)]
                if not d.empty:
                    fig = desenhar(d, "noite", title=rotulo(m))
                    if sombrear and len(carregadas) == 1:
                        sombrear_estagios(fig, next(iter(carregadas)))
                    fig.update_layout(height=altura, yaxis_title=METRICAS[m][1])
                    st.plotly_chart(fig, width="stretch")
        elif arranjo.startswith("Uma coluna"):
            fig = desenhar(df, "noite", facet_col="noite", facet_row="metrica",
                           category_orders={"noite": list(carregadas)})
            if sombrear:
                for k, nome in enumerate(carregadas, start=1):
                    sombrear_estagios(fig, nome, col=k)
            fig.update_yaxes(matches=None, title_text="")
            fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
            fig.update_layout(height=altura * len(metricas), showlegend=False)
            st.plotly_chart(fig, width="stretch")
        else:
            df["valor"] = df.groupby("metrica").valor.transform(lambda v: (v - v.mean()) / v.std(ddof=0))
            fig = desenhar(df, "metrica", facet_row="noite")
            fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
            fig.update_layout(height=altura * len(escolhidas), yaxis_title="desvios-padrão")
            st.plotly_chart(fig, width="stretch")

with abas[1]:
    st.caption("Cada janela de HRV recebe o estágio que o Mi Fitness atribuiu ao seu centro. "
               "Assim dá para ver quais sinais o app parece usar para decidir cada estágio.")
    janela_metricas = [k for k, v in METRICAS.items() if v[2] == "janela" and k != "cobertura"]
    partes = []
    for nome, (n, j, _) in carregadas.items():
        if j.empty or n.estagios_app.empty:
            continue
        centros = j.index + pd.Timedelta(minutes=minutos / 2)
        partes.append(j[janela_metricas].assign(estagio=hrv.rotular(centros, n.estagios_app).to_numpy(),
                                                noite=nome))
    if not partes:
        st.info("Nenhuma das noites escolhidas tem hipnograma do Mi Fitness.")
    else:
        d = pd.concat(partes).dropna(subset=["estagio"])
        presentes = [e for e in hrv.ORDEM_ESTAGIOS if e in set(d.estagio)]
        c1, c2 = st.columns(2)
        m = c1.selectbox("Métrica", janela_metricas, index=janela_metricas.index("sdnn_ms"),
                         format_func=rotulo, key="est_m")
        forma = c2.radio("Forma", ["Caixa (boxplot)", "Violino", "Pontos ao longo da noite"],
                         horizontal=True, key="est_f")
        if forma == "Pontos ao longo da noite":
            pts = d.reset_index(names="inicio")
            pts["x"] = [eixo(pd.DatetimeIndex([t]), carregadas[nm][0].deitou)[0]
                        for t, nm in zip(pts.inicio, pts.noite)]
            fig = px.scatter(pts, x="x", y=m, color="estagio", facet_row="noite",
                             color_discrete_map=COR_ESTAGIO, category_orders={"estagio": presentes})
            fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
            fig.update_layout(height=220 * d.noite.nunique() + 80, xaxis_title="")
        else:
            f = px.box if forma.startswith("Caixa") else px.violin
            fig = f(d, x="estagio", y=m, color="estagio", color_discrete_map=COR_ESTAGIO,
                    category_orders={"estagio": presentes}, **({"points": "all"} if f is px.box else {"box": True}))
            fig.update_layout(height=altura + 120, showlegend=False)
        fig.update_layout(title=f"{rotulo(m)} por estágio do Mi Fitness", margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")

        st.subheader("Quanto cada métrica separa os estágios")
        st.caption("AUC: 0,5 = não separa nada; quanto mais longe de 0,5 (perto de 1 ou de 0), melhor separa. "
                   "Abaixo de 0,5 significa que o valor é MENOR no primeiro grupo.")
        tabela = []
        for k in janela_metricas:
            tabela.append({
                "métrica": rotulo(k),
                "profundo × resto": hrv.auc(d[d.estagio == "profundo"][k], d[d.estagio != "profundo"][k]),
                "REM × leve": hrv.auc(d[d.estagio == "rem"][k], d[d.estagio == "leve"][k]),
                **{f"mediana {e}": d[d.estagio == e][k].median() for e in presentes},
            })
        st.dataframe(pd.DataFrame(tabela).round(2), hide_index=True, width="stretch")
        st.caption(f"{len(d)} janelas de {minutos} min: " +
                   ", ".join(f"{e} {int((d.estagio == e).sum())}" for e in presentes))

with abas[2]:
    resumo = pd.DataFrame([r for (_, _, r) in carregadas.values()], index=list(carregadas))
    colunas_num = [c for c in resumo.columns if resumo[c].dtype.kind in "fi"]
    c1, c2 = st.columns([2, 1])
    escolha = c1.multiselect("Indicadores da noite", colunas_num,
                             default=[c for c in ("rmssd_ms_mediana", "fc_min_relogio", "spo2_media")
                                      if c in colunas_num])
    forma = c2.radio("Forma", ["Barras", "Pontos ligados"], horizontal=True)
    for c in escolha:
        d = resumo[[c]].reset_index(names="noite")
        fig = (px.bar(d, x="noite", y=c, text_auto=".1f") if forma == "Barras"
               else px.line(d, x="noite", y=c, markers=True))
        fig.update_layout(height=altura, title=c, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")
    tabela = resumo.copy()
    for c in ("deitou", "acordou"):
        tabela[c] = pd.to_datetime(tabela[c]).dt.tz_convert(fuso).dt.strftime("%d/%m %H:%M")
    # transposta mistura texto e número na mesma coluna: formata tudo como texto para exibir
    exibir = tabela.T.map(lambda v: f"{v:.2f}" if isinstance(v, (float, np.floating)) else str(v))
    st.dataframe(exibir, width="stretch")

with abas[3]:
    c1, c2 = st.columns(2)
    m = c1.selectbox("Métrica", list(METRICAS), index=2, format_func=rotulo, key="dist_m")
    forma = c2.radio("Forma", ["Histograma", "Caixa (boxplot)", "Violino"], horizontal=True)
    d = longo([m])
    if d.empty:
        st.warning("Sem dados.")
    else:
        if forma == "Histograma":
            fig = px.histogram(d, x="valor", color="noite", barmode="overlay", opacity=0.6, nbins=40)
        elif forma.startswith("Caixa"):
            fig = px.box(d, x="noite", y="valor", color="noite", points="outliers")
        else:
            fig = px.violin(d, x="noite", y="valor", color="noite", box=True)
        fig.update_layout(height=altura + 100, title=rotulo(m), showlegend=forma == "Histograma")
        st.plotly_chart(fig, width="stretch")

with abas[4]:
    st.caption("Cada ponto é uma janela de HRV. Útil para ver, por exemplo, se o RMSSD cai quando a FC sobe.")
    janela_metricas = [k for k, v in METRICAS.items() if v[2] == "janela"]
    c1, c2, c3 = st.columns(3)
    mx = c1.selectbox("Eixo X", janela_metricas, index=0, format_func=rotulo)
    my = c2.selectbox("Eixo Y", janela_metricas, index=1, format_func=rotulo)
    tendencia = c3.checkbox("Linha de tendência", value=True)
    pts = []
    for nome, (n, j, _) in carregadas.items():
        if not j.empty and mx in j and my in j:
            pts.append(j[[mx, my]].dropna().assign(noite=nome))
    if pts:
        d = pd.concat(pts)
        fig = px.scatter(d, x=mx, y=my, color="noite", opacity=0.7)
        if tendencia and len(d) > 2:
            a, b = np.polyfit(d[mx], d[my], 1)
            xs = np.linspace(d[mx].min(), d[mx].max(), 50)
            fig.add_scatter(x=xs, y=a * xs + b, mode="lines", name="tendência (todas)",
                            line=dict(dash="dash", color="gray"))
            r = np.corrcoef(d[mx], d[my])[0, 1]
            st.metric("Correlação de Pearson (r)", f"{r:.2f}")
        fig.update_layout(height=altura + 150, xaxis_title=rotulo(mx), yaxis_title=rotulo(my))
        st.plotly_chart(fig, width="stretch")

with abas[5]:
    st.caption("Cada ponto é um par (RR atual, próximo RR). Nuvem larga = alta variabilidade; "
               "estreita e alongada = ritmo mais regular.")
    nome = st.selectbox("Noite", list(carregadas), key="poinc")
    n = carregadas[nome][0]
    v = n.rr[n.rr.valido].rr_ms.to_numpy()
    cor_hora = st.checkbox("Colorir pela hora da noite")
    if len(v) > 2:
        d = pd.DataFrame({"RR n (ms)": v[:-1], "RR n+1 (ms)": v[1:]})
        if cor_hora:
            t = n.rr[n.rr.valido].t.iloc[:-1]
            d["horas desde deitar"] = ((t - pd.Timestamp(n.deitou, unit="s", tz="UTC"))
                                       .dt.total_seconds() / 3600).to_numpy()
        fig = px.scatter(d, x="RR n (ms)", y="RR n+1 (ms)", opacity=0.15,
                         color="horas desde deitar" if cor_hora else None)
        fig.update_traces(marker=dict(size=3))
        fig.update_layout(height=600, yaxis_scaleanchor="x")
        st.plotly_chart(fig, width="stretch")
        r = carregadas[nome][2]
        c1, c2 = st.columns(2)
        c1.metric("SD1 (mediana das janelas)", f"{r.get('sd1_ms_mediana', np.nan):.0f} ms")
        c2.metric("SD2 (mediana das janelas)", f"{r.get('sd2_ms_mediana', np.nan):.0f} ms")

with abas[6]:
    st.caption("Quantos batimentos foram aproveitados. Lacunas e artefatos (movimento, mau contato) "
               "são descartados antes do cálculo.")
    linhas = []
    for nome, (n, j, _) in carregadas.items():
        linhas.append({"noite": nome, "intervalos RR": len(n.rr),
                       "válidos (%)": round(100 * n.rr.valido.mean(), 1),
                       "janelas usadas": int(j.rmssd_ms.notna().sum()) if not j.empty else 0,
                       "janelas totais": len(j)})
    st.dataframe(pd.DataFrame(linhas), width="stretch", hide_index=True)
    d = longo(["cobertura"])
    if not d.empty:
        fig = desenhar(d, "noite", title="Cobertura por janela")
        fig.add_hline(y=cobertura, line_dash="dot", annotation_text="mínimo")
        fig.update_layout(height=altura)
        st.plotly_chart(fig, width="stretch")
    nome = st.selectbox("Distribuição dos RR de uma noite", list(carregadas), key="qual")
    rr = carregadas[nome][0].rr
    fig = px.histogram(rr[(rr.rr_ms > 200) & (rr.rr_ms < 2500)], x="rr_ms", color="valido",
                       nbins=120, barmode="overlay", opacity=0.7,
                       labels={"rr_ms": "intervalo RR (ms)", "valido": "válido"})
    fig.update_layout(height=altura)
    st.plotly_chart(fig, width="stretch")

with abas[7]:
    for k, (nome, unidade, origem, texto) in METRICAS.items():
        st.markdown(f"**{nome}**{f' ({unidade})' if unidade else ''}: {texto}")
    st.markdown("""
---
**De onde vêm os dados.** O Redmi Watch 2 Lite não envia estágios do sono: envia o instante de cada
batimento, a FC por minuto, SpO2 e respiração. Os estágios e a nota que o Mi Fitness mostra são
calculados no app ou na nuvem. Este painel calcula a HRV diretamente dos batimentos.

**Validação.** A FC calculada dos batimentos bate com a FC por minuto do relógio
(diferença média de ~2 bpm), então os horários dos batimentos são confiáveis.

**Respiração.** Os valores (~8 rpm) estão abaixo do típico em adultos dormindo (12–20 rpm).
Pode ser outra unidade ou outro campo; trate como não confirmado.

**Cuidados.** HRV de pulso óptico tem mais artefatos que ECG, principalmente com movimento.
Compare noites entre si, não com valores de referência de ECG.
""")
