"""
A APU — o chip de som.

O Game Boy não toca arquivos de áudio. Não haveria como: um segundo de som
gravado ocuparia mais memória do que o cartucho inteiro de Tetris. O que ele tem
são quatro GERADORES de onda, cada um com um jeito próprio de produzir som, e o
jogo os configura escrevendo em registradores — a mesma ideia de um sintetizador.

Uma nota musical vira, na prática, "canal 2, onda quadrada, frequência tal,
volume decaindo". São alguns bytes por nota, e é assim que trilhas sonoras
inteiras cabem em cartuchos minúsculos.

    Canal 1   onda quadrada, com varredura de frequência
    Canal 2   onda quadrada simples
    Canal 3   onda desenhada pelo jogo, 32 amostras de 4 bits
    Canal 4   ruído

Os dois primeiros fazem melodia e baixo. O terceiro permite timbres que a onda
quadrada não alcança. O quarto não tem altura definida: é chiado, e é dele que
saem as explosões, os passos e a percussão.


O QUE É UMA ONDA QUADRADA
-------------------------

O jeito mais barato de gerar som é alternar entre dois valores. Ligado,
desligado, ligado, desligado — mais rápido, som mais agudo. Uma onda quadrada é
isso, e o que se controla nela é a proporção do tempo ligado, chamada DUTY:

    12,5%   ▁▁▁▁▁▁▁█     fininho, quase um clique
    25%     █▁▁▁▁▁▁█     nasal
    50%     █▁▁▁▁███     cheio, o som clássico de videogame
    75%     ▁█████▁▁     soa igual ao de 25%, invertido

Trocar o duty muda o timbre sem mudar a nota. É a diferença entre o baixo e a
melodia de uma mesma trilha.


ENVELOPE: O VOLUME QUE ANDA SOZINHO
-----------------------------------

Uma nota com volume constante soa artificial — instrumentos reais atacam forte e
decaem. Fazer isso pela CPU custaria uma escrita a cada poucos milissegundos,
para cada canal.

O envelope resolve em hardware: o jogo diz "comece no volume 15 e desça de um em
um a cada N passos", e o chip cuida do resto. É o que dá aos sons do Game Boy
aquele decaimento característico.


SWEEP: A FREQUÊNCIA QUE ANDA SOZINHA
------------------------------------

Só o canal 1 tem, e é a mesma ideia aplicada à altura em vez do volume: a
frequência sobe ou desce sozinha, em passos. É o som de um laser, de um pulo, de
alguma coisa caindo.


O FRAME SEQUENCER, E O RELÓGIO QUE VEM DO TIMER
-----------------------------------------------

Envelope, sweep e o contador de duração precisam de um pulso regular. Quem dá é
o frame sequencer, um contador de 8 passos a 512 Hz:

    passo 0   duração
    passo 1   —
    passo 2   duração + sweep
    passo 3   —
    passo 4   duração
    passo 5   —
    passo 6   duração + sweep
    passo 7   envelope

E aqui está a esquisitice mais consequente do chip: o frame sequencer NÃO tem
relógio próprio. Ele é ligado direto na borda de descida do bit 4 do DIV — o
mesmo contador que move o timer, em `timer.py`. É um fio, não um circuito
separado.

A consequência: escrever em FF04 zera aquele contador, e no momento certo isso
bagunça o andamento do som. Um jogo que use o DIV como fonte de aleatoriedade
pode, sem querer, acelerar o próprio decaimento das notas. Acontece no hardware,
e ROMs de teste medem.


O DAC, E O ERRO QUE DEIXA O SOM ESTOURADO
-----------------------------------------

Cada canal tem seu conversor digital-analógico, e ele não funciona como a
intuição sugere. O valor digital 0 NÃO é silêncio: é a tensão mais negativa. O
15 é a mais positiva. Silêncio de verdade só existe com o DAC desligado.

Tratar 0 como silêncio é o erro clássico — foi cometido aqui e corrigido. O
resultado era um sinal inteiramente acima de zero, com um degrau de corrente
contínua, e cada canal que ligava ou desligava produzia um estalo. O console
real tem um capacitor na saída de fone que remove essa componente contínua, e é
por isso que existe um filtro passa-altas no fim de `_calcular_amostra`.
"""

from array import array

# Os quatro formatos de onda quadrada, 8 amostras cada. A fase percorre estes
# oito valores em círculo, e a velocidade da volta define a nota.
DUTIES = (
    (0, 0, 0, 0, 0, 0, 0, 1),   # 12,5%
    (1, 0, 0, 0, 0, 0, 0, 1),   # 25%
    (1, 0, 0, 0, 0, 1, 1, 1),   # 50%
    (0, 1, 1, 1, 1, 1, 1, 0),   # 75%
)

# Divisores de frequência do canal de ruído.
DIVISORES = (8, 16, 32, 48, 64, 80, 96, 112)

# ----------------------------------------------------------------------
# O DAC
# ----------------------------------------------------------------------
# A conversão descrita no topo do arquivo: 0 vira -1,0 e 15 vira +1,0, passando
# por zero no meio da escala. `v / 7.5 - 1.0` faz exatamente esse mapeamento.
DAC = tuple((v / 7.5) - 1.0 for v in range(16))
DAC0 = DAC[0]          # atalho: um canal parado empurra o digital 0

# Amplitude do PCM de 16 bits entregue ao frontend. Fica abaixo do máximo
# possível (32767) para dar folga aos picos da soma dos quatro canais.
AMPLITUDE = 26000

# Quanto o capacitor de saída descarrega por T-cycle. Quanto mais perto de 1,
# mais grave é a frequência de corte do filtro. Este valor é o medido no
# hardware.
FATOR_DE_CARGA = 0.999958

