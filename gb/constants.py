"""
Apelidos para os registradores da CPU e para os bits do registrador de flags.

Nada aqui faz coisa alguma sozinho: são todos números fixos, com nome. Mas são
os números que aparecem em quase toda linha de `cpu.py` e `opcodes.py`, então
vale conhecê-los antes.

O motivo de existirem índices em vez de atributos comuns está em `cpu.py`: os
registradores do processador não moram em variáveis separadas, e sim num único
`bytearray` de 12 bytes. Escrever `cpu.reg8[B]` em vez de `cpu.reg8[3]` é a
diferença entre código legível e um campo minado de números soltos.
"""

# ----------------------------------------------------------------------
# Os pares de 16 bits
# ----------------------------------------------------------------------
# O SM83 tem registradores de 8 bits, mas endereços têm 16. A solução do chip é
# grudar os registradores de dois em dois: B e C juntos formam BC, D e E formam
# DE, e assim por diante. Cada par funciona como um número de 16 bits quando a
# instrução pede, e como dois de 8 bits quando pede o contrário.
#
# Os números abaixo são a posição de cada par dentro do banco de registradores.
AF = 0; BC = 1; DE = 2
HL = 3; SP = 4; PC = 5

# AF é o par especial: A é o acumulador, onde quase toda conta acontece, e F
# guarda as flags (o resultado da última operação). SP é o topo da pilha e PC
# aponta para a próxima instrução a executar.

# ----------------------------------------------------------------------
# Os registradores de 8 bits
# ----------------------------------------------------------------------
# A ordem parece embaralhada — F antes de A, C antes de B — e não é descuido.
# Ela reflete como os bytes ficam guardados na memória em processadores
# little-endian, onde o byte MENOS significativo vem primeiro. Como F é a
# metade baixa de AF, F ocupa a posição 0 e A a posição 1. O mesmo vale para os
# outros pares.
#
# A recompensa dessa ordem esquisita: ler o par inteiro é só olhar os mesmos
# bytes de outro jeito, sem conversão nenhuma. Ver `registradores.py`.
F = 0; A = 1; C = 2; B = 3
E = 4; D = 5; L = 6; H = 7

# ----------------------------------------------------------------------
# As flags
# ----------------------------------------------------------------------
# O registrador F não guarda um valor: guarda quatro respostas sim/não sobre a
# última operação aritmética, uma em cada bit. É lendo essas respostas que
# instruções de desvio decidem para onde pular — um `JR Z, e8` só pula se a
# flag Z estiver ligada.
#
# `1 << 7` é o número 1 empurrado 7 casas para a esquerda, ou seja, um valor com
# apenas o bit 7 ligado. Escrever assim deixa óbvio de qual bit se trata; o
# valor decimal equivalente (128) esconderia isso.
FLAG_Z = 1 << 7  # Zero:      o resultado deu exatamente zero
FLAG_N = 1 << 6  # Negativo:  a última operação foi uma subtração
FLAG_H = 1 << 5  # Half-carry: houve "vai um" do bit 3 para o bit 4
FLAG_C = 1 << 4  # Carry:     houve "vai um" para fora do byte (ou empréstimo)

# Os quatro bits de baixo de F não existem fisicamente no chip: leem sempre 0,
# não importa o que se escreva. `cpu.write_af` cuida disso.
#
# FLAG_N e FLAG_H parecem inúteis à primeira vista — quem se importa se a
# operação foi soma ou subtração depois de pronta? Uma instrução se importa:
# a DAA, que corrige o resultado quando o programa trata os bytes como dígitos
# decimais. Sem saber o que veio antes, ela não teria como corrigir. A história
# completa está na DAA, em `opcodes.py`.
