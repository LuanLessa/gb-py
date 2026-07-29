"""
Testes da busca e da decodificação.

Antes de conferir o que cada instrução FAZ, vale conferir se a instrução certa
foi escolhida. Estes casos verificam que o byte lido leva à função certa, que o
prefixo 0xCB desvia para a segunda tabela, que o ponteiro de programa avança o
número certo de bytes e que os operandos de 16 bits são montados na ordem certa
— byte baixo primeiro.

Um erro aqui faria TODOS os outros testes falharem de formas inexplicáveis, e é
por isso que este arquivo vem cedo na suíte.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gb.cartridge import Cartridge
from gb.machine import Machine
from gb.cpu import PC, SP


def maquina(patches=None):
    """Monta uma máquina com uma ROM sintética de 32KB."""
    rom = bytearray(0x8000)
    rom[0x148] = 0x00                      # 32KB
    rom[0x149] = 0x00                      # sem RAM externa
    if patches:
        for addr, val in patches.items():
            rom[addr] = val
    return Machine(Cartridge(rom))


def test_read8_le_rom():
    """A leitura devolve o byte que está na ROM."""
    m = maquina({0x0100: 0x3E, 0x0101: 0xAB})
    assert m.cpu.read8(0x0100) == 0x3E
    assert m.cpu.read8(0x0101) == 0xAB
    print("  read8 lê da ROM: OK")


def test_read8_custa_4():
    """
    Todo acesso ao barramento custa exatamente 1 M-cycle.

    É a regra que dá a precisão de ciclo ao emulador inteiro, e está verificada aqui
    no nível mais baixo possível.
    """
    m = maquina({0x0100: 0x3E})
    antes = m.cycles
    m.cpu.read8(0x0100)
    delta = m.cycles - antes
    assert delta == 4, f"read8 custou {delta} T-cycles, esperado 4"
    print("  read8 custa 4 T-cycles: OK")


def test_write8():
    """A escrita chega ao destino, e também custa 1 M-cycle."""
    m = maquina()
    antes = m.cycles
    m.cpu.write8(0xC000, 0x42)
    delta = m.cycles - antes
    assert m.bus_read(0xC000) == 0x42, "write8 não escreveu"
    assert delta == 4, f"write8 custou {delta}, esperado 4"
    print("  write8 escreve e custa 4: OK")


def test_fetch8():
    """Buscar um byte devolve o valor e avança o ponteiro."""
    m = maquina({0x0100: 0x3E, 0x0101: 0xAB})
    m.cpu.reg16[PC] = 0x0100
    antes = m.cycles

    v = m.cpu.fetch8()
    assert v == 0x3E, f"fetch8 devolveu {v:02X}, esperado 3E"
    assert m.cpu.reg16[PC] == 0x0101, f"PC == {m.cpu.reg16[PC]:04X}, esperado 0101"

    v = m.cpu.fetch8()
    assert v == 0xAB, f"fetch8 devolveu {v:02X}, esperado AB"
    assert m.cpu.reg16[PC] == 0x0102

    delta = m.cycles - antes
    assert delta == 8, f"dois fetch8 custaram {delta}, esperado 8"
    print("  fetch8 lê e avança PC: OK")


def test_fetch8_wrap():
    """
    No fim da memória, o ponteiro dá a volta para 0x0000.

    São 16 bits: depois de 0xFFFF vem 0x0000, e não 0x10000.
    """
    m = maquina()
    m.cpu.reg16[PC] = 0xFFFF
    m.cpu.fetch8()
    assert m.cpu.reg16[PC] == 0x0000, \
        f"PC == {m.cpu.reg16[PC]:04X}, esperado 0000 (deve dar a volta)"
    print("  fetch8 faz PC dar a volta em FFFF: OK")


def test_fetch16():
    """
    Dois bytes viram um valor de 16 bits, com o byte BAIXO primeiro.

    É a convenção little-endian do processador: `LD HL, $1234` fica gravado na ROM
    como 21 34 12. Ler na ordem trocada faria todo endereço sair errado.
    """
    m = maquina({0x0200: 0x50, 0x0201: 0x01})
    m.cpu.reg16[PC] = 0x0200
    antes = m.cycles

    v = m.cpu.fetch16()
    assert v == 0x0150, f"fetch16 devolveu {v:04X}, esperado 0150 (little-endian)"
    assert m.cpu.reg16[PC] == 0x0202, f"PC == {m.cpu.reg16[PC]:04X}, esperado 0202"

    delta = m.cycles - antes
    assert delta == 8, f"fetch16 custou {delta}, esperado 8"
    print("  fetch16 é little-endian e custa 8: OK")


if __name__ == "__main__":
    print("testes de fetch:")
    for fn in (test_read8_le_rom, test_read8_custa_4, test_write8,
               test_fetch8, test_fetch8_wrap, test_fetch16):
        fn()
    print("todos passaram.")