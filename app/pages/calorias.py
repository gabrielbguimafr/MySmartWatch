"""Página de calorias: o que o relógio reporta × equações conhecidas × modelo ajustado."""

import sys
from datetime import date, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from smartdata.analise import calorias as cal  # noqa: E402
from smartdata.analise.hrv import fuso_horas  # noqa: E402

st.set_page_config(page_title="Calorias", page_icon="🔥", layout="wide")
px.defaults.color_discrete_sequence = px.colors.qualitative.Set2

FUSO_H = fuso_horas()
FUSO = timezone(timedelta(hours=FUSO_H))


@st.cache_data(show_spinner="Lendo dados...")
def dados():
    return cal.minutos(), cal.resumos(), cal.treinos()


@st.cache_data(show_spinner="Ajustando modelo...")
def modelo(_m: pd.DataFrame, n: int) -> cal.ModeloPassosFC:  # n entra só para invalidar o cache
    return cal.ajustar_passos_fc(_m)


m, r, tr = dados()
if m.empty:
    st.error("Sem dados de atividade no banco. Rode tools/sincronizar.py e tools/carregar_banco.py.")
    st.stop()
mod = modelo(m, len(m))
p0 = cal.perfil_do_env()

# ------------------------------------------------------------------ controles
with st.sidebar:
    st.header("Perfil")
    st.caption("Valores do Mi Fitness. Mude para simular (\"e se eu pesasse 80 kg?\").")
    peso = st.number_input("Peso (kg)", 30.0, 250.0, p0.peso_kg, step=0.5)
    altura = st.number_input("Altura (cm)", 100.0, 230.0, p0.altura_cm, step=1.0)
    idade = st.number_input("Idade (anos)", 10, 100, p0.idade)
    sexo = st.radio("Sexo", ["masculino", "feminino"], index=0 if p0.homem else 1, horizontal=True)
    perfil = cal.Perfil(sexo, date.today().replace(year=date.today().year - int(idade)), altura, peso, p0.fc_max)
    formula = st.selectbox("Equação da TMB", list(cal.TMB))
    tmb_dia = cal.TMB[formula](perfil)

    st.header("O que mostrar")
    m["dia"] = (m.t + pd.Timedelta(hours=FUSO_H)).dt.date
    todos_dias = sorted(m.dia.unique())
    dias = st.multiselect("Dias", todos_dias, default=todos_dias, format_func=lambda d: d.strftime("%d/%m"))
    MODELOS = {
        "relogio": "Relógio (calorias ativas)",
        "ajustado": f"Modelo passos + FC (ajustado, R² {mod.r2:.2f})",
        "keytel_liq": "Keytel líquido (− TMB)",
        "keytel_bruto": "Keytel bruto",
    }
    escolhidos = st.multiselect("Modelos", list(MODELOS), default=["relogio", "ajustado", "keytel_liq"],
                                format_func=MODELOS.get)
    st.header("Como mostrar")
    agreg = st.select_slider("Agregação", ["1 min", "15 min", "1 h"], value="15 min")
    acumulado = st.checkbox("Acumulado ao longo do dia", value=False)
    tipo = st.selectbox("Tipo de gráfico", ["Linha", "Área", "Barras", "Degraus"])
    altura_graf = st.slider("Altura dos gráficos", 250, 700, 380, step=10)

if not dias:
    st.info("Escolha pelo menos um dia.")
    st.stop()

sel = m[m.dia.isin(dias)].copy()
sel["relogio"] = sel.calorias_ativas
sel["ajustado"] = mod.prever(sel.passos, sel.fc)
# Keytel só onde há FC medida (sem FC não há o que calcular)
sel["keytel_bruto"] = np.where(sel.fc.notna(), cal.keytel_bruto(sel.fc.fillna(0), perfil), np.nan)
sel["keytel_liq"] = np.where(sel.fc.notna(), cal.keytel_liquido(sel.fc.fillna(0), perfil, tmb_dia), np.nan)


