"""
O programa que você executa: janela, teclado, som e ritmo.

A pasta `gb/` sabe ser um Game Boy e nada mais. Ela não abre janela, não lê
teclado e não faz som — entrega um retângulo de 160x144 números e um punhado de
amostras de áudio, e o que fazer com isso é problema daqui.

Essa divisão é o que permite ao emulador rodar sem interface nenhuma nos testes,
e é a razão de `gb/` não depender de nada além da biblioteca padrão do Python. O
pygame só aparece neste arquivo e na pasta `ui/`.

    python main.py                            abre a janela no seletor de jogos
    python main.py --continuar                reabre o último jogo
    python main.py jogo.gb                    abre esse jogo
    python main.py jogo.gb --frames 600       roda 600 quadros e sai, sem janela
    python main.py jogo.gb --png tela.png     salva a tela num arquivo
    python main.py jogo.gb --ascii            mostra a tela no próprio terminal
    python main.py jogo.gb --serial           imprime a saída da porta serial
    python main.py jogo.gb --diagnostico      mede cada fase do quadro

Controles:

    setas .......... direcional
    Z / X .......... A / B
    Enter .......... Start
    Backspace ...... Select
    Tab (segurar) .. turbo
    Esc ............ menu (e, dentro dele, voltar)
    F5 ............. reabre o áudio, se o som sumir


O PROBLEMA CENTRAL DESTE ARQUIVO É O RITMO
------------------------------------------

Emular corretamente não basta. O console produz 59,7275 quadros por segundo, e o
emulador precisa entregá-los NESSE ritmo — nem mais rápido, senão o jogo corre
em câmera acelerada, nem mais devagar.

Parece simples: emula um quadro, espera o que falta para completar 16,74 ms,
repete. Não é, por três motivos que só aparecem na prática.

O PRIMEIRO é que o `sleep` do sistema operacional não acorda na hora pedida. Ele
acorda depois, e o quanto depois varia por máquina — num Windows medimos 5,5 ms
de atraso mediano. Pedir 11 ms e dormir 16,5 estoura o quadro sozinho, com o
emulador tendo folga de sobra. A solução aqui é dormir quase tudo e afiar o resto
girando em espera ativa, com a margem entre as duas coisas se ajustando sozinha.

O SEGUNDO é o que fazer quando a máquina não acompanha. Rodar em câmera lenta ou
mostrar menos quadros — e a segunda é quase sempre melhor, porque a emulação
continua exata e só o desenho é pulado. O jogo mantém a velocidade certa.

O TERCEIRO é que 60 Hz não é a taxa do console. Mirar em 60 redondos acumula erro
e o quadro escorrega devagarinho até estourar. A conta certa é 70224 ciclos
divididos por 4194304 Hz.

Nada disso aparece num teste de precisão, e tudo isso decide se o jogo parece
fluido ou travado. `tests/test_ritmo.py` cobre este arquivo com um relógio
virtual, e já pegou dois defeitos que nenhuma outra parte da suíte pegaria.
"""

import argparse
import os
import sys
import time

from gb.cartridge import Cartridge
from gb.machine import Machine
from gb.ppu import ALTURA, LARGURA, PALETA_DMG
from ui import paletas
from ui.biblioteca import Biblioteca
from ui.config import Preferencias
from ui.menu import Menu

ESCALA_PADRAO = 3
PASTA_DE_ROMS = "roms"

# Duração de um quadro do Game Boy: 70224 ciclos a 4194304 Hz.
INTERVALO_DO_QUADRO = 70224 / 4194304

# Quantos quadros seguidos podem ser pulados antes de forçarmos um desenho.
# Sem esse teto, uma máquina muito lenta congelaria a imagem por completo.
PULO_MAXIMO_PADRAO = 3

# No turbo, um quadro desenhado a cada N emulados. Serve só para você ver onde
# está enquanto o jogo corre — desenhar todos jogaria fora, em vídeo, o tempo
# que deveria estar adiantando a partida.
DESENHOS_NO_TURBO = 8

# Limites da margem de giro — o pedaço final da espera que é feito girando em
# vez de dormindo. O `time.sleep` do sistema nunca acorda no instante pedido, e
# o quanto ele erra varia por máquina: medimos 5,5 ms de excesso mediano num
# Windows com PyPy, contra frações de milissegundo em outros. Por isso a margem
# é adaptativa (ver o laço), e estes são só o piso e o teto.
MARGEM_MINIMA = 0.0005
MARGEM_MAXIMA = 0.008

# Enquanto o menu está aberto o emulador não roda; 60 Hz aqui é só para o
# cursor responder na hora sem torrar um núcleo à toa.
FPS_DO_MENU = 60


class CartuchoIncompativel(Exception):
    """
    ROM marcada como exclusiva de Game Boy Color.

    Recusar é mais honesto do que fingir que roda: a ROM produziria resultados
    errados em silêncio, e num console de verdade ela mostraria a tela de cartucho
    incompatível.
    """


