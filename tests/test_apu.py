"""
Testes do som.

O foco é o que as ROMs `dmg_sound` da Blargg cobram, que é bem mais estrito do
que "o som sai": máscaras de leitura registrador a registrador, o frame
sequencer amarrado ao bit 4 do DIV, os contadores de duração com seus casos de
borda, o envelope, o sweep e as esquisitices da wave RAM.

Vários destes testes existem porque uma versão anterior do emulador falhava
neles. O de máscara de leitura, por exemplo: devolver 0 nos bits que não existem
parece mais limpo e está errado — e nenhum jogo revelaria isso, só a ROM de
teste.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Suite, maquina_de_teste     # noqa: E402

s = Suite("APU")


def maquina():
    m = maquina_de_teste()
    m.bus_write(0xFF40, 0x11)        # LCD desligado
    m.bus_write(0xFF26, 0x80)        # APU ligada
    m.bus_write(0xFF24, 0x77)
    m.bus_write(0xFF25, 0xFF)
    return m


def clock_de_length(m, vezes=1):
    """Avança o frame sequencer até passar por `vezes` passos que clocam length."""
    alvo = vezes
    while alvo:
        antes = m.apu.passo_fs
        m.tick(4)
        if m.apu.passo_fs != antes and (antes & 1) == 0:
            alvo -= 1


# ======================================================================
# Registradores
# ======================================================================
def teste_mascaras_de_leitura():
    """Cada registrador tem bits que não existem fisicamente e leem como 1."""
    m = maquina()
    esperado = {
        0xFF10: 0x80, 0xFF11: 0x3F, 0xFF12: 0x00, 0xFF13: 0xFF, 0xFF14: 0xBF,
        0xFF16: 0x3F, 0xFF17: 0x00, 0xFF18: 0xFF, 0xFF19: 0xBF,
        0xFF1A: 0x7F, 0xFF1B: 0xFF, 0xFF1C: 0x9F, 0xFF1D: 0xFF, 0xFF1E: 0xBF,
        0xFF20: 0xFF, 0xFF21: 0x00, 0xFF22: 0x00, 0xFF23: 0xBF,
    }
    for addr, mascara in esperado.items():
        m.bus_write(addr, 0x00)
        s.igual(m.bus_read(addr) & mascara, mascara,
                f"os bits inexistentes de FF{addr & 0xFF:02X} leem 1")


def teste_nr52_bits_de_status():
    """O registrador de estado diz quais canais estão tocando agora."""
    m = maquina()
    s.checar(bool(m.bus_read(0xFF26) & 0x80), "o bit 7 do NR52 indica a APU ligada")
    s.igual(m.bus_read(0xFF26) & 0x70, 0x70, "os bits 4-6 do NR52 leem 1")


def teste_desligar_apu_zera_registradores():
    """Desligar o som limpa tudo — é o que o hardware faz."""
    m = maquina()
    m.bus_write(0xFF12, 0xF0)        # envelope do canal 1
    m.bus_write(0xFF25, 0xFF)
    m.bus_write(0xFF26, 0x00)        # desliga

    s.igual(m.bus_read(0xFF26) & 0x80, 0, "o bit 7 do NR52 zera ao desligar")
    s.igual(m.bus_read(0xFF25), 0x00, "desligar a APU zera o NR51")
    s.igual(m.bus_read(0xFF12), 0x00, "desligar a APU zera os registradores dos canais")


def teste_wave_ram_sobrevive_ao_desligamento():
    """
    A memória de onda é a única coisa que sobrevive ao desligamento.

    Permite ao jogo preparar a forma de onda com o som desligado.
    """
    m = maquina()
    for i in range(16):
        m.bus_write(0xFF30 + i, 0x10 * (i & 0x0F) + 1)
    m.bus_write(0xFF26, 0x00)
    s.igual(m.bus_read(0xFF30), 0x01,
            "a wave RAM NÃO é apagada quando a APU desliga")


def teste_escritas_ignoradas_com_apu_desligada():
    """
    Com o som desligado quase tudo é ignorado — menos os contadores de duração.

    Essa exceção vale para a DMG e não para o Game Boy Color, e é um dos itens que as
    ROMs de teste usam para distinguir os dois modelos.
    """
    m = maquina()
    m.bus_write(0xFF26, 0x00)
    m.bus_write(0xFF12, 0xF0)
    s.igual(m.bus_read(0xFF12), 0x00,
            "com a APU desligada as escritas nos canais são ignoradas")


def teste_length_gravavel_com_apu_desligada():
    """Na DMG (mas não no CGB) os registradores de length continuam graváveis."""
    m = maquina()
    m.bus_write(0xFF26, 0x00)
    m.bus_write(0xFF11, 0x3F)        # length do canal 1 = 1
    s.igual(m.apu.ch1.length, 1,
            "os registradores de length aceitam escrita mesmo com a APU desligada")


# ======================================================================
# Frame sequencer
# ======================================================================
def teste_fs_segue_o_div():
    """O frame sequencer avança na borda de descida do bit 4 do DIV."""
    m = maquina()
    m.timer.contador = 0x0FFC        # prestes a virar o bit 12
    m.apu._div_bit_anterior = False
    passo = m.apu.passo_fs

    m.tick(4)                        # contador = 0x1000 → bit sobe
    s.igual(m.apu.passo_fs, passo, "a subida do bit 4 do DIV não avança o FS")

    m.timer.contador = 0x1FFC
    m.tick(4)                        # vira para 0x2000 → bit desce
    s.igual(m.apu.passo_fs, (passo + 1) & 7,
            "a descida do bit 4 do DIV avança um passo do FS")


def teste_fs_a_512hz():
    """
    O frame sequencer bate 512 vezes por segundo, e o relógio dele vem do timer.

    Não há circuito dedicado: é um fio ligado no bit 4 do DIV. É por isso que
    escrever em FF04 no momento certo bagunça o andamento da música.
    """
    m = maquina()
    m.apu.passo_fs = 0
    m.tick(8192)                     # 8192 T-cycles = 1/512 s
    s.igual(m.apu.passo_fs, 1, "o frame sequencer roda a 512 Hz")


# ======================================================================
# Length counter
# ======================================================================
def teste_length_desliga_o_canal():
    """O contador de duração cala a nota sozinho ao zerar."""
    m = maquina()
    m.bus_write(0xFF17, 0xF0)        # canal 2: volume 15, DAC ligado
    m.bus_write(0xFF16, 0x3F)        # length = 1
    m.bus_write(0xFF19, 0xC0)        # trigger + length habilitado
    s.checar(m.apu.ch2.habilitado, "o trigger liga o canal 2")

    for _ in range(300):
        clock_de_length(m)
        if not m.apu.ch2.habilitado:
            break
    s.checar(not m.apu.ch2.habilitado, "o length counter acaba desligando o canal")


def teste_trigger_com_length_zero_recarrega():
    """Disparar com o contador zerado o recarrega no máximo."""
    m = maquina()
    m.bus_write(0xFF17, 0xF0)
    m.apu.ch2.length = 0
    m.apu.ch2.length_habilitado = False
    m.bus_write(0xFF19, 0x80)        # trigger sem habilitar length
    s.igual(m.apu.ch2.length, 64,
            "trigger com length zerado recarrega para o máximo (64)")


def teste_canal_wave_tem_length_de_256():
    """O canal 3 conta até 256, e não 64 como os outros."""
    m = maquina()
    m.bus_write(0xFF1A, 0x80)        # DAC do canal 3 ligado
    m.apu.ch3.length = 0
    m.apu.ch3.length_habilitado = False
    m.bus_write(0xFF1E, 0x80)        # trigger
    s.igual(m.apu.ch3.length, 256, "o canal 3 tem length de 256, não de 64")


def teste_clock_extra_ao_habilitar_length():
    """
    Ligar o length no meio de um passo do FS que NÃO clocka length faz o
    hardware dar um clock extra na hora. É o quirk que a ROM 03-trigger cobra.
    """
    m = maquina()
    m.bus_write(0xFF17, 0xF0)
    m.bus_write(0xFF16, 0x3D)        # length = 3
    m.apu.ch2.habilitado = True
    m.apu.ch2.length_habilitado = False
    m.apu.passo_fs = 1               # próximo passo é ímpar → não clocka length

    m.bus_write(0xFF19, 0x40)        # habilita length sem trigger
    s.igual(m.apu.ch2.length, 2, "habilitar o length na metade certa clocka na hora")


def teste_sem_clock_extra_na_outra_metade():
    """
    O decremento extra só acontece na metade certa do ciclo do sequencer.

    O par deste teste — o que confere que ELE acontece — está logo acima. Ter os dois
    é o que impede a correção de virar um decremento a mais em todo lugar.
    """
    m = maquina()
    m.bus_write(0xFF17, 0xF0)
    m.bus_write(0xFF16, 0x3D)        # length = 3
    m.apu.ch2.habilitado = True
    m.apu.ch2.length_habilitado = False
    m.apu.passo_fs = 0               # próximo passo clocka length

    m.bus_write(0xFF19, 0x40)
    s.igual(m.apu.ch2.length, 3, "na outra metade não há clock extra")


# ======================================================================
# DAC e envelope
# ======================================================================
def teste_dac_desligado_mata_o_canal():
    """Sem conversor não há como produzir tensão: o canal morre."""
    m = maquina()
    m.bus_write(0xFF17, 0xF0)
    m.bus_write(0xFF19, 0x80)
    s.checar(m.apu.ch2.habilitado, "canal ligado")

    m.bus_write(0xFF17, 0x00)        # 5 bits altos zerados = DAC desligado
    s.checar(not m.apu.ch2.habilitado, "desligar o DAC desliga o canal na hora")


def teste_trigger_com_dac_desligado_nao_liga():
    """E disparar uma nota com o conversor desligado não adianta nada."""
    m = maquina()
    m.bus_write(0xFF17, 0x00)
    m.bus_write(0xFF19, 0x80)
    s.checar(not m.apu.ch2.habilitado,
             "trigger com o DAC desligado não liga o canal")


def teste_dac_do_canal_3():
    """
    O canal 3 é o único cujo conversor tem bit próprio.

    Os outros tiram o liga/desliga dos bits altos do envelope — que este canal não
    tem.
    """
    m = maquina()
    m.bus_write(0xFF1A, 0x80)
    m.bus_write(0xFF1E, 0x80)
    s.checar(m.apu.ch3.habilitado, "o bit 7 do NR30 é o DAC do canal 3")
    m.bus_write(0xFF1A, 0x00)
    s.checar(not m.apu.ch3.habilitado, "zerar o NR30 desliga o canal 3")


def teste_envelope_desce_o_volume():
    """O volume anda sozinho, um degrau por vez."""
    m = maquina()
    m.bus_write(0xFF17, 0xF1)        # volume 15, descendo, período 1
    m.bus_write(0xFF19, 0x80)
    s.igual(m.apu.ch2.env.volume, 15, "o trigger carrega o volume inicial")

    m.apu.passo_fs = 7
    m.apu._avancar_fs()              # passo 7 clocka o envelope
    s.igual(m.apu.ch2.env.volume, 14, "o envelope decrementa o volume")


def teste_envelope_para_no_limite():
    """Chegando ao teto ou ao chão, o envelope para — não dá a volta."""
    m = maquina()
    m.bus_write(0xFF17, 0x01)        # volume 0, descendo, período 1
    m.bus_write(0xFF19, 0x80)
    for _ in range(10):
        m.apu.passo_fs = 7
        m.apu._avancar_fs()
    s.igual(m.apu.ch2.env.volume, 0, "o envelope não passa de 0")


# ======================================================================
# Sweep (canal 1)
# ======================================================================
def teste_sweep_sobe_a_frequencia():
    """A varredura muda a altura da nota sozinha."""
    m = maquina()
    m.bus_write(0xFF12, 0xF0)        # DAC do canal 1
    m.bus_write(0xFF13, 0x00)
    m.bus_write(0xFF14, 0x04)        # freq = 0x400
    m.bus_write(0xFF10, 0x11)        # período 1, subindo, shift 1
    m.bus_write(0xFF14, 0x84)        # trigger

    m.apu.passo_fs = 2
    m.apu._avancar_fs()              # passo 2 clocka o sweep
    s.igual(m.apu.ch1.freq, 0x400 + 0x200,
            "o sweep soma freq >> shift à frequência")


def teste_sweep_estoura_e_desliga():
    """
    Passar de 2047 desliga o canal.

    É proteção do hardware contra frequências impossíveis, e jogos a usam de
    propósito para terminar um efeito sonoro sem precisar voltar para desligá-lo.
    """
    m = maquina()
    m.bus_write(0xFF12, 0xF0)
    m.bus_write(0xFF13, 0xFF)
    m.bus_write(0xFF14, 0x07)        # freq = 0x7FF (máxima)
    m.bus_write(0xFF10, 0x11)        # subindo, shift 1
    m.bus_write(0xFF14, 0x87)        # trigger → o cálculo já estoura
    s.checar(not m.apu.ch1.habilitado,
             "o sweep que estoura 2047 desliga o canal já no trigger")


# ======================================================================
# Wave RAM
# ======================================================================
def teste_wave_ram_livre_com_canal_desligado():
    """Com o canal 3 parado, a CPU acessa a memória de onda à vontade."""
    m = maquina()
    m.bus_write(0xFF1A, 0x00)        # canal 3 desligado
    m.bus_write(0xFF30, 0xAB)
    s.igual(m.bus_read(0xFF30), 0xAB,
            "com o canal 3 desligado a wave RAM é acessível normalmente")


def teste_wave_ram_bloqueada_com_canal_ligado():
    """
    Com ele tocando, o acesso só passa no T-cycle exato da busca.

    É o comportamento mais estranho do som inteiro, e exige uma precisão que nenhum
    outro canal pede: saber em QUAL dos quatro T-cycles do M-cycle a busca caiu.
    """
    m = maquina()
    for i in range(16):
        m.bus_write(0xFF30 + i, 0x00)
    m.bus_write(0xFF1A, 0x80)
    m.bus_write(0xFF1D, 0x00)
    m.bus_write(0xFF1E, 0x87)        # trigger, frequência alta
    m.apu.ch3.busca_agora = False
    s.igual(m.bus_read(0xFF30), 0xFF,
            "na DMG, ler a wave RAM fora da janela devolve 0xFF")


def teste_amostras_de_4_bits():
    """Cada byte da memória de onda guarda duas amostras."""
    m = maquina()
    m.bus_write(0xFF1A, 0x00)
    m.bus_write(0xFF30, 0x8F)
    m.bus_write(0xFF1A, 0x80)
    m.bus_write(0xFF1C, 0x20)        # volume 100%
    m.bus_write(0xFF1D, 0xFF)
    m.bus_write(0xFF1E, 0x87)        # trigger

    m.apu.ch3.pos = 0
    m.apu.ch3.amostra = 0x0F
    s.igual(m.apu.ch3.amostra_digital(), 0x0F, "volume 100% entrega a amostra inteira")
    m.bus_write(0xFF1C, 0x40)        # 50%
    s.igual(m.apu.ch3.amostra_digital(), 0x07, "volume 50% divide a amostra por 2")
    m.bus_write(0xFF1C, 0x00)        # mudo
    s.igual(m.apu.ch3.amostra_digital(), 0, "volume 0 = mudo")


# ======================================================================
# Ruído
# ======================================================================
def teste_lfsr_de_15_bits():
    """O gerador de ruído percorre uma sequência longa antes de repetir."""
    m = maquina()
    m.bus_write(0xFF21, 0xF0)        # DAC do canal 4
    m.bus_write(0xFF22, 0x00)        # divisor 8, shift 0, 15 bits
    m.bus_write(0xFF23, 0x80)        # trigger
    s.igual(m.apu.ch4.lfsr, 0x7FFF, "o trigger enche o LFSR de 1s")

    m.apu.ch4.step(8)
    s.checar(m.apu.ch4.lfsr != 0x7FFF, "o LFSR avança com o tempo")


def teste_lfsr_curto():
    """
    No modo de 7 bits a sequência repete bem mais rápido.

    O resultado é um chiado quase afinado, usado para sons de robô.
    """
    m = maquina()
    m.bus_write(0xFF21, 0xF0)
    m.bus_write(0xFF22, 0x08)        # bit 3 = modo de 7 bits
    m.bus_write(0xFF23, 0x80)
    s.checar(m.apu.ch4.largura_curta, "o bit 3 do NR43 seleciona o LFSR de 7 bits")


# ======================================================================
# DAC e mixagem analógica
# ======================================================================
def teste_dac_e_bipolar():
    """
    O DAC não transforma 0 em silêncio: 0 é a tensão mais NEGATIVA e 15 a mais
    positiva. Tratar 0 como silêncio deixa o som inteiro acima de zero — é o
    erro que faz o áudio sair estourado.
    """
    from gb.apu import DAC
    s.igual(round(DAC[0], 3), -1.0, "o digital 0 vira a tensão mínima")
    s.igual(round(DAC[15], 3), 1.0, "o digital 15 vira a tensão máxima")
    s.checar(abs(DAC[7] + DAC[8]) < 0.01, "a escala do DAC é simétrica em torno de zero")


def teste_dac_desligado_e_silencio_de_verdade():
    """
    Conversor desligado dá zero; canal parado dá a tensão MÍNIMA, que não é zero.

    Confundir as duas coisas foi um erro real neste projeto. O sintoma era o som
    inteiro deslocado acima de zero, com um estalo a cada canal que ligava ou
    desligava.
    """
    m = maquina()
    m.bus_write(0xFF17, 0x00)        # DAC do canal 2 desligado
    s.igual(m.apu.ch2.saida(), 0.0,
            "com o DAC desligado a saída fica no centro (silêncio real)")

    m.bus_write(0xFF17, 0xF0)        # DAC ligado, canal ainda parado
    s.igual(m.apu.ch2.saida(), -1.0,
            "canal parado com DAC ligado empurra o digital 0, não silêncio")


def teste_saida_sem_corrente_continua():
    """
    O capacitor de saída do console bloqueia a componente DC. Sem ele o sinal
    fica preso acima de zero e cada canal ligando/desligando dá um estouro.
    """
    m = maquina()
    m.apu.audio_ativo = True
    m.bus_write(0xFF25, 0xFF)        # tudo roteado para os dois lados
    m.bus_write(0xFF12, 0xF0)        # canal 1: volume 15
    m.bus_write(0xFF13, 0x00)
    m.bus_write(0xFF14, 0x87)        # trigger

    m.tick(4 * 30000)                # ~28 ms de som

    # O buffer é PCM de 16 bits intercalado (L, R, L, R...).
    from gb.apu import AMPLITUDE
    esq = [v / AMPLITUDE for v in m.apu.buffer[0::2]]
    s.checar(len(esq) > 100, "o buffer de áudio foi preenchido")

    media = sum(esq) / len(esq)
    s.checar(abs(media) < 0.05, "a média da saída fica em torno de zero",
             f"média = {media:+.3f}")
    s.checar(min(esq) < -0.01, "o sinal desce abaixo de zero (é bipolar)",
             f"mínimo = {min(esq):+.3f}")
    s.checar(max(esq) <= 1.3 and min(esq) >= -1.3,
             "a saída não estoura a escala")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("teste_"):
            fn()
    sys.exit(0 if s.relatorio() else 1)
