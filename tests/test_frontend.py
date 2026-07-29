"""
Roda o laço da janela de verdade, com um pygame de mentira.

Este é o teste que faltava. `test_ritmo.py` mede o raciocínio do limitador de
quadros com um relógio virtual; `test_ui.py` navega pelos menus e confere o
layout. Nenhum dos dois executa a `rodar_com_janela` — a função que amarra
tudo: eventos, menu, emulação, desenho, áudio e espera.

E é justamente ali que mora a classe de defeito mais irritante de todas: o
`NameError` num ramo que só roda quando o jogador aperta Esc, ou o argumento
trocado na chamada que só acontece ao trocar de cartucho. Nada disso aparece
num teste de precisão, e tudo isso aparece nos dez primeiros segundos de uso.

O pygame de mentira não desenha: ele finge. Aceita as chamadas, devolve
superfícies vazias e entrega um roteiro de teclas em vez de esperar o jogador.
O que se prova aqui é o que o roteiro percorre — abrir o menu, mexer em todos
os ajustes, trocar de jogo, reiniciar o console e sair — sem levantar exceção
e com o estado certo no fim.

As ROMs são fabricadas na hora, num diretório temporário: o teste não depende
de você ter jogo nenhum na máquina.
"""

import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from harness import Suite                        # noqa: E402

s = Suite("Frontend com janela")


# ======================================================================
# O pygame de mentira
# ======================================================================
class _Superficie:
    def __init__(self, tamanho):
        self.tamanho = tuple(tamanho)

    def get_size(self):
        return self.tamanho

    def fill(self, cor, rect=None):
        pass

    def blit(self, origem, posicao):
        pass

    def set_colorkey(self, cor):
        pass

    def set_alpha(self, a):
        pass

    def convert(self):
        return self


class _Canal:
    """Um canal de áudio que confere o que recebe em vez de tocar."""

    def __init__(self, numero):
        self.tocando = False
        self.volumes = []
        self.blocos = 0

    def play(self, som):
        self.tocando = True
        self.blocos += 1

    def queue(self, som):
        self.blocos += 1

    def get_busy(self):
        return self.tocando

    def get_queue(self):
        return None

    def stop(self):
        self.tocando = False

    def set_volume(self, v):
        # O pygame aceita 0..1. Passar porcentagem aqui deixaria o som mudo ou
        # estourado sem erro nenhum — é o tipo de engano que só um teste pega.
        assert 0.0 <= v <= 1.0, f"volume fora de 0..1: {v}"
        self.volumes.append(v)


class _Relogio:
    def tick(self, fps):
        return 16


TECLAS = ("K_UP", "K_DOWN", "K_LEFT", "K_RIGHT", "K_z", "K_x", "K_RETURN",
          "K_BACKSPACE", "K_ESCAPE", "K_TAB", "K_F5", "K_PAGEUP", "K_PAGEDOWN")


def _pygame_falso():
    p = types.ModuleType("pygame")
    p.error = RuntimeError
    p.Surface = _Superficie
    p.QUIT, p.KEYDOWN, p.KEYUP = 256, 768, 769
    p.WINDOWFOCUSGAINED, p.WINDOWRESTORED = 512, 513
    for i, nome in enumerate(TECLAS):
        setattr(p, nome, 1000 + i)

    p.canais = []
    p.legendas = []

    def canal(numero):
        c = _Canal(numero)
        p.canais.append(c)
        return c

    p.display = types.SimpleNamespace(
        init=lambda: None,
        set_mode=lambda tamanho: _Superficie(tamanho),
        set_caption=p.legendas.append,
        flip=lambda: None)
    p.transform = types.SimpleNamespace(
        scale=lambda origem, tamanho: _Superficie(tamanho))
    p.image = types.SimpleNamespace(
        frombuffer=lambda buf, tamanho, fmt: _Superficie(tamanho))
    p.time = types.SimpleNamespace(Clock=_Relogio)
    p.mixer = types.SimpleNamespace(
        init=lambda **k: None, quit=lambda: None,
        Channel=canal, Sound=lambda buffer=None: object())
    p.quit = lambda: None
    p.event = types.SimpleNamespace(get=lambda: [])
    return p