# ----------------------------------------------------------------------
# Cores
# ----------------------------------------------------------------------
def tabelas_de_cor(tons):
    """
    Três tabelas que convertem os índices do framebuffer em vermelho, verde e azul.

    A PPU entrega um byte por pixel com um valor de 0 a 3, e a tela do computador
    quer três bytes de cor. Converter pixel a pixel seriam 23.040 iterações em
    Python por quadro, sessenta vezes por segundo.

    Com estas tabelas a conversão vira três chamadas a `bytes.translate()`, que roda
    em C e faz a tela inteira de uma vez. E como só as tabelas dependem da paleta,
    trocar de cores custa exatamente nada — é o que permite recolorir o jogo ao vivo
    pelo menu.
    """
    return (bytes((tons[c] >> 16) & 0xFF if c < 4 else 0 for c in range(256)),
            bytes((tons[c] >> 8) & 0xFF if c < 4 else 0 for c in range(256)),
            bytes(tons[c] & 0xFF if c < 4 else 0 for c in range(256)))


TABELAS_DMG = tabelas_de_cor(PALETA_DMG)


def framebuffer_rgb(fb, tabelas=None):
    """
    Converte a tela de índices de cor num buffer RGB pronto para o pygame.

    As fatias com passo 3 (`buf[0::3]`) preenchem uma componente de cor de cada vez:
    todos os vermelhos, depois todos os verdes, depois todos os azuis. Três
    operações em bloco no lugar de um laço.
    """
    r, g, b = tabelas or TABELAS_DMG
    buf = bytearray(LARGURA * ALTURA * 3)
    buf[0::3] = fb.translate(r)
    buf[1::3] = fb.translate(g)
    buf[2::3] = fb.translate(b)
    return bytes(buf)


# ----------------------------------------------------------------------
# Cartucho
# ----------------------------------------------------------------------
def info_do_cartucho(cart):
    """Imprime a ficha do cartucho no terminal."""
    print(f"Título:     {cart.title or '(sem título)'}")
    print(f"Tipo:       {cart.tipo_nome()}")
    print(f"Console:    {cart.compatibilidade()}")
    print(f"ROM:        {cart.rom_size} bytes (arquivo: {len(cart.rom)})")
    print(f"RAM:        {cart.ram_size} bytes")
    print(f"Bateria:    {'sim' if cart.tem_bateria else 'não'}")
    print(f"Checksum:   {'OK' if cart.header_checksum_ok() else 'FALHOU'}")


def caminho_do_save(rom):
    """O arquivo `.sav` que corresponde a uma ROM: o mesmo nome, outra extensão."""
    return os.path.splitext(rom)[0] + ".sav"


class Sessao:
    """
    Um cartucho aberto: o arquivo, a máquina e o save.

    Esta classe existe porque a janela passou a poder trocar de jogo sem fechar.
    Antes, o ciclo "carregar o save, rodar, gravar o save" ficava solto no `main()` e
    valia para a execução inteira. Com a troca de jogo, ele passou a acontecer uma
    vez por cartucho — e esquecer de gravar ao trocar apagaria a partida do jogador.

    Juntar as três coisas num objeto só torna difícil esquecer.
    """

    def __init__(self, caminho, usar_save=True, forcar=False):
        self.caminho = caminho
        self.cart = Cartridge.from_file(caminho)

        if self.cart.so_cgb and not forcar:
            # O byte 0x143 valendo 0xC0 significa "só Game Boy Color". Um DMG
            # de verdade exibe a tela de cartucho incompatível e não executa
            # nada. Fingir que roda é pior do que recusar: a ROM produziria
            # resultados errados em silêncio.
            raise CartuchoIncompativel(self.cart.title or os.path.basename(caminho))

        self.usa_save = self.cart.tem_bateria and usar_save
        if self.usa_save:
            self.cart.carregar_ram(caminho_do_save(caminho))

        self.m = Machine(self.cart)
        self.m.reset()

    @property
    def nome(self):
        return self.cart.title or os.path.basename(self.caminho)

    def reiniciar(self):
        """
        Reinicia o console, como apertar o botão do aparelho.

        A RAM da bateria NÃO é apagada, e isso é importante. No cartucho de
        verdade ela fica num chip alimentado por pilha, alheio ao botão de ligar
        — zerá-la aqui apagaria o save de quem só queria recomeçar a partida.

        O cartucho é reaproveitado justamente por isso: só a máquina é nova.
        """
        self.m = Machine(self.cart)
        self.m.reset()

    def gravar_save(self):
        """Grava a RAM da bateria no arquivo `.sav`, se o cartucho tiver save."""
        if self.usa_save:
            self.cart.salvar_ram(caminho_do_save(self.caminho))
            return caminho_do_save(self.caminho)
        return None


# ----------------------------------------------------------------------
# Saídas sem janela
# ----------------------------------------------------------------------
def salvar_imagem(framebuffer, destino):
    """
    Grava a tela num arquivo de imagem.

    Usa a Pillow se estiver instalada. Se não estiver, cai no formato PPM, que não
    precisa de biblioteca nenhuma: um cabeçalho de três linhas em texto seguido dos
    bytes RGB crus. É um formato antigo e pouco prático, e a vantagem é justamente
    essa simplicidade — dá para escrevê-lo à mão em cinco linhas.
    """
    dados = framebuffer_rgb(framebuffer)

    try:
        from PIL import Image
        Image.frombytes("RGB", (LARGURA, ALTURA), dados).save(destino)
        return destino
    except ImportError:
        pass

    # PPM (P6) não precisa de biblioteca nenhuma: cabeçalho de texto + RGB cru.
    destino = os.path.splitext(destino)[0] + ".ppm"
    with open(destino, "wb") as f:
        f.write(f"P6\n{LARGURA} {ALTURA}\n255\n".encode())
        f.write(dados)
    return destino


