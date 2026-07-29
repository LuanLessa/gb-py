"""
Fonte de bitmap no estilo do Game Boy.

Por que desenhar uma fonte à mão em vez de usar a do pygame? Três motivos:

  1. a fonte do sistema muda de máquina para máquina — o mesmo menu ficaria
     com larguras diferentes no Windows e no Linux, e o layout, que é medido
     em pixels, sairia do lugar;
  2. `pygame.font` traz o SDL_ttf junto, e o projeto vive de não depender de
     nada além do pygame no frontend e de nada além da biblioteca padrão no
     emulador;
  3. tipografia suavizada ao lado de pixels quadrados de 1994 fica estranha.
     A interface tem de parecer parte do console, não uma janela colada nele.

Cada glifo cabe numa caixa de 5x7 pixels. Os acentos NÃO são glifos próprios:
são marcas de 2 linhas desenhadas por cima da letra base. Isso resolve o
português inteiro com cinco desenhos (agudo, grave, circunflexo, til, trema)
em vez de vinte e quatro letras acentuadas, e garante que `á` e `à` fiquem
exatamente com o mesmo corpo.

A marca é posicionada logo acima da primeira linha com tinta da letra — e não
numa altura fixa. Sem isso, o acento de um `ã` minúsculo flutuaria longe da
letra, no espaço reservado às maiúsculas.
"""

LARGURA = 5           # pixels de largura de um glifo
ALTURA = 7            # pixels de altura do corpo
ACIMA = 2             # linhas reservadas aos acentos, acima do corpo
ABAIXO = 2            # linhas reservadas à cedilha, abaixo do corpo

ALTURA_LINHA = ACIMA + ALTURA + ABAIXO      # 11
AVANCO = LARGURA + 1                        # 1 pixel de respiro entre letras

