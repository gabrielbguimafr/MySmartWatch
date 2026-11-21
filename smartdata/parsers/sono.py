"""Sono (ACTIVITY_SLEEP / DETAILS). Portado de SleepDetailsParser.java (Gadgetbridge).

Estrutura:
  [ID 7B][0x00][header 1-2B (bitmap)]
  [acordado u8][hora_deitou u32][hora_acordou u32][qualidade u8 se v>=4 e válida]
  [v>=5: 9 bytes ? + hora_na_cama u32 + hora_acordou2 u32]
  até 3 blocos antigos (unidade u16, contagem u16, [t0 u32], dados) que são pulados
  depois uma sequência de pacotes, cada um começando pela assinatura fb fa fc ff:
    [tam_header u8 (17)][ts i64][paridade u8][tipo u8][tam_dados u16 big-endian][dados big-endian]
    tipo 1   -> intervalos entre batimentos (deltas em 10 ms)  => HRV
    tipo 10  -> frequência respiratória (janela de 10 min)
    tipo 16  -> resumo: durações de sono/acordado/leve/REM/profundo (minutos)
    tipo 17  -> estágios: pares (estágio 4 bits, duração 12 bits em minutos)
"""

import struct

from smartdata.xiaomi.atividade import IdArquivo

from .complexo import Leitor, bit_valido

ASSINATURA = 0xFFFCFAFB
TIPOS_SEM_DADOS = {0x2, 0x3, 0x9, 0xC, 0xD, 0xE, 0xF, 0x12}
ESTAGIOS = {0: "acordado", 1: "leve", 2: "profundo", 3: "rem", 4: "fora_do_sono"}


def _proximo_pacote(lei: Leitor) -> bool:
    """Procura a assinatura avançando byte a byte (readStagePacketHeader)."""
    while lei.restante() >= 17:
        if lei.u32() == ASSINATURA:
            return True
        lei.pos -= 3
    return False


def sono(id_arq: IdArquivo, dados: bytes) -> dict:
    v = id_arq.versao
    if v not in (1, 2, 3, 4, 5):
        raise ValueError(f"Versão de sono não suportada: {v}")
    lei = Leitor(dados, 8, len(dados) - 4)
    header = lei.bytes(2 if v == 5 else 1)

    idx = 0
    r: dict = {"acordado_flag": lei.u8()}
    idx += 1
    r["deitou"] = lei.i32()
    idx += 1
    r["acordou"] = lei.i32()
    idx += 1
    if v >= 4:
        if bit_valido(header, idx):
            r["qualidade"] = lei.u8()
        idx += 1
    if v >= 5:
        lei.pular(9)
        r["na_cama"] = lei.i32()
        lei.i32()
        idx += 5

    # Blocos de séries temporais (o Gadgetbridge pula). Pelo conteúdo observado no
    # Redmi Watch 2 Lite: bloco 0 = FC por minuto (bpm), bloco 1 = SpO2 (%) a cada ~12 min.
    # Bloco 2 (v>=3, 4 bytes por valor) ainda não identificado.
    nomes = ["fc_serie", "spo2_serie", "bloco3_serie"]
    for bloco in range(3):
        if bloco == 2 and v < 3:
            break
        if bit_valido(header, idx):
            unidade = lei.u16()  # segundos entre valores
            contagem = lei.u16()
            if contagem > 0:
                t0 = lei.u32() if v >= 2 else r["deitou"]
                largura = 4 if bloco == 2 else 1
                brutos = lei.bytes(contagem * largura)
                valores = (list(brutos) if largura == 1
                           else list(struct.unpack(f"<{contagem}I", brutos)))
                r[nomes[bloco]] = [{"timestamp": t0 + k * unidade, "valor": x}
                                   for k, x in enumerate(valores) if x not in (0, 255)]
        idx += 1

    # HIPÓTESE (não está no Gadgetbridge): no Redmi Watch 2 Lite, logo depois da série de FC
    # vem outra série com o mesmo formato [unidade u16][contagem u16][t0 u32][valores u8],
    # mesmo com o bit do header desligado. Os valores (~90-98) parecem SpO2.
    if "spo2_serie" not in r and lei.restante() >= 8:
        inicio = lei.pos
        unidade, contagem, t0 = struct.unpack_from("<HHI", dados, inicio)
        fim_serie = inicio + 8 + contagem
        if (0 < contagem < 200 and 60 <= unidade <= 3600 and fim_serie + 4 <= lei.fim
                and struct.unpack_from("<I", dados, fim_serie)[0] == ASSINATURA
                and abs(t0 - r["deitou"]) < 6 * 3600):
            valores = dados[inicio + 8:fim_serie]
            r["spo2_serie_hipotese"] = [{"timestamp": t0 + k * unidade, "valor": x}
                                        for k, x in enumerate(valores) if x not in (0, 255)]
            lei.pos = fim_serie

    resumos, estagios, batimentos, respiracao, desconhecidos = [], [], [], [], []
    ultimo_batimento_ms = 0
    while lei.restante() >= 17:
        if not _proximo_pacote(lei):
            break
        lei.u8()  # tamanho do header (17)
        ts = lei.i64()
        lei.u8()  # paridade
        tipo = lei.u8()
        tam = struct.unpack(">H", lei.bytes(2))[0]
        if tipo in TIPOS_SEM_DADOS:
            continue
        corpo = lei.bytes(tam)

        if tipo == 0:  # não decodificado pelo Gadgetbridge (150 B a cada ~10 min); guardado bruto
            desconhecidos.append({"tipo": tipo, "ts": ts, "dados": corpo})
        elif tipo == 1:  # batimentos: ts em ms, deltas de 10 ms
            if abs(ultimo_batimento_ms - ts) > 30_000:
                ultimo_batimento_ms = ts
                batimentos.append(ultimo_batimento_ms)
            for delta in corpo:
                ultimo_batimento_ms += 10 * delta
                batimentos.append(ultimo_batimento_ms)
        elif tipo == 16:
            b0 = corpo[0]
            sono_min, acordado, leve, rem, profundo = struct.unpack_from(">5H", corpo, 1)
            resumos.append({"indice_sono": b0 >> 4, "despertares": b0 & 0xF, "total_min": sono_min,
                            "acordado_min": acordado, "leve_min": leve, "rem_min": rem,
                            "profundo_min": profundo, "tem_rem": bool(corpo[11] & 0x10)})
        elif tipo == 17:  # estágios: ts em segundos
            t = ts
            for i in range(0, tam - 1, 2):
                (val,) = struct.unpack_from(">H", corpo, i)
                estagio = val >> 12
                estagios.append({"inicio": t, "estagio": ESTAGIOS.get(estagio, f"desconhecido_{estagio}"),
                                 "duracao_min": val & 0xFFF})
                t += (val & 0xFFF) * 60
        elif tipo == 0xA:  # respiração: ts em ns, fim de uma janela de 10 min
            n = tam // 4
            fim_ms = round(ts / 1_000_000)
            for i in range(n):
                taxa = corpo[4 * i + 1]
                if 1 <= taxa <= 40:
                    respiracao.append({"timestamp_ms": fim_ms - 600_000 + (i + 1) * 600_000 // (n + 1),
                                       "rpm": taxa})

    r.update(resumos[-1] if resumos else {})
    r["estagios"] = estagios
    r["batimentos_ms"] = batimentos
    r["respiracao"] = respiracao
    r["pacotes_desconhecidos"] = desconhecidos
    return r