def desenhar_no_terminal(framebuffer):
    """
    Mostra a tela em ASCII, útil para conferir alguma coisa sem interface gráfica.

    Os saltos de 3 em 3 na vertical e de 2 em 2 na horizontal compensam o formato do
    caractere de terminal, que é mais alto do que largo. Sem isso a imagem sairia
    esticada.
    """
    tons = " .:#"
    linhas = []
    for y in range(0, ALTURA, 3):
        linhas.append("".join(tons[framebuffer[y * LARGURA + x]]
                              for x in range(0, LARGURA, 2)))
    return "\n".join(linhas)


def rodar_sem_janela(m, frames, mostrar_serial):
    """
    Roda um número fixo de quadros o mais rápido possível e relata a velocidade.

    Sem janela e sem limitador de ritmo — é assim que se mede o desempenho bruto do
    emulador, porque o limitador esconde qualquer medição feita olhando o número de
    quadros por segundo na barra de título.
    """
    t0 = time.time()
    for _ in range(frames):
        m.rodar_frame()
    dt = time.time() - t0

    print(f"\n{frames} quadros em {dt:.1f}s "
          f"({frames / dt:.1f} fps, {m.cycles / dt / 4194304:.2f}x tempo real)")

    if mostrar_serial and m.serial.saida:
        print("\n--- saída serial ---")
        print(m.serial.saida.decode("ascii", "replace"))


# ----------------------------------------------------------------------
# Janela
# ----------------------------------------------------------------------
def _afinar_relogio_do_windows():
    """
    Pede ao Windows um temporizador de 1 ms, e devolve como desfazer isso.

    Por padrão o Windows acorda tarefas dormindo apenas a cada 15,6 ms. Um
    `time.sleep(0.011)` pode então dormir 15,6 ms, e o quadro estoura sozinho mesmo
    com o emulador tendo folga de sobra.

    Não é hipótese: foi o que o diagnóstico mostrou. A fase de espera respondia por
    59% dos engasgos enquanto a emulação usava 4 ms de um orçamento de 16,7 —
    sobrava capacidade e faltava fluidez, e a causa era o relógio do sistema
    operacional.

    `timeBeginPeriod(1)` reduz esse passo para 1 ms. A configuração vale para o
    sistema INTEIRO e aumenta o consumo de energia, então precisa ser desfeita ao
    sair — daí a função devolver o desfazedor em vez de simplesmente aplicar.
    """
    if sys.platform != "win32":
        return lambda: None
    try:
        import ctypes
        winmm = ctypes.WinDLL("winmm")
        if winmm.timeBeginPeriod(1) != 0:      # 0 = TIMERR_NOERROR
            return lambda: None
        return lambda: winmm.timeEndPeriod(1)
    except Exception:
        return lambda: None


