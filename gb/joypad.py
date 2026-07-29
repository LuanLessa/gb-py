"""
Os oito botões, lidos por um único endereço.

O Game Boy tem oito botões e um registrador só para todos: FF00. Ler oito
estados de um byte pareceria fácil — sobrariam bits — mas o console não faz
assim, e o motivo é economia de pinos.

Cada botão ligado direto ao processador gastaria um pino, e pino em chip é
caro. A solução é uma MATRIZ: duas linhas de seleção e quatro fios de retorno,
seis pinos no lugar de oito. O jogo escolhe qual metade quer ler e depois lê os
quatro fios:

                     direita  esquerda  cima   baixo
    linha 0 (bit 4)     ●        ●        ●      ●
    linha 1 (bit 5)     ●        ●        ●      ●
                       A        B      select  start

Ler os oito botões exige, portanto, duas leituras: seleciona a primeira linha,
lê; seleciona a segunda, lê. É por isso que a rotina de leitura de controle de
qualquer jogo de Game Boy tem esse formato repetido.


A LÓGICA É INVERTIDA
--------------------

O ponto que confunde todo mundo na primeira vez: aqui 0 significa PRESSIONADO
e 1 significa solto. O mesmo vale para a seleção — escrever 0 num bit é que
seleciona aquela linha.

Não é perversidade. Num circuito assim, o estado de repouso é mantido por
resistores que puxam a linha para 1, e apertar o botão a conecta ao terra,
derrubando para 0. É mais barato e mais confiável do que o contrário, e como
consequência a leitura sai invertida.
"""

IRQ_JOYPAD = 0x10

# Os nomes na ordem dos bits de retorno, do bit 0 ao bit 3.
DIRECIONAIS = ("direita", "esquerda", "cima", "baixo")
ACOES = ("a", "b", "select", "start")


class Joypad:
    def __init__(self, bus):
        self.bus = bus

        # O estado de verdade dos botões, sem inversão nenhuma: True é
        # pressionado. A inversão fica toda dentro de `_nibble`, para que o
        # resto do emulador não precise pensar nisso.
        self.botoes = {n: False for n in DIRECIONAIS + ACOES}

        # Qual linha o jogo selecionou por último. 0x30 são os dois bits em 1,
        # ou seja, nenhuma linha selecionada.
        self.selecao = 0x30

        # O valor anterior dos quatro fios de retorno, para detectar a descida
        # que gera interrupção. Ver `_checar_irq`.
        self._nibble_anterior = 0x0F

    # ------------------------------------------------------------------
    # O que o frontend chama quando o jogador aperta uma tecla
    # ------------------------------------------------------------------
    def pressionar(self, nome):
        if nome in self.botoes:
            self.botoes[nome] = True
            self._checar_irq()

    def soltar(self, nome):
        if nome in self.botoes:
            self.botoes[nome] = False
            self._checar_irq()

    def definir(self, nome, apertado):
        """Pressionar ou soltar conforme um booleano — o mais prático dos três."""
        if nome in self.botoes:
            self.botoes[nome] = bool(apertado)
            self._checar_irq()

    # ------------------------------------------------------------------
    def _nibble(self):
        """
        Os quatro bits de retorno, conforme a linha selecionada no momento.

        Começa com todos em 1 (nenhum botão apertado) e vai DERRUBANDO os bits
        dos botões pressionados — a lógica invertida descrita no topo.

        As duas linhas podem estar selecionadas ao mesmo tempo, e nesse caso os
        botões se misturam: apertar "direita" e apertar "A" derrubam o mesmo bit,
        e não há como distinguir. O hardware é assim, e jogos evitam a situação
        selecionando uma linha por vez.
        """
        v = 0x0F
        if not (self.selecao & 0x10):            # bit 4 em 0 seleciona os direcionais
            for i, nome in enumerate(DIRECIONAIS):
                if self.botoes[nome]:
                    v &= ~(1 << i)
        if not (self.selecao & 0x20):            # bit 5 em 0 seleciona os de ação
            for i, nome in enumerate(ACOES):
                if self.botoes[nome]:
                    v &= ~(1 << i)
        return v & 0x0F

    def _checar_irq(self):
        """
        Dispara a interrupção quando algum fio de retorno cai de 1 para 0.

        É o mesmo detector de borda do timer e do STAT, e pela mesma razão: o
        que interessa é a MUDANÇA, não o estado. Uma tecla mantida pressionada
        gera uma interrupção só, no instante em que desce.

        `anterior & ~atual` fica com os bits que estavam em 1 e agora estão em
        0 — exatamente as descidas.

        Esta interrupção é pouco usada durante o jogo, porque ler o registrador
        de tempos em tempos é mais simples. Ela existe mesmo para acordar o
        console do STOP: é o único jeito de sair daquele estado.
        """
        atual = self._nibble()
        if self._nibble_anterior & ~atual & 0x0F:
            self.bus.if_ |= IRQ_JOYPAD
        self._nibble_anterior = atual

    # ------------------------------------------------------------------
    def ler(self):
        """FF00 — os bits de seleção, mais os quatro de retorno."""
        # Os bits 6 e 7 não existem e leem sempre 1.
        return 0xC0 | (self.selecao & 0x30) | self._nibble()

    def escrever(self, val):
        """
        FF00 — só os bits 4 e 5 são graváveis: eles escolhem a linha.

        A checagem de interrupção no fim é necessária porque trocar de linha
        muda o que os fios de retorno mostram. Selecionar a linha dos direcionais
        com uma seta já pressionada faz o bit cair de 1 para 0 — uma descida como
        qualquer outra, e portanto uma interrupção.
        """
        self.selecao = val & 0x30
        self._checar_irq()
