"""
Roda a suíte inteira: os testes unitários primeiro, as ROMs de teste depois.

    python tests/executar_todos.py            tudo
    python tests/executar_todos.py --rapido   só os unitários, em segundos

A ORDEM importa, e não é alfabética. Os unitários vêm antes por serem rápidos e
específicos: se a decodificação de instruções está quebrada, é melhor descobrir
isso em dez segundos do que depois de quinze minutos rodando ROMs que iam falhar
todas pelo mesmo motivo.

Dentro dos unitários vale a mesma lógica, das camadas mais baixas para as mais
altas. Duração das instruções, depois comportamento, depois busca e barramento,
depois os periféricos. Um erro embaixo derruba tudo acima, então a primeira
falha do relatório costuma ser a causa das outras.

As ROMs levam vários minutos em Python puro, e o executor guarda o resultado de
cada uma — dá para interromper com Ctrl+C e retomar de onde parou.
"""

import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))

UNITARIOS = [
    ("Instruções — duração em ciclos", "test_timing.py"),
    ("Instruções — comportamento",     "test_registers.py"),
    ("Busca e decodificação",          "test_fetch.py"),
    ("Barramento e mapa de memória",   "test_bus.py"),
    ("Passo de execução",              "test_step.py"),
    ("Interrupções",                   "test_interrupts.py"),
    ("Timer",                          "test_timer.py"),
    ("PPU",                            "test_ppu.py"),
    ("OAM DMA",                        "test_dma.py"),
    ("MBCs",                           "test_mbc.py"),
    ("APU",                            "test_apu.py"),
    ("Serial e Joypad",                "test_serial.py"),
    ("Ritmo do frontend",              "test_ritmo.py"),
    ("Interface",                      "test_ui.py"),
    ("Frontend com janela",            "test_frontend.py"),
]


def rodar(script):
    caminho = os.path.join(AQUI, script)
    if not os.path.exists(caminho):
        return None, f"(arquivo {script} não encontrado)"
    p = subprocess.run([sys.executable, caminho], capture_output=True, text=True)
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def main():
    rapido = "--rapido" in sys.argv
    print("=" * 66)
    print(" TESTES UNITÁRIOS")
    print("=" * 66)

    falhas = []
    for titulo, script in UNITARIOS:
        ok, saida = rodar(script)
        if ok is None:
            print(f"  ??  {titulo:<34} {saida}")
            continue
        marca = "OK" if ok else "!!"
        resumo = saida.splitlines()[-1] if saida else ""
        print(f"  {marca}  {titulo:<34} {resumo}")
        if not ok:
            falhas.append((titulo, saida))

    for titulo, saida in falhas:
        print(f"\n--- detalhes de '{titulo}' ---\n{saida}")

    if rapido:
        return 1 if falhas else 0

    print("\n" + "=" * 66)
    print(" ROMs DE TESTE DA BLARGG")
    print("=" * 66)
    p = subprocess.run([sys.executable, os.path.join(AQUI, "test_blargg.py")])
    return 1 if (falhas or p.returncode) else 0


if __name__ == "__main__":
    sys.exit(main())
