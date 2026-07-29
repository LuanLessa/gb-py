"""
O barramento — a placa em que todos os chips estão soldados.

A CPU sabe fazer conta e sabe pedir "me dê o byte do endereço 0x8000". O que
ela não sabe é QUEM responde por esse endereço. Descobrir isso é trabalho deste
arquivo, e é a primeira das duas coisas que ele faz.

    1. DECODIFICAR ENDEREÇOS
       0x0100 é ROM do cartucho, 0x8000 é memória de vídeo, 0xFF07 é o
       registrador de controle do timer. São faixas fixas, definidas quando o
       console foi projetado, e `bus_read` e `bus_write` são o mapa.

    2. DISTRIBUIR O TEMPO
       Cada M-cycle que a CPU consome é repassado ao timer, à PPU, ao DMA, ao
       som e à porta serial. Todos avançam juntos, de 4 em 4 T-cycles, no meio
       da execução de cada instrução.

O segundo ponto é o que dá a precisão do emulador. Nada roda "em lote" no fim
do quadro: quando uma instrução lê três bytes da memória, o mundo avança três
vezes durante essa instrução, e a PPU pode muito bem mudar de estado entre a
primeira e a segunda leitura — como no hardware.


O MAPA DE MEMÓRIA
-----------------

Os 65.536 endereços que a CPU enxerga não são todos memória. Boa parte é
fiação: escrever num endereço específico liga o som, muda a paleta ou dispara
uma cópia. O mapa completo:

    0000-3FFF   ROM, banco fixo         o começo do cartucho, sempre visível
    4000-7FFF   ROM, banco trocável     o resto, uma fatia por vez
    8000-9FFF   VRAM                    os desenhos e o mapa da tela
    A000-BFFF   RAM do cartucho         o save, quando o cartucho tem pilha
    C000-DFFF   WRAM                    os 8 KB de memória do console
    E000-FDFF   eco da WRAM             a mesma memória, num segundo endereço
    FE00-FE9F   OAM                     a tabela dos 40 sprites
    FEA0-FEFF   proibida                não existe; o chip responde esquisito
    FF00-FF7F   registradores           os controles de todo o hardware
    FF80-FFFE   HRAM                    127 bytes de memória rápida
    FFFF        IE                      quais interrupções o jogo quer

Duas faixas merecem explicação.

O ECO da WRAM (E000-FDFF) devolve exatamente os mesmos bytes de C000-DDFF. Não
foi decisão de projeto: o chip simplesmente não conferia todos os bits do
endereço, e a memória acabou aparecendo duas vezes. A Nintendo mandava não usar,
mas alguns jogos usam mesmo assim, e um emulador tem de reproduzir.

A HRAM (FF80-FFFE) é memória de verdade, dentro do processador. Ela existe por
causa do DMA: durante uma cópia automática de sprites, a CPU perde o acesso à
memória externa e só consegue executar código que esteja aqui. Todo jogo tem uma
rotininha copiada para a HRAM só para esperar o DMA terminar.
"""

from .cpu import CPU
from .timer import Timer
from .ppu import PPU
from .dma import DMA
from .apu import APU
from .serial import Serial
from .joypad import Joypad


