"""
Testes dos controladores de banco de memória.

A montagem é o truque que torna estes testes legíveis: cada MBC recebe uma ROM
sintética em que o primeiro byte de cada banco é o PRÓPRIO NÚMERO do banco.
Assim, conferir qual banco está visível na janela 4000-7FFF é uma única leitura,
e a asserção se lê sozinha.

Os casos incluem o bug do banco 0 do MBC1 — escrever 0 seleciona o banco 1, o
que torna os bancos 0x20, 0x40 e 0x60 inalcançáveis. Um emulador que "consertar"
esse bug quebra os jogos que contam com ele.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Suite                       # noqa: E402
from gb.cartridge import Cartridge              # noqa: E402
from gb.machine import Machine                  # noqa: E402

s = Suite("MBCs")


def rom_marcada(tipo, bancos, cod_ram=0x03):
    """ROM em que o byte 0 de cada banco guarda o número do banco (mod 256)."""
    rom = bytearray(0x4000 * bancos)
    for b in range(bancos):
        rom[b * 0x4000] = b & 0xFF
        rom[b * 0x4000 + 1] = (b >> 8) & 0xFF
    rom[0x147] = tipo
    rom[0x148] = max(0, (bancos.bit_length() - 2))
    rom[0x149] = cod_ram
    return rom


def maquina(tipo, bancos, cod_ram=0x03):
    m = Machine(Cartridge(bytes(rom_marcada(tipo, bancos, cod_ram))))
    m.reset()
    m.bus_write(0xFF40, 0x11)        # LCD desligado, sem travas
    return m


def banco_atual(m):
    return m.bus_read(0x4000) | (m.bus_read(0x4001) << 8)


# ======================================================================
# Sem MBC
# ======================================================================
def teste_rom_only():
    """Sem MBC, a ROM inteira fica visível e nada troca."""
    m = maquina(0x00, 2, cod_ram=0x00)
    s.igual(m.bus_read(0x0000), 0, "banco 0 fixo em 0000-3FFF")
    s.igual(banco_atual(m), 1, "banco 1 fixo em 4000-7FFF")
    m.bus_write(0x2000, 0x05)
    s.igual(banco_atual(m), 1, "escrever na ROM não muda nada sem MBC")


# ======================================================================
# MBC1
# ======================================================================
def teste_mbc1_troca_de_banco():
    """Escrever em 2000-3FFF troca a fatia visível na janela alta."""
    m = maquina(0x01, 16)
    for b in (2, 5, 9, 15):
        m.bus_write(0x2000, b)
        s.igual(banco_atual(m), b, f"MBC1 seleciona o banco {b}")


def teste_mbc1_banco_zero_vira_um():
    """
    O bug mais famoso da família: escrever 0 seleciona o banco 1.

    Não é defeito deste emulador — é do chip, e a intenção era evitar que o jogo
    pusesse o mesmo banco nas duas janelas. Corrigir quebraria os jogos que contam
    com o comportamento.
    """
    m = maquina(0x01, 16)
    m.bus_write(0x2000, 0x00)
    s.igual(banco_atual(m), 1,
            "MBC1: escrever 0 no seletor seleciona o banco 1 (bug clássico)")


def teste_mbc1_bancos_altos():
    """Os 2 bits extras estendem o alcance para além do banco 31."""
    m = maquina(0x01, 128)           # 2 MB
    m.bus_write(0x6000, 0x00)        # modo simples
    m.bus_write(0x2000, 0x01)
    m.bus_write(0x4000, 0x02)        # bits 5-6 do banco
    s.igual(banco_atual(m), 0x41,
            "MBC1: o registrador 4000-5FFF fornece os bits altos do banco")


def teste_mbc1_bancos_inalcancaveis():
    """
    A consequência do bug: 0x20, 0x40 e 0x60 não podem ser selecionados.

    Chegar ao 0x20 exigiria escrever 0 nos cinco bits baixos, e isso vira 1,
    resultando em 0x21. Cartuchos grandes desperdiçam esses três bancos ou repetem
    neles o conteúdo de outros.
    """
    m = maquina(0x01, 128)
    m.bus_write(0x4000, 0x01)
    m.bus_write(0x2000, 0x00)        # vira 1 → banco 0x21, não 0x20
    s.igual(banco_atual(m), 0x21,
            "MBC1: os bancos 0x20/0x40/0x60 são inalcançáveis")


def teste_mbc1_modo_avancado():
    """
    No modo avançado, até a janela "fixa" troca de banco.

    É como um cartucho de 1 MB alcança a segunda metade da ROM.
    """
    m = maquina(0x01, 128)
    m.bus_write(0x4000, 0x01)
    m.bus_write(0x6000, 0x01)        # modo avançado
    s.igual(m.bus_read(0x0000), 0x20,
            "MBC1 no modo avançado troca até a janela fixa 0000-3FFF")


def teste_mbc1_ram():
    """A RAM só responde depois de ser ligada com o valor 0x0A."""
    m = maquina(0x01, 4)
    m.bus_write(0xA000, 0x42)
    s.igual(m.bus_read(0xA000), 0xFF, "a RAM lê 0xFF enquanto está desabilitada")

    m.bus_write(0x0000, 0x0A)        # habilita
    m.bus_write(0xA000, 0x42)
    s.igual(m.bus_read(0xA000), 0x42, "com 0x0A em 0000-1FFF a RAM funciona")

    m.bus_write(0x0000, 0x00)        # desabilita
    s.igual(m.bus_read(0xA000), 0xFF, "desabilitar a RAM volta a ler 0xFF")


def teste_mbc1_banco_de_ram():
    """No modo avançado, os 2 bits extras passam a escolher o banco de RAM."""
    m = maquina(0x01, 4)
    m.bus_write(0x0000, 0x0A)
    m.bus_write(0x6000, 0x01)        # modo avançado habilita bancos de RAM
    m.bus_write(0x4000, 0x00)
    m.bus_write(0xA000, 0x11)
    m.bus_write(0x4000, 0x01)
    m.bus_write(0xA000, 0x22)
    m.bus_write(0x4000, 0x00)
    s.igual(m.bus_read(0xA000), 0x11, "MBC1: os bancos de RAM são independentes")


# ======================================================================
# MBC2
# ======================================================================
def teste_mbc2_ram_de_4_bits():
    """
    A RAM do MBC2 guarda meio byte por posição; os 4 bits altos leem 1.

    Um emulador que devolvesse o byte cheio faria o jogo ler valores que o cartucho
    nunca produziria.
    """
    m = maquina(0x05, 8, cod_ram=0x00)
    m.bus_write(0x0000, 0x0A)
    m.bus_write(0xA000, 0xAB)
    s.igual(m.bus_read(0xA000), 0xFB,
            "MBC2: só os 4 bits baixos existem; os altos leem 1")


def teste_mbc2_ram_espelhada():
    """
    As 512 posições dão a volta por toda a faixa A000-BFFF.

    Não há fiação para distinguir endereços além do bit 9, então a mesma memória
    aparece repetida — como o eco da WRAM, e pelo mesmo motivo.
    """
    m = maquina(0x05, 8, cod_ram=0x00)
    m.bus_write(0x0000, 0x0A)
    m.bus_write(0xA000, 0x07)
    s.igual(m.bus_read(0xA200), 0xF7,
            "MBC2: a RAM de 512 nibbles se repete por toda a janela")


def teste_mbc2_seletor_pelo_bit_8():
    """
    O MBC2 não usa faixas de endereço: usa o bit 8 para escolher o comando.

    Com ele em 0 a escrita liga a RAM; com ele em 1, troca o banco.
    """
    m = maquina(0x05, 8, cod_ram=0x00)
    m.bus_write(0x0100, 0x03)        # bit 8 ligado → seleciona o banco
    s.igual(banco_atual(m), 3, "MBC2: com o bit 8 do endereço em 1, troca o banco")
    m.bus_write(0x0000, 0x00)        # bit 8 desligado → mexe na RAM
    s.igual(banco_atual(m), 3, "MBC2: com o bit 8 em 0, o banco não muda")


# ======================================================================
# MBC3
# ======================================================================
def teste_mbc3_troca_de_banco():
    """Sete bits de banco, até 128 fatias de ROM."""
    m = maquina(0x13, 128)
    for b in (1, 0x40, 0x7F):
        m.bus_write(0x2000, b)
        s.igual(banco_atual(m), b, f"MBC3 seleciona o banco 0x{b:02X}")


def teste_mbc3_rtc():
    """Os bancos de RAM 0x08 a 0x0C expõem os registradores do relógio."""
    m = maquina(0x10, 8)
    m.bus_write(0x0000, 0x0A)
    m.bus_write(0x4000, 0x08)        # banco 08 = registrador de segundos
    m.bus_write(0xA000, 30)
    m.bus_write(0x6000, 0x00)
    m.bus_write(0x6000, 0x01)        # latch
    s.igual(m.bus_read(0xA000), 30, "MBC3: o RTC expõe os segundos no banco 0x08")


def teste_mbc3_rtc_anda():
    """O relógio conta um segundo a cada 4.194.304 T-cycles."""
    m = maquina(0x10, 8)
    m.bus_write(0x0000, 0x0A)
    m.bus_write(0x4000, 0x08)
    m.bus_write(0xA000, 0)
    m.cart.mbc.tick_rtc(4194304 * 3)     # 3 segundos
    m.bus_write(0x6000, 0x00)
    m.bus_write(0x6000, 0x01)
    s.igual(m.bus_read(0xA000), 3, "MBC3: o relógio avança 1 por segundo emulado")


def teste_mbc3_latch_congela():
    """
    Escrever 0 e depois 1 tira uma fotografia do relógio.

    Sem isso, ler os cinco registradores em sequência poderia pegar o minuto virando
    no meio — e o jogo enxergaria um horário que nunca existiu.
    """
    m = maquina(0x10, 8)
    m.bus_write(0x0000, 0x0A)
    m.bus_write(0x4000, 0x08)
    m.bus_write(0xA000, 0)
    m.bus_write(0x6000, 0x00)
    m.bus_write(0x6000, 0x01)            # congela em 0
    m.cart.mbc.tick_rtc(4194304 * 5)
    s.igual(m.bus_read(0xA000), 0,
            "MBC3: sem um novo latch a leitura fica congelada")


# ======================================================================
# MBC5
# ======================================================================
def teste_mbc5_banco_zero_e_valido():
    """No MBC5 o banco 0 é selecionável de verdade: o bug antigo não existe mais."""
    m = maquina(0x19, 16)
    m.bus_write(0x2000, 0x00)
    s.igual(banco_atual(m), 0,
            "MBC5: diferente do MBC1, o banco 0 é selecionável de verdade")


def teste_mbc5_nono_bit():
    """O seletor vem partido em dois endereços, e é isso que permite passar de 2 MB."""
    m = maquina(0x19, 512)           # 8 MB
    m.bus_write(0x2000, 0x00)
    m.bus_write(0x3000, 0x01)        # bit 8
    s.igual(banco_atual(m), 0x100, "MBC5: o registrador 3000-3FFF dá o bit 8")


def teste_mbc5_bancos_de_ram():
    """Até 16 bancos de RAM, ou 8 quando há motor de vibração."""
    m = maquina(0x1B, 8, cod_ram=0x04)   # 128 KB de RAM
    m.bus_write(0x0000, 0x0A)
    for b in range(4):
        m.bus_write(0x4000, b)
        m.bus_write(0xA000, 0x10 + b)
    for b in range(4):
        m.bus_write(0x4000, b)
        s.igual(m.bus_read(0xA000), 0x10 + b, f"MBC5: banco de RAM {b} isolado")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("teste_"):
            fn()
    sys.exit(0 if s.relatorio() else 1)
