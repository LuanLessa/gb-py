"""
O timer — um contador que avisa a CPU de tempos em tempos.

Um jogo precisa medir tempo para coisas que não têm nada a ver com a tela:
trocar a música no compasso certo, contar os segundos de uma corrida, decidir
quando o inimigo ataca de novo. Contar instruções não serve, porque a duração de
cada uma varia. O timer resolve isso: o jogo configura de quanto em quanto quer
ser avisado, e o hardware avisa.

São quatro registradores:

    DIV  (FF04)  um contador que sobe sozinho e não para nunca
    TIMA (FF05)  o contador que dispara a interrupção ao estourar
    TMA  (FF06)  o valor de recomeço do TIMA depois do estouro
    TAC  (FF07)  liga/desliga, e escolhe a velocidade


O QUE QUASE TODO EMULADOR ERRA
------------------------------

A leitura ingênua é "o TIMA sobe a cada N ciclos". Com essa ideia o emulador roda
a maioria dos jogos e falha em todos os testes de precisão, porque o hardware não
funciona assim.

O que existe de verdade é UM contador interno de 16 bits que sobe a cada T-cycle
e nunca é desligado. O TIMA não conta ciclos: ele é incrementado pela BORDA DE
DESCIDA de um bit específico desse contador — o bit escolhido pelo TAC, passado
por um E lógico com o bit de habilitação.

"Borda de descida" é o instante em que um sinal passa de 1 para 0. Se o TAC
seleciona o bit 3, o TIMA sobe toda vez que aquele bit troca de 1 para 0, o que
acontece a cada 16 T-cycles. Selecionar o bit 9 dá um evento a cada 1024.

Essa diferença de mecanismo produz um comportamento que parece absurdo:

    ESCREVER NO DIV PODE INCREMENTAR O TIMA.

Escrever no DIV zera o contador interno. Se o bit selecionado estava em 1 na
hora, zerar tudo o leva a 0 — e isso é uma borda de descida como qualquer outra.
O TIMA sobe, sem que ninguém tenha pedido.

Não é curiosidade de museu. Vários jogos e todas as ROMs de teste de timer
dependem disso, e é impossível reproduzir sem modelar o contador do jeito certo.
"""

# Qual bit do contador interno cada valor de TAC[1:0] vigia.
#
# Bits mais baixos trocam mais depressa, então dão frequências mais altas. A
# ordem parece embaralhada porque é: a codificação dos dois bits do TAC foi
# escolhida por conveniência de fiação, não por ordem de velocidade.
#
#   TAC  bit    borda a cada        frequência
#   00     9    1024 T-cycles         4096 Hz
#   01     3      16 T-cycles       262144 Hz
#   10     5      64 T-cycles        65536 Hz
#   11     7     256 T-cycles        16384 Hz
BIT_SELECIONADO = (9, 3, 5, 7)

# O bit do registrador IF que este chip liga quando o TIMA estoura.
IRQ_TIMER = 0x04