# Bits que não existem em cada registrador e leem sempre 1.
#
# Registrador de som quase nunca usa os 8 bits. Devolver 0 nos bits inexistentes
# pareceria mais limpo e reprovaria nas ROMs de teste, que conferem byte a byte.
MASCARA_LEITURA = {
    0xFF10: 0x80, 0xFF11: 0x3F, 0xFF12: 0x00, 0xFF13: 0xFF, 0xFF14: 0xBF,
    0xFF15: 0xFF, 0xFF16: 0x3F, 0xFF17: 0x00, 0xFF18: 0xFF, 0xFF19: 0xBF,
    0xFF1A: 0x7F, 0xFF1B: 0xFF, 0xFF1C: 0x9F, 0xFF1D: 0xFF, 0xFF1E: 0xBF,
    0xFF1F: 0xFF, 0xFF20: 0xFF, 0xFF21: 0x00, 0xFF22: 0x00, 0xFF23: 0xBF,
    0xFF24: 0x00, 0xFF25: 0x00, 0xFF26: 0x70,
}


# ======================================================================
# Peças reaproveitadas
# ======================================================================
class Envelope:
    """
    O volume que sobe ou desce sozinho, um passo por vez.

    Compartilhado pelos canais 1, 2 e 4 — o canal 3 não tem, porque o volume
    dele é escolhido entre quatro valores fixos.
    """

    def __init__(self):
        self.volume_inicial = 0
        self.subindo = False
        self.periodo = 0        # de quantos passos do sequencer é cada degrau
        self.volume = 0
        self.contador = 0
        self.ativo = False

    def trigger(self):
        """Recomeça do volume inicial. Chamado quando a nota é disparada."""
        self.volume = self.volume_inicial
        # Período 0 conta como 8. É assim no hardware, e vale para o sweep também.
        self.contador = self.periodo if self.periodo else 8
        self.ativo = True

    def clock(self):
        """Um passo do envelope, no passo 7 do frame sequencer."""
        if not self.ativo:
            return
        if self.contador > 0:
            self.contador -= 1
        if self.contador == 0:
            self.contador = self.periodo if self.periodo else 8
            if self.periodo == 0:
                self.ativo = False
                return
            novo = self.volume + (1 if self.subindo else -1)
            if 0 <= novo <= 15:
                self.volume = novo
            else:
                # Chegou ao teto ou ao chão e para ali — não dá a volta.
                self.ativo = False


class CanalBase:
    """
    O que os quatro canais têm em comum: duração, DAC e habilitação.

    O CONTADOR DE DURAÇÃO merece explicação. O jogo pode dizer "toque por N
    passos e cale sozinho", e o hardware conta. Isso poupa a CPU de precisar
    voltar para desligar cada nota — a trilha pode ser uma lista de "toque isto
    por tanto tempo" sem nenhum acompanhamento.

    Os dois métodos com "quirk" na explicação abaixo são casos de borda reais do
    chip, e existem porque o contador é decrementado pelo frame sequencer: mexer
    nele entre dois passos produz resultados que dependem de em qual metade do
    ciclo estamos.
    """

    MAX_LENGTH = 64

    def __init__(self, apu):
        self.apu = apu
        self.habilitado = False
        self.dac_ligado = False
        self.length = 0
        self.length_habilitado = False

    def clock_length(self):
        """Um passo do contador de duração. Ao zerar, o canal se cala."""
        if self.length_habilitado and self.length > 0:
            self.length -= 1
            if self.length == 0:
                self.habilitado = False

    def _trigger_length(self):
        """
        Recarrega o contador quando ele está zerado, no disparo da nota.

        O ajuste de um a menos é um caso de borda: se a recarga acontece num
        passo do sequencer que NÃO decrementa duração, o hardware já sai com um
        decremento adiantado. Sem isso, a nota dura um passo a mais do que
        deveria, e as ROMs de teste de duração acusam.
        """
        if self.length == 0:
            self.length = self.MAX_LENGTH
            if self.length_habilitado and not self.apu.proximo_clocka_length():
                self.length -= 1

    def _escrever_length_enable(self, val):
        """
        Ligar o contador no meio do ciclo dá um decremento extra na hora.

        Outro caso de borda do mesmo tipo, conhecido como "extra length
        clocking". Ligar a contagem num passo que não decrementa faz o hardware
        aplicar um decremento imediato — e se isso zerar o contador sem que haja
        um disparo junto, o canal se cala na mesma hora.
        """
        antes = self.length_habilitado
        agora = (val & 0x40) != 0
        if not antes and agora and not self.apu.proximo_clocka_length():
            if self.length > 0:
                self.length -= 1
                if self.length == 0 and not (val & 0x80):
                    self.habilitado = False
        self.length_habilitado = agora

    def desligar_dac_se_preciso(self):
        """Sem DAC não há como o canal produzir tensão nenhuma: ele morre."""
        if not self.dac_ligado:
            self.habilitado = False

    def saida(self):
        """
        A saída analógica do canal, entre -1 e 1.

        Um canal PARADO não produz silêncio: ele empurra o valor digital 0, que
        o DAC traduz para a tensão mais negativa. Silêncio de verdade só existe
        com o DAC desligado — e é por isso que um jogo que queira calar um canal
        de verdade zera os cinco bits altos do registrador de envelope, em vez de
        simplesmente parar a nota.
        """
        if not self.dac_ligado:
            return 0.0
        return DAC[self.amostra_digital()]


