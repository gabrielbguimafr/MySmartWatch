"""Sono e variabilidade da frequência cardíaca (HRV) a partir dos batimentos.

O relógio grava o instante de cada batimento durante o sono. A diferença entre
batimentos consecutivos é o intervalo RR (ms). Métricas clássicas (Task Force 1996):
  RMSSD  raiz da média dos quadrados das diferenças sucessivas de RR -> tônus vagal
         (parassimpático), a métrica mais robusta para janelas curtas.
  SDNN   desvio padrão dos RR -> variabilidade total.
  pNN50  % de diferenças sucessivas > 50 ms.
  LF/HF  razão de potência 0,04-0,15 Hz / 0,15-0,40 Hz (Lomb-Scargle, tolera falhas).
         Interpretação "simpato-vagal" é controversa; use como exploração.
  SD1/SD2 do gráfico de Poincaré (SD1 ~ RMSSD/sqrt(2)).

Limpeza de artefatos: RR fora de [300, 2000] ms é descartado (falhas de detecção ou
lacunas), e também RR que difere mais que `tolerancia` do RR anterior válido.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import lombscargle

BANCO = Path(__file__).resolve().parents[2] / ".dados" / "smartdata.db"


def _ler(sql: str, params=()) -> pd.DataFrame:
    with sqlite3.connect(BANCO) as con:
        return pd.read_sql(sql, con, params=params)


def fuso_horas() -> float:
    """Fuso dos arquivos do relógio (em horas), do resumo diário mais recente."""
    df = _ler("SELECT fuso_15min FROM resumo_diario ORDER BY ts DESC LIMIT 1")
    return float(df.fuso_15min.iloc[0]) / 4 if len(df) else 0.0


def noites() -> pd.DataFrame:
    df = _ler("SELECT deitou, acordou FROM sono ORDER BY deitou")
    df["duracao_h"] = (df.acordou - df.deitou) / 3600
    return df


@dataclass
class Noite:
    deitou: int
    acordou: int
    rr: pd.DataFrame          # t (datetime UTC), rr_ms, valido
    fc_relogio: pd.Series     # FC por minuto calculada pelo relógio
    spo2: pd.Series
    respiracao: pd.Series
    estagios_app: pd.DataFrame  # inicio, fim (datetime UTC), estagio — calculados pelo Mi Fitness


ORDEM_ESTAGIOS = ["acordado", "rem", "leve", "profundo"]


def estagios_app(ini: int, fim: int) -> pd.DataFrame:
    """Hipnograma do Mi Fitness (tabela app_estagios) que cai dentro de [ini, fim]."""
    try:
        d = _ler("SELECT inicio, fim, estagio FROM app_estagios WHERE fim > ? AND inicio < ? ORDER BY inicio",
                 (ini, fim))
    except Exception:  # banco antigo sem a tabela
        d = pd.DataFrame(columns=["inicio", "fim", "estagio"])
    d["inicio"] = pd.to_datetime(d.inicio, unit="s", utc=True)
    d["fim"] = pd.to_datetime(d.fim, unit="s", utc=True)
    return d


def rotular(instantes: pd.DatetimeIndex, estagios: pd.DataFrame) -> pd.Series:
    """Estágio do app em cada instante (None fora do hipnograma)."""
    out = pd.Series([None] * len(instantes), index=instantes, dtype=object)
    for e in estagios.itertuples():
        out[(instantes >= e.inicio) & (instantes < e.fim)] = e.estagio
    return out


def carregar_noite(deitou: int, acordou: int, tolerancia: float = 0.2) -> Noite:
    # janela: 1 h antes de deitar até 1 h depois de acordar
    ini, fim = deitou - 3600, acordou + 3600
    b = _ler("SELECT ts_ms FROM batimentos WHERE ts_ms BETWEEN ? AND ? ORDER BY ts_ms",
             (ini * 1000, fim * 1000)).ts_ms.to_numpy()
    rr = np.diff(b).astype(float)
    t = b[1:]
    valido = (rr >= 300) & (rr <= 2000)
    # filtro de diferença sucessiva relativa ao último RR válido
    ultimo = np.nan
    for k in range(len(rr)):
        if not valido[k]:
            ultimo = np.nan  # lacuna: recomeça a referência
            continue
        if not np.isnan(ultimo) and abs(rr[k] - ultimo) > tolerancia * ultimo:
            valido[k] = False
            continue
        ultimo = rr[k]
    rr_df = pd.DataFrame({"t": pd.to_datetime(t, unit="ms", utc=True), "rr_ms": rr, "valido": valido})

    def serie(sql, col):
        d = _ler(sql, (ini, fim))
        return pd.Series(d[col].to_numpy(), index=pd.to_datetime(d.ts, unit="s", utc=True), name=col)

    fc = serie("SELECT ts, fc FROM sono_fc WHERE ts BETWEEN ? AND ? ORDER BY ts", "fc")
    spo2 = serie("SELECT ts, spo2 FROM sono_spo2 WHERE ts BETWEEN ? AND ? ORDER BY ts", "spo2")
    r = _ler("SELECT ts_ms, rpm FROM respiracao WHERE ts_ms BETWEEN ? AND ? ORDER BY ts_ms",
             (ini * 1000, fim * 1000))
    resp = pd.Series(r.rpm.to_numpy(), index=pd.to_datetime(r.ts_ms, unit="ms", utc=True), name="rpm")
    return Noite(deitou, acordou, rr_df, fc, spo2, resp, estagios_app(ini, fim))


# ---------------------------------------------------------------- métricas

def _metricas(rr: np.ndarray, t_s: np.ndarray, espectral: bool) -> dict:
    out = {"n_rr": len(rr)}
    if len(rr) < 10:
        return out
    d = np.diff(rr)
    out["fc_bpm"] = 60000 / rr.mean()
    out["rr_medio_ms"] = rr.mean()
    out["sdnn_ms"] = rr.std(ddof=1)
    out["rmssd_ms"] = float(np.sqrt(np.mean(d ** 2)))
    out["ln_rmssd"] = float(np.log(out["rmssd_ms"])) if out["rmssd_ms"] > 0 else np.nan
    out["pnn50_pct"] = float(np.mean(np.abs(d) > 50) * 100)
    out["sd1_ms"] = float(np.std(d, ddof=1) / np.sqrt(2))
    out["sd2_ms"] = float(np.sqrt(max(2 * out["sdnn_ms"] ** 2 - out["sd1_ms"] ** 2, 0)))
    if espectral and len(rr) >= 60:
        f = np.linspace(0.04, 0.40, 160)
        x = rr - rr.mean()
        p = lombscargle(t_s - t_s[0], x, 2 * np.pi * f, normalize=False)
        lf = np.trapezoid(p[f < 0.15], f[f < 0.15])
        hf = np.trapezoid(p[f >= 0.15], f[f >= 0.15])
        out["lf"], out["hf"] = lf, hf
        out["lf_hf"] = lf / hf if hf > 0 else np.nan
    return out


def janelas(noite: Noite, minutos: int = 5, espectral: bool = True,
            cobertura_min: float = 0.5) -> pd.DataFrame:
    """Métricas de HRV por janela de `minutos`. Janelas com pouca cobertura viram NaN."""
    v = noite.rr[noite.rr.valido]
    if v.empty:
        return pd.DataFrame()
    grupos = v.groupby(v.t.dt.floor(f"{minutos}min"))
    linhas = []
    for inicio, g in grupos:
        # segundos via total_seconds (pandas 3 pode guardar datetimes em ms, não ns)
        t_s = (g.t - pd.Timestamp(0, tz="UTC")).dt.total_seconds().to_numpy()
        m = _metricas(g.rr_ms.to_numpy(), t_s, espectral)
        m["inicio"] = inicio
        m["cobertura"] = g.rr_ms.sum() / (minutos * 60_000)
        linhas.append(m)
    df = pd.DataFrame(linhas).set_index("inicio")
    metricas = [c for c in df.columns if c not in ("n_rr", "cobertura")]
    df.loc[df.cobertura < cobertura_min, metricas] = np.nan
    return df


def auc(positivos, negativos) -> float:
    """Área sob a curva ROC via postos (Mann-Whitney). 0,5 = não separa; 1 ou 0 = separa bem."""
    p, n = np.asarray(positivos, float), np.asarray(negativos, float)
    p, n = p[~np.isnan(p)], n[~np.isnan(n)]
    if not len(p) or not len(n):
        return np.nan
    postos = pd.Series(np.r_[p, n]).rank().to_numpy()
    return (postos[:len(p)].sum() - len(p) * (len(p) + 1) / 2) / (len(p) * len(n))


def resumo_noite(noite: Noite, minutos: int = 5) -> dict:
    """Resumo da noite. RMSSD/LF-HF: mediana das janelas (padrão para registros longos)."""
    j = janelas(noite, minutos)
    validos = noite.rr[noite.rr.valido]
    r = {
        "deitou": pd.to_datetime(noite.deitou, unit="s", utc=True),
        "acordou": pd.to_datetime(noite.acordou, unit="s", utc=True),
        "duracao_h": (noite.acordou - noite.deitou) / 3600,
        "batimentos": len(noite.rr) + 1,
        "rr_validos_pct": 100 * noite.rr.valido.mean() if len(noite.rr) else np.nan,
        "fc_media_relogio": noite.fc_relogio.mean(),
        "fc_min_relogio": noite.fc_relogio.min(),
        "spo2_media": noite.spo2.mean(),
        "spo2_min": noite.spo2.min(),
        "respiracao_media": noite.respiracao.mean(),
    }
    if not j.empty:
        for c in ("rmssd_ms", "ln_rmssd", "sdnn_ms", "pnn50_pct", "lf_hf", "fc_bpm", "sd1_ms", "sd2_ms"):
            if c in j:
                r[f"{c}_mediana"] = j[c].median()
        r["rmssd_ms_p90"] = j["rmssd_ms"].quantile(0.9)
    r["sdnn_noite_ms"] = validos.rr_ms.std(ddof=1) if len(validos) > 1 else np.nan
    e = noite.estagios_app
    if not e.empty:
        dur = (e.fim - e.inicio).dt.total_seconds() / 60
        for estagio in ("profundo", "leve", "rem", "acordado"):
            r[f"app_{estagio}_min"] = float(dur[e.estagio == estagio].sum())
    return r
