"""
O desenhista da interface. É o único arquivo de `ui/` que importa pygame.

Tudo aqui é retângulo cheio: sem suavização, sem gradiente, sem transparência
no texto. A tela do Game Boy tem 160x144 pixels quadrados, e uma interface com
bordas suavizadas por cima dela pareceria uma janela de outro programa colada
na frente do jogo.

O único efeito é escurecer o quadro congelado atrás do menu — que não é
enfeite: sem ele o texto se perde sobre a cena do jogo, e a diferença entre
"o jogo está pausado" e "o jogo travou" fica só no fato de a imagem não se
mexer.

Os glifos são desenhados uma vez e guardados em cache. O cache é do módulo, e
não do pincel, para sobreviver à troca de escala: mudar o tamanho da janela
recria o pincel, e seria bobagem redesenhar o alfabeto por causa disso.
"""

import pygame

from . import fonte

_CACHE_GLIFOS = {}      # (caractere, cor, escala) → Surface
_CACHE_VEU = {}         # (largura, altura, cor) → Surface


def _rgb(valor):
    return ((valor >> 16) & 0xFF, (valor >> 8) & 0xFF, valor & 0xFF)


def esquecer_cache():
    """
    Joga fora os glifos já desenhados.

    Precisa ser chamado quando a janela é recriada — ao mudar a escala, por exemplo.
    As superfícies passaram por `convert()`, que as adapta ao formato de pixel do
    vídeo ATUAL; depois de um `set_mode` novo esse formato pode ser outro, e uma
    superfície convertida para o formato antigo desenha errado ou nem desenha.
    """
    _CACHE_GLIFOS.clear()
    _CACHE_VEU.clear()


def _glifo(ch, cor, escala):
    """
    A superfície de um caractere, com o fundo transparente.

    Cada glifo é desenhado UMA vez e guardado. Sem o cache, cada letra do menu
    custaria 35 retângulos por quadro, sessenta vezes por segundo.

    A transparência usa cor-chave em vez de canal alfa: escolhe-se uma cor que não
    aparece no texto (magenta) e o pygame passa a tratá-la como buraco. É mais
    rápido que alfa de verdade e suficiente aqui, onde não há meio-tom nenhum.
    """
    chave = (ch, cor, escala)
    pronto = _CACHE_GLIFOS.get(chave)
    if pronto is not None:
        return pronto

    largura = fonte.LARGURA * escala
    altura = fonte.ALTURA_LINHA * escala
    superficie = pygame.Surface((largura, altura))

    # Cor-chave: escolhemos um tom que não colide com o texto para marcar o
    # que é vazio. Preto puro não serve — o texto costuma ser quase preto.
    vazio = (255, 0, 255)
    superficie.fill(vazio)

    linhas = fonte.linhas(ch)
    for y, bits in enumerate(linhas):
        if not bits:
            continue
        for x in range(fonte.LARGURA):
            if bits & (1 << (fonte.LARGURA - 1 - x)):
                superficie.fill(cor, (x * escala, y * escala, escala, escala))

    try:
        superficie = superficie.convert()
    except pygame.error:
        pass          # sem modo de vídeo definido ainda; a superfície crua serve
    superficie.set_colorkey(vazio)
    _CACHE_GLIFOS[chave] = superficie
    return superficie


