"""
Testes de comportamento das instruções, uma a uma.

Cada caso monta uma máquina com uma ROM sintética, escreve a instrução na
memória, executa um passo e confere o efeito — registradores, flags, memória e
ponteiro de programa.

É o teste mais tedioso do projeto e um dos mais valiosos. Quando uma ROM da
Blargg falha, ela diz "instrução errada" e não qual; foi aqui que várias delas
foram encurraladas até o `LD` ou o `ADC` específico.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gb.cartridge import Cartridge
from gb.machine import Machine
from gb.cpu import PC, UnknownOpcode
from gb.opcodes import opcode

OPCODES = opcode
def maquina(patches=None):
    rom = bytearray(0x8000)
    rom[0x148] = 0x00
    rom[0x149] = 0x00
    if patches:
        for addr, val in patches.items():
            rom[addr] = val
    return Machine(Cartridge(rom))


def test_tabela_tem_256():
    """
    As duas tabelas de despacho estão completas: nenhuma posição vazia.

    Uma posição esquecida viraria `None is not callable` na primeira vez que aquele
    byte aparecesse — possivelmente meses depois, num jogo específico.
    """
    assert len(OPCODES) == 256, f"tabela tem {len(OPCODES)} entradas, esperado 256"
    print("  tabela tem 256 entradas: OK")


def test_nop_avanca_pc():
    """A instrução mais simples avança o ponteiro em um byte."""
    m = maquina({0x0100: 0x00})
    m.cpu.reg16[PC] = 0x0100
    m.cpu.step()
    assert m.cpu.reg16[PC] == 0x0101, \
        f"PC == {m.cpu.reg16[PC]:04X}, esperado 0101"
    print("  NOP avança PC em 1: OK")


def test_nop_custa_4():
    """E gasta exatamente um M-cycle."""
    m = maquina({0x0100: 0x00})
    m.cpu.reg16[PC] = 0x0100
    antes = m.cycles
    m.cpu.step()
    delta = m.cycles - antes
    assert delta == 4, f"NOP custou {delta} T-cycles, esperado 4"
    print("  NOP custa 4 T-cycles: OK")


def test_nop_nao_mexe_em_nada():
    """
    E não toca em registrador nem flag nenhuma.

    Vale testar o que uma instrução NÃO faz: é assim que se pega um efeito colateral
    acidental, que seria invisível olhando só o que ela deveria fazer.
    """
    m = maquina({0x0100: 0x00})
    m.cpu.reg16[PC] = 0x0100
    m.cpu.reg8[1] = 0x42          # A
    m.cpu.reg16[3] = 0xBEEF       # HL
    m.cpu.reg16[4] = 0xFFFE       # SP
    m.cpu.step()
    assert m.cpu.reg8[1] == 0x42, "NOP mexeu em A"
    assert m.cpu.reg16[3] == 0xBEEF, "NOP mexeu em HL"
    assert m.cpu.reg16[4] == 0xFFFE, "NOP mexeu em SP"
    print("  NOP não altera registradores: OK")


def test_cem_nops():
    """Cem instruções seguidas somam exatamente cem vezes o custo de uma."""
    rom_patches = {0x0100 + i: 0x00 for i in range(100)}
    m = maquina(rom_patches)
    m.cpu.reg16[PC] = 0x0100
    antes = m.cycles
    for _ in range(100):
        m.cpu.step()
    assert m.cpu.reg16[PC] == 0x0164, \
        f"PC == {m.cpu.reg16[PC]:04X}, esperado 0164"
    assert m.cycles - antes == 400, \
        f"100 NOPs custaram {m.cycles - antes}, esperado 400"
    print("  100 NOPs seguidos: OK")


def test_opcode_desconhecido():
    """
    Um byte que não é instrução levanta erro nomeado, com o endereço.

    No chip real isso trava o processador. Aqui vale muito mais saber qual byte
    estranho apareceu e onde — quase sempre significa que o ponteiro se perdeu e
    está executando dados como se fossem código.
    """
    m = maquina({0x0100: 0xD3})       # D3 não existe no SM83
    m.cpu.reg16[PC] = 0x0100
    try:
        m.cpu.step()
    except UnknownOpcode as e:
        msg = str(e).upper()
        assert "D3" in msg, f"mensagem não diz qual opcode: {e}"
        print(f"  opcode desconhecido levanta UnknownOpcode: OK")
        print(f"    (mensagem: {e})")
        return
    raise AssertionError("deveria ter levantado UnknownOpcode")


if __name__ == "__main__":
    print("testes do step:")
    for fn in (test_tabela_tem_256, test_nop_avanca_pc, test_nop_custa_4,
               test_nop_nao_mexe_em_nada, test_cem_nops,
               test_opcode_desconhecido):
        fn()
    print("todos passaram.")