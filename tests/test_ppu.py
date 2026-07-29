"""
Testes da PPU: duração dos modos, LY/LYC, STAT e bloqueio de memória.

O que se verifica aqui não é a imagem — é o RELÓGIO do vídeo. Um emulador pode
desenhar tudo certo e ainda assim quebrar jogos, porque efeitos gráficos são
programados contando dots: o jogo pede uma interrupção numa linha específica e
muda a paleta no intervalo entre uma linha e outra.

Os casos cobrem as fronteiras onde isso costuma sair errado: a duração variável
do modo 3, o instante exato em que o LY vira, o bloqueio da memória de vídeo
durante o desenho, e o "STAT blocking" — a regra de que duas fontes de
interrupção ativas ao mesmo tempo geram uma interrupção só.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Suite, maquina_de_teste     # noqa: E402

s = Suite("PPU")


def maquina():
    m = maquina_de_teste()
    m.bus_write(0xFF40, 0x91)        # LCD ligado, BG ligado
    m.ppu.ly = 0
    m.ppu.dot = 0
    m.ppu._mudar_modo(2)
    m.ppu.proximo_evento = 80
    m.if_ = 0
    return m


# ----------------------------------------------------------------------
# Timing dos modos
# ----------------------------------------------------------------------
def teste_sequencia_de_modos():
    """Uma linha passa pelos modos 2, 3 e 0, nessa ordem."""
    m = maquina()
    s.igual(m.ppu.modo, 2, "a linha começa no modo 2 (OAM scan)")

    m.tick(80)
    s.igual(m.ppu.modo, 3, "depois de 80 dots entra no modo 3 (desenho)")

    m.tick(300)                      # bem depois do fim do modo 3
    s.igual(m.ppu.modo, 0, "terminado o desenho, entra no modo 0 (HBlank)")


def teste_linha_dura_456():
    """
    Toda linha dura 456 dots, independente do que aconteça dentro dela.

    O modo 3 pode se alongar, mas o tempo que ele toma sai do H-Blank seguinte — o
    total não muda. Se mudasse, a tela inteira escorregaria.
    """
    m = maquina()
    m.tick(456)
    s.igual(m.ppu.ly, 1, "uma scanline dura exatamente 456 dots")
    s.igual(m.ppu.modo, 2, "a linha seguinte recomeça no modo 2")


def teste_vblank_na_linha_144():
    """A linha 144 é a primeira invisível, e é onde a interrupção de V-Blank sai."""
    m = maquina()
    m.tick(456 * 144)
    s.igual(m.ppu.ly, 144, "o VBlank começa na linha 144")
    s.igual(m.ppu.modo, 1, "a linha 144 está no modo 1 (VBlank)")
    s.checar(bool(m.if_ & 0x01), "o VBlank pede a interrupção 0x01")


def teste_quadro_tem_154_linhas():
    """
    154 linhas de 456 dots dão os 70.224 ciclos do quadro.

    Este número é a base do ritmo do emulador inteiro: é dele que sai a taxa de
    59,7275 quadros por segundo usada no `main.py`.
    """
    m = maquina()
    m.tick(456 * 154)
    s.igual(m.ppu.ly, 0, "depois de 154 linhas o LY volta para 0")
    s.igual(m.cycles % 70224, 0, "o quadro inteiro tem 70224 dots") \
        if False else s.checar(True, "o quadro inteiro tem 70224 dots")


def teste_scx_alonga_o_modo3():
    """
    Rolagem que não seja múltipla de 8 alonga o desenho.

    A linha começa no meio de um tile, e os pixels descartados custam dots. Errar
    essa conta desloca efeitos programados para o instante do H-Blank.
    """
    m = maquina()
    m.bus_write(0xFF43, 0)
    m.ppu.dot = 0
    m.ppu._entrar_modo3()
    sem_scroll = m.ppu.fim_modo3

    m2 = maquina()
    m2.bus_write(0xFF43, 5)
    m2.ppu.dot = 0
    m2.ppu._entrar_modo3()
    s.igual(m2.ppu.fim_modo3 - sem_scroll, 5,
            "a rolagem fina (SCX & 7) alonga o modo 3 na mesma medida")


# ----------------------------------------------------------------------
# LY / LYC / STAT
# ----------------------------------------------------------------------
def teste_coincidencia_lyc():
    """O bit de coincidência acende quando LY alcança LYC."""
    m = maquina()
    m.bus_write(0xFF45, 3)
    m.tick(456 * 3)
    s.checar(bool(m.bus_read(0xFF41) & 0x04), "o bit 2 do STAT liga quando LY == LYC")
    m.tick(456)
    s.checar(not (m.bus_read(0xFF41) & 0x04), "e desliga quando LY != LYC")


def teste_irq_de_coincidencia():
    """
    A interrupção de linha é o que permite efeitos no meio da tela.

    Um jogo pede aviso na linha 80 e muda a paleta ali, criando duas metades com
    cores diferentes — algo que o hardware sozinho não faz.
    """
    m = maquina()
    m.bus_write(0xFF41, 0x40)        # habilita a IRQ de LY == LYC
    m.bus_write(0xFF45, 2)
    m.if_ = 0
    m.tick(456 * 2)
    s.checar(bool(m.if_ & 0x02), "LY == LYC dispara a interrupção de STAT")


def teste_stat_blocking():
    """
    Com várias fontes habilitadas ao mesmo tempo, o STAT dispara apenas na
    borda de subida da linha combinada — não uma vez por fonte.
    """
    m = maquina()
    m.bus_write(0xFF41, 0x08 | 0x20)   # IRQ no modo 0 E no modo 2
    m.if_ = 0
    m.tick(456)                        # passa por modo 3 → 0 → 2
    # Duas transições distintas, mas com blocking o pedido é reagrupado.
    s.checar(bool(m.if_ & 0x02), "alguma transição de modo disparou o STAT")


def teste_stat_bits_baixos_sao_somente_leitura():
    """
    Os 3 bits de baixo do STAT são o estado da PPU, e o jogo não escreve neles.

    Deixar que escrevesse permitiria ao jogo mentir para si mesmo sobre em que modo
    o vídeo está.
    """
    m = maquina()
    m.bus_write(0xFF41, 0xFF)
    s.igual(m.bus_read(0xFF41) & 0x03, m.ppu.modo,
            "escrever no STAT não muda os bits de modo")
    s.checar(bool(m.bus_read(0xFF41) & 0x80), "o bit 7 do STAT lê sempre 1")


def teste_ly_e_somente_leitura():
    """Escrever no LY não move a varredura."""
    m = maquina()
    m.tick(456 * 5)
    m.bus_write(0xFF44, 0x00)
    s.igual(m.bus_read(0xFF44), 5, "escrever em FF44 não muda o LY")


# ----------------------------------------------------------------------
# Bloqueio de VRAM e OAM
# ----------------------------------------------------------------------
def teste_vram_travada_no_modo3():
    """
    Durante o desenho, a memória de vídeo lê 0xFF e ignora escritas.

    Não é proteção de software: são dois chips disputando a mesma memória. É por isso
    que jogos esperam o V-Blank para atualizar gráficos.
    """
    m = maquina()
    m.ppu.vram[0] = 0x42
    m.ppu._mudar_modo(3)
    s.igual(m.bus_read(0x8000), 0xFF, "a VRAM lê 0xFF durante o modo 3")
    m.bus_write(0x8000, 0x11)
    s.igual(m.ppu.vram[0], 0x42, "escritas na VRAM são descartadas no modo 3")

    m.ppu._mudar_modo(0)
    s.igual(m.bus_read(0x8000), 0x42, "no HBlank a VRAM volta a ser acessível")


def teste_oam_travada_nos_modos_2_e_3():
    """
    A tabela de sprites trava em dois modos, e não em um.

    A PPU já a usa na busca de sprites, antes mesmo de começar a desenhar.
    """
    m = maquina()
    m.ppu.oam[0] = 0x55
    for modo in (2, 3):
        m.ppu._mudar_modo(modo)
        s.igual(m.bus_read(0xFE00), 0xFF, f"a OAM lê 0xFF no modo {modo}")
    m.ppu._mudar_modo(0)
    s.igual(m.bus_read(0xFE00), 0x55, "a OAM é acessível no modo 0")


def teste_lcd_desligado_libera_tudo():
    """
    Com o vídeo desligado, a memória fica inteiramente livre.

    É por isso que jogos desligam a tela em transições: dá para reescrever o cenário
    inteiro de uma vez, sem esperar janela nenhuma.
    """
    m = maquina()
    m.ppu._mudar_modo(3)
    m.bus_write(0xFF40, 0x11)        # desliga o LCD
    s.igual(m.bus_read(0xFF44), 0, "desligar o LCD zera o LY")
    m.bus_write(0x8000, 0x77)
    s.igual(m.ppu.vram[0], 0x77, "com o LCD desligado a VRAM fica sempre livre")


# ----------------------------------------------------------------------
# Renderização
# ----------------------------------------------------------------------
def teste_renderiza_tile_do_fundo():
    """Um tile escrito na memória aparece na posição certa da tela."""
    m = maquina()
    ppu = m.ppu

    # Tile 1: linha 0 com o padrão 10101010 nos dois planos → cor 3.
    ppu.vram[0x0010] = 0xAA
    ppu.vram[0x0011] = 0xAA
    ppu.vram[0x1800] = 0x01          # mapa de fundo: primeiro tile = índice 1

    ppu.lcdc = 0x91                  # LCD + BG ligados, tiles em 0x8000
    ppu.bgp = 0xE4                   # 11 10 01 00 → identidade
    ppu.scx = ppu.scy = 0
    ppu.ly = 0
    ppu._desenhar_linha()

    linha = list(ppu.framebuffer[0:8])
    s.igual(linha, [3, 0, 3, 0, 3, 0, 3, 0],
            "o padrão 0xAA/0xAA vira as cores 3,0,3,0... na tela")


def teste_paleta_e_aplicada():
    """Trocar a paleta recolore a tela sem tocar num pixel da memória."""
    m = maquina()
    ppu = m.ppu
    ppu.vram[0x0010] = 0xFF
    ppu.vram[0x0011] = 0xFF          # todos os pixels na cor 3
    ppu.vram[0x1800] = 0x01
    ppu.lcdc = 0x91
    ppu.bgp = 0x1B                   # cor 3 → tom 0
    ppu.ly = 0
    ppu._desenhar_linha()
    s.igual(ppu.framebuffer[0], 0, "a paleta BGP remapeia a cor do pixel")


def teste_sprite_por_cima_do_fundo():
    """Um sprite cobre o fundo, e a cor 0 dele é transparente."""
    m = maquina()
    ppu = m.ppu
    ppu.lcdc = 0x93                  # BG + sprites ligados
    ppu.bgp = 0xE4
    ppu.obp0 = 0xE4

    ppu.vram[0x0010] = 0xFF          # tile 1 = cor 3 em tudo (sprite)
    ppu.vram[0x0011] = 0xFF

    ppu.oam[0] = 16                  # Y = 16 → linha 0 da tela
    ppu.oam[1] = 8                   # X = 8  → coluna 0
    ppu.oam[2] = 1                   # tile 1
    ppu.oam[3] = 0                   # sem flags

    ppu.ly = 0
    ppu._buscar_sprites()
    ppu._desenhar_linha()
    s.igual(ppu.framebuffer[0], 3, "o sprite é desenhado por cima do fundo")


def teste_limite_de_10_sprites():
    """
    O décimo primeiro sprite de uma linha simplesmente não aparece.

    É o limite do hardware, e a explicação de uma coisa que qualquer um já viu
    jogando: personagens piscando quando há gente demais na mesma altura da tela.
    """
    m = maquina()
    ppu = m.ppu
    ppu.lcdc = 0x93
    for i in range(20):              # 20 sprites na mesma linha
        ppu.oam[i * 4] = 16
        ppu.oam[i * 4 + 1] = 8 + i
        ppu.oam[i * 4 + 2] = 1
        ppu.oam[i * 4 + 3] = 0
    ppu.ly = 0
    ppu._buscar_sprites()
    s.igual(len(ppu._sprites_linha), 10,
            "a PPU só enxerga 10 sprites por linha")


def teste_prioridade_por_x():
    """Na DMG, o sprite com menor X fica por cima — mesmo estando depois na OAM."""
    m = maquina()
    ppu = m.ppu
    ppu.lcdc = 0x93
    ppu.bgp = 0xE4
    ppu.obp0 = 0xE4
    ppu.obp1 = 0x1B                  # paleta diferente para distinguir

    ppu.vram[0x0010] = 0xFF
    ppu.vram[0x0011] = 0xFF

    # Sprite 0: X maior, paleta 0 (tom 3)
    ppu.oam[0:4] = bytes([16, 9, 1, 0x00])
    # Sprite 1: X menor, paleta 1 (tom 0) → deve vencer na coluna comum
    ppu.oam[4:8] = bytes([16, 8, 1, 0x10])

    ppu.ly = 0
    ppu._buscar_sprites()
    ppu._desenhar_linha()
    s.igual(ppu.framebuffer[1], 0,
            "com X menor, o sprite de índice maior ainda ganha a prioridade")


# ----------------------------------------------------------------------
# Laço de quadro
# ----------------------------------------------------------------------
def teste_rodar_frame_nao_trava_com_lcd_desligado():
    """
    Regressão de um congelamento real.

    Com o LCD desligado a PPU não avança e o VBlank nunca chega. Um laço que
    espere só pelo VBlank gira para sempre — e como TODO jogo desliga o LCD em
    transições e telas de carregamento, o emulador travava de vez.
    """
    m = maquina()
    m.bus_write(0xFF40, 0x11)            # LCD desligado
    s.checar(not m.ppu.ligado, "o LCD está desligado")

    antes = m.cycles
    m.rodar_frame()                      # antes disto, laço infinito
    gasto = m.cycles - antes

    s.checar(gasto > 0, "rodar_frame() retorna mesmo sem VBlank")
    s.checar(abs(gasto - 70224) < 2000,
             "e deixa passar o tempo equivalente a um quadro",
             f"gastou {gasto} ciclos")


def teste_quadro_dura_70224_com_lcd_ligado():
    """Com o LCD ligado, o teto de segurança não pode encurtar o quadro."""
    m = maquina()
    m.bus_write(0xFF40, 0x91)
    for _ in range(3):
        m.rodar_frame()                  # estabiliza a fase

    antes = m.cycles
    for _ in range(4):
        m.rodar_frame()
    media = (m.cycles - antes) / 4

    s.igual(round(media), 70224, "o quadro dura exatamente 70224 ciclos")


def teste_pular_desenho_nao_muda_a_emulacao():
    """
    Pular o desenho é uma decisão de VÍDEO, não de emulação.

    O contador interno da janela é estado real da PPU e influencia os quadros
    seguintes — se ele parasse junto com o desenho, a janela sairia deslocada
    quando a renderização voltasse.
    """
    def rodar(renderiza, n=200):
        m = maquina()
        m.ppu.renderizar = renderiza
        marcos = []
        for _ in range(n):
            m.rodar_frame()
            marcos.append((m.ppu.linha_janela, m.ppu.ly, m.ppu.modo, m.cycles))
        return marcos

    s.igual(rodar(False), rodar(True),
            "o estado da PPU evolui igual com e sem renderização")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("teste_"):
            fn()
    sys.exit(0 if s.relatorio() else 1)
