"""Extração do hipnograma do Mi Fitness a partir de um log sintético."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartdata.mifitness import extrair  # noqa: E402

LOG = (
    "2026-11-21 12:00:00.000|3.60.0i|I|Sleep|SleepData(lightDuration = 10, deepDuration = 5, "
    "remDuration = 3, wakeCount = 1, wakeDuration = 1, sleepItems = [SleepStateItem(startTime=1000, "
    "endTime=1300, sleepState=2), SleepStateItem(startTime=1300, endTime=1900, sleepState=3), "
    "SleepStateItem(startTime=1900, endTime=20\n80, sleepState=4), SleepStateItem(startTime=2080, "
    "endTime=2140, sleepState=5)])\n"
)


def test_extrai_hipnograma_com_quebra_de_linha():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "XiaomiFit.main.log").write_text(LOG + LOG, encoding="utf-8")  # duplicado de propósito
        noites = extrair(Path(d))
    assert len(noites) == 1
    n = noites[0]
    assert (n["inicio"], n["fim"]) == (1000, 2140)
    assert [e["estagio"] for e in n["estagios"]] == ["profundo", "leve", "rem", "acordado"]
    assert n["estagios"][2]["fim"] == 2080  # número quebrado no meio pelo log
    assert (n["profundo_min"], n["leve_min"], n["rem_min"], n["despertares"]) == (5, 10, 3, 1)


if __name__ == "__main__":
    test_extrai_hipnograma_com_quebra_de_linha()
    print("ok test_extrai_hipnograma_com_quebra_de_linha")