# ======================================================================
# Canais 1 e 2 — ondas quadradas
# ======================================================================
class CanalQuadrado(CanalBase):
    """
    A onda quadrada descrita no topo do arquivo. O canal 1 tem sweep; o 2, não.

    A frequência não é gravada em hertz. O que se escreve é um número de 11 bits,
    e o período sai de `(2048 - freq) * 4` T-cycles por passo da fase. Números
    maiores dão períodos menores, ou seja, notas mais agudas — o valor máximo,
    2047, dá o período mínimo.
    """

    def __init__(self, apu, com_sweep):
        super().__init__(apu)
        self.com_sweep = com_sweep

        self.duty = 0
        self.pos_duty = 0        # em qual das 8 posições da onda estamos
        self.freq = 0
        self.timer = 0
        self.env = Envelope()

        # Sweep — só o canal 1 usa.
        self.sweep_periodo = 0
        self.sweep_negativo = False
        self.sweep_shift = 0
        self.sweep_timer = 0
        self.sweep_sombra = 0    # a frequência que o sweep manipula
        self.sweep_ativo = False
        self.sweep_negou = False  # já houve algum cálculo em modo negativo?

    # ------------------------------------------------------------------
    def step(self, t):
        """
        Avança `t` T-cycles de uma vez, sem laço.

        A fase da onda é pura aritmética: se faltavam `timer` T-cycles para o
        próximo passo e cada passo leva `periodo`, dá para calcular quantos
        passos couberam no lote e somar tudo de uma vez.

        Isso importa porque `sincronizar` pode entregar milhares de T-cycles
        acumulados numa chamada só. Um laço aqui custaria um giro por passo.
        """
        timer = self.timer - t
        if timer > 0:
            self.timer = timer
            return
        periodo = (2048 - self.freq) * 4
        n = (-timer) // periodo + 1
        self.pos_duty = (self.pos_duty + n) & 7
        self.timer = timer + n * periodo

    def amostra_digital(self):
        """O valor de 0 a 15 que entra no DAC: a onda multiplicada pelo volume."""
        if not self.habilitado:
            return 0
        return DUTIES[self.duty][self.pos_duty] * self.env.volume

    # ------------------------------------------------------------------
    def trigger(self):
        """
        Dispara a nota — o que acontece ao escrever o bit 7 do registrador alto.

        Reiniciar tudo aqui é o que permite tocar a mesma nota duas vezes
        seguidas de forma audível: sem o disparo, o envelope continuaria no
        volume em que estava.
        """
        self.habilitado = True
        self._trigger_length()
        self.timer = (2048 - self.freq) * 4
        self.env.trigger()

        if self.com_sweep:
            self.sweep_sombra = self.freq
            self.sweep_timer = self.sweep_periodo if self.sweep_periodo else 8
            self.sweep_ativo = self.sweep_periodo > 0 or self.sweep_shift > 0
            self.sweep_negou = False
            if self.sweep_shift:
                # O primeiro cálculo acontece já no disparo, e se ele estourar o
                # limite o canal morre antes de emitir som nenhum.
                self._calcular_sweep()

        if not self.dac_ligado:
            self.habilitado = False

    def _calcular_sweep(self):
        """
        A próxima frequência do sweep, e o teste que pode matar o canal.

        O passo é proporcional à frequência atual — `sombra >> shift` — e não
        um valor fixo. Por isso a varredura acelera conforme sobe: em escala
        logarítmica, que é como o ouvido percebe altura.

        Passar de 2047 desliga o canal. É uma proteção do hardware contra
        frequências impossíveis, e jogos a usam de propósito para terminar um
        efeito sonoro sem precisar voltar para desligá-lo.
        """
        delta = self.sweep_sombra >> self.sweep_shift
        if self.sweep_negativo:
            nova = self.sweep_sombra - delta
            self.sweep_negou = True
        else:
            nova = self.sweep_sombra + delta
        if nova > 2047:
            self.habilitado = False
        return nova

    def clock_sweep(self):
        """Um passo do sweep, nos passos 2 e 6 do frame sequencer."""
        if not self.com_sweep:
            return
        if self.sweep_timer > 0:
            self.sweep_timer -= 1
        if self.sweep_timer != 0:
            return

        self.sweep_timer = self.sweep_periodo if self.sweep_periodo else 8
        if not self.sweep_ativo or self.sweep_periodo == 0:
            return

        nova = self._calcular_sweep()
        if nova <= 2047 and self.sweep_shift:
            self.sweep_sombra = nova
            self.freq = nova
            # O hardware calcula uma segunda vez e testa de novo, sem guardar o
            # resultado. Parece desperdício e não é: esse segundo teste pode
            # desligar o canal um passo antes do que aconteceria sem ele.
            self._calcular_sweep()


