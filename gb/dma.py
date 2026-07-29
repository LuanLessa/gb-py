"""
A cópia automática da tabela de sprites.

Todo quadro, um jogo precisa atualizar a posição dos seus 40 sprites. Essa
informação mora na OAM, uma tabela de 160 bytes que a PPU lê enquanto desenha —
e que, por isso, quase nunca está disponível para a CPU escrever.

A solução do console é um DMA: "acesso direto à memória". O jogo prepara a
tabela nova num canto qualquer da memória, escreve um único byte em FF46, e o
hardware copia os 160 bytes sozinho, sem a CPU precisar mexer um dedo. São 160
M-cycles contra os mais de 600 que a cópia manual custaria.

O byte escrito em FF46 é o byte ALTO do endereço de origem. Escrever 0xC1 copia
de 0xC100 a 0xC19F. O byte baixo não é configurável: a origem sempre começa num
múltiplo de 0x100.


O PREÇO
-------

Enquanto a cópia acontece, o DMA é o dono do barramento. A CPU continua
executando, mas tudo que ela tenta ler da memória externa devolve 0xFF — ROM
inclusive, o que significa que ela nem consegue buscar a próxima instrução.

A saída é a HRAM, os 127 bytes que ficam dentro do próprio processador e não
passam pelo barramento externo. Por isso TODO jogo de Game Boy copia uma
rotininha de espera para a HRAM e a chama logo depois de disparar o DMA:

    ld a, $C1
    ld ($FF46), a      ; dispara a cópia
    ld a, 40
    espera:            ; esta rotina precisa estar NA HRAM
      dec a
      jr nz, espera

Se essa rotina ficasse na ROM, a CPU leria 0xFF em vez das instruções e o
console travaria. É um dos poucos casos em que a organização física da memória
aparece diretamente no código de um jogo.
"""


class DMA:
    def __init__(self, bus):
        self.bus = bus
        self.origem = 0          # o byte alto do endereço de origem (FF46)
        self.ativo = False
        self.indice = 0          # próximo byte a copiar, de 0 a 159
        self.atraso = 0          # M-cycles que faltam para a cópia começar

    # ------------------------------------------------------------------
    def escrever(self, val):
        """
        FF46 — agenda uma transferência.

        A cópia não começa neste instante. O hardware leva cerca de um M-cycle
        para engatar, e durante essa folga a CPU ainda enxerga o barramento
        normalmente. O atraso é curto, mas mensurável, e as ROMs de teste de DMA
        conferem exatamente isso.
        """
        self.origem = val & 0xFF
        self.atraso = 2
        self.indice = 0

    def ler(self):
        """FF46 — devolve o último valor escrito."""
        return self.origem

    # ------------------------------------------------------------------
    def step(self):
        """
        Avança 1 M-cycle da transferência: exatamente um byte por vez.

        Copiar tudo de uma vez e depois "gastar" 160 M-cycles daria o mesmo
        resultado final e estaria errado no meio do caminho. A CPU continua
        rodando durante a cópia, e um jogo pode perfeitamente ler a OAM enquanto
        ela acontece — encontrando a tabela pela metade, com os primeiros
        sprites já atualizados e os últimos ainda velhos.
        """
        if self.atraso:
            self.atraso -= 1
            if self.atraso == 0:
                self.ativo = True
                self.indice = 0
            return

        if not self.ativo:
            return

        # A leitura passa por `ler_para_dma`, que ignora os bloqueios de VRAM e
        # de OAM. Seria absurdo o DMA bloquear a si mesmo.
        end = (self.origem << 8) | self.indice
        self.bus.ppu.oam[self.indice] = self.bus.ler_para_dma(end)

        self.indice += 1
        if self.indice >= 0xA0:      # 160 bytes copiados: acabou
            self.ativo = False

    # ------------------------------------------------------------------
    def bloqueia(self, addr):
        """
        Este endereço está inacessível para a CPU por causa da cópia?

        Só a HRAM escapa, porque ela é interna ao processador. O registrador IE
        (FFFF) também, por estar dentro da mesma faixa.
        """
        return self.ativo and not (0xFF80 <= addr <= 0xFFFE)