class Machine:
    def __init__(self, cart):
        self.cart = cart
        self.wram = bytearray(0x2000)   # 8 KB de memória do console (C000-DFFF)
        self.hram = bytearray(0x7F)     # 127 bytes dentro da CPU (FF80-FFFE)
        self.ie = 0                     # FFFF — quais interrupções interessam
        self.if_ = 0xE1                 # FF0F — quais estão pedindo atenção
        self.cycles = 0                 # T-cycles desde que o console ligou

        # Cada periférico recebe o barramento na construção, e não o contrário.
        # É por essa referência que eles pedem interrupção: a PPU, ao terminar
        # um quadro, escreve num bit de `self.if_` e a CPU descobre sozinha.
        self.timer = Timer(self)
        self.ppu = PPU(self)
        self.dma = DMA(self)
        self.apu = APU(self)
        self.serial = Serial(self)
        self.joypad = Joypad(self)

        self.cpu = CPU(self)

        # Atalhos para o caminho quente. Ler `self.cart.rom` custa dois acessos
        # a atributo; ler `self.rom` custa um. Parece exagero até lembrar que
        # toda busca de instrução passa por aqui, milhões de vezes por segundo.
        self.rom = cart.rom
        self.rom_len = len(cart.rom)
        self.mbc = cart.mbc

        self._boot_rom_ativa = False

    # ==================================================================
    # Distribuição do tempo
    # ==================================================================
    def tick4(self):
        """
        Avança o console inteiro em exatamente 1 M-cycle.

        Este é o método mais chamado do emulador — mais de um milhão de vezes
        por segundo emulado. É o único lugar do projeto onde a legibilidade
        cedeu espaço para a velocidade, e vale explicar o porquê antes de o
        código assustar.

        O jeito natural de escrever isto seriam quatro chamadas: `timer.step()`,
        `ppu.step()`, `apu.step()`, `serial.step()`. Some cinco milhões de
        chamadas de função por segundo emulado — e em Python cada chamada custa
        mais do que o trabalho que ela faz. Somar 4 num contador e comparar com
        um limite é barato; entrar e sair de uma função, não.

        A solução foi copiar para cá o CAMINHO COMUM de cada periférico: aquele
        em que nada de interessante acontece e só o contador anda. Quando algo
        realmente acontece — um estouro, um evento de vídeo —, o código chama o
        método do módulo, que continua sendo o dono da lógica de verdade.

        Cada bloco abaixo tem, portanto, um gêmeo documentado no seu arquivo. O
        lugar de entender o timer é `timer.py`; aqui está só o atalho.
        """
        self.cycles += 4

        # --- Timer ---
        # Caminho comum: o contador anda e o detector de borda é reavaliado.
        # Caminho raro: um estouro do TIMA está em curso, e aí a lógica
        # completa de `Timer.step` é necessária.
        t = self.timer
        if t.recarga_pendente or t.recarregando:
            t.step()
        else:
            c = (t.contador + 4) & 0xFFFF
            t.contador = c
            if t.habilitado:
                novo = (c >> t.bit_sel) & 1 == 1
                if t.sinal and not novo:
                    t._incrementar_tima()
                t.sinal = novo

        # --- DMA ---
        # Só faz alguma coisa quando há uma cópia em andamento, o que é raro:
        # 160 M-cycles por quadro, contra os 17.556 do quadro inteiro.
        if self.dma.ativo or self.dma.atraso:
            self.dma.step()

        # --- PPU ---
        # O vídeo avança em "dots", que são T-cycles. Em vez de decidir a cada
        # passo em qual modo ela está, a PPU calcula com antecedência o instante
        # do PRÓXIMO evento; aqui basta comparar dois números.
        p = self.ppu
        if p.ligado:
            d = p.dot + 4
            p.dot = d
            if d >= p.proximo_evento:
                p._processar_evento()

        # --- Som ---
        # O detalhe curioso: o relógio interno do som é derivado do bit 12 do
        # contador do timer. Não é coincidência nem gambiarra do emulador — no
        # chip real os dois compartilham o mesmo divisor, e é por isso que
        # escrever no DIV pode alterar o andamento do som de um jogo.
        a = self.apu
        if a.ligada:
            bit = (t.contador & 0x1000) != 0
            if a._div_bit_anterior and not bit:
                a.sincronizar()
                a._avancar_fs()
            a._div_bit_anterior = bit
            a._pendente += 4
            if a.audio_ativo:
                a._acum_amostra += 4
                if a._acum_amostra >= a.T_POR_AMOSTRA:
                    a._acum_amostra -= a.T_POR_AMOSTRA
                    a.sincronizar()
                    a.amostrar()

        # --- Porta serial ---
        if self.serial.transferindo:
            self.serial.step()

    def tick(self, t):
        """
        Avança `t` T-cycles. O valor é sempre múltiplo de 4.

        O relógio de tempo real do MBC3 é atualizado aqui, e não dentro do
        `tick4`, porque ele conta segundos de verdade: não faria diferença
        alguma consultá-lo um M-cycle antes ou depois.
        """
        for _ in range(t >> 2):
            self.tick4()

        if self.cart.tem_rtc:
            self.cart.tick(t)

    # ==================================================================
    # Leitura
    # ==================================================================
    def bus_read(self, addr):
        """
        Devolve o byte de um endereço, seja ele memória ou hardware.

        A ordem dos testes não é a ordem do mapa de memória: é a ordem da
        frequência. A ROM vem primeiro porque toda busca de instrução passa por
        aqui, e adiar esse teste custaria comparações inúteis milhões de vezes
        por segundo.
        """
        # Durante uma cópia automática de sprites, a CPU perde o barramento
        # EXTERNO e qualquer leitura devolve 0xFF. Os registradores e a HRAM
        # ficam de fora do bloqueio por serem internos ao chip — e é exatamente
        # por isso que a rotina de espera do DMA precisa rodar da HRAM.
        if self.dma.ativo and addr < 0xFF00:
            return 0xFF

        # Leitura da ROM, sem intermediários. O cartucho mantém `off0` e `off1`
        # atualizados com o deslocamento de cada banco, então isto é uma soma e
        # um acesso a `bytearray` — e não duas chamadas de método por byte.
        if addr < 0x8000:
            mbc = self.mbc
            i = addr + (mbc.off0 if addr < 0x4000 else mbc.off1)
            return self.rom[i] if i < self.rom_len else 0xFF

        # `addr >> 12` descarta os 12 bits de baixo e sobra o dígito
        # hexadecimal mais alto do endereço — que é justamente o que separa as
        # faixas do mapa. 0x8000 e 0x9FFF dão ambos 8 e 9, a faixa da VRAM.
        top = addr >> 12
        if top <= 9:
            return self.ppu.ler_vram(addr)
        if top <= 0xB:
            return self.cart.read_ram(addr)
        if top <= 0xD:
            return self.wram[addr & 0x1FFF]
        if addr < 0xFE00:
            # Eco da WRAM. `& 0x1FFF` fica com os 13 bits de baixo, que é o que
            # sobra dentro dos 8 KB — e é literalmente o que o chip fazia ao
            # não conferir os bits de cima.
            return self.wram[addr & 0x1FFF]
        if addr < 0xFEA0:
            return self.ppu.ler_oam(addr)
        if addr < 0xFF00:
            # A faixa proibida. Não há memória aqui, e o valor devolvido depende
            # do que a PPU está fazendo: 0x00 normalmente, 0xFF enquanto ela
            # está usando a tabela de sprites.
            return 0xFF if (self.ppu.ligado and self.ppu.modo >= 2) else 0x00
        if addr < 0xFF80:
            return self.read_io(addr)
        if addr == 0xFFFF:
            return self.ie
        return self.hram[addr - 0xFF80]

    def ler_para_dma(self, addr):
        """
        Leitura feita pelo próprio DMA, que não obedece ao bloqueio.

        Faz sentido: quem bloqueou o barramento foi o DMA, e seria absurdo ele
        bloquear a si mesmo.
        """
        top = addr >> 12
        if top <= 7:
            return self.cart.read_rom(addr)
        if top <= 9:
            return self.ppu.vram[addr & 0x1FFF]
        if top <= 0xB:
            return self.cart.read_ram(addr)
        if top <= 0xF:
            return self.wram[addr & 0x1FFF]
        return 0xFF

    # ==================================================================
    # Escrita
    # ==================================================================
    def bus_write(self, addr, val):
        """
        Grava um byte — ou aciona o hardware, conforme o endereço.

        A primeira faixa é a mais surpreendente. Escrever entre 0x0000 e 0x7FFF
        é escrever "na ROM", que por definição é só de leitura. E funciona: não
        grava nada, mas o chip dentro do cartucho escuta o barramento e usa
        esses valores como COMANDO para trocar de banco. Ver `cartridge.py`.
        """
        val &= 0xFF

        if self.dma.ativo and addr < 0xFF00:
            return

        top = addr >> 12
        if top <= 7:
            self.cart.write_rom(addr, val)         # comando para o MBC
        elif top <= 9:
            self.ppu.escrever_vram(addr, val)
        elif top <= 0xB:
            self.cart.write_ram(addr, val)
        elif top <= 0xD:
            self.wram[addr & 0x1FFF] = val
        elif addr < 0xFE00:
            self.wram[addr & 0x1FFF] = val         # eco da WRAM
        elif addr < 0xFEA0:
            self.ppu.escrever_oam(addr, val)
        elif addr < 0xFF00:
            pass                                   # faixa proibida: some
        elif addr < 0xFF80:
            self.write_io(addr, val)
        elif addr == 0xFFFF:
            self.ie = val
        else:
            self.hram[addr - 0xFF80] = val

    # ==================================================================
    # Registradores de hardware (FF00-FF7F)
    # ==================================================================
    #
    # Cada endereço desta faixa é um botão ligado a algum chip. Ler FF00 devolve
    # o estado dos botões; escrever FF46 dispara uma cópia de sprites; escrever
    # FF40 pode apagar a tela.
    #
    # As duas funções abaixo são só uma central telefônica: recebem o endereço e
    # passam a ligação para o módulo certo. A lógica de cada registrador mora no
    # arquivo do seu chip.

    def read_io(self, addr):
        if addr == 0xFF00:
            return self.joypad.ler()
        if addr == 0xFF01:
            return self.serial.ler_sb()
        if addr == 0xFF02:
            return self.serial.ler_sc()
        if addr == 0xFF04:
            return self.timer.ler_div()
        if addr == 0xFF05:
            return self.timer.ler_tima()
        if addr == 0xFF06:
            return self.timer.ler_tma()
        if addr == 0xFF07:
            return self.timer.ler_tac()
        if addr == 0xFF0F:
            # Só 5 interrupções existem, e os 3 bits de cima não têm fiação:
            # leem sempre 1. Devolver 0 ali reprovaria em teste.
            return self.if_ | 0xE0
        if 0xFF10 <= addr <= 0xFF3F:
            return self.apu.ler(addr)
        if addr == 0xFF46:
            return self.dma.ler()
        if 0xFF40 <= addr <= 0xFF4B:
            return self.ppu.ler_reg(addr)
        # Endereço sem ninguém do outro lado. Um barramento solto lê como 0xFF,
        # porque é para onde os resistores o puxam quando nada o controla.
        return 0xFF

    def write_io(self, addr, val):
        if addr == 0xFF00:
            self.joypad.escrever(val)
        elif addr == 0xFF01:
            self.serial.escrever_sb(val)
        elif addr == 0xFF02:
            self.serial.escrever_sc(val)
        elif addr == 0xFF04:
            # O valor escrito é ignorado: qualquer escrita aqui zera o contador.
            self.timer.escrever_div()
        elif addr == 0xFF05:
            self.timer.escrever_tima(val)
        elif addr == 0xFF06:
            self.timer.escrever_tma(val)
        elif addr == 0xFF07:
            self.timer.escrever_tac(val)
        elif addr == 0xFF0F:
            self.if_ = val & 0x1F
        elif 0xFF10 <= addr <= 0xFF3F:
            self.apu.escrever(addr, val)
        elif addr == 0xFF46:
            self.dma.escrever(val)
        elif 0xFF40 <= addr <= 0xFF4B:
            self.ppu.escrever_reg(addr, val)
        elif addr == 0xFF50:
            # Escrever aqui desliga a ROM de boot e a faz desaparecer do mapa,
            # descobrindo a ROM do cartucho por baixo. É a última coisa que a
            # ROM de boot faz, e não tem volta: só ligando o console de novo.
            self._boot_rom_ativa = False

    # ==================================================================
    # Conveniências
    # ==================================================================
    @property
    def saida_serial(self):
        """Tudo que o cartucho mandou pela porta serial desde que ligou."""
        return self.serial.saida

    @property
    def serial_bytes(self):
        """Nome antigo de `saida_serial`, mantido para os testes que o usam."""
        return self.serial.saida

    def reset(self):
        """
        Deixa o console no estado exato de quando a ROM de boot termina.

        A ROM de boot faz mais do que mostrar o logotipo: ela deixa vários
        registradores configurados, e os jogos contam com isso. Um jogo que
        assume o vídeo já ligado não o liga por conta própria, e a tela ficaria
        preta se o emulador começasse com tudo zerado.

        Os valores abaixo foram medidos num DMG real e são o que a ROM de boot
        deixa para trás.
        """
        self.cpu.reset_pos_boot()
        self.if_ = 0xE1
        self.ie = 0x00

        # O contador do timer não começa em zero: a ROM de boot leva um tempo
        # para rodar, e o contador andou junto. O valor exato importa para jogos
        # que usam o DIV como fonte de números aleatórios.
        self.timer.contador = 0xABCC
        self.timer.escrever_tac(0xF8)
        self.timer.tima = 0
        self.timer.tma = 0

        self.ppu.lcdc = 0x91        # vídeo ligado, fundo ligado, sprites ligados
        self.ppu.ligado = True
        self.ppu.stat = 0x85
        self.ppu.bgp = 0xFC         # paleta de fundo
        self.ppu.obp0 = 0xFF
        self.ppu.obp1 = 0xFF

        # O som também sai ligado, com o volume alto e todos os canais
        # liberados: o jingle de abertura acabou de tocar.
        self.apu.escrever(0xFF26, 0xF1)
        self.apu.escrever(0xFF24, 0x77)
        self.apu.escrever(0xFF25, 0xF3)

    # Um quadro inteiro: 154 linhas de 456 dots cada.
    #
    # São 144 linhas visíveis mais 10 de intervalo — o V-Blank, a pausa em que
    # a TV de tubo levava o feixe de volta ao topo da tela. Sem imagem para
    # desenhar, é a janela em que o jogo pode mexer na memória de vídeo à
    # vontade, e é para ela que quase toda rotina de atualização é programada.
    CICLOS_POR_QUADRO = 70224

    def rodar_frame(self):
        """
        Executa até a PPU terminar um quadro, e devolve a imagem pronta.

        O teto de ciclos não é excesso de cuidado. Quando o jogo DESLIGA o vídeo
        — coisa que todos fazem em transições de tela, telas de carregamento e ao
        entrar em construções — a PPU para de avançar e o fim de quadro nunca
        chega. Sem o teto, este laço giraria para sempre e a janela congelaria em
        0 quadros por segundo. Foi exatamente o que aconteceu antes de ele
        existir.

        Com o vídeo desligado, o comportamento certo é este mesmo: deixar passar
        o tempo equivalente a um quadro e devolver a tela como está.
        """
        ppu = self.ppu
        ppu.frame_pronto = False
        # A folga de uma linha inteira evita cortar por um fio um quadro
        # legítimo que tenha demorado um pouco mais que o previsto.
        limite = self.cycles + self.CICLOS_POR_QUADRO + 456

        # As referências saem para variáveis locais antes do laço. Este teste
        # roda uma vez por instrução, centenas de milhares de vezes por quadro, e
        # em Python buscar um atributo custa bem mais do que ler uma local.
        cpu = self.cpu
        passo = cpu.step
        tick4 = self.tick4

        while not ppu.frame_pronto and self.cycles < limite:
            if cpu.halted and not cpu.stopped:
                # A CPU está dormindo à espera de uma interrupção, e enquanto
                # nenhuma chega a única coisa que acontece é o tempo passar.
                # Chamar `cpu.step()` só para ele chamar `tick4()` dobraria o
                # custo de cada M-cycle à toa.
                #
                # A economia é grande porque jogos passam muito mais tempo
                # dormindo do que executando: em Pokémon, mais de 90% dos passos
                # da CPU são HALT esperando o fim do quadro. Girar aqui dá
                # exatamente o mesmo resultado pela metade do preço.
                while (cpu.halted
                       and not (self.ie & self.if_ & 0x1F)
                       and not ppu.frame_pronto
                       and self.cycles < limite):
                    tick4()
            passo()

        return ppu.framebuffer
