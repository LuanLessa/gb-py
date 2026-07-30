"""
Descobre o byte baixo do contador do DIV que a ROM de boot deixa.

A Pan Docs documenta que, no instante em que o jogo começa, o registrador DIV
vale 0xAB num DMG. Mas o DIV é só o byte ALTO de um contador de 16 bits, e os 8
bits de baixo não estão documentados em lugar nenhum — porque nenhum programa
consegue lê-los diretamente.

Eles importam mesmo assim. O teste `boot_div` da Mooneye lê o DIV algumas
instruções depois do início, e nesse intervalo o contador andou: se o byte baixo
estiver perto de estourar, o alto vira e o teste vê 0xAC em vez de 0xAB.

Este script varre os 256 valores possíveis e diz quais passam no teste. É força
bruta, e é o método honesto quando o valor não está documentado: o resultado é
uma medição, não um chute.

    python tests/varrer_div.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import gb.machine as maquina                        # noqa: E402
from gb.cartridge import Cartridge                  # noqa: E402
from gb.constants import B, C, D, E, H, L           # noqa: E402
import test_mooneye as mooneye                      # noqa: E402

PASSOU = {B: 3, C: 5, D: 8, E: 13, H: 21, L: 34}
FALHOU = 0x42


def veredito_de(rom_bytes, valor_do_div, lotes=40, por_lote=5000):
    """Roda a ROM com um valor de DIV e devolve o veredito da Mooneye."""
    maquina.DIV_POS_BOOT = valor_do_div
    m = maquina.Machine(Cartridge(rom_bytes))
    m.reset()
    reg = m.cpu.reg8
    for _ in range(lotes):
        for _ in range(por_lote):
            m.cpu.step()
        if all(reg[r] == v for r, v in PASSOU.items()):
            return "passou"
        if all(reg[r] == FALHOU for r in (B, C, D, E, H, L)):
            return "falhou"
    return "indeciso"


def main():
    suite = mooneye.achar_suite()
    if suite is None:
        print("não achei a suíte da Mooneye.")
        return 2
    rom = os.path.join(suite, "acceptance", "boot_div-dmgABCmgb.gb")
    if not os.path.exists(rom):
        print(f"não achei {rom}")
        return 2
    dados = open(rom, "rb").read()

    original = maquina.DIV_POS_BOOT
    print("varrendo os 256 valores do byte baixo, com o alto fixo em 0xAB...\n")
    achou = []
    try:
        for baixo in range(256):
            v = veredito_de(dados, 0xAB00 | baixo)
            if v == "passou":
                achou.append(baixo)
                print(f"  *** 0xAB{baixo:02X} PASSA", flush=True)
            elif baixo % 32 == 0:
                print(f"  ... 0xAB{baixo:02X} {v}", flush=True)
    finally:
        maquina.DIV_POS_BOOT = original

    print()
    if achou:
        print(f"{len(achou)} valores passam: "
              + ", ".join(f"0xAB{v:02X}" for v in achou))
        if len(achou) > 1:
            print("Mais de um valor serve — o teste não distingue todos os bits "
                  "baixos. Qualquer um deles é uma escolha defensável.")
    else:
        print("Nenhum valor passa. O erro não está no valor inicial do DIV:")
        print("está na taxa de avanço do contador ou no instante da leitura.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
