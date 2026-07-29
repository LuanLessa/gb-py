"""
Testes das interrupções: prioridade, duração do despacho, EI, HALT e o bug.

O teste de duração aqui é o mesmo que a ROM `interrupt_time.gb` faz. Ela não roda
neste emulador por exigir um Game Boy Color — usa o modo de velocidade dobrada —
então a parte que vale para a DMG foi reescrita como teste unitário: os 5
M-cycles do despacho, medidos aqui.

O bug do HALT tem lugar de destaque. Ele é um defeito de verdade do chip, em que
a instrução seguinte a um HALT é executada duas vezes, e reproduzi-lo é
obrigatório: `halt_bug.gb` reprova quem não o faz.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Suite, maquina_de_teste     # noqa: E402
from gb.constants import PC, SP, A              # noqa: E402

s = Suite("Interrupções")


def maquina_em(pc=0xC000):
    m = maquina_de_teste()
    m.bus_write(0xFF40, 0x11)        # LCD desligado: sem VBlank/STAT atrapalhando
    m.cpu.reg16[PC] = pc
    m.cpu.reg16[SP] = 0xDFF0
    m.if_ = 0
    m.ie = 0
    return m


def escrever(m, addr, *bytes_):
    for i, b in enumerate(bytes_):
        m.bus_write(addr + i, b)


# ----------------------------------------------------------------------
# Despacho
# ----------------------------------------------------------------------
def teste_despacho_leva_5_m_cycles():
    """
    Atender uma interrupção custa exatamente 5 M-cycles.

    É a medição que a ROM `interrupt_time.gb` faria, se ela não exigisse um Game Boy
    Color. Errar esse número desloca todo efeito gráfico programado dentro de uma
    rotina de interrupção.
    """
    m = maquina_em()
    escrever(m, 0xC000, 0x00)        # NOP (nunca chega a executar)
    m.cpu.ime = True
    m.ie = 0x04                      # timer
    m.if_ = 0x04

    antes = m.cycles
    m.cpu.step()
    s.igual(m.cycles - antes, 20,
            "o despacho de interrupção custa 20 T-cycles (5 M-cycles)")
    s.igual(m.cpu.reg16[PC], 0x50, "o PC pula para o vetor do timer (0x50)")
    s.checar(not m.cpu.ime, "o IME é desligado ao entrar no handler")
    s.igual(m.if_ & 0x04, 0, "o bit atendido é limpo no IF")


def teste_prioridade():
    """Bit menor = prioridade maior. VBlank ganha de todo mundo."""
    vetores = {0x01: 0x40, 0x02: 0x48, 0x04: 0x50, 0x08: 0x58, 0x10: 0x60}
    for bit, vetor in vetores.items():
        m = maquina_em()
        m.cpu.ime = True
        m.ie = 0x1F
        m.if_ = bit
        m.cpu.step()
        s.igual(m.cpu.reg16[PC], vetor, f"IF=0x{bit:02X} vai para o vetor 0x{vetor:02X}")

    m = maquina_em()
    m.cpu.ime = True
    m.ie = 0x1F
    m.if_ = 0x1F                     # todas ao mesmo tempo
    m.cpu.step()
    s.igual(m.cpu.reg16[PC], 0x40, "com tudo pendente, o VBlank é atendido primeiro")


def teste_empilha_o_pc():
    """O endereço de retorno vai para a pilha, byte alto primeiro."""
    m = maquina_em(0xC123)
    m.cpu.ime = True
    m.ie = 0x01
    m.if_ = 0x01
    m.cpu.step()
    sp = m.cpu.reg16[SP]
    s.igual(m.bus_read(sp) | (m.bus_read(sp + 1) << 8), 0xC123,
            "o endereço de retorno é empilhado corretamente")


def teste_ime_desligado_nao_atende():
    """Com a chave geral desligada, o pedido fica esperando."""
    m = maquina_em()
    escrever(m, 0xC000, 0x00)
    m.cpu.ime = False
    m.ie = 0x01
    m.if_ = 0x01
    m.cpu.step()
    s.igual(m.cpu.reg16[PC], 0xC001, "com IME=0 a interrupção é ignorada")
    s.igual(m.if_ & 0x01, 0x01, "e o bit continua pendente no IF")


def teste_ie_zerado_nao_atende():
    """Sem o jogo declarar interesse no IE, nada é atendido."""
    m = maquina_em()
    escrever(m, 0xC000, 0x00)
    m.cpu.ime = True
    m.ie = 0x00
    m.if_ = 0x1F
    m.cpu.step()
    s.igual(m.cpu.reg16[PC], 0xC001, "sem habilitação no IE nada é atendido")


# ----------------------------------------------------------------------
# EI / DI / RETI
# ----------------------------------------------------------------------
def teste_ei_tem_atraso_de_uma_instrucao():
    """
    O EI só liga a chave depois que a PRÓXIMA instrução terminar.

    O atraso existe para que o par `EI; RET` execute o retorno antes de qualquer
    interrupção nova entrar. Sem ele, uma interrupção poderia empilhar mais um
    endereço de retorno a cada volta, até a pilha invadir os dados do jogo.
    """
    m = maquina_em()
    escrever(m, 0xC000, 0xFB, 0x00, 0x00)    # EI ; NOP ; NOP
    m.ie = 0x01
    m.if_ = 0x01

    m.cpu.step()                              # EI
    s.checar(not m.cpu.ime, "o EI não liga o IME imediatamente")

    m.cpu.step()                              # NOP — ainda protegido
    s.igual(m.cpu.reg16[PC], 0xC002,
            "a instrução logo após o EI não é interrompida")
    s.checar(m.cpu.ime, "o IME está ligado ao fim dessa instrução")

    m.cpu.step()                              # agora sim
    s.igual(m.cpu.reg16[PC], 0x40, "a interrupção é atendida na instrução seguinte")


def teste_ei_seguido_de_di_nao_interrompe():
    """
    Um DI logo depois de um EI cancela o efeito antes de ele valer.

    Consequência direta do atraso: a chave nunca chega a ligar.
    """
    m = maquina_em()
    escrever(m, 0xC000, 0xFB, 0xF3, 0x00)    # EI ; DI ; NOP
    m.ie = 0x01
    m.if_ = 0x01
    m.cpu.step()                              # EI
    m.cpu.step()                              # DI
    m.cpu.step()                              # NOP
    s.igual(m.cpu.reg16[PC], 0xC003,
            "'EI; DI' cancela o agendamento e nada é interrompido")


def teste_reti_religa_na_hora():
    """
    O RETI liga a chave imediatamente, sem o atraso do EI.

    Faz sentido pela mecânica do atraso: o propósito dele é proteger o retorno, e no
    RETI o retorno acontece dentro da própria instrução.
    """
    m = maquina_em()
    m.cpu.reg16[SP] = 0xDFF0
    m.bus_write(0xDFF0, 0x00)
    m.bus_write(0xDFF1, 0xC5)
    escrever(m, 0xC000, 0xD9)                 # RETI
    m.cpu.ime = False
    m.cpu.step()
    s.checar(m.cpu.ime, "o RETI religa o IME sem atraso")
    s.igual(m.cpu.reg16[PC], 0xC500, "e retorna para o endereço da pilha")


# ----------------------------------------------------------------------
# HALT
# ----------------------------------------------------------------------
def teste_halt_dorme_e_acorda():
    """
    O HALT termina com QUALQUER interrupção pendente, mesmo com o IME desligado.

    Este é o erro clássico. O IME decide apenas se a rotina de tratamento será
    chamada — não se a CPU acorda. Trocar as duas coisas trava jogos que usam HALT
    com as interrupções desligadas de propósito.
    """
    m = maquina_em()
    escrever(m, 0xC000, 0x76, 0x00)           # HALT ; NOP
    m.cpu.ime = False
    m.ie = 0x04
    m.if_ = 0x00

    m.cpu.step()                              # HALT
    s.checar(m.cpu.halted, "o HALT coloca a CPU para dormir")

    antes = m.cycles
    m.cpu.step()
    s.igual(m.cycles - antes, 4, "dormindo, cada passo consome 4 T-cycles")
    s.checar(m.cpu.halted, "e a CPU continua dormindo")

    m.if_ = 0x04                              # chega uma interrupção
    m.cpu.step()
    s.checar(not m.cpu.halted,
             "a CPU acorda mesmo com IME=0 (o IME só decide se chama o handler)")


def teste_halt_com_ime_chama_handler():
    """Com a chave ligada, acordar do HALT leva direto à rotina."""
    m = maquina_em()
    escrever(m, 0xC000, 0x76, 0x00)
    m.cpu.ime = True
    m.ie = 0x04
    m.cpu.step()                              # HALT
    m.if_ = 0x04
    m.cpu.step()                              # acorda e atende
    s.igual(m.cpu.reg16[PC], 0x50, "com IME=1 acordar do HALT chama o handler")


def teste_bug_do_halt():
    """
    Com IME=0 e uma interrupção já pendente, o HALT não dorme e o PC não
    incrementa na busca seguinte — a próxima instrução roda DUAS vezes.
    """
    m = maquina_em()
    escrever(m, 0xC000, 0x76, 0x3C, 0x00)     # HALT ; INC A ; NOP
    m.cpu.reg8[A] = 0
    m.cpu.ime = False
    m.ie = 0x04
    m.if_ = 0x04                              # já pendente ANTES do HALT

    m.cpu.step()                              # HALT
    s.checar(not m.cpu.halted, "com IRQ pendente e IME=0 o HALT não dorme")
    s.checar(m.cpu.halt_bug, "o bug do HALT fica armado")

    m.cpu.step()                              # INC A (sem avançar o PC)
    s.igual(m.cpu.reg16[PC], 0xC001, "o PC não avançou na busca com o bug armado")
    s.igual(m.cpu.reg8[A], 1, "o INC A executou")

    m.cpu.step()                              # INC A de novo
    s.igual(m.cpu.reg8[A], 2, "a instrução seguinte ao HALT executa duas vezes")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("teste_"):
            fn()
    sys.exit(0 if s.relatorio() else 1)
