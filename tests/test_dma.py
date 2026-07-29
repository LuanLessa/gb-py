"""
Testes da cópia automática de sprites: duração, cópia byte a byte e bloqueio.

O caso mais importante é o do BLOQUEIO. Durante a cópia, a CPU perde o acesso à
memória externa e tudo que ela lê vira 0xFF — ROM inclusive, o que significa que
ela nem consegue buscar instruções. Um emulador que esqueça esse detalhe roda
todos os jogos normalmente, porque eles se protegem executando da HRAM; o que
quebra é a ROM de teste, que o verifica de propósito.

O outro caso é a cópia acontecer de UM byte por M-cycle, e não toda de uma vez.
A diferença é observável: um jogo pode ler a tabela de sprites no meio da cópia e
encontrá-la pela metade.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Suite, maquina_de_teste     # noqa: E402

s = Suite("OAM DMA")


def maquina_com_fonte():
    m = maquina_de_teste()
    m.bus_write(0xFF40, 0x11)        # LCD desligado: a OAM fica sempre acessível
    for i in range(0xA0):
        m.wram[i] = (i * 3) & 0xFF   # C000 + i
    return m


def teste_copia_completa():
    """Os 160 bytes chegam inteiros à tabela de sprites."""
    m = maquina_com_fonte()
    m.bus_write(0xFF46, 0xC0)        # origem = 0xC000
    m.tick(4 * 162)                  # atraso + 160 M-cycles
    ok = all(m.ppu.oam[i] == ((i * 3) & 0xFF) for i in range(0xA0))
    s.checar(ok, "o DMA copia os 160 bytes corretamente")


def teste_duracao_160_m_cycles():
    """
    Um byte por M-cycle, e não tudo de uma vez.

    A diferença é observável: a CPU continua rodando durante a cópia, e um jogo pode
    ler a tabela no meio dela — encontrando os primeiros sprites já novos e os
    últimos ainda velhos.
    """
    m = maquina_com_fonte()
    m.bus_write(0xFF46, 0xC0)
    m.tick(4 * 2)                    # consome o atraso
    s.checar(m.dma.ativo, "o DMA fica ativo após o atraso inicial")

    m.tick(4 * 159)
    s.checar(m.dma.ativo, "ainda ativo faltando 1 byte")
    m.tick(4)
    s.checar(not m.dma.ativo, "termina exatamente em 160 M-cycles")


def teste_bloqueia_barramento():
    """
    Durante a cópia, a CPU lê 0xFF de tudo que seja memória externa.

    Inclusive da ROM, o que significa que ela nem consegue buscar instruções. É por
    isso que todo jogo copia uma rotina de espera para a HRAM antes de disparar o
    DMA.
    """
    m = maquina_com_fonte()
    m.wram[0x1000] = 0x5A            # 0xD000
    m.bus_write(0xFF46, 0xC0)
    m.tick(4 * 3)                    # DMA em andamento

    s.igual(m.bus_read(0xD000), 0xFF,
            "durante o DMA a CPU lê 0xFF no barramento externo")

    m.hram[0] = 0x33
    s.igual(m.bus_read(0xFF80), 0x33,
            "a HRAM continua acessível durante o DMA")

    s.igual(m.bus_read(0xFF46), 0xC0,
            "os registradores de I/O continuam acessíveis durante o DMA")

    m.bus_write(0xD000, 0x99)
    s.igual(m.wram[0x1000], 0x5A,
            "escritas no barramento externo são descartadas durante o DMA")


def teste_reinicio_do_dma():
    """Disparar uma cópia nova no meio de outra recomeça do zero."""
    m = maquina_com_fonte()
    m.bus_write(0xFF46, 0xC0)
    m.tick(4 * 50)
    m.bus_write(0xFF46, 0xC0)        # reinicia no meio
    s.igual(m.dma.indice, 0, "escrever em FF46 de novo reinicia a transferência")


def teste_ff46_e_legivel():
    """O registrador devolve o último valor escrito."""
    m = maquina_com_fonte()
    m.bus_write(0xFF46, 0xC0)
    s.igual(m.bus_read(0xFF46), 0xC0, "FF46 devolve o último valor escrito")


def teste_dma_ignora_bloqueio_da_ppu():
    """O DMA tem prioridade no barramento: lê a VRAM mesmo no modo 3."""
    m = maquina_de_teste()
    m.bus_write(0xFF40, 0x91)
    for i in range(0xA0):
        m.ppu.vram[i] = (0x80 + i) & 0xFF
    m.ppu._mudar_modo(3)
    m.bus_write(0xFF46, 0x80)        # origem = 0x8000 (VRAM)
    m.tick(4 * 162)
    s.igual(m.ppu.oam[10], (0x80 + 10) & 0xFF,
            "o DMA lê a VRAM mesmo com ela travada para a CPU")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("teste_"):
            fn()
    sys.exit(0 if s.relatorio() else 1)
