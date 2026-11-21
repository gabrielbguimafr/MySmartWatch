"""Identificadores e montagem dos arquivos de atividade (canal 0053).

Portado de XiaomiActivityFileId.java e XiaomiActivityFileFetcher.java (Gadgetbridge).

ID de arquivo (7 bytes, little-endian):
  [timestamp u32 (s)][fuso u8 (blocos de 15 min)][versão u8][flags u8]
  flags = tipo<<7 | subtipo<<2 | detalhe

Cada pedaço recebido no canal 0053 (já decifrado) é [total u16][número u16][dados].
O arquivo montado = [ID 7 bytes][0x00][conteúdo...][CRC32 u32].
"""

import struct
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIPOS = {0: "ACTIVITY", 1: "SPORTS"}
SUBTIPOS = {
    (0, 0x00): "ACTIVITY_DAILY",
    (0, 0x03): "ACTIVITY_SLEEP_STAGES",
    (0, 0x06): "ACTIVITY_MANUAL_SAMPLES",
    (0, 0x08): "ACTIVITY_SLEEP",
    (1, 0x01): "SPORTS_OUTDOOR_RUNNING",
    (1, 0x02): "SPORTS_OUTDOOR_WALKING_V1",
    (1, 0x03): "SPORTS_TREADMILL",
    (1, 0x06): "SPORTS_OUTDOOR_CYCLING_V2",
    (1, 0x07): "SPORTS_INDOOR_CYCLING",
    (1, 0x08): "SPORTS_FREESTYLE",
    (1, 0x09): "SPORTS_POOL_SWIMMING",
    (1, 0x0B): "SPORTS_ELLIPTICAL",
    (1, 0x0D): "SPORTS_ROWING",
    (1, 0x0E): "SPORTS_JUMP_ROPING",
    (1, 0x10): "SPORTS_HIIT",
    (1, 0x16): "SPORTS_OUTDOOR_WALKING_V2",
    (1, 0x17): "SPORTS_OUTDOOR_CYCLING",
}
DETALHES = {0: "DETAILS", 1: "SUMMARY", 2: "GPS_TRACK"}


@dataclass(frozen=True, order=True)
class IdArquivo:
    timestamp: int
    fuso: int  # em blocos de 15 minutos
    tipo: int
    subtipo: int
    detalhe: int
    versao: int

    @classmethod
    def de_bytes(cls, b: bytes) -> "IdArquivo":
        ts, fuso, versao, flags = struct.unpack("<IbBB", b[:7])
        return cls(ts, fuso, (flags >> 7) & 1, (flags & 0x7F) >> 2, flags & 3, versao)

    def para_bytes(self) -> bytes:
        flags = self.tipo << 7 | self.subtipo << 2 | self.detalhe
        return struct.pack("<IbBB", self.timestamp, self.fuso, self.versao, flags)

    @property
    def nome_tipo(self) -> str:
        return TIPOS.get(self.tipo, f"UNKNOWN_{self.tipo:02X}")

    @property
    def nome_subtipo(self) -> str:
        return SUBTIPOS.get((self.tipo, self.subtipo), f"UNKNOWN_{self.subtipo:02X}")

    @property
    def nome_detalhe(self) -> str:
        return DETALHES.get(self.detalhe, f"UNKNOWN_{self.detalhe:02X}")

    @property
    def data_local(self) -> datetime:
        tz = timezone(timedelta(minutes=15 * self.fuso))
        return datetime.fromtimestamp(self.timestamp, tz)

    def caminho(self, raiz: Path) -> Path:
        """Mesmo layout do Gadgetbridge (rawFetchOperations), para facilitar comparações."""
        d = datetime.fromtimestamp(self.timestamp, timezone.utc)
        nome = f"{d:%Y%m%dT%H%M%S}_{self.tipo:02X}_{self.subtipo:02X}_{self.detalhe:02X}_v{self.versao}.bin"
        return raiz / f"{d:%Y}" / self.nome_tipo / self.nome_subtipo / self.nome_detalhe / nome

    def __str__(self) -> str:
        return (f"{self.data_local:%Y-%m-%d %H:%M} {self.nome_subtipo}/{self.nome_detalhe} v{self.versao}")


def ids_de_lista(dados: bytes) -> list[IdArquivo]:
    if len(dados) % 7:
        raise ValueError(f"Lista de IDs com {len(dados)} bytes (não é múltiplo de 7).")
    ids = [IdArquivo.de_bytes(dados[i:i + 7]) for i in range(0, len(dados), 7)]
    return [i for i in ids if not (i.timestamp == 0 and i.versao == 0)]


class Montador:
    """Junta os pedaços do canal 0053 e entrega o arquivo completo com CRC conferido."""

    def __init__(self):
        self.buffer = bytearray()

    def adicionar(self, pedaco: bytes) -> bytes | None:
        total, numero = struct.unpack_from("<HH", pedaco, 0)
        if numero == 1:
            self.buffer = bytearray()
        self.buffer += pedaco[4:]
        if numero != total:
            return None
        dados, self.buffer = bytes(self.buffer), bytearray()
        if len(dados) < 13:
            raise ValueError(f"Arquivo curto demais ({len(dados)} bytes).")
        crc_esperado = struct.unpack_from("<I", dados, len(dados) - 4)[0]
        if zlib.crc32(dados[:-4]) != crc_esperado:
            raise ValueError("CRC32 do arquivo de atividade não confere.")
        return dados
