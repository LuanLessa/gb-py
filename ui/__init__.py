"""
A interface: menu de pausa, seletor de jogos e ajustes.

Esta pasta é separada de `gb/` por uma razão de organização que vale entender,
porque ela guia decisões no projeto inteiro.

`gb/` é o console. Cada arquivo lá dentro corresponde a um chip, e nada lá sabe
que existe uma tela, um teclado ou uma pessoa jogando. Interface não é hardware.
Misturar as duas coisas destruiria a propriedade que sustenta o projeto — a de
que o emulador roda sozinho, sem depender de nada além da biblioteca padrão do
Python, e por isso pode ser testado sem abrir janela nenhuma.

O mesmo princípio se repete DENTRO desta pasta, num nível abaixo: só o
`desenho.py` importa pygame. Fonte, menus, preferências e leitura da pasta de
jogos são Python puro.

Isso não é purismo. É o que permite ao `tests/test_ui.py` navegar pelos menus
inteiros, trocar ajustes e conferir o resultado em milissegundos, sem placa de
vídeo e sem ninguém apertando tecla. E é o que permite testar o DESENHO num
servidor sem monitor, entregando ao `desenho.py` um pygame de mentira que, em
vez de pintar, anota onde cada retângulo caiu.

Sempre que uma parte do programa consegue ser separada do mundo exterior desse
jeito, ela fica testável — e o que é testável tende a continuar funcionando.

    fonte.py       os caracteres desenhados à mão, 5x7, com acentos
    paletas.py     os quatro tons, usados pelo jogo e pelo menu
    config.py      preferências que sobrevivem a fechar a janela
    biblioteca.py  a pasta de jogos e os títulos lidos dos cartuchos
    menu.py        páginas, itens e navegação — sem pygame
    desenho.py     a pintura, e o único arquivo que fala com o pygame
"""

from .config import Preferencias
from .biblioteca import Biblioteca
from .menu import Menu

__all__ = ["Preferencias", "Biblioteca", "Menu", "paletas"]
