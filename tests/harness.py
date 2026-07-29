"""
A bancada de testes: um mini framework e o executor de ROMs de teste.

POR QUE NÃO PYTEST
------------------

É a primeira pergunta que quem já viu uma disciplina de testes faz, e a resposta
não é teimosia.

O pytest é excelente e teria poupado as trinta linhas da classe `Suite` lá
embaixo. O que ele custaria é a única dependência externa do projeto inteiro —
`gb/` roda com Python e mais nada, e essa propriedade é o que permite copiar a
pasta para qualquer máquina e ver funcionando, sem instalar nem configurar.

Trinta linhas parecem barato demais para abrir mão disso. E há um segundo ganho
que só aparece rodando: cada arquivo de teste é um programa comum, executável
sozinho com `python tests/test_timer.py`. Sem descoberta automática, sem plugins,
sem configuração — o que falhou aparece na tela e o arquivo diz por quê.

Num projeto de verdade, com equipe e integração contínua, a conta provavelmente
se inverte. Aqui não.


COMO SE SABE SE UMA ROM DE TESTE PASSOU
---------------------------------------

As ROMs da Blargg e da Mooneye são programas de Game Boy escritos para exercitar
comportamentos específicos do hardware. Rodá-las é o teste mais duro que existe
para um emulador: elas foram calibradas contra o console real.

O problema é ler o resultado. Um Game Boy não tem terminal, arquivo nem rede — e
essas ROMs relatam de três formas diferentes, conforme a época e o autor:

  1. PELA PORTA SERIAL. Escrevem o texto letra por letra na saída do cabo link.
     Sem cabo nenhum a transferência acontece assim mesmo (ver `gb/serial.py`), e
     o emulador só precisa guardar os bytes. É o método mais confiável.

  2. PELA RAM DO CARTUCHO. Gravam a assinatura DE B0 61 em A001-A003 e o código
     de saída em A000. Serve para as ROMs que não usam a serial.

  3. PELA TELA. Algumas só escrevem o resultado na imagem, e nada mais.

O terceiro caso parece exigir reconhecimento de imagem, e não exige — a solução
está em `texto_da_tela`, e é uma das coisas mais elegantes que este projeto tem.

O executor observa as três fontes e para assim que qualquer uma dá veredito.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gb.cartridge import Cartridge      # noqa: E402
from gb.machine import Machine          # noqa: E402

RAIZ = os.path.dirname(__file__)
ROMS = os.path.join(RAIZ, "roms")

# Os três bytes que a Blargg grava para dizer "o que está em A000 é meu".
# Sem essa assinatura, qualquer lixo na RAM poderia ser lido como resultado.
ASSINATURA = (0xDE, 0xB0, 0x61)


class Resultado:
    """
    O que aconteceu com uma ROM de teste.

    `aplicavel` é a distinção que evita um relatório enganoso: uma ROM que exige
    Game Boy Color não FALHOU neste emulador — ela está fora do escopo dele.
    Misturar as duas coisas faria a contagem parecer pior do que é, e esconderia
    as falhas de verdade no meio do ruído.
    """

    def __init__(self, nome, passou, texto, motivo="", ciclos=0, segundos=0.0,
                 aplicavel=True):
        self.nome = nome
        self.passou = passou
        self.texto = " ".join(texto.split())
        self.motivo = motivo
        self.ciclos = ciclos
        self.segundos = segundos
        self.aplicavel = aplicavel

    def __str__(self):
        marca = "n/a" if not self.aplicavel else ("PASSOU" if self.passou else "FALHOU")
        extra = self.motivo or self.texto
        return f"{marca:>6}  {self.nome:<32} {extra}"


def texto_da_tela(m):
    """
    Lê o resultado direto do mapa de tiles — sem olhar um único pixel.

    Esta função resolve o terceiro caso descrito no topo do arquivo, e o truque
    merece ser entendido porque é bonito.

    A tela do Game Boy é montada a partir de um MAPA: uma grade de 32x32 bytes,
    onde cada byte é o número do desenho que vai naquela posição. Ver `gb/ppu.py`.

    Acontece que a biblioteca que a Blargg usa para escrever texto carrega a
    fonte na memória de vídeo de um jeito específico: o desenho da letra "A" fica
    guardado na posição 65, o "B" na 66, e assim por diante — exatamente os
    códigos ASCII.

    A consequência é que o mapa de tiles JÁ É o texto. Ler a tela vira ler 20
    bytes por linha e converter cada um em caractere. Nada de reconhecer imagem,
    nada de comparar com uma tela de referência: uma função de dez linhas.
    """
    base = 0x1C00 if (m.ppu.lcdc & 0x08) else 0x1800
    vram = m.ppu.vram
    linhas = []
    for r in range(18):
        fila = vram[base + r * 32: base + r * 32 + 20]
        linhas.append("".join(chr(c) if 32 <= c < 127 else " " for c in fila).rstrip())
    return "\n".join(linhas).strip()


def _codigo_na_memoria(m):
    """
    Lê o código de saída gravado na RAM do cartucho, se a assinatura conferir.

    Devolve None quando não há resultado válido ali — o que inclui o caso comum
    de a ROM ainda não ter escrito nada.
    """
    ram = m.cart.ram
    if len(ram) < 4:
        return None
    if (ram[1], ram[2], ram[3]) != ASSINATURA:
        return None
    return ram[0]


def rodar_rom(path, max_segundos_emulados=120, timeout_real=1200):
    """
    Roda uma ROM de teste até ela concluir, ou até um dos dois limites estourar.

    São dois limites porque há duas formas de travar, e elas pedem respostas
    diferentes. O limite de CICLOS EMULADOS pega a ROM que entrou num laço
    infinito — dois minutos de tempo de console é muito mais do que qualquer
    teste precisa. O limite de tempo REAL pega o caso em que o emulador está
    lento demais para chegar ao fim antes de a paciência acabar.

    Sem o segundo, uma execução em CPython poderia levar horas sem que ninguém
    soubesse se estava progredindo ou travada.
    """
    nome = os.path.basename(path)
    cart = Cartridge.from_file(path)

    if cart.so_cgb:
        # O byte 0xC0 em 0x143 marca a ROM como exclusiva de Game Boy Color, e
        # essas ROMs conferem um checksum escolhido na montagem — não há detecção
        # de hardware em execução. Rodá-la aqui produziria uma falha enganosa,
        # que diria mais sobre o escopo do emulador do que sobre a corretude dele.
        return Resultado(nome, False, "", "exige Game Boy Color",
                         aplicavel=False)

    m = Machine(cart)
    m.reset()

    limite_ciclos = 4194304 * max_segundos_emulados
    t0 = time.time()

    def veredito():
        """
        Consulta as três fontes. Devolve True, False, ou None para "ainda rodando".

        A serial tem prioridade sobre a tela quando as duas têm conteúdo, porque
        é a mais confiável — a tela pode estar no meio de uma atualização.
        """
        serial = bytes(m.serial.saida).decode("ascii", "replace")
        tela = texto_da_tela(m)
        texto = serial if serial.strip() else tela

        for fonte in (serial, tela):
            if "Passed" in fonte:
                return True, texto
            if "Failed" in fonte or "Error" in fonte:
                return False, texto

        codigo = _codigo_na_memoria(m)
        if codigo is not None and codigo != 0x80:      # 0x80 = ainda rodando
            return codigo == 0, texto + (f"  [codigo={codigo}]" if codigo else "")

        return None, texto

    try:
        while m.cycles < limite_ciclos:
            # Trinta mil instruções entre uma consulta e outra. Conferir o
            # veredito a cada instrução funcionaria e seria absurdamente lento —
            # `texto_da_tela` percorre 360 bytes da memória de vídeo toda vez.
            for _ in range(30000):
                m.cpu.step()

            passou, texto = veredito()
            if passou is not None:
                return Resultado(nome, passou, texto, ciclos=m.cycles,
                                 segundos=time.time() - t0)

            if time.time() - t0 > timeout_real:
                return Resultado(nome, False, texto, "estourou o tempo real",
                                 ciclos=m.cycles, segundos=time.time() - t0)

    except Exception as e:
        # Uma exceção aqui costuma significar que o PC se perdeu e a CPU está
        # executando dados como se fossem código. O endereço vai junto na
        # mensagem porque é a primeira coisa que se quer saber.
        _, texto = veredito()
        return Resultado(nome, False, texto,
                         f"{type(e).__name__}: {e} (PC={m.cpu.reg16[5]:04X})",
                         ciclos=m.cycles, segundos=time.time() - t0)

    _, texto = veredito()
    return Resultado(nome, False, texto, "estourou o limite de ciclos",
                     ciclos=m.cycles, segundos=time.time() - t0)


def maquina_de_teste(rom=None):
    """
    Um console pronto para uso, com uma ROM sintética de 32 KB cheia de zeros.

    A maioria dos testes unitários não precisa de jogo nenhum: eles escrevem
    instruções direto na memória e conferem o efeito. Uma ROM vazia com o
    cabeçalho mínimo preenchido é tudo que a `Machine` exige para se construir.
    """
    if rom is None:
        rom = bytearray(0x8000)
        rom[0x147] = 0x00      # sem MBC
        rom[0x148] = 0x00      # 32 KB
        rom[0x149] = 0x00      # sem RAM
    m = Machine(Cartridge(bytes(rom)))
    m.reset()
    return m


# ----------------------------------------------------------------------
# O mini framework
# ----------------------------------------------------------------------
class Suite:
    """
    Um punhado de asserções com nome, e um relatório no fim.

    A diferença para um `assert` comum é que uma falha NÃO interrompe a
    execução: ela é anotada e o teste continua. Isso importa porque um erro no
    emulador costuma quebrar várias coisas ao mesmo tempo, e ver as dezessete
    falhas de uma vez diz muito mais sobre a causa do que ver a primeira e ter de
    rodar de novo dezessete vezes.

    Toda asserção leva uma DESCRIÇÃO em texto corrido, e isso é proposital. Um
    relatório de falha que diz "esperado 4, obtido 5" manda o leitor abrir o
    arquivo e reconstruir o contexto; um que diz "o TIMA sobe uma vez a cada 16
    T-cycles com TAC=01" já explica o que está errado.
    """

    def __init__(self, titulo):
        self.titulo = titulo
        self.ok = 0
        self.falhas = []

    def checar(self, condicao, descricao, detalhe=""):
        """Anota uma asserção. `detalhe` só aparece quando ela falha."""
        if condicao:
            self.ok += 1
        else:
            self.falhas.append((descricao, detalhe))

    def igual(self, obtido, esperado, descricao):
        """Compara dois valores, montando o detalhe sozinha."""
        self.checar(obtido == esperado, descricao,
                    f"esperado {esperado!r}, obtido {obtido!r}")

    def relatorio(self):
        """Imprime o resumo e devolve True se tudo passou."""
        total = self.ok + len(self.falhas)
        print(f"\n{self.titulo}: {self.ok}/{total}")
        for descricao, detalhe in self.falhas:
            print(f"   x {descricao}" + (f"  —  {detalhe}" if detalhe else ""))
        return not self.falhas
