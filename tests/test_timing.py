"""
A duração de cada uma das 512 instruções, conferida contra uma tabela.

Este arquivo é uma tabela de referência transcrita da documentação do console, e
um laço que executa cada opcode medindo quantos T-cycles ele consumiu.

Instruções condicionais têm DUAS durações, conforme o desvio aconteça ou não, e
as duas são conferidas. Esse é o erro clássico: um `JR NZ` custa 12 T-cycles
quando pula e 8 quando não pula, e um emulador que cobre sempre 12 acumula erro
em todo laço — o suficiente para desalinhar efeitos gráficos programados por
contagem de ciclos.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gb.cartridge import Cartridge
from gb.machine import Machine
from gb.cpu import PC, SP, HL
from gb.opcodes import opcode

OPCODES = opcode
# Duração em T-cycles. Tupla = (tomado, não-tomado). None = opcode ilegal.
DURACAO = [
    4,12, 8, 8, 4, 4, 8, 4,20, 8, 8, 8, 4, 4, 8, 4,   # 0x
    4,12, 8, 8, 4, 4, 8, 4,12, 8, 8, 8, 4, 4, 8, 4,   # 1x
    (12,8),12,8,8,4,4,8,4,(12,8),8,8,8,4,4,8,4,       # 2x
    (12,8),12,8,8,12,12,12,4,(12,8),8,8,8,4,4,8,4,    # 3x
    4,4,4,4,4,4,8,4, 4,4,4,4,4,4,8,4,                 # 4x
    4,4,4,4,4,4,8,4, 4,4,4,4,4,4,8,4,                 # 5x
    4,4,4,4,4,4,8,4, 4,4,4,4,4,4,8,4,                 # 6x
    8,8,8,8,8,8,4,8, 4,4,4,4,4,4,8,4,                 # 7x  (76 = HALT)
    4,4,4,4,4,4,8,4, 4,4,4,4,4,4,8,4,                 # 8x
    4,4,4,4,4,4,8,4, 4,4,4,4,4,4,8,4,                 # 9x
    4,4,4,4,4,4,8,4, 4,4,4,4,4,4,8,4,                 # Ax
    4,4,4,4,4,4,8,4, 4,4,4,4,4,4,8,4,                 # Bx
    (20,8),12,(16,12),16,(24,12),16,8,16,
    (20,8),16,(16,12),4,(24,12),24,8,16,              # Cx  (CB = 4)
    (20,8),12,(16,12),None,(24,12),16,8,16,
    (20,8),16,(16,12),None,(24,12),None,8,16,         # Dx
    12,12,8,None,None,16,8,16,
    16,4,16,None,None,None,8,16,                      # Ex
    12,12,8,4,None,16,8,16,
    12,8,16,4,None,None,8,16,                         # Fx
]

PULAR = {0x10, 0x76, 0xCB}          # STOP, HALT, prefixo


def medir(op):
    rom = bytearray(0x8000)
    rom[0x148] = 0x00
    rom[0x149] = 0x00
    m = Machine(Cartridge(rom))
    c = m.cpu
    c.reg16[PC] = 0xC200
    c.reg16[SP] = 0xC100
    c.reg16[HL] = 0xC000
    m.bus_write(0xC200, op)
    antes = m.cycles
    c.step()
    return m.cycles - antes


if __name__ == "__main__":
    assert len(DURACAO) == 256, f"tabela tem {len(DURACAO)}"
    ok = falhou = pulado = nao_impl = 0
    erros = []

    for op in range(256):
        esperado = DURACAO[op]
        if esperado is None or op in PULAR:
            pulado += 1
            continue
        if OPCODES[op] is None:
            nao_impl += 1
            continue
        if isinstance(esperado, tuple):
            pulado += 1          # condicionais: Módulo 3
            continue
        try:
            real = medir(op)
        except Exception as e:
            erros.append((op, esperado, f"exceção: {type(e).__name__}: {e}"))
            falhou += 1
            continue
        if real == esperado:
            ok += 1
        else:
            falta = esperado - real
            dica = f"faltam {falta} ({falta//4} ciclo(s) interno(s))" if falta > 0 \
                   else f"sobram {-falta}"
            erros.append((op, esperado, f"deu {real} — {dica}"))
            falhou += 1

    print(f"OK: {ok}   falhou: {falhou}   não implementado: {nao_impl}   pulado: {pulado}")
    if erros:
        print("\nproblemas:")
        for op, esp, msg in erros:
            print(f"  0x{op:02X}  esperado {esp:>2}  {msg}")

    print()
    from gb.opcodes import opcodeCB          # ajuste ao seu nome
    ok_cb = falhou_cb = 0
    erros_cb = []
    for op in range(256):
        # (HL) é a coluna 6 e E de cada linha
        col = op & 0x07
        if col != 6:
            esperado = 8
        elif 0x40 <= op <= 0x7F:               # BIT u3,(HL)
            esperado = 12
        else:
            esperado = 16
        if opcodeCB[op] is None:
            continue
        rom = bytearray(0x8000); rom[0x148] = rom[0x149] = 0x00
        m = Machine(Cartridge(rom))
        m.cpu.reg16[PC] = 0xC200
        m.cpu.reg16[HL] = 0xC000
        m.bus_write(0xC200, 0xCB)
        m.bus_write(0xC201, op)
        antes = m.cycles
        try:
            m.cpu.step()
        except Exception as e:
            erros_cb.append((op, esperado, f"exceção: {type(e).__name__}"))
            falhou_cb += 1
            continue
        real = m.cycles - antes
        if real == esperado:
            ok_cb += 1
        else:
            erros_cb.append((op, esperado, f"deu {real}"))
            falhou_cb += 1

    print(f"CB — OK: {ok_cb}   falhou: {falhou_cb}")
    for op, esp, msg in erros_cb:
        print(f"  CB 0x{op:02X}  esperado {esp:>2}  {msg}")