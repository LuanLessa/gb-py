"""
As 512 instruções que o Sharp SM83 sabe executar.

Este é o arquivo mais longo do projeto e um dos mais fáceis. São 110 funções
que seguem meia dúzia de padrões: entendidas as primeiras de cada família, as
outras se leem sozinhas.

No fim do arquivo estão as duas tabelas que ligam cada byte à sua função. É
por elas que `CPU.step` decide o que executar.


COMO LER OS NOMES
-----------------

Os nomes seguem a notação usada na documentação do console, e cada sufixo diz
de onde vem o operando:

    r8      um registrador de 8 bits          ADD_A_r8   → ADD A, B
    r16     um par de registradores           INC_r16    → INC HL
    n8      um número gravado na instrução    ADD_A_n8   → ADD A, $05
    n16     um endereço gravado na instrução  JP_n16     → JP $1234
    e8      um deslocamento com sinal         JR_e8      → JR -8
    mHL     o byte que HL aponta              ADD_A_mHL  → ADD A, [HL]
    mN16    o byte de um endereço fixo        LD_mN16_A  → LD [$1234], A
    u3      um número de 0 a 7                BIT_u3_r8  → BIT 3, B
    cc      uma condição (Z, NZ, C, NC)       JP_cc_n16  → JP NZ, $1234

O `m` de mHL vem de "memória": nos manuais isso aparece como colchetes, e a
diferença entre `LD HL, $8000` e `LD [HL], A` é justamente essa. O primeiro
mexe no ponteiro; o segundo, na memória para onde ele aponta.

Manter os nomes originais, em vez de traduzi-los, é o que permite comparar
este arquivo linha a linha com qualquer tabela de referência do Game Boy.


A FORMA DAS FUNÇÕES
-------------------

Toda função recebe `cpu` como ÚLTIMO parâmetro, e não como primeiro. A ordem
foi escolhida para as tabelas do fim do arquivo, onde uma família inteira de
opcodes é escrita com a mesma função e um parâmetro diferente:

    opcode[0x04] = lambda cpu: INC_r8(B, cpu)    # INC B
    opcode[0x0C] = lambda cpu: INC_r8(C, cpu)    # INC C

Uma função por instrução seriam 512 funções quase idênticas. Uma função por
FAMÍLIA, parametrizada pelo registrador, resolve as oito de uma vez.

Nenhuma delas devolve nada: o efeito é sempre mudar o estado da CPU — um
registrador, uma flag, o ponteiro de programa, a memória.


DE ONDE VEM O TEMPO
-------------------

Quase nenhuma função conta ciclos explicitamente, e isso não é descuido. O
tempo é cobrado por quem acessa o barramento: `cpu.fetch8()`, `cpu.read8()` e
`cpu.write8()` já avançam 1 M-cycle cada, como explicado em `cpu.py`. Uma
instrução que lê dois bytes e escreve um custa 3 M-cycles sem precisar declarar
nada.

As chamadas soltas a `cpu.bus.tick4()` que aparecem aqui e ali são os ciclos
INTERNOS: instantes em que o chip trabalha sem tocar na memória, como ao somar
dois valores de 16 bits com uma unidade aritmética de 8. Sem eles o emulador
roda os jogos normalmente — e falha nos testes de temporização, que medem a
duração de cada uma das 512 instruções.
"""

from typing import Callable

from .cpu import *
from .constants import *


def opcode_invalido(opc, cpu):
    """
    Os onze bytes que não correspondem a instrução nenhuma.
    São eles: D3, DB, DD, E3, E4, EB, EC, ED, F4, FC e FD. No chip real esses
    bytes TRAVAM o processador — ele entra num estado do qual só sai desligando
    o console.
    Aqui o resultado é uma exceção com o byte e o endereço. Para um emulador
    didático, saber qual byte estranho apareceu e onde vale muito mais do que um
    congelamento silencioso: quase sempre significa que o PC se perdeu e está
    executando dados como se fossem código.
    """
    raise UnknownOpcode(
        f"Opcode inválido 0x{opc:02X} executado em PC=0x{(cpu.reg16[PC] - 1) & 0xFFFF:04X}"
    )

# ======================================================================
#  BIT, RES e SET — mexer num bit de cada vez
# ======================================================================
#
# Num console com 8 KB de memória, gastar um byte inteiro para guardar um
# sim/não é luxo. Um byte comporta oito respostas dessas, e estas três
# instruções são o que permite tratá-las separadamente:
#
#     BIT   lê um bit    (a resposta vai para a flag Z)
#     SET   liga um bit
#     RES   desliga um bit
#
# Todas fazem parte do conjunto estendido, o do prefixo 0xCB, e por isso
# custam um M-cycle a mais que as instruções comuns.


def BIT_u3_r8(u3, r8, cpu):
    """
    BIT u3, r8 — o bit u3 do registrador está ligado?
    A resposta não vai para lugar nenhum a não ser para a flag Z, que fica ligada
    quando o bit testado é ZERO. A inversão parece contraintuitiva, mas combina
    com o resto do conjunto de instruções: Z sempre significa "deu zero", e o
    desvio `JR Z` que vem logo depois se lê como "se o bit estava desligado".
    O registrador não é alterado, e a flag C também não. Só Z, N e H se mexem.
    """
    register = cpu.reg8[r8]
    bit_value = (register >> u3) & 1
    cpu.setFlag(FLAG_Z, bit_value == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, True)


def BIT_u3_mHL(u3, cpu):
    """
    BIT u3, [HL] — o mesmo teste, no byte que HL aponta.
    Custa 3 M-cycles em vez de 2: um a mais para ir buscar o valor na memória.
    Nada é escrito de volta, porque testar não modifica.
    """
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    bit_value = (data >> u3) & 1
    cpu.setFlag(FLAG_Z, bit_value == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, True)


def RES_u3_r8(u3, r8, cpu):
    """
    RES u3, r8 — desliga o bit u3, deixando os outros sete como estavam.
    O jeito de desligar UM bit é montar uma máscara com 1 em todas as posições
    menos naquela, e aplicar `&`. Onde a máscara tem 1, o valor original passa;
    onde tem 0, o bit morre.

        u3 = 3
        1 << 3        = 00001000     o bit que queremos desligar
        ^ 0xFF        = 11110111     invertido, vira a máscara
        10110101 &    = 10110101
                        11110111
                        --------
                        10110101 -> o bit 3 já era 0, nada mudou
        10111101 &    = 10110101 -> aqui ele era 1, e foi desligado

    Nenhuma flag é afetada.
    """
    register = cpu.reg8[r8]

    # Ex.: u3=3 -> 00001000, invertido vira 11110111
    mask = (1 << u3) ^ 0xFF
    cpu.reg8[r8] = (register & mask) & 0xFF


def RES_u3_mHL(u3, cpu):
    """
    RES u3, [HL] — desliga um bit do byte que HL aponta.
    Este é o padrão "ler, modificar, escrever": três acessos ao barramento (buscar
    a instrução, ler o dado, gravar de volta) mais o prefixo CB, num total de 4
    M-cycles. É o dobro do custo da versão em registrador, e a razão pela qual
    código apertado carrega o valor para um registrador antes de mexer nele.
    """
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    mask = (1 << u3) ^ 0xFF
    result = (data & mask) & 0xFF
    cpu.write8(register_hl, result)


def SET_u3_r8(u3, r8, cpu):
    """
    SET u3, r8 — liga o bit u3, deixando os outros sete como estavam.
    O inverso do RES, e mais simples: `|` com uma máscara que tem 1 só na posição
    desejada. Onde a máscara tem 1, o resultado vira 1; onde tem 0, o valor
    original passa intacto.
    Nenhuma flag é afetada.
    """
    register = cpu.reg8[r8]
    mask = 1 << u3
    cpu.reg8[r8] = (register | mask) & 0xFF


def SET_u3_mHL(u3, cpu):
    """SET u3, [HL] — liga um bit do byte que HL aponta. 4 M-cycles."""
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    mask = 1 << u3
    result = (data | mask) & 0xFF
    cpu.write8(register_hl, result)


# ======================================================================
#  ROTAÇÕES CIRCULARES — o bit que sai de um lado entra do outro
# ======================================================================
#
# Girar não perde informação: os oito bits continuam todos ali, só que em
# outra posição. Oito giros seguidos devolvem o byte original.
#
# Cada família tem três formas, e a diferença entre elas é só onde está o
# valor:
#
#     RLC_r8    num registrador          2 M-cycles
#     RLC_mHL   na memória, via HL       4 M-cycles (lê e escreve de volta)
#     RLCA      no acumulador, sem CB    1 M-cycle
#
# A terceira forma existe porque girar o acumulador é tão comum que ganhou
# opcode próprio, sem o prefixo 0xCB. E ela tem uma diferença de
# comportamento que não é atalho nenhum — está explicada em RLCA.

def RLC_r8(r8, cpu):
    """
    RLC r8 — gira o byte uma casa para a esquerda, em círculo.
    O bit que sai pela esquerda dá a volta e entra pela direita, e uma cópia dele
    também vai para a flag C:

        10110101  ->  01101011      o bit 7 (1) reapareceu na posição 0
        ^                    ^
        saiu daqui           e entrou aqui, além de ir para o carry

    Girar é diferente de deslocar: aqui nenhum bit se perde. Depois de oito RLC
    seguidos o valor volta a ser o mesmo.
    """
    register = cpu.reg8[r8]
    bit7 = (register >> 7) & 1

    # O bit que saiu pela esquerda reentra pela direita
    result = ((register << 1) | bit7) & 0xFF
    cpu.reg8[r8] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit7 == 1)


def RLC_mHL(cpu):
    """RLC [HL] — gira para a esquerda, em círculo, o byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    bit7 = (data >> 7) & 1
    result = ((data << 1) | bit7) & 0xFF
    cpu.write8(register_hl, result)
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit7 == 1)


def RLCA(cpu):
    """
    RLCA — o mesmo giro que RLC A, com duas diferenças que importam.
    A primeira é o tamanho: RLCA é uma instrução de um byte só (0x07), enquanto
    RLC A precisa do prefixo CB e ocupa dois. Metade do espaço e metade do tempo,
    para a operação que mais se faz no acumulador.
    A segunda é a flag Z, e é uma pegadinha clássica. RLCA deixa Z sempre em ZERO,
    mesmo que o resultado seja zero. RLC A liga Z normalmente. Emuladores que
    tratam as duas como a mesma instrução passam na maioria dos jogos e falham nas
    ROMs de teste — e, mais cedo ou mais tarde, num jogo que dependa disso.
    """
    register = cpu.reg8[A]
    bit7 = (register >> 7) & 1
    result = ((register << 1) | bit7) & 0xFF
    cpu.reg8[A] = result

    # Aqui está a diferença para o RLC A: Z fica desligada mesmo com resultado zero
    cpu.setFlag(FLAG_Z, False)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit7 == 1)


def RRC_r8(r8, cpu):
    """
    RRC r8 — gira o byte uma casa para a direita, em círculo.
    Espelho do RLC: o bit 0 sai pela direita, reaparece na posição 7 e uma cópia
    vai para a flag C.
    """
    register = cpu.reg8[r8]
    bit0 = register & 1
    result = (register >> 1) | (bit0 << 7)
    cpu.reg8[r8] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit0 == 1)


def RRC_mHL(cpu):
    """RRC [HL] — gira para a direita, em círculo, o byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    bit0 = data & 1
    result = (data >> 1) | (bit0 << 7)
    cpu.write8(register_hl, result)
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit0 == 1)


def RRCA(cpu):
    """
    RRCA — RRC A em um byte só, e com a flag Z sempre desligada.
    Mesma diferença descrita em RLCA, na outra direção.
    """
    register = cpu.reg8[A]
    bit0 = register & 1
    result = (register >> 1) | (bit0 << 7)
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, False)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit0 == 1)


# ======================================================================
#  ROTAÇÕES ATRAVÉS DO CARRY — a flag C entra no círculo
# ======================================================================
#
# Aqui o círculo tem NOVE posições: os oito bits do byte mais a flag C. O bit
# que sai vai para a flag, e o valor que a flag tinha antes entra do outro
# lado.
#
# É o que torna possível deslocar valores maiores que um byte. Num número de
# 16 bits guardado em dois registradores, um RL no byte baixo joga o bit 7
# para o carry, e o RL seguinte no byte alto o recolhe — o bit atravessa de um
# registrador para o outro.

def RL_r8(r8, cpu):
    """
    RL r8 — gira para a esquerda passando PELA flag C.
    A diferença para o RLC está em quem entra pela direita. No RLC, entra o bit que
    acabou de sair. Aqui, entra o valor que a flag C tinha ANTES da operação — e o
    bit que saiu é que vai ocupar a flag. O carry vira o nono bit do círculo:

        antes:  C=1   valor = 10110101
        depois: C=1   valor = 01101011
                                 ^ entrou o C antigo, e o bit 7 (1) virou o C novo

    É isso que permite deslocar números maiores que um byte. Para girar um valor de
    16 bits guardado em dois registradores, um RL no byte baixo e outro no alto
    fazem o bit atravessar de um para o outro através do carry.
    """
    register = cpu.reg8[r8]
    old_carry = 1 if cpu.getFlag(FLAG_C) else 0
    bit7 = (register >> 7) & 1

    # Entra o carry ANTIGO; o bit que sai vira o carry novo
    result = ((register << 1) | old_carry) & 0xFF
    cpu.reg8[r8] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit7 == 1)


def RL_mHL(cpu):
    """RL [HL] — gira para a esquerda através do carry, no byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    old_carry = 1 if cpu.getFlag(FLAG_C) else 0
    bit7 = (data >> 7) & 1
    result = ((data << 1) | old_carry) & 0xFF
    cpu.write8(register_hl, result)
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit7 == 1)


def RLA(cpu):
    """RLA — RL A em um byte só, com a flag Z sempre desligada."""
    register = cpu.reg8[A]
    old_carry = 1 if cpu.getFlag(FLAG_C) else 0
    bit7 = (register >> 7) & 1
    result = ((register << 1) | old_carry) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, False)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit7 == 1)


def RR_r8(r8, cpu):
    """
    RR r8 — gira para a direita passando pela flag C.
    Espelho do RL: o valor antigo do carry entra na posição 7, e o bit 0 vira o
    novo carry.
    """
    register = cpu.reg8[r8]
    old_carry = 1 if cpu.getFlag(FLAG_C) else 0
    bit0 = register & 1
    result = (register >> 1) | (old_carry << 7)
    cpu.reg8[r8] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit0 == 1)


def RR_mHL(cpu):
    """RR [HL] — gira para a direita através do carry, no byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    old_carry = 1 if cpu.getFlag(FLAG_C) else 0
    bit0 = data & 1
    result = (data >> 1) | (old_carry << 7)
    cpu.write8(register_hl, result)
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit0 == 1)


def RRA(cpu):
    """RRA — RR A em um byte só, com a flag Z sempre desligada."""
    register = cpu.reg8[A]
    old_carry = 1 if cpu.getFlag(FLAG_C) else 0
    bit0 = register & 1
    result = (register >> 1) | (old_carry << 7)
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, False)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit0 == 1)


# ======================================================================
#  DESLOCAMENTOS — aqui os bits caem fora
# ======================================================================
#
# Diferente das rotações: o bit que sai vai para a flag C e não volta mais. O
# lugar vago é preenchido por 0 — ou, no caso do SRA, pela cópia do bit de
# sinal.
#
# Deslocar é a forma de multiplicar e dividir por potências de 2 num
# processador que não tem instrução de multiplicação nem de divisão:
#
#     SLA   << 1    multiplica por 2
#     SRL   >> 1    divide por 2, para números SEM sinal
#     SRA   >> 1    divide por 2, para números COM sinal

def SLA_r8(r8, cpu):
    """
    SLA r8 — desloca uma casa para a esquerda; entra 0 pela direita.
    Ao contrário do giro, aqui um bit se perde de verdade: o bit 7 vai para o carry
    e não volta mais.
    Deslocar para a esquerda é multiplicar por 2. Como o SM83 não tem instrução de
    multiplicação, essa é a ferramenta disponível — multiplicar por 10, por
    exemplo, vira "desloca uma vez, guarda, desloca mais duas, soma".
    """
    register = cpu.reg8[r8]
    bit7 = (register >> 7) & 1
    result = (register << 1) & 0xFF
    cpu.reg8[r8] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit7 == 1)


def SLA_mHL(cpu):
    """SLA [HL] — desloca para a esquerda o byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    bit7 = (data >> 7) & 1
    result = (data << 1) & 0xFF
    cpu.write8(register_hl, result)
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit7 == 1)


def SRA_r8(r8, cpu):
    """
    SRA r8 — desloca para a direita PRESERVANDO o bit 7.
    O A é de "aritmético", e a preservação do bit 7 é o motivo do nome. Quando o
    byte representa um número com sinal, o bit 7 é o sinal: 0 para positivo, 1 para
    negativo. Um deslocamento comum jogaria 0 ali e transformaria -8 em +124.
    Repetir o bit de sinal mantém o número negativo, e o resultado continua sendo a
    divisão por 2 que se esperava:

        11111000 (-8)  ->  11111100 (-4)     com SRA, o sinal se mantém
        11111000 (-8)  ->  01111100 (+124)   com SRL, o sinal se perde

    O bit 0 vai para o carry nos dois casos.
    """
    register = cpu.reg8[r8]
    bit0 = register & 1
    bit7_mask = register & 0x80 # Isola apenas o bit 7 (128)

    # O bit 7 se repete: é ele que preserva o sinal do número
    result = (register >> 1) | bit7_mask
    cpu.reg8[r8] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit0 == 1)


def SRA_mHL(cpu):
    """SRA [HL] — desloca para a direita preservando o sinal, no byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    bit0 = data & 1
    bit7_mask = data & 0x80
    result = (data >> 1) | bit7_mask
    cpu.write8(register_hl, result)
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit0 == 1)


def SRL_r8(r8, cpu):
    """
    SRL r8 — desloca para a direita; entra 0 pela esquerda.
    O L é de "lógico": aqui o byte é tratado como um número sem sinal, e dividir
    por 2 é só empurrar os bits. Para valores com sinal, a instrução certa é SRA.
    """
    register = cpu.reg8[r8]
    bit0 = register & 1
    result = register >> 1
    cpu.reg8[r8] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit0 == 1)


def SRL_mHL(cpu):
    """SRL [HL] — desloca para a direita sem preservar sinal, no byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    bit0 = data & 1
    result = data >> 1
    cpu.write8(register_hl, result)
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, bit0 == 1)


# ======================================================================
#  SWAP — troca as duas metades do byte
# ======================================================================

def SWAP_r8(r8, cpu):
    """
    SWAP r8 — troca de lugar os dois nibbles do byte.
    Nibble é meio byte, quatro bits. SWAP faz 0xAB virar 0xBA:

        10110101  ->  01011011
        ^^^^          ....^^^^   o nibble alto foi para baixo, e vice-versa

    Parece uma operação exótica, e é surpreendentemente útil. Quatro bits guardam
    um dígito hexadecimal exato, então um byte comporta dois dígitos — e mostrar um
    número em hexadecimal na tela é justamente separar os dois. SWAP resolve isso
    em uma instrução, contra os dois deslocamentos que seriam necessários.
    Todas as flags são mexidas, e C sempre termina desligada.
    """
    register = cpu.reg8[r8]
    high_nibble = register & 0xF0
    low_nibble = register & 0x0F
    result = (low_nibble << 4) | (high_nibble >> 4)
    cpu.reg8[r8] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, False)


def SWAP_mHL(cpu):
    """SWAP [HL] — troca os nibbles do byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    data = cpu.read8(register_hl)
    high_nibble = data & 0xF0
    low_nibble = data & 0x0F
    result = (low_nibble << 4) | (high_nibble >> 4)
    cpu.write8(register_hl, result)
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, False)


# ======================================================================
#  ARITMÉTICA — somar, subtrair, comparar
# ======================================================================
#
# Tudo aqui gira em torno de um registrador só. O SM83 tem um ACUMULADOR, o
# registrador A, e é nele que toda conta acontece: um dos operandos vem de A,
# e o resultado volta para A. Somar B com C exige passar por ele.
#
# Cada operação aparece em três formas, conforme a origem do segundo operando:
#
#     ADD_A_r8    outro registrador                 1 M-cycle
#     ADD_A_mHL   o byte que HL aponta              2 M-cycles
#     ADD_A_n8    um número gravado na instrução    2 M-cycles
#
# As versões com carry (ADC e SBC) existem para contas maiores que um byte,
# encadeando o "vai um" de uma etapa para a seguinte.
#
# As flags são o produto mais importante destas instruções — mais até que o
# resultado, no caso do CP, que descarta a conta e fica só com elas.


def ADC_A_r8(r8, cpu):
    """
    ADC A, r8 — soma um registrador MAIS o carry que sobrou da conta anterior.
    Existe para somar números maiores do que um byte. O SM83 só soma 8 bits por
    vez, então somar dois valores de 16 bits é feito em duas etapas: um ADD nos
    bytes de baixo, que deixa em C o "vai um", e um ADC nos bytes de cima, que
    recolhe esse carry. É a conta de somar do papel, com os bytes no lugar dos
    algarismos.
    O `carry` entra como True ou False, e Python trata como 1 e 0 numa soma.
    """
    accumulator = cpu.reg8[A]
    register = cpu.reg8[r8]
    carry = cpu.getFlag(FLAG_C)
    result = (accumulator + register + carry) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    # H olha só o nibble de baixo; C olha o byte inteiro. A conta é feita sem
    cpu.setFlag(FLAG_H, (accumulator & 0xF) + (register & 0xF) + carry > 0xF)
    # máscara de propósito, para que o estouro apareça na comparação.
    cpu.setFlag(FLAG_C, (accumulator + register + carry) > 0xFF)


def ADC_A_mHL(cpu):
    """ADC A, [HL] — soma com carry o byte que HL aponta."""
    accumulator = cpu.reg8[A]
    data = cpu.read8(cpu.reg16[HL])
    carry = cpu.getFlag(FLAG_C)
    result = (accumulator + data + carry) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, (accumulator & 0xF) + (data & 0xF) + carry > 0xF)
    cpu.setFlag(FLAG_C,  (accumulator + data + carry) > 0xFF)


def ADC_A_n8(cpu):
    """ADC A, n8 — soma com carry um número escrito na instrução."""
    accumulator = cpu.reg8[A]
    data = cpu.fetch8()
    carry = cpu.getFlag(FLAG_C)
    result = (accumulator + data + carry) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, (accumulator & 0xF) + (data & 0xF) + carry > 0xF)
    cpu.setFlag(FLAG_C,  (accumulator + data + carry) > 0xFF)


def ADD_A_r8(r8, cpu):
    """
    ADD A, r8 — soma um registrador ao acumulador.
    Toda conta do SM83 termina em A. Não existe "soma B com C": os dois operandos
    passam por A, e é por isso que tanta instrução existe só para mover valores.
    As quatro flags saem daqui, e duas merecem atenção.
    FLAG_C é o "vai um" para fora do byte. A soma é feita em Python, onde o
    resultado pode passar de 255 à vontade, e a comparação `> 0xFF` pergunta se
    teria estourado no hardware. Só depois disso o `& 0xFF` corta o excesso.
    FLAG_H é o "vai um" do bit 3 para o bit 4 — o meio do byte. Somar só os nibbles
    de baixo dos dois operandos e ver se passou de 0xF responde exatamente isso.
    Serve para uma instrução só, a DAA, que está mais abaixo neste arquivo e
    explica por que essa flag existe.
    """
    accumulator = cpu.reg8[A]
    register = cpu.reg8[r8]
    result = (accumulator + register) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, (accumulator & 0xF) + (register & 0xF) > 0xF)
    cpu.setFlag(FLAG_C,  (accumulator + register) > 0xFF)


def ADD_A_mHL(cpu):
    """ADD A, [HL] — soma ao acumulador o byte que HL aponta. 2 M-cycles."""
    accumulator = cpu.reg8[A]
    data = cpu.read8(cpu.reg16[HL])
    result = (accumulator + data) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, (accumulator & 0xF) + (data & 0xF) > 0xF)
    cpu.setFlag(FLAG_C,  (accumulator + data) > 0xFF)


def ADD_A_n8(cpu):
    """
    ADD A, n8 — soma ao acumulador um número escrito na própria instrução.
    O `n8` é lido com `fetch8()`: ele está gravado na ROM logo depois do opcode.
    Uma instrução dessas ocupa dois bytes e custa 2 M-cycles.
    """
    accumulator = cpu.reg8[A]
    data = cpu.fetch8()
    result = (accumulator + data) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, (accumulator & 0xF) + (data & 0xF) > 0xF)
    cpu.setFlag(FLAG_C,  (accumulator + data) > 0xFF)


def CP_A_r8(r8, cpu):
    """
    CP A, r8 — compara, subtraindo sem guardar o resultado.
    É um SUB que joga a conta fora e fica só com as flags. Serve para comparar dois
    valores sem estragar o acumulador, e as três respostas ficam legíveis assim:

        Z ligado    A é igual ao valor comparado
        C ligado    A é menor
        nenhum      A é maior

    Daí o par `CP` seguido de `JR Z` ou `JR C` ser o "if" do assembly do Game Boy.
    """
    accumulator = cpu.reg8[A]
    register = cpu.reg8[r8]
    result = (accumulator - register) & 0xFF
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, (register & 0xF) > (accumulator & 0xF))
    cpu.setFlag(FLAG_C, register > accumulator)


def CP_A_mHL(cpu):
    """CP A, [HL] — compara o acumulador com o byte que HL aponta."""
    accumulator = cpu.reg8[A]
    data = cpu.read8(cpu.reg16[HL])
    result = (accumulator - data) & 0xFF
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, (data & 0xF) > (accumulator & 0xF))
    cpu.setFlag(FLAG_C, data > accumulator)


def CP_A_n8(cpu):
    """CP A, n8 — compara o acumulador com um número escrito na instrução."""
    accumulator = cpu.reg8[A]
    data = cpu.fetch8()
    result = (accumulator - data) & 0xFF
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, (data & 0xF) > (accumulator & 0xF))
    cpu.setFlag(FLAG_C, data > accumulator)


def DEC_r8(r8, cpu):
    """
    DEC r8 — subtrai 1 do registrador.
    Como no INC, a flag C fica intacta. FLAG_H liga quando o nibble de baixo era 0,
    que é quando subtrair 1 exige emprestar do nibble de cima.
    `DEC B` seguido de `JR NZ` é o laço mais comum do assembly do Game Boy:
    decrementa e repete até zerar, com o teste saindo de graça na flag Z.
    """
    register = cpu.reg8[r8]
    result = (register - 1) & 0xFF
    cpu.reg8[r8] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, register & 0xF == 0x0)


def DEC_mHL(cpu):
    """DEC [HL] — subtrai 1 do byte que HL aponta. 3 M-cycles."""
    register = cpu.reg16[HL]
    data = cpu.read8(register)
    result = (data - 1) & 0xFF
    cpu.write8(register, result)
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, data & 0xF == 0x0)


def INC_r8(r8, cpu):
    """
    INC r8 — soma 1 ao registrador.
    A flag C NÃO é tocada, e isso é de propósito: um contador de laço pode ser
    incrementado no meio de uma conta de 16 bits sem destruir o carry que ainda
    será usado. Um `ADD A, 1` mexeria em C e estragaria a conta.
    FLAG_H liga quando o nibble de baixo era 0xF, porque é aí que somar 1 leva o
    "vai um" para o nibble de cima.
    """
    register = cpu.reg8[r8]
    result = (register + 1) & 0xFF
    cpu.reg8[r8] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, register & 0xF == 0xF)


def INC_mHL(cpu):
    """
    INC [HL] — soma 1 ao byte que HL aponta.
    Ler, modificar e escrever: 3 M-cycles, contra 1 da versão em registrador.
    """
    register = cpu.reg16[HL]
    data = cpu.read8(register)
    result = (data + 1) & 0xFF
    cpu.write8(register, result)
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, data & 0xF == 0xF)


def SBC_A_r8(r8, cpu):
    """
    SBC A, r8 — subtrai um registrador E o empréstimo da conta anterior.
    O par do ADC, para o outro lado: subtrair valores de 16 bits é um SUB nos bytes
    de baixo seguido de um SBC nos de cima.
    """
    accumulator = cpu.reg8[A]
    register = cpu.reg8[r8]
    carry = cpu.getFlag(FLAG_C)
    result = (accumulator - (register + carry)) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, (register & 0xF) + carry > (accumulator & 0xF))
    cpu.setFlag(FLAG_C, register + carry > accumulator)


def SBC_A_mHL(cpu):
    """SBC A, [HL] — subtrai com empréstimo o byte que HL aponta."""
    accumulator = cpu.reg8[A]
    data = cpu.read8(cpu.reg16[HL])
    carry = cpu.getFlag(FLAG_C)
    result = (accumulator - (data + carry)) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, (data & 0xF) + carry > (accumulator & 0xF))
    cpu.setFlag(FLAG_C, data + carry > accumulator)


def SBC_A_n8(cpu):
    """SBC A, n8 — subtrai com empréstimo um número escrito na instrução."""
    accumulator = cpu.reg8[A]
    data = cpu.fetch8()
    carry = cpu.getFlag(FLAG_C)
    result = (accumulator - (data + carry)) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, (data & 0xF) + carry > (accumulator & 0xF))
    cpu.setFlag(FLAG_C, data + carry > accumulator)


def SUB_A_r8(r8, cpu):
    """
    SUB A, r8 — subtrai um registrador do acumulador.
    Na subtração, FLAG_C e FLAG_H mudam de significado: em vez de "vai um", passam
    a indicar EMPRÉSTIMO. C liga quando o valor subtraído era maior que A, e H
    quando o nibble de baixo do subtraído era maior que o de A — os dois casos em
    que a conta precisa pedir emprestado.
    FLAG_N liga, e é justamente para registrar que a última operação foi uma
    subtração. Quem lê essa informação depois é a DAA.
    """
    accumulator = cpu.reg8[A]
    register = cpu.reg8[r8]
    result = (accumulator - register) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, (register & 0xF) > (accumulator & 0xF))
    cpu.setFlag(FLAG_C,  register > accumulator)


def SUB_A_mHL(cpu):
    """SUB A, [HL] — subtrai do acumulador o byte que HL aponta."""
    accumulator = cpu.reg8[A]
    data = cpu.read8(cpu.reg16[HL])
    result = (accumulator - data) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, (data & 0xF) > (accumulator & 0xF))
    cpu.setFlag(FLAG_C,  data > accumulator)


def SUB_A_n8(cpu):
    """SUB A, n8 — subtrai do acumulador um número escrito na instrução."""
    accumulator = cpu.reg8[A]
    data = cpu.fetch8()
    result = (accumulator - data) & 0xFF
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, (data & 0xF) > (accumulator & 0xF))
    cpu.setFlag(FLAG_C,  data > accumulator)


def ADD_HL_r16(r16, cpu):
    """
    ADD HL, r16 — soma de 16 bits, com HL fazendo o papel de acumulador.
    Serve para andar por estruturas na memória: HL aponta para o começo de uma
    tabela e recebe o deslocamento somado de uma vez.
    As flags H e C mudam de fronteira aqui. Em 8 bits, H olha a passagem do bit 3
    para o 4; em 16, olha a do bit 11 para o 12 — daí a máscara 0xFFF. C olha o
    estouro dos 16 bits inteiros. E a flag Z fica INTACTA, ao contrário de quase
    tudo o mais.
    O `tick4()` no fim é um M-cycle interno que a instrução gasta sem acessar a
    memória: a unidade aritmética do chip tem 8 bits, então uma soma de 16 leva dois
    passos e custa 2 M-cycles no total.
    """
    register_HL = cpu.reg16[HL]
    register = cpu.reg16[r16]
    cpu.reg16[HL] = (register_HL + register) & 0xFFFF
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, (register_HL & 0xFFF) + (register & 0xFFF) > 0xFFF)
    cpu.setFlag(FLAG_C,  (register_HL + register) > 0xFFFF)
    cpu.bus.tick4()


def DEC_r16(r16, cpu):
    """DEC r16 — subtrai 1 de um par de registradores, sem mexer em flags."""
    register = cpu.reg16[r16]
    cpu.bus.tick4()
    _talvez_corromper_oam(cpu, register)
    cpu.reg16[r16] = (register - 1) & 0xFFFF


def _talvez_corromper_oam(cpu, endereco):
    """
    Dispara a corrupção da OAM se o endereço estiver na faixa FE00-FEFF.
    Toda instrução que mexe num par de registradores de 16 bits passa por aqui. O
    motivo é uma falha elétrica do chip original, descrita em `cpu.bug_oam`: quando
    o valor aponta para a região da tabela de sprites, a alteração embaralha uma
    linha inteira dessa tabela.
    O `_` na frente do nome marca que a função é de uso interno deste arquivo.
    """
    if 0xFE00 <= endereco <= 0xFEFF:
        cpu.bus.ppu.corrupcao_oam_escrita()


def _corromper_oam_leitura(cpu, endereco):
    """
    A variante da corrupção que acontece quando o acesso é de LEITURA.
    O padrão de embaralhamento é diferente do da escrita — os detalhes de ambos
    estão em `ppu.py`.
    """
    if 0xFE00 <= endereco <= 0xFEFF:
        cpu.bus.ppu.corrupcao_oam_leitura_incremento()


def INC_r16(r16, cpu):
    """
    INC r16 — soma 1 a um par de registradores, sem mexer em flag nenhuma.
    Nenhuma flag é afetada, o que faz desta a instrução natural para andar por um
    ponteiro no meio de qualquer conta.
    O `tick4()` vem ANTES da mudança, e essa ordem tem consequência: durante esse
    M-cycle o endereço antigo ainda está no barramento, e é por isso que a
    verificação do bug da OAM usa o valor de antes. Ver `_talvez_corromper_oam`.
    """
    register = cpu.reg16[r16]
    cpu.bus.tick4()
    _talvez_corromper_oam(cpu, register)
    cpu.reg16[r16] = (register + 1) & 0xFFFF


# ======================================================================
#  OPERAÇÕES LÓGICAS — bit a bit
# ======================================================================
#
# Trabalham em cada posição de bit isoladamente, sem "vai um" entre elas.
#
#     AND   1 onde AMBOS têm 1        isola partes de um valor
#     OR    1 onde QUALQUER um tem 1  junta valores, liga bits
#     XOR   1 onde os dois DIFEREM    inverte bits, e zera um valor consigo
#     CPL   inverte o byte inteiro


def AND_A_r8(r8, cpu):
    """
    AND A, r8 — E lógico, bit a bit, entre o acumulador e um registrador.
    Cada bit do resultado só fica em 1 se estiver em 1 nos DOIS operandos. O uso
    mais comum é isolar parte de um valor: `AND A, 0x0F` descarta o nibble de cima
    e fica com o de baixo.
    FLAG_H liga sempre, e FLAG_C desliga sempre. Não há razão profunda — é assim no
    chip, e há teste que confere.
    """
    accumulator = cpu.reg8[A]
    register = cpu.reg8[r8]
    result = accumulator & register
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, True)
    cpu.setFlag(FLAG_C, False)


def AND_A_mHL(cpu):
    """AND A, [HL] — E lógico com o byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    accumulator = cpu.reg8[A]
    data = cpu.read8(register_hl)
    result = accumulator & data
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, True)
    cpu.setFlag(FLAG_C, False)


def AND_A_n8(cpu):
    """AND A, n8 — E lógico com um número escrito na instrução."""
    accumulator = cpu.reg8[A]
    data = cpu.fetch8()
    result = accumulator & data
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, True)
    cpu.setFlag(FLAG_C, False)


def CPL(cpu):
    """
    CPL — inverte todos os bits do acumulador.
    `^ 0xFF` troca 1 por 0 e 0 por 1 em cada posição. Em aritmética de complemento
    de dois, inverter e somar 1 troca o sinal do número, então `CPL` seguido de
    `INC A` é como se nega um valor num processador que não tem instrução para isso.
    Z e C ficam intactas; N e H ligam sempre.
    """
    accumulator = cpu.reg8[A]
    cpu.reg8[A] = accumulator ^ 0xFF  # XOR com todos os bits em 1 inverte o valor
    cpu.setFlag(FLAG_N, True)
    cpu.setFlag(FLAG_H, True)


def OR_A_r8(r8, cpu):
    """
    OR A, r8 — OU lógico, bit a bit.
    Cada bit fica em 1 se estiver em 1 em QUALQUER um dos operandos. Serve para
    juntar valores e para ligar bits sem tocar nos demais.
    """
    accumulator = cpu.reg8[A]
    register = cpu.reg8[r8]
    result = accumulator | register
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, False)


def OR_A_mHL(cpu):
    """OR A, [HL] — OU lógico com o byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    accumulator = cpu.reg8[A]
    data = cpu.read8(register_hl)
    result = accumulator | data
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, False)


def OR_A_n8(cpu):
    """OR A, n8 — OU lógico com um número escrito na instrução."""
    accumulator = cpu.reg8[A]
    data = cpu.fetch8()
    result = accumulator | data
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, False)


def XOR_A_r8(r8, cpu):
    """
    XOR A, r8 — OU exclusivo, bit a bit.
    Cada bit fica em 1 quando os operandos DIFEREM naquela posição. Um valor com
    ele mesmo dá sempre zero, e daí vem o truque mais visto em ROMs de Game Boy:
    `XOR A, A` zera o acumulador em um byte e um M-cycle, contra os dois bytes de
    um `LD A, 0`. Ainda de brinde, liga a flag Z.
    """
    accumulator = cpu.reg8[A]
    register = cpu.reg8[r8]
    result = accumulator ^ register
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, False)


def XOR_A_mHL(cpu):
    """XOR A, [HL] — OU exclusivo com o byte que HL aponta."""
    register_hl = cpu.reg16[HL]
    accumulator = cpu.reg8[A]
    data = cpu.read8(register_hl)
    result = accumulator ^ data
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, False)


def XOR_A_n8(cpu):
    """XOR A, n8 — OU exclusivo com um número escrito na instrução."""
    accumulator = cpu.reg8[A]
    data = cpu.fetch8()
    result = accumulator ^ data
    cpu.reg8[A] = result
    cpu.setFlag(FLAG_Z, result == 0)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, False)


def CCF(cpu):
    """CCF — inverte a flag de carry."""
    current_carry = cpu.getFlag(FLAG_C)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, not current_carry)


def SCF(cpu):
    """
    SCF — liga a flag de carry.
    Costuma aparecer antes de uma sequência de rotações que precisam começar com um
    1 entrando pela direita.
    """
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, False)
    cpu.setFlag(FLAG_C, True)


# ======================================================================
#  CONTROLE DA CPU — interrupções, sono, e a instrução mais estranha
# ======================================================================
#
# Este grupo não calcula nada: mexe no comportamento do próprio processador.
# São poucas instruções, e três delas concentram a maior parte das
# dificuldades de um emulador — o atraso do EI, o bug do HALT e a lógica da
# DAA.


def NOP(cpu):
    """
    NOP — não faz nada, e gasta 1 M-cycle fazendo isso.
    A instrução mais simples que existe, e não é inútil. Serve para ajustar o tempo
    de uma rotina que precisa durar um número exato de ciclos, e para reservar
    espaço que outro trecho de código vai sobrescrever depois.
    O corpo vazio não é esquecimento: o M-cycle já foi cobrado na busca do próprio
    opcode, em `fetch8`.
    """


def DI(cpu):
    """
    DI — desliga as interrupções na hora, sem atraso nenhum.
    Usada para proteger um trecho que não pode ser interrompido no meio, como a
    atualização de uma variável de 16 bits: se uma interrupção caísse entre a
    escrita dos dois bytes, quem lesse encontraria metade do valor novo e metade do
    velho.
    Note o contraste com o EI, logo abaixo, que tem um atraso de uma instrução.
    Desligar é imediato; ligar, não.
    """
    cpu.ime = False
    cpu.ime_pending = False   # cancela um EI que ainda não tinha "pegado"


def EI(cpu):
    """
    EI — religa as interrupções, mas só depois da PRÓXIMA instrução.
    O atraso é do chip real e não é capricho. Ele existe para que o par `EI; RET`,
    no fim de uma rotina de tratamento, execute o RET antes de qualquer interrupção
    nova ser atendida. Sem isso, uma interrupção poderia entrar entre as duas
    instruções e empilhar mais um endereço de retorno; repetido o bastante, a pilha
    cresce até invadir os dados do jogo.
    Quem cumpre o atraso é `CPU.step`, através do campo `ime_pending`.
    """
    # Só agenda. Quem liga o IME de fato, uma instrução depois, é o CPU.step.
    cpu.ime_pending = True


def HALT(cpu):
    """
    HALT — para a CPU até que alguma interrupção aconteça.
    Esta é a instrução que mantém a pilha do Game Boy durando trinta horas. Em vez
    de gastar ciclos num laço vazio esperando a tela terminar de desenhar, o jogo
    manda HALT e o processador simplesmente desliga; o resto do console continua
    andando, e a interrupção de V-Blank o acorda. Num jogo típico, a CPU passa a
    maior parte do tempo parada aqui.
    Os três caminhos abaixo têm um caso esquisito no meio. Com as interrupções
    desligadas E uma interrupção já pendente, o chip original NÃO para — em vez
    disso, ele executa a próxima instrução duas vezes. É o bug do HALT, e está
    descrito em detalhe em `CPU.fetch8`. A ROM `halt_bug.gb` existe só para
    verificar se um emulador o reproduz.
    """
    if cpu.ime:
        cpu.halted = True
    elif cpu.bus.ie & cpu.bus.if_ & 0x1F:
        cpu.halt_bug = True       # não dorme, e o próximo fetch não avança o PC
    else:
        cpu.halted = True


def STOP(cpu):
    """
    STOP — congela o console inteiro, tela incluída.
    Só o joypad acorda. Poucos jogos usam; no Game Boy Color a mesma instrução
    serve para trocar a velocidade do processador.
    Duas esquisitices no código. O PC avança um byte a mais porque o STOP é seguido
    de um byte que o hardware ignora — na prática é uma instrução de dois bytes com
    metade sem uso. E o DIV é zerado, o que pode disparar um incremento no TIMA
    como efeito colateral; o motivo dessa reação em cadeia está em `timer.py`.
    """
    # O STOP ocupa dois bytes, e o segundo é ignorado pelo hardware — nem chega
    # a ser buscado, por isso o PC avança sem custar M-cycle nenhum.
    cpu.reg16[PC] = (cpu.reg16[PC] + 1) & 0xFFFF
    cpu.stopped = True
    # Zerar o DIV pode incrementar o TIMA de tabela. Ver timer.py.
    cpu.bus.timer.escrever_div()


def DAA(cpu):
    """
    DAA — corrige o acumulador para que ele volte a fazer sentido em decimal.
    Esta é a instrução mais estranha do conjunto, e existe por um motivo bem
    concreto: mostrar a pontuação na tela.
    Um byte guarda de 0 a 255, mas nada impede um programa de tratar cada nibble
    como um DÍGITO DECIMAL. Nessa convenção — chamada BCD — o byte 0x42 representa
    o número quarenta e dois, e não sessenta e seis. A vantagem é que exibir o valor
    fica trivial: cada nibble já é o dígito a desenhar, sem divisões por 10, que o
    SM83 não sabe fazer.
    O problema aparece na soma. Somando 0x08 e 0x08, o processador devolve 0x10,
    porque ele soma em binário. Em BCD, 8 + 8 deveria dar 0x16. O resultado ficou
    6 a menos, e a correção é somar 0x06 — que é exatamente o que a DAA faz.
    Como ela sabe que precisa corrigir? Pelas flags que a operação anterior deixou.
    FLAG_H avisa que houve "vai um" do nibble de baixo, FLAG_C que houve do byte
    inteiro, e FLAG_N se a operação foi soma ou subtração — porque a correção tem
    sinal contrário nos dois casos. São essas três flags, aparentemente inúteis, que
    tornam a DAA possível.
    A flag C tem uma regra própria aqui: uma vez ligada pela correção, ela não é
    desligada, para que uma cadeia de somas BCD de vários bytes funcione.
    """
    a = cpu.reg8[A]
    adjust = 0
    carry_out = False

    # Depois de uma SOMA: a correção também soma.
    if not cpu.getFlag(FLAG_N):
        # Nibble de baixo acima de 9 (ou com vai-um): não é dígito decimal válido.
        if cpu.getFlag(FLAG_H) or (a & 0x0F) > 0x09:
            adjust |= 0x06
        # Mesma coisa no nibble de cima, e aí o resultado passou de 99.
        if cpu.getFlag(FLAG_C) or a > 0x99:
            adjust |= 0x60
            carry_out = True
        a = (a + adjust) & 0xFF

    # Depois de uma SUBTRAÇÃO: a correção subtrai. É para isto que FLAG_N serve.
    else:
        if cpu.getFlag(FLAG_H):
            a = (a - 0x06) & 0xFF
        if cpu.getFlag(FLAG_C):
            a = (a - 0x60) & 0xFF
            carry_out = True

    cpu.reg8[A] = a
    cpu.setFlag(FLAG_Z, a == 0)
    cpu.setFlag(FLAG_H, False)

    # C só é ligada, nunca desligada: uma cadeia de somas BCD depende disso.
    if carry_out:
        cpu.setFlag(FLAG_C, True)


# ======================================================================
#  DESVIOS ABSOLUTOS — o destino vem por extenso
# ======================================================================
#
# Um desvio é simplesmente escrever no PC. Como o PC guarda de onde vem a
# próxima instrução, trocar seu valor muda o rumo da execução — não existe
# outro mecanismo por trás disso.
#
# As versões condicionais recebem a condição JÁ RESOLVIDA, como True ou False.
# Quem lê a flag é a tabela de despacho no fim do arquivo, e não a função.

def JP_n16(cpu):
    """
    JP n16 — pula para um endereço, escrito por extenso na instrução.
    Escrever no PC É o pulo: como o PC guarda "de onde vem a próxima instrução",
    trocar seu valor faz a execução continuar em outro lugar. Não existe mecanismo
    além disso.
    O `tick4()` extra é um M-cycle interno que o chip gasta ajustando o ponteiro,
    levando a instrução a 4 M-cycles no total. Sem ele o emulador roda os jogos
    igual, e falha nos testes de temporização.
    """
    address = cpu.fetch16()
    cpu.reg16[PC] = address
    cpu.bus.tick4()

def JP_cc_n16(condition, cpu):
    """
    JP cc, n16 — pula só se a condição for verdadeira.
    A condição chega já resolvida em `condition`, como True ou False: quem a
    avaliou foi a tabela de despacho, lendo a flag apropriada. Ver o fim do arquivo.
    O detalhe que costuma passar batido é o custo. O endereço é lido dos dois jeitos
    — pulando ou não —, então a instrução nunca custa menos de 3 M-cycles. O quarto
    só é cobrado quando o pulo acontece de fato. Uma instrução com duas durações
    diferentes conforme o resultado é o tipo de coisa que separa um emulador que
    roda de um emulador correto.
    """
    address = cpu.fetch16()
    if condition:
        cpu.reg16[PC] = address
        cpu.bus.tick4()      # ciclo interno extra só quando o pulo acontece (16T vs 12T)

def JP_HL(cpu):
    """
    JP HL — pula para o endereço que está em HL.
    A mais rápida de todas: 1 M-cycle, sem leitura nenhuma, porque o destino já
    está dentro do processador.
    É com ela que se monta uma tabela de saltos — o `switch` do assembly. O programa
    calcula um índice, soma à base da tabela, carrega o endereço em HL e pula. Menus
    e máquinas de estado de jogos inteiros são feitos assim.
    """
    cpu.reg16[PC] = cpu.reg16[HL]


# ======================================================================
#  DESVIOS RELATIVOS — o destino é contado a partir daqui
# ======================================================================
#
# Em vez de um endereço de 16 bits, carregam um deslocamento de 8 bits com
# sinal: de -128 a +127 bytes. Ocupam dois bytes em vez de três.
#
# A economia parece pequena até lembrar que um banco de ROM tem 32 KB e que
# desvio é a instrução mais comum depois da cópia. A limitação é o alcance:
# para chegar mais longe, só com JP.

def JR_e8(cpu):
    """
    JR e8 — pula para perto, contando a partir da posição atual.
    Enquanto o JP carrega um endereço completo de 16 bits, o JR carrega um
    deslocamento de 8 bits COM SINAL: de -128 a +127 bytes a partir da instrução
    seguinte. Ocupa dois bytes em vez de três, e num console com 32 KB de ROM por
    banco essa economia importa.
    A conversão de sinal é a parte que merece atenção. O `fetch8` devolve um número
    de 0 a 255, sem noção de negativo. A convenção do complemento de dois diz que
    valores acima de 127 representam números negativos, e subtrair 256 faz a
    tradução: 0xFF, que chega como 255, vira -1.
    Como o PC já avançou para depois do operando quando a soma acontece, o
    deslocamento é contado a partir da PRÓXIMA instrução — e não da atual.
    """
    offset = cpu.fetch8()

    # Complemento de dois: acima de 127, o número é negativo. 0xFF vira -1.
    if offset > 127:
        offset -= 256

    cpu.reg16[PC] = (cpu.reg16[PC] + offset) & 0xFFFF
    cpu.bus.tick4()

def JR_cc_e8(condition, cpu):
    """
    JR cc, e8 — pulo curto condicional. O laço mais comum do Game Boy.
    `DEC B` seguido de `JR NZ, -4` é o "repita até zerar" de praticamente todo
    código escrito para o console.
    Como no JP condicional, a duração muda: 2 M-cycles quando não pula, 3 quando
    pula.
    """
    offset = cpu.fetch8()
    if condition:
        if offset > 127:
            offset -= 256
        cpu.reg16[PC] = (cpu.reg16[PC] + offset) & 0xFFFF
        cpu.bus.tick4()      # ciclo interno do cálculo do endereço (12T vs 8T)

# ======================================================================
#  SUB-ROTINAS — chamar e voltar
# ======================================================================
#
# CALL é um desvio que anota o caminho de volta. Ele empilha o endereço da
# instrução seguinte e salta; o RET lá dentro desempilha esse endereço e a
# execução continua de onde parou.
#
# Toda a mecânica de funções de qualquer linguagem, inclusive Python, é feita
# em cima deste par. E a fragilidade também é a mesma: se a sub-rotina empilhar
# algo e esquecer de desempilhar, o RET volta para um endereço errado.

def CALL_n16(cpu):
    """
    CALL n16 — chama uma sub-rotina.
    Um pulo que deixa o caminho de volta anotado. A instrução empilha o endereço
    seguinte ao CALL e só então salta; um RET lá dentro desempilha esse endereço e a
    execução continua de onde parou.
    É esse par que permite chamar uma função de vários lugares diferentes e voltar
    sempre para o lugar certo. O preço é que a pilha precisa estar em ordem: uma
    sub-rotina que empilhe algo e esqueça de desempilhar faz o RET voltar para um
    endereço errado, com resultado imprevisível.
    O `cpu.reg16[PC]` empilhado já aponta para depois do operando de 16 bits, porque
    o `fetch16` acima avançou o ponteiro.
    """
    address = cpu.fetch16()

    # Ciclo interno, antes de qualquer escrita
    cpu.bus.tick4()

    # O PC já aponta para depois do operando: é este o endereço de volta
    cpu.push16(cpu.reg16[PC])
    cpu.reg16[PC] = address

def CALL_cc_n16(condition, cpu):
    """
    CALL cc, n16 — chama a sub-rotina só se a condição for verdadeira.
    3 M-cycles quando não chama, 6 quando chama.
    """
    address = cpu.fetch16()
    if condition:
        cpu.bus.tick4()              # ciclo interno (decremento do SP) — 24T vs 12T
        cpu.push16(cpu.reg16[PC])
        cpu.reg16[PC] = address


def RET(cpu):
    """
    RET — volta de uma sub-rotina.
    Desempilha um endereço e o coloca no PC. O código está escrito à mão em vez de
    chamar `cpu.pop16()` porque o RET não dispara a corrupção da OAM que o POP
    dispara — e o `pop16` a dispara.
    """
    # Escrito à mão, e não com cpu.pop16(), porque o RET não dispara a
    low = cpu.read8(cpu.reg16[SP])
    cpu.reg16[SP] = (cpu.reg16[SP] + 1) & 0xFFFF

    # corrupção da OAM que o POP dispara.
    high = cpu.read8(cpu.reg16[SP])
    cpu.reg16[SP] = (cpu.reg16[SP] + 1) & 0xFFFF
    cpu.reg16[PC] = (high << 8) | low
    cpu.bus.tick4()

def RET_cc(condition, cpu):
    """
    RET cc — volta só se a condição for verdadeira.
    Custa 2 M-cycles mesmo quando não volta, e 5 quando volta. O M-cycle a mais em
    relação ao RET simples é o tempo que o chip leva para consultar a flag: o
    `tick4()` inicial acontece ANTES do teste, e é cobrado de qualquer jeito.
    """
    # Este ciclo é cobrado mesmo quando a condição é falsa: é o tempo de consultar a flag.
    cpu.bus.tick4()                  # 8T quando não retorna
    if condition:
        cpu.reg16[PC] = cpu.pop16()
        cpu.bus.tick4()              # 20T quando retorna

def RETI(cpu):
    """
    RETI — volta de uma rotina de interrupção e religa as interrupções.
    Equivale a um `EI` seguido de `RET`, com uma diferença que importa: aqui não há
    atraso. O `ime` liga na hora, e não depois da próxima instrução.
    Faz sentido pela mecânica do atraso do EI, explicada lá. O propósito do atraso é
    garantir que o RET seguinte execute antes de qualquer interrupção nova. No RETI
    o retorno acontece dentro da própria instrução, então não há o que proteger.
    """
    low = cpu.read8(cpu.reg16[SP])
    cpu.reg16[SP] = (cpu.reg16[SP] + 1) & 0xFFFF
    high = cpu.read8(cpu.reg16[SP])
    cpu.reg16[SP] = (cpu.reg16[SP] + 1) & 0xFFFF
    cpu.reg16[PC] = (high << 8) | low

    # Sem o atraso do EI: aqui o retorno já aconteceu, não há o que proteger.
    cpu.ime = True
    cpu.ime_pending = False
    cpu.bus.tick4()


def RST_vec(vec, cpu):
    """
    RST — um CALL de um byte só, para oito endereços fixos.
    Os destinos possíveis são 0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30 e 0x38 — de
    8 em 8, no comecinho da memória. Como o destino está codificado no próprio
    opcode, a instrução ocupa um byte contra os três de um CALL.
    Servia para as rotinas mais chamadas do jogo, que ganhavam um dos oito endereços
    e passavam a ser invocadas pela metade do custo. Com 32 KB por banco de ROM,
    economizar dois bytes numa chamada feita quinhentas vezes é economizar mil bytes.
    """
    cpu.bus.tick4()              # ciclo interno (decremento do SP)
    cpu.push16(cpu.reg16[PC])    # empilha o endereço de retorno
    cpu.reg16[PC] = vec


# ======================================================================
#  CARGAS — mover dados de um lugar para outro
# ======================================================================
#
# Mais da metade da tabela de opcodes é isto aqui, e a razão é a arquitetura:
# como só o acumulador faz conta, quase toda operação começa e termina com
# uma cópia.
#
# LD é de "load", e a seta vai da direita para a esquerda: `LD A, B` copia B
# PARA A. Colchetes significam "o conteúdo do endereço", então `LD A, [HL]`
# lê da memória, enquanto `LD A, H` lê de um registrador.
#
# As variantes com HL+ e HL- juntam a cópia com o avanço do ponteiro, o que
# torna a cópia de blocos bem mais barata. As variantes LDH encurtam o acesso
# aos registradores de hardware da faixa FF00-FFFF.


def LD_r8_r8(r81, r82, cpu):
    """
    LD r8, r8 — copia um registrador para outro.
    A instrução mais frequente de qualquer programa do console, e ocupa quase um
    quarto da tabela de opcodes: são 49 combinações de origem e destino.
    Tanta cópia existe porque o SM83 só faz conta no acumulador. Somar B com C exige
    copiar um deles para A, somar, e copiar o resultado de volta.
    """
    cpu.reg8[r81] = cpu.reg8[r82]


def LD_r8_n8(r8, cpu):
    """
    LD r8, n8 — coloca no registrador um número escrito na própria instrução.
    O número está gravado na ROM logo depois do opcode. Instruções assim se chamam
    "imediatas", porque o valor vem junto em vez de ser buscado em outro lugar.
    """
    cpu.reg8[r8] = cpu.fetch8()


def LD_r16_n16(r16, cpu):
    """
    LD r16, n16 — coloca num par de registradores um valor de 16 bits.
    É assim que um ponteiro é inicializado: `LD HL, $8000` deixa HL apontando para o
    começo da memória de vídeo. Três bytes, 3 M-cycles.
    """
    cpu.reg16[r16] = cpu.fetch16()


def LD_mHL_r8(r8, cpu):
    """
    LD [HL], r8 — grava um registrador na memória, no endereço que HL aponta.
    Os colchetes na notação significam "o conteúdo do endereço". `LD HL, $8000`
    mexe no ponteiro; `LD [HL], A` mexe na memória apontada por ele.
    """
    cpu.write8(cpu.reg16[HL], cpu.reg8[r8])


def LD_mHL_n8(cpu):
    """LD [HL], n8 — grava na memória um número escrito na instrução."""
    cpu.write8(cpu.reg16[HL], cpu.fetch8())


def LD_r8_mHL(r8, cpu):
    """LD r8, [HL] — lê da memória para um registrador."""
    cpu.reg8[r8] = cpu.read8(cpu.reg16[HL])


def LD_mR16_A(r16, cpu):
    """
    LD [r16], A — grava o acumulador no endereço apontado por um par.
    Só BC e DE aparecem aqui; HL tem instruções próprias, com mais variantes.
    """
    cpu.write8(cpu.reg16[r16], cpu.reg8[A])


def LD_mN16_A(cpu):
    """
    LD [n16], A — grava o acumulador num endereço escrito por extenso.
    A carga mais cara do conjunto: quatro bytes de instrução e 4 M-cycles. Vale
    quando o endereço é fixo e conhecido na hora de escrever o programa.
    """
    cpu.write8(cpu.fetch16(), cpu.reg8[A])


def LDH_mN8_A(cpu):
    """
    LDH [n8], A — grava o acumulador num registrador de hardware.
    A faixa FF00-FFFF é onde moram os controles do console: o registrador de vídeo,
    os do som, o do joypad, os do timer. Como todos começam com FF, guardar o byte
    alto seria desperdício — a instrução carrega só o de baixo e o `0xFF00 |` monta
    o endereço completo.
    Dois bytes em vez de três, e 2 M-cycles em vez de 4. Numa rotina de V-Blank, que
    roda sessenta vezes por segundo e mexe em vários desses registradores, a
    diferença é real.
    O H do nome é de "high", pela metade alta do mapa de memória.
    """
    address = 0xFF00 | cpu.fetch8()
    cpu.write8(address, cpu.reg8[A])


def LDH_mC_A(cpu):
    """
    LDH [C], A — grava o acumulador em FF00 mais o valor de C.
    A mesma ideia do LDH, com o endereço vindo de um registrador em vez de estar
    fixo na instrução. Serve para percorrer registradores de hardware em sequência —
    carregar as 32 posições da tabela de som, por exemplo, com C andando num laço.
    Ocupa um byte só.
    """
    cpu.write8(0xFF00 | cpu.reg8[C], cpu.reg8[A])


def LD_A_mR16(r16, cpu):
    """LD A, [r16] — lê para o acumulador o byte apontado por um par."""
    cpu.reg8[A] = cpu.read8(cpu.reg16[r16])


def LD_A_mN16(cpu):
    """LD A, [n16] — lê para o acumulador o byte de um endereço escrito por extenso."""
    cpu.reg8[A] = cpu.read8(cpu.fetch16())


def LDH_A_mC(cpu):
    """LDH A, [C] — lê para o acumulador o byte em FF00 mais o valor de C."""
    cpu.reg8[A] = cpu.read8(0xFF00 | cpu.reg8[C])


def LD_mHLI_A(cpu):
    """
    LD [HL+], A — grava o acumulador e depois avança HL.
    Copiar um bloco de memória é a tarefa mais comum de um jogo: mandar gráficos
    para a VRAM, mover tabelas de sprite. Sem esta instrução, cada byte custaria uma
    gravação mais um `INC HL`. Aqui as duas coisas vêm juntas, de graça.
    O `+` no nome se refere ao que acontece DEPOIS da gravação: o valor antigo de HL
    é usado, e só então o ponteiro anda.
    A chamada a `_talvez_corromper_oam` está no meio porque a corrupção depende do
    endereço ANTES do incremento.
    """
    register = cpu.reg16[HL]
    cpu.write8(register, cpu.reg8[A])
    _talvez_corromper_oam(cpu, register)     # o HL++ também mexe no barramento
    cpu.reg16[HL] = (register + 1) & 0xFFFF


def LD_mHLD_A(cpu):
    """
    LD [HL-], A — grava o acumulador e depois recua HL.
    A versão decrescente. Preencher uma região de trás para frente tem uma vantagem
    sutil: chegar a zero liga a flag Z sozinha, e o laço termina sem precisar de uma
    comparação.
    """
    register = cpu.reg16[HL]
    cpu.write8(register, cpu.reg8[A])
    _talvez_corromper_oam(cpu, register)
    cpu.reg16[HL] = (register - 1) & 0xFFFF


def LD_A_mHLI(cpu):
    """
    LD A, [HL+] — lê para o acumulador e depois avança HL.
    O outro lado da cópia de blocos: um par `LD A, [HL+]` e `LD [DE], A` move um
    byte por vez com o ponteiro de origem andando sozinho.
    """
    register = cpu.reg16[HL]
    cpu.reg8[A] = cpu.read8(register)
    _corromper_oam_leitura(cpu, register)    # lê e SÓ DEPOIS incrementa
    cpu.reg16[HL] = (register + 1) & 0xFFFF


def LD_A_mHLD(cpu):
    """LD A, [HL-] — lê para o acumulador e depois recua HL."""
    register = cpu.reg16[HL]
    cpu.reg8[A] = cpu.read8(register)
    _corromper_oam_leitura(cpu, register)
    cpu.reg16[HL] = (register - 1) & 0xFFFF


def LDH_A_mN8(cpu):
    """LDH A, [n8] — lê um registrador de hardware para o acumulador."""
    address = 0xFF00 | cpu.fetch8()
    cpu.reg8[A] = cpu.read8(address)


# ======================================================================
#  PILHA E PONTEIRO DE PILHA
# ======================================================================
#
# A pilha é uma região de memória que cresce PARA BAIXO, apontada pelo SP.
# Guarda endereços de retorno de sub-rotinas e valores que precisam
# sobreviver a uma chamada.
#
# As instruções abaixo dividem-se em duas ideias. PUSH e POP movem valores de
# 16 bits para dentro e para fora da pilha. As que mexem no SP diretamente —
# ADD SP e LD HL, SP+e8 — servem para reservar espaço, e são a coisa mais
# próxima de uma variável local que o processador oferece.
#
# Essas duas últimas têm uma regra de flags que parece errada à primeira
# vista, e não é. Está explicada em LD_HL_SP_e8.


def ADD_HL_SP(cpu):
    """
    ADD HL, SP — soma o ponteiro de pilha em HL.
    Idêntica à ADD HL, r16, e existe separada só porque o SP não faz parte da mesma
    numeração de registradores usada pelas outras.
    """
    hl = cpu.reg16[HL]
    sp = cpu.reg16[SP]
    result = (hl + sp) & 0xFFFF
    cpu.reg16[HL] = result
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, (hl & 0xFFF) + (sp & 0xFFF) > 0xFFF)
    cpu.setFlag(FLAG_C, (hl + sp) > 0xFFFF)
    cpu.bus.tick4()


def ADD_SP_e8(cpu):
    """
    ADD SP, e8 — soma um deslocamento com sinal ao ponteiro de pilha.
    Move a pilha inteira, ao contrário da LD HL, SP+e8, que só calcula um endereço.
    É como uma sub-rotina reserva ou devolve espaço para suas variáveis locais.
    As mesmas regras de flag da LD HL, SP+e8 valem aqui, incluindo o Z sempre
    desligado. Os dois `tick4()` são M-cycles internos: a instrução custa 4 no total,
    uma das mais lentas do conjunto.
    """
    e8 = cpu.fetch8()
    signed_e8 = e8 - 256 if e8 > 127 else e8
    sp = cpu.reg16[SP]
    result = (sp + signed_e8) & 0xFFFF
    cpu.reg16[SP] = result
    cpu.setFlag(FLAG_Z, False)
    cpu.setFlag(FLAG_N, False)
    # H e C saem dos 8 bits DE BAIXO, com o valor sem sinal. É assim no chip.
    cpu.setFlag(FLAG_H, (sp & 0xF) + (e8 & 0xF) > 0xF)
    cpu.setFlag(FLAG_C, (sp & 0xFF) + e8 > 0xFF)
    cpu.bus.tick4()
    cpu.bus.tick4()


def DEC_SP(cpu):
    """DEC SP — subtrai 1 do ponteiro de pilha. Sem flags."""
    cpu.reg16[SP] = (cpu.reg16[SP] - 1) & 0xFFFF


def INC_SP(cpu):
    """INC SP — soma 1 ao ponteiro de pilha. Sem flags."""
    cpu.reg16[SP] = (cpu.reg16[SP] + 1) & 0xFFFF


def LD_SP_n16(cpu):
    """
    LD SP, n16 — posiciona o ponteiro de pilha.
    Uma das primeiras coisas que todo jogo faz. O valor de praxe é 0xFFFE, o topo da
    memória interna: como a pilha cresce para baixo, começar no fim dá o máximo de
    espaço antes de ela colidir com os dados.
    """
    cpu.reg16[SP] = cpu.fetch16()


def LD_mN16_SP(cpu):
    """
    LD [n16], SP — grava o ponteiro de pilha na memória, em dois bytes.
    Byte baixo primeiro, byte alto no endereço seguinte, seguindo a convenção
    little-endian do processador. Cinco M-cycles, a instrução mais lenta do conjunto
    básico.
    """
    address = cpu.fetch16()
    sp = cpu.reg16[SP]

    # Byte baixo primeiro (little-endian)
    cpu.write8(address, sp & 0xFF)
    cpu.write8((address + 1) & 0xFFFF, (sp >> 8) & 0xFF)


def LD_HL_SP_e8(cpu):
    """
    LD HL, SP+e8 — calcula um endereço perto do topo da pilha.
    Aqui está a instrução mais próxima que o SM83 tem de uma variável local. Uma
    sub-rotina reserva espaço na pilha, e esta instrução dá o endereço de um item
    desse espaço sem gastar o SP.
    As flags saem de uma regra que parece errada e não é: embora a conta seja de
    16 bits, H e C são calculadas sobre os 8 bits DE BAIXO, como se fosse uma soma
    de bytes. E a flag Z desliga sempre, mesmo que o resultado dê zero. O motivo é
    elétrico — internamente o chip faz a soma em duas metades, e as flags refletem
    só a primeira.
    `(e8 & 0xF)` e `(sp & 0xFF)` usam o valor SEM sinal de propósito, apesar de a
    soma usar a versão com sinal. Também é assim no hardware.
    """
    e8 = cpu.fetch8()
    signed_e8 = e8 - 256 if e8 > 127 else e8
    sp = cpu.reg16[SP]
    result = (sp + signed_e8) & 0xFFFF
    cpu.reg16[HL] = result
    cpu.setFlag(FLAG_Z, False)
    cpu.setFlag(FLAG_N, False)
    cpu.setFlag(FLAG_H, (sp & 0xF) + (e8 & 0xF) > 0xF)
    cpu.setFlag(FLAG_C, (sp & 0xFF) + e8 > 0xFF)
    cpu.bus.tick4()


def LD_SP_HL(cpu):
    """
    LD SP, HL — copia HL para o ponteiro de pilha.
    Serve para trocar de pilha, o que só faz sentido em código de sistema. Custa
    2 M-cycles: o segundo é interno, sem acesso à memória.
    """
    cpu.reg16[SP] = cpu.reg16[HL]
    cpu.bus.tick4()


def PUSH_r16(r16, cpu):
    """
    PUSH r16 — empilha um par de registradores.
    Serve para guardar um valor que a sub-rotina prestes a ser chamada vai destruir.
    O par `PUSH BC` no começo e `POP BC` no fim é a convenção de quem quer preservar
    um registrador entre chamadas.
    O `tick4()` inicial é um M-cycle interno gasto antes de a gravação começar,
    levando a instrução a 4 M-cycles.
    """
    cpu.bus.tick4()              # ciclo interno do decremento do SP
    cpu.push16(cpu.reg16[r16])   # High byte primeiro, depois o Low byte


def PUSH_AF(cpu):
    """
    PUSH AF — empilha o acumulador junto com as flags.
    Existe separada porque AF é o único par cujo empilhamento precisa cuidar dos
    quatro bits inexistentes de F. Rotinas de interrupção começam com PUSH AF e
    terminam com POP AF, para devolver o processador exatamente como o encontraram —
    inclusive as flags, que o código interrompido pode estar prestes a testar.
    """
    cpu.bus.tick4()                                  # ciclo interno do SP
    cpu.push16((cpu.reg8[A] << 8) | cpu.reg8[F])     # A = high, F = low


def POP_r16(r16, cpu):
    """
    POP r16 — desempilha para um par de registradores.
    A ordem importa: os POPs precisam vir na ordem inversa dos PUSHes. Empilhar BC e
    depois DE, e desempilhar BC antes de DE, troca os valores de lugar.
    """
    # Via cpu.pop16(), que além de desempilhar dispara o bug da OAM quando o
    # ponteiro passa pela faixa FE00-FEFF.
    cpu.reg16[r16] = cpu.pop16()


def POP_AF(cpu):
    """
    POP AF — desempilha para o acumulador e as flags.
    Passa por `cpu.write_af` em vez de escrever direto, porque os quatro bits de
    baixo de F não existem no chip e precisam ser zerados. Sem isso, um `PUSH AF`
    seguido de `POP AF` devolveria um valor que o console nunca devolveria — e há
    teste que confere exatamente essa sequência.
    """
    valor = cpu.pop16()

    # write_af zera os 4 bits de baixo de F, que não existem no chip.
    cpu.reg8[A] = (valor >> 8) & 0xFF
    cpu.reg8[F] = valor & 0xF0


# ======================================================================
#  AS TABELAS DE DESPACHO
# ======================================================================
#
# Aqui cada byte encontra a sua função. `CPU.step` lê um byte da ROM, usa esse
# byte como índice nesta lista, e chama o que encontrar:
#
#     self.opcode[opc](self)
#
# Decodificar uma instrução é, portanto, um acesso a uma lista. Não há cadeia
# de `if`, não há busca: o custo é o mesmo para o primeiro e para o último
# opcode. Uma tabela de 256 posições gasta alguns kilobytes de memória e
# devolve isso em velocidade a cada instrução executada — e são milhões por
# segundo.
#
# POR QUE OS LAMBDAS
#
# Uma função como `INC_r8` atende oito instruções diferentes, uma por
# registrador. O que muda entre elas é só um parâmetro:
#
#     opcode[0x04] = lambda cpu: INC_r8(B, cpu)    # INC B
#     opcode[0x0C] = lambda cpu: INC_r8(C, cpu)    # INC C
#
# O lambda embrulha a função com o parâmetro já preenchido, e o resultado é
# algo que se chama com `cpu` e mais nada. Todas as 512 posições ficam com a
# mesma forma, e `step` não precisa saber que INC e JP têm assinaturas
# diferentes.
#
# Nos desvios condicionais, o lambda faz mais do que preencher: ele AVALIA a
# condição no momento da chamada, e a função recebe True ou False já pronto.
#
#     opcode[0x20] = lambda cpu: JR_cc_e8(not cpu.getFlag(FLAG_Z), cpu)
#
# DUAS TABELAS
#
# `opcode` tem as 256 instruções diretas. `opcodeCB` tem as 256 que só são
# alcançadas depois do byte 0xCB — o prefixo que dobra o espaço disponível,
# explicado no fim de `CPU.step`.
#
# As posições que sobram apontam para `opcode_invalido`. São onze bytes que
# não correspondem a instrução nenhuma e que, no chip real, travam o
# processador de vez.
#
# O comentário no fim de cada linha é o mnemônico — o nome legível da
# instrução, do jeito que apareceria num desmontador.

opcode: list[Callable | None] = [None] * 256
opcodeCB: list[Callable | None] = [None] * 256

opcode[0x00] = lambda cpu: NOP(cpu) # NOP
opcode[0x01] = lambda cpu: LD_r16_n16(BC, cpu) # LD BC, n16
opcode[0x02] = lambda cpu: LD_mR16_A(BC, cpu) # LD [BC], A
opcode[0x03] = lambda cpu: INC_r16(BC, cpu) # INC BC
opcode[0x04] = lambda cpu: INC_r8(B, cpu) # INC B
opcode[0x05] = lambda cpu: DEC_r8(B, cpu) # DEC B
opcode[0x06] = lambda cpu: LD_r8_n8(B, cpu) # LD B, n8
opcode[0x07] = lambda cpu: RLCA(cpu) # RLCA
opcode[0x08] = lambda cpu: LD_mN16_SP(cpu) # LD [a16], SP
opcode[0x09] = lambda cpu: ADD_HL_r16(BC, cpu) # ADD HL, BC
opcode[0x0A] = lambda cpu: LD_A_mR16(BC, cpu) # LD A, [BC]
opcode[0x0B] = lambda cpu: DEC_r16(BC, cpu) # DEC BC
opcode[0x0C] = lambda cpu: INC_r8(C, cpu) # INC C
opcode[0x0D] = lambda cpu: DEC_r8(C, cpu) # DEC C
opcode[0x0E] = lambda cpu: LD_r8_n8(C, cpu) # LD C, n8
opcode[0x0F] = lambda cpu: RRCA(cpu) # RRCA

opcode[0x10] = lambda cpu: STOP(cpu) # STOP n8
opcode[0x11] = lambda cpu: LD_r16_n16(DE, cpu) # LD DE, n16
opcode[0x12] = lambda cpu: LD_mR16_A(DE, cpu) # LD [DE], A
opcode[0x13] = lambda cpu: INC_r16(DE, cpu) # INC DE
opcode[0x14] = lambda cpu: INC_r8(D, cpu) # INC D
opcode[0x15] = lambda cpu: DEC_r8(D, cpu) # DEC D
opcode[0x16] = lambda cpu: LD_r8_n8(D, cpu) # LD D, n8
opcode[0x17] = lambda cpu: RLA(cpu) # RLA
opcode[0x18] = lambda cpu: JR_e8(cpu) # JR e8
opcode[0x19] = lambda cpu: ADD_HL_r16(DE, cpu) # ADD HL, DE
opcode[0x1A] = lambda cpu: LD_A_mR16(DE, cpu) # LD A, [DE]
opcode[0x1B] = lambda cpu: DEC_r16(DE, cpu) # DEC DE
opcode[0x1C] = lambda cpu: INC_r8(E, cpu) # INC E
opcode[0x1D] = lambda cpu: DEC_r8(E, cpu) # DEC E
opcode[0x1E] = lambda cpu: LD_r8_n8(E, cpu) # LD E, n8
opcode[0x1F] = lambda cpu: RRA(cpu) # RRA

opcode[0x20] = lambda cpu: JR_cc_e8(not cpu.getFlag(FLAG_Z), cpu) # JR NZ, e8
opcode[0x21] = lambda cpu: LD_r16_n16(HL, cpu) # LD HL, n16
opcode[0x22] = lambda cpu: LD_mHLI_A(cpu) # LD [HL+], A
opcode[0x23] = lambda cpu: INC_r16(HL, cpu) # INC HL
opcode[0x24] = lambda cpu: INC_r8(H, cpu) # INC H
opcode[0x25] = lambda cpu: DEC_r8(H, cpu) # DEC H
opcode[0x26] = lambda cpu: LD_r8_n8(H, cpu) # LD H, n8
opcode[0x27] = lambda cpu: DAA(cpu) # DAA
opcode[0x28] = lambda cpu: JR_cc_e8(cpu.getFlag(FLAG_Z), cpu) # JR Z, e8
opcode[0x29] = lambda cpu: ADD_HL_r16(HL, cpu) # ADD HL, HL
opcode[0x2A] = lambda cpu: LD_A_mHLI(cpu) # LD A, [HL+]
opcode[0x2B] = lambda cpu: DEC_r16(HL, cpu) # DEC HL
opcode[0x2C] = lambda cpu: INC_r8(L, cpu) # INC L
opcode[0x2D] = lambda cpu: DEC_r8(L, cpu) # DEC L
opcode[0x2E] = lambda cpu: LD_r8_n8(L, cpu) # LD L, n8
opcode[0x2F] = lambda cpu: CPL(cpu) # CPL

opcode[0x30] = lambda cpu: JR_cc_e8(not cpu.getFlag(FLAG_C), cpu) # JR NC, e8
opcode[0x31] = lambda cpu: LD_r16_n16(SP, cpu) # LD SP, n16
opcode[0x32] = lambda cpu: LD_mHLD_A(cpu) # LD [HL-], A
opcode[0x33] = lambda cpu: INC_r16(SP, cpu) # INC SP
opcode[0x34] = lambda cpu: INC_mHL(cpu) # INC [HL]
opcode[0x35] = lambda cpu: DEC_mHL(cpu) # DEC [HL]
opcode[0x36] = lambda cpu: LD_mHL_n8(cpu) # LD [HL], n8
opcode[0x37] = lambda cpu: SCF(cpu) # SCF
opcode[0x38] = lambda cpu: JR_cc_e8(cpu.getFlag(FLAG_C), cpu) # JR C, e8
opcode[0x39] = lambda cpu: ADD_HL_SP(cpu) # ADD HL, SP
opcode[0x3A] = lambda cpu: LD_A_mHLD(cpu) # LD A, [HL-]
opcode[0x3B] = lambda cpu: DEC_r16(SP, cpu) # DEC SP
opcode[0x3C] = lambda cpu: INC_r8(A, cpu) # INC A
opcode[0x3D] = lambda cpu: DEC_r8(A, cpu) # DEC A
opcode[0x3E] = lambda cpu: LD_r8_n8(A, cpu) # LD A, n8
opcode[0x3F] = lambda cpu: CCF(cpu) # CCF

