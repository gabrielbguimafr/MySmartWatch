"""Gasto calórico: o que o relógio reporta e como se compara a modelos conhecidos.

Conceitos:
  Gasto total diário (TDEE) = TMB + gasto ativo (+ efeito térmico dos alimentos, ~10%).
  TMB (taxa metabólica basal): energia gasta em repouso absoluto. Estimada por equações
  de regressão sobre peso, altura, idade e sexo:
    Mifflin-St Jeor (1990), homem:  10·P + 6,25·A − 5·I + 5
    Harris-Benedict revisada (Roza & Shizgal 1984), homem: 88,362 + 13,397·P + 4,799·A − 5,677·I
  Keytel et al. (2005): gasto BRUTO por minuto a partir da FC (validada em exercício):
    homem: kJ/min = −55,0969 + 0,6309·FC + 0,1988·P + 0,2017·I   (÷ 4,184 → kcal)
  Gasto LÍQUIDO (ativo) = bruto − TMB por minuto, que é o que o relógio chama de "calorias ativas".

Achados nos dados (detalhados na documentação):
  - As calorias ativas por minuto acompanham os PASSOS (r ≈ 0,83) mais que a FC.
  - Sem passos, o relógio só credita calorias com FC bem acima do repouso (limiar ~85-90 bpm).
  - Keytel superestima muito em FC baixa (2-3,5× nos treinos), como a literatura já aponta.
"""

from dataclasses import dataclass
from datetime import date
import sqlite3

import numpy as np
import pandas as pd

from smartdata.config import ler_env
from smartdata.analise.hrv import BANCO

KCAL_POR_KJ = 1 / 4.184


@dataclass
class Perfil:
    sexo: str          # "masculino" | "feminino"
    nascimento: date
    altura_cm: float
    peso_kg: float
    fc_max: float

    @property
    def idade(self) -> int:
        hoje = date.today()
        return hoje.year - self.nascimento.year - ((hoje.month, hoje.day) < (self.nascimento.month, self.nascimento.day))

    @property
    def homem(self) -> bool:
        return self.sexo.lower().startswith("m")


def perfil_do_env() -> Perfil:
    e = ler_env()
    return Perfil(e.get("PERFIL_SEXO", "masculino"), date.fromisoformat(e.get("PERFIL_NASCIMENTO", "2000-01-01")),
                  float(e.get("PERFIL_ALTURA_CM", 175)), float(e.get("PERFIL_PESO_KG", 75)),
                  float(e.get("PERFIL_FC_MAX", 190)))


# ------------------------------------------------------------------ equações

def tmb_mifflin(p: Perfil) -> float:
    return 10 * p.peso_kg + 6.25 * p.altura_cm - 5 * p.idade + (5 if p.homem else -161)


def tmb_harris_benedict(p: Perfil) -> float:
    if p.homem:
        return 88.362 + 13.397 * p.peso_kg + 4.799 * p.altura_cm - 5.677 * p.idade
    return 447.593 + 9.247 * p.peso_kg + 3.098 * p.altura_cm - 4.330 * p.idade


TMB = {"Mifflin-St Jeor": tmb_mifflin, "Harris-Benedict": tmb_harris_benedict}


def keytel_bruto(fc, p: Perfil) -> np.ndarray:
    """kcal/min (bruto, inclui o basal). Valores negativos (FC muito baixa) viram 0."""
    fc = np.asarray(fc, float)
    if p.homem:
        kj = -55.0969 + 0.6309 * fc + 0.1988 * p.peso_kg + 0.2017 * p.idade
    else:
        kj = -20.4022 + 0.4472 * fc - 0.1263 * p.peso_kg + 0.074 * p.idade
    return np.maximum(kj * KCAL_POR_KJ, 0)


def keytel_liquido(fc, p: Perfil, tmb_dia: float) -> np.ndarray:
    return np.maximum(keytel_bruto(fc, p) - tmb_dia / 1440, 0)


# ------------------------------------------------------------------ dados

def _ler(sql: str, params=()) -> pd.DataFrame:
    with sqlite3.connect(BANCO) as con:
        return pd.read_sql(sql, con, params=params)