def desenhar(df, x, y, cor, **kw):
    if tipo in ("Linha", "Degraus"):
        fig = px.line(df, x=x, y=y, color=cor, line_shape="hv" if tipo == "Degraus" else "linear", **kw)
    elif tipo == "Área":
        fig = px.area(df, x=x, y=y, color=cor, **kw)
        fig.update_traces(stackgroup=None, fill="tozeroy")
    else:
        fig = px.bar(df, x=x, y=y, color=cor, barmode="group", **kw)
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), legend_title_text="")
    return fig


st.title("Calorias")
st.caption(f"Perfil: {perfil.peso_kg:.1f} kg, {perfil.altura_cm:.0f} cm, {perfil.idade} anos, {perfil.sexo} · "
           f"TMB ({formula}): {tmb_dia:.0f} kcal/dia")
abas = st.tabs(["Dia a dia", "Ao longo do dia", "Passos", "FC sem passos", "Treinos", "Sobre os modelos"])

# ------------------------------------------------------------------ dia a dia
with abas[0]:
    t = cal.tabela_diaria(perfil, sel, r, FUSO_H)
    t = t[t.index.isin(dias)]
    st.caption("O total do relógio = basal implícito + ativas. Compare o basal implícito com a TMB das equações.")
    d = t.reset_index(names="dia")
    d["rotulo"] = d.dia.map(lambda x: x.strftime("%d/%m")) + np.where(d.completo, "", " (parcial)")
    longo = d.melt(id_vars="rotulo", value_vars=["basal_implicito", "ativas_relogio"], var_name="parte", value_name="kcal")
    longo["parte"] = longo.parte.map({"basal_implicito": "Basal implícito (total − ativas)", "ativas_relogio": "Ativas"})
    fig = px.bar(longo, x="rotulo", y="kcal", color="parte", text_auto=".0f", title="Total diário do relógio")
    for nome, f in cal.TMB.items():
        fig.add_scatter(x=d.rotulo, y=f(perfil) * d.minutos / 1440, mode="markers+lines", name=f"TMB {nome}",
                        line=dict(dash="dot"))
    fig.update_layout(height=altura_graf, margin=dict(l=10, r=10, t=40, b=10), legend_title_text="", xaxis_title="")
    st.plotly_chart(fig, width="stretch")
    completos = t[t.completo]
    if len(completos):
        c1, c2, c3 = st.columns(3)
        razao = completos.basal_implicito / (tmb_dia)
        c1.metric("Basal implícito médio (dias completos)", f"{completos.basal_implicito.mean():.0f} kcal")
        c2.metric(f"Razão basal implícito / TMB {formula}", f"{razao.mean():.2f}",
                  help="Acima de 1: o relógio conta mais que a TMB no gasto 'de fundo'.")
        c3.metric("Calorias ativas por 100 passos", f"{(100 * completos.ativas_relogio.sum() / completos.passos.sum()):.1f}")
    st.dataframe(t.drop(columns=["completo"]).round(1).rename_axis("dia").reset_index(), hide_index=True, width="stretch")

# ------------------------------------------------------------------ ao longo do dia
with abas[1]:
    if not escolhidos:
        st.info("Escolha modelos na barra lateral.")
    else:
        regra = {"1 min": "1min", "15 min": "15min", "1 h": "1h"}[agreg]
        partes = []
        for dia, g in sel.groupby("dia"):
            g = g.set_index(g.t.dt.tz_convert(FUSO).dt.tz_localize(None))
            soma = g[escolhidos].resample(regra).sum(min_count=1)
            if acumulado:
                soma = soma.cumsum()
            soma["hora"] = pd.Timestamp("2000-01-01") + (soma.index - soma.index.normalize())
            soma["dia"] = dia.strftime("%d/%m")
            partes.append(soma.reset_index(drop=True))
        d = pd.concat(partes).melt(id_vars=["hora", "dia"], var_name="modelo", value_name="kcal")
        d["modelo"] = d.modelo.map(MODELOS)
        fig = desenhar(d, "hora", "kcal", "modelo", facet_row="dia" if len(dias) > 1 else None)
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
        fig.update_xaxes(tickformat="%H:%M", title_text="")
        fig.update_yaxes(title_text="kcal" + (" acumuladas" if acumulado else f" por {agreg}"))
        fig.update_layout(height=max(altura_graf, 230 * len(dias)))
        st.plotly_chart(fig, width="stretch")
        st.caption("Keytel só aparece nos minutos com FC medida. Fora deles, o relógio e o modelo ajustado "
                   "usam apenas os passos.")
        tot = sel.groupby("dia")[escolhidos].sum().rename(columns=MODELOS)
        tot.index = [x.strftime("%d/%m") for x in tot.index]
        st.dataframe(tot.round(0), width="stretch")

