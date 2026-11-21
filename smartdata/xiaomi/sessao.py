"""Criptografia da sessão: derivação de chaves no handshake e AES-CCM.

Portado de XiaomiAuthService.java (Gadgetbridge).

Handshake:
  1. PC envia um nonce aleatório de 16 bytes.
  2. Relógio responde com o nonce dele + um HMAC que prova que conhece a auth key.
  3. Ambos derivam 64 bytes de material de chave a partir de (auth key, nonces):
       [0:16] chave para decifrar o que vem do relógio
       [16:32] chave para cifrar o que o PC envia
       [32:36] / [36:40] prefixos de nonce de cada direção
  4. PC prova que também conhece a chave (HMAC dos nonces) e envia seus dados cifrados.
"""

import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESCCM

TAG_BYTES = 4  # o protocolo usa MAC de 32 bits no AES-CCM


def _hmac(chave: bytes, dados: bytes) -> bytes:
    return hmac.new(chave, dados, hashlib.sha256).digest()


def derivar_material(auth_key: bytes, nonce_pc: bytes, nonce_relogio: bytes) -> bytes:
    """computeAuthStep3Hmac: HMAC de extração seguido de expansão estilo HKDF ('miwear-auth')."""
    chave_prk = _hmac(nonce_pc + nonce_relogio, auth_key)
    saida, bloco, contador = b"", b"", 1
    while len(saida) < 64:
        bloco = _hmac(chave_prk, bloco + b"miwear-auth" + bytes([contador]))
        saida += bloco
        contador += 1
    return saida[:64]


class Sessao:
    def __init__(self, auth_key_hex: str):
        chave = bytes.fromhex(auth_key_hex.removeprefix("0x"))
        if len(chave) != 16:
            raise ValueError("A auth key deve ter 16 bytes (32 caracteres hex).")
        self.auth_key = chave
        self.nonce_pc = os.urandom(16)
        self.pronta = False  # True depois do handshake: a partir daí tudo é cifrado

    def processar_nonce_relogio(self, nonce_relogio: bytes, hmac_relogio: bytes) -> bytes:
        """Deriva as chaves, confere a prova do relógio e devolve a nossa prova (encryptedNonces)."""
        m = derivar_material(self.auth_key, self.nonce_pc, nonce_relogio)
        self.chave_dec, self.chave_enc = m[0:16], m[16:32]
        self.nonce_dec, self.nonce_enc = m[32:36], m[36:40]

        esperado = _hmac(self.chave_dec, nonce_relogio + self.nonce_pc)
        if not hmac.compare_digest(esperado, hmac_relogio):
            raise PermissionError("HMAC do relógio não confere: a auth key está errada ou desatualizada.")
        return _hmac(self.chave_enc, self.nonce_pc + nonce_relogio)

    def cifrar(self, dados: bytes, indice: int) -> bytes:
        nonce = self.nonce_enc + struct.pack("<II", 0, indice)
        return AESCCM(self.chave_enc, tag_length=TAG_BYTES).encrypt(nonce, dados, None)

    def decifrar(self, dados: bytes) -> bytes:
        nonce = self.nonce_dec + struct.pack("<II", 0, 0)
        return AESCCM(self.chave_dec, tag_length=TAG_BYTES).decrypt(nonce, dados, None)
