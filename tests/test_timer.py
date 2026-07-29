"""
Testes do timer.

Um teste que só conferisse "o TIMA sobe a cada N ciclos" passaria num emulador
errado. Os casos aqui são deliberadamente os comportamentos ESQUISITOS do
hardware — os que separam um emulador que roda a maioria dos jogos de um que
roda todos:

  * escrever no DIV pode incrementar o TIMA, porque zerar o contador cria uma
    borda de descida;
  * trocar a frequência no TAC pode fazer a mesma coisa, pelo mesmo motivo;
  * o TIMA fica um M-cycle inteiro valendo 0 antes de receber o TMA, e uma
    escrita nesse instante é engolida pelo hardware.

Cada um deles existe porque uma ROM de teste da Blargg o cobra, e a explicação
do mecanismo está em `gb/timer.py`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Suite, maquina_de_teste     # noqa: E402

s = Suite("Timer")


def m_com_tac(tac, tima=0, tma=0):
    m = maquina_de_teste()
    m.timer.contador = 0
    m.timer.sinal = False
    m.bus_write(0xFF07, tac)
    m.bus_write(0xFF06, tma)
    m.bus_write(0xFF05, tima)
    m.if_ = 0
    return m


# ----------------------------------------------------------------------
# DIV
# ----------------------------------------------------------------------
def teste_div_conta():
    """O contador sobe sozinho, e o DIV mostra o byte alto dele."""
    m = maquina_de_teste()
    m.timer.contador = 0
    m.tick(256 * 4)          # 256 M-cycles = 1024 T = 4 incrementos do DIV
    s.igual(m.bus_read(0xFF04), 4, "DIV sobe 1 a cada 256 T-cycles")


def teste_div_escrita_zera():
    """
    Qualquer escrita em FF04 zera o contador, seja qual for o valor.

    Um emulador que guardasse o byte escrito passaria em jogo nenhum: o DIV é usado
    como fonte de aleatoriedade justamente por ser incontrolável.
    """
    m = maquina_de_teste()
    m.tick(4 * 300)
    m.bus_write(0xFF04, 0xAB)
    s.igual(m.bus_read(0xFF04), 0, "escrever em FF04 zera o DIV (ignora o valor)")


def teste_div_zera_incrementa_tima():
    """
    O clássico: com TAC=0x05 (bit 3), se o bit 3 do contador estiver em 1 e o
    jogo escrever no DIV, o contador zera — criando uma borda de descida que
    incrementa o TIMA "do nada".
    """
    m = m_com_tac(0x05)
    m.timer.contador = 0x08          # bit 3 ligado
    m.timer._avaliar_borda()
    antes = m.bus_read(0xFF05)
    m.bus_write(0xFF04, 0x00)
    s.igual(m.bus_read(0xFF05), (antes + 1) & 0xFF,
            "escrever no DIV com o bit selecionado em 1 incrementa o TIMA")


# ----------------------------------------------------------------------
# Frequências
# ----------------------------------------------------------------------
def teste_frequencias():
    # (TAC, T-cycles por incremento do TIMA)
    """
    Cada valor do TAC vigia um bit diferente, e portanto uma frequência diferente.

    As quatro são conferidas contando quantos T-cycles se passam entre dois
    incrementos do TIMA. Errar a tabela de bits desafina toda música de jogo que use
    o timer para marcar o compasso.
    """
    for tac, periodo in ((0x04, 1024), (0x05, 16), (0x06, 64), (0x07, 256)):
        m = m_com_tac(tac)
        m.tick(periodo * 10)
        s.igual(m.bus_read(0xFF05), 10,
                f"TAC=0x{tac:02X} incrementa o TIMA a cada {periodo} T-cycles")


def teste_desabilitado_nao_conta():
    """Com o bit 2 do TAC desligado, o TIMA fica parado."""
    m = m_com_tac(0x00)              # bit 2 desligado = timer parado
    m.tick(4096)
    s.igual(m.bus_read(0xFF05), 0, "com o bit 2 do TAC desligado o TIMA não anda")


# ----------------------------------------------------------------------
# Estouro e recarga
# ----------------------------------------------------------------------
def teste_estouro_recarrega_e_interrompe():
    """
    Ao dar a volta, o TIMA recebe o TMA e a interrupção sai.

    É o ciclo completo, e o caso que qualquer emulador acerta. Os três testes
    seguintes cobrem as bordas dele, que quase nenhum acerta.
    """
    m = m_com_tac(0x05, tima=0xFF, tma=0x37)
    m.tick(16)                       # provoca o estouro
    s.igual(m.bus_read(0xFF05), 0x00, "no M-cycle do estouro o TIMA fica em 0x00")
    s.checar(not (m.if_ & 0x04), "a interrupção ainda não foi pedida no estouro")

    m.tick(4)                        # o M-cycle seguinte faz a recarga
    s.igual(m.bus_read(0xFF05), 0x37, "1 M-cycle depois o TIMA recebe o TMA")
    s.checar(bool(m.if_ & 0x04), "a interrupção de timer é pedida na recarga")


def teste_escrita_no_tima_cancela_recarga():
    """
    Escrever no TIMA cancela um estouro que ainda não recarregou.

    Faz sentido: se o programa acabou de pôr um valor novo ali, a recarga pendente
    diz respeito a um número que não existe mais.
    """
    m = m_com_tac(0x05, tima=0xFF, tma=0x37)
    m.tick(16)                       # estourou, recarga pendente
    m.bus_write(0xFF05, 0x12)        # escrita durante o atraso
    m.tick(4)
    s.igual(m.bus_read(0xFF05), 0x12,
            "escrever no TIMA durante o atraso cancela a recarga")
    s.checar(not (m.if_ & 0x04),
             "cancelar a recarga também cancela a interrupção")


def teste_escrita_no_tma_durante_recarga():
    """
    Escrever no TMA durante a recarga muda também o TIMA.

    Uma janela de UM M-cycle. O valor novo chega a tempo de ser o que está sendo
    copiado — e um jogo que troque o TMA na rotina de interrupção do timer cai
    exatamente nela.
    """
    m = m_com_tac(0x05, tima=0xFF, tma=0x37)
    m.tick(16)
    m.tick(4)                        # aqui a recarga acontece
    m.bus_write(0xFF06, 0x99)        # escrever no TMA no M-cycle da recarga...
    s.igual(m.bus_read(0xFF05), 0x99,
            "escrever no TMA no M-cycle da recarga muda o valor recarregado")


def teste_escrita_no_tima_durante_recarga_e_ignorada():
    """
    E escrever no TIMA nessa mesma janela é engolido pelo hardware.

    O par com o teste acima: na mesma janela de um M-cycle, uma escrita vale e a
    outra some. É o tipo de assimetria que só se descobre medindo o chip.
    """
    m = m_com_tac(0x05, tima=0xFF, tma=0x37)
    m.tick(16)
    m.tick(4)                        # M-cycle da recarga
    m.bus_write(0xFF05, 0x11)
    s.igual(m.bus_read(0xFF05), 0x37,
            "escrever no TIMA no M-cycle da recarga é ignorado")


# ----------------------------------------------------------------------
# TAC
# ----------------------------------------------------------------------
def teste_tac_bits_altos():
    """
    Os bits 3 a 7 do TAC não existem e leem sempre 1.

    Devolver 0 ali pareceria mais limpo e reprovaria na ROM de teste, que compara o
    byte inteiro.
    """
    m = maquina_de_teste()
    m.bus_write(0xFF07, 0x00)
    s.igual(m.bus_read(0xFF07), 0xF8, "os bits 3-7 do TAC leem sempre 1")


def teste_desligar_tac_pode_incrementar():
    """Desligar o timer com o bit selecionado em 1 gera uma borda de descida."""
    m = m_com_tac(0x05)
    m.timer.contador = 0x08
    m.timer._avaliar_borda()
    antes = m.bus_read(0xFF05)
    m.bus_write(0xFF07, 0x01)        # desliga (bit 2 = 0)
    s.igual(m.bus_read(0xFF05), (antes + 1) & 0xFF,
            "desligar o TAC com o bit em 1 incrementa o TIMA")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("teste_"):
            fn()
    sys.exit(0 if s.relatorio() else 1)