def minutos() -> pd.DataFrame:
    m = _ler("SELECT * FROM minutos ORDER BY ts")
    m["passos"] = m.passos.fillna(0)
    m["distancia_cm"] = m.distancia_cm.fillna(0)
    m["t"] = pd.to_datetime(m.ts, unit="s", utc=True)
    return m


def resumos() -> pd.DataFrame:
    r = _ler("SELECT ts, fuso_15min, passos, calorias_ativas, calorias, fc_repouso, fc_media FROM resumo_diario ORDER BY ts")
    r["t"] = pd.to_datetime(r.ts, unit="s", utc=True)
    return r


def treinos() -> pd.DataFrame:
    return _ler("SELECT * FROM treinos ORDER BY inicio")


def treino_segundos(inicio: int, fim: int) -> pd.DataFrame:
    return _ler("SELECT * FROM treino_segundos WHERE ts BETWEEN ? AND ? ORDER BY ts", (inicio, fim))


# ------------------------------------------------------------------ modelos ajustados

@dataclass
class ModeloPassosFC:
    """kcal_ativas/min ≈ a·passos + b·max(FC − limiar, 0)   (mínimos quadrados, sem intercepto)."""
    a: float
    b: float
    limiar: float
    r2: float
    r2_so_passos: float
    n: int
    a_so_passos: float = 0.0  # kcal/passo do modelo que usa só passos

    def prever(self, passos, fc) -> np.ndarray:
        fc = np.nan_to_num(np.asarray(fc, float), nan=0.0)
        return self.a * np.asarray(passos, float) + self.b * np.maximum(fc - self.limiar, 0)


def _r2(y, pred) -> float:
    return float(1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum())


def ajustar_passos_fc(m: pd.DataFrame, limiares=range(60, 111, 2)) -> ModeloPassosFC:
    """Ajusta nos minutos com FC medida; escolhe o limiar de FC que maximiza o R²."""
    d = m.dropna(subset=["fc", "calorias_ativas"])
    y = d.calorias_ativas.to_numpy(float)
    passos = d.passos.to_numpy(float)
    a0 = float(np.linalg.lstsq(passos[:, None], y, rcond=None)[0][0])
    r2_passos = _r2(y, a0 * passos)
    melhor = None
    for lim in limiares:
        X = np.column_stack([passos, np.maximum(d.fc.to_numpy(float) - lim, 0)])
        coef = np.linalg.lstsq(X, y, rcond=None)[0]
        r2 = _r2(y, X @ coef)
        if melhor is None or r2 > melhor.r2:
            melhor = ModeloPassosFC(float(coef[0]), float(coef[1]), float(lim), r2, r2_passos, len(d))
    # inclinação "só passos" sobre TODOS os minutos (com e sem FC), para o gráfico de passos
    todos = m.dropna(subset=["calorias_ativas"])
    melhor.a_so_passos = float(np.linalg.lstsq(todos.passos.to_numpy(float)[:, None],
                                               todos.calorias_ativas.to_numpy(float), rcond=None)[0][0])
    return melhor


def tabela_diaria(p: Perfil, m: pd.DataFrame, r: pd.DataFrame, fuso_h: float) -> pd.DataFrame:
    """Uma linha por dia: o que o relógio diz e o que cada equação daria."""
    m = m.copy()
    m["dia"] = (m.t + pd.Timedelta(hours=fuso_h)).dt.date
    g = m.groupby("dia").agg(minutos=("ts", "size"), passos=("passos", "sum"),
                             km=("distancia_cm", lambda s: s.sum() / 1e5),
                             ativas_minutos=("calorias_ativas", "sum"),
                             min_com_fc=("fc", "count"), fc_media=("fc", "mean"))
    r = r.copy()
    r["dia"] = (r.t + pd.Timedelta(hours=fuso_h)).dt.date
    g = g.join(r.set_index("dia")[["calorias", "calorias_ativas", "fc_repouso"]]
               .rename(columns={"calorias": "total_relogio", "calorias_ativas": "ativas_relogio"}))
    g["basal_implicito"] = g.total_relogio - g.ativas_relogio
    g["completo"] = g.minutos >= 1440
    for nome, f in TMB.items():
        g[f"tmb_{nome}"] = f(p) * g.minutos / 1440
    g["kcal_por_100_passos"] = 100 * g.ativas_relogio / g.passos.replace(0, np.nan)
    return g
