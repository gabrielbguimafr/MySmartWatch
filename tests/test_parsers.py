"""Testes dos decodificadores com os arquivos reais em .dados/brutos (pulados se não houver)."""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from smartdata.parsers.diario import detalhes_diarios, resumo_diario  # noqa: E402
from smartdata.parsers.sono import sono  # noqa: E402
from smartdata.xiaomi.atividade import IdArquivo  # noqa: E402

BRUTOS = RAIZ / ".dados" / "brutos"


def _arquivos(padrao: str):
    return sorted(BRUTOS.rglob(padrao)) if BRUTOS.exists() else []


def _ler(f: Path):
    d = f.read_bytes()
    return IdArquivo.de_bytes(d), d


def test_detalhes_batem_com_resumo():
    """Soma dos minutos == totais que o próprio relógio calcula no resumo do dia."""
    resumos = {f.name[:15]: f for f in _arquivos("ACTIVITY_DAILY/SUMMARY/*.bin")}
    testados = 0
    for f in _arquivos("ACTIVITY_DAILY/DETAILS/*.bin"):
        if f.name[:15] not in resumos:
            continue
        i, d = _ler(f)
        minutos = detalhes_diarios(i, d)
        r = resumo_diario(*_ler(resumos[f.name[:15]]))
        assert len(minutos) <= 1440
        assert sum(m.get("passos", 0) for m in minutos) == r["passos"]
        assert sum(m.get("calorias_ativas", 0) for m in minutos) == r["calorias_ativas"]
        fcs = [m["fc"] for m in minutos if "fc" in m]
        if fcs and r.get("fc_max"):
            assert max(fcs) == r["fc_max"] and min(fcs) == r["fc_min"]
        testados += 1
    print(f"  {testados} dia(s) conferido(s)")


def test_sono_plausivel():
    for f in _arquivos("ACTIVITY_SLEEP/DETAILS/*.bin"):
        s = sono(*_ler(f))
        assert s["deitou"] < s["acordou"]
        fc = [x["valor"] for x in s["fc_serie"]]
        assert fc and 35 <= sum(fc) / len(fc) <= 100
        b = s["batimentos_ms"]
        rr = [b[k + 1] - b[k] for k in range(len(b) - 1) if 300 < b[k + 1] - b[k] < 2000]
        assert 600 < sum(rr) / len(rr) < 1500  # intervalo RR médio de sono: 40-100 bpm
        assert all(85 <= x["valor"] <= 100 for x in s.get("spo2_serie_hipotese", []))


def test_treino_detalhes_batem_com_resumo():
    from smartdata.parsers.treino import detalhes_treino, resumo_treino
    resumos = {f.name[:15]: f for f in _arquivos("SPORTS_FREESTYLE/SUMMARY/*.bin")}
    for f in _arquivos("SPORTS_FREESTYLE/DETAILS/*.bin"):
        r = resumo_treino(*_ler(resumos[f.name[:15]]))
        a = detalhes_treino(*_ler(f))
        fc = [x["fc"] for x in a if "fc" in x]
        assert len(a) == r["segundos_ativos"]
        assert sum(x["calorias"] for x in a) == r["calorias"]
        assert (max(fc), min(fc), round(sum(fc) / len(fc))) == (r["fc_max"], r["fc_min"], r["fc_media"])
        assert a[0]["timestamp"] == r["inicio"]


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            print(f"ok {nome}")
