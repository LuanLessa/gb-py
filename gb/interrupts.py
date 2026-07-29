"""
As cinco interrupções do console.

Uma interrupção é um pedido de socorro do hardware. Sem elas, um jogo que
precisasse saber quando a tela terminou de ser desenhada teria de ficar
perguntando num laço — gastando ciclos e pilha para, na maior parte das vezes,
ouvir "ainda não". Com elas, o jogo manda um HALT, o processador desliga, e o
próprio hardware o acorda na hora exata.

O mecanismo tem duas metades, e as duas precisam concordar:

    IE (FFFF)   quais interrupções o jogo QUER receber
    IF (FF0F)   quais estão PEDINDO atenção neste momento

Quem escreve no IE é o jogo, ao dizer no que tem interesse. Quem escreve no IF é
o hardware, ao acontecer alguma coisa. A interrupção só é atendida quando os dois
apontam para o mesmo bit e a chave geral está ligada:

    IME == 1   e   (IE & IF) != 0

O IME é essa chave geral, e mora na CPU, não aqui. As instruções EI, DI e RETI
são o que a liga e desliga — ver `opcodes.py`.

Cada bit corresponde a uma fonte, e a POSIÇÃO do bit define a prioridade: se
duas interrupções chegam juntas, vence a de bit mais baixo. Faz sentido que o
V-Blank, que organiza o desenho da tela inteira, venha antes do joypad.

Este arquivo é pequeno porque quase toda a lógica está em `CPU.servir_interrupcao`
e em `CPU.step`. O que fica aqui são os nomes e as duas contas que aparecem em
mais de um lugar.
"""

# Máscara de bit de cada fonte, na ordem de prioridade.
INT_VBLANK = 0x01   # a PPU terminou de desenhar o quadro (chegou à linha 144)
INT_STAT = 0x02     # um evento de vídeo que o jogo pediu para vigiar
INT_TIMER = 0x04    # o TIMA estourou
INT_SERIAL = 0x08   # a transferência de 8 bits pelo cabo terminou
INT_JOYPAD = 0x10   # algum botão foi pressionado

# Para onde a CPU pula ao atender cada uma. De 8 em 8, porque era esse o espaço
# reservado a cada rotina — e não cabe muita coisa em 8 bytes, então na prática
# o jogo põe ali um salto para a rotina de verdade.
VETORES = (0x40, 0x48, 0x50, 0x58, 0x60)

NOMES = ("VBlank", "STAT", "Timer", "Serial", "Joypad")


def pendentes(ie, if_):
    """
    Quais interrupções estão habilitadas E pedindo atenção ao mesmo tempo.

    O `& 0x1F` no fim descarta os três bits de cima, que não correspondem a
    fonte nenhuma: existem 5 interrupções, e não 8.
    """
    return ie & if_ & 0x1F


def mais_prioritaria(mascara):
    """
    O índice do bit ligado mais à direita, que é o de maior prioridade.

    `mascara & -mascara` isola esse bit sozinho — um truque que funciona pela
    forma como números negativos são representados em complemento de dois. Para
    0b10100, o resultado é 0b00100. Daí `.bit_length() - 1` converte o bit no seu
    índice: 0b00100 tem comprimento 3, então o índice é 2.

    Devolve None quando não há nenhuma pendente.
    """
    if not mascara:
        return None
    return (mascara & -mascara).bit_length() - 1
