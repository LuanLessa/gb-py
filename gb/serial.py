"""
A porta serial — o cabo que ligava dois Game Boys.

Era por aqui que se trocavam Pokémon. Dois consoles ligados por um cabo, um
byte de cada vez: o registrador SB (FF01) guarda o byte, e a cada pulso de
relógio um bit sai por uma ponta enquanto outro entra pela outra. Depois de oito
pulsos, os dois consoles trocaram um byte inteiro — cada um agora tem o do
outro.

O SC (FF02) controla, e dois bits dele importam:

    bit 7   começa a transferência
    bit 0   quem manda o relógio: 1 é este console, 0 é o outro

Como só um dos dois pode mandar o relógio, um cabo funciona com um console
configurado como "interno" e o outro como "externo".


SEM CABO, E MESMO ASSIM ÚTIL
----------------------------

Sem nada conectado, a linha de dados fica solta e o console lê só bits 1. Mas a
transferência ACONTECE assim mesmo, desde que ele esteja usando o relógio
interno: oito bits a 8192 Hz, um a cada 512 T-cycles, e no fim a interrupção
sai normalmente.

Esse detalhe é o que transforma a porta serial no terminal de depuração do Game
Boy. O console não tem tela de texto nem jeito de imprimir nada, mas escrever um
caractere no SB e disparar a transferência é observável de fora — e é
exatamente o que todas as ROMs de teste da Blargg fazem para relatar o
resultado, letra por letra. O `harness.py` dos testes lê daqui.

Com o relógio EXTERNO e nenhum cabo, o console fica esperando um pulso que
nunca vem, e a transferência nunca termina. Também é o comportamento real.
"""

IRQ_SERIAL = 0x08

# Um bit por 512 T-cycles dá 8192 bits por segundo — a velocidade do relógio
# interno. Um byte inteiro leva 4096 T-cycles, quase um vigésimo de quadro.
T_POR_BIT = 512


class Serial:
    def __init__(self, bus):
        self.bus = bus
        self.sb = 0x00        # FF01 — o byte sendo trocado
        self.sc = 0x7E        # FF02 — controle
        self.transferindo = False
        self.bits_restantes = 0
        self.contador = 0

        # Tudo que o console mandou pela porta desde que ligou. Não faz parte do
        # hardware: é o gravador que permite aos testes lerem o que a ROM disse.
        self.saida = bytearray()

    # ------------------------------------------------------------------
    def step(self):
        """
        Avança 1 M-cycle da transferência em curso.

        O deslocamento é o mecanismo de verdade: a cada pulso, o SB anda um bit
        para a esquerda. O bit que sai pela esquerda iria para o cabo, e o que
        entra pela direita viria do outro console — sem cabo, entra 1, porque é
        assim que uma linha solta é lida.

        Depois de oito pulsos o byte original saiu inteiro e o SB ficou com
        0xFF. Um jogo que dependesse da resposta veria "nada conectado".
        """
        if not self.transferindo:
            return

        self.contador += 4
        while self.contador >= T_POR_BIT:
            self.contador -= T_POR_BIT

            self.sb = ((self.sb << 1) | 0x01) & 0xFF
            self.bits_restantes -= 1

            if self.bits_restantes == 0:
                self.transferindo = False
                self.sc &= 0x7F                 # o bit 7 se apaga sozinho ao fim
                self.bus.if_ |= IRQ_SERIAL
                break

    # ------------------------------------------------------------------
    def ler_sb(self):
        """FF01 — o byte em trânsito."""
        return self.sb

    def escrever_sb(self, val):
        """FF01 — carrega o byte a enviar."""
        self.sb = val & 0xFF

    def ler_sc(self):
        """FF02 — controle. Os bits 1 a 6 não existem e leem 1."""
        return self.sc | 0x7E

    def escrever_sc(self, val):
        """
        FF02 — pode disparar uma transferência.

        O byte é registrado em `saida` IMEDIATAMENTE, e não ao fim dos 4096
        T-cycles. É uma concessão deliberada: o gravador não faz parte do
        hardware, e adiar o registro só atrasaria o que os testes leem sem mudar
        nada do que o jogo observa. A contagem dos oito bits e a interrupção
        continuam sendo emuladas com o tempo certo.
        """
        self.sc = val & 0xFF

        if (val & 0x81) == 0x81:
            # Bit 7 e bit 0 ligados: começar, com o relógio deste console.
            self.saida.append(self.sb)
            self.transferindo = True
            self.bits_restantes = 8
            self.contador = 0
        elif val & 0x80:
            # Começar com o relógio do OUTRO console. Sem cabo, nenhum pulso
            # chega e a transferência simplesmente nunca anda.
            self.transferindo = False