class Pincel:
    """
    Desenha texto e caixas numa superfície, usando a paleta escolhida.

    Todo o layout é medido em UNIDADES DE FONTE e só multiplicado pela escala no
    fim. Assim existe um único lugar onde a interface pode não caber — a escolha da
    escala — em vez de uma dúzia de contas em pixels que precisariam conferir a
    borda da janela cada uma por si.
    """

    def __init__(self, superficie, tons, escala=2):
        self.superficie = superficie
        self.tons = [_rgb(t) for t in tons]
        self.escala = max(1, escala)
        self.avanco = fonte.AVANCO * self.escala
        self.altura_linha = fonte.ALTURA_LINHA * self.escala
        self.u = self.escala          # unidade de medida do layout

    # ------------------------------------------------------------------
    def cor(self, tom):
        return self.tons[max(0, min(3, tom))]

    def largura(self, texto):
        return fonte.largura_do_texto(texto) * self.escala

    def texto(self, x, y, s, tom=3):
        """Escreve e devolve a largura ocupada."""
        cor = self.cor(tom)
        destino = self.superficie
        passo = self.avanco
        for i, ch in enumerate(s):
            if ch != " ":
                destino.blit(_glifo(ch, cor, self.escala), (x + i * passo, y))
        return len(s) * passo - self.escala if s else 0

    def texto_direita(self, x_direita, y, s, tom=3):
        self.texto(x_direita - self.largura(s), y, s, tom)

    def caixa(self, x, y, largura, altura, fundo=None, borda=None, espessura=None):
        if fundo is not None:
            self.superficie.fill(self.cor(fundo), (x, y, largura, altura))
        if borda is not None:
            e = espessura or self.u
            cor = self.cor(borda)
            self.superficie.fill(cor, (x, y, largura, e))
            self.superficie.fill(cor, (x, y + altura - e, largura, e))
            self.superficie.fill(cor, (x, y, e, altura))
            self.superficie.fill(cor, (x + largura - e, y, e, altura))


def escurecer(superficie, tom_escuro, alpha=160):
    """
    Cobre a tela com um véu do tom mais escuro da paleta.

    Não é enfeite. Sem ele o texto do menu se perde sobre a cena do jogo, e a
    diferença entre "pausado" e "travado" fica só no fato de a imagem não se mexer.
    """
    tamanho = superficie.get_size()
    chave = (tamanho, tom_escuro, alpha)
    veu = _CACHE_VEU.get(chave)
    if veu is None:
        veu = pygame.Surface(tamanho)
        veu.fill(_rgb(tom_escuro))
        veu.set_alpha(alpha)
        _CACHE_VEU[chave] = veu
    superficie.blit(veu, (0, 0))


# ======================================================================
# Layout
# ======================================================================
#
# Todo o layout é medido em UNIDADES DE FONTE, e só no fim multiplicado pela
# escala. Assim existe um único lugar onde a interface pode não caber — a
# escolha da escala — em vez de uma dúzia de contas em pixels que precisariam
# conferir a borda da janela cada uma por si.
#
# O rodapé fica DENTRO do painel, e não abaixo dele. Fora, ele era a única
# parte do menu cuja posição não dependia do tamanho do painel, e numa janela
# pequena escorria para fora da tela sem que nada no cálculo do painel
# percebesse.

RECHEIO = 3           # respiro entre a moldura e o conteúdo, em unidades
LINHAS_DE_RODAPE = 2  # uma para o recado, uma para a dica de teclas
LARGURA_MINIMA = 24   # caracteres — abaixo disso o painel fica esquisito


def escala_da_fonte(escala_janela):
    """
    Quantos pixels de tela vale um pixel de fonte, antes de conferir se cabe.

    Não pode ser a escala da janela: numa janela 1x o texto ficaria com 5 pixels de
    altura, ilegível. Também não pode ser fixa: numa janela 6x um texto pequeno se
    perderia no meio da tela. Um pouco abaixo da escala do jogo é o que mantém o
    menu legível sem cobrir tudo.
    """
    return max(2, escala_janela - 1)


def _altura_da_pagina(quantos_itens):
    """A altura do painel de uma página fixa, em unidades de fonte."""
    linha = fonte.ALTURA_LINHA
    return (1                       # borda de cima
            + linha + 1             # barra de título
            + RECHEIO
            + quantos_itens * linha
            + RECHEIO
            + LINHAS_DE_RODAPE * linha
            + 1)                    # borda de baixo