# ------------------------------------------------------------------ passos
with abas[2]:
    st.caption("Cada ponto é um minuto. A inclinação da reta é quanto o relógio dá por passo.")
    d = sel[sel.passos > 0].copy()
    d["faixa de FC"] = pd.cut(d.fc, [0, 75, 90, 110, 250], labels=["<75", "75-90", "90-110", ">110"]).astype(str)
    d.loc[d.fc.isna(), "faixa de FC"] = "sem FC"
    d["kcal (com tremor)"] = d.calorias_ativas + np.random.default_rng(0).uniform(-0.2, 0.2, len(d))
    fig = px.scatter(d, x="passos", y="kcal (com tremor)", color="faixa de FC", opacity=0.6,
                     labels={"passos": "passos no minuto", "kcal (com tremor)": "calorias ativas no minuto"})
    xs = np.linspace(0, d.passos.max() if len(d) else 1, 50)
    fig.add_scatter(x=xs, y=mod.a_so_passos * xs, mode="lines",
                    name=f"só passos: {mod.a_so_passos * 100:.1f} kcal/100 passos",
                    line=dict(dash="dash", color="gray"))
    fig.update_layout(height=altura_graf + 80)
    st.plotly_chart(fig, width="stretch")
    st.caption("O tremor vertical (±0,2) só separa os pontos: o relógio grava calorias inteiras por minuto.")
    d["cadência"] = pd.cut(d.passos, [0, 20, 60, 90, 110, 130, 250],
                           labels=["1-20", "21-60", "61-90", "91-110", "111-130", ">130"])
    g = d.groupby("cadência", observed=True).agg(minutos=("passos", "size"), passos=("passos", "sum"),
                                                 kcal=("calorias_ativas", "sum")).reset_index()
    g["kcal por 100 passos"] = 100 * g.kcal / g.passos
    fig = px.bar(g, x="cadência", y="kcal por 100 passos", text_auto=".1f", hover_data=["minutos"],
                 title="Calorias por 100 passos, por cadência (passos/min)")
    fig.update_layout(height=altura_graf)
    st.plotly_chart(fig, width="stretch")

