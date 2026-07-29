"""
A lógica dos menus — sem uma linha de pygame.

Este módulo não sabe desenhar. Ele sabe quais páginas existem, qual item está
selecionado, o que cada tecla faz e o que resulta disso. Quem pinta pixels é o
`ui/desenho.py`.

A separação não é purismo: é o que permite TESTAR o menu. Abrir uma janela
dentro da suíte de testes seria lento, exigiria uma placa de vídeo no ambiente
e não rodaria sem monitor. Do jeito que está, `tests/test_ui.py` navega pelo
menu inteiro, troca ajustes e confere o resultado em milissegundos, no mesmo
processo — do mesmo jeito que os testes da CPU executam instruções sem precisar
de um Game Boy.

O menu conversa com o resto do mundo por dois canais estreitos:

    ao_mudar(chave, valor)   — um ajuste mudou; aplique agora
    tecla(nome) -> ação      — o que o frontend deve fazer

As ações são tuplas: ("continuar",), ("reiniciar",), ("sair",),
("carregar", caminho). Nada de callbacks escondidos — o frontend recebe a
decisão e age, o que também deixa o teste conferir a decisão sem executá-la.
"""

import os

from . import paletas

# Nomes de tecla que o menu entende. O frontend traduz as teclas do pygame
# para estes nomes, e é só isso que o menu conhece do mundo exterior.
TECLAS = ("cima", "baixo", "esquerda", "direita",
          "confirmar", "voltar", "pagina_cima", "pagina_baixo")


# ======================================================================
# Itens
# ======================================================================
class Item:
    """
    A base de tudo que aparece numa linha de menu.

    As subclasses abaixo mudam só o que acontece ao apertar as setas ou o Enter. É
    o padrão mais simples de polimorfismo: quem desenha e quem navega tratam todos
    os itens igual, e cada tipo decide sozinho o que fazer quando é acionado.
    """
    selecionavel = True

    def __init__(self, rotulo):
        self.rotulo = rotulo

    def valor_texto(self):
        """O que aparece à direita do rótulo. Vazio quando não há valor."""
        return ""

    def ajustar(self, passo):
        """Seta para a esquerda/direita. Devolve uma ação, ou None."""
        return None

    def confirmar(self):
        """Enter. Devolve uma ação, ou None."""
        return None


class Separador(Item):
    """Um texto que não se seleciona. Serve de título de seção ou de espaçamento."""

    selecionavel = False

    def __init__(self, rotulo=""):
        super().__init__(rotulo)


class Botao(Item):
    """Faz alguma coisa ao receber Enter, devolvendo uma ação para quem chamou."""
    def __init__(self, rotulo, acao):
        super().__init__(rotulo)
        self.acao = acao

    def confirmar(self):
        return self.acao


class Ajuste(Item):
    """A base dos itens ligados a uma preferência guardada."""

    def __init__(self, rotulo, prefs, chave, ao_mudar=None):
        super().__init__(rotulo)
        self.prefs = prefs
        self.chave = chave
        self.ao_mudar = ao_mudar

    @property
    def valor(self):
        return self.prefs[self.chave]

    def _guardar(self, valor):
        if valor == self.prefs[self.chave]:
            return
        self.prefs[self.chave] = valor
        if self.ao_mudar:
            # O valor lido de volta das preferências, e não o que passamos: a
            # validação pode ter corrigido, e aplicar um número diferente do
            # que ficou salvo deixaria a tela e o arquivo em desacordo.
            self.ao_mudar(self.chave, self.prefs[self.chave])


class Alternador(Ajuste):
    """Liga e desliga — o item de sim/não."""
    def __init__(self, rotulo, prefs, chave, ao_mudar=None,
                 ligado="ligado", desligado="desligado"):
        super().__init__(rotulo, prefs, chave, ao_mudar)
        self.rotulo_ligado = ligado
        self.rotulo_desligado = desligado

    def valor_texto(self):
        return self.rotulo_ligado if self.valor else self.rotulo_desligado

    def ajustar(self, passo):
        self._guardar(not self.valor)
        return None

    def confirmar(self):
        return self.ajustar(1)


class Numero(Ajuste):
    """Um número que sobe e desce com as setas, dentro de limites."""
    def __init__(self, rotulo, prefs, chave, minimo, maximo, passo=1,
                 sufixo="", ao_mudar=None, zero=None):
        super().__init__(rotulo, prefs, chave, ao_mudar)
        self.minimo = minimo
        self.maximo = maximo
        self.passo = passo
        self.sufixo = sufixo
        self.zero = zero          # texto especial quando o valor é o mínimo

    def valor_texto(self):
        if self.zero is not None and self.valor == self.minimo:
            return self.zero
        return f"{self.valor}{self.sufixo}"

    def ajustar(self, passo):
        novo = self.valor + passo * self.passo
        self._guardar(min(self.maximo, max(self.minimo, novo)))
        return None