opcode[0x40] = lambda cpu: LD_r8_r8(B, B, cpu) # LD B, B
opcode[0x41] = lambda cpu: LD_r8_r8(B, C, cpu) # LD B, C
opcode[0x42] = lambda cpu: LD_r8_r8(B, D, cpu) # LD B, D
opcode[0x43] = lambda cpu: LD_r8_r8(B, E, cpu) # LD B, E
opcode[0x44] = lambda cpu: LD_r8_r8(B, H, cpu) # LD B, H
opcode[0x45] = lambda cpu: LD_r8_r8(B, L, cpu) # LD B, L
opcode[0x46] = lambda cpu: LD_r8_mHL(B, cpu) # LD B, [HL]
opcode[0x47] = lambda cpu: LD_r8_r8(B, A, cpu) # LD B, A
opcode[0x48] = lambda cpu: LD_r8_r8(C, B, cpu) # LD C, B
opcode[0x49] = lambda cpu: LD_r8_r8(C, C, cpu) # LD C, C
opcode[0x4A] = lambda cpu: LD_r8_r8(C, D, cpu) # LD C, D
opcode[0x4B] = lambda cpu: LD_r8_r8(C, E, cpu) # LD C, E
opcode[0x4C] = lambda cpu: LD_r8_r8(C, H, cpu) # LD C, H
opcode[0x4D] = lambda cpu: LD_r8_r8(C, L, cpu) # LD C, L
opcode[0x4E] = lambda cpu: LD_r8_mHL(C, cpu) # LD C, [HL]
opcode[0x4F] = lambda cpu: LD_r8_r8(C, A, cpu) # LD C, A

opcode[0x50] = lambda cpu: LD_r8_r8(D, B, cpu) # LD D, B
opcode[0x51] = lambda cpu: LD_r8_r8(D, C, cpu) # LD D, C
opcode[0x52] = lambda cpu: LD_r8_r8(D, D, cpu) # LD D, D
opcode[0x53] = lambda cpu: LD_r8_r8(D, E, cpu) # LD D, E
opcode[0x54] = lambda cpu: LD_r8_r8(D, H, cpu) # LD D, H
opcode[0x55] = lambda cpu: LD_r8_r8(D, L, cpu) # LD D, L
opcode[0x56] = lambda cpu: LD_r8_mHL(D, cpu) # LD D, [HL]
opcode[0x57] = lambda cpu: LD_r8_r8(D, A, cpu) # LD D, A
opcode[0x58] = lambda cpu: LD_r8_r8(E, B, cpu) # LD E, B
opcode[0x59] = lambda cpu: LD_r8_r8(E, C, cpu) # LD E, C
opcode[0x5A] = lambda cpu: LD_r8_r8(E, D, cpu) # LD E, D
opcode[0x5B] = lambda cpu: LD_r8_r8(E, E, cpu) # LD E, E
opcode[0x5C] = lambda cpu: LD_r8_r8(E, H, cpu) # LD E, H
opcode[0x5D] = lambda cpu: LD_r8_r8(E, L, cpu) # LD E, L
opcode[0x5E] = lambda cpu: LD_r8_mHL(E, cpu) # LD E, [HL]
opcode[0x5F] = lambda cpu: LD_r8_r8(E, A, cpu) # LD E, A

opcode[0x60] = lambda cpu: LD_r8_r8(H, B, cpu) # LD H, B
opcode[0x61] = lambda cpu: LD_r8_r8(H, C, cpu) # LD H, C
opcode[0x62] = lambda cpu: LD_r8_r8(H, D, cpu) # LD H, D
opcode[0x63] = lambda cpu: LD_r8_r8(H, E, cpu) # LD H, E
opcode[0x64] = lambda cpu: LD_r8_r8(H, H, cpu) # LD H, H
opcode[0x65] = lambda cpu: LD_r8_r8(H, L, cpu) # LD H, L
opcode[0x66] = lambda cpu: LD_r8_mHL(H, cpu) # LD H, [HL]
opcode[0x67] = lambda cpu: LD_r8_r8(H, A, cpu) # LD H, A
opcode[0x68] = lambda cpu: LD_r8_r8(L, B, cpu) # LD L, B
opcode[0x69] = lambda cpu: LD_r8_r8(L, C, cpu) # LD L, C
opcode[0x6A] = lambda cpu: LD_r8_r8(L, D, cpu) # LD L, D
opcode[0x6B] = lambda cpu: LD_r8_r8(L, E, cpu) # LD L, E
opcode[0x6C] = lambda cpu: LD_r8_r8(L, H, cpu) # LD L, H
opcode[0x6D] = lambda cpu: LD_r8_r8(L, L, cpu) # LD L, L
opcode[0x6E] = lambda cpu: LD_r8_mHL(L, cpu) # LD L, [HL]
opcode[0x6F] = lambda cpu: LD_r8_r8(L, A, cpu) # LD L, A

opcode[0x70] = lambda cpu: LD_mHL_r8(B, cpu) # LD [HL], B
opcode[0x71] = lambda cpu: LD_mHL_r8(C, cpu) # LD [HL], C
opcode[0x72] = lambda cpu: LD_mHL_r8(D, cpu) # LD [HL], D
opcode[0x73] = lambda cpu: LD_mHL_r8(E, cpu) # LD [HL], E
opcode[0x74] = lambda cpu: LD_mHL_r8(H, cpu) # LD [HL], H
opcode[0x75] = lambda cpu: LD_mHL_r8(L, cpu) # LD [HL], L
opcode[0x76] = lambda cpu: HALT(cpu) # HALT
opcode[0x77] = lambda cpu: LD_mHL_r8(A, cpu) # LD [HL], A
opcode[0x78] = lambda cpu: LD_r8_r8(A, B, cpu) # LD A, B
opcode[0x79] = lambda cpu: LD_r8_r8(A, C, cpu) # LD A, C
opcode[0x7A] = lambda cpu: LD_r8_r8(A, D, cpu) # LD A, D
opcode[0x7B] = lambda cpu: LD_r8_r8(A, E, cpu) # LD A, E
opcode[0x7C] = lambda cpu: LD_r8_r8(A, H, cpu) # LD A, H
opcode[0x7D] = lambda cpu: LD_r8_r8(A, L, cpu) # LD A, L
opcode[0x7E] = lambda cpu: LD_A_mR16(HL, cpu) # LD A, [HL]
opcode[0x7F] = lambda cpu: LD_r8_r8(A, A, cpu) # LD A, A

opcode[0x80] = lambda cpu: ADD_A_r8(B, cpu) # ADD A, B
opcode[0x81] = lambda cpu: ADD_A_r8(C, cpu) # ADD A, C
opcode[0x82] = lambda cpu: ADD_A_r8(D, cpu) # ADD A, D
opcode[0x83] = lambda cpu: ADD_A_r8(E, cpu) # ADD A, E
opcode[0x84] = lambda cpu: ADD_A_r8(H, cpu) # ADD A, H
opcode[0x85] = lambda cpu: ADD_A_r8(L, cpu) # ADD A, L
opcode[0x86] = lambda cpu: ADD_A_mHL(cpu) # ADD A, [HL]
opcode[0x87] = lambda cpu: ADD_A_r8(A, cpu) # ADD A, A
opcode[0x88] = lambda cpu: ADC_A_r8(B, cpu) # ADC A, B
opcode[0x89] = lambda cpu: ADC_A_r8(C, cpu) # ADC A, C
opcode[0x8A] = lambda cpu: ADC_A_r8(D, cpu) # ADC A, D
opcode[0x8B] = lambda cpu: ADC_A_r8(E, cpu) # ADC A, E
opcode[0x8C] = lambda cpu: ADC_A_r8(H, cpu) # ADC A, H
opcode[0x8D] = lambda cpu: ADC_A_r8(L, cpu) # ADC A, L
opcode[0x8E] = lambda cpu: ADC_A_mHL(cpu) # ADC A, [HL]
opcode[0x8F] = lambda cpu: ADC_A_r8(A, cpu) # ADC A, A

opcode[0x90] = lambda cpu: SUB_A_r8(B, cpu) # SUB A, B
opcode[0x91] = lambda cpu: SUB_A_r8(C, cpu) # SUB A, C
opcode[0x92] = lambda cpu: SUB_A_r8(D, cpu) # SUB A, D
opcode[0x93] = lambda cpu: SUB_A_r8(E, cpu) # SUB A, E
opcode[0x94] = lambda cpu: SUB_A_r8(H, cpu) # SUB A, H
opcode[0x95] = lambda cpu: SUB_A_r8(L, cpu) # SUB A, L
opcode[0x96] = lambda cpu: SUB_A_mHL(cpu) # SUB A, [HL]
opcode[0x97] = lambda cpu: SUB_A_r8(A, cpu) # SUB A, A
opcode[0x98] = lambda cpu: SBC_A_r8(B, cpu) # SBC A, B
opcode[0x99] = lambda cpu: SBC_A_r8(C, cpu) # SBC A, C
opcode[0x9A] = lambda cpu: SBC_A_r8(D, cpu) # SBC A, D
opcode[0x9B] = lambda cpu: SBC_A_r8(E, cpu) # SBC A, E
opcode[0x9C] = lambda cpu: SBC_A_r8(H, cpu) # SBC A, H
opcode[0x9D] = lambda cpu: SBC_A_r8(L, cpu) # SBC A, L
opcode[0x9E] = lambda cpu: SBC_A_mHL(cpu) # SBC A, [HL]
opcode[0x9F] = lambda cpu: SBC_A_r8(A, cpu) # SBC A, A

opcode[0xA0] = lambda cpu: AND_A_r8(B, cpu) # AND A, B
opcode[0xA1] = lambda cpu: AND_A_r8(C, cpu) # AND A, C
opcode[0xA2] = lambda cpu: AND_A_r8(D, cpu) # AND A, D
opcode[0xA3] = lambda cpu: AND_A_r8(E, cpu) # AND A, E
opcode[0xA4] = lambda cpu: AND_A_r8(H, cpu) # AND A, H
opcode[0xA5] = lambda cpu: AND_A_r8(L, cpu) # AND A, L
opcode[0xA6] = lambda cpu: AND_A_mHL(cpu) # AND A, [HL]
opcode[0xA7] = lambda cpu: AND_A_r8(A, cpu) # AND A, A
opcode[0xA8] = lambda cpu: XOR_A_r8(B, cpu) # XOR A, B
opcode[0xA9] = lambda cpu: XOR_A_r8(C, cpu) # XOR A, C
opcode[0xAA] = lambda cpu: XOR_A_r8(D, cpu) # XOR A, D
opcode[0xAB] = lambda cpu: XOR_A_r8(E, cpu) # XOR A, E
opcode[0xAC] = lambda cpu: XOR_A_r8(H, cpu) # XOR A, H
opcode[0xAD] = lambda cpu: XOR_A_r8(L, cpu) # XOR A, L
opcode[0xAE] = lambda cpu: XOR_A_mHL(cpu) # XOR A, [HL]
opcode[0xAF] = lambda cpu: XOR_A_r8(A, cpu) # XOR A, A

opcode[0xB0] = lambda cpu: OR_A_r8(B, cpu) # OR A, B
opcode[0xB1] = lambda cpu: OR_A_r8(C, cpu) # OR A, C
opcode[0xB2] = lambda cpu: OR_A_r8(D, cpu) # OR A, D
opcode[0xB3] = lambda cpu: OR_A_r8(E, cpu) # OR A, E
opcode[0xB4] = lambda cpu: OR_A_r8(H, cpu) # OR A, H
opcode[0xB5] = lambda cpu: OR_A_r8(L, cpu) # OR A, L
opcode[0xB6] = lambda cpu: OR_A_mHL(cpu) # OR A, [HL]
opcode[0xB7] = lambda cpu: OR_A_r8(A, cpu) # OR A, A
opcode[0xB8] = lambda cpu: CP_A_r8(B, cpu) # CP A, B
opcode[0xB9] = lambda cpu: CP_A_r8(C, cpu) # CP A, C
opcode[0xBA] = lambda cpu: CP_A_r8(D, cpu) # CP A, D
opcode[0xBB] = lambda cpu: CP_A_r8(E, cpu) # CP A, E
opcode[0xBC] = lambda cpu: CP_A_r8(H, cpu) # CP A, H
opcode[0xBD] = lambda cpu: CP_A_r8(L, cpu) # CP A, L
opcode[0xBE] = lambda cpu: CP_A_mHL(cpu) # CP A, [HL]
opcode[0xBF] = lambda cpu: CP_A_r8(A, cpu) # CP A, A

opcode[0xC0] = lambda cpu: RET_cc(not cpu.getFlag(FLAG_Z), cpu) # RET NZ
opcode[0xC1] = lambda cpu: POP_r16(BC, cpu) # POP BC
opcode[0xC2] = lambda cpu: JP_cc_n16(not cpu.getFlag(FLAG_Z), cpu) # JP NZ, a16
opcode[0xC3] = lambda cpu: JP_n16(cpu) # JP a16
opcode[0xC4] = lambda cpu: CALL_cc_n16(not cpu.getFlag(FLAG_Z), cpu) # CALL NZ, a16
opcode[0xC5] = lambda cpu: PUSH_r16(BC, cpu) # PUSH BC
opcode[0xC6] = lambda cpu: ADD_A_n8(cpu) # ADD A, n8
opcode[0xC7] = lambda cpu: RST_vec(0x00, cpu) # RST $00
opcode[0xC8] = lambda cpu: RET_cc(cpu.getFlag(FLAG_Z), cpu) # RET Z
opcode[0xC9] = lambda cpu: RET(cpu) # RET
opcode[0xCA] = lambda cpu: JP_cc_n16(cpu.getFlag(FLAG_Z), cpu) # JP Z, a16
opcode[0xCB] = lambda cpu: None # PREFIX CB
opcode[0xCC] = lambda cpu: CALL_cc_n16(cpu.getFlag(FLAG_Z), cpu) # CALL Z, a16
opcode[0xCD] = lambda cpu: CALL_n16(cpu) # CALL a16
opcode[0xCE] = lambda cpu: ADC_A_n8(cpu) # ADC A, n8
opcode[0xCF] = lambda cpu: RST_vec(0x08, cpu) # RST $08