# ======================================================================
# Canal 3 — a onda desenhada pelo jogo
# ======================================================================
class CanalWave(CanalBase):
    """
    O único canal que lê de uma memória: 16 bytes com 32 amostras de 4 bits.

    O jogo desenha a forma de onda que quiser nessa "wave RAM" e o canal a
    percorre em círculo. Dá para imitar um instrumento, ou usar como um
    reprodutor de amostras muito curtas — alguns jogos conseguem voz digitalizada
    assim, reescrevendo a tabela em tempo real.

    E é justamente esse acesso à memória que produz o comportamento mais estranho
    da APU inteira. Enquanto o canal toca, a CPU NÃO consegue ler nem escrever a
    wave RAM livremente: os dois disputam a mesma memória, e o acesso da CPU só
    passa quando cai exatamente no T-cycle em que o canal está buscando uma
    amostra. Fora dessa janela, a leitura devolve 0xFF e a escrita se perde.

    É por isso que este canal precisa saber em QUAL dos quatro T-cycles do
    M-cycle a busca aconteceu — uma precisão que nenhum outro exige. As ROMs
    `09-wave read while on`, `10-wave trigger while on` e `12-wave write while
    on` medem exatamente isso, deslocando o acesso em dois clocks a cada
    tentativa.
    """

    MAX_LENGTH = 256

    def __init__(self, apu):
        super().__init__(apu)
        self.freq = 0
        self.timer = 0
        self.pos = 0                 # qual das 32 amostras está tocando
        self.volume_cod = 0          # 0 mudo, 1 = 100%, 2 = 50%, 3 = 25%
        self.amostra = 0
        self.ultimo_byte_lido = 0

        # True quando a última busca caiu no mesmo T-cycle em que a CPU encosta
        # no barramento. É essa coincidência que abre a janela de acesso.
        self.busca_agora = False

    def step(self, t):
        """
        Avança `t` T-cycles de uma vez, sem laço.

        A versão original percorria T-cycle a T-cycle só para descobrir em qual
        deles a busca caía — milhões de iterações por segundo. A mesma resposta
        sai por aritmética: se faltava `t0` para a primeira busca e o período é
        `p`, as buscas caem em t0, t0+p, t0+2p... e a última que couber no lote
        define tanto a posição final quanto o instante exato.
        """
        if not self.habilitado:
            self.busca_agora = False
            return

        timer = self.timer - t
        if timer > 0:                        # nenhuma busca coube neste lote
            self.timer = timer
            self.busca_agora = False
            return

        periodo = (2048 - self.freq) * 2
        t0 = self.timer                      # quanto faltava para a primeira busca
        n = (t - t0) // periodo + 1          # quantas buscas couberam

        pos = (self.pos + n) & 31
        indice = pos >> 1                    # duas amostras de 4 bits por byte
        b = self.apu.wave_ram[indice]

        self.pos = pos
        self.amostra = (b >> 4) if (pos & 1) == 0 else (b & 0x0F)
        self.ultimo_byte_lido = indice
        self.timer = t0 + n * periodo - t

        # A janela de acesso não se importa com QUANTAS buscas houve, e sim se a
        # última caiu no ÚLTIMO T-cycle do lote — que é o T-cycle em que a CPU
        # encosta no barramento.
        self.busca_agora = (t0 - 1 + (n - 1) * periodo) == t - 1

    def janela_aberta(self):
        """A CPU consegue tocar a wave RAM neste M-cycle?"""
        return (not self.habilitado) or self.busca_agora

    def amostra_digital(self):
        # O volume aqui é um deslocamento, e não uma multiplicação: 100%, metade
        # ou um quarto. Não há envelope neste canal.
        if not self.habilitado or self.volume_cod == 0:
            return 0
        return self.amostra >> (self.volume_cod - 1)

    def trigger(self):
        """
        Dispara o canal — e pode corromper a wave RAM ao fazê-lo.

        Disparar no instante exato em que o canal está buscando uma amostra
        embaralha a memória de onda. É o mesmo tipo de defeito do bug da OAM:
        dois acessos simultâneos à mesma memória, e o resultado é o que a
        eletricidade decidir.
        """
        if self.habilitado and self.busca_agora:
            self._corromper_wave()

        self.habilitado = True
        self._trigger_length()
        # Os 6 T-cycles a mais são um atraso real do hardware ao reiniciar.
        self.timer = (2048 - self.freq) * 2 + 6
        self.pos = 0
        if not self.dac_ligado:
            self.habilitado = False

    def _corromper_wave(self):
        """O padrão exato do embaralhamento, medido em hardware."""
        wr = self.apu.wave_ram
        i = self.ultimo_byte_lido
        if i < 4:
            # Dentro do primeiro bloco, só o byte lido vaza para a posição 0.
            wr[0] = wr[i]
        else:
            # Fora dele, o bloco de 4 bytes inteiro é copiado para o começo.
            bloco = i & 0x0C
            wr[0:4] = wr[bloco:bloco + 4]


# ======================================================================
# Canal 4 — ruído
# ======================================================================
class CanalRuido(CanalBase):
    """
    O canal de chiado: explosões, passos, percussão.

    Ruído é aleatoriedade, e gerar aleatoriedade de verdade num chip é caro. A
    solução é um LFSR — um registrador de deslocamento com realimentação linear.
    Ele produz uma sequência que se repete, mas com período tão longo que o
    ouvido não percebe padrão nenhum.

    O funcionamento cabe em duas linhas: pega os dois bits mais baixos, faz XOR
    entre eles, empurra tudo uma casa para a direita e coloca o resultado no
    topo. O bit que sai por baixo é a saída do canal.

    Há um modo curto, de 7 bits em vez de 15, em que a sequência se repete bem
    mais rápido. O resultado é um chiado metálico, quase afinado — usado para
    sons de robô e efeitos eletrônicos.
    """

    def __init__(self, apu):
        super().__init__(apu)
        self.timer = 0
        self.lfsr = 0x7FFF
        self.shift = 0
        self.largura_curta = False
        self.divisor_cod = 0
        self.env = Envelope()

    def _periodo(self):
        return DIVISORES[self.divisor_cod] << self.shift

    def step(self, t):
        """
        Avança o LFSR.

        Este é o único canal que NÃO dá para resolver por aritmética: cada estado
        depende do anterior, então o laço é inevitável. O que dá para fazer é
        deixar cada volta o mais barata possível — o período e o próprio LFSR
        saem para variáveis locais, e o teste de largura fica FORA do laço em vez
        de dentro dele.

        A diferença é real: com o avanço em lote, este laço chega a mil voltas de
        uma vez. Uma versão anterior chamava `_periodo()` a cada volta, o que
        dava mais de duzentas mil chamadas por segundo à toa.
        """
        if self.shift >= 14:
            return                       # frequências inválidas travam o LFSR

        periodo = DIVISORES[self.divisor_cod] << self.shift
        timer = self.timer - t
        if timer > 0:
            self.timer = timer
            return

        n = (-timer) // periodo + 1
        self.timer = timer + n * periodo
        lfsr = self.lfsr

        if self.largura_curta:
            for _ in range(n):
                bit = (lfsr ^ (lfsr >> 1)) & 1
                lfsr = ((lfsr >> 1) | (bit << 14)) & 0x7FBF | (bit << 6)
        else:
            for _ in range(n):
                bit = (lfsr ^ (lfsr >> 1)) & 1
                lfsr = (lfsr >> 1) | (bit << 14)

        self.lfsr = lfsr

    def amostra_digital(self):
        # O bit 0 INVERTIDO é a saída: com o LFSR começando em todos os bits em
        # 1, o canal parte do silêncio.
        if not self.habilitado:
            return 0
        return (~self.lfsr & 1) * self.env.volume

    def trigger(self):
        self.habilitado = True
        self._trigger_length()
        self.timer = self._periodo()
        self.lfsr = 0x7FFF          # todos os bits em 1: o estado de partida
        self.env.trigger()
        if not self.dac_ligado:
            self.habilitado = False