class Escolha(Ajuste):
    """Gira por uma lista de opções, como a paleta de cores."""

    def __init__(self, rotulo, prefs, chave, opcoes, ao_mudar=None):
        super().__init__(rotulo, prefs, chave, ao_mudar)
        self.opcoes = list(opcoes)

    def _indice(self):
        for i, (valor, _) in enumerate(self.opcoes):
            if valor == self.valor:
                return i
        return 0

    def valor_texto(self):
        return self.opcoes[self._indice()][1] if self.opcoes else ""

    def ajustar(self, passo):
        if not self.opcoes:
            return None
        i = (self._indice() + passo) % len(self.opcoes)
        self._guardar(self.opcoes[i][0])
        return None

    def confirmar(self):
        return self.ajustar(1)


# ======================================================================
# Páginas
# ======================================================================
class Pagina:
    """Uma lista curta e fixa de itens, como o menu de pausa."""

    rolavel = False

    def __init__(self, titulo, itens, rodape=""):
        self.titulo = titulo
        self.itens = itens
        self.rodape = rodape
        self.selecionado = 0
        if not self._selecionavel(self.selecionado):
            self.mover(1)

    def _selecionavel(self, i):
        return 0 <= i < len(self.itens) and self.itens[i].selecionavel

    def mover(self, passo):
        """
        Anda pela lista pulando os itens que não se selecionam, e dá a volta no fim.

        Dar a volta importa mais do que parece num menu operado pelo direcional: chegar
        ao último item e continuar apertando "baixo" sem sair do lugar passa a impressão
        de que a tecla travou.
        """
        if not self.itens:
            return
        i = self.selecionado
        for _ in range(len(self.itens)):
            i = (i + passo) % len(self.itens)
            if self.itens[i].selecionavel:
                self.selecionado = i
                return

    def item(self):
        if self._selecionavel(self.selecionado):
            return self.itens[self.selecionado]
        return None


class PaginaLista:
    """
    Uma lista longa e rolante — o seletor de jogos.

    A janela visível é decidida aqui, e não no desenho, porque ela também responde
    a teclas: PageUp e PageDown andam de tela em tela, o que é decisão de navegação
    e não de pintura. Quem desenha apenas informa quantas linhas cabem.
    """

    rolavel = True

    def __init__(self, titulo, biblioteca, rodape=""):
        self.titulo = titulo
        self.biblioteca = biblioteca
        self.rodape = rodape
        self.selecionado = 0
        self.primeiro = 0
        self.visiveis = 10

    @property
    def entradas(self):
        return self.biblioteca.entradas

    def selecionar_por_caminho(self, caminho):
        """
        Deixa o cursor sobre um arquivo, se ele estiver na pasta atual.

        É o que faz o seletor abrir já em cima do último jogo aberto.
        """
        if not caminho:
            return False
        alvo = os.path.abspath(caminho)
        for i, e in enumerate(self.entradas):
            if os.path.abspath(e.caminho) == alvo:
                self.selecionado = i
                self.acertar_rolagem()
                return True
        return False

    def mover(self, passo):
        n = len(self.entradas)
        if not n:
            self.selecionado = self.primeiro = 0
            return
        self.selecionado = (self.selecionado + passo) % n
        self.acertar_rolagem()

    def acertar_rolagem(self):
        """Move a janela visível o mínimo necessário para o cursor aparecer nela."""
        n = len(self.entradas)
        visiveis = max(1, self.visiveis)
        if self.selecionado < self.primeiro:
            self.primeiro = self.selecionado
        elif self.selecionado >= self.primeiro + visiveis:
            self.primeiro = self.selecionado - visiveis + 1
        self.primeiro = max(0, min(self.primeiro, max(0, n - visiveis)))

    def item(self):
        if 0 <= self.selecionado < len(self.entradas):
            return self.entradas[self.selecionado]
        return None

    def confirmar(self):
        """Entra na pasta, ou devolve a ação de carregar a ROM."""
        entrada = self.item()
        if entrada is None:
            return None
        if entrada.pasta:
            self.biblioteca.entrar(entrada)
            self.selecionado = 0
            self.primeiro = 0
            return None
        return ("carregar", entrada.caminho)


