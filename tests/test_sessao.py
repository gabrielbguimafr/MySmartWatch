"""Simula o lado do relógio no handshake e confere cifra/decifra nos dois sentidos."""

import hashlib
import hmac
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: E402

from smartdata.proto import Command  # noqa: E402
from smartdata.xiaomi.sessao import Sessao, derivar_material  # noqa: E402

CHAVE = "00112233445566778899aabbccddeeff"


def test_handshake_e_cifra():
    pc = Sessao(CHAVE)
    nonce_relogio = os.urandom(16)

    # Lado do relógio: mesma derivação, mas com as direções trocadas.
    m = derivar_material(bytes.fromhex(CHAVE), pc.nonce_pc, nonce_relogio)
    rel_enc, rel_dec = m[0:16], m[16:32]  # o que o PC decifra, o relógio cifra
    rel_nonce_enc, rel_nonce_dec = m[32:36], m[36:40]
    prova_relogio = hmac.new(rel_enc, nonce_relogio + pc.nonce_pc, hashlib.sha256).digest()

    prova_pc = pc.processar_nonce_relogio(nonce_relogio, prova_relogio)
    assert prova_pc == hmac.new(rel_dec, pc.nonce_pc + nonce_relogio, hashlib.sha256).digest()

    # PC -> relógio, índice 7
    texto = b"ola relogio"
    cifrado = pc.cifrar(texto, 7)
    assert len(cifrado) == len(texto) + 4
    nonce = rel_nonce_dec + struct.pack("<II", 0, 7)
    assert AESCCM(rel_dec, tag_length=4).decrypt(nonce, cifrado, None) == texto

    # relógio -> PC
    resposta = AESCCM(rel_enc, tag_length=4).encrypt(rel_nonce_enc + bytes(8), b"ola pc", None)
    assert pc.decifrar(resposta) == b"ola pc"


def test_chave_errada_e_recusada():
    pc = Sessao(CHAVE)
    try:
        pc.processar_nonce_relogio(os.urandom(16), os.urandom(32))
    except PermissionError:
        return
    raise AssertionError("HMAC inválido deveria ser recusado")


def test_protobuf_auth():
    cmd = Command(type=1, subtype=26)
    cmd.auth.appVerify.nonce = b"\x01" * 16
    volta = Command()
    volta.ParseFromString(cmd.SerializeToString())
    assert volta.auth.appVerify.nonce == b"\x01" * 16


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            print(f"ok {nome}")