def rodar_com_janela(sessao, prefs, pasta_de_roms=PASTA_DE_ROMS,
                     diagnostico=None, forcar=False, usar_save=True):
    """
    Abre a janela e roda até o jogador sair.

    Esta é a função mais longa do projeto, e concentra tudo que o README chama de
    "ritmo". A cada volta do laço ela faz sempre a mesma sequência:

        1. lê o teclado
        2. decide o prazo deste quadro
        3. decide se vai DESENHAR este quadro ou só emulá-lo
        4. emula um quadro inteiro
        5. desenha, se for o caso
        6. entrega o áudio acumulado
        7. espera até o prazo

    O passo 2 parece burocracia e é o coração de tudo. O prazo é fixado no COMEÇO do
    quadro, e não no fim — fixá-lo no fim foi um erro que custou caro: o teste de
    atraso comparava o relógio com um prazo que a espera anterior acabara de
    cumprir, e que portanto já tinha passado. O emulador se achava atrasado em todo
    quadro e desenhava um a cada quatro. Quinze quadros por segundo na tela, com a
    máquina folgada.

    `sessao` pode vir None: é o caso de abrir o emulador sem escolher jogo, quando a
    janela nasce direto no seletor de ROMs.
    """
    try:
        import pygame
    except ImportError:
        print("pygame não está instalado. Rode `pip install pygame` "
              "ou use --frames / --png / --ascii.")
        return False

    from ui import desenho

    soltar_relogio = _afinar_relogio_do_windows()

    escala = max(1, prefs["escala"])
    tons = paletas.tons(prefs["paleta"])
    tabelas = tabelas_de_cor(tons)
    pulo_maximo = max(0, prefs["pulo_maximo"])

    pygame.display.init()
    tela = pygame.display.set_mode((LARGURA * escala, ALTURA * escala))
    relogio = pygame.time.Clock()

    # O mapeamento precisa usar as constantes reais do pygame, que são
    # MAIÚSCULAS para teclas especiais e minúsculas para letras.
    botoes = {
        pygame.K_UP: "cima",       pygame.K_DOWN: "baixo",
        pygame.K_LEFT: "esquerda", pygame.K_RIGHT: "direita",
        pygame.K_z: "a",           pygame.K_x: "b",
        pygame.K_RETURN: "start",  pygame.K_BACKSPACE: "select",
    }

    # As mesmas setas servem ao jogo e ao menu; o que muda é para quem elas vão.
    teclas_do_menu = {
        pygame.K_UP: "cima",        pygame.K_DOWN: "baixo",
        pygame.K_LEFT: "esquerda",  pygame.K_RIGHT: "direita",
        pygame.K_RETURN: "confirmar", pygame.K_z: "confirmar",
        pygame.K_ESCAPE: "voltar",  pygame.K_x: "voltar",
        pygame.K_PAGEUP: "pagina_cima", pygame.K_PAGEDOWN: "pagina_baixo",
    }

    som = _AudioPygame(sessao.m, pygame, prefs["volume"]) \
        if (prefs["som"] and sessao) else None

    inicial = prefs["ultima_pasta"] or pasta_de_roms
    if not os.path.isdir(inicial):
        inicial = pasta_de_roms if os.path.isdir(pasta_de_roms) else "."
    livraria = Biblioteca(inicial)

    def aplicar(chave, valor):
        """Um ajuste mudou no menu. Ele vale a partir de agora, não ao sair."""
        nonlocal escala, tela, tons, tabelas, som, pulo_maximo
        if chave == "escala":
            escala = max(1, valor)
            tela = pygame.display.set_mode((LARGURA * escala, ALTURA * escala))
            # As superfícies em cache foram convertidas para o formato de vídeo
            # antigo; depois de um `set_mode` novo elas não servem mais.
            desenho.esquecer_cache()
        elif chave == "paleta":
            tons = paletas.tons(valor)
            tabelas = tabelas_de_cor(tons)
        elif chave == "volume":
            if som:
                som.definir_volume(valor)
        elif chave == "pulo_maximo":
            pulo_maximo = max(0, valor)
        elif chave == "som":
            if valor and som is None and sessao:
                som = _AudioPygame(sessao.m, pygame, prefs["volume"])
            elif not valor and som is not None:
                som.encerrar()
                som = None
                if sessao:
                    sessao.m.apu.audio_ativo = False

    menu = Menu(prefs, livraria, aplicar, tem_jogo=sessao is not None)

    crono = None
    if diagnostico:
        from gb.diagnostico import Cronometro
        crono = Cronometro()
        print(f"diagnóstico ligado — jogue normalmente e feche a janela.\n"
              f"o relatório vai para {diagnostico}")

    # Eventos que pedem para reabrir o mixer. A lista é curta de propósito:
    #   - ACTIVEEVENT dispara até quando o mouse passa pela borda da janela;
    #   - AUDIODEVICEADDED é emitido pelo PRÓPRIO mixer.init(), o que faria a
    #     reabertura se disparar de novo, e de novo, para sempre.
    # Ambos travariam o emulador em vez de consertar o som.
    reabrir_audio = {getattr(pygame, n) for n in
                     ("WINDOWFOCUSGAINED", "WINDOWRESTORED")
                     if hasattr(pygame, n)}

    def titulo_da_janela(extra=""):
        nome = sessao.nome if sessao else "nenhum jogo"
        pygame.display.set_caption(f"gb-py — {nome}{extra}")

    def soltar_botoes():
        """
        Larga todos os botões ao abrir o menu.

        Sem isso, uma direção pressionada no instante do Esc continuaria
        pressionada quando o jogo voltasse — e o personagem sairia andando
        sozinho para o lado.
        """
        if sessao:
            for nome in set(botoes.values()):
                sessao.m.joypad.definir(nome, False)

    def abrir_menu():
        soltar_botoes()
        if som:
            som.silenciar()
        menu.tem_jogo = sessao is not None
        menu.abrir()

    def trocar_de_jogo(caminho):
        """Fecha o cartucho atual e abre outro, sem fechar a janela."""
        nonlocal sessao, som
        if sessao:
            gravado = sessao.gravar_save()
            if gravado:
                print(f"save gravado em {gravado}")
        try:
            nova = Sessao(caminho, usar_save=usar_save, forcar=forcar)
        except CartuchoIncompativel as e:
            menu.recado = f"{e} exige um Game Boy Color"
            menu.abrir()
            return False
        except (OSError, ValueError, IndexError) as e:
            menu.recado = f"não consegui abrir: {e}"
            menu.abrir()
            return False

        sessao = nova
        prefs["ultima_rom"] = os.path.abspath(caminho)
        prefs["ultima_pasta"] = os.path.abspath(livraria.pasta)
        prefs.salvar()

        if som:
            som.encerrar()
            som = None
        if prefs["som"]:
            som = _AudioPygame(sessao.m, pygame, prefs["volume"])

        info_do_cartucho(sessao.cart)
        titulo_da_janela()
        return True

    titulo_da_janela()
    if sessao is None:
        abrir_menu()

    rodando = True
    turbo = False
    contador_turbo = 0
    margem = MARGEM_MINIMA
    quadros = 0
    mostrados = 0
    pulados_seguidos = 0
    ultimo_fb = sessao.m.ppu.framebuffer if sessao else None
    t_placar = time.time()

    # Prazo do próximo quadro. Serve para saber se estamos atrasados — e não
    # para controlar a velocidade, que continua a cargo da espera lá embaixo.
    prazo = time.perf_counter()

    try:
      while rodando:
          if crono:
              crono.novo_quadro()

          for ev in pygame.event.get():
              if ev.type == pygame.QUIT:
                  rodando = False
              elif ev.type in reabrir_audio:
                  if som:
                      som.reiniciar()
              elif ev.type == pygame.KEYDOWN and menu.aberto:
                  nome = teclas_do_menu.get(ev.key)
                  if nome:
                      acao = menu.tecla(nome)
                      if acao:
                          if acao[0] == "sair":
                              rodando = False
                          elif acao[0] == "reiniciar":
                              sessao.reiniciar()
                              if som:
                                  som.trocar_de_maquina(sessao.m)
                          elif acao[0] == "carregar":
                              trocar_de_jogo(acao[1])
              elif ev.type == pygame.KEYUP and menu.aberto:
                  pass          # o menu só reage ao apertar
              elif ev.type in (pygame.KEYDOWN, pygame.KEYUP):
                  apertou = ev.type == pygame.KEYDOWN
                  if ev.key == pygame.K_ESCAPE and apertou:
                      abrir_menu()
                  elif ev.key == pygame.K_TAB:
                      turbo = apertou
                  elif ev.key == pygame.K_F5 and apertou and som:
                      som.reiniciar()          # escape manual, se o som sumir
                  elif ev.key in botoes and sessao:
                      sessao.m.joypad.definir(botoes[ev.key], apertou)

          if crono:
              crono.marcar("eventos")

          # ----------------------------------------------------------------
          # Menu aberto: o console fica parado
          # ----------------------------------------------------------------
          if menu.aberto:
              # O quadro de fundo é redesenhado a partir do framebuffer, e não
              # copiado da tela: assim trocar de paleta ou de escala DENTRO do
              # menu recolore e redimensiona o jogo congelado na hora, em vez
              # de deixar uma imagem velha por baixo.
              if ultimo_fb is not None:
                  fundo = pygame.image.frombuffer(
                      framebuffer_rgb(ultimo_fb, tabelas), (LARGURA, ALTURA), "RGB")
                  tela.blit(pygame.transform.scale(fundo, tela.get_size()), (0, 0))
              else:
                  tela.fill(((tons[0] >> 16) & 0xFF, (tons[0] >> 8) & 0xFF,
                             tons[0] & 0xFF))
              desenho.desenhar(tela, menu, tons, escala)
              pygame.display.flip()
              relogio.tick(FPS_DO_MENU)

              # O relógio andou enquanto o jogo estava parado. Sem reancorar, a
              # primeira espera depois do menu tentaria "recuperar" todo esse
              # tempo de uma vez — o mesmo defeito que congelava o emulador ao
              # soltar o turbo.
              prazo = time.perf_counter()
              turbo = False
              if crono:
                  crono.fim_do_quadro(True, True)   # não conta no orçamento
              continue

          if sessao is None:
              # Fecharam o menu sem escolher jogo (só acontece se `tem_jogo`
              # estiver errado); não há o que emular.
              abrir_menu()
              continue

          m = sessao.m

          # ----------------------------------------------------------------
          # Prazo deste quadro
          # ----------------------------------------------------------------
          # O prazo é fixado AQUI, no começo do quadro, e não no fim. Fixá-lo no
          # fim era um erro sutil e caro: o teste de atraso comparava o relógio
          # com o prazo que a espera do quadro anterior tinha acabado de cumprir,
          # e que portanto JÁ tinha passado. O resultado era o emulador se achar
          # atrasado em todo quadro e pular o desenho até o teto forçar um — três
          # pulados para cada um desenhado, 15 quadros por segundo na tela.
          prazo += INTERVALO_DO_QUADRO
          agora = time.perf_counter()

          if turbo:
              # O turbo não tem prazo a cumprir. Sem reancorar, o prazo correria
              # para o futuro (avança um quadro inteiro a cada volta enquanto o
              # relógio real mal se move) e, ao soltar o Tab, a espera dormiria
              # os segundos acumulados de uma vez.
              prazo = agora
          elif not (-0.25 < prazo - agora < 0.25):
              # Perdeu o compasso de vez — engasgo grande ou saída do turbo.
              prazo = agora + INTERVALO_DO_QUADRO

          # ----------------------------------------------------------------
          # Pulo de quadro adaptativo
          # ----------------------------------------------------------------
          # Quando a máquina não dá conta de emular a 60 Hz, só existem duas
          # saídas: o jogo roda em câmera lenta, ou mostramos menos quadros.
          # A segunda é quase sempre melhor — a emulação continua EXATA (mesma
          # CPU, mesmos timings, mesmas interrupções; só o desenho é pulado) e o
          # jogo mantém a velocidade certa. O limite de pulos seguidos evita que
          # a imagem congele de vez se a máquina estiver muito atrás.
          if turbo:
              # No avanço rápido ninguém acompanha quadro a quadro — o que se
              # quer é atravessar um trecho depressa. Desenhar tudo desperdiça
              # em vídeo o tempo que deveria estar adiantando o jogo. Mostrar um
              # em cada oito basta para você ver onde está.
              contador_turbo += 1
              desenhar = (contador_turbo % DESENHOS_NO_TURBO) == 0
              pulados_seguidos = 0
          else:
              contador_turbo = 0
              atrasado = agora > prazo
              desenhar = (not atrasado) or pulados_seguidos >= pulo_maximo
              pulados_seguidos = 0 if desenhar else pulados_seguidos + 1

          m.ppu.renderizar = desenhar
          fb = m.rodar_frame()
          ultimo_fb = fb
          if crono:
              crono.marcar("emulação")

          if desenhar:
              # frombuffer + scale fazem todo o trabalho em C. Não usamos a forma
              # de 3 argumentos do scale() porque ela exige que origem e destino
              # tenham a mesma profundidade de cor, o que nem sempre é verdade.
              superficie = pygame.image.frombuffer(framebuffer_rgb(fb, tabelas),
                                                   (LARGURA, ALTURA), "RGB")
              tela.blit(pygame.transform.scale(superficie, tela.get_size()), (0, 0))
              if crono:
                  crono.marcar("desenho")
              # O flip() pode BLOQUEAR esperando o vsync do monitor. Medi-lo
              # separado é o que distingue "emulador lento" de "brigando com a
              # taxa de atualização da tela".
              pygame.display.flip()
              mostrados += 1

          if crono:
              crono.marcar("vídeo")

          if som:
              som.despejar()
          if crono:
              crono.marcar("áudio")

          quadros += 1
          agora = time.time()
          if agora - t_placar >= 1.0:
              emulados = quadros / (agora - t_placar)
              vistos = mostrados / (agora - t_placar)
              extra = "" if mostrados == quadros else f", {vistos:.0f} na tela"
              titulo_da_janela(
                  f"   {emulados:.0f} fps "
                  f"({emulados / 59.7:.0%} da velocidade real{extra})"
                  + ("   [TURBO]" if turbo else ""))
              quadros = mostrados = 0
              t_placar = agora

          if not turbo:
              # Ritmo pelo prazo real do console (59,7275 Hz), e não pelo
              # Clock.tick(60) do pygame. O diagnóstico mostrou que ele era a
              # maior causa isolada de engasgo: mirava 60 Hz em vez de 59,7275 e
              # dormia em blocos grosseiros do Windows, estourando o orçamento
              # mesmo com a emulação folgada.
              #
              # Dormimos quase tudo e afiamos o resto girando: o sono do sistema
              # tem resolução de milissegundos, e o último pedaço precisa ser
              # exato para o quadro não escorregar.
              # A margem se ajusta sozinha: medimos quanto cada sono passou do
              # alvo e a mantemos um pouco acima disso. Numa máquina onde o
              # sono é preciso ela encolhe a quase nada; onde ele é grosseiro,
              # cresce e absorve o erro. Sem isso é escolher entre queimar CPU
              # girando à toa ou estourar o quadro — e o valor certo depende
              # da máquina, do sistema e da carga do momento.
              alvo = prazo - margem
              agora_espera = time.perf_counter()
              if alvo > agora_espera:
                  time.sleep(alvo - agora_espera)
                  excesso = time.perf_counter() - alvo
                  if excesso > margem:
                      # Passou da margem: cresce de uma vez, com folga.
                      margem = min(MARGEM_MAXIMA, excesso * 1.25)
                  elif excesso < margem * 0.5:
                      # Só encolhe com FOLGA CONFORTÁVEL, e bem devagar. Sem a
                      # zona morta a margem encolhia até ficar curta, levava um
                      # atraso, saltava de volta e recomeçava. E com queda
                      # rápida o ciclo apenas ficava mais largo: o sono do
                      # sistema é IRREGULAR, então a margem precisa lembrar do
                      # pior caso recente, não reagir à última amostra.
                      margem = max(MARGEM_MINIMA, margem * 0.9995)
              while time.perf_counter() < prazo:
                  pass

          if crono:
              crono.marcar("espera")
              crono.fim_do_quadro(desenhar, turbo)

    finally:
        # O relatório é gravado aqui, e não depois do laço, porque a saída nem
        # sempre é pela porta da frente: um Ctrl+C no terminal levantaria a
        # exceção e pularia a gravação, deixando no lugar o arquivo da execução
        # ANTERIOR — que é pior do que não ter arquivo nenhum, porque parece
        # válido e leva a conclusões erradas.
        if som:
            som.encerrar()
        pygame.quit()
        soltar_relogio()

        prefs["ultima_pasta"] = os.path.abspath(livraria.pasta)
        if sessao:
            prefs["ultima_rom"] = os.path.abspath(sessao.caminho)
        prefs.salvar()

        if crono:
            print()
            print(crono.relatorio())
            caminho = os.path.abspath(crono.salvar(diagnostico))
            print(f"\nrelatório completo (com os dados brutos) em:\n  {caminho}")

    return sessao


