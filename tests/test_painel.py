"""Roda o painel sem navegador, em todas as combinações de tipo de gráfico e organização."""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(RAIZ / "app" / "painel.py")


def test_todas_combinacoes():
    if not (RAIZ / ".dados" / "smartdata.db").exists():
        print("  sem banco, pulando")
        return
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception, at.exception
    todas = at.sidebar.multiselect[1].options
    at.sidebar.multiselect[1].set_value(list(todas)).run()
    assert not at.exception, at.exception
    falhas = []
    for tipo in at.sidebar.selectbox[0].options:
        for arranjo in at.sidebar.radio[1].options:
            for x in at.sidebar.radio[0].options:
                at.sidebar.selectbox[0].set_value(tipo)
                at.sidebar.radio[1].set_value(arranjo)
                at.sidebar.radio[0].set_value(x)
                at.run()
                if at.exception:
                    falhas.append((tipo, arranjo, x, at.exception[0].message))
    at.sidebar.slider[0].set_value(5).run()  # suavização
    at.sidebar.select_slider[0].set_value(1).run()  # janela de 1 min
    if at.exception:
        falhas.append(("suavizacao/janela", at.exception[0].message))
    assert not falhas, falhas


if __name__ == "__main__":
    test_todas_combinacoes()
    print("ok test_todas_combinacoes")