opcode[0xD0] = lambda cpu: RET_cc(not cpu.getFlag(FLAG_C), cpu) # RET NC
opcode[0xD1] = lambda cpu: POP_r16(DE, cpu) # POP DE
opcode[0xD2] = lambda cpu: JP_cc_n16(not cpu.getFlag(FLAG_C), cpu) # JP NC, a16
opcode[0xD3] = lambda cpu: opcode_invalido(0xD3, cpu)  # (Opcode Inválido)
opcode[0xD4] = lambda cpu: CALL_cc_n16(not cpu.getFlag(FLAG_C), cpu) # CALL NC, a16
opcode[0xD5] = lambda cpu: PUSH_r16(DE, cpu) # PUSH DE
opcode[0xD6] = lambda cpu: SUB_A_n8(cpu) # SUB A, n8
opcode[0xD7] = lambda cpu: RST_vec(0x10, cpu) # RST $10
opcode[0xD8] = lambda cpu: RET_cc(cpu.getFlag(FLAG_C), cpu) # RET C
opcode[0xD9] = lambda cpu: RETI(cpu) # RETI
opcode[0xDA] = lambda cpu: JP_cc_n16(cpu.getFlag(FLAG_C), cpu) # JP C, a16
opcode[0xDB] = lambda cpu: opcode_invalido(0xDB, cpu)  # (Opcode Inválido)
opcode[0xDC] = lambda cpu: CALL_cc_n16(cpu.getFlag(FLAG_C), cpu) # CALL C, a16
opcode[0xDD] = lambda cpu: opcode_invalido(0xDD, cpu)  # (Opcode Inválido)
opcode[0xDE] = lambda cpu: SBC_A_n8(cpu) # SBC A, n8
opcode[0xDF] = lambda cpu: RST_vec(0x18, cpu) # RST $18

opcode[0xE0] = lambda cpu: LDH_mN8_A(cpu) # LDH [a8], A
opcode[0xE1] = lambda cpu: POP_r16(HL, cpu) # POP HL
opcode[0xE2] = lambda cpu: LDH_mC_A(cpu) # LDH [C], A
opcode[0xE3] = lambda cpu: opcode_invalido(0xE3, cpu)  # (Opcode Inválido)
opcode[0xE4] = lambda cpu: opcode_invalido(0xE4, cpu)  # (Opcode Inválido)
opcode[0xE5] = lambda cpu: PUSH_r16(HL, cpu) # PUSH HL
opcode[0xE6] = lambda cpu: AND_A_n8(cpu) # AND A, n8
opcode[0xE7] = lambda cpu: RST_vec(0x20, cpu) # RST $20
opcode[0xE8] = lambda cpu: ADD_SP_e8(cpu) # ADD SP, e8
opcode[0xE9] = lambda cpu: JP_HL(cpu) # JP HL
opcode[0xEA] = lambda cpu: LD_mN16_A(cpu) # LD [a16], A
opcode[0xEB] = lambda cpu: opcode_invalido(0xEB, cpu)  # (Opcode Inválido)
opcode[0xEC] = lambda cpu: opcode_invalido(0xEC, cpu)  # (Opcode Inválido)
opcode[0xED] = lambda cpu: opcode_invalido(0xED, cpu)  # (Opcode Inválido)
opcode[0xEE] = lambda cpu: XOR_A_n8(cpu) # XOR A, n8
opcode[0xEF] = lambda cpu: RST_vec(0x28, cpu) # RST $28

opcode[0xF0] = lambda cpu: LDH_A_mN8(cpu) # LDH A, [a8]
opcode[0xF1] = lambda cpu: POP_AF(cpu) # POP AF
opcode[0xF2] = lambda cpu: LDH_A_mC(cpu) # LDH A, [C]
opcode[0xF3] = lambda cpu: DI(cpu) # DI
opcode[0xF4] = lambda cpu: opcode_invalido(0xF4, cpu)  # (Opcode Inválido)
opcode[0xF5] = lambda cpu: PUSH_AF(cpu) # PUSH AF
opcode[0xF6] = lambda cpu: OR_A_n8(cpu) # OR A, n8
opcode[0xF7] = lambda cpu: RST_vec(0x30, cpu) # RST $30
opcode[0xF8] = lambda cpu: LD_HL_SP_e8(cpu) # LD HL, SP + e8
opcode[0xF9] = lambda cpu: LD_SP_HL(cpu) # LD SP, HL
opcode[0xFA] = lambda cpu: LD_A_mN16(cpu) # LD A, [a16]
opcode[0xFB] = lambda cpu: EI(cpu) # EI
opcode[0xFC] = lambda cpu: opcode_invalido(0xFC, cpu)  # (Opcode Inválido)
opcode[0xFD] = lambda cpu: opcode_invalido(0xFD, cpu)  # (Opcode Inválido)
opcode[0xFE] = lambda cpu: CP_A_n8(cpu) # CP A, n8
opcode[0xFF] = lambda cpu: RST_vec(0x38, cpu) # RST $38

opcodeCB[0x00] = lambda cpu: RLC_r8(B, cpu) # RLC B
opcodeCB[0x01] = lambda cpu: RLC_r8(C, cpu) # RLC C
opcodeCB[0x02] = lambda cpu: RLC_r8(D, cpu) # RLC D
opcodeCB[0x03] = lambda cpu: RLC_r8(E, cpu) # RLC E
opcodeCB[0x04] = lambda cpu: RLC_r8(H, cpu) # RLC H
opcodeCB[0x05] = lambda cpu: RLC_r8(L, cpu) # RLC L
opcodeCB[0x06] = lambda cpu: RLC_mHL(cpu) # RLC [HL]
opcodeCB[0x07] = lambda cpu: RLC_r8(A, cpu) # RLC A
opcodeCB[0x08] = lambda cpu: RRC_r8(B, cpu) # RRC B
opcodeCB[0x09] = lambda cpu: RRC_r8(C, cpu) # RRC C
opcodeCB[0x0A] = lambda cpu: RRC_r8(D, cpu) # RRC D
opcodeCB[0x0B] = lambda cpu: RRC_r8(E, cpu) # RRC E
opcodeCB[0x0C] = lambda cpu: RRC_r8(H, cpu) # RRC H
opcodeCB[0x0D] = lambda cpu: RRC_r8(L, cpu) # RRC L
opcodeCB[0x0E] = lambda cpu: RRC_mHL(cpu) # RRC [HL]
opcodeCB[0x0F] = lambda cpu: RRC_r8(A, cpu) # RRC A

opcodeCB[0x10] = lambda cpu: RL_r8(B, cpu) # RL B
opcodeCB[0x11] = lambda cpu: RL_r8(C, cpu) # RL C
opcodeCB[0x12] = lambda cpu: RL_r8(D, cpu) # RL D
opcodeCB[0x13] = lambda cpu: RL_r8(E, cpu) # RL E
opcodeCB[0x14] = lambda cpu: RL_r8(H, cpu) # RL H
opcodeCB[0x15] = lambda cpu: RL_r8(L, cpu) # RL L
opcodeCB[0x16] = lambda cpu: RL_mHL(cpu) # RL [HL]
opcodeCB[0x17] = lambda cpu: RL_r8(A, cpu) # RL A
opcodeCB[0x18] = lambda cpu: RR_r8(B, cpu) # RR B
opcodeCB[0x19] = lambda cpu: RR_r8(C, cpu) # RR C
opcodeCB[0x1A] = lambda cpu: RR_r8(D, cpu) # RR D
opcodeCB[0x1B] = lambda cpu: RR_r8(E, cpu) # RR E
opcodeCB[0x1C] = lambda cpu: RR_r8(H, cpu) # RR H
opcodeCB[0x1D] = lambda cpu: RR_r8(L, cpu) # RR L
opcodeCB[0x1E] = lambda cpu: RR_mHL(cpu) # RR [HL]
opcodeCB[0x1F] = lambda cpu: RR_r8(A, cpu) # RR A

opcodeCB[0x20] = lambda cpu: SLA_r8(B, cpu) # SLA B
opcodeCB[0x21] = lambda cpu: SLA_r8(C, cpu) # SLA C
opcodeCB[0x22] = lambda cpu: SLA_r8(D, cpu) # SLA D
opcodeCB[0x23] = lambda cpu: SLA_r8(E, cpu) # SLA E
opcodeCB[0x24] = lambda cpu: SLA_r8(H, cpu) # SLA H
opcodeCB[0x25] = lambda cpu: SLA_r8(L, cpu) # SLA L
opcodeCB[0x26] = lambda cpu: SLA_mHL(cpu) # SLA [HL]
opcodeCB[0x27] = lambda cpu: SLA_r8(A, cpu) # SLA A
opcodeCB[0x28] = lambda cpu: SRA_r8(B, cpu) # SRA B
opcodeCB[0x29] = lambda cpu: SRA_r8(C, cpu) # SRA C
opcodeCB[0x2A] = lambda cpu: SRA_r8(D, cpu) # SRA D
opcodeCB[0x2B] = lambda cpu: SRA_r8(E, cpu) # SRA E
opcodeCB[0x2C] = lambda cpu: SRA_r8(H, cpu) # SRA H
opcodeCB[0x2D] = lambda cpu: SRA_r8(L, cpu) # SRA L
opcodeCB[0x2E] = lambda cpu: SRA_mHL(cpu) # SRA [HL]
opcodeCB[0x2F] = lambda cpu: SRA_r8(A, cpu) # SRA A

opcodeCB[0x30] = lambda cpu: SWAP_r8(B, cpu) # SWAP B
opcodeCB[0x31] = lambda cpu: SWAP_r8(C, cpu) # SWAP C
opcodeCB[0x32] = lambda cpu: SWAP_r8(D, cpu) # SWAP D
opcodeCB[0x33] = lambda cpu: SWAP_r8(E, cpu) # SWAP E
opcodeCB[0x34] = lambda cpu: SWAP_r8(H, cpu) # SWAP H
opcodeCB[0x35] = lambda cpu: SWAP_r8(L, cpu) # SWAP L
opcodeCB[0x36] = lambda cpu: SWAP_mHL(cpu) # SWAP [HL]
opcodeCB[0x37] = lambda cpu: SWAP_r8(A, cpu) # SWAP A
opcodeCB[0x38] = lambda cpu: SRL_r8(B, cpu) # SRL B
opcodeCB[0x39] = lambda cpu: SRL_r8(C, cpu) # SRL C
opcodeCB[0x3A] = lambda cpu: SRL_r8(D, cpu) # SRL D
opcodeCB[0x3B] = lambda cpu: SRL_r8(E, cpu) # SRL E
opcodeCB[0x3C] = lambda cpu: SRL_r8(H, cpu) # SRL H
opcodeCB[0x3D] = lambda cpu: SRL_r8(L, cpu) # SRL L
opcodeCB[0x3E] = lambda cpu: SRL_mHL(cpu) # SRL [HL]
opcodeCB[0x3F] = lambda cpu: SRL_r8(A, cpu) # SRL A

opcodeCB[0x40] = lambda cpu: BIT_u3_r8(0, B, cpu) # BIT 0, B
opcodeCB[0x41] = lambda cpu: BIT_u3_r8(0, C, cpu) # BIT 0, C
opcodeCB[0x42] = lambda cpu: BIT_u3_r8(0, D, cpu) # BIT 0, D
opcodeCB[0x43] = lambda cpu: BIT_u3_r8(0, E, cpu) # BIT 0, E
opcodeCB[0x44] = lambda cpu: BIT_u3_r8(0, H, cpu) # BIT 0, H
opcodeCB[0x45] = lambda cpu: BIT_u3_r8(0, L, cpu) # BIT 0, L
opcodeCB[0x46] = lambda cpu: BIT_u3_mHL(0, cpu) # BIT 0, [HL]
opcodeCB[0x47] = lambda cpu: BIT_u3_r8(0, A, cpu) # BIT 0, A
opcodeCB[0x48] = lambda cpu: BIT_u3_r8(1, B, cpu) # BIT 1, B
opcodeCB[0x49] = lambda cpu: BIT_u3_r8(1, C, cpu) # BIT 1, C
opcodeCB[0x4A] = lambda cpu: BIT_u3_r8(1, D, cpu) # BIT 1, D
opcodeCB[0x4B] = lambda cpu: BIT_u3_r8(1, E, cpu) # BIT 1, E
opcodeCB[0x4C] = lambda cpu: BIT_u3_r8(1, H, cpu) # BIT 1, H
opcodeCB[0x4D] = lambda cpu: BIT_u3_r8(1, L, cpu) # BIT 1, L
opcodeCB[0x4E] = lambda cpu: BIT_u3_mHL(1, cpu) # BIT 1, [HL]
opcodeCB[0x4F] = lambda cpu: BIT_u3_r8(1, A, cpu) # BIT 1, A

opcodeCB[0x50] = lambda cpu: BIT_u3_r8(2, B, cpu) # BIT 2, B
opcodeCB[0x51] = lambda cpu: BIT_u3_r8(2, C, cpu) # BIT 2, C
opcodeCB[0x52] = lambda cpu: BIT_u3_r8(2, D, cpu) # BIT 2, D
opcodeCB[0x53] = lambda cpu: BIT_u3_r8(2, E, cpu) # BIT 2, E
opcodeCB[0x54] = lambda cpu: BIT_u3_r8(2, H, cpu) # BIT 2, H
opcodeCB[0x55] = lambda cpu: BIT_u3_r8(2, L, cpu) # BIT 2, L
opcodeCB[0x56] = lambda cpu: BIT_u3_mHL(2, cpu) # BIT 2, [HL]
opcodeCB[0x57] = lambda cpu: BIT_u3_r8(2, A, cpu) # BIT 2, A
opcodeCB[0x58] = lambda cpu: BIT_u3_r8(3, B, cpu) # BIT 3, B
opcodeCB[0x59] = lambda cpu: BIT_u3_r8(3, C, cpu) # BIT 3, C
opcodeCB[0x5A] = lambda cpu: BIT_u3_r8(3, D, cpu) # BIT 3, D
opcodeCB[0x5B] = lambda cpu: BIT_u3_r8(3, E, cpu) # BIT 3, E
opcodeCB[0x5C] = lambda cpu: BIT_u3_r8(3, H, cpu) # BIT 3, H
opcodeCB[0x5D] = lambda cpu: BIT_u3_r8(3, L, cpu) # BIT 3, L
opcodeCB[0x5E] = lambda cpu: BIT_u3_mHL(3, cpu) # BIT 3, [HL]
opcodeCB[0x5F] = lambda cpu: BIT_u3_r8(3, A, cpu) # BIT 3, A

opcodeCB[0x60] = lambda cpu: BIT_u3_r8(4, B, cpu) # BIT 4, B
opcodeCB[0x61] = lambda cpu: BIT_u3_r8(4, C, cpu) # BIT 4, C
opcodeCB[0x62] = lambda cpu: BIT_u3_r8(4, D, cpu) # BIT 4, D
opcodeCB[0x63] = lambda cpu: BIT_u3_r8(4, E, cpu) # BIT 4, E
opcodeCB[0x64] = lambda cpu: BIT_u3_r8(4, H, cpu) # BIT 4, H
opcodeCB[0x65] = lambda cpu: BIT_u3_r8(4, L, cpu) # BIT 4, L
opcodeCB[0x66] = lambda cpu: BIT_u3_mHL(4, cpu) # BIT 4, [HL]
opcodeCB[0x67] = lambda cpu: BIT_u3_r8(4, A, cpu) # BIT 4, A
opcodeCB[0x68] = lambda cpu: BIT_u3_r8(5, B, cpu) # BIT 5, B
opcodeCB[0x69] = lambda cpu: BIT_u3_r8(5, C, cpu) # BIT 5, C
opcodeCB[0x6A] = lambda cpu: BIT_u3_r8(5, D, cpu) # BIT 5, D
opcodeCB[0x6B] = lambda cpu: BIT_u3_r8(5, E, cpu) # BIT 5, E
opcodeCB[0x6C] = lambda cpu: BIT_u3_r8(5, H, cpu) # BIT 5, H
opcodeCB[0x6D] = lambda cpu: BIT_u3_r8(5, L, cpu) # BIT 5, L
opcodeCB[0x6E] = lambda cpu: BIT_u3_mHL(5, cpu) # BIT 5, [HL]
opcodeCB[0x6F] = lambda cpu: BIT_u3_r8(5, A, cpu) # BIT 5, A

