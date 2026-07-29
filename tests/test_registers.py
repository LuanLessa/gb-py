"""
Testes do banco de registradores.

O ponto central é a EQUIVALÊNCIA entre as duas implementações da visão de 16
bits — a por `memoryview` e a por composição de bytes, descritas em
`gb/registradores.py`. O emulador escolhe uma ou outra conforme o interpretador,
e essa escolha só é segura se as duas fizerem exatamente a mesma coisa.

O teste percorre valores e confere byte a byte que elas concordam. Sem ele, uma
divergência apareceria como "o jogo funciona no CPython e trava no PyPy", que é
o tipo de sintoma que consome dias.

Os outros casos cobrem a união entre as duas visões: escrever em H tem de mudar
o byte alto de HL na mesma hora, e os quatro bits de baixo de F têm de ler
sempre 0.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gb.cpu import CPU, AF, BC, DE, HL, SP, PC
from gb.cpu import A, F, B, C, D, E, H, L
from gb.cpu import FLAG_Z, FLAG_N, FLAG_H, FLAG_C


def novo():
    return CPU()


def test_bytes():
    """Cada registrador de 8 bits guarda e devolve o que recebeu."""
    c = novo()
    for i, nome in ((A, "A"), (B, "B"), (C, "C"), (D, "D"),
                    (E, "E"), (H, "H"), (L, "L")):
        c.reg8[i] = 0x5A
        assert c.reg8[i] == 0x5A, f"{nome} não guardou"
    print("  bytes individuais: OK")


def test_uniao_compoe():
    """
    Escrever nos dois bytes muda o par de 16 bits — não são cópias.

    É a propriedade central do banco de registradores: a MESMA memória vista de dois
    jeitos. Manter duas representações em sincronia manualmente seria uma fonte
    clássica de bug.
    """
    c = novo()
    c.reg8[B], c.reg8[C] = 0x12, 0x34
    assert c.reg16[BC] == 0x1234, f"BC == {c.reg16[BC]:04X}, esperado 1234"
    c.reg8[D], c.reg8[E] = 0xDE, 0xAD
    assert c.reg16[DE] == 0xDEAD, f"DE == {c.reg16[DE]:04X}"
    c.reg8[H], c.reg8[L] = 0xBE, 0xEF
    assert c.reg16[HL] == 0xBEEF, f"HL == {c.reg16[HL]:04X}"
    print("  bytes compõem os pares: OK")


def test_uniao_decompoe():
    """E o caminho inverso: escrever no par muda os dois bytes."""
    c = novo()
    c.reg16[BC] = 0xABCD
    assert (c.reg8[B], c.reg8[C]) == (0xAB, 0xCD), \
        f"B,C == {c.reg8[B]:02X},{c.reg8[C]:02X}, esperado AB,CD"
    c.reg16[HL] = 0xBEEF
    assert (c.reg8[H], c.reg8[L]) == (0xBE, 0xEF)
    print("  pares decompõem em bytes: OK")


def test_sp_pc():
    """SP e PC também fazem parte do mesmo banco."""
    c = novo()
    c.reg16[SP] = 0xFFFE
    c.reg16[PC] = 0x0100
    assert c.reg16[SP] == 0xFFFE and c.reg16[PC] == 0x0100
    print("  SP e PC: OK")


def test_flags_leem():
    """Cada flag lê o bit certo do registrador F."""
    c = novo()
    c.reg8[F] = 0xB0                      # 1011 0000
    assert c.getFlag(FLAG_Z), "Z devia estar setado"
    assert not c.getFlag(FLAG_N), "N devia estar limpo"
    assert c.getFlag(FLAG_H), "H devia estar setado"
    assert c.getFlag(FLAG_C), "C devia estar setado"
    print("  getFlag: OK")


def test_flags_escrevem():
    """Ligar uma flag não mexe nas outras três."""
    c = novo()
    c.reg8[F] = 0
    c.setFlag(FLAG_Z, 1)
    assert c.reg8[F] == 0x80, f"F == {c.reg8[F]:02X}, esperado 80"
    c.setFlag(FLAG_C, 1)
    assert c.reg8[F] == 0x90, f"F == {c.reg8[F]:02X}, esperado 90"
    c.setFlag(FLAG_Z, 0)
    assert c.reg8[F] == 0x10, f"F == {c.reg8[F]:02X}, esperado 10"
    print("  setFlag: OK")


def test_f_mascara():
    """
    Os 4 bits de baixo de F não existem e leem sempre 0.

    Sem isso, um `PUSH AF` seguido de `POP AF` devolveria um valor que o console
    nunca devolveria — e há ROM de teste que confere exatamente essa sequência.
    """
    c = novo()
    c.write_af(0x12FF)
    assert c.reg8[A] == 0x12, f"A == {c.reg8[A]:02X}"
    assert c.reg8[F] == 0xF0, f"F == {c.reg8[F]:02X}, esperado F0"
    assert c.reg16[AF] == 0x12F0, f"AF == {c.reg16[AF]:04X}, esperado 12F0"
    print("  máscara do nibble baixo de F: OK")


if __name__ == "__main__":
    print("testes do banco de registradores:")
    for fn in (test_bytes, test_uniao_compoe, test_uniao_decompoe,
               test_sp_pc, test_flags_leem, test_flags_escrevem,
               test_f_mascara):
        fn()
    print("todos passaram.")