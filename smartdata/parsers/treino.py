"""Treinos (SPORTS_*): resumo (SUMMARY) e detalhes segundo a segundo (DETAILS).

Resumo: espelho do WorkoutSummaryParser.getFreestyleParser + XiaomiSimpleActivityParser
(Gadgetbridge). Como no Java, o bitmap de validade do header NÃO é aplicado (lá está
desativado com FIXME, porque campos desconhecidos podem dessincronizar o bitmap).

Detalhes: o Redmi Watch 2 Lite grava "versão 1" com assinatura 0xC0, que no Gadgetbridge
é o layout da versão 2 (o Gadgetbridge rejeita o arquivo). Layout:
  [ID 7B][0x00][0xC0] e segmentos: [nº registros i32][ts início i32][1 byte ?]
  seguidos de registros de 2 bytes [calorias u8][fc u8], um por segundo.
Uma pausa abre um segmento novo.
"""

import struct

from smartdata.xiaomi.atividade import IdArquivo

from .complexo import Leitor

# (nome, leitor) — None = bytes desconhecidos ("unknown" no Java)
def _campos_livre(versao: int) -> list[tuple[str | None, str]]:
    c: list[tuple[str | None, str]] = [
        ("inicio", "i32"), ("fim", "i32"), ("segundos_ativos", "i32"), ("calorias", "u16"),
        ("fc_media", "u8"), ("fc_max", "u8"), ("fc_min", "u8"),
    ]
    if versao > 5:
        c.append((None, "6"))
    c.append(("efeito_treino_aerobico", "f32"))
    if versao > 6:
        c.append((None, "1"))
    c += [(None, "1"), ("recuperacao_horas", "u16"),
          ("zona_extrema_s", "i32"), ("zona_anaerobica_s", "i32"), ("zona_aerobica_s", "i32"),
          ("zona_queima_gordura_s", "i32"), ("zona_aquecimento_s", "i32")]
    if versao == 5:
        c += [(None, "10"), ("tipo_treino_xiaomi", "u16"), (None, "2"),
              ("meta_tempo_s", "i32"), ("meta_calorias", "u16")]
    else:
        c += [("calorias_total", "u16"), (None, "4"), ("efeito_treino_anaerobico", "f32"), (None, "1"),
              ("tipo_treino_xiaomi", "u16"), (None, "2"), ("meta_tempo_s", "i32"),
              ("meta_calorias", "u16"), ("carga_treino", "u16"), (None, "1")]
        if versao > 7:
            c += [("ganho_vitalidade", "u8"), ("socos_total", "u16"), ("socos_perfeitos", "u16"),
                  ("socos_bons", "u16"), ("socos_errados", "u16"), (None, "7")]
        if versao >= 10:
            c += [("arremessos_baixos", "u16"), ("arremessos_medios", "u16"),
                  ("arremessos_altos", "u16"), (None, "1")]
    return c


TAMANHO_HEADER_LIVRE = {5: 3, 7: 5, 8: 6, 9: 6, 10: 6}


def resumo_treino(id_arq: IdArquivo, dados: bytes) -> dict:
    if id_arq.nome_subtipo != "SPORTS_FREESTYLE":
        raise ValueError(f"Resumo de {id_arq.nome_subtipo} ainda não suportado")
    if id_arq.versao not in TAMANHO_HEADER_LIVRE:
        raise ValueError(f"Versão de resumo de treino livre não suportada: {id_arq.versao}")
    lei = Leitor(dados, 8, len(dados) - 4)
    lei.pular(TAMANHO_HEADER_LIVRE[id_arq.versao])
    r: dict = {"subtipo": id_arq.nome_subtipo}
    for nome, tipo in _campos_livre(id_arq.versao):
        if nome is None:
            lei.pular(int(tipo))
            continue
        if lei.restante() < struct.calcsize("<" + {"i32": "i", "u16": "H", "u8": "B", "f32": "f"}[tipo]):
            break  # arquivos mais curtos que o layout: para sem inventar valores
        r[nome] = getattr(lei, tipo)()
    return r


def detalhes_treino(id_arq: IdArquivo, dados: bytes) -> list[dict]:
    """Uma amostra por segundo: {'timestamp', 'fc', 'calorias'}."""
    if dados[8] != 0xC0:
        raise ValueError(f"Assinatura de detalhes não suportada: {dados[8:10].hex()} (v{id_arq.versao})")
    lei = Leitor(dados, 9, len(dados) - 4)
    amostras = []
    while lei.restante() >= 9:
        nr, ts = lei.i32(), lei.i32()
        lei.u8()  # byte desconhecido do header do segmento
        if nr <= 0:
            break
        for k in range(min(nr, lei.restante() // 2)):
            # Ordem confirmada nos dados reais: soma de cal == calorias do resumo e
            # fc média/máx/mín == as do resumo. (O case 2 do Java lê na ordem inversa.)
            cal, fc = lei.u8(), lei.u8()
            a = {"timestamp": ts + k, "calorias": cal}
            if fc not in (0, 255):
                a["fc"] = fc
            amostras.append(a)
    return amostras