opcodeCB[0x70] = lambda cpu: BIT_u3_r8(6, B, cpu) # BIT 6, B
opcodeCB[0x71] = lambda cpu: BIT_u3_r8(6, C, cpu) # BIT 6, C
opcodeCB[0x72] = lambda cpu: BIT_u3_r8(6, D, cpu) # BIT 6, D
opcodeCB[0x73] = lambda cpu: BIT_u3_r8(6, E, cpu) # BIT 6, E
opcodeCB[0x74] = lambda cpu: BIT_u3_r8(6, H, cpu) # BIT 6, H
opcodeCB[0x75] = lambda cpu: BIT_u3_r8(6, L, cpu) # BIT 6, L
opcodeCB[0x76] = lambda cpu: BIT_u3_mHL(6, cpu) # BIT 6, [HL]
opcodeCB[0x77] = lambda cpu: BIT_u3_r8(6, A, cpu) # BIT 6, A
opcodeCB[0x78] = lambda cpu: BIT_u3_r8(7, B, cpu) # BIT 7, B
opcodeCB[0x79] = lambda cpu: BIT_u3_r8(7, C, cpu) # BIT 7, C
opcodeCB[0x7A] = lambda cpu: BIT_u3_r8(7, D, cpu) # BIT 7, D
opcodeCB[0x7B] = lambda cpu: BIT_u3_r8(7, E, cpu) # BIT 7, E
opcodeCB[0x7C] = lambda cpu: BIT_u3_r8(7, H, cpu) # BIT 7, H
opcodeCB[0x7D] = lambda cpu: BIT_u3_r8(7, L, cpu) # BIT 7, L
opcodeCB[0x7E] = lambda cpu: BIT_u3_mHL(7, cpu) # BIT 7, [HL]
opcodeCB[0x7F] = lambda cpu: BIT_u3_r8(7, A, cpu) # BIT 7, A

opcodeCB[0x80] = lambda cpu: RES_u3_r8(0, B, cpu) # RES 0, B
opcodeCB[0x81] = lambda cpu: RES_u3_r8(0, C, cpu) # RES 0, C
opcodeCB[0x82] = lambda cpu: RES_u3_r8(0, D, cpu) # RES 0, D
opcodeCB[0x83] = lambda cpu: RES_u3_r8(0, E, cpu) # RES 0, E
opcodeCB[0x84] = lambda cpu: RES_u3_r8(0, H, cpu) # RES 0, H
opcodeCB[0x85] = lambda cpu: RES_u3_r8(0, L, cpu) # RES 0, L
opcodeCB[0x86] = lambda cpu: RES_u3_mHL(0, cpu) # RES 0, [HL]
opcodeCB[0x87] = lambda cpu: RES_u3_r8(0, A, cpu) # RES 0, A
opcodeCB[0x88] = lambda cpu: RES_u3_r8(1, B, cpu) # RES 1, B
opcodeCB[0x89] = lambda cpu: RES_u3_r8(1, C, cpu) # RES 1, C
opcodeCB[0x8A] = lambda cpu: RES_u3_r8(1, D, cpu) # RES 1, D
opcodeCB[0x8B] = lambda cpu: RES_u3_r8(1, E, cpu) # RES 1, E
opcodeCB[0x8C] = lambda cpu: RES_u3_r8(1, H, cpu) # RES 1, H
opcodeCB[0x8D] = lambda cpu: RES_u3_r8(1, L, cpu) # RES 1, L
opcodeCB[0x8E] = lambda cpu: RES_u3_mHL(1, cpu) # RES 1, [HL]
opcodeCB[0x8F] = lambda cpu: RES_u3_r8(1, A, cpu) # RES 1, A

opcodeCB[0x90] = lambda cpu: RES_u3_r8(2, B, cpu) # RES 2, B
opcodeCB[0x91] = lambda cpu: RES_u3_r8(2, C, cpu) # RES 2, C
opcodeCB[0x92] = lambda cpu: RES_u3_r8(2, D, cpu) # RES 2, D
opcodeCB[0x93] = lambda cpu: RES_u3_r8(2, E, cpu) # RES 2, E
opcodeCB[0x94] = lambda cpu: RES_u3_r8(2, H, cpu) # RES 2, H
opcodeCB[0x95] = lambda cpu: RES_u3_r8(2, L, cpu) # RES 2, L
opcodeCB[0x96] = lambda cpu: RES_u3_mHL(2, cpu) # RES 2, [HL]
opcodeCB[0x97] = lambda cpu: RES_u3_r8(2, A, cpu) # RES 2, A
opcodeCB[0x98] = lambda cpu: RES_u3_r8(3, B, cpu) # RES 3, B
opcodeCB[0x99] = lambda cpu: RES_u3_r8(3, C, cpu) # RES 3, C
opcodeCB[0x9A] = lambda cpu: RES_u3_r8(3, D, cpu) # RES 3, D
opcodeCB[0x9B] = lambda cpu: RES_u3_r8(3, E, cpu) # RES 3, E
opcodeCB[0x9C] = lambda cpu: RES_u3_r8(3, H, cpu) # RES 3, H
opcodeCB[0x9D] = lambda cpu: RES_u3_r8(3, L, cpu) # RES 3, L
opcodeCB[0x9E] = lambda cpu: RES_u3_mHL(3, cpu) # RES 3, [HL]
opcodeCB[0x9F] = lambda cpu: RES_u3_r8(3, A, cpu) # RES 3, A

opcodeCB[0xA0] = lambda cpu: RES_u3_r8(4, B, cpu) # RES 4, B
opcodeCB[0xA1] = lambda cpu: RES_u3_r8(4, C, cpu) # RES 4, C
opcodeCB[0xA2] = lambda cpu: RES_u3_r8(4, D, cpu) # RES 4, D
opcodeCB[0xA3] = lambda cpu: RES_u3_r8(4, E, cpu) # RES 4, E
opcodeCB[0xA4] = lambda cpu: RES_u3_r8(4, H, cpu) # RES 4, H
opcodeCB[0xA5] = lambda cpu: RES_u3_r8(4, L, cpu) # RES 4, L
opcodeCB[0xA6] = lambda cpu: RES_u3_mHL(4, cpu) # RES 4, [HL]
opcodeCB[0xA7] = lambda cpu: RES_u3_r8(4, A, cpu) # RES 4, A
opcodeCB[0xA8] = lambda cpu: RES_u3_r8(5, B, cpu) # RES 5, B
opcodeCB[0xA9] = lambda cpu: RES_u3_r8(5, C, cpu) # RES 5, C
opcodeCB[0xAA] = lambda cpu: RES_u3_r8(5, D, cpu) # RES 5, D
opcodeCB[0xAB] = lambda cpu: RES_u3_r8(5, E, cpu) # RES 5, E
opcodeCB[0xAC] = lambda cpu: RES_u3_r8(5, H, cpu) # RES 5, H
opcodeCB[0xAD] = lambda cpu: RES_u3_r8(5, L, cpu) # RES 5, L
opcodeCB[0xAE] = lambda cpu: RES_u3_mHL(5, cpu) # RES 5, [HL]
opcodeCB[0xAF] = lambda cpu: RES_u3_r8(5, A, cpu) # RES 5, A

opcodeCB[0xB0] = lambda cpu: RES_u3_r8(6, B, cpu) # RES 6, B
opcodeCB[0xB1] = lambda cpu: RES_u3_r8(6, C, cpu) # RES 6, C
opcodeCB[0xB2] = lambda cpu: RES_u3_r8(6, D, cpu) # RES 6, D
opcodeCB[0xB3] = lambda cpu: RES_u3_r8(6, E, cpu) # RES 6, E
opcodeCB[0xB4] = lambda cpu: RES_u3_r8(6, H, cpu) # RES 6, H
opcodeCB[0xB5] = lambda cpu: RES_u3_r8(6, L, cpu) # RES 6, L
opcodeCB[0xB6] = lambda cpu: RES_u3_mHL(6, cpu) # RES 6, [HL]
opcodeCB[0xB7] = lambda cpu: RES_u3_r8(6, A, cpu) # RES 6, A
opcodeCB[0xB8] = lambda cpu: RES_u3_r8(7, B, cpu) # RES 7, B
opcodeCB[0xB9] = lambda cpu: RES_u3_r8(7, C, cpu) # RES 7, C
opcodeCB[0xBA] = lambda cpu: RES_u3_r8(7, D, cpu) # RES 7, D
opcodeCB[0xBB] = lambda cpu: RES_u3_r8(7, E, cpu) # RES 7, E
opcodeCB[0xBC] = lambda cpu: RES_u3_r8(7, H, cpu) # RES 7, H
opcodeCB[0xBD] = lambda cpu: RES_u3_r8(7, L, cpu) # RES 7, L
opcodeCB[0xBE] = lambda cpu: RES_u3_mHL(7, cpu) # RES 7, [HL]
opcodeCB[0xBF] = lambda cpu: RES_u3_r8(7, A, cpu) # RES 7, A

opcodeCB[0xC0] = lambda cpu: SET_u3_r8(0, B, cpu) # SET 0, B
opcodeCB[0xC1] = lambda cpu: SET_u3_r8(0, C, cpu) # SET 0, C
opcodeCB[0xC2] = lambda cpu: SET_u3_r8(0, D, cpu) # SET 0, D
opcodeCB[0xC3] = lambda cpu: SET_u3_r8(0, E, cpu) # SET 0, E
opcodeCB[0xC4] = lambda cpu: SET_u3_r8(0, H, cpu) # SET 0, H
opcodeCB[0xC5] = lambda cpu: SET_u3_r8(0, L, cpu) # SET 0, L
opcodeCB[0xC6] = lambda cpu: SET_u3_mHL(0, cpu) # SET 0, [HL]
opcodeCB[0xC7] = lambda cpu: SET_u3_r8(0, A, cpu) # SET 0, A
opcodeCB[0xC8] = lambda cpu: SET_u3_r8(1, B, cpu) # SET 1, B
opcodeCB[0xC9] = lambda cpu: SET_u3_r8(1, C, cpu) # SET 1, C
opcodeCB[0xCA] = lambda cpu: SET_u3_r8(1, D, cpu) # SET 1, D
opcodeCB[0xCB] = lambda cpu: SET_u3_r8(1, E, cpu) # SET 1, E
opcodeCB[0xCC] = lambda cpu: SET_u3_r8(1, H, cpu) # SET 1, H
opcodeCB[0xCD] = lambda cpu: SET_u3_r8(1, L, cpu) # SET 1, L
opcodeCB[0xCE] = lambda cpu: SET_u3_mHL(1, cpu) # SET 1, [HL]
opcodeCB[0xCF] = lambda cpu: SET_u3_r8(1, A, cpu) # SET 1, A

opcodeCB[0xD0] = lambda cpu: SET_u3_r8(2, B, cpu) # SET 2, B
opcodeCB[0xD1] = lambda cpu: SET_u3_r8(2, C, cpu) # SET 2, C
opcodeCB[0xD2] = lambda cpu: SET_u3_r8(2, D, cpu) # SET 2, D
opcodeCB[0xD3] = lambda cpu: SET_u3_r8(2, E, cpu) # SET 2, E
opcodeCB[0xD4] = lambda cpu: SET_u3_r8(2, H, cpu) # SET 2, H
opcodeCB[0xD5] = lambda cpu: SET_u3_r8(2, L, cpu) # SET 2, L
opcodeCB[0xD6] = lambda cpu: SET_u3_mHL(2, cpu) # SET 2, [HL]
opcodeCB[0xD7] = lambda cpu: SET_u3_r8(2, A, cpu) # SET 2, A
opcodeCB[0xD8] = lambda cpu: SET_u3_r8(3, B, cpu) # SET 3, B
opcodeCB[0xD9] = lambda cpu: SET_u3_r8(3, C, cpu) # SET 3, C
opcodeCB[0xDA] = lambda cpu: SET_u3_r8(3, D, cpu) # SET 3, D
opcodeCB[0xDB] = lambda cpu: SET_u3_r8(3, E, cpu) # SET 3, E
opcodeCB[0xDC] = lambda cpu: SET_u3_r8(3, H, cpu) # SET 3, H
opcodeCB[0xDD] = lambda cpu: SET_u3_r8(3, L, cpu) # SET 3, L
opcodeCB[0xDE] = lambda cpu: SET_u3_mHL(3, cpu) # SET 3, [HL]
opcodeCB[0xDF] = lambda cpu: SET_u3_r8(3, A, cpu) # SET 3, A

opcodeCB[0xE0] = lambda cpu: SET_u3_r8(4, B, cpu) # SET 4, B
opcodeCB[0xE1] = lambda cpu: SET_u3_r8(4, C, cpu) # SET 4, C
opcodeCB[0xE2] = lambda cpu: SET_u3_r8(4, D, cpu) # SET 4, D
opcodeCB[0xE3] = lambda cpu: SET_u3_r8(4, E, cpu) # SET 4, E
opcodeCB[0xE4] = lambda cpu: SET_u3_r8(4, H, cpu) # SET 4, H
opcodeCB[0xE5] = lambda cpu: SET_u3_r8(4, L, cpu) # SET 4, L
opcodeCB[0xE6] = lambda cpu: SET_u3_mHL(4, cpu) # SET 4, [HL]
opcodeCB[0xE7] = lambda cpu: SET_u3_r8(4, A, cpu) # SET 4, A
opcodeCB[0xE8] = lambda cpu: SET_u3_r8(5, B, cpu) # SET 5, B
opcodeCB[0xE9] = lambda cpu: SET_u3_r8(5, C, cpu) # SET 5, C
opcodeCB[0xEA] = lambda cpu: SET_u3_r8(5, D, cpu) # SET 5, D
opcodeCB[0xEB] = lambda cpu: SET_u3_r8(5, E, cpu) # SET 5, E
opcodeCB[0xEC] = lambda cpu: SET_u3_r8(5, H, cpu) # SET 5, H
opcodeCB[0xED] = lambda cpu: SET_u3_r8(5, L, cpu) # SET 5, L
opcodeCB[0xEE] = lambda cpu: SET_u3_mHL(5, cpu) # SET 5, [HL]
opcodeCB[0xEF] = lambda cpu: SET_u3_r8(5, A, cpu) # SET 5, A

opcodeCB[0xF0] = lambda cpu: SET_u3_r8(6, B, cpu) # SET 6, B
opcodeCB[0xF1] = lambda cpu: SET_u3_r8(6, C, cpu) # SET 6, C
opcodeCB[0xF2] = lambda cpu: SET_u3_r8(6, D, cpu) # SET 6, D
opcodeCB[0xF3] = lambda cpu: SET_u3_r8(6, E, cpu) # SET 6, E
opcodeCB[0xF4] = lambda cpu: SET_u3_r8(6, H, cpu) # SET 6, H
opcodeCB[0xF5] = lambda cpu: SET_u3_r8(6, L, cpu) # SET 6, L
opcodeCB[0xF6] = lambda cpu: SET_u3_mHL(6, cpu) # SET 6, [HL]
opcodeCB[0xF7] = lambda cpu: SET_u3_r8(6, A, cpu) # SET 6, A
opcodeCB[0xF8] = lambda cpu: SET_u3_r8(7, B, cpu) # SET 7, B
opcodeCB[0xF9] = lambda cpu: SET_u3_r8(7, C, cpu) # SET 7, C
opcodeCB[0xFA] = lambda cpu: SET_u3_r8(7, D, cpu) # SET 7, D
opcodeCB[0xFB] = lambda cpu: SET_u3_r8(7, E, cpu) # SET 7, E
opcodeCB[0xFC] = lambda cpu: SET_u3_r8(7, H, cpu) # SET 7, H
opcodeCB[0xFD] = lambda cpu: SET_u3_r8(7, L, cpu) # SET 7, L
opcodeCB[0xFE] = lambda cpu: SET_u3_mHL(7, cpu) # SET 7, [HL]
opcodeCB[0xFF] = lambda cpu: SET_u3_r8(7, A, cpu) # SET 7, A