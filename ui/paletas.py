"""
Paletas de quatro tons.

O Game Boy não tinha cores: tinha quatro níveis de cinza-esverdeado, e o tom
exato dependia do aparelho — o DMG original era verde-oliva, o Pocket era
cinza de verdade, e a mesma ROM parecia outro jogo em cada um.

As paletas abaixo servem tanto ao jogo quanto à interface. Ter uma só fonte de
cores é o que faz o menu parecer parte do console: se você troca para o cinza
do Pocket, o menu troca junto.

O índice 0 é sempre o tom mais claro e o 3 o mais escuro — a PPU depende disso.
"""

PALETAS = {
    "verde":  ("verde (DMG)",    (0xE0F8D0, 0x88C070, 0x346856, 0x081820)),
    "cinza":  ("cinza (Pocket)", (0xFFFFFF, 0xA9A9A9, 0x545454, 0x000000)),
    "ambar":  ("âmbar",          (0xFFF4D6, 0xE0A44C, 0x9A5B1E, 0x3B1F0B)),
    "azul":   ("azul",           (0xE8F4FF, 0x7FA8D0, 0x3D5A80, 0x14213D)),
}

PADRAO = "verde"

# Na ordem em que o menu as apresenta.
OPCOES = [(chave, PALETAS[chave][0]) for chave in ("verde", "cinza", "ambar", "azul")]


def tons(chave):
    """Os quatro tons de uma paleta, em RGB de 24 bits."""
    return PALETAS.get(chave, PALETAS[PADRAO])[1]


def nome(chave):
    """O nome legível de uma paleta, para o menu."""
    return PALETAS.get(chave, PALETAS[PADRAO])[0]