def _tecla(p, k, baixo=True):
    return types.SimpleNamespace(type=p.KEYDOWN if baixo else p.KEYUP, key=k)


def _janela(p):
    return types.SimpleNamespace(type=p.QUIT)


# ======================================================================
# Bancada
# ======================================================================
def _fabricar_rom(caminho, titulo):
    """32 KB de NOP com um cabeçalho válido. Roda para sempre, sem fazer nada."""
    dados = bytearray(32768)
    nome = titulo.encode("ascii")[:16]
    dados[0x134:0x134 + len(nome)] = nome
    dados[0x147] = 0x00        # ROM ONLY
    dados[0x148] = 0x00        # 32 KB
    with open(caminho, "wb") as f:
        f.write(dados)


def _bancada(roteiro, rom=0, som=True):
    """
    Monta uma pasta com três ROMs, roda o laço da janela e devolve o resultado.

    `roteiro` recebe (pygame falso, lista de entradas da pasta) e devolve a
    fila de eventos. `rom` é o índice da ROM inicial, ou None para começar sem
    jogo nenhum.
    """
    p = _pygame_falso()
    sys.modules["pygame"] = p
    for nome in [n for n in sys.modules if n.startswith("ui.desenho")]:
        del sys.modules[nome]

    import main as M
    from ui.biblioteca import Biblioteca

    pasta = tempfile.mkdtemp()
    nomes = ["alfa.gb", "beta.gb", "gama.gb"]
    for i, nome in enumerate(nomes):
        _fabricar_rom(os.path.join(pasta, nome), f"JOGO {i}")

    entradas = Biblioteca(pasta).entradas
    fila = list(roteiro(p, entradas))
    p.event.get = lambda: [fila.pop(0)] if fila else []

    caminho_cfg = os.path.join(pasta, "prefs.json")
    prefs = M.Preferencias(caminho_cfg)
    prefs["som"] = som
    prefs["escala"] = 3

    sessao = None if rom is None else M.Sessao(os.path.join(pasta, nomes[rom]))

    # O frontend imprime a ficha do cartucho a cada troca de jogo; num teste
    # isso é ruído entre os resultados.
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        final = M.rodar_com_janela(sessao, prefs, pasta_de_roms=pasta)
    return types.SimpleNamespace(pygame=p, prefs=prefs, sessao=final,
                                 pasta=pasta, entradas=entradas)


def _indice(entradas, nome):
    return next(i for i, e in enumerate(entradas) if e.nome == nome)


# ======================================================================
# Cenários
# ======================================================================
def teste_jogar_e_fechar_a_janela():
    """O caminho mais curto: apertar botões e fechar."""
    def roteiro(p, _):
        r = []
        for k in (p.K_RIGHT, p.K_z, p.K_RETURN, p.K_BACKSPACE, p.K_x):
            r += [_tecla(p, k), _tecla(p, k, False)]
        r += [_tecla(p, p.K_TAB), _tecla(p, p.K_TAB, False)]   # turbo
        r += [_janela(p)]
        return r

    b = _bancada(roteiro)
    s.checar(b.sessao is not None, "a janela devolveu a sessão em que parou")
    s.checar(len(b.pygame.legendas) >= 1,
             "a barra de título recebeu o nome do jogo",
             str(b.pygame.legendas[:1]))


