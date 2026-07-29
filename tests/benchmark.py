"""
Mede a velocidade do emulador, sem janela e sem limitador de quadros.

    python tests/benchmark.py                    ROM sintética, 3 segundos
    python tests/benchmark.py jogo.gb            com um jogo de verdade
    python tests/benchmark.py jogo.gb --som      incluindo a mixagem de áudio
    python tests/benchmark.py jogo.gb --perfil   onde o tempo está indo
    python tests/benchmark.py jogo.gb --regs     compara as duas visões de
                                                 registrador de 16 bits

SEM JANELA E SEM LIMITADOR, e isso não é detalhe. Olhar os quadros por segundo
na barra de título não mede o emulador: mede o limitador, que segura tudo em 59,7
de propósito. Um emulador capaz de 300% e um capaz de 60% aparecem exatamente
iguais ali — até o segundo engasgar.

O número que importa é o "x tempo real". 1,00x significa acompanhar um Game Boy
de verdade, e é exatamente o ponto em que o jogo roda na velocidade certa. Abaixo
disso é câmera lenta ou quadros pulados; acima é a folga que absorve os picos.

Rodar o mesmo comando sob CPython e sob PyPy é o que revela a diferença entre os
dois interpretadores — e foi assim que a otimização do banco de registradores foi
descoberta, com o `--regs` mostrando 170 contra 1055 quadros por segundo.

O `--perfil` responde a outra pergunta: não "quão rápido", mas "onde o tempo
está sendo gasto". As duas medições servem a decisões diferentes, e confundi-las
leva a otimizar o lugar errado.
"""

import os
import platform
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gb.cartridge import Cartridge          # noqa: E402
from gb.machine import Machine              # noqa: E402
from gb.registradores import criar_reg16    # noqa: E402

CICLOS_POR_SEGUNDO = 4194304


def rom_sintetica():
    """
    ROM mínima que exercita o caminho quente: um laço de ALU + memória.

    Serve para comparar runtimes sem depender de ter um jogo à mão, e é
    determinística — o mesmo trabalho toda vez.
    """
    rom = bytearray(0x8000)
    rom[0x147] = 0x00
    prog = [
        0x3E, 0x00,        # LD A, 0
        0x21, 0x00, 0xC0,  # LD HL, 0xC000
        0x01, 0x34, 0x12,  # LD BC, 0x1234
        # laço:
        0x3C,              # INC A
        0x77,              # LD (HL), A
        0x7E,              # LD A, (HL)
        0x09,              # ADD HL, BC
        0xB8,              # CP B
        0xCB, 0x27,        # SLA A
        0x0B,              # DEC BC
        0x21, 0x00, 0xC0,  # LD HL, 0xC000
        0xC3, 0x08, 0x01,  # JP laço
    ]
    rom[0x100:0x100 + len(prog)] = bytes(prog)
    return rom


ORCAMENTO_MS = 1000.0 / 59.7      # tempo disponível por quadro a 60 Hz


def medir(m, segundos, rotulo, detalhar=False):
    """
    Mede velocidade e, opcionalmente, a DISTRIBUIÇÃO do tempo por quadro.

    A média sozinha engana: um emulador com média de 60 fps pode estar
    alternando entre 90 e 40 e parecer horrível. O que decide se a imagem sai
    lisa é o pior caso — se o quadro no percentil 99 cabe no orçamento de
    16,7 ms, não há drop visível.
    """
    tempos = []
    t0 = time.perf_counter()
    c0 = m.cycles
    while time.perf_counter() - t0 < segundos:
        t = time.perf_counter()
        m.rodar_frame()
        tempos.append((time.perf_counter() - t) * 1000.0)
    dt = time.perf_counter() - t0
    ciclos = m.cycles - c0

    fps = len(tempos) / dt
    vezes = ciclos / dt / CICLOS_POR_SEGUNDO
    print(f"  {rotulo:<22} {fps:7.1f} fps   {vezes:5.2f}x tempo real   "
          f"{ciclos / dt / 1e6:5.2f} MHz")

    if detalhar and tempos:
        tempos.sort()
        n = len(tempos)
        def p(q):
            return tempos[min(n - 1, int(n * q))]
        estourados = sum(1 for x in tempos if x > ORCAMENTO_MS)
        print(f"      tempo por quadro (orçamento {ORCAMENTO_MS:.1f} ms):")
        print(f"        mediana {p(0.50):6.2f} ms   p95 {p(0.95):6.2f} ms   "
              f"p99 {p(0.99):6.2f} ms   pior {tempos[-1]:6.2f} ms")
        print(f"        quadros acima do orçamento: {estourados}/{n} "
              f"({100 * estourados / n:.1f}%)")
    return vezes


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {a for a in sys.argv[1:] if a.startswith("--")}
    segundos = 3.0

    print(f"{platform.python_implementation()} {platform.python_version()} "
          f"em {platform.machine()}")
    print()

    if args:
        cart = Cartridge.from_file(args[0])
        nome = cart.title or os.path.basename(args[0])
    else:
        cart = Cartridge(bytes(rom_sintetica()))
        nome = "ROM sintética"

    if "--regs" in opts:
        print(f"ROM: {nome}")
        print("  comparando as duas visões de registrador de 16 bits")
        print("  (no CPython o memoryview ganha; no PyPy espera-se o contrário)")
        for modo in ("memoryview", "pares"):
            m = Machine(cart)
            m.cpu.reg16 = criar_reg16(m.cpu.reg_buffer, forcar=modo)
            m.reset()
            m.apu.audio_ativo = False
            for _ in range(60):
                m.rodar_frame()
            medir(m, segundos, modo)
        return 0

    m = Machine(cart)
    m.reset()
    for _ in range(60):                      # aquece (o jogo sai da tela inicial)
        m.rodar_frame()

    if "--perfil" in opts:
        import cProfile
        import pstats
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(30):
            m.rodar_frame()
        pr.disable()
        pstats.Stats(pr).sort_stats("tottime").print_stats(15)
        return 0

    print(f"ROM: {nome}")
    m.apu.audio_ativo = False
    sem_som = medir(m, segundos, "sem áudio", detalhar=True)

    if "--som" in opts:
        m.apu.audio_ativo = True
        com_som = medir(m, segundos, "com áudio", detalhar=True)
        m.apu.consumir_audio()
        if com_som:
            print(f"\n  o áudio custa {(sem_som / com_som - 1) * 100:.0f}% "
                  f"do tempo de execução")

    print()
    print("  referência: 1,00x = 60 fps = velocidade de um Game Boy real")
    print("  o que decide se a imagem sai LISA é o p99, não a média")
    return 0


if __name__ == "__main__":
    sys.exit(main())