# ----------------------------------------------------------------------
# Os desenhos
# ----------------------------------------------------------------------
# Sete linhas de cinco colunas, separadas por "/". `#` é tinta, `.` é vazio.
# Escrever assim custa uma linha por caractere e permite conferir o desenho a
# olho nu — o formato compacto (hexadecimal) seria menor e impossível de
# revisar.
GLIFOS = {
    " ": "...../...../...../...../...../...../.....",

    "A": ".###./#...#/#...#/#####/#...#/#...#/#...#",
    "B": "####./#...#/#...#/####./#...#/#...#/####.",
    "C": ".###./#...#/#..../#..../#..../#...#/.###.",
    "D": "####./#...#/#...#/#...#/#...#/#...#/####.",
    "E": "#####/#..../#..../####./#..../#..../#####",
    "F": "#####/#..../#..../####./#..../#..../#....",
    "G": ".###./#...#/#..../#.###/#...#/#...#/.###.",
    "H": "#...#/#...#/#...#/#####/#...#/#...#/#...#",
    "I": ".###./..#../..#../..#../..#../..#../.###.",
    "J": "..###/...#./...#./...#./...#./#..#./.##..",
    "K": "#...#/#..#./#.#../##.../#.#../#..#./#...#",
    "L": "#..../#..../#..../#..../#..../#..../#####",
    "M": "#...#/##.##/#.#.#/#...#/#...#/#...#/#...#",
    "N": "#...#/##..#/#.#.#/#..##/#...#/#...#/#...#",
    "O": ".###./#...#/#...#/#...#/#...#/#...#/.###.",
    "P": "####./#...#/#...#/####./#..../#..../#....",
    "Q": ".###./#...#/#...#/#...#/#.#.#/#..#./.##.#",
    "R": "####./#...#/#...#/####./#.#../#..#./#...#",
    "S": ".####/#..../#..../.###./....#/....#/####.",
    "T": "#####/..#../..#../..#../..#../..#../..#..",
    "U": "#...#/#...#/#...#/#...#/#...#/#...#/.###.",
    "V": "#...#/#...#/#...#/#...#/#...#/.#.#./..#..",
    "W": "#...#/#...#/#...#/#...#/#.#.#/##.##/#...#",
    "X": "#...#/#...#/.#.#./..#../.#.#./#...#/#...#",
    "Y": "#...#/#...#/.#.#./..#../..#../..#../..#..",
    "Z": "#####/....#/...#./..#../.#.../#..../#####",

    "a": "...../...../.###./....#/.####/#...#/.####",
    "b": "#..../#..../####./#...#/#...#/#...#/####.",
    "c": "...../...../.###./#..../#..../#..../.###.",
    "d": "....#/....#/.####/#...#/#...#/#...#/.####",
    "e": "...../...../.###./#...#/#####/#..../.###.",
    "f": "..##./.#.../.#.../###../.#.../.#.../.#...",
    "g": "...../.####/#...#/#...#/.####/....#/.###.",
    "h": "#..../#..../####./#...#/#...#/#...#/#...#",
    "i": "..#../...../.##../..#../..#../..#../.###.",
    "j": "...#./...../..##./...#./...#./#..#./.##..",
    "k": "#..../#..../#..#./#.#../##.../#.#../#..#.",
    "l": ".##../..#../..#../..#../..#../..#../.###.",
    "m": "...../...../##.#./#.#.#/#.#.#/#.#.#/#.#.#",
    "n": "...../...../####./#...#/#...#/#...#/#...#",
    "o": "...../...../.###./#...#/#...#/#...#/.###.",
    "p": "...../####./#...#/#...#/####./#..../#....",
    "q": "...../.####/#...#/#...#/.####/....#/....#",
    "r": "...../...../#.##./##..#/#..../#..../#....",
    "s": "...../...../.####/#..../.###./....#/####.",
    "t": ".#.../.#.../###../.#.../.#.../.#..#/..##.",
    "u": "...../...../#...#/#...#/#...#/#..##/.##.#",
    "v": "...../...../#...#/#...#/#...#/.#.#./..#..",
    "w": "...../...../#...#/#...#/#.#.#/#.#.#/.#.#.",
    "x": "...../...../#...#/.#.#./..#../.#.#./#...#",
    "y": "...../#...#/#...#/#...#/.####/....#/.###.",
    "z": "...../...../#####/...#./..#../.#.../#####",

    "0": ".###./#...#/#..##/#.#.#/##..#/#...#/.###.",
    "1": "..#../.##../..#../..#../..#../..#../.###.",
    "2": ".###./#...#/....#/...#./..#../.#.../#####",
    "3": "#####/...#./..#../...#./....#/#...#/.###.",
    "4": "...#./..##./.#.#./#..#./#####/...#./...#.",
    "5": "#####/#..../####./....#/....#/#...#/.###.",
    "6": "..##./.#.../#..../####./#...#/#...#/.###.",
    "7": "#####/....#/...#./..#../.#.../.#.../.#...",
    "8": ".###./#...#/#...#/.###./#...#/#...#/.###.",
    "9": ".###./#...#/#...#/.####/....#/...#./.##..",

    ".": "...../...../...../...../...../.##../.##..",
    ",": "...../...../...../...../.##../.##../.#...",
    ":": "...../.##../.##../...../.##../.##../.....",
    ";": "...../.##../.##../...../.##../.##../.#...",
    "!": "..#../..#../..#../..#../..#../...../..#..",
    "?": ".###./#...#/....#/...#./..#../...../..#..",
    "-": "...../...../...../#####/...../...../.....",
    "_": "...../...../...../...../...../...../#####",
    "+": "...../..#../..#../#####/..#../..#../.....",
    "=": "...../...../#####/...../#####/...../.....",
    "*": "...../.#.#./..#../#####/..#../.#.#./.....",
    "/": "....#/....#/...#./..#../.#.../#..../#....",
    "\\": "#..../#..../.#.../..#../...#./....#/....#",
    "(": "...#./..#../.#.../.#.../.#.../..#../...#.",
    ")": ".#.../..#../...#./...#./...#./..#../.#...",
    "[": "..###/..#../..#../..#../..#../..#../..###",
    "]": "###../..#../..#../..#../..#../..#../###..",
    "<": "...#./..#../.#.../#..../.#.../..#../...#.",
    ">": ".#.../..#../...#./....#/...#./..#../.#...",
    "'": "..#../..#../...../...../...../...../.....",
    '"': ".#.#./.#.#./...../...../...../...../.....",
    "%": "##..#/##..#/...#./..#../.#.../#..##/#..##",
    "#": ".#.#./#####/.#.#./.#.#./#####/.#.#./.....",
    "&": ".##../#..#./#.#../.#.../#.#.#/#..#./.##.#",
    "@": ".###./#...#/#.###/#.#.#/#.###/#..../.###.",
    "|": "..#../..#../..#../..#../..#../..#../..#..",
    "~": "...../...../.##.#/#.##./...../...../.....",
    "$": "..#../.####/#.#../.###./..#.#/####./..#..",
    "°": ".##../#..#./.##../...../...../...../.....",

    # Setas — o seletor as usa para indicar rolagem e submenus.
    "↑": "..#../.###./#.#.#/..#../..#../..#../..#..",
    "↓": "..#../..#../..#../..#../#.#.#/.###./..#..",
    "←": "..#../.#.../#####/.#.../..#../...../.....",
    "→": "..#../...#./#####/...#./..#../...../.....",

    # `i` sem o pingo: quando leva acento, o pingo tem de sair.
    "ı": "...../...../.##../..#../..#../..#../.###.",
}

