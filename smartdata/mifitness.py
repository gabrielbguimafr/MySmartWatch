"""Extrai dos logs do Mi Fitness os estágios de sono que o app calculou (hipnograma).

O app registra no log, quando você abre uma noite, objetos como:
  ... deepDuration = 156, remDuration = 121, wakeCount = 1, wakeDuration = 1, ...
  sleepItems = [SleepStateItem(startTime=..., endTime=..., sleepState=3), ...]
Códigos confirmados (a soma por código bate com as durações que o app mostra):
  2 = profundo, 3 = leve, 4 = REM, 5 = acordado
O log quebra linhas longas no meio dos números, então juntamos tudo antes de procurar.
"""

import re
from pathlib import Path

ESTAGIOS_APP = {2: "profundo", 3: "leve", 4: "rem", 5: "acordado"}
PASTA_LOGS = Path(__file__).resolve().parent.parent / ".dados" / "mifitness_logs"

_ITENS = re.compile(r"sleepItems = \[(.*?)\]")
_ITEM = re.compile(r"startTime=(\d+), endTime=(\d+), sleepState=(\d+)")
_CAMPO = re.compile(r"\b(deepDuration|lightDuration|remDuration|wakeDuration|wakeCount|sleepDuration)"
                    r" ?= ?(\d+)")


def extrair(pasta: Path = PASTA_LOGS) -> list[dict]:
    """Uma entrada por noite (a versão mais completa, se aparecer várias vezes no log)."""
    texto = "".join(f.read_text(encoding="utf-8", errors="ignore")
                    for f in sorted(pasta.rglob("*")) if f.is_file())
    texto = texto.replace("\r", "").replace("\n", "")
    noites: dict[int, dict] = {}
    for m in _ITENS.finditer(texto):
        itens = [(int(a), int(b), int(c)) for a, b, c in _ITEM.findall(m.group(1))]
        if not itens:
            continue
        contexto = texto[max(0, m.start() - 600):m.start()]
        campos = {k: int(v) for k, v in _CAMPO.findall(contexto)}
        inicio = itens[0][0]
        if inicio in noites and len(noites[inicio]["estagios"]) >= len(itens):
            continue
        noites[inicio] = {
            "inicio": inicio, "fim": itens[-1][1],
            "profundo_min": campos.get("deepDuration"), "leve_min": campos.get("lightDuration"),
            "rem_min": campos.get("remDuration"), "acordado_min": campos.get("wakeDuration"),
            "despertares": campos.get("wakeCount"),
            "estagios": [{"inicio": a, "fim": b, "estagio": ESTAGIOS_APP.get(c, f"codigo_{c}")}
                         for a, b, c in itens],
        }
    return sorted(noites.values(), key=lambda n: n["inicio"])