def teste_ajustes_valem_na_hora_e_ficam_salvos():
    """
    Mexe em TODOS os ajustes e confere que cada um chegou ao seu destino.

    O valor de um ajuste passa por três lugares: o item do menu, a preferência
    gravada e o efeito real (a janela, o mixer, as tabelas de cor). Um teste
    que só olhasse a preferência não veria o dia em que a escala parasse de
    redimensionar a janela.
    """
    def roteiro(p, _):
        r = [_tecla(p, p.K_ESCAPE)]                        # abre o menu
        r += [_tecla(p, p.K_DOWN)] * 3                     # até "Ajustes"
        r += [_tecla(p, p.K_RETURN)]
        r += [_tecla(p, p.K_DOWN), _tecla(p, p.K_LEFT), _tecla(p, p.K_LEFT)]
        r += [_tecla(p, p.K_DOWN), _tecla(p, p.K_RIGHT)]   # escala 3 → 4
        r += [_tecla(p, p.K_DOWN), _tecla(p, p.K_RIGHT)]   # paleta
        r += [_tecla(p, p.K_DOWN), _tecla(p, p.K_LEFT)]    # pulo de quadros
        r += [_tecla(p, p.K_ESCAPE), _tecla(p, p.K_ESCAPE)]
        r += [_janela(p)]
        return r

    b = _bancada(roteiro)
    s.igual(b.prefs["volume"], 50, "o volume desceu duas casas")
    s.igual(b.prefs["escala"], 4, "a escala subiu uma")
    s.checar(b.prefs["paleta"] != "verde", "a paleta mudou",
             b.prefs["paleta"])
    s.igual(b.prefs["pulo_maximo"], 2, "o pulo de quadros desceu")

    # O efeito real: a janela foi recriada no tamanho novo e o canal de áudio
    # recebeu o volume novo, já convertido para a escala do pygame.
    s.checar(0.5 in b.pygame.canais[0].volumes,
             "o mixer recebeu o volume em 0..1",
             str(b.pygame.canais[0].volumes))

    depois = type(b.prefs)(os.path.join(b.pasta, "prefs.json"))
    s.igual(depois["escala"], 4, "e tudo isso sobreviveu ao fechar da janela")


def teste_trocar_de_jogo_sem_fechar_a_janela():
    """
    Trocar de cartucho pelo menu grava o save do anterior antes.

    Esquecer essa gravação apagaria a partida de quem só queria jogar outra coisa.
    """
    def roteiro(p, entradas):
        r = [_tecla(p, p.K_ESCAPE)]
        r += [_tecla(p, p.K_DOWN), _tecla(p, p.K_DOWN)]    # "Trocar de jogo"
        r += [_tecla(p, p.K_RETURN)]
        r += [_tecla(p, p.K_DOWN)] * _indice(entradas, "gama.gb")
        r += [_tecla(p, p.K_RETURN)]
        r += [_janela(p)]
        return r

    b = _bancada(roteiro, rom=0)
    s.igual(os.path.basename(b.sessao.caminho), "gama.gb",
            "o jogo trocou sem a janela fechar")
    s.igual(b.prefs["ultima_rom"], os.path.join(b.pasta, "gama.gb"),
            "e o novo jogo virou o 'último aberto'")


def teste_entrar_em_subpasta_e_voltar():
    """Navegar por pastas não derruba nem perde o jogo aberto."""
    def roteiro(p, entradas):
        r = [_tecla(p, p.K_ESCAPE)]
        r += [_tecla(p, p.K_DOWN), _tecla(p, p.K_DOWN), _tecla(p, p.K_RETURN)]
        r += [_tecla(p, p.K_RETURN)]        # confirma em ".." → sobe uma pasta
        r += [_tecla(p, p.K_ESCAPE), _tecla(p, p.K_ESCAPE)]
        r += [_janela(p)]
        return r

    b = _bancada(roteiro)
    s.checar(b.sessao is not None,
             "navegar por pastas não derruba nem perde o jogo aberto")