# ----------------------------------------------------------------------
# As marcas
# ----------------------------------------------------------------------
# Duas linhas cada. Vão acima da letra (ou abaixo, no caso da cedilha).
MARCAS = {
    "agudo":        "...#./..#..",
    "grave":        ".#.../..#..",
    "circunflexo":  "..#../.#.#.",
    "til":          ".##.#/#.##.",
    "trema":        ".#.#./.....",
    "cedilha":      "..#../..##.",     # esta desce, não sobe
}

# Letra base + marca. Cobre o português; acrescentar espanhol ou francês é
# só estender esta tabela, sem desenhar nada.
COMPOSTOS = {
    "á": ("a", "agudo"),      "Á": ("A", "agudo"),
    "à": ("a", "grave"),      "À": ("A", "grave"),
    "â": ("a", "circunflexo"), "Â": ("A", "circunflexo"),
    "ã": ("a", "til"),        "Ã": ("A", "til"),
    "é": ("e", "agudo"),      "É": ("E", "agudo"),
    "ê": ("e", "circunflexo"), "Ê": ("E", "circunflexo"),
    "í": ("ı", "agudo"), "Í": ("I", "agudo"),
    "ó": ("o", "agudo"),      "Ó": ("O", "agudo"),
    "ô": ("o", "circunflexo"), "Ô": ("O", "circunflexo"),
    "õ": ("o", "til"),        "Õ": ("O", "til"),
    "ú": ("u", "agudo"),      "Ú": ("U", "agudo"),
    "ü": ("u", "trema"),      "Ü": ("U", "trema"),
    "ç": ("c", "cedilha"),    "Ç": ("C", "cedilha"),
}

SUBSTITUTO = "?"      # o que aparece no lugar de um caractere sem desenho


# ----------------------------------------------------------------------
def _bits(desenho):
    """
    Converte o desenho em texto numa tupla de inteiros, um por linha.

    Cada `#` vira um bit ligado, na posição correspondente. Guardar assim é o que
    permite desenhar rápido: testar um pixel vira uma operação de bits, e não uma
    busca numa string.
    """
    linhas = []
    for linha in desenho.split("/"):
        valor = 0
        for x, c in enumerate(linha):
            if c == "#":
                valor |= 1 << (LARGURA - 1 - x)
        linhas.append(valor)
    return tuple(linhas)


_CORPOS = {c: _bits(d) for c, d in GLIFOS.items()}
_MARCAS = {n: _bits(d) for n, d in MARCAS.items()}

_CACHE = {}


def linhas(ch):
    """
    O caractere pronto: `ALTURA_LINHA` inteiros de `LARGURA` bits cada.

    A linha 0 é o topo da caixa, onde ficam os acentos, e a última é o fundo, onde
    fica a cedilha. O bit mais alto de cada inteiro é o pixel mais à esquerda.

    O resultado fica em cache porque o menu redesenha as mesmas letras sessenta
    vezes por segundo, e montar a caixa envolve várias operações.
    """
    pronto = _CACHE.get(ch)
    if pronto is not None:
        return pronto

    base, marca = COMPOSTOS.get(ch, (ch, None))
    corpo = _CORPOS.get(base)
    if corpo is None:
        corpo = _CORPOS[SUBSTITUTO]
        marca = None

    caixa = [0] * ALTURA_LINHA
    for i, valor in enumerate(corpo):
        caixa[ACIMA + i] = valor

    if marca == "cedilha":
        # A cedilha pende da última linha COM TINTA do corpo, e não do fundo
        # da caixa: pendurada no fundo ela se descolaria do `c` minúsculo.
        fim = max((i for i, v in enumerate(corpo) if v), default=ALTURA - 1)
        topo = ACIMA + fim + 1
        for i, valor in enumerate(_MARCAS[marca]):
            if topo + i < ALTURA_LINHA:
                caixa[topo + i] |= valor
    elif marca:
        # Acento colado no topo da tinta: numa maiúscula ele sobe até a borda
        # da caixa; numa minúscula desce junto, acompanhando a letra.
        inicio = min((i for i, v in enumerate(corpo) if v), default=0)
        topo = max(0, ACIMA + inicio - 2)
        for i, valor in enumerate(_MARCAS[marca]):
            caixa[topo + i] |= valor

    pronto = tuple(caixa)
    _CACHE[ch] = pronto
    return pronto


def largura_do_texto(texto):
    """A largura em pixels, sem escala. O último caractere não leva respiro."""
    if not texto:
        return 0
    return len(texto) * AVANCO - 1


def cortar(texto, largura_maxima):
    """
    Encurta o texto para caber numa largura, com reticências.

    Nomes de arquivo de ROM são longos e não cabem na tela. Cortar no meio de uma
    palavra sem avisar faria parecer que o nome é aquele mesmo — as reticências
    avisam que houve corte.
    """
    if largura_do_texto(texto) <= largura_maxima:
        return texto
    cabem = (largura_maxima + 1) // AVANCO
    if cabem <= 3:
        return texto[:max(0, cabem)]
    return texto[:cabem - 3] + "..."
