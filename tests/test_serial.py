"""
Testes da porta serial e do joypad.

Na serial, o que se verifica é a duração: 8 bits a 8192 Hz, um a cada 512
T-cycles, com a interrupção saindo no fim. E que sem cabo conectado a
transferência acontece assim mesmo, devolvendo 0xFF — é disso que dependem todas
as ROMs de teste para relatar o resultado.

No joypad, a lógica invertida e a matriz de seleção: bit 0 significa
pressionado, e ler os oito botões exige duas leituras com linhas diferentes.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Suite, maquina_de_teste     # noqa: E402

s = Suite("Serial e Joypad")


# ======================================================================
# Serial
# ======================================================================
def teste_um_byte():
    """Um byte sai pela porta e a interrupção avisa no fim."""
    m = maquina_de_teste()
    m.bus_write(0xFF01, 0x48)                  # 'H'
    m.bus_write(0xFF02, 0x81)                  # inicia com clock interno
    s.igual(bytes(m.serial.saida), b"H", "um byte é transmitido")


def teste_palavra_inteira():
    """Vários bytes seguidos chegam na ordem em que foram enviados."""
    m = maquina_de_teste()
    for ch in b"Passed":
        m.bus_write(0xFF01, ch)
        m.bus_write(0xFF02, 0x81)
    s.igual(bytes(m.serial.saida), b"Passed", "a sequência de bytes é preservada")


def teste_sem_bit7_nao_transmite():
    """Sem o bit de início, escrever no SB não dispara nada."""
    m = maquina_de_teste()
    m.bus_write(0xFF01, 0x48)
    m.bus_write(0xFF02, 0x01)                  # bit 7 desligado
    s.igual(bytes(m.serial.saida), b"", "sem o bit 7 nada é transmitido")


def teste_clock_externo_nao_transmite():
    """
    Com o relógio do outro console e nenhum cabo, a transferência nunca anda.

    Também é o comportamento real: o console fica esperando um pulso que não vem.
    """
    m = maquina_de_teste()
    m.bus_write(0xFF01, 0x48)
    m.bus_write(0xFF02, 0x80)                  # bit 0 = 0 → clock externo
    s.igual(bytes(m.serial.saida), b"",
            "com clock externo e sem cabo, nada acontece")


def teste_duracao_de_4096_t_cycles():
    """Oito bits a 512 T-cycles cada. A duração é o que as ROMs de teste dependem."""
    m = maquina_de_teste()
    m.if_ = 0
    m.bus_write(0xFF01, 0x48)
    m.bus_write(0xFF02, 0x81)

    m.tick(4096 - 4)
    s.checar(bool(m.bus_read(0xFF02) & 0x80), "o bit 7 continua ligado durante a transferência")
    s.checar(not (m.if_ & 0x08), "a interrupção ainda não saiu")

    m.tick(4)
    s.checar(not (m.bus_read(0xFF02) & 0x80), "o bit 7 é limpo ao terminar")
    s.checar(bool(m.if_ & 0x08), "a interrupção de serial é pedida no fim")


def teste_sb_recebe_uns():
    """Sem um segundo console, a linha de dados está solta e entra 0xFF."""
    m = maquina_de_teste()
    m.bus_write(0xFF01, 0x00)
    m.bus_write(0xFF02, 0x81)
    m.tick(4096)
    s.igual(m.bus_read(0xFF01), 0xFF,
            "sem cabo conectado o SB acaba cheio de 1s")


def teste_sc_bits_inexistentes():
    """Os bits 1 a 6 do SC não existem e leem 1."""
    m = maquina_de_teste()
    m.bus_write(0xFF02, 0x00)
    s.igual(m.bus_read(0xFF02) & 0x7E, 0x7E, "os bits 1-6 do SC leem sempre 1")


# ======================================================================
# Joypad
# ======================================================================
def teste_nenhum_botao_apertado():
    """Sem nada pressionado, os quatro fios de retorno leem 1 — a lógica é invertida."""
    m = maquina_de_teste()
    m.bus_write(0xFF00, 0x10)                  # seleciona os direcionais
    s.igual(m.bus_read(0xFF00) & 0x0F, 0x0F,
            "sem botões apertados todos os bits leem 1")


def teste_direcionais():
    """Com a linha dos direcionais selecionada, as setas derrubam seus bits."""
    m = maquina_de_teste()
    m.bus_write(0xFF00, 0x20)                  # bit 4 em 0 → direcionais
    for i, nome in enumerate(("direita", "esquerda", "cima", "baixo")):
        m.joypad.botoes = dict.fromkeys(m.joypad.botoes, False)
        m.joypad.pressionar(nome)
        s.igual(m.bus_read(0xFF00) & 0x0F, 0x0F & ~(1 << i),
                f"'{nome}' zera o bit {i} (lógica invertida)")


def teste_botoes_de_acao():
    """E com a outra linha, os botões A, B, Start e Select."""
    m = maquina_de_teste()
    m.bus_write(0xFF00, 0x10)                  # bit 5 em 0 → ações
    for i, nome in enumerate(("a", "b", "select", "start")):
        m.joypad.botoes = dict.fromkeys(m.joypad.botoes, False)
        m.joypad.pressionar(nome)
        s.igual(m.bus_read(0xFF00) & 0x0F, 0x0F & ~(1 << i),
                f"'{nome}' zera o bit {i}")


def teste_grupo_nao_selecionado_nao_aparece():
    """
    Um botão da linha não selecionada não aparece na leitura.

    É o que obriga a rotina de leitura de qualquer jogo a fazer duas leituras, uma
    por linha.
    """
    m = maquina_de_teste()
    m.bus_write(0xFF00, 0x20)                  # só direcionais
    m.joypad.pressionar("start")
    s.igual(m.bus_read(0xFF00) & 0x0F, 0x0F,
            "botões do grupo não selecionado não aparecem")


def teste_bits_altos():
    """Os bits 6 e 7 não existem e leem 1."""
    m = maquina_de_teste()
    m.bus_write(0xFF00, 0x00)
    s.igual(m.bus_read(0xFF00) & 0xC0, 0xC0, "os bits 6 e 7 de FF00 leem sempre 1")


def teste_interrupcao_de_joypad():
    """
    A interrupção sai na descida do fio, e não enquanto a tecla está pressionada.

    É o mesmo detector de borda do timer e do STAT. Uma tecla mantida gera uma
    interrupção só.
    """
    m = maquina_de_teste()
    m.bus_write(0xFF00, 0x10)
    m.if_ = 0
    m.joypad.pressionar("start")
    s.checar(bool(m.if_ & 0x10), "apertar um botão pede a interrupção de joypad")

    m.if_ = 0
    m.joypad.soltar("start")
    s.checar(not (m.if_ & 0x10), "soltar um botão NÃO gera interrupção")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("teste_"):
            fn()
    sys.exit(0 if s.relatorio() else 1)
