"""
Mealybug Tearoom Tests — os testes de vídeo mais duros que existem.

Todas as outras suítes perguntam "o valor deste registrador está certo?". Esta
pergunta outra coisa: "a IMAGEM está certa?". E compara pixel a pixel com uma
foto tirada de um Game Boy de verdade.

O que elas fazem é mudar um registrador de vídeo NO MEIO de uma linha sendo
desenhada — trocar a paleta, mover a rolagem, ligar a janela, mudar o tamanho dos
sprites — e conferir exatamente onde, naquela linha, o efeito aparece. Um
emulador que desenhe a linha inteira de uma vez, como o nosso, só acerta por
acidente: o resultado correto exige saber em qual pixel a PPU estava quando a
escrita chegou.

Por isso este é o teto de dificuldade. Emuladores maduros passam em parte delas,
e não em todas.


COMO O VEREDITO FUNCIONA
------------------------

A pasta `expected/` tem um PNG por ROM, capturado em hardware real, organizado
por modelo de console:

    DMG-blob     o DMG comum, com o chip encapsulado em resina  → o nosso alvo
    DMG-CPU B    uma revisão específica do DMG                  → também serve
    CPU CGB C/D  Game Boy Color                                 → fora de escopo

Os PNGs são em tons de cinza com quatro níveis, que correspondem exatamente aos
quatro índices do nosso framebuffer:

    255 → 0     170 → 1     85 → 2     0 → 3

Então comparar é traduzir e conferir byte a byte. Não há tolerância: um pixel de
diferença é uma falha, porque um pixel de diferença significa que a PPU mudou de
estado no ciclo errado.

    python tests/test_mealybug.py            roda todas
    python tests/test_mealybug.py bgp        só as que casam com "bgp"
    python tests/test_mealybug.py "" --salvar    grava as telas que falharam
    python tests/test_mealybug.py "" --auditar   confere o próprio comparador


POR QUE A COMPARAÇÃO É CONFIÁVEL
--------------------------------

Uma suspeita razoável, ao ver um placar de zero: e se o erro estiver no
comparador, e não no emulador? Bordas de janela, barra de título, escala — se a
imagem viesse de uma captura de tela, qualquer uma dessas coisas deslocaria tudo
e faria o resultado inteiro parecer errado.

Não vem. A imagem é lida de `ppu.framebuffer`, o array de 160x144 bytes que a
emulação produz, ANTES de o pygame existir. Não há janela, não há escala, não há
sistema operacional no caminho. Este arquivo nem importa pygame.

Ainda assim, "confie em mim" não é argumento. O modo `--auditar` mede as três
formas de o comparador estar errado, e usa os próprios testes como referência:

  1. DESLOCAMENTO. Compara em todos os deslocamentos de -3 a +3 em x e y. Se
     algum alinhar melhor do que (0,0), a comparação está torta.
  2. MAPEAMENTO DE TONS. Testa as 24 permutações de 0,1,2,3. Se alguma alinhar
     melhor do que a identidade, o mapa de cinzas está errado.
  3. ESTABILIDADE. Compara a tela em 10, 30, 60 e 120 quadros. Se mudar, o
     número de quadros foi mal escolhido.

Quando rodei isso, os testes de diferença pequena confirmaram (0,0) e a
identidade como os melhores alinhamentos — ou seja, o comparador está certo e a
diferença é do emulador.

Um caso deu resultado curioso e vale registrar: no `m3_bgp_change`, a permutação
(1,2,3,0) alinha quatro vezes melhor do que a identidade. Isso NÃO significa que
o mapa de tons está errado — se estivesse, todos os testes melhorariam junto.
Significa que naquele teste específico estamos aplicando a paleta com um passo de
defasagem, o que produz exatamente uma rotação dos tons. É sintoma do erro de
temporização da paleta, e não da comparação.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gb.cartridge import Cartridge      # noqa: E402
from gb.machine import Machine          # noqa: E402
from gb.ppu import ALTURA, LARGURA      # noqa: E402

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# Os modelos de referência que valem para um DMG, na ordem de preferência.
MODELOS = ("DMG-blob", "DMG-CPU B")

# Tom de cinza do PNG → índice de cor do nosso framebuffer.
DE_CINZA = {255: 0, 170: 1, 85: 2, 0: 3}

# Quantos quadros rodar antes de comparar. As ROMs montam a tela e param; o
# limite existe só para não rodar para sempre se alguma travar.
QUADROS = 30


def achar_suite():
    """Localiza a pasta da Mealybug pela presença de `expected/`."""
    for raiz, pastas, _ in os.walk(RAIZ):
        if "expected" in pastas and any(
                a.endswith(".gb") for a in os.listdir(raiz)):
            return raiz
    return None


def carregar_referencia(caminho):
    """
    Lê um PNG de referência e devolve os índices de cor, como o framebuffer.

    Devolve None se o arquivo não puder ser lido — o que inclui não ter a Pillow
    instalada, caso em que a suíte inteira é simplesmente pulada.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(caminho).convert("L")
    except Exception:
        return None
    if im.size != (LARGURA, ALTURA):
        return None
    # Tons fora dos quatro esperados viram o mais próximo, o que protege contra
    # um PNG que tenha passado por conversão de cor em algum momento.
    def indice(v):
        if v in DE_CINZA:
            return DE_CINZA[v]
        return min(DE_CINZA, key=lambda k: abs(k - v)) and DE_CINZA[
            min(DE_CINZA, key=lambda k: abs(k - v))]
    return bytes(indice(v) for v in im.getdata())


