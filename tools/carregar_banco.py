"""Decodifica tudo em .dados/brutos e carrega em .dados/smartdata.db.

Uso: .venv\\Scripts\\python tools\\carregar_banco.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartdata.banco import BANCO, carregar_app_sono, carregar_tudo, conectar  # noqa: E402

for arquivo, status in carregar_tudo():
    print(f"{arquivo:55s} {status}")
print(f"Mi Fitness: {carregar_app_sono()} noite(s) com estágios nos logs")

con = conectar()
print(f"\n{BANCO}")
for tabela in ["minutos", "resumo_diario", "sono", "sono_fc", "sono_spo2", "batimentos", "respiracao", "treinos",
               "treino_segundos", "app_sono", "app_estagios"]:
    print(f"  {tabela:14s} {con.execute(f'SELECT COUNT(*) FROM {tabela}').fetchone()[0]:>7} linhas")
