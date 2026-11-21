"""Atividade diária: amostras por minuto (DETAILS) e resumo do dia (SUMMARY).

Portado de DailyDetailsParser.java e DailySummaryParser.java (Gadgetbridge).
Todos os arquivos: [ID 7B][0x00][header][registros...][CRC32 4B].
"""

from smartdata.xiaomi.atividade import IdArquivo

from .complexo import Leitor, ParserComplexo, bit_valido

TAMANHO_HEADER_DETALHES = {1: 4, 2: 4, 3: 5, 4: 6}


def detalhes_diarios(id_arq: IdArquivo, dados: bytes) -> list[dict]:
    """Uma amostra por minuto a partir da meia-noite do arquivo.

    Campos (só presentes quando válidos): passos, calorias_ativas (kcal),
    distancia_cm, fc (bpm), energia, spo2 (%), estresse (0-100).
    """
    versao = id_arq.versao
    if versao not in TAMANHO_HEADER_DETALHES:
        raise ValueError(f"Versão de detalhes diários não suportada: {versao}")

    lei = Leitor(dados, 8, len(dados) - 4)  # pula ID + padding, descarta CRC
    header = lei.bytes(TAMANHO_HEADER_DETALHES[versao])
    p = ParserComplexo(header, lei)

    amostras, ts = [], id_arq.timestamp
    while lei.restante() > 0:
        p.reset()
        a: dict = {"timestamp": ts}
        extra = 0
        if p.proximo_grupo(16):
            if p.tem(1):
                extra = p.get(1, 1)
            if p.tem(2):
                a["passos"] = p.get(2, 14)
        if p.proximo_grupo(8) and p.tem(1):
            a["calorias_ativas"] = p.get(2, 6)
        p.proximo_grupo(8)  # desconhecido
        if p.proximo_grupo(16) and p.tem(0):
            a["distancia_cm"] = p.get(0, 16) * 100
        if p.proximo_grupo(8) and p.tem(0):
            fc = p.get(0, 8)
            if fc not in (0, 255):  # 0 = não medido neste minuto
                a["fc"] = fc
        if p.proximo_grupo(8) and p.tem(0):
            a["energia"] = p.get(0, 8)
        p.proximo_grupo(16)  # desconhecido
        if versao >= 3:
            if p.proximo_grupo(8) and p.tem(0):
                spo2 = p.get(0, 8)
                if spo2 not in (0, 255):
                    a["spo2"] = spo2
            if p.proximo_grupo(8) and p.tem(0):
                estresse = p.get(0, 8)
                if estresse != 255:
                    a["estresse"] = estresse
        if extra == 1:
            lei.u8()
        if versao >= 4:
            p.proximo_grupo(16)
            p.proximo_grupo(16)
        amostras.append(a)
        ts += 60
    return amostras


# (nome, leitor) na ordem do bitmap; None = byte(s) reservado(s) descartado(s)
_CAMPOS_RESUMO = [
    ("passos", "u32"), ("calorias_ativas", "u16"), (None, "u8"),
    ("fc_repouso", "u8"), ("fc_max", "u8"), ("fc_max_ts", "i32"),
    ("fc_min", "u8"), ("fc_min_ts", "i32"), ("fc_media", "u8"),
    ("estresse_medio", "u8"), ("estresse_max", "u8"), ("estresse_min", "u8"),
    ("em_pe_bitmap", "u24"), ("calorias", "u16"), ("recuperacao_horas", "u16"), (None, "u8"),
    ("spo2_max", "u8"), ("spo2_max_ts", "i32"), ("spo2_min", "u8"), ("spo2_min_ts", "i32"),
    ("spo2_medio", "u8"),
    ("carga_treino_dia", "u16"), ("carga_treino_semana", "u16"), ("carga_treino_nivel", "u8"),
    ("vitalidade_leve", "u8"), ("vitalidade_moderada", "u8"), ("vitalidade_alta", "u8"),
    ("vitalidade_atual", "u16"), (None, "u8"), (None, "u8"), (None, "u16"), (None, "u16"),
]
_VERSOES_RESUMO = {3: (3, 21), 4: (3, 21), 5: (4, 32)}  # versão -> (tamanho header, nº campos)


def resumo_diario(id_arq: IdArquivo, dados: bytes) -> dict:
    if id_arq.versao not in _VERSOES_RESUMO:
        raise ValueError(f"Versão de resumo diário não suportada: {id_arq.versao}")
    tam_header, n_campos = _VERSOES_RESUMO[id_arq.versao]
    lei = Leitor(dados, 8, len(dados) - 4)
    header = lei.bytes(tam_header)
    r: dict = {"timestamp": id_arq.timestamp, "fuso_15min": id_arq.fuso}
    for i, (nome, tipo) in enumerate(_CAMPOS_RESUMO[:n_campos]):
        if tipo == "u24":
            b = lei.bytes(3)
            valor = b[0] | b[1] << 8 | b[2] << 16
        else:
            valor = getattr(lei, tipo)()
        if nome and bit_valido(header, i):
            r[nome] = valor
    return r
