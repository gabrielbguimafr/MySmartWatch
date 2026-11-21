"""Carrega os arquivos brutos decodificados em um SQLite local (.dados/smartdata.db).

Tabelas (timestamps Unix em segundos, UTC; batimentos em ms):
  minutos(ts, passos, calorias_ativas, distancia_cm, fc, spo2, estresse)
  resumo_diario(ts, ...campos do resumo..., json)
  sono(deitou, acordou, ...)            uma linha por noite
  sono_fc(ts, fc) / sono_spo2(ts, spo2) séries durante o sono
  batimentos(ts_ms)                     instante de cada batimento detectado (HRV)
  respiracao(ts_ms, rpm)
A carga é idempotente: recarregar um arquivo substitui as linhas dele.
"""

import json
import sqlite3
from pathlib import Path

from smartdata.parsers.diario import detalhes_diarios, resumo_diario
from smartdata.parsers.sono import sono
from smartdata.parsers.treino import detalhes_treino, resumo_treino
from smartdata.xiaomi.atividade import IdArquivo

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / ".dados" / "smartdata.db"
BRUTOS = RAIZ / ".dados" / "brutos"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS arquivos (caminho TEXT PRIMARY KEY, tipo TEXT, ts INTEGER, versao INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS minutos (ts INTEGER PRIMARY KEY, passos INTEGER, calorias_ativas INTEGER,
    distancia_cm INTEGER, fc INTEGER, spo2 INTEGER, estresse INTEGER);
CREATE TABLE IF NOT EXISTS resumo_diario (ts INTEGER PRIMARY KEY, fuso_15min INTEGER, passos INTEGER,
    calorias_ativas INTEGER, calorias INTEGER, fc_repouso INTEGER, fc_min INTEGER, fc_max INTEGER,
    fc_media INTEGER, spo2_min INTEGER, spo2_max INTEGER, spo2_medio INTEGER, estresse_medio INTEGER, json TEXT);
CREATE TABLE IF NOT EXISTS sono (deitou INTEGER PRIMARY KEY, acordou INTEGER, versao INTEGER,
    total_min INTEGER, profundo_min INTEGER, leve_min INTEGER, rem_min INTEGER, acordado_min INTEGER,
    n_pacotes_desconhecidos INTEGER);
CREATE TABLE IF NOT EXISTS sono_fc (ts INTEGER PRIMARY KEY, fc INTEGER);
CREATE TABLE IF NOT EXISTS sono_spo2 (ts INTEGER PRIMARY KEY, spo2 INTEGER);
CREATE TABLE IF NOT EXISTS batimentos (ts_ms INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS respiracao (ts_ms INTEGER PRIMARY KEY, rpm INTEGER);
CREATE TABLE IF NOT EXISTS treinos (inicio INTEGER PRIMARY KEY, fim INTEGER, subtipo TEXT,
    segundos_ativos INTEGER, calorias INTEGER, fc_media INTEGER, fc_max INTEGER, fc_min INTEGER, json TEXT);
CREATE TABLE IF NOT EXISTS treino_segundos (ts INTEGER PRIMARY KEY, fc INTEGER, calorias INTEGER);
CREATE TABLE IF NOT EXISTS app_sono (inicio INTEGER PRIMARY KEY, fim INTEGER, profundo_min INTEGER,
    leve_min INTEGER, rem_min INTEGER, acordado_min INTEGER, despertares INTEGER);
CREATE TABLE IF NOT EXISTS app_estagios (inicio INTEGER PRIMARY KEY, fim INTEGER, estagio TEXT,
    noite INTEGER);
"""

COLUNAS_RESUMO = ["passos", "calorias_ativas", "calorias", "fc_repouso", "fc_min", "fc_max", "fc_media",
                  "spo2_min", "spo2_max", "spo2_medio", "estresse_medio"]


def conectar() -> sqlite3.Connection:
    BANCO.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(BANCO)
    con.executescript(ESQUEMA)
    return con


def _carregar(con: sqlite3.Connection, i: IdArquivo, d: bytes) -> str:
    sub, det = i.nome_subtipo, i.nome_detalhe
    if sub == "ACTIVITY_DAILY" and det == "DETAILS":
        linhas = [(m["timestamp"], m.get("passos"), m.get("calorias_ativas"), m.get("distancia_cm"),
                   m.get("fc"), m.get("spo2"), m.get("estresse")) for m in detalhes_diarios(i, d)]
        con.executemany("INSERT OR REPLACE INTO minutos VALUES (?,?,?,?,?,?,?)", linhas)
        return f"{len(linhas)} minutos"
    if sub == "ACTIVITY_DAILY" and det == "SUMMARY":
        r = resumo_diario(i, d)
        con.execute(f"INSERT OR REPLACE INTO resumo_diario VALUES (?,?,{','.join('?' * len(COLUNAS_RESUMO))},?)",
                    [r["timestamp"], r["fuso_15min"], *[r.get(c) for c in COLUNAS_RESUMO], json.dumps(r)])
        return "resumo"
    if sub == "ACTIVITY_SLEEP" and det == "DETAILS":
        s = sono(i, d)
        con.execute("INSERT OR REPLACE INTO sono VALUES (?,?,?,?,?,?,?,?,?)",
                    (s["deitou"], s["acordou"], i.versao, s.get("total_min"), s.get("profundo_min"),
                     s.get("leve_min"), s.get("rem_min"), s.get("acordado_min"),
                     len(s["pacotes_desconhecidos"])))
        con.executemany("INSERT OR REPLACE INTO sono_fc VALUES (?,?)",
                        [(x["timestamp"], x["valor"]) for x in s.get("fc_serie", [])])
        spo2 = s.get("spo2_serie") or s.get("spo2_serie_hipotese", [])
        con.executemany("INSERT OR REPLACE INTO sono_spo2 VALUES (?,?)", [(x["timestamp"], x["valor"]) for x in spo2])
        con.executemany("INSERT OR IGNORE INTO batimentos VALUES (?)", [(b,) for b in s["batimentos_ms"]])
        con.executemany("INSERT OR REPLACE INTO respiracao VALUES (?,?)",
                        [(x["timestamp_ms"], x["rpm"]) for x in s["respiracao"]])
        return f"sono: {len(s['batimentos_ms'])} batimentos"
    if sub.startswith("SPORTS_") and det == "SUMMARY":
        r = resumo_treino(i, d)
        con.execute("INSERT OR REPLACE INTO treinos VALUES (?,?,?,?,?,?,?,?,?)",
                    (r["inicio"], r["fim"], sub, r.get("segundos_ativos"), r.get("calorias"),
                     r.get("fc_media"), r.get("fc_max"), r.get("fc_min"), json.dumps(r)))
        return "resumo de treino"
    if sub.startswith("SPORTS_") and det == "DETAILS":
        a = detalhes_treino(i, d)
        con.executemany("INSERT OR REPLACE INTO treino_segundos VALUES (?,?,?)",
                        [(x["timestamp"], x.get("fc"), x["calorias"]) for x in a])
        return f"{len(a)} segundos de treino"
    if sub == "ACTIVITY_MANUAL_SAMPLES" and len(d) <= 13:
        return "vazio"
    return "sem decodificador"


def carregar_app_sono() -> int:
    """Estágios de sono calculados pelo Mi Fitness (extraídos dos logs do app)."""
    from smartdata.mifitness import extrair
    noites = extrair()
    con = conectar()
    with con:
        for n in noites:
            con.execute("INSERT OR REPLACE INTO app_sono VALUES (?,?,?,?,?,?,?)",
                        (n["inicio"], n["fim"], n["profundo_min"], n["leve_min"], n["rem_min"],
                         n["acordado_min"], n["despertares"]))
            con.execute("DELETE FROM app_estagios WHERE noite = ?", (n["inicio"],))
            con.executemany("INSERT OR REPLACE INTO app_estagios VALUES (?,?,?,?)",
                            [(e["inicio"], e["fim"], e["estagio"], n["inicio"]) for e in n["estagios"]])
    con.close()
    return len(noites)


def carregar_tudo() -> list[tuple[str, str]]:
    con = conectar()
    resultado = []
    with con:
        for f in sorted(BRUTOS.rglob("*.bin")):
            d = f.read_bytes()
            i = IdArquivo.de_bytes(d)
            try:
                status = _carregar(con, i, d)
            except Exception as erro:  # um arquivo ruim não impede os outros
                status = f"erro: {erro!r}"
            con.execute("INSERT OR REPLACE INTO arquivos VALUES (?,?,?,?,?)",
                        (str(f.relative_to(BRUTOS)), f"{i.nome_subtipo}/{i.nome_detalhe}", i.timestamp, i.versao, status))
            resultado.append((str(i), status))
    con.close()
    return resultado
