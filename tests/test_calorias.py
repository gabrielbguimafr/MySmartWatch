"""Equações de gasto calórico conferidas contra valores calculados à mão, e a página de calorias."""

import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402

from smartdata.analise import calorias as cal  # noqa: E402

# perfil genérico de teste (não é o do usuário: dados pessoais não entram no git)
HOMEM = cal.Perfil("masculino", date(date.today().year - 30, 1, 1), 175, 70, 190)  # 30 anos


def test_equacoes():
    assert abs(cal.tmb_mifflin(HOMEM) - 1648.75) < 0.01        # 700 + 1093,75 − 150 + 5
    assert abs(cal.tmb_harris_benedict(HOMEM) - 1695.67) < 0.1  # 88,362 + 937,79 + 839,825 − 170,31
    # Keytel, FC 120: (−55,0969 + 75,708 + 13,916 + 6,051) = 40,5781 kJ / 4,184 = 9,698 kcal/min
    assert abs(cal.keytel_bruto([120], HOMEM)[0] - 9.698) < 0.01
    assert cal.keytel_bruto([20], HOMEM)[0] == 0                # negativo vira 0
    assert np.isclose(cal.keytel_liquido([120], HOMEM, 1440)[0], 9.698 - 1, atol=0.01)


def test_modelo_recupera_coeficientes():
    import pandas as pd
    rng = np.random.default_rng(1)
    passos = rng.integers(0, 130, 2000).astype(float)
    fc = rng.uniform(55, 140, 2000)
    y = 0.03 * passos + 0.08 * np.maximum(fc - 80, 0)
    m = pd.DataFrame({"passos": passos, "fc": fc, "calorias_ativas": y})
    mod = cal.ajustar_passos_fc(m)
    assert mod.limiar == 80 and abs(mod.a - 0.03) < 1e-6 and abs(mod.b - 0.08) < 1e-6 and mod.r2 > 0.999


def test_pagina_calorias():
    if not (RAIZ / ".dados" / "smartdata.db").exists():
        return
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(RAIZ / "app" / "pages" / "calorias.py"), default_timeout=120).run()
    assert not at.exception, at.exception
    for tipo in at.sidebar.selectbox[1].options:
        at.sidebar.selectbox[1].set_value(tipo).run()
        assert not at.exception, (tipo, at.exception)
    at.sidebar.checkbox[0].set_value(True).run()  # acumulado
    assert not at.exception, at.exception


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            print(f"ok {nome}")