class _AudioPygame:
    """
    A saída de som, e o cuidado que ela exige.

    O pygame aceita um som na fila de um canal por vez. A tentação é, a cada quadro,
    pegar as amostras que a APU gerou e mandar direto — e isso funciona até o
    primeiro quadro que atrase um pouquinho. Se a fila estiver ocupada naquele
    instante, as amostras se perdem; se o canal secar, o som simplesmente para e não
    volta.

    Foi exatamente o sintoma relatado: o áudio funcionava por alguns segundos e
    morria.

    A solução é um acumulador próprio. As amostras entram nele, e só saem em blocos
    quando há espaço na fila. Nada é descartado por acidente — o único descarte é
    proposital, quando o emulador roda mais rápido que a placa de som e a latência
    começaria a crescer sem parar.
    """

    AMOSTRAS_POR_BLOCO = 1024        # ~23 ms de áudio por bloco
    ATRASO_MAXIMO = 6144             # ~140 ms acumulados no máximo

    def __init__(self, maquina, pygame, volume=100):
        import array
        self.m = maquina
        self.pygame = pygame
        self.canal = None
        self.volume = max(0.0, min(1.0, volume / 100.0))
        self.pendentes = array.array("h")     # 16 bits com sinal, intercalado L/R

        # A APU já gera nesta taxa; o mixer precisa ser aberto na mesma.
        taxa = int(maquina.apu.TAXA_SAIDA)
        try:
            pygame.mixer.init(frequency=taxa, size=-16, channels=2, buffer=1024)
            self.canal = pygame.mixer.Channel(0)
            self.canal.set_volume(self.volume)
            maquina.apu.audio_ativo = True
        except Exception as e:      # placa de som ausente, driver sem permissão...
            print(f"áudio indisponível ({e}); seguindo em silêncio")
            maquina.apu.audio_ativo = False

    def definir_volume(self, porcento):
        """
        Ajusta o volume no mixer, e não na APU.

        Mexer na amplitude que a APU gera mudaria as amostras que os testes de som
        conferem — e um ajuste de conforto do jogador não tem por que alterar o que o
        console produz. O canal do pygame apenas multiplica no fim da linha, que é
        exatamente o que o botão de volume de um aparelho faz.
        """
        self.volume = max(0.0, min(1.0, porcento / 100.0))
        if self.canal:
            self.canal.set_volume(self.volume)

    def trocar_de_maquina(self, maquina):
        """Depois de reiniciar o console, as amostras passam a vir de outra APU."""
        self.m = maquina
        maquina.apu.audio_ativo = self.canal is not None
        self.silenciar()

    def silenciar(self):
        """
        Corta o som na hora e joga fora o que estava acumulado.

        Usado ao abrir o menu. Sem isso, o canal continuaria tocando os cerca de 140 ms
        já entregues ao mixer depois de o jogo ter congelado, e o trecho velho voltaria
        a tocar fora de sincronia quando a partida recomeçasse.
        """
        del self.pendentes[:]
        if self.canal:
            try:
                self.canal.stop()
            except Exception:
                pass

    def despejar(self):
        """
        Entrega ao mixer o que couber, e guarda o resto para o próximo quadro.

        O descarte do começo do acumulador é o único proposital de toda a classe: quando
        o emulador produz som mais rápido do que a placa consome, a latência cresceria
        para sempre. Jogar fora o mais antigo mantém o atraso limitado a cerca de 140 ms.
        """
        if not self.canal:
            return

        # A APU já entrega PCM de 16 bits intercalado, no formato final: não
        # há conversão nem laço por amostra aqui.
        self.pendentes.extend(self.m.apu.consumir_audio())
        pend = self.pendentes

        # Emulador mais rápido que o relógio da placa de som: se deixarmos
        # acumular, a latência cresce para sempre. Descartamos o mais antigo.
        excesso = len(pend) - self.ATRASO_MAXIMO * 2
        if excesso > 0:
            del pend[:excesso]

        bloco = self.AMOSTRAS_POR_BLOCO * 2
        while len(pend) >= bloco:
            try:
                som = self.pygame.mixer.Sound(buffer=pend[:bloco].tobytes())
                if not self.canal.get_busy():
                    self.canal.play(som)      # canal parado: recomeça na hora
                elif self.canal.get_queue() is None:
                    self.canal.queue(som)
                else:
                    break                     # fila cheia: tenta no próximo quadro
            except Exception:
                break
            del pend[:bloco]

    def reiniciar(self):
        """
        Reabre o mixer do zero.

        Trocar de janela e voltar pode deixar o dispositivo de áudio num estado do qual
        ele não sai sozinho: o canal aceita tudo que se entrega e nada chega ao
        alto-falante. Pela API do pygame esse estado é indistinguível de um canal
        saudável — cheguei a escrever um vigia para detectá-lo e ele provadamente nunca
        disparava, porque os dois casos parecem idênticos de fora.

        Então, em vez de tentar adivinhar, o mixer é simplesmente reaberto quando a
        janela recupera o foco. Custa alguns milissegundos e é determinístico.
        """
        del self.pendentes[:]
        try:
            self.pygame.mixer.quit()
            self.pygame.mixer.init(frequency=int(self.m.apu.TAXA_SAIDA),
                                   size=-16, channels=2, buffer=1024)
            self.canal = self.pygame.mixer.Channel(0)
            self.canal.set_volume(self.volume)
        except Exception as e:
            print(f"não consegui reabrir o áudio ({e}); seguindo em silêncio")
            self.canal = None
            self.m.apu.audio_ativo = False

    def encerrar(self):
        """Fecha o mixer."""
        if self.canal:
            self.pygame.mixer.quit()
            self.canal = None


