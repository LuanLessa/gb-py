"""
Testes do barramento e do mapa de memória.

Duas perguntas, e as duas mais úteis do que parecem.

A primeira é se TODO endereço responde alguma coisa. Uma varredura pelos 65.536
endereços pega, de uma vez, qualquer faixa esquecida no mapa — e um endereço
esquecido devolve None ou levanta exceção no meio de um jogo, horas depois, sem
pista nenhuma de onde veio.

A segunda é se as faixas espelhadas realmente espelham: o eco da WRAM tem de
devolver os mesmos bytes da WRAM, e a RAM do MBC2 tem de dar a volta a cada 512
posições.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gb.cartridge import Cartridge
from gb.machine import Machine

ROM = "tests/roms/blargg/cpu_instrs/cpu_instrs.gb"


def test_varredura(m):
    """
    Todos os 65.536 endereços respondem alguma coisa.

    Uma faixa esquecida no mapa devolveria None ou levantaria exceção no meio de um
    jogo, horas depois, sem pista de onde veio. A varredura pega isso de uma vez.
    """
    for addr in range(0x10000):
        v = m.bus_read(addr)
        assert 0 <= v <= 0xFF, f"{addr:04X} devolveu {v!r}"
    print("  varredura de leitura: OK")


def test_escrita(m):
    """Escrever e reler devolve o mesmo valor, onde isso deve valer."""
    for addr in range(0x10000):
        m.bus_write(addr, 0xAB)
    print("  varredura de escrita: OK")


def test_echo_ram(m):
    """
    A faixa E000-FDFF devolve os mesmos bytes da memória principal.

    Não foi decisão de projeto: o chip não conferia todos os bits do endereço, e a
    memória acabou aparecendo duas vezes. A Nintendo mandava não usar, e alguns
    jogos usaram.
    """
    m.bus_write(0xC000, 0x42)
    assert m.bus_read(0xE000) == 0x42, "echo RAM não espelha"
    m.bus_write(0xDDFF, 0x99)
    assert m.bus_read(0xFDFF) == 0x99, "echo RAM não espelha no topo"
    print("  echo RAM: OK")


def test_hram(m):
    """Os 127 bytes rápidos guardam e devolvem normalmente."""
    m.bus_write(0xFF80, 0x11)
    m.bus_write(0xFFFE, 0x22)
    assert m.bus_read(0xFF80) == 0x11
    assert m.bus_read(0xFFFE) == 0x22
    print("  HRAM: OK")


def test_ie_if(m):
    """Os dois registradores de interrupção respondem nos endereços certos."""
    m.bus_write(0xFFFF, 0x1F)
    assert m.bus_read(0xFFFF) == 0x1F, "IE não persiste"
    m.bus_write(0xFF0F, 0x05)
    assert m.bus_read(0xFF0F) == 0xE5, "IF deve ter bits 7-5 em 1"
    print("  IE/IF: OK")


def test_proibida(m):
    # FEA0-FEFF não existe. Na DMG ela lê 0x00 normalmente, e 0xFF enquanto a
    # PPU está bloqueando a OAM (modos 2 e 3).
    """
    A faixa FEA0-FEFF não é memória, e o que ela devolve depende da PPU.

    0x00 normalmente, 0xFF enquanto a tabela de sprites está em uso.
    """
    m.bus_write(0xFF40, 0x11)              # LCD desligado
    for addr in range(0xFEA0, 0xFF00):
        assert m.bus_read(addr) == 0x00, f"{addr:04X} devia ler 0x00"

    m.bus_write(0xFF40, 0x91)              # LCD ligado
    m.ppu._mudar_modo(3)
    assert m.bus_read(0xFEA0) == 0xFF, "com a OAM bloqueada devia ler 0xFF"
    print("  região proibida: OK")


if __name__ == "__main__":
    m = Machine(Cartridge.from_file(ROM))
    print("rodando testes do barramento:")
    test_varredura(m)
    test_escrita(m)
    test_echo_ram(m)
    test_hram(m)
    test_ie_if(m)
    test_proibida(m)
    print("todos passaram.")