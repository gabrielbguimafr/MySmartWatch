"""Leitor binário e parser de grupos de bits (XiaomiComplexActivityParser.java).

Formato "complexo": o arquivo tem um header de N bytes, e cada nibble (4 bits) do
header descreve um grupo de campos de cada registro:
  bit 8 (0b1000) -> o grupo existe neste registro (e seus bytes estão presentes)
  bits 4, 2, 1   -> o 1º, 2º e 3º subcampo do grupo são válidos
Os valores de um grupo são lidos como um inteiro de 8/16/32 bits e os subcampos
são fatias de bits desse inteiro, da esquerda para a direita.
"""

import struct


class Leitor:
    """Equivalente a um ByteBuffer little-endian do Java."""

    def __init__(self, dados: bytes, inicio: int = 0, fim: int | None = None):
        self.dados = dados
        self.pos = inicio
        self.fim = len(dados) if fim is None else fim

    def _ler(self, fmt: str) -> int:
        n = struct.calcsize(fmt)
        if self.pos + n > self.fim:
            raise EOFError(f"Fim dos dados lendo {fmt} em {self.pos} (fim {self.fim})")
        (v,) = struct.unpack_from(fmt, self.dados, self.pos)
        self.pos += n
        return v

    def u8(self) -> int: return self._ler("<B")
    def i8(self) -> int: return self._ler("<b")
    def u16(self) -> int: return self._ler("<H")
    def i16(self) -> int: return self._ler("<h")
    def u32(self) -> int: return self._ler("<I")
    def i32(self) -> int: return self._ler("<i")
    def i64(self) -> int: return self._ler("<q")
    def f32(self) -> float: return self._ler("<f")

    def bytes(self, n: int) -> bytes:
        if self.pos + n > self.fim:
            raise EOFError(f"Fim dos dados lendo {n} bytes em {self.pos}")
        b = self.dados[self.pos:self.pos + n]
        self.pos += n
        return b

    def pular(self, n: int) -> None:
        self.bytes(n)

    def restante(self) -> int:
        return self.fim - self.pos


class ParserComplexo:
    def __init__(self, header: bytes, leitor: Leitor):
        self.header = header
        self.leitor = leitor
        self.reset()

    def reset(self) -> None:
        self.grupo = -1
        self.bits_grupo = 0
        self.valor = 0

    def _nibble(self) -> int:
        b = self.header[self.grupo // 2]
        return (b >> 4) & 0xF if self.grupo % 2 == 0 else b & 0xF

    def _consumir(self, n_bits: int) -> int:
        return {8: self.leitor.u8, 16: self.leitor.u16, 32: self.leitor.i32}[n_bits]()

    def proximo_grupo(self, n_bits: int) -> bool:
        """Avança para o próximo grupo; True se ele existe neste registro."""
        self.grupo += 1
        if self.grupo >= len(self.header) * 2:
            self._consumir(n_bits)
            return False
        if not self._nibble() & 8:
            return False
        self.bits_grupo = n_bits
        self.valor = self._consumir(n_bits)
        return True

    def tem(self, idx: int) -> bool:
        return bool(self._nibble() & (1 << (2 - idx)))

    def get(self, idx: int, n_bits: int) -> int:
        desloc = self.bits_grupo - idx - n_bits
        return (self.valor >> desloc) & ((1 << n_bits) - 1)


def bit_valido(header: bytes, i: int) -> bool:
    """validData do XiaomiActivityParser: bitmap MSB-first."""
    return bool(header[i // 8] & (1 << (7 - i % 8)))