# ------------------------------------------------------------------ FC sem passos
with abas[3]:
    st.caption("Minutos com FC medida e nenhum passo: o relógio só credita calorias acima de um limiar de FC.")
    z = sel[(sel.passos == 0) & sel.fc.notna()].copy()
    largura = st.slider("Largura das faixas de FC (bpm)", 2, 15, 5)
    z["faixa"] = (z.fc // largura) * largura
    g = z.groupby("faixa").agg(minutos=("fc", "size"), com_kcal=("calorias_ativas", lambda s: (s > 0).mean()),
                               kcal=("calorias_ativas", "mean")).reset_index()
    fig = go.Figure()
    fig.add_bar(x=g.faixa + largura / 2, y=g.com_kcal * 100, name="% dos minutos com caloria",
                customdata=g.minutos, hovertemplate="FC %{x}<br>%{y:.0f}%<br>%{customdata} minutos<extra></extra>")
    fig.add_scatter(x=g.faixa + largura / 2, y=g.kcal, name="kcal média por minuto", yaxis="y2", mode="lines+markers")
    fig.add_vline(x=mod.limiar, line_dash="dot", annotation_text=f"limiar ajustado {mod.limiar:.0f} bpm")
    fig.update_layout(height=altura_graf + 40, xaxis_title="FC (bpm)", yaxis_title="% com caloria",
                      yaxis2=dict(overlaying="y", side="right", title="kcal/min"),
                      margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")
    reserva = (mod.limiar - 65) / (perfil.fc_max - 65) * 100
    st.markdown(f"Modelo ajustado nos {mod.n} minutos com FC: **{mod.a * 100:.2f} kcal por 100 passos** + "
                f"**{mod.b:.3f} kcal/min por bpm acima de {mod.limiar:.0f}** · R² = {mod.r2:.2f} "
                f"(só passos: {mod.r2_so_passos:.2f}). O limiar equivale a ~{reserva:.0f}% da reserva de FC "
                f"(repouso ~65, máx {perfil.fc_max:.0f}).")

# ------------------------------------------------------------------ treinos
with abas[4]:
    if tr.empty:
        st.info("Nenhum treino no banco.")
    else:
        rot = {t.inicio: pd.Timestamp(t.inicio, unit="s", tz="UTC").tz_convert(FUSO).strftime("%d/%m %H:%M")
               for t in tr.itertuples()}
        escolha = st.selectbox("Treino", list(rot), format_func=rot.get)
        t = tr[tr.inicio == escolha].iloc[0]
        s = cal.treino_segundos(int(t.inicio), int(t.fim))
        s["fc"] = s.fc.ffill()
        s["min"] = (s.ts - t.inicio) / 60
        s["Relógio"] = s.calorias.cumsum()
        s["Keytel bruto"] = (cal.keytel_bruto(s.fc, perfil) / 60).cumsum()
        s["Keytel líquido"] = (cal.keytel_liquido(s.fc, perfil, tmb_dia) / 60).cumsum()
        d = s.melt(id_vars="min", value_vars=["Relógio", "Keytel líquido", "Keytel bruto"], var_name="modelo", value_name="kcal")
        fig = px.line(d, x="min", y="kcal", color="modelo", title="Calorias acumuladas no treino")
        fig.add_scatter(x=s["min"], y=s.fc, name="FC", yaxis="y2", line=dict(color="lightgray", width=1))
        fig.update_layout(height=altura_graf + 60, xaxis_title="minutos", yaxis2=dict(overlaying="y", side="right", title="FC"),
                          margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")
        c = st.columns(4)
        c[0].metric("Relógio", f"{t.calorias} kcal")
        c[1].metric("Keytel líquido", f"{s['Keytel líquido'].iloc[-1]:.0f} kcal")
        c[2].metric("Keytel bruto", f"{s['Keytel bruto'].iloc[-1]:.0f} kcal")
        c[3].metric("FC média / máx", f"{t.fc_media} / {t.fc_max}")

# ------------------------------------------------------------------ sobre
with abas[5]:
    st.markdown(r"""
**TMB (taxa metabólica basal)**: energia gasta em repouso absoluto, estimada por equações de regressão.

- Mifflin-St Jeor (1990): homem $10P + 6{,}25A - 5I + 5$; mulher $\ldots - 161$
- Harris-Benedict revisada (1984): homem $88{,}362 + 13{,}397P + 4{,}799A - 5{,}677I$

P = peso (kg), A = altura (cm), I = idade (anos). Erro típico de ±10% para uma pessoa.

**Keytel et al. (2005)**: gasto bruto por minuto a partir da FC, validado em exercício:
homem $\text{kJ/min} = -55{,}0969 + 0{,}6309\,FC + 0{,}1988\,P + 0{,}2017\,I$ (÷ 4,184 → kcal).
Em FC baixa (repouso, caminhada leve) superestima bastante; o **líquido** subtrai a TMB por minuto.

**Modelo ajustado**: $\text{kcal}_{min} = a \cdot \text{passos} + b \cdot \max(FC - L, 0)$, ajustado por mínimos
quadrados nos minutos com FC, escolhendo o limiar $L$ que maximiza o $R^2$. Não é a fórmula do relógio;
é a forma mais simples que reproduz o comportamento observado.

**Basal implícito**: total diário do relógio − calorias ativas. Fica acima da TMB das equações,
então o relógio provavelmente inclui algo além da TMB no gasto "de fundo" (por exemplo, efeito
térmico dos alimentos ou atividade leve não contada como ativa). Com poucos dias, não dá para dizer o quê.
""")