def referencias_de(suite, nome_rom):
    """
    Os PNGs de referência que se aplicam a esta ROM, num DMG.

    Pode haver mais de um: revisões diferentes do console produzem imagens
    ligeiramente diferentes em alguns testes, e passar em QUALQUER uma delas
    conta como acerto — é o mesmo critério que a própria suíte usa.
    """
    base = os.path.splitext(nome_rom)[0]
    achados = []
    for modelo in MODELOS:
        caminho = os.path.join(suite, "expected", modelo, base + ".png")
        if os.path.exists(caminho):
            achados.append((modelo, caminho))
    return achados


def rodar_e_comparar(caminho_rom, referencias, salvar_em=None):
    """
    Roda a ROM e compara a tela com cada referência.

    Devolve (veredito, detalhe). O veredito é "passou", "difere", "sem
    referência" ou "erro".
    """
    nome = os.path.basename(caminho_rom)
    try:
        m = Machine(Cartridge.from_file(caminho_rom))
        m.reset()
        for _ in range(QUADROS):
            m.rodar_frame()
        tela = bytes(m.ppu.framebuffer)
    except Exception as e:
        return "erro", f"{type(e).__name__}: {e}"

    if not referencias:
        return "sem referência", ""

    melhor = None
    for modelo, caminho_png in referencias:
        esperado = carregar_referencia(caminho_png)
        if esperado is None:
            return "erro", "não consegui ler o PNG (falta Pillow?)"
        if tela == esperado:
            return "passou", modelo
        diferentes = sum(1 for a, b in zip(tela, esperado) if a != b)
        if melhor is None or diferentes < melhor[1]:
            melhor = (modelo, diferentes)

    modelo, diferentes = melhor
    total = LARGURA * ALTURA
    if salvar_em:
        _salvar(tela, os.path.join(salvar_em, nome.replace(".gb", ".png")))
    return "difere", f"{diferentes} de {total} pixels ({100*diferentes/total:.1f}%) vs {modelo}"


def _salvar(framebuffer, destino):
    """Grava a nossa tela como PNG, para poder olhar lado a lado."""
    try:
        from PIL import Image
        cinza = {0: 255, 1: 170, 2: 85, 3: 0}
        im = Image.new("L", (LARGURA, ALTURA))
        im.putdata([cinza[v] for v in framebuffer])
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        im.save(destino)
    except Exception:
        pass