# ----------------------------------------------------------------------
def main():
    """
    Lê a linha de comando, monta a sessão e escolhe o modo de execução.

    A precedência é: o que foi dito na linha de comando vence o que estava salvo nas
    preferências, mas só naquilo que foi dito. Passar `--escala 4` não deve zerar a
    paleta escolhida da última vez.
    """
    p = argparse.ArgumentParser(description="Emulador de Game Boy em Python puro")
    p.add_argument("rom", nargs="?",
                   help="arquivo .gb (sem ele, a janela abre no seletor)")
    p.add_argument("--continuar", "-c", action="store_true",
                   help="reabre o último jogo, sem passar pelo seletor")
    p.add_argument("--janela", action="store_true",
                   help="aceito por compatibilidade; a janela já é o padrão")
    p.add_argument("--som", action="store_true", help="liga o áudio")
    p.add_argument("--sem-som", action="store_true", help="desliga o áudio")
    p.add_argument("--escala", type=int, default=0,
                   help="multiplicador da janela (padrão: o último usado)")
    p.add_argument("--roms", default=PASTA_DE_ROMS, metavar="PASTA",
                   help=f"pasta onde o seletor começa (padrão: {PASTA_DE_ROMS})")
    p.add_argument("--frames", type=int, default=0,
                   help="roda N quadros sem abrir janela e sai")
    p.add_argument("--png", help="salva a tela final neste arquivo")
    p.add_argument("--ascii", action="store_true", help="mostra a tela em ASCII")
    p.add_argument("--serial", action="store_true", help="imprime a saída serial")
    p.add_argument("--sem-save", action="store_true", help="não carrega/grava o .sav")
    p.add_argument("--pulo-maximo", type=int, default=-1, metavar="N",
                   help="quantos quadros seguidos podem ser pulados quando a "
                        "máquina não acompanha (0 desliga o pulo)")
    p.add_argument("--diagnostico", nargs="?", const="diagnostico.txt",
                   metavar="ARQUIVO",
                   help="mede o tempo de cada fase do quadro e grava um "
                        "relatório ao fechar (padrão: diagnostico.txt)")
    p.add_argument("--forcar", action="store_true",
                   help="roda mesmo ROMs marcadas como exclusivas de Game Boy Color")
    args = p.parse_args()

    prefs = Preferencias()
    # A linha de comando manda mais que o arquivo, mas só no que foi dito nela.
    if args.escala:
        prefs["escala"] = args.escala
    if args.som:
        prefs["som"] = True
    if args.sem_som:
        prefs["som"] = False
    if args.pulo_maximo >= 0:
        prefs["pulo_maximo"] = args.pulo_maximo

    caminho = args.rom
    if caminho is None and args.continuar:
        caminho = prefs["ultima_rom"]
        if not caminho or not os.path.exists(caminho):
            print("não há um último jogo para continuar.")
            caminho = None

    sem_janela = args.frames or args.png or args.ascii or args.serial

    if caminho is None and sem_janela:
        print("informe a ROM: esses modos não abrem a janela para escolher.")
        return 1

    sessao = None
    if caminho:
        if not os.path.exists(caminho):
            print(f"ROM não encontrada: {caminho}")
            return 1
        try:
            sessao = Sessao(caminho, usar_save=not args.sem_save,
                            forcar=args.forcar)
        except CartuchoIncompativel:
            cart = Cartridge.from_file(caminho)
            info_do_cartucho(cart)
            print("\nEste cartucho exige um Game Boy Color — este emulador é um DMG.")
            print("Num Game Boy original ele mostraria a tela de incompatibilidade.")
            print("Use --forcar para executar mesmo assim (o resultado não será fiel).")
            return 2
        info_do_cartucho(sessao.cart)

    try:
        if sem_janela:
            rodar_sem_janela(sessao.m, args.frames or 60, args.serial)
        else:
            sessao = rodar_com_janela(sessao, prefs, pasta_de_roms=args.roms,
                                      diagnostico=args.diagnostico,
                                      forcar=args.forcar,
                                      usar_save=not args.sem_save)
            if sessao is False:          # pygame ausente
                return 1
    except KeyboardInterrupt:
        print("\ninterrompido")

    if sessao and args.png:
        print(f"tela salva em {salvar_imagem(sessao.m.ppu.framebuffer, args.png)}")

    if sessao and args.ascii:
        print()
        print(desenhar_no_terminal(sessao.m.ppu.framebuffer))

    if sessao:
        gravado = sessao.gravar_save()
        if gravado:
            print(f"save gravado em {gravado}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
