"""
A PPU — o chip que desenha a tela.

Uma placa de vídeo moderna recebe uma imagem pronta e a mostra. A PPU do Game
Boy não tem memória para isso: uma tela de 160x144 com 2 bits por pixel ocuparia
5.760 bytes, e o console inteiro tem 8.192 de memória de trabalho. Guardar a
imagem seria gastar quase tudo com uma coisa só.

A saída é não guardar imagem nenhuma. A PPU monta a tela LINHA POR LINHA, na
hora, e cada linha é jogada fora assim que passa. O que fica guardado é a
receita: um catálogo de desenhos de 8x8 e um mapa dizendo onde cada um vai.


TILES: O CATÁLOGO DE DESENHOS
-----------------------------

Um tile é um quadradinho de 8x8 pixels, e cada pixel tem 4 valores possíveis —
os quatro tons do console. Dois bits por pixel, 64 pixels, 16 bytes por tile.

O formato de armazenamento é o que confunde de primeira. Os dois bits de um
pixel NÃO ficam juntos: o tile é guardado como dois "planos" entrelaçados, dois
bytes por linha. O primeiro byte tem o bit de baixo dos oito pixels; o segundo,
o bit de cima.

    byte 0:  0 1 1 1 1 1 1 0     ← bits de baixo dos 8 pixels
    byte 1:  0 0 1 1 1 1 0 0     ← bits de cima
             ─────────────────
    pixel:   0 1 3 3 3 3 1 0     ← a cor de cada um, montada dos dois

Parece complicação gratuita e não é: assim o chip lê os dois bytes de uma vez e
extrai os oito pixels em paralelo, um bit de cada byte por vez.

A função `linha_de_tile` faz essa desmontagem, e o resultado fica em cache
porque os mesmos tiles reaparecem o tempo todo.


O MAPA: ONDE CADA TILE VAI
--------------------------

O fundo é uma grade de 32x32 tiles — 256x256 pixels, bem maior que a tela. Cada
posição do mapa guarda um byte: o número do tile que vai ali.

A tela mostra uma JANELA de 160x144 dentro dessa grade, e os registradores SCX e
SCY dizem onde essa janela está. Mudar SCX de 1 em 1 rola o cenário suavemente,
sem redesenhar nada — a memória continua igual, só o recorte se move. É assim
que praticamente todo jogo de plataforma do console rola a tela.

A grade dá a volta: passar do fim volta ao começo, o que faz um cenário
repetitivo rolar para sempre com 1 KB de mapa.


SPRITES: O QUE SE MEXE POR CIMA
-------------------------------

Personagens e objetos não fazem parte do mapa — se fizessem, movê-los exigiria
reescrever o cenário toda vez. Eles são sprites: até 40 desenhos com posição
própria, listados numa tabela de 160 bytes chamada OAM, quatro bytes cada.

    byte 0   posição Y (com 16 somados)
    byte 1   posição X (com 8 somados)
    byte 2   número do tile
    byte 3   atributos: paleta, espelhamento, prioridade

Os deslocamentos de 16 e 8 existem para permitir que um sprite entre em cena
pela borda: com Y=0 ele está totalmente escondido acima da tela.

E há um limite que se vê jogando: a PPU só consegue desenhar 10 sprites por
linha. O décimo primeiro simplesmente não aparece. É por isso que jogos antigos
piscam personagens quando há gente demais na mesma altura da tela — não é bug do
jogo, é o hardware chegando ao limite.


OS MODOS, E POR QUE A CPU FICA DE FORA
--------------------------------------

Cada linha da tela dura exatamente 456 dots — e um dot é um T-cycle. A PPU passa
por três fases:

    Modo 2   80 dots      procura quais sprites aparecem nesta linha
    Modo 3   172+ dots    desenha os pixels de verdade
    Modo 0   o que sobrar descanso até a linha seguinte (H-Blank)

Durante os modos 2 e 3 a PPU está usando a memória de vídeo, e a CPU é
BLOQUEADA: qualquer leitura devolve 0xFF e qualquer escrita é descartada. Não é
proteção de software, é disputa física pelo mesmo barramento.

Depois das 144 linhas visíveis vêm 10 linhas de Modo 1, o V-Blank — herança da
TV de tubo, que precisava desse tempo para levar o feixe de volta ao topo. Como
não há nada a desenhar, a memória de vídeo fica livre, e é nessa janela que todo
jogo faz suas atualizações gráficas.

    154 linhas x 456 dots = 70.224 dots por quadro ≈ 59,7 quadros por segundo
"""

LARGURA = 160
ALTURA = 144

DOTS_POR_LINHA = 456
LINHAS_TOTAIS = 154          # 144 visíveis + 10 de V-Blank
DOTS_MODO2 = 80
DOTS_MODO3_BASE = 172        # o mínimo; a duração real varia (ver _duracao_modo3)

# Em que dot a varredura recomeça quando o vídeo é ligado. Ver `PPU._ligar`.
DOTS_AO_LIGAR = 4