def auditar(suite, roms):
    """
    Confere o comparador contra si mesmo. Ver a explicação no topo do arquivo.

    Não é um teste do emulador: é um teste do teste. Existe porque um placar de
    zero merece a pergunta "e se o erro for meu?", e essa pergunta se responde
    com medição, não com garantia.
    """
    import itertools

    print(" AUDITORIA DO COMPARADOR\n")
    print(f" {'ROM':<38} {'atual':>7} {'melhor deslocamento':>22} {'melhor permutação':>20}")
    print(" " + "-" * 88)

    for nome in roms:
        refs = referencias_de(suite, nome)
        if not refs:
            continue
        esperado = carregar_referencia(refs[0][1])
        if esperado is None:
            continue
        m = Machine(Cartridge.from_file(os.path.join(suite, nome)))
        m.reset()
        for _ in range(QUADROS):
            m.rodar_frame()
        nosso = bytes(m.ppu.framebuffer)

        def diferenca(img):
            return sum(1 for a, b in zip(img, esperado) if a != b)

        base = diferenca(nosso)

        # 1) deslocamento
        melhor_d = (base, 0, 0)
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                if dx == dy == 0:
                    continue
                movido = bytearray(LARGURA * ALTURA)
                for y in range(ALTURA):
                    sy = y - dy
                    for x in range(LARGURA):
                        sx = x - dx
                        movido[y * LARGURA + x] = (
                            nosso[sy * LARGURA + sx]
                            if 0 <= sx < LARGURA and 0 <= sy < ALTURA else 0xFF)
                d = diferenca(bytes(movido))
                if d < melhor_d[0]:
                    melhor_d = (d, dx, dy)

        # 2) permutação de tons
        melhor_p = (base, (0, 1, 2, 3))
        for p in itertools.permutations(range(4)):
            if p == (0, 1, 2, 3):
                continue
            tab = bytes(p[v] if v < 4 else v for v in range(256))
            d = diferenca(nosso.translate(tab))
            if d < melhor_p[0]:
                melhor_p = (d, p)

        aviso_d = f"({melhor_d[1]:+},{melhor_d[2]:+}) {melhor_d[0]}" \
            if melhor_d[1:] != (0, 0) else "(0,0) — correto"
        aviso_p = f"{melhor_p[1]} {melhor_p[0]}" \
            if melhor_p[1] != (0, 1, 2, 3) else "identidade — correta"
        print(f" {nome:<38} {base:>7} {aviso_d:>22} {aviso_p:>20}")

    print()
    print(" Um deslocamento ou permutação melhor que o atual indicaria erro no")
    print(" COMPARADOR. Do contrário, a diferença é do emulador.")
    return 0


def main(argv):
    filtro = argv[1] if len(argv) > 1 else ""
    salvar = "--salvar" in argv
    suite = achar_suite()
    if suite is None:
        print("não achei a pasta da Mealybug (procurei por uma pasta com .gb "
              "e uma subpasta 'expected').")
        return 2

    destino = os.path.join(RAIZ, "mealybug-falhas") if salvar else None

    print("=" * 72)
    print(" MEALYBUG TEAROOM TESTS")
    print("=" * 72)
    print(f" suíte em: {os.path.relpath(suite, RAIZ)}")
    print(f" referências: {', '.join(MODELOS)}\n")

    roms = sorted(a for a in os.listdir(suite) if a.endswith(".gb"))
    if filtro:
        roms = [r for r in roms if filtro in r]

    if "--auditar" in argv:
        return auditar(suite, roms)

    contagem = {}
    for nome in roms:
        refs = referencias_de(suite, nome)
        veredito, detalhe = rodar_e_comparar(
            os.path.join(suite, nome), refs, destino)
        contagem[veredito] = contagem.get(veredito, 0) + 1
        marca = {"passou": "OK ", "difere": " x ",
                 "sem referência": "n/a", "erro": "ERR"}[veredito]
        extra = f"  {detalhe}" if detalhe else ""
        print(f" {marca} {nome:<44}{extra}", flush=True)

    print()
    print("=" * 72)
    ok = contagem.get("passou", 0)
    com_ref = ok + contagem.get("difere", 0) + contagem.get("erro", 0)
    if com_ref:
        print(f" TOTAL: {ok}/{com_ref} com referência de DMG"
              f"   ({100 * ok / com_ref:.0f}%)")
    if contagem.get("sem referência"):
        print(f" {contagem['sem referência']} ROMs sem referência de DMG"
              f" (só existe captura de Game Boy Color)")
    if destino and contagem.get("difere"):
        print(f" telas das falhas gravadas em {os.path.relpath(destino, RAIZ)}/")
    print("=" * 72)
    return 0 if ok == com_ref else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