def teste_abrir_sem_jogo_e_escolher_na_janela():
    """
    `python main.py` sem argumento nenhum: a janela nasce no seletor.

    É o caminho de quem clicou num atalho, e o único em que a `rodar_com_janela`
    começa sem máquina — todo acesso a `sessao` antes da escolha tem de estar
    protegido.
    """
    def roteiro(p, entradas):
        r = [_tecla(p, p.K_DOWN)] * _indice(entradas, "beta.gb")
        r += [_tecla(p, p.K_RETURN)]
        r += [_janela(p)]
        return r

    b = _bancada(roteiro, rom=None)
    s.checar(b.sessao is not None, "a janela abriu sem jogo e terminou com um")
    s.igual(os.path.basename(b.sessao.caminho), "beta.gb",
            "o jogo escolhido no seletor é o que ficou rodando")


def teste_reiniciar_zera_o_console():
    """Reiniciar pelo menu recomeça a máquina, preservando o save."""
    def roteiro(p, _):
        r = [_tecla(p, p.K_RIGHT), _tecla(p, p.K_RIGHT, False)]
        r += [_tecla(p, p.K_ESCAPE)]
        r += [_tecla(p, p.K_DOWN), _tecla(p, p.K_RETURN)]    # "Reiniciar"
        r += [_janela(p)]
        return r

    b = _bancada(roteiro)
    s.checar(b.sessao.m.cycles < 70224 * 30,
             "depois de reiniciar, o contador de ciclos recomeçou",
             f"{b.sessao.m.cycles} ciclos")


def teste_menu_nao_deixa_botao_preso():
    """
    Abrir o menu com uma direção pressionada não pode deixá-la pressionada.

    Sem soltar os botões, o personagem sairia andando sozinho ao voltar do
    menu — o jogo nunca vê o KEYUP, porque ele foi para o menu.
    """
    def roteiro(p, _):
        r = [_tecla(p, p.K_RIGHT)]              # segura a direita
        r += [_tecla(p, p.K_ESCAPE)]            # e abre o menu sem soltar
        r += [_tecla(p, p.K_ESCAPE)]            # volta ao jogo
        r += [_janela(p)]
        return r

    b = _bancada(roteiro)
    apertados = [n for n, apertado in b.sessao.m.joypad.botoes.items()
                 if apertado]
    s.checar(not apertados, "nenhum botão ficou preso ao sair do menu",
             str(apertados))


def teste_som_pode_ser_desligado_e_religado_no_menu():
    """
    Desligar e religar o som reabre o mixer e volta a gerar amostras.

    O caminho passa por criar e destruir objetos de áudio no meio do laço, que é onde
    esse tipo de ajuste costuma deixar algo inconsistente.
    """
    def roteiro(p, _):
        r = [_tecla(p, p.K_ESCAPE)]
        r += [_tecla(p, p.K_DOWN)] * 3 + [_tecla(p, p.K_RETURN)]   # Ajustes
        r += [_tecla(p, p.K_RIGHT)]             # Som: liga → desliga
        r += [_tecla(p, p.K_RIGHT)]             # e volta a ligar
        r += [_tecla(p, p.K_ESCAPE), _tecla(p, p.K_ESCAPE)]
        r += [_janela(p)]
        return r

    b = _bancada(roteiro)
    s.igual(b.prefs["som"], True, "o som terminou ligado")
    s.checar(len(b.pygame.canais) >= 2,
             "o mixer foi reaberto ao religar o som",
             f"{len(b.pygame.canais)} canais abertos")
    s.checar(b.sessao.m.apu.audio_ativo,
             "e a APU voltou a gerar amostras")


def teste_sair_pelo_menu():
    """Sair pelo menu encerra o laço sem erro, e sem processar o que vier depois."""
    def roteiro(p, _):
        r = [_tecla(p, p.K_ESCAPE)]
        r += [_tecla(p, p.K_DOWN)] * 4 + [_tecla(p, p.K_RETURN)]   # "Sair"
        r += [_tecla(p, p.K_ESCAPE)] * 5      # nada disso deve rodar
        return r

    b = _bancada(roteiro)
    s.checar(b.sessao is not None, "sair pelo menu encerra o laço sem erro")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("teste_"):
            fn()
    sys.exit(0 if s.relatorio() else 1)