IRQ_VBLANK = 0x01
IRQ_STAT = 0x02

# Os quatro tons da DMG em RGB, do mais claro para o mais escuro. O verde não é
# licença poética: a tela original era um LCD sobre fundo verde-oliva.
PALETA_DMG = (0xE0F8D0, 0x88C070, 0x346856, 0x081820)


# ----------------------------------------------------------------------
# Tabelas e caches
# ----------------------------------------------------------------------
#
# As três estruturas abaixo existem por velocidade, e valem a pena pelo mesmo
# motivo: um jogo desenha os MESMOS tiles milhares de vezes por segundo. Calcular
# tudo de novo a cada vez é trabalho jogado fora.

def _tabela_de_traducao(paleta):
    """
    Transforma um registrador de paleta numa tabela de 256 posições.

    Uma paleta é um byte que diz qual tom cada uma das quatro cores vira: dois
    bits por cor. O jogo mexe nisso para fazer flashes, escurecer a tela e
    animar água — trocar a paleta recolore tudo instantaneamente, sem tocar num
    único pixel da memória.

    A tabela permite aplicar a paleta em 8 pixels de uma vez com
    `bytes.translate()`, que roda em C. Traduzir pixel a pixel em Python seria
    umas vinte vezes mais lento.
    """
    t = bytearray(256)
    for cor in range(4):
        t[cor] = (paleta >> (cor * 2)) & 0x03
    return bytes(t)


# Uma tabela pronta para cada um dos 256 valores possíveis de paleta.
TRADUCAO = tuple(_tabela_de_traducao(p) for p in range(256))

# Linhas de tile já desmontadas: os dois bytes entrelaçados viram 8 índices de
# cor. A chave junta os dois bytes num inteiro só.
_CACHE_LINHA = {}

# A mesma coisa, já invertida, para sprites espelhados na horizontal.
_CACHE_LINHA_ESPELHADA = {}


def linha_de_tile(b0, b1):
    """
    Desmonta os dois bytes de uma linha de tile nos 8 índices de cor.

    A conta faz o que o desenho do topo do arquivo mostra: para cada uma das 8
    posições, pega o bit correspondente de cada byte e os junta, com o bit de
    `b1` valendo 2 e o de `b0` valendo 1.

    O `7 - i` existe porque o pixel mais à esquerda é o bit MAIS ALTO do byte —
    a ordem de leitura na tela é a inversa da numeração dos bits.
    """
    chave = (b1 << 8) | b0
    linha = _CACHE_LINHA.get(chave)
    if linha is None:
        linha = bytes((((b1 >> (7 - i)) & 1) << 1) | ((b0 >> (7 - i)) & 1)
                      for i in range(8))
        _CACHE_LINHA[chave] = linha
    return linha


def linha_de_tile_espelhada(b0, b1):
    """A mesma linha, invertida — para sprites virados na horizontal."""
    chave = (b1 << 8) | b0
    linha = _CACHE_LINHA_ESPELHADA.get(chave)
    if linha is None:
        linha = linha_de_tile(b0, b1)[::-1]
        _CACHE_LINHA_ESPELHADA[chave] = linha
    return linha


# Linhas de tile com a paleta JÁ aplicada, prontas para copiar no framebuffer.
# A chave junta paleta e padrão num único inteiro: usar uma tupla como chave
# alocaria um objeto por consulta, que é justamente o que este cache evita.
_CACHE_TRADUZIDA = {}
_LIMITE_DO_CACHE = 1 << 16


def linha_traduzida(chave, paleta):
    """
    Os 8 pixels de um tile, desmontados e paletizados.

    Este cache nasceu de um problema medido, não de suposição. Sem ele, cada
    tile desenhado alocava dois objetos: a fatia da linha e o resultado do
    `translate()`. São vinte tiles por linha, 144 linhas por quadro, 60 quadros
    por segundo — mais de trezentos mil objetos por segundo indo para o coletor
    de lixo, que os devolvia na forma de engasgos de dezenas de milissegundos no
    meio do jogo.

    Com o cache, o caso comum — um tile alinhado à grade — não aloca nada.

    O limite de tamanho protege contra um jogo que troque de paleta a cada
    linha: sem ele, o cache cresceria sem parar guardando combinações que nunca
    mais se repetem.
    """
    k = (paleta << 16) | chave
    linha = _CACHE_TRADUZIDA.get(k)
    if linha is None:
        if len(_CACHE_TRADUZIDA) > _LIMITE_DO_CACHE:
            _CACHE_TRADUZIDA.clear()
        linha = linha_de_tile(chave & 0xFF, chave >> 8).translate(TRADUCAO[paleta])
        _CACHE_TRADUZIDA[k] = linha
    return linha