def _escala_que_cabe(pagina, tamanho, escala):
    """
    Encolhe a fonte até a página caber na janela.

    Uma janela 1x tem 160x144 pixels — menos que a maioria dos ícones de hoje. O
    menu de ajustes, na fonte confortável, precisaria de quase 200 pixels de altura
    e sairia pela borda.

    Em vez de proibir a janela pequena ou deixar o menu vazar, a fonte diminui até
    caber. No limite ela fica do tamanho da fonte do próprio Game Boy, que é de onde
    ela veio.
    """
    largura_tela, altura_tela = tamanho
    if pagina.rolavel:
        # A lista ocupa a janela inteira e mostra menos linhas quando aperta;
        # só o cabeçalho e o rodapé têm altura fixa.
        minimo = _altura_da_pagina(1)
    else:
        minimo = _altura_da_pagina(len(pagina.itens))

    while escala > 1 and minimo * escala > altura_tela:
        escala -= 1
    while escala > 1 and LARGURA_MINIMA * fonte.AVANCO * escala > largura_tela:
        escala -= 1
    return escala


def desenhar(superficie, menu, tons, escala_janela):
    """Desenha o menu inteiro sobre a superfície da janela."""
    escurecer(superficie, tons[3])
    pagina = menu.pagina
    if pagina is None:
        return
    escala = _escala_que_cabe(pagina, superficie.get_size(),
                              escala_da_fonte(escala_janela))
    pincel = Pincel(superficie, tons, escala)
    if pagina.rolavel:
        _desenhar_lista(pincel, menu, pagina)
    else:
        _desenhar_pagina(pincel, menu, pagina)


def _moldura(pincel, x, y, largura, altura, titulo):
    """Painel com barra de título em negativo. Devolve o y onde o conteúdo começa."""
    u = pincel.u
    pincel.caixa(x, y, largura, altura, fundo=0, borda=3, espessura=u)

    barra = pincel.altura_linha + u
    pincel.caixa(x + u, y + u, largura - 2 * u, barra, fundo=3)
    cabe = (largura - 2 * u - 2 * RECHEIO * u) // pincel.escala
    pincel.texto(x + u + RECHEIO * u, y + u + u // 2,
                 fonte.cortar(titulo, cabe), tom=0)
    return y + u + barra


def _rodape(pincel, x, y, largura, texto, recado=""):
    """As duas últimas linhas do painel: o recado e a dica de teclas."""
    cabe = largura // pincel.escala
    pincel.texto(x, y, fonte.cortar(recado, cabe), tom=3)
    pincel.texto(x, y + pincel.altura_linha, fonte.cortar(texto, cabe), tom=2)


