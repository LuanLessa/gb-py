"""
Duas formas de ver os mesmos 12 bytes, e por que existem duas.

Os registradores do SM83 podem ser lidos de dois jeitos: como 8 valores de
8 bits, ou como 6 pares de 16 bits. Não são cópias — é a MESMA memória, e
escrever em H muda o byte alto de HL no mesmo instante. `constants.py` explica
como os índices se organizam.

Em Python, a forma direta de expressar isso é um `bytearray` de 12 bytes com um
`memoryview(...).cast("H")` por cima. São duas linhas, é elegante, e funciona.

O problema apareceu ao medir.


O QUE A MEDIÇÃO MOSTROU
-----------------------

PyPy é um interpretador de Python com compilação em tempo de execução. Ele
observa o programa rodando, identifica os trechos quentes e os traduz para
código de máquina — e num emulador, escrito quase todo em laços apertados, isso
costuma render de dez a vinte vezes mais velocidade.

Só que `memoryview.cast` é um dos pontos que esse compilador não consegue
otimizar: ele precisa parar e chamar código em C a cada acesso. E como o acesso
aos registradores é a operação mais frequente do emulador inteiro, esse único
detalhe derrubava todo o ganho.

O número medido, com o mesmo jogo e a mesma máquina:

    memoryview      170,0 quadros por segundo    (2,85x o tempo real)
    por composição 1055,9 quadros por segundo   (17,68x)

Seis vezes mais rápido — trocando código elegante por código que parece pior.
No CPython a relação se inverte, porque lá o `memoryview` é uma chamada em C
enquanto a composição são várias operações interpretadas.

Daí as duas implementações, com a MESMA semântica, e a escolha automática pelo
interpretador em uso. `tests/test_registers.py` verifica que as duas concordam
byte a byte, o que é o que torna a troca segura.
"""

import platform
import sys


class Reg16PorPares:
    """
    Monta o valor de 16 bits a partir dos dois bytes, na hora de cada acesso.

    Parece mais trabalho do que o `memoryview` — e no CPython é mesmo. Mas o
    PyPy consegue embutir estes métodos por completo, e o que sobra depois disso
    são dois acessos a `bytearray` e um deslocamento, que ele compila para
    aritmética direta sobre a memória.

    `__slots__` evita que cada objeto carregue um dicionário de atributos, o que
    economiza memória e um nível de indireção em cada acesso.
    """

    __slots__ = ("r8",)

    def __init__(self, r8):
        self.r8 = r8

    def __getitem__(self, i):
        # `i += i` é o mesmo que `i * 2`, e sai um pouco mais barato: cada par
        # ocupa dois bytes, então o índice do par vira o índice do byte baixo.
        i += i
        r = self.r8
        # Byte baixo primeiro — little-endian, como o processador guarda.
        return r[i] | (r[i + 1] << 8)

    def __setitem__(self, i, valor):
        i += i
        r = self.r8
        r[i] = valor & 0xFF
        r[i + 1] = (valor >> 8) & 0xFF

    def __len__(self):
        return len(self.r8) >> 1


def criar_reg16(reg_buffer, forcar=None):
    """
    Devolve a visão de 16 bits mais rápida para o interpretador em uso.

    `forcar` aceita "memoryview" ou "pares", e existe por dois motivos: permitir
    que os testes comparem as duas implementações entre si, e permitir que o
    benchmark meça a diferença na máquina de quem está rodando.
    """
    if sys.byteorder != "little":
        # As duas implementações assumem que o byte de baixo vem primeiro. Numa
        # máquina big-endian, o par seria montado ao contrário — e falhar aqui,
        # alto e claro, é melhor do que rodar devolvendo valores trocados.
        raise Exception("Este emulador requer um sistema Little-Endian!")

    if forcar == "pares":
        return Reg16PorPares(reg_buffer)
    if forcar == "memoryview":
        return memoryview(reg_buffer).cast("H")

    if platform.python_implementation() == "PyPy":
        return Reg16PorPares(reg_buffer)
    return memoryview(reg_buffer).cast("H")