class Timer:
    def __init__(self, bus):
        self.bus = bus

        # O contador de 16 bits que move tudo. O DIV que o jogo lê em FF04 é
        # apenas o byte ALTO deste número — o de baixo não aparece de fora,
        # embora seja ele que decide as bordas mais rápidas.
        self.contador = 0

        self.tima = 0            # FF05
        self.tma = 0             # FF06
        self.tac = 0             # FF07

        self.bit_sel = BIT_SELECIONADO[0]
        self.habilitado = False

        # O valor anterior de (bit selecionado E habilitado). Guardar o estado
        # anterior é o que permite detectar a TROCA de 1 para 0 — sem ele só
        # daria para saber o valor atual, e não que ele acabou de cair.
        self.sinal = False

        # O estouro do TIMA não recarrega na hora. Existe um M-cycle inteiro em
        # que o TIMA vale 0x00 antes de receber o TMA e a interrupção sair. Um
        # jogo que leia o TIMA exatamente nesse instante vê zero, e não o TMA.
        # Os dois campos abaixo modelam essa janela.
        self.recarga_pendente = False
        self.recarregando = False

    # ------------------------------------------------------------------
    # Passagem do tempo
    # ------------------------------------------------------------------
    def step(self):
        """
        Avança 1 M-cycle (4 T-cycles).

        O caminho comum deste método está copiado dentro de `Machine.tick4`, por
        velocidade; aqui fica a versão completa, que trata também a recarga
        pendente. O motivo da duplicação está explicado em `machine.py`.
        """
        # Resolve a recarga que ficou pendente do M-cycle anterior. Só AGORA o
        # TMA entra no TIMA e a interrupção é solicitada — um M-cycle depois do
        # estouro, como no hardware.
        if self.recarga_pendente:
            self.recarga_pendente = False
            self.tima = self.tma
            self.bus.if_ |= IRQ_TIMER
            self.recarregando = True
        elif self.recarregando:
            self.recarregando = False

        self.contador = (self.contador + 4) & 0xFFFF
        self._avaliar_borda()

    def _avaliar_borda(self):
        """
        Compara o sinal atual com o anterior e incrementa o TIMA na descida.

        Este método é chamado de todo lugar que possa mudar o sinal: o avanço do
        contador, a escrita no DIV, a troca de bit pelo TAC. É o coração do
        arquivo, e a razão de os comportamentos estranhos do timer saírem de
        graça em vez de precisarem de casos especiais espalhados.
        """
        novo = self.habilitado and ((self.contador >> self.bit_sel) & 1) == 1
        if self.sinal and not novo:
            self._incrementar_tima()
        self.sinal = novo

    def _incrementar_tima(self):
        """Soma 1 ao TIMA; se der a volta, agenda a recarga para o M-cycle seguinte."""
        self.tima = (self.tima + 1) & 0xFF
        if self.tima == 0:
            self.recarga_pendente = True

    # ------------------------------------------------------------------
    # Registradores
    # ------------------------------------------------------------------
    def ler_div(self):
        """
        FF04 — o byte alto do contador interno.

        Como sobe sozinho e nunca para, o DIV é a fonte de aleatoriedade mais
        usada nos jogos de Game Boy. Um console sem relógio e sem entrada
        aleatória não tem de onde tirar imprevisibilidade; ler o DIV no instante
        em que o jogador apertou o botão é imprevisível o bastante.
        """
        return (self.contador >> 8) & 0xFF

    def escrever_div(self):
        """
        FF04 — qualquer escrita zera o contador. O valor escrito é ignorado.

        Esta função não recebe parâmetro de propósito: `LD A,$42` seguido de
        `LD ($FF04),A` significa "zere o DIV", e não "ponha 0x42 no DIV".

        A chamada a `_avaliar_borda` logo abaixo é o comportamento descrito no
        topo do arquivo: zerar o contador pode criar uma borda de descida e
        incrementar o TIMA sem que ninguém tenha pedido.
        """
        self.contador = 0
        self._avaliar_borda()

    def ler_tima(self):
        """FF05 — o contador que estoura."""
        return self.tima

    def escrever_tima(self, val):
        """
        FF05 — grava um novo valor, exceto durante a janela de recarga.

        Se a escrita cai no M-cycle exato em que o TMA está sendo carregado, o
        hardware a engole: o valor escrito some, e o TIMA fica com o TMA.

        Fora dessa janela, escrever CANCELA um estouro que ainda não recarregou.
        Faz sentido: se o programa acabou de pôr um valor novo ali, a recarga
        pendente diz respeito a um número que não existe mais.
        """
        if self.recarregando:
            return
        self.tima = val & 0xFF
        self.recarga_pendente = False

    def ler_tma(self):
        """FF06 — o valor com que o TIMA recomeça."""
        return self.tma

    def escrever_tma(self, val):
        """
        FF06 — grava o valor de recomeço.

        Com uma exceção de um M-cycle: escrever no TMA exatamente durante a
        recarga muda também o TIMA, porque o valor novo chega a tempo de ser o
        que está sendo copiado.
        """
        self.tma = val & 0xFF
        if self.recarregando:
            self.tima = self.tma

    def ler_tac(self):
        """
        FF07 — controle. Só os 3 bits de baixo existem.

        Os bits 3 a 7 não têm fiação e leem sempre 1, daí o `| 0xF8`. Devolver
        zero neles pareceria mais limpo e estaria errado — há teste que confere.
        """
        return self.tac | 0xF8

    def escrever_tac(self, val):
        """
        FF07 — liga/desliga o timer (bit 2) e escolhe a frequência (bits 0-1).

        A chamada a `_avaliar_borda` no fim é necessária porque trocar o bit
        vigiado, ou desligar o timer, pode fazer o sinal cair de 1 para 0 — e
        isso incrementa o TIMA, exatamente como a escrita no DIV. Mais um
        comportamento que sai de graça por modelar o detector de borda em vez de
        contar ciclos.
        """
        self.tac = val & 0x07
        self.habilitado = (self.tac & 0x04) != 0
        self.bit_sel = BIT_SELECIONADO[self.tac & 0x03]
        self._avaliar_borda()