class PPU:
    def __init__(self, bus):
        self.bus = bus

        self.vram = bytearray(0x2000)   # 8 KB: os tiles e os dois mapas
        self.oam = bytearray(0xA0)      # 160 bytes: a tabela dos 40 sprites

        # --- Registradores, todos em FF40-FF4B ---
        self.lcdc = 0x91     # o painel de controle: liga/desliga cada camada
        self.stat = 0x00     # estado atual e quais eventos geram interrupção
        self.scy = 0         # rolagem vertical do fundo
        self.scx = 0         # rolagem horizontal do fundo
        self.ly = 0          # linha sendo desenhada agora (0 a 153)
        self.lyc = 0         # linha em que o jogo quer ser avisado
        self.bgp = 0xFC      # paleta do fundo
        self.obp0 = 0xFF     # paleta 0 dos sprites
        self.obp1 = 0xFF     # paleta 1 dos sprites
        self.wy = 0          # posição vertical da janela
        self.wx = 0          # posição horizontal da janela (com 7 somados)

        # --- Estado interno ---
        self.dot = 0                       # posição dentro da linha (0 a 455)
        self.modo = 2
        self.fim_modo3 = DOTS_MODO2 + DOTS_MODO3_BASE

        # Em vez de conferir a cada passo em que modo estamos, a PPU calcula
        # com antecedência o dot do PRÓXIMO evento. O caminho comum vira uma
        # soma e uma comparação. Ver `step`.
        self.proximo_evento = DOTS_MODO2

        # A janela tem um contador de linhas próprio, que só anda nas linhas em
        # que ela aparece. Não dá para usar o LY: se a janela começa na linha
        # 100, ela precisa desenhar a partir da sua PRÓPRIA primeira linha.
        self.linha_janela = 0
        self.janela_ativa_na_linha = False

        # Estado anterior da linha de interrupção do STAT. Guardar isso é o que
        # implementa o "STAT blocking" — ver `_atualizar_stat`.
        self.linha_stat = False

        self.ligado = True
        self.frame_pronto = False

        # Quando False, a PPU emula tudo normalmente mas não gasta tempo
        # pintando pixels. Serve para pular quadros de VÍDEO sem alterar nada da
        # emulação — o frontend usa isso quando a máquina não acompanha.
        self.renderizar = True

        # A imagem sendo montada: um byte por pixel, com o índice de cor já
        # paletizado. Quem converte para RGB é o frontend.
        self.framebuffer = bytearray(LARGURA * ALTURA)

        # Os índices de cor do fundo ANTES da paleta, só da linha atual. São
        # necessários para a prioridade dos sprites, que compara com "cor 0" —
        # e a cor 0 depois da paleta pode ser qualquer tom.
        self._cor_bg_linha = bytearray(LARGURA)

        self._sprites_linha = []

    # ==================================================================
    # Passagem do tempo
    # ==================================================================
    def step(self):
        """
        Avança 4 dots (1 M-cycle).

        Roda mais de um milhão de vezes por segundo emulado, então o caminho
        comum precisa ser muito barato: uma soma e uma comparação. Toda a lógica
        pesada — trocar de modo, avaliar interrupções, desenhar — só acontece
        quando o dot alcança o evento previsto.

        Este método tem uma cópia inline dentro de `Machine.tick4`, pelo motivo
        explicado lá.
        """
        self.dot += 4
        if self.dot >= self.proximo_evento:
            self._processar_evento()

    def _processar_evento(self):
        """Chegou a hora marcada: descobre o que acontece e marca a próxima."""
        if self.dot >= DOTS_POR_LINHA:
            self.dot -= DOTS_POR_LINHA
            self._proxima_linha()
        elif self.modo == 2:
            self._entrar_modo3()
        elif self.modo == 3:
            # A linha inteira é desenhada de uma vez, no fim do modo 3. O
            # hardware a empurra pixel a pixel ao longo do modo, mas o resultado
            # visível é o mesmo — e ninguém consegue observar a diferença,
            # porque a CPU está bloqueada da memória de vídeo justamente aqui.
            self._desenhar_linha()
            self._mudar_modo(0)
            self.proximo_evento = DOTS_POR_LINHA
        else:
            self.proximo_evento = DOTS_POR_LINHA
        self._atualizar_stat()

    def _proxima_linha(self):
        """Terminou uma linha. Decide o que vem depois."""
        self.ly += 1

        if self.ly == ALTURA:
            # A linha 144 é a primeira invisível: o quadro acabou de ficar
            # pronto. É aqui que a interrupção de V-Blank sai, e é ela que
            # acorda o jogo para atualizar os gráficos.
            self._mudar_modo(1)
            self.bus.if_ |= IRQ_VBLANK
            self.frame_pronto = True
            self.proximo_evento = DOTS_POR_LINHA
        elif self.ly >= LINHAS_TOTAIS:
            # Fim das 154 linhas: volta ao topo da tela.
            self.ly = 0
            self.linha_janela = 0
            self._mudar_modo(2)
            self.proximo_evento = DOTS_MODO2
        elif self.ly < ALTURA:
            self._mudar_modo(2)
            self.proximo_evento = DOTS_MODO2
        else:
            self.proximo_evento = DOTS_POR_LINHA    # ainda no V-Blank

    def _entrar_modo3(self):
        """Fim da busca de sprites; começa o desenho."""
        self._buscar_sprites()
        self.fim_modo3 = DOTS_MODO2 + self._duracao_modo3()
        self._mudar_modo(3)
        self.proximo_evento = self.fim_modo3

    def _duracao_modo3(self):
        """
        Quanto tempo o desenho desta linha vai levar.

        O modo 3 não tem duração fixa, e o tempo que ele toma a mais sai do
        H-Blank seguinte — a linha inteira continua com 456 dots. Três coisas o
        alongam:

        ROLAGEM FINA. Quando SCX não é múltiplo de 8, a linha começa no meio de
        um tile, e os primeiros pixels precisam ser buscados e descartados. Cada
        pixel descartado custa um dot.

        JANELA. Ligá-la no meio da linha obriga a PPU a esvaziar a fila de
        pixels do fundo e recomeçar, o que custa 6 dots.

        SPRITES. Cada sprite na linha custa de 6 a 11 dots, conforme o
        alinhamento dele com a grade de tiles.

        Isso importa porque jogos usam a interrupção de H-Blank para efeitos que
        mudam o cenário no meio da tela. Se o emulador erra o instante em que o
        modo 3 termina, o efeito sai na altura errada.
        """
        dur = DOTS_MODO3_BASE + (self.scx & 7)

        if (self.lcdc & 0x20) and self.wy <= self.ly and self.wx <= 166:
            dur += 6

        for _, sx, _, _ in self._sprites_linha:
            # Aproximação, mas fiel ao formato: sprites alinhados à grade custam
            # menos do que sprites no meio de um tile.
            dur += 11 - min(5, (sx + self.scx) & 7)

        return dur

    # ==================================================================
    # STAT e interrupções
    # ==================================================================
    def _mudar_modo(self, modo):
        """Troca o modo, mantendo os bits de configuração do STAT intactos."""
        self.modo = modo
        self.stat = (self.stat & 0xFC) | modo

    def _atualizar_stat(self):
        """
        Decide se a interrupção de STAT deve sair agora.

        O STAT permite ao jogo pedir aviso em quatro situações: entrada em cada
        um dos três modos, e chegada a uma linha específica (LY == LYC). A
        segunda é a mais usada — é com ela que se muda a paleta ou a rolagem no
        meio da tela, criando efeitos que o hardware sozinho não faria.

        O detalhe que dá nome a um bug famoso é o seguinte: as quatro fontes não
        são independentes. Elas são combinadas num OU, e a interrupção só sai na
        BORDA DE SUBIDA desse sinal combinado — quando ele passa de desligado
        para ligado.

        A consequência é que, se duas fontes ficam ativas ao mesmo tempo, sai UMA
        interrupção só. E se uma fonte já estava mantendo o sinal ligado, a
        segunda não gera nada. Isso se chama "STAT blocking", e jogos dependem
        dele: sem o bloqueio, alguns recebem interrupções demais e piscam.

        É o mesmo mecanismo de detecção de borda do timer, e pela mesma razão —
        é assim que se detecta uma mudança em vez de um estado.
        """
        coincide = self.ly == self.lyc
        if coincide:
            self.stat |= 0x04
        else:
            self.stat &= ~0x04

        linha = ((self.stat & 0x40) and coincide) or \
                ((self.stat & 0x20) and self.modo == 2) or \
                ((self.stat & 0x10) and self.modo == 1) or \
                ((self.stat & 0x08) and self.modo == 0)
        linha = bool(linha)

        if linha and not self.linha_stat:
            self.bus.if_ |= IRQ_STAT
        self.linha_stat = linha

    # ==================================================================
    # Busca de sprites (modo 2)
    # ==================================================================
    def _buscar_sprites(self):
        """
        Percorre os 40 sprites e separa os que cruzam a linha atual.

        O `break` no décimo não é otimização: é o limite do hardware. A PPU tem
        espaço para exatamente 10 sprites por linha, e o décimo primeiro é
        ignorado — daí os personagens piscando em jogos com muita coisa na tela.

        Como a varredura é feita na ordem da tabela, quem chega primeiro fica.
        Um jogo pode escolher quem tem prioridade só pela posição na OAM.
        """
        self._sprites_linha = []
        if not (self.lcdc & 0x02):       # sprites desligados no LCDC
            return

        altura = 16 if (self.lcdc & 0x04) else 8
        ly = self.ly
        oam = self.oam

        for i in range(0, 160, 4):       # 4 bytes por sprite
            sy = oam[i] - 16             # desfaz o deslocamento do formato
            if not (sy <= ly < sy + altura):
                continue
            sx = oam[i + 1] - 8
            self._sprites_linha.append((sy, sx, oam[i + 2], oam[i + 3]))
            if len(self._sprites_linha) == 10:
                break

    # ==================================================================
    # Desenho da linha
    # ==================================================================
    def _janela_aparece_nesta_linha(self):
        """
        A janela está visível nesta linha?

        A janela é uma segunda camada, que não rola junto com o fundo. Serve
        para painéis fixos: a barra de vida no topo, a caixa de diálogo embaixo.
        Ela sempre aparece por cima do fundo e começa sempre do seu próprio
        canto superior esquerdo.

        Esta pergunta está numa função separada porque o contador
        `linha_janela` depende dela — e precisa continuar andando mesmo quando o
        desenho é pulado, senão a janela sai deslocada quando a renderização
        voltar.
        """
        return ((self.lcdc & 0x21) == 0x21           # fundo e janela ligados
                and self.wy <= self.ly
                and self.wx <= 166
                and (self.wx - 7) < LARGURA)

    def _desenhar_linha(self):
        """Monta uma linha da imagem: primeiro o fundo, depois os sprites."""
        if not self.renderizar:
            # Pular o desenho não muda NADA do estado emulado: a CPU, os tempos
            # e as interrupções seguem idênticos, e o jogo não tem como
            # perceber. A única coisa que não pode ser pulada é o contador da
            # janela, que é estado real da PPU e afeta os quadros seguintes.
            if self._janela_aparece_nesta_linha():
                self.linha_janela += 1
            return

        base = self.ly * LARGURA

        if self.lcdc & 0x01:
            self._desenhar_fundo(base)
        else:
            # Com o bit 0 do LCDC desligado, o fundo e a janela somem, e no seu
            # lugar fica a cor 0 da paleta.
            for x in range(LARGURA):
                self._cor_bg_linha[x] = 0
                self.framebuffer[base + x] = self.bgp & 0x03

        if self.lcdc & 0x02:
            self._desenhar_sprites(base)

    def _desenhar_fundo(self, base):
        """
        Desenha o fundo e a janela desta linha, um TILE de cada vez.

        Trabalhar por tile, e não por pixel, é o que a PPU real faz: ela busca
        um tile, desmonta os 8 pixels e empurra todos para a fila de uma vez.
        Aqui a vantagem é a mesma — o laço fica oito vezes mais curto, e a
        paleta pode ser aplicada no bloco inteiro com `translate()`.

        O trecho é o mais quente do emulador depois do `tick4`, e por isso está
        escrito com as variáveis puxadas para locais e sem chamadas de função no
        caminho comum.
        """
        vram = self.vram
        fb = self.framebuffer
        cores_bg = self._cor_bg_linha
        bgp = self.bgp
        traducao = TRADUCAO[bgp]

        # Onde os tiles estão guardados. O LCDC escolhe entre dois esquemas de
        # endereçamento, e a diferença é o tipo do índice: no modo 0x8000 ele é
        # um número comum de 0 a 255; no modo 0x8800 ele é COM SINAL, de -128 a
        # 127, contado a partir de 0x9000. Ter dois esquemas permite que fundo e
        # sprites usem catálogos parcialmente diferentes.
        modo_8000 = (self.lcdc & 0x10) != 0

        # E onde está o mapa. São dois, e o LCDC escolhe qual vale para o fundo
        # e qual vale para a janela — trocar de mapa permite montar a tela
        # seguinte enquanto a atual ainda aparece.
        mapa_bg = 0x1C00 if (self.lcdc & 0x08) else 0x1800
        mapa_jn = 0x1C00 if (self.lcdc & 0x40) else 0x1800

        janela = (self.lcdc & 0x20) != 0 and self.wy <= self.ly and self.wx <= 166
        # O WX tem 7 somados por causa de como o hardware conta: WX=7 é a
        # margem esquerda da tela, e valores menores empurram a janela para fora.
        wx_inicio = self.wx - 7
        fim_bg = LARGURA
        if janela and wx_inicio < LARGURA:
            fim_bg = wx_inicio if wx_inicio > 0 else 0

        # ---------------- Fundo ----------------
        # `& 0xFF` faz a grade dar a volta: passar do fim do mapa retorna ao
        # começo, e o cenário se repete sem custo nenhum.
        y = (self.ly + self.scy) & 0xFF
        # `y >> 3` é a linha de TILES (dividir por 8); `<< 5` multiplica por 32,
        # que é a largura do mapa em tiles.
        base_mapa = mapa_bg + ((y >> 3) << 5)
        # Dentro do tile, cada linha ocupa 2 bytes.
        deslocamento = (y & 7) << 1

        x = 0
        col = self.scx & 0xFF
        while x < fim_bg:
            n = vram[base_mapa + (col >> 3)]
            end = (n << 4) if modo_8000 else 0x1000 + ((n ^ 0x80) - 0x80) * 16
            b0 = vram[end + deslocamento]
            b1 = vram[end + deslocamento + 1]
            chave = (b1 << 8) | b0
            linha = _CACHE_LINHA.get(chave) or linha_de_tile(b0, b1)

            # Quantos pixels deste tile entram na tela. Só o primeiro e o último
            # da linha costumam ficar cortados, por causa da rolagem fina.
            dentro = col & 7
            quantos = 8 - dentro
            if x + quantos > fim_bg:
                quantos = fim_bg - x

            if dentro == 0 and quantos == 8:
                # Tile inteiro e alinhado à grade — o caso comum, e o único que
                # não aloca nada: as duas linhas abaixo são cópias de bloco.
                cores_bg[x:x + 8] = linha
                fb[base + x:base + x + 8] = linha_traduzida(chave, bgp)
            else:
                pedaco = linha[dentro:dentro + quantos]
                cores_bg[x:x + quantos] = pedaco
                fb[base + x:base + x + quantos] = pedaco.translate(traducao)

            x += quantos
            col = (col + quantos) & 0xFF

        # ---------------- Janela ----------------
        if not janela or fim_bg >= LARGURA:
            return

        # A janela não usa SCX nem SCY: ela sempre começa do seu próprio canto
        # superior esquerdo, e por isso tem contador de linha próprio.
        y = self.linha_janela
        base_mapa = mapa_jn + ((y >> 3) << 5)
        deslocamento = (y & 7) << 1

        x = fim_bg
        col = fim_bg - wx_inicio
        while x < LARGURA:
            n = vram[base_mapa + ((col >> 3) & 31)]
            end = (n << 4) if modo_8000 else 0x1000 + ((n ^ 0x80) - 0x80) * 16
            b0 = vram[end + deslocamento]
            b1 = vram[end + deslocamento + 1]
            chave = (b1 << 8) | b0
            linha = _CACHE_LINHA.get(chave) or linha_de_tile(b0, b1)

            dentro = col & 7
            quantos = 8 - dentro
            if x + quantos > LARGURA:
                quantos = LARGURA - x

            if dentro == 0 and quantos == 8:
                cores_bg[x:x + 8] = linha
                fb[base + x:base + x + 8] = linha_traduzida(chave, bgp)
            else:
                pedaco = linha[dentro:dentro + quantos]
                cores_bg[x:x + quantos] = pedaco
                fb[base + x:base + x + quantos] = pedaco.translate(traducao)

            x += quantos
            col += quantos

        # O contador só avança nas linhas em que a janela apareceu de fato.
        self.linha_janela += 1

    def _desenhar_sprites(self, base):
        """
        Desenha os sprites desta linha por cima do fundo.

        Duas regras decidem o que fica visível quando as coisas se sobrepõem.

        ENTRE SPRITES, na DMG, ganha o de menor X; havendo empate, o que vier
        antes na tabela. Como aqui o desenho é por sobrescrita, a lista é
        percorrida do MENOS para o MAIS prioritário — X maior primeiro — e o
        vencedor acaba pintando por último.

        ENTRE SPRITE E FUNDO, o bit 7 dos atributos decide. Ligado, o sprite
        passa a ficar ATRÁS de qualquer pixel de fundo que não seja da cor 0. É
        assim que um personagem some atrás de um arbusto.
        """
        vram = self.vram
        fb = self.framebuffer
        cores_bg = self._cor_bg_linha
        altura = 16 if (self.lcdc & 0x04) else 8

        # A ordenação usa tuplas de números negativos em vez de `key=lambda`:
        # comparar tuplas roda em C, enquanto o lambda seria chamado a cada
        # comparação. Os sinais invertem a ordem sem precisar de `reverse`.
        sprites = self._sprites_linha
        ordem = sorted((-s[1], -i) for i, s in enumerate(sprites))

        for menos_sx, menos_i in ordem:
            sy, sx, tile, flags = sprites[-menos_i]
            if sx <= -8 or sx >= LARGURA:
                continue                            # inteiramente fora da tela

            linha = self.ly - sy
            if flags & 0x40:                        # espelhado na vertical
                linha = altura - 1 - linha

            # Em modo 8x16 o sprite ocupa dois tiles seguidos, e o bit 0 do
            # número é ignorado — daí o `& 0xFE`, que arredonda para o par.
            n = tile & 0xFE if altura == 16 else tile
            end_tile = (n << 4) + (linha << 1)

            if flags & 0x20:                        # espelhado na horizontal
                pixels = linha_de_tile_espelhada(vram[end_tile], vram[end_tile + 1])
            else:
                pixels = linha_de_tile(vram[end_tile], vram[end_tile + 1])

            traducao = TRADUCAO[self.obp1 if (flags & 0x10) else self.obp0]
            atras_do_bg = (flags & 0x80) != 0

            # A faixa visível é recortada ANTES do laço, para não testar a borda
            # da tela oito vezes por sprite.
            ini = 0 if sx >= 0 else -sx
            fim = 8 if sx + 8 <= LARGURA else LARGURA - sx

            for px in range(ini, fim):
                cor = pixels[px]
                if cor == 0:
                    # Nos sprites a cor 0 não é uma cor: é transparência. Por
                    # isso um sprite só consegue mostrar três tons, e por isso
                    # a paleta de sprite tem o primeiro valor sem uso.
                    continue
                x = sx + px
                if atras_do_bg and cores_bg[x] != 0:
                    continue
                fb[base + x] = traducao[cor]

    # ==================================================================
    # O bug de corrupção da OAM
    # ==================================================================
    #
    # Este é um defeito de fábrica do Game Boy original, e um dos testes mais
    # duros que existem para um emulador.
    #
    # Durante o modo 2, a PPU lê a tabela de sprites em 20 "fileiras" de 8
    # bytes, uma a cada 4 dots. Nesse chip, a porta de endereço da OAM é
    # compartilhada com o barramento da CPU — e um erro de projeto faz o
    # seguinte: se a CPU incrementar ou decrementar um registrador de 16 bits
    # cujo valor esteja na faixa FE00-FEFF nesse exato momento, a fileira que a
    # PPU está lendo é EMBARALHADA.
    #
    # Não é curiosidade acadêmica. Jogos que percorriam a tabela de sprites com
    # `inc hl` sem esperar o V-Blank exibiam sprites piscando ou deformados, e a
    # Nintendo chegou a documentar o problema para os desenvolvedores.
    #
    # As três variantes abaixo diferem pela fórmula e pelas fileiras envolvidas,
    # conforme o tipo de acesso que a CPU fez. As fórmulas foram descobertas por
    # engenharia reversa, e não têm explicação elegante: são o que a lógica
    # elétrica produz quando dois sinais disputam a mesma linha.

    def _fileira_varrida(self):
        """Qual das 20 fileiras a PPU está lendo neste instante, ou None."""
        if not self.ligado or self.modo != 2:
            return None
        fileira = self.dot >> 2
        # A fileira 0 não tem antecessora, e todas as fórmulas dependem dela.
        if fileira < 1 or fileira > 19:
            return None
        return fileira

    def _palavra(self, endereco):
        """Lê 2 bytes da OAM como um valor de 16 bits."""
        return self.oam[endereco] | (self.oam[endereco + 1] << 8)

    def _gravar_palavra(self, endereco, valor):
        """Grava um valor de 16 bits em 2 bytes da OAM."""
        self.oam[endereco] = valor & 0xFF
        self.oam[endereco + 1] = (valor >> 8) & 0xFF

    def corrupcao_oam_escrita(self):
        """
        A variante disparada por `inc rr` e `dec rr` sobre a faixa FEXX.

        A primeira palavra da fileira vira `((a ^ c) & (b ^ c)) ^ c`, onde `a` é
        o valor atual dela, `b` é a primeira palavra da fileira anterior e `c` é
        a terceira. As outras três palavras são simplesmente copiadas da fileira
        anterior.
        """
        fileira = self._fileira_varrida()
        if fileira is None:
            return

        atual = fileira * 8
        anterior = atual - 8

        a = self._palavra(atual)
        b = self._palavra(anterior)
        c = self._palavra(anterior + 4)

        self._gravar_palavra(atual, ((a ^ c) & (b ^ c)) ^ c)
        self.oam[atual + 2:atual + 8] = self.oam[anterior + 2:anterior + 8]

    def corrupcao_oam_leitura_incremento(self):
        """
        A variante do `pop rr` — leitura, incremento e escrita.

        É a mais complicada das três, e envolve também a fileira de DUAS
        posições atrás: o ciclo de leitura e o de incremento pegam a tabela em
        momentos diferentes da varredura, e o resultado carrega traço dos dois.

        Acertar exatamente esta fórmula, e o instante em que ela dispara, foi o
        que fez a ROM `oam_bug` sair de reprovada para aprovada. Ver o comentário
        em `CPU.pop16`.
        """
        fileira = self._fileira_varrida()
        if fileira is None or fileira < 2:
            return

        atual = fileira * 8
        anterior = atual - 8
        retrasada = atual - 16

        a = self._palavra(atual)
        b = self._palavra(anterior)
        c = self._palavra(anterior + 4)
        d = self._palavra(retrasada)

        self._gravar_palavra(atual, (b & (a | c | d)) | (a & c & d))
        self.oam[atual + 2:atual + 8] = self.oam[anterior + 2:anterior + 8]

    def corrupcao_oam_leitura(self):
        """
        A variante das instruções que LEEM de FEXX e só depois avançam o
        ponteiro, como `ld a,(hl+)`. Aqui a fórmula é `b | (a & c)`.
        """
        fileira = self._fileira_varrida()
        if fileira is None:
            return

        atual = fileira * 8
        anterior = atual - 8

        a = self._palavra(atual)
        b = self._palavra(anterior)
        c = self._palavra(anterior + 4)

        self._gravar_palavra(atual, b | (a & c))
        self.oam[atual + 2:atual + 8] = self.oam[anterior + 2:anterior + 8]

    # ==================================================================
    # Acesso da CPU
    # ==================================================================
    #
    # Os quatro métodos abaixo são a disputa pelo barramento que dá nome ao
    # capítulo dos modos. Não é proteção de software: são dois chips querendo a
    # mesma memória, e a PPU ganha.

    def ler_vram(self, addr):
        """Durante o modo 3 a PPU está usando a memória; a CPU lê 0xFF."""
        if self.ligado and self.modo == 3:
            return 0xFF
        return self.vram[addr & 0x1FFF]

    def escrever_vram(self, addr, val):
        """Escritas durante o modo 3 são simplesmente descartadas."""
        if self.ligado and self.modo == 3:
            return
        self.vram[addr & 0x1FFF] = val

    def ler_oam(self, addr):
        """
        A tabela de sprites fica travada nos modos 2 e 3.

        São dois modos, e não um, porque a PPU usa a OAM já na busca de sprites.
        A cópia automática também tranca — durante o DMA, a OAM é dele.
        """
        if self.ligado and self.modo >= 2:
            return 0xFF
        if self.bus.dma.ativo:
            return 0xFF
        return self.oam[addr & 0xFF]

    def escrever_oam(self, addr, val):
        if self.ligado and self.modo >= 2:
            return
        if self.bus.dma.ativo:
            return
        self.oam[addr & 0xFF] = val

    # --- Registradores ---
    def ler_reg(self, addr):
        if addr == 0xFF40:
            return self.lcdc
        if addr == 0xFF41:
            # O bit 7 não existe e lê sempre 1. Com o vídeo desligado, os bits
            # de modo leem 0 — não há modo nenhum em curso.
            if not self.ligado:
                return (self.stat & 0xF8) | 0x80
            return self.stat | 0x80
        if addr == 0xFF42:
            return self.scy
        if addr == 0xFF43:
            return self.scx
        if addr == 0xFF44:
            # LY é o registrador mais lido do console: é assim que um jogo
            # descobre em que ponto da tela a PPU está.
            return self.ly
        if addr == 0xFF45:
            return self.lyc
        if addr == 0xFF47:
            return self.bgp
        if addr == 0xFF48:
            return self.obp0
        if addr == 0xFF49:
            return self.obp1
        if addr == 0xFF4A:
            return self.wy
        if addr == 0xFF4B:
            return self.wx
        return 0xFF

    def escrever_reg(self, addr, val):
        if addr == 0xFF40:
            # O bit 7 do LCDC liga e desliga a tela inteira. Todo jogo desliga
            # em transições, porque com a tela apagada a memória de vídeo fica
            # livre e dá para reescrever o cenário inteiro de uma vez.
            estava = self.ligado
            self.lcdc = val
            self.ligado = (val & 0x80) != 0
            if estava and not self.ligado:
                self._desligar()
            elif not estava and self.ligado:
                self._ligar()
        elif addr == 0xFF41:
            # Os 3 bits de baixo do STAT são o estado atual da PPU, e o jogo não
            # pode escrever neles: são só de leitura.
            self.stat = (val & 0x78) | (self.stat & 0x07)
            self._atualizar_stat()
        elif addr == 0xFF42:
            self.scy = val
        elif addr == 0xFF43:
            self.scx = val
        elif addr == 0xFF44:
            pass                                    # LY é só de leitura
        elif addr == 0xFF45:
            # Mudar o LYC pode criar uma coincidência na hora, e isso precisa
            # ser reavaliado imediatamente — não na próxima linha.
            self.lyc = val
            self._atualizar_stat()
        elif addr == 0xFF47:
            self.bgp = val
        elif addr == 0xFF48:
            self.obp0 = val
        elif addr == 0xFF49:
            self.obp1 = val
        elif addr == 0xFF4A:
            self.wy = val
        elif addr == 0xFF4B:
            self.wx = val

    def _desligar(self):
        """
        Desligar o vídeo zera a varredura e apaga a tela.

        Com o LCD desligado, a PPU para de avançar e as interrupções de vídeo
        param de sair — inclusive a de V-Blank. Um laço que espere pelo fim do
        quadro nesse estado espera para sempre, e é por isso que
        `Machine.rodar_frame` tem um teto de ciclos.
        """
        self.ly = 0
        self.dot = 0
        self.linha_janela = 0
        self._mudar_modo(0)
        self.proximo_evento = DOTS_POR_LINHA
        self.linha_stat = False
        self.framebuffer = bytearray(LARGURA * ALTURA)

    def _ligar(self):
        """
        Religar o vídeo, com um detalhe de 4 dots que custa caro errar.

        A varredura não recomeça num dot 0 perfeito: a PPU leva um M-cycle para
        engatar, e a primeira linha sai 4 dots mais curta. A ROM `1-lcd_sync.gb`
        mede exatamente isso — ela liga o vídeo, espera, e exige que o LY vire 1
        num ponto específico.

        Sem esse deslocamento de 4, todos os testes de temporização da tabela de
        sprites saem de fase, porque o modo 2 passa a começar no dot errado.
        """
        self.ly = 0
        self.dot = DOTS_AO_LIGAR
        self.linha_janela = 0
        self._mudar_modo(2)
        self.proximo_evento = DOTS_MODO2
        self.linha_stat = False
        self._atualizar_stat()

    # ==================================================================
    # Saída
    # ==================================================================
    def pegar_frame_rgb(self):
        """A tela como uma lista de cores RGB, para quem quiser exibi-la."""
        return [PALETA_DMG[c] for c in self.framebuffer]
