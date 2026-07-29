"""
Testes da interface.

Nenhum deles abre uma janela. Isso é possível porque a única parte da `ui/`
que fala com o pygame é o `desenho.py`; fonte, menus, preferências e leitura
da pasta de jogos são Python puro. O que se ganha com isso é o mesmo que se
ganha nos testes da CPU: dá para conferir o comportamento de verdade, rápido,
sem placa de vídeo e sem ninguém apertando tecla.

O que estes testes cobrem, e por quê:

  * a FONTE tem de ter desenho para tudo que o menu escreve. Um caractere sem
    glifo vira "?" silenciosamente — o menu não quebra, ele só fica errado, que
    é pior. O teste varre todo o texto da interface;
  * as PREFERÊNCIAS não podem derrubar o emulador. Arquivo corrompido, valor
    absurdo, pasta sem permissão: tudo tem de virar "seguiu com os padrões";
  * o MENU é uma máquina de estados, e máquinas de estados quebram nas bordas —
    a volta no fim da lista, o item que não se seleciona, a pilha de páginas.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from harness import Suite                                    # noqa: E402
from ui import biblioteca, config, fonte, menu, paletas      # noqa: E402

s = Suite("Interface")


# ======================================================================
# Fonte
# ======================================================================
def teste_fonte_tem_as_dimensoes_declaradas():
    """Todo glifo cabe na caixa que o resto do código assume."""
    for ch in ("A", "z", "0", "ç", "Ã", " ", "?"):
        linhas = fonte.linhas(ch)
        s.igual(len(linhas), fonte.ALTURA_LINHA,
                f"o glifo {ch!r} tem {fonte.ALTURA_LINHA} linhas")
        s.checar(all(0 <= v < (1 << fonte.LARGURA) for v in linhas),
                 f"o glifo {ch!r} cabe em {fonte.LARGURA} pixels de largura")


def teste_fonte_cobre_todo_o_texto_da_interface():
    """
    Um caractere sem desenho não quebra nada — ele vira "?".

    É justamente esse o problema: o menu continua funcionando e ninguém
    percebe que "Configurações" virou "Configura?ões". Então varremos tudo que
    a interface escreve e exigimos desenho para cada caractere.
    """
    textos = []
    prefs = config.Preferencias(_arquivo_temporario())
    m = menu.Menu(prefs, _BibliotecaFalsa([]))
    m.abrir()
    for pagina in (m._pagina_pausa(), m._pagina_ajustes()):
        textos.append(pagina.titulo)
        textos.append(pagina.rodape)
        for item in pagina.itens:
            textos.append(item.rotulo)
            textos.append(item.valor_texto())
    for _, rotulo in paletas.OPCOES:
        textos.append(rotulo)
    textos += ["pasta acima", "pasta", "ilegível", "sem título",
               "só Game Boy Color", "(nenhuma ROM nesta pasta)",
               "nenhuma pasta de jogos configurada", "Escolha um jogo"]

    faltando = sorted({c for t in textos for c in t
                       if c not in fonte.GLIFOS and c not in fonte.COMPOSTOS})
    s.checar(not faltando,
             "toda a interface usa caracteres que a fonte sabe desenhar",
             f"sem desenho: {faltando}")


def teste_acento_fica_colado_na_letra():
    """
    O acento acompanha a altura da letra, e não uma altura fixa.

    Numa maiúscula ele encosta no topo da caixa; numa minúscula desce junto.
    Fixá-lo no topo faria o til do `ã` flutuar dois pixels acima da letra.
    """
    def topo(ch):
        linhas = fonte.linhas(ch)
        return next(i for i, v in enumerate(linhas) if v)

    s.checar(topo("Ã") < topo("ã"),
             "o til da maiúscula fica acima do til da minúscula",
             f"Ã na linha {topo('Ã')}, ã na linha {topo('ã')}")

    # O corpo tem de continuar igual ao da letra sem acento: a marca só
    # acrescenta tinta acima, nunca reescreve a letra.
    inicio = topo("a")
    s.igual(fonte.linhas("ã")[inicio:], fonte.linhas("a")[inicio:],
            "o corpo do 'ã' é o mesmo do 'a'")
    s.checar(all(a & b == a for a, b in zip(fonte.linhas("a"), fonte.linhas("ã"))),
             "nenhum pixel do 'a' se perde ao receber o til")


def teste_i_perde_o_pingo_quando_acentuado():
    """`í` com pingo E acento vira uma coluna de três pontos."""
    tinta = sum(bin(v).count("1") for v in fonte.linhas("í"))
    tinta_ponto_i = sum(bin(v).count("1") for v in fonte.linhas("i"))
    tinta_acento = sum(bin(v).count("1") for v in fonte._MARCAS["agudo"])
    s.igual(tinta, tinta_ponto_i - 1 + tinta_acento,
            "o 'í' troca o pingo pelo acento em vez de acumular os dois")


def teste_cedilha_desce_e_nao_invade_a_letra():
    """A cedilha pende abaixo do 'c' sem apagar nada dele."""
    c = fonte.linhas("c")
    cedilha = fonte.linhas("ç")
    fim = max(i for i, v in enumerate(c) if v)
    s.igual(cedilha[:fim + 1], c[:fim + 1],
            "a cedilha não mexe no corpo do 'c'")
    s.checar(any(cedilha[fim + 1:]), "a cedilha aparece abaixo do 'c'")


def teste_corte_cabe_na_largura_pedida():
    """
    Texto cortado tem de caber MESMO, em qualquer largura.

    Inclusive nas larguras absurdas: zero, e menor que as próprias reticências.
    """
    longo = "Legend of Zelda, The - Link's Awakening (USA, Europe).gb"
    for limite in (0, 10, 30, 60, 200):
        cortado = fonte.cortar(longo, limite)
        s.checar(fonte.largura_do_texto(cortado) <= limite,
                 f"o texto cortado cabe em {limite} pixels",
                 f"{fonte.largura_do_texto(cortado)} > {limite}: {cortado!r}")
    s.igual(fonte.cortar("curto", 500), "curto", "texto que já cabe não é mexido")
    s.checar(fonte.cortar(longo, 100).endswith("..."),
             "o corte avisa que houve corte")


# ======================================================================
# Preferências
# ======================================================================
def _arquivo_temporario():
    fd, caminho = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(caminho)          # queremos o NOME, não o arquivo
    return caminho


def teste_preferencias_vao_e_voltam():
    """O que foi salvo é o que volta na próxima execução."""
    caminho = _arquivo_temporario()
    try:
        p = config.Preferencias(caminho)
        p["escala"] = 5
        p["paleta"] = "ambar"
        p["ultima_rom"] = "roms/Tetris.gb"
        s.checar(p.salvar(), "as preferências foram gravadas")

        q = config.Preferencias(caminho)
        s.igual(q["escala"], 5, "a escala voltou do arquivo")
        s.igual(q["paleta"], "ambar", "a paleta voltou do arquivo")
        s.igual(q["ultima_rom"], "roms/Tetris.gb", "a última ROM voltou")
    finally:
        if os.path.exists(caminho):
            os.unlink(caminho)


def teste_preferencias_sobrevivem_a_arquivo_corrompido():
    """
    O arquivo é texto: alguém vai editá-lo à mão, e vai errar.

    Um traceback antes do jogo abrir, por causa de uma vírgula sobrando num
    arquivo de configuração, é um jeito ruim de perder o usuário.
    """
    caminho = _arquivo_temporario()
    try:
        for lixo in ("{isto não é json", "[]", "null", ""):
            with open(caminho, "w", encoding="utf-8") as f:
                f.write(lixo)
            p = config.Preferencias(caminho)
            s.igual(p["escala"], config.CAMPOS["escala"][0],
                    f"padrão preservado com o arquivo contendo {lixo!r}")
    finally:
        os.unlink(caminho)


def teste_preferencias_recusam_valores_absurdos():
    """
    `escala: 400` abriria uma janela maior que o monitor — e a interface para
    corrigir isso estaria fora da tela. O valor é limitado na leitura.
    """
    caminho = _arquivo_temporario()
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"escala": 400, "volume": -50, "som": "talvez",
                       "paleta": 7}, f)
        p = config.Preferencias(caminho)
        s.igual(p["escala"], 8, "a escala é limitada ao máximo")
        s.igual(p["volume"], 0, "o volume é limitado ao mínimo")
        s.igual(p["som"], True, "um booleano inválido volta ao padrão")
        s.igual(p["paleta"], "verde", "uma paleta não-texto volta ao padrão")
    finally:
        os.unlink(caminho)


def teste_preferencias_nao_quebram_sem_permissao_de_escrita():
    """
    Uma pasta onde não dá para escrever devolve False, e não uma exceção.

    Perder a configuração é irritante; não conseguir jogar por causa disso seria bem
    pior.
    """
    p = config.Preferencias(os.path.join(
        tempfile.gettempdir(), "pasta-que-nao-existe-gbpy", "x.json"))
    s.checar(p.salvar() is False, "gravar numa pasta inexistente devolve False")
    s.checar(p.somente_leitura, "e o módulo passa a se saber somente-leitura")
    s.igual(p["escala"], 3, "os padrões continuam de pé")


# ======================================================================
# Biblioteca
# ======================================================================
def _rom_falsa(caminho, titulo, flag_cgb=0x00):
    """Escreve um arquivo com um cabeçalho de cartucho válido e nada mais."""
    dados = bytearray(0x150)
    nome = titulo.encode("ascii")[:16]
    dados[0x134:0x134 + len(nome)] = nome
    dados[0x143] = flag_cgb
    dados[0x147] = 0x13         # MBC3+RAM+BATTERY
    with open(caminho, "wb") as f:
        f.write(dados)


def teste_biblioteca_le_o_titulo_do_cabecalho():
    """O seletor mostra o nome do cartucho, e não só o do arquivo."""
    with tempfile.TemporaryDirectory() as pasta:
        _rom_falsa(os.path.join(pasta, "b.gb"), "TETRIS")
        _rom_falsa(os.path.join(pasta, "a.gb"), "ZELDA", flag_cgb=0xC0)
        os.mkdir(os.path.join(pasta, "sub"))
        with open(os.path.join(pasta, "leiame.txt"), "w") as f:
            f.write("não é uma rom")

        b = biblioteca.Biblioteca(pasta)
        nomes = [e.nome for e in b.entradas]
        s.checar("leiame.txt" not in nomes,
                 "arquivos que não são ROM ficam de fora", str(nomes))
        s.checar(nomes.index("sub") < nomes.index("a.gb"),
                 "as pastas vêm antes dos arquivos", str(nomes))
        s.checar(nomes[0] == "..", "a primeira entrada é a pasta acima")

        por_nome = {e.nome: e for e in b.entradas}
        s.igual(b.descricao(por_nome["b.gb"]), "TETRIS",
                "o título vem do cabeçalho, não do nome do arquivo")
        s.igual(b.descricao(por_nome["a.gb"]), "só Game Boy Color",
                "uma ROM exclusiva de Color é anunciada como tal")
        s.igual(b.descricao(por_nome["sub"]), "pasta", "pastas se identificam")


def teste_biblioteca_navega_entre_pastas():
    """Entrar numa subpasta e voltar leva de volta ao mesmo lugar."""
    with tempfile.TemporaryDirectory() as pasta:
        dentro = os.path.join(pasta, "testes")
        os.mkdir(dentro)
        _rom_falsa(os.path.join(dentro, "mooneye.gb"), "MOONEYE")

        b = biblioteca.Biblioteca(pasta)
        alvo = next(e for e in b.entradas if e.nome == "testes")
        s.checar(b.entrar(alvo), "entrar numa subpasta funciona")
        s.igual([e.nome for e in b.entradas if not e.subir], ["mooneye.gb"],
                "a listagem passou a ser a da subpasta")

        acima = next(e for e in b.entradas if e.subir)
        b.entrar(acima)
        s.igual(os.path.abspath(b.pasta), os.path.abspath(pasta),
                "e dá para voltar por onde se entrou")


def teste_biblioteca_aguenta_arquivo_menor_que_o_cabecalho():
    """Um `.gb` truncado não pode derrubar o seletor — só não tem título."""
    with tempfile.TemporaryDirectory() as pasta:
        with open(os.path.join(pasta, "quebrada.gb"), "wb") as f:
            f.write(b"\x00" * 16)
        b = biblioteca.Biblioteca(pasta)
        entrada = next(e for e in b.entradas if e.nome == "quebrada.gb")
        s.igual(b.descricao(entrada), "ilegível", "o arquivo truncado é marcado")


# ======================================================================
# Menu
# ======================================================================
class _EntradaFalsa:
    def __init__(self, nome, pasta=False, subir=False):
        self.nome = nome
        self.caminho = f"/roms/{nome}"
        self.pasta = pasta
        self.subir = subir


class _BibliotecaFalsa:
    def __init__(self, entradas):
        self.entradas = list(entradas)
        self.pasta = "/roms"
        self.entrou = []

    def entrar(self, entrada):
        self.entrou.append(entrada.nome)
        self.entradas = [_EntradaFalsa("dentro.gb")]
        return True

    def descricao(self, entrada):
        return "pasta" if entrada.pasta else "TESTE"


def _menu(entradas=(), tem_jogo=True, mudancas=None):
    prefs = config.Preferencias(_arquivo_temporario())
    prefs.somente_leitura = True          # o teste não grava nada em disco
    registrar = (lambda c, v: mudancas.append((c, v))) if mudancas is not None else None
    m = menu.Menu(prefs, _BibliotecaFalsa(entradas), registrar, tem_jogo=tem_jogo)
    m.abrir()
    return m


def teste_menu_abre_no_pausa_e_fecha_no_continuar():
    """O caminho mais curto do menu, e o mais usado."""
    m = _menu()
    s.igual(m.pagina.titulo, "gb-py", "o menu abre na página de pausa")
    s.igual(m.pagina.item().rotulo, "Continuar",
            "o primeiro item é o que o jogador mais vai querer")
    s.igual(m.tecla("confirmar"), ("continuar",), "confirmar devolve a ação")
    s.checar(not m.aberto, "e o menu se fecha sozinho")


def teste_menu_sem_jogo_vai_direto_para_a_selecao():
    """
    Sem cartucho não existe "continuar". Cair num menu cujo primeiro item é
    inútil convida a apertar Enter à toa; o certo é já mostrar a lista.
    """
    m = _menu([_EntradaFalsa("jogo.gb")], tem_jogo=False)
    s.checar(m.pagina.rolavel, "o menu abre direto no seletor de jogos")
    s.checar(m.tecla("voltar") is None and m.aberto,
             "e Esc não fecha o menu, porque não há para onde voltar")


def teste_selecao_da_a_volta_no_fim_da_lista():
    """
    Subir do primeiro item leva ao último, e descer do último volta ao primeiro.

    Num menu operado pelo direcional, parar na borda passa a impressão de que a
    tecla travou.
    """
    entradas = [_EntradaFalsa(f"{i}.gb") for i in range(4)]
    m = _menu(entradas)
    m.tecla("confirmar")           # Continuar? não — vamos até "Trocar de jogo"
    m = _menu(entradas)
    m.tecla("baixo"); m.tecla("baixo")
    s.igual(m.pagina.item().rotulo, "Trocar de jogo", "chegamos no item certo")
    m.tecla("confirmar")
    s.checar(m.pagina.rolavel, "o seletor abriu")

    m.tecla("cima")
    s.igual(m.pagina.selecionado, len(entradas) - 1,
            "subir a partir do primeiro leva ao último")
    m.tecla("baixo")
    s.igual(m.pagina.selecionado, 0, "e descer do último volta ao primeiro")


def teste_selecao_entra_em_pasta_e_carrega_rom():
    """Confirmar numa pasta navega; confirmar numa ROM carrega."""
    m = _menu([_EntradaFalsa("suite", pasta=True), _EntradaFalsa("jogo.gb")])
    m.pilha.append(m._pagina_selecao())

    s.checar(m.tecla("confirmar") is None,
             "confirmar numa pasta não devolve ação nenhuma")
    s.igual(m.biblioteca.entrou, ["suite"], "ele entra na pasta")
    s.igual(m.pagina.selecionado, 0, "e o cursor volta ao topo da nova lista")

    acao = m.tecla("confirmar")
    s.igual(acao, ("carregar", "/roms/dentro.gb"),
            "confirmar numa ROM devolve o caminho para o frontend")
    s.checar(not m.aberto, "e o menu fecha para o jogo aparecer")


def teste_rolagem_acompanha_o_cursor():
    """O item selecionado está sempre dentro da janela visível."""
    entradas = [_EntradaFalsa(f"{i}.gb") for i in range(50)]
    m = _menu(entradas)
    m.pilha.append(m._pagina_selecao())
    pagina = m.pagina
    pagina.visiveis = 8

    for _ in range(20):
        m.tecla("baixo")
    s.checar(pagina.primeiro <= pagina.selecionado < pagina.primeiro + 8,
             "o item selecionado está sempre dentro da janela visível",
             f"primeiro={pagina.primeiro} selecionado={pagina.selecionado}")

    m.tecla("pagina_baixo")
    s.checar(pagina.primeiro <= pagina.selecionado < pagina.primeiro + 8,
             "inclusive depois de saltar uma tela inteira",
             f"primeiro={pagina.primeiro} selecionado={pagina.selecionado}")
    s.checar(pagina.primeiro + 8 <= len(entradas),
             "a janela nunca passa do fim da lista",
             f"primeiro={pagina.primeiro} de {len(entradas)}")


def teste_ajustes_aplicam_na_hora():
    """
    Mudar o volume e só ouvir a diferença ao fechar o menu seria inútil — o
    ajuste tem de valer enquanto o dedo ainda está na seta.
    """
    mudancas = []
    m = _menu(mudancas=mudancas)
    m.pilha.append(m._pagina_ajustes())

    volume = next(i for i in m.pagina.itens if i.rotulo == "Volume")
    m.pagina.selecionado = m.pagina.itens.index(volume)
    antes = volume.valor
    m.tecla("esquerda")
    s.igual(volume.valor, antes - 10, "a seta esquerda baixa o volume")
    s.igual(mudancas[-1], ("volume", antes - 10),
            "e o frontend é avisado imediatamente")

    for _ in range(30):
        m.tecla("esquerda")
    s.igual(volume.valor, 0, "o volume não passa de zero")
    s.igual(volume.valor_texto(), "mudo", "e zero se anuncia como 'mudo'")


def teste_paleta_gira_pelas_opcoes():
    """Girar passa por todas as paletas e volta ao ponto de partida."""
    m = _menu()
    m.pilha.append(m._pagina_ajustes())
    paleta = next(i for i in m.pagina.itens if i.rotulo == "Paleta")
    vistas = set()
    for _ in range(len(paletas.OPCOES)):
        vistas.add(paleta.valor)
        paleta.ajustar(1)
    s.igual(len(vistas), len(paletas.OPCOES),
            "girar passa por todas as paletas antes de repetir")
    s.igual(paleta.valor, m.prefs["paleta"],
            "e a volta completa devolve ao ponto de partida")


def teste_separador_nao_se_seleciona():
    """Um item de espaçamento no meio do menu não pode receber o cursor."""
    m = _menu()
    m.pilha.append(m._pagina_ajustes())
    pagina = m.pagina
    posicoes = set()
    for _ in range(len(pagina.itens) * 2):
        posicoes.add(pagina.selecionado)
        m.tecla("baixo")
    naveg = {i for i, item in enumerate(pagina.itens) if item.selecionavel}
    s.igual(posicoes, naveg, "o cursor visita exatamente os itens selecionáveis")


def teste_pilha_de_paginas_volta_passo_a_passo():
    """
    Esc sobe um nível por vez, e só fecha o menu no topo.

    É a mesma estrutura do botão "voltar" de um navegador.
    """
    m = _menu([_EntradaFalsa("jogo.gb")])
    m.pilha.append(m._pagina_ajustes())
    s.igual(len(m.pilha), 2, "estamos dois níveis abaixo")
    s.checar(m.tecla("voltar") is None, "Esc no submenu não devolve ação")
    s.igual(len(m.pilha), 1, "só sobe um nível")
    s.igual(m.tecla("voltar"), ("continuar",),
            "e no topo o Esc volta para o jogo")


# ======================================================================
# Desenho
# ======================================================================
#
# O `ui/desenho.py` é o único arquivo da interface que importa pygame, e num
# servidor de testes não há pygame nem monitor. Em vez de deixar o desenho sem
# teste nenhum, damos a ele um pygame de mentira que, em vez de pintar, anota
# onde cada retângulo caiu.
#
# Isso não prova que o menu ficou bonito — nenhum teste prova isso. Prova o
# que dá para provar sozinho, e que é justamente onde o cálculo de layout
# costuma errar: nada é desenhado fora da janela, nada tem largura negativa, e
# a lista longa não escorre para fora do painel.
class _SuperficieFalsa:
    def __init__(self, tamanho, registro=None):
        self.tamanho = tamanho
        self.registro = registro if registro is not None else []

    def get_size(self):
        return self.tamanho

    def fill(self, cor, rect=None):
        self.registro.append(("fill", rect or (0, 0) + self.tamanho))

    def blit(self, origem, posicao):
        largura, altura = origem.get_size()
        self.registro.append(("blit", (posicao[0], posicao[1], largura, altura)))

    def set_colorkey(self, cor):
        pass

    def set_alpha(self, a):
        pass

    def convert(self):
        return self


def _pygame_falso():
    import types
    falso = types.ModuleType("pygame")
    falso.error = RuntimeError
    falso.Surface = lambda tamanho: _SuperficieFalsa(tamanho)
    return falso


def _desenhar(pagina_extra=None, tamanho=(480, 432), escala=3, entradas=()):
    """Desenha um menu com o pygame de mentira e devolve o que foi pintado."""
    import types
    salvo = sys.modules.get("pygame")
    sys.modules["pygame"] = _pygame_falso()
    try:
        for nome in list(sys.modules):
            if nome.startswith("ui.desenho"):
                del sys.modules[nome]
        from ui import desenho
        desenho.esquecer_cache()

        m = _menu(entradas)
        if pagina_extra:
            m.pilha.append(pagina_extra(m))

        registro = []
        tela = _SuperficieFalsa(tamanho, registro)
        desenho.desenhar(tela, m, paletas.tons("verde"), escala)
        return registro, m
    finally:
        if salvo is not None:
            sys.modules["pygame"] = salvo
        else:
            del sys.modules["pygame"]
        for nome in list(sys.modules):
            if nome.startswith("ui.desenho"):
                del sys.modules[nome]


def _fora_da_janela(registro, tamanho):
    largura, altura = tamanho
    fora = []
    for tipo, (x, y, w, h) in registro:
        if w < 0 or h < 0:
            fora.append(("tamanho negativo", tipo, (x, y, w, h)))
        elif x < 0 or y < 0 or x + w > largura or y + h > altura:
            fora.append(("fora da janela", tipo, (x, y, w, h)))
    return fora


TAMANHOS = (((160, 144), 1), ((320, 288), 2), ((480, 432), 3),
            ((640, 576), 4), ((1280, 1152), 8),
            # Larga e baixa. Numa janela com a forma do Game Boy é sempre a
            # LARGURA que aperta primeiro, e o teste nunca chegaria a exercitar
            # o limite de altura — que é o que vai apertar no dia em que
            # alguém acrescentar itens ao menu de ajustes.
            ((640, 200), 4))


def teste_menu_cabe_em_qualquer_janela():
    """
    De 160x144 (o tamanho da tela do console) a 1280x1152.

    A janela 1x é o caso que quebra: nela o menu de ajustes, na fonte
    confortável, precisaria de quase 200 pixels de altura e sairia pela borda.
    A fonte tem de encolher até caber, e o teste existe para que ela continue
    encolhendo quando alguém acrescentar um item ao menu.
    """
    longo = "Legend of Zelda, The - Link's Awakening (USA, Europe) (Rev 2).gb"
    listona = [_EntradaFalsa(longo) for _ in range(40)]
    paginas = (
        ("pausa", None, ()),
        ("ajustes", lambda m: m._pagina_ajustes(), ()),
        ("seletor", lambda m: m._pagina_selecao(), listona),
        ("pasta vazia", lambda m: m._pagina_selecao(), []),
    )
    for tamanho, escala in TAMANHOS:
        for nome, fabrica, entradas in paginas:
            registro, _ = _desenhar(fabrica, tamanho=tamanho, escala=escala,
                                    entradas=entradas)
            onde = f"{nome} em {tamanho[0]}x{tamanho[1]}"
            s.checar(len(registro) > 20, f"o menu desenhou algo — {onde}",
                     f"{len(registro)} operações")
            fora = _fora_da_janela(registro, tamanho)
            s.checar(not fora, f"nada escapa da janela — {onde}", str(fora[:2]))


def teste_lista_longa_mostra_so_o_que_cabe():
    """
    Cinquenta ROMs numa janela que comporta quinze.

    O caso que quebra layout de lista é sempre este: desenhar mais linhas do
    que cabem, e as últimas saírem pelo rodapé do painel.
    """
    entradas = [_EntradaFalsa(f"jogo-numero-{i:02d}.gb") for i in range(50)]
    registro, m = _desenhar(lambda mm: mm._pagina_selecao(), entradas=entradas)
    s.checar(not _fora_da_janela(registro, (480, 432)),
             "a lista longa não escorre para fora")
    s.checar(m.pagina.visiveis < len(entradas),
             "o desenho informou à página quantas linhas cabem",
             f"visiveis={m.pagina.visiveis}")

    # Numa janela mais baixa cabem menos linhas — se este número não mudar, a
    # página está usando um valor fixo em vez do espaço real.
    _, baixa = _desenhar(lambda mm: mm._pagina_selecao(),
                         tamanho=(480, 216), escala=3, entradas=entradas)
    s.checar(baixa.pagina.visiveis < m.pagina.visiveis,
             "uma janela mais baixa mostra menos linhas",
             f"{baixa.pagina.visiveis} contra {m.pagina.visiveis}")


def teste_lista_vazia_nao_quebra():
    """Uma pasta sem ROM nenhuma é comum — e não pode virar divisão por zero."""
    registro, _ = _desenhar(lambda m: m._pagina_selecao(), entradas=[])
    s.checar(len(registro) > 5, "a lista vazia ainda desenha o painel e o aviso")
    s.checar(not _fora_da_janela(registro, (480, 432)),
             "e continua dentro da janela")


def teste_todas_as_paletas_tem_quatro_tons_do_claro_ao_escuro():
    """A PPU depende de o índice 0 ser o mais claro e o 3 o mais escuro."""
    def brilho(rgb):
        return ((rgb >> 16) & 0xFF) + ((rgb >> 8) & 0xFF) + (rgb & 0xFF)

    for chave, (rotulo, tons) in paletas.PALETAS.items():
        s.igual(len(tons), 4, f"a paleta {chave!r} tem quatro tons")
        s.checar(all(brilho(tons[i]) > brilho(tons[i + 1]) for i in range(3)),
                 f"a paleta {chave!r} vai do claro para o escuro",
                 str([hex(t) for t in tons]))
    s.igual({c for c, _ in paletas.OPCOES}, set(paletas.PALETAS),
            "o menu oferece exatamente as paletas que existem")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("teste_"):
            fn()
    sys.exit(0 if s.relatorio() else 1)