def _desenhar_pagina(pincel, menu, pagina):
    """
    Desenha uma página fixa: título, itens e rodapé, tudo dentro do painel.

    O rodapé fica DENTRO do painel, e não abaixo dele. Fora, ele era a única parte
    do menu cuja posição não dependia do tamanho do painel, e numa janela pequena
    escorria para fora da tela sem que nada no cálculo percebesse.
    """
    u = pincel.u
    largura_tela, altura_tela = pincel.superficie.get_size()
    linha = pincel.altura_linha
    recheio = RECHEIO * u

    # Largura pelo item mais largo, com um piso para o painel não ficar
    # estreito demais em menus de rótulos curtos.
    precisa = pincel.largura(pagina.titulo)
    for item in pagina.itens:
        largura_item = pincel.largura(item.rotulo)
        valor = item.valor_texto()
        if valor:
            largura_item += pincel.largura("  " + valor)
        precisa = max(precisa, largura_item)
    precisa = max(precisa, LARGURA_MINIMA * pincel.avanco)

    largura = min(largura_tela - 2 * u, precisa + 2 * recheio + 2 * u)
    altura = _altura_da_pagina(len(pagina.itens)) * pincel.escala

    x = (largura_tela - largura) // 2
    y = max(0, (altura_tela - altura) // 2)

    conteudo = _moldura(pincel, x, y, largura, altura, pagina.titulo) + recheio
    esquerda = x + recheio
    direita = x + largura - recheio

    for i, item in enumerate(pagina.itens):
        alvo = conteudo + i * linha
        marcado = i == pagina.selecionado and item.selecionavel
        if marcado:
            pincel.caixa(x + 2 * u, alvo, largura - 4 * u, linha, fundo=2)
        tom = 0 if marcado else (2 if not item.selecionavel else 3)
        pincel.texto(esquerda, alvo,
                     fonte.cortar(item.rotulo,
                                  (direita - esquerda) // pincel.escala), tom=tom)
        valor = item.valor_texto()
        if valor:
            pincel.texto_direita(direita, alvo, valor, tom=0 if marcado else 2)

    _rodape(pincel, esquerda, conteudo + len(pagina.itens) * linha + recheio,
            direita - esquerda, pagina.rodape, menu.recado)


def _desenhar_lista(pincel, menu, pagina):
    """
    Desenha o seletor de jogos, que ocupa a janela inteira.

    Quantas linhas cabem só se sabe aqui, com o tamanho da janela na mão — por isso
    a página é informada agora, antes de se decidir o que mostrar.
    """
    u = pincel.u
    largura_tela, altura_tela = pincel.superficie.get_size()
    linha = pincel.altura_linha
    recheio = RECHEIO * u

    x, y = u, u
    largura = largura_tela - 2 * u
    altura = altura_tela - 2 * u

    conteudo = _moldura(pincel, x, y, largura, altura, pagina.titulo) + recheio
    fim_do_conteudo = y + altura - u - LINHAS_DE_RODAPE * linha - recheio

    # Quantas linhas cabem só se sabe aqui, com a janela na mão — por isso a
    # página é informada agora, antes de decidirmos o que mostrar.
    pagina.visiveis = max(1, (fim_do_conteudo - conteudo) // linha)
    pagina.acertar_rolagem()

    esquerda = x + recheio
    direita = x + largura - recheio
    entradas = pagina.entradas

    if not entradas:
        pincel.texto(esquerda, conteudo,
                     fonte.cortar("(nenhuma ROM nesta pasta)",
                                  (direita - esquerda) // pincel.escala), tom=2)
    else:
        rolando = len(entradas) > pagina.visiveis
        barra = 2 * u if rolando else 0
        direita_do_texto = direita - barra
        # Três quintos da largura para o nome do arquivo, o resto para o
        # título gravado no cartucho.
        corte = (direita_do_texto - esquerda) * 3 // 5

        for i in range(pagina.visiveis):
            indice = pagina.primeiro + i
            if indice >= len(entradas):
                break
            entrada = entradas[indice]
            alvo = conteudo + i * linha
            marcado = indice == pagina.selecionado
            if marcado:
                pincel.caixa(x + 2 * u, alvo, largura - 4 * u, linha, fundo=2)

            nome = entrada.nome + ("/" if entrada.pasta and not entrada.subir else "")
            pincel.texto(esquerda, alvo,
                         fonte.cortar(nome, corte // pincel.escala),
                         tom=0 if marcado else 3)

            descricao = menu.biblioteca.descricao(entrada)
            se_cabe = (direita_do_texto - esquerda - corte - pincel.avanco)
            if descricao and se_cabe > pincel.avanco:
                pincel.texto_direita(direita_do_texto, alvo,
                                     fonte.cortar(descricao,
                                                  se_cabe // pincel.escala),
                                     tom=0 if marcado else 2)

        if rolando:
            _barra_de_rolagem(pincel, direita - barra + u, conteudo,
                              barra - u, pagina.visiveis * linha,
                              pagina.primeiro, pagina.visiveis, len(entradas))

    posicao = f"{pagina.selecionado + 1}/{len(entradas)}" if entradas else ""
    dica = f"{pagina.rodape}   {posicao}" if posicao else pagina.rodape
    _rodape(pincel, esquerda, fim_do_conteudo + recheio,
            direita - esquerda, dica, menu.recado)


def _barra_de_rolagem(pincel, x, y, largura, altura, primeiro, visiveis, total):
    """
    A barra lateral, que mostra quanto da lista está visível e onde.

    O tamanho mínimo da fatia importa: numa pasta com quinhentas ROMs, a proporção
    exata daria menos de um pixel, e uma barra invisível é pior do que nenhuma.
    """
    pincel.caixa(x, y, largura, altura, fundo=1)
    fatia = max(pincel.u * 2, altura * visiveis // total)
    percurso = max(0, altura - fatia)
    deslocamento = percurso * primeiro // max(1, total - visiveis)
    pincel.caixa(x, y + deslocamento, largura, fatia, fundo=3)