# ======================================================================
# A APU
# ======================================================================
class APU:
    # A taxa de saída não é do console: é a do computador que vai tocar o som.
    # A APU gera amostras já nesta taxa para que o frontend não precise
    # reamostrar nada.
    TAXA_SAIDA = 44100
    T_POR_AMOSTRA = 4194304 / TAXA_SAIDA

    def __init__(self, bus):
        self.bus = bus

        self.ligada = False
        self.nr50 = 0        # volume geral de cada lado
        self.nr51 = 0        # matriz de roteamento: qual canal vai para qual lado

        self.wave_ram = bytearray(16)

        self.ch1 = CanalQuadrado(self, com_sweep=True)
        self.ch2 = CanalQuadrado(self, com_sweep=False)
        self.ch3 = CanalWave(self)
        self.ch4 = CanalRuido(self)
        self.canais = (self.ch1, self.ch2, self.ch3, self.ch4)

        self.passo_fs = 0
        self._div_bit_anterior = False

        # O buffer de saída: PCM de 16 bits com sinal, intercalado L,R,L,R.
        #
        # Já sai no formato final de propósito. A versão anterior guardava uma
        # tupla de floats por amostra — 44100 tuplas por segundo emulado, que
        # viravam trabalho para o coletor de lixo. Sob PyPy isso aparecia como
        # picos de dezenas de milissegundos no meio do jogo.
        self.audio_ativo = False
        self.buffer = array("h")
        self._acum_amostra = 0.0

        # T-cycles que já passaram mas ainda não foram aplicados aos canais.
        # Ver `sincronizar`.
        self._pendente = 0

        # Estado do filtro passa-altas, um por lado do estéreo.
        self._capacitor = [0.0, 0.0]
        self._esq = 0.0
        self._dir = 0.0
        self.decaimento = FATOR_DE_CARGA ** (4194304.0 / self.TAXA_SAIDA)

    # ==================================================================
    # Tempo
    # ==================================================================
    def step(self):
        """
        Avança 1 M-cycle. Só é chamado com o som ligado.

        O frame sequencer segue a borda de descida do bit 4 do DIV, que é o bit
        12 do contador interno de 16 bits do timer. Não há relógio dedicado — é
        literalmente um fio ligado no divisor, e é por isso que escrever em FF04
        no momento certo bagunça o ritmo do som.

        Este método tem uma cópia inline dentro de `Machine.tick4`.
        """
        bit = (self.bus.timer.contador & 0x1000) != 0
        if self._div_bit_anterior and not bit:
            self.sincronizar()
            self._avancar_fs()
        self._div_bit_anterior = bit

        # Os canais NÃO avançam aqui. O tempo fica anotado como dívida e é pago
        # quando alguém for de fato olhar para eles.
        self._pendente += 4

        # A mixagem só roda se houver alguém ouvindo. Quem liga isso é o
        # frontend, ao abrir a saída de áudio.
        if self.audio_ativo:
            self._acum_amostra += 4
            if self._acum_amostra >= self.T_POR_AMOSTRA:
                self._acum_amostra -= self.T_POR_AMOSTRA
                self.sincronizar()
                self.amostrar()

    def sincronizar(self):
        """
        Paga a dívida de tempo acumulada, pondo os quatro canais em dia.

        Avançar os canais a cada M-cycle custava quatro chamadas de método por
        M-cycle — mais de um milhão e meio por segundo emulado, e o maior custo
        isolado do emulador inteiro.

        A observação que permite evitar isso: o estado interno dos canais (a fase
        da onda, a posição na wave RAM, o LFSR) não é observável de fora, exceto
        em três momentos:

          - a CPU lê ou escreve um registrador de som,
          - o frame sequencer bate,
          - uma amostra de áudio é gerada.

        Então o tempo é acumulado e quitado nesses três momentos. O resultado é
        idêntico, e não aproximado, porque os canais avançam por aritmética: dar
        mil T-cycles de uma vez leva ao mesmo estado que dar quatro, duzentas e
        cinquenta vezes. A única exceção é o LFSR do ruído, que é iterativo — e
        por isso o laço dele continua lá.
        """
        t = self._pendente
        if not t:
            return
        self._pendente = 0

        # Canais mortos, sem habilitação e sem DAC, não têm estado observável e
        # são pulados. O laço está desenrolado porque são só quatro e este é um
        # caminho quente.
        c = self.ch1
        if c.habilitado or c.dac_ligado:
            c.step(t)
        c = self.ch2
        if c.habilitado or c.dac_ligado:
            c.step(t)
        c = self.ch3
        if c.habilitado or c.dac_ligado:
            c.step(t)
        c = self.ch4
        if c.habilitado or c.dac_ligado:
            c.step(t)

    def _avancar_fs(self):
        """Um passo do frame sequencer, seguindo a tabela do topo do arquivo."""
        if not self.ligada:
            return
        passo = self.passo_fs
        self.passo_fs = (passo + 1) & 7

        if passo in (0, 2, 4, 6):
            for c in self.canais:
                c.clock_length()
        if passo in (2, 6):
            self.ch1.clock_sweep()
        if passo == 7:
            self.ch1.env.clock()
            self.ch2.env.clock()
            self.ch4.env.clock()

    def proximo_clocka_length(self):
        """
        O PRÓXIMO passo do sequencer vai decrementar a duração?

        Os casos de borda do contador de duração dependem de saber em qual
        metade do ciclo estamos, e é esta função que responde.
        """
        return (self.passo_fs & 1) == 0

    # ==================================================================
    # Mixagem
    # ==================================================================
    def amostrar(self):
        """
        Gera uma amostra e a grava no buffer já convertida para PCM de 16 bits.

        Nada é alocado no caminho, porque isto roda 44100 vezes por segundo
        emulado. O `int(e * AMPLITUDE)` com os limites em volta é uma saturação:
        a soma dos quatro canais pode passar de 1, e cortar no limite é melhor do
        que deixar o valor dar a volta e virar um estalo.
        """
        self._calcular_amostra()
        b = self.buffer
        e = self._esq
        d = self._dir
        b.append(-32768 if e < -1.0 else 32767 if e > 1.0 else int(e * AMPLITUDE))
        b.append(-32768 if d < -1.0 else 32767 if d > 1.0 else int(d * AMPLITUDE))

    def _misturar(self):
        """A última amostra como par de floats. Usado pelos testes."""
        self._calcular_amostra()
        return (self._esq, self._dir)

    def _calcular_amostra(self):
        """
        Mistura os quatro canais numa amostra estéreo.

        É a segunda função mais quente do emulador, atrás só do `tick4`, e está
        escrita de acordo: sem chamar `saida()` nem uma função de filtro, com o
        DAC de cada canal e o passa-altas escritos inline. São oito chamadas de
        método economizadas por amostra — mais de trezentas mil por segundo.

        O resultado fica em `_esq` e `_dir` em vez de ser devolvido numa tupla,
        pelo mesmo motivo: alocar um objeto por amostra alimenta o coletor de
        lixo o suficiente para causar engasgos visíveis.

        A lógica de cada canal é a de `CanalBase.saida`: DAC desligado dá
        silêncio de verdade, canal parado empurra o digital 0.
        """
        if not self.ligada:
            self._esq = self._dir = 0.0
            return

        c = self.ch1
        v1 = (DAC[DUTIES[c.duty][c.pos_duty] * c.env.volume] if c.habilitado
              else DAC0) if c.dac_ligado else 0.0
        c = self.ch2
        v2 = (DAC[DUTIES[c.duty][c.pos_duty] * c.env.volume] if c.habilitado
              else DAC0) if c.dac_ligado else 0.0
        c = self.ch3
        v3 = (DAC[c.amostra >> (c.volume_cod - 1)]
              if (c.habilitado and c.volume_cod) else DAC0) if c.dac_ligado else 0.0
        c = self.ch4
        v4 = (DAC[(~c.lfsr & 1) * c.env.volume] if c.habilitado
              else DAC0) if c.dac_ligado else 0.0

        # O NR51 é uma matriz de roteamento: cada canal pode sair pela esquerda,
        # pela direita, pelos dois ou por nenhum. É o estéreo do console — e
        # como o aparelho só tem um alto-falante, ele só aparece de fone.
        nr51 = self.nr51
        esq = ((v1 if nr51 & 0x10 else 0.0) + (v2 if nr51 & 0x20 else 0.0)
               + (v3 if nr51 & 0x40 else 0.0) + (v4 if nr51 & 0x80 else 0.0))
        dir_ = ((v1 if nr51 & 0x01 else 0.0) + (v2 if nr51 & 0x02 else 0.0)
                + (v3 if nr51 & 0x04 else 0.0) + (v4 if nr51 & 0x08 else 0.0))

        nr50 = self.nr50
        # Volume geral de cada lado, de 0 a 7. Os quatro canais somados chegam a
        # 4, então o 0,25 embutido na constante normaliza de volta para [-1, 1].
        esq *= (((nr50 >> 4) & 7) + 1) * 0.03125       # (vol+1)/8 * 0.25
        dir_ *= ((nr50 & 7) + 1) * 0.03125

        # O filtro do capacitor de saída, que remove a componente contínua. Sem
        # ele o sinal fica preso acima de zero e cada canal que liga ou desliga
        # produz um estalo audível. Ver a explicação no topo do arquivo.
        cap = self._capacitor
        d = self.decaimento
        se = esq - cap[0]
        cap[0] = esq - se * d
        sd = dir_ - cap[1]
        cap[1] = dir_ - sd * d
        self._esq = se
        self._dir = sd

    def consumir_audio(self):
        """
        Entrega o PCM acumulado e recomeça um buffer vazio.

        Trocar o buffer em vez de esvaziá-lo evita que o frontend fique com uma
        referência para algo que a emulação continua modificando.
        """
        buf = self.buffer
        self.buffer = array("h")
        return buf

    # ==================================================================
    # Registradores (FF10-FF3F)
    # ==================================================================
    def ler(self, addr):
        """
        Lê um registrador de som.

        O `sincronizar()` na primeira linha é obrigatório: a CPU está prestes a
        olhar para o estado dos canais, e eles podem estar com tempo acumulado
        por pagar. Sem isso, o valor lido seria o de alguns M-cycles atrás.
        """
        self.sincronizar()
        if 0xFF30 <= addr <= 0xFF3F:
            # A janela de acesso à wave RAM, descrita em `CanalWave`. Com o canal
            # tocando, a CPU só enxerga a memória no T-cycle da busca — e o que
            # ela lê é o byte que o CANAL buscou, e não o endereço que pediu.
            if self.ch3.habilitado:
                if self.ch3.busca_agora:
                    return self.wave_ram[self.ch3.ultimo_byte_lido]
                return 0xFF
            return self.wave_ram[addr - 0xFF30]

        if addr == 0xFF26:
            # O registrador de estado: quais canais estão tocando agora. É
            # somente-leitura nesses bits, e um jogo o consulta para saber quando
            # uma nota terminou.
            v = 0x70 | (0x80 if self.ligada else 0)
            for i, c in enumerate(self.canais):
                if c.habilitado:
                    v |= 1 << i
            return v

        mascara = MASCARA_LEITURA.get(addr, 0xFF)
        return self._ler_cru(addr) | mascara

    def _ler_cru(self, addr):
        """
        Remonta o valor de um registrador a partir do estado dos canais.

        Este emulador não guarda os bytes escritos: guarda o que eles
        significam. Ler exige, portanto, montar o byte de volta. Dá mais
        trabalho, e em troca não há como o valor guardado divergir do estado
        real — que é uma fonte clássica de bug difícil de achar.
        """
        c1, c2, c3, c4 = self.canais
        if addr == 0xFF10:
            return (self.ch1.sweep_periodo << 4) | (0x08 if c1.sweep_negativo else 0) \
                   | c1.sweep_shift
        if addr == 0xFF11:
            return c1.duty << 6
        if addr == 0xFF12:
            return (c1.env.volume_inicial << 4) | (0x08 if c1.env.subindo else 0) \
                   | c1.env.periodo
        if addr == 0xFF14:
            return 0x40 if c1.length_habilitado else 0
        if addr == 0xFF16:
            return c2.duty << 6
        if addr == 0xFF17:
            return (c2.env.volume_inicial << 4) | (0x08 if c2.env.subindo else 0) \
                   | c2.env.periodo
        if addr == 0xFF19:
            return 0x40 if c2.length_habilitado else 0
        if addr == 0xFF1A:
            return 0x80 if c3.dac_ligado else 0
        if addr == 0xFF1C:
            return c3.volume_cod << 5
        if addr == 0xFF1E:
            return 0x40 if c3.length_habilitado else 0
        if addr == 0xFF21:
            return (c4.env.volume_inicial << 4) | (0x08 if c4.env.subindo else 0) \
                   | c4.env.periodo
        if addr == 0xFF22:
            return (c4.shift << 4) | (0x08 if c4.largura_curta else 0) | c4.divisor_cod
        if addr == 0xFF23:
            return 0x40 if c4.length_habilitado else 0
        if addr == 0xFF24:
            return self.nr50
        if addr == 0xFF25:
            return self.nr51
        return 0x00

    # ------------------------------------------------------------------
    def escrever(self, addr, val):
        """
        Escreve num registrador de som.

        Como na leitura, o `sincronizar()` vem primeiro: disparos e janelas de
        acesso dependem do estado exato dos canais NESTE M-cycle, e não em
        algum ponto do passado.
        """
        self.sincronizar()
        val &= 0xFF

        if 0xFF30 <= addr <= 0xFF3F:
            if self.ch3.habilitado:
                if self.ch3.busca_agora:
                    self.wave_ram[self.ch3.ultimo_byte_lido] = val
                return
            self.wave_ram[addr - 0xFF30] = val
            return

        if addr == 0xFF26:
            self._escrever_nr52(val)
            return

        if not self.ligada:
            # Com o som desligado quase tudo é ignorado — mas na DMG os
            # registradores de DURAÇÃO continuam graváveis. É uma diferença em
            # relação ao Game Boy Color, e um dos itens que as ROMs de teste
            # usam para distinguir os modelos.
            if addr in (0xFF11, 0xFF16, 0xFF1B, 0xFF20):
                self._escrever_length(addr, val)
            return

        self._escrever_ligada(addr, val)

    def _escrever_length(self, addr, val):
        """
        Carrega o contador de duração.

        O valor é escrito ao contrário: o jogo informa quanto já passou, e o que
        se guarda é quanto falta. Daí o `64 - val`.
        """
        if addr == 0xFF11:
            self.ch1.length = 64 - (val & 0x3F)
        elif addr == 0xFF16:
            self.ch2.length = 64 - (val & 0x3F)
        elif addr == 0xFF1B:
            self.ch3.length = 256 - val      # o canal 3 conta até 256
        elif addr == 0xFF20:
            self.ch4.length = 64 - (val & 0x3F)

    def _escrever_ligada(self, addr, val):
        """
        A escrita de verdade, com o som ligado.

        Os registradores seguem um padrão por canal, e conhecê-lo faz o bloco
        abaixo se ler sozinho:

            NRx0   sweep (só o canal 1)
            NRx1   duty e duração
            NRx2   envelope, e o liga/desliga do DAC
            NRx3   os 8 bits baixos da frequência
            NRx4   os 3 bits altos, o disparo (bit 7) e a duração (bit 6)

        A frequência chegar partida em dois registradores é o motivo de o
        disparo ficar no segundo: escrever o byte alto é a última coisa que o
        jogo faz, e é aí que a nota começa, já com a frequência completa.
        """
        c1, c2, c3, c4 = self.canais

        # ---------- Canal 1 ----------
        if addr == 0xFF10:
            negativo_antes = c1.sweep_negativo
            c1.sweep_periodo = (val >> 4) & 7
            c1.sweep_negativo = (val & 0x08) != 0
            c1.sweep_shift = val & 0x07
            # Sair do modo negativo depois de já ter calculado nele mata o canal.
            # É um caso de borda documentado, e há teste que o exercita.
            if negativo_antes and not c1.sweep_negativo and c1.sweep_negou:
                c1.habilitado = False
        elif addr == 0xFF11:
            c1.duty = val >> 6
            c1.length = 64 - (val & 0x3F)
        elif addr == 0xFF12:
            self._escrever_envelope(c1, val)
        elif addr == 0xFF13:
            c1.freq = (c1.freq & 0x700) | val
        elif addr == 0xFF14:
            c1.freq = (c1.freq & 0xFF) | ((val & 0x07) << 8)
            c1._escrever_length_enable(val)
            if val & 0x80:
                c1.trigger()

        # ---------- Canal 2 ----------
        elif addr == 0xFF16:
            c2.duty = val >> 6
            c2.length = 64 - (val & 0x3F)
        elif addr == 0xFF17:
            self._escrever_envelope(c2, val)
        elif addr == 0xFF18:
            c2.freq = (c2.freq & 0x700) | val
        elif addr == 0xFF19:
            c2.freq = (c2.freq & 0xFF) | ((val & 0x07) << 8)
            c2._escrever_length_enable(val)
            if val & 0x80:
                c2.trigger()

        # ---------- Canal 3 ----------
        elif addr == 0xFF1A:
            # Este é o único canal cujo DAC tem um bit próprio, em vez de sair
            # dos bits altos do envelope — porque ele não tem envelope.
            c3.dac_ligado = (val & 0x80) != 0
            c3.desligar_dac_se_preciso()
        elif addr == 0xFF1B:
            c3.length = 256 - val
        elif addr == 0xFF1C:
            c3.volume_cod = (val >> 5) & 3
        elif addr == 0xFF1D:
            c3.freq = (c3.freq & 0x700) | val
        elif addr == 0xFF1E:
            c3.freq = (c3.freq & 0xFF) | ((val & 0x07) << 8)
            c3._escrever_length_enable(val)
            if val & 0x80:
                c3.trigger()

        # ---------- Canal 4 ----------
        elif addr == 0xFF20:
            c4.length = 64 - (val & 0x3F)
        elif addr == 0xFF21:
            self._escrever_envelope(c4, val)
        elif addr == 0xFF22:
            # O ruído não tem frequência: tem um divisor e um deslocamento, que
            # juntos definem a velocidade do LFSR.
            c4.shift = val >> 4
            c4.largura_curta = (val & 0x08) != 0
            c4.divisor_cod = val & 0x07
        elif addr == 0xFF23:
            c4._escrever_length_enable(val)
            if val & 0x80:
                c4.trigger()

        # ---------- Mixer ----------
        elif addr == 0xFF24:
            self.nr50 = val
        elif addr == 0xFF25:
            self.nr51 = val

    def _escrever_envelope(self, canal, val):
        """
        Escreve no registrador de envelope, com o "modo zumbi" incluído.

        Mexer no envelope com o canal TOCANDO produz um efeito colateral que não
        estava no projeto: o volume atual é alterado por um caminho que ninguém
        pretendeu criar. Os ajustes abaixo são o comportamento medido em
        hardware, e não têm explicação limpa — são o que a lógica faz quando
        recebe uma escrita num momento em que não era esperada.

        Alguns jogos, por acidente ou por descoberta, acabaram dependendo disso.

        Os cinco bits altos também controlam o DAC: zerá-los desliga o conversor
        e cala o canal de verdade, que é a forma correta de silenciá-lo.
        """
        env = canal.env
        novo_periodo = val & 0x07
        nova_subida = (val & 0x08) != 0
        novo_inicial = val >> 4

        if canal.habilitado:
            if env.periodo == 0 and env.ativo:
                env.volume = (env.volume + 1) & 0x0F
            elif not env.subindo:
                env.volume = (env.volume + 2) & 0x0F
            if nova_subida != env.subindo:
                env.volume = (16 - env.volume) & 0x0F

        env.periodo = novo_periodo
        env.subindo = nova_subida
        env.volume_inicial = novo_inicial

        canal.dac_ligado = (val & 0xF8) != 0
        canal.desligar_dac_se_preciso()

    def _escrever_nr52(self, val):
        """
        FF26 — o liga/desliga geral do som.

        Desligar zera TODOS os registradores, e não é uma limpeza de cortesia: é
        o que o hardware faz. A wave RAM é a única coisa que sobrevive, o que
        permite ao jogo preparar a forma de onda com o som desligado.

        Ligar reinicia o frame sequencer no passo 0. É por isso que um jogo pode
        desligar e religar a APU para sincronizar a música com alguma outra
        coisa.
        """
        ligar = (val & 0x80) != 0

        if self.ligada and not ligar:
            for addr in range(0xFF10, 0xFF26):
                self._escrever_ligada(addr, 0)
            for c in self.canais:
                c.habilitado = False
                c.dac_ligado = False
                c.length_habilitado = False
            self.nr50 = 0
            self.nr51 = 0
            self.ligada = False

        elif not self.ligada and ligar:
            self.ligada = True
            self.passo_fs = 0
            # O detector de borda precisa começar sabendo o estado atual do bit,
            # senão uma borda falsa apareceria no primeiro M-cycle.
            self._div_bit_anterior = (self.bus.timer.contador & 0x1000) != 0
            self.ch1.pos_duty = 0
            self.ch2.pos_duty = 0
            self.ch3.pos = 0
