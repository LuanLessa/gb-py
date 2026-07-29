"""
A pasta de jogos vista pelo seletor de ROMs.

Duas decisões que valem explicação:

**Subpastas são navegáveis.** A `roms/` deste projeto não tem só jogos: tem a
suíte da Mooneye, a SameSuite, as ROMs de teste da Mealybug — cada uma numa
subpasta com dezenas de arquivos. Um seletor que só enxergasse o primeiro
nível serviria para jogar e não serviria para testar.

**O título é lido com preguiça.** A pasta da Mooneye sozinha tem centenas de
ROMs; abrir todas para montar a lista faria o menu demorar visivelmente para
aparecer. Então a lista mostra o nome do arquivo na hora, e o título gravado
no cabeçalho só é lido para as linhas que estão na tela — algumas dezenas, no
pior caso. O resultado fica em cache, com a data de modificação junto, para
não reler nada duas vezes.

Ler o cabeçalho custa 0x50 bytes: não carregamos a ROM inteira só para saber
o nome dela.
"""

import os

EXTENSOES = (".gb", ".gbc")

# Onde ficam os campos do cabeçalho do cartucho.
_INICIO = 0x100
_FIM = 0x150
_TITULO = (0x134, 0x144)
_FLAG_CGB = 0x143
_TIPO = 0x147


class Entrada:
    """Uma linha do seletor: uma pasta, um jogo, ou o item de voltar."""

    __slots__ = ("nome", "caminho", "pasta", "subir")

    def __init__(self, nome, caminho, pasta=False, subir=False):
        self.nome = nome
        self.caminho = caminho
        self.pasta = pasta
        self.subir = subir

    def __repr__(self):
        que = "pasta" if self.pasta else "rom"
        return f"<Entrada {que} {self.nome!r}>"


def ler_cabecalho(caminho):
    """
    Lê o cabeçalho do cartucho sem carregar a ROM inteira.

    São 0x50 bytes, contra até 8 MB do arquivo completo. A diferença aparece ao
    montar uma lista com centenas de ROMs.

    O checksum não é conferido de propósito: ROMs de teste caseiras costumam tê-lo
    errado, e são justamente as mais interessantes de rodar aqui.
    """
    try:
        with open(caminho, "rb") as f:
            f.seek(_INICIO)
            cabecalho = f.read(_FIM - _INICIO)
    except OSError:
        return None

    if len(cabecalho) < _FIM - _INICIO:
        return None

    def byte(endereco):
        return cabecalho[endereco - _INICIO]

    cru = bytes(cabecalho[_TITULO[0] - _INICIO:_TITULO[1] - _INICIO])
    cru = cru.split(b"\x00", 1)[0]
    titulo = "".join(chr(b) for b in cru if 32 <= b < 127).strip()

    flag = byte(_FLAG_CGB)
    return {
        "titulo": titulo,
        "so_cgb": flag == 0xC0,
        "suporta_cgb": flag in (0x80, 0xC0),
        "tipo": byte(_TIPO),
    }


def listar(pasta):
    """
    As entradas de uma pasta: subpastas primeiro, depois as ROMs.

    Pastas antes de arquivos porque é assim que todo gerenciador de arquivos faz — e
    porque as subpastas são poucas e os arquivos são muitos, então misturá-los
    esconderia as pastas no meio da rolagem.
    """
    entradas = []

    pai = os.path.dirname(os.path.abspath(pasta))
    if pai and pai != os.path.abspath(pasta):
        entradas.append(Entrada("..", pai, pasta=True, subir=True))

    try:
        with os.scandir(pasta) as itens:
            pastas, roms = [], []
            for item in itens:
                if item.name.startswith("."):
                    continue
                try:
                    if item.is_dir():
                        pastas.append(Entrada(item.name, item.path, pasta=True))
                    elif os.path.splitext(item.name)[1].lower() in EXTENSOES:
                        roms.append(Entrada(item.name, item.path))
                except OSError:
                    continue        # link quebrado, permissão negada
    except OSError:
        return entradas

    chave = lambda e: e.nome.lower()      # noqa: E731
    entradas.extend(sorted(pastas, key=chave))
    entradas.extend(sorted(roms, key=chave))
    return entradas


class Biblioteca:
    """
    A pasta atual do seletor, e o cache dos títulos já lidos.

    O título é lido com PREGUIÇA, e essa é a decisão que faz o seletor abrir na hora.
    A pasta de testes da Mooneye sozinha tem centenas de ROMs; abrir todas para
    montar a lista faria o menu demorar visivelmente. Então a lista mostra o nome do
    arquivo imediatamente, e o título gravado no cabeçalho só é lido para as linhas
    que estão na tela — algumas dezenas, no pior caso.

    O resultado fica em cache junto com a data de modificação do arquivo, o que
    evita reler e ao mesmo tempo detecta se a ROM foi trocada.
    """

    def __init__(self, pasta):
        self.pasta = os.path.abspath(pasta)
        self.entradas = []
        self._cache = {}          # caminho → (mtime, cabeçalho)
        self.reler()

    def reler(self):
        """Relê a pasta atual do disco."""
        self.entradas = listar(self.pasta)
        return self.entradas

    def entrar(self, entrada):
        """Navega para uma subpasta. Devolve True se a pasta mudou."""
        if not entrada.pasta:
            return False
        self.pasta = os.path.abspath(entrada.caminho)
        self.reler()
        return True

    def cabecalho(self, entrada):
        """O cabeçalho do cartucho, lido sob demanda e guardado em cache."""
        if entrada.pasta:
            return None
        try:
            mtime = os.path.getmtime(entrada.caminho)
        except OSError:
            return None

        guardado = self._cache.get(entrada.caminho)
        if guardado and guardado[0] == mtime:
            return guardado[1]

        cabecalho = ler_cabecalho(entrada.caminho)
        self._cache[entrada.caminho] = (mtime, cabecalho)
        return cabecalho

    def descricao(self, entrada):
        """
        O texto da segunda coluna do seletor.

        O nome do arquivo já está na primeira coluna. O que ajuda aqui é o que o nome do
        arquivo NÃO diz: como o cartucho se chama de verdade, e se ele vai rodar neste
        emulador — que é um DMG e recusa ROMs exclusivas de Color.
        """
        if entrada.subir:
            return "pasta acima"
        if entrada.pasta:
            return "pasta"
        cabecalho = self.cabecalho(entrada)
        if cabecalho is None:
            return "ilegível"
        if cabecalho["so_cgb"]:
            return "só Game Boy Color"
        return cabecalho["titulo"] or "sem título"