# ======================================================================
# O menu
# ======================================================================
class Menu:
    """
    O menu inteiro: a pilha de páginas e o que cada tecla faz.

    A PILHA é o que permite entrar em submenus e voltar. Abrir "Ajustes" empilha uma
    página nova; o Esc desempilha. No topo da pilha, o Esc fecha o menu e devolve o
    jogo. É a mesma estrutura que um navegador usa para o botão "voltar".

    O menu conversa com o resto do programa por dois canais estreitos, e de
    propósito:

        ao_mudar(chave, valor)   um ajuste mudou; aplique agora
        tecla(nome) -> ação      o que o frontend deve fazer

    As ações são tuplas simples: ("continuar",), ("sair",), ("carregar", caminho).
    Devolver a decisão em vez de executá-la é o que deixa o teste conferir o que o
    menu decidiu sem precisar que nada aconteça de verdade.
    """
    def __init__(self, prefs, biblioteca=None, ao_mudar=None, tem_jogo=True):
        self.prefs = prefs
        self.biblioteca = biblioteca
        self.ao_mudar = ao_mudar
        self.tem_jogo = tem_jogo
        self.pilha = []
        self.aberto = False
        self.recado = ""          # mensagem curta mostrada no rodapé

    # ------------------------------------------------------------------
    @property
    def pagina(self):
        return self.pilha[-1] if self.pilha else None

    def abrir(self):
        """
        Abre no menu de pausa — ou direto no seletor, quando não há jogo.

        Sem cartucho não existe "continuar", e cair num menu cujo primeiro item é inútil
        é um convite a apertar Enter à toa. Nesse caso o caminho certo é o único que faz
        sentido: escolher um jogo.
        """
        self.aberto = True
        self.pilha = [self._pagina_pausa()]
        if not self.tem_jogo:
            self.pilha.append(self._pagina_selecao())

    def fechar(self):
        self.aberto = False
        self.pilha = []
        self.recado = ""

    def voltar(self):
        """Sobe um nível na pilha. No topo, fecha o menu — se houver jogo para voltar."""
        if len(self.pilha) > 1:
            self.pilha.pop()
            return None
        if self.tem_jogo:
            self.fechar()
            return ("continuar",)
        return None       # sem jogo não há para onde voltar: o menu fica

    # ------------------------------------------------------------------
    def _pagina_pausa(self):
        itens = []
        if self.tem_jogo:
            itens.append(Botao("Continuar", ("continuar",)))
            itens.append(Botao("Reiniciar", ("reiniciar",)))
        itens.append(Botao("Trocar de jogo", ("ir", "selecao")))
        itens.append(Botao("Ajustes", ("ir", "ajustes")))
        itens.append(Botao("Sair", ("sair",)))
        return Pagina("gb-py", itens,
                      "setas: escolher    Z/Enter: confirmar    Esc: voltar")

    def _pagina_selecao(self):
        pagina = PaginaLista("Escolha um jogo", self.biblioteca,
                             "Z/Enter: abrir    Esc: voltar")
        pagina.selecionar_por_caminho(self.prefs["ultima_rom"])
        return pagina

    def _pagina_ajustes(self):
        mudou = self._ajuste_mudou
        itens = [
            Alternador("Som", self.prefs, "som", mudou),
            Numero("Volume", self.prefs, "volume", 0, 100, 10, "%", mudou,
                   zero="mudo"),
            Numero("Escala da janela", self.prefs, "escala", 1, 8, 1, "x", mudou),
            Escolha("Paleta", self.prefs, "paleta", paletas.OPCOES, mudou),
            Numero("Pulo de quadros", self.prefs, "pulo_maximo", 0, 10, 1, "",
                   mudou, zero="nunca"),
            Separador(),
            Botao("Voltar", ("voltar",)),
        ]
        return Pagina("Ajustes", itens,
                      "setas ← →: mudar o valor    Esc: voltar")

    def _ajuste_mudou(self, chave, valor):
        if self.ao_mudar:
            self.ao_mudar(chave, valor)

    # ------------------------------------------------------------------
    def tecla(self, nome):
        """
        Processa uma tecla e devolve uma ação para o frontend, ou None.

        O menu não conhece o pygame: ele recebe nomes como "cima" e "confirmar". Quem
        traduz as teclas de verdade é o `main.py`, e é essa fronteira que permite testar
        toda a navegação sem abrir janela.
        """
        pagina = self.pagina
        if pagina is None:
            return None

        if nome == "cima":
            pagina.mover(-1)
        elif nome == "baixo":
            pagina.mover(1)
        elif nome == "pagina_cima":
            pagina.mover(-max(1, getattr(pagina, "visiveis", 1)))
        elif nome == "pagina_baixo":
            pagina.mover(max(1, getattr(pagina, "visiveis", 1)))
        elif nome in ("esquerda", "direita"):
            if not pagina.rolavel:
                item = pagina.item()
                if item is not None:
                    return self._resolver(item.ajustar(1 if nome == "direita" else -1))
        elif nome == "confirmar":
            if pagina.rolavel:
                return self._resolver(pagina.confirmar())
            item = pagina.item()
            if item is not None:
                return self._resolver(item.confirmar())
        elif nome == "voltar":
            return self.voltar()
        return None

    def _resolver(self, acao):
        """
        Trata as ações internas do menu e repassa o resto ao frontend.

        "ir" e "voltar" só mexem na pilha de páginas — o frontend não tem nada a ver com
        isso. Já "carregar", "reiniciar" e "sair" pertencem ao mundo real e sobem.
        """
        if acao is None:
            return None

        if acao[0] == "ir":
            destino = acao[1]
            if destino == "selecao":
                if self.biblioteca is None:
                    self.recado = "nenhuma pasta de jogos configurada"
                    return None
                self.pilha.append(self._pagina_selecao())
            elif destino == "ajustes":
                self.pilha.append(self._pagina_ajustes())
            return None

        if acao[0] == "voltar":
            return self.voltar()

        if acao[0] in ("continuar", "reiniciar"):
            self.fechar()
            return acao

        if acao[0] == "carregar":
            self.fechar()
            return acao

        return acao       # ("sair",) e o que mais vier
