"""
O cartucho, e o chip que faz jogos grandes caberem num console pequeno.

Aqui mora um problema de aritmética que a Nintendo teve de resolver em 1989. A
CPU do Game Boy usa endereços de 16 bits, e 16 bits comportam 65.536 valores.
Desses, o mapa de memória reserva 32 KB para o cartucho. Pokémon Vermelho tem
1 MB — trinta e duas vezes mais do que cabe.

A solução é o MBC, um chip que vai DENTRO do cartucho. A ideia é a de uma janela:
a CPU sempre enxerga 32 KB, mas o MBC decide QUAL pedaço do MB o cartucho vai
mostrar naquele momento.

    0000-3FFF   janela fixa       quase sempre o começo da ROM
    4000-7FFF   janela trocável   uma fatia de 16 KB, escolhida pelo jogo

O jogo troca de fatia quando precisa, e a rotina que faz a troca precisa estar
na janela fixa — senão ela sumiria no meio da própria execução.


ESCREVER NUMA MEMÓRIA SÓ DE LEITURA
-----------------------------------

O comando de troca chega por um caminho que surpreende: o jogo ESCREVE num
endereço da ROM. Escrever numa memória só de leitura deveria ser inútil, e é —
nenhum byte muda. Mas o MBC está ligado no mesmo barramento e ouve tudo, e usa
esses endereços e valores como sinalização.

    LD A, $05
    LD ($2000), A     ; não grava nada; manda o MBC trazer o banco 5

Não havia pinos sobrando para um canal de comando dedicado, e essa foi a saída.
Toda a configuração do cartucho — banco de ROM, banco de RAM, ligar a bateria,
travar o relógio — passa por escritas que não escrevem.


AS QUATRO GERAÇÕES
------------------

    SemMBC   32 KB, sem troca nenhuma. Tetris.
    MBC1     até 2 MB. O mais comum, e o que tem o bug mais famoso.
    MBC2     512 nibbles de RAM dentro do próprio chip. O esquisito.
    MBC3     até 2 MB, mais um relógio de tempo real com bateria.
    MBC5     até 8 MB, sem os bugs dos anteriores.

Cada um tem suas regras e suas manias, documentadas na sua classe.


A RAM COM BATERIA
-----------------

Cartuchos de jogos com save trazem RAM e uma pilha para mantê-la. É literalmente
isso: a partida sobrevive porque uma bateria de lítio continua alimentando um
chip de memória. Quando essa pilha acaba, vinte anos depois, o save some — e é
por isso que tantos cartuchos antigos "esqueceram" seus jogos.

Aqui essa RAM é gravada num arquivo `.sav` ao lado da ROM.
"""

# Quanto de RAM cada código do cabeçalho significa, em bytes.
RAM_SIZES = {0x00: 0, 0x01: 0x800, 0x02: 0x2000,
             0x03: 0x8000, 0x04: 0x20000, 0x05: 0x10000}

# O byte 0x147 do cabeçalho diz qual chip o cartucho traz.
TIPOS = {0x00: "ROM ONLY", 0x01: "MBC1", 0x02: "MBC1+RAM",
         0x03: "MBC1+RAM+BATTERY", 0x05: "MBC2", 0x06: "MBC2+BATTERY",
         0x08: "ROM+RAM", 0x09: "ROM+RAM+BATTERY",
         0x0F: "MBC3+TIMER+BATTERY", 0x10: "MBC3+TIMER+RAM+BATTERY",
         0x11: "MBC3", 0x12: "MBC3+RAM", 0x13: "MBC3+RAM+BATTERY",
         0x19: "MBC5", 0x1A: "MBC5+RAM", 0x1B: "MBC5+RAM+BATTERY",
         0x1C: "MBC5+RUMBLE", 0x1D: "MBC5+RUMBLE+RAM",
         0x1E: "MBC5+RUMBLE+RAM+BATTERY"}

# Quais tipos trazem pilha — e portanto guardam o save.
COM_BATERIA = {0x03, 0x06, 0x09, 0x0F, 0x10, 0x13, 0x1B, 0x1E}


# ======================================================================
# Os controladores
# ======================================================================
#
# Todo MBC mantém dois DESLOCAMENTOS, em bytes, dentro do arquivo da ROM:
#
#     off0 — some ao endereço para chegar à janela 0000-3FFF
#     off1 — some ao endereço para chegar à janela 4000-7FFF
#
# Com eles, ler a ROM vira uma soma e um acesso a `bytearray`, sem passar por
# duas chamadas de método a cada byte. Isso pesa porque a busca de instrução é a
# operação mais frequente que existe num emulador, e em Python uma chamada de
# função custa mais do que o acesso ao array em si.
#
# Os deslocamentos são recalculados apenas quando um banco muda — o caminho
# raro, que acontece algumas dezenas de vezes por quadro no máximo.
#
# Os métodos `read_rom` continuam existindo e fazendo a conta completa. Eles são
# o caminho de referência: mais lentos, mais legíveis, e usados quando alguém
# que não é o barramento precisa ler o cartucho.

class SemMBC:
    """
    Cartucho de 32 KB sem chip nenhum: a ROM inteira cabe no mapa de memória.

    É o caso do Tetris, do Dr. Mario e de boa parte dos primeiros jogos. Não há
    troca de banco porque não há o que trocar — tudo já está visível.
    """

    def __init__(self, cart):
        self.cart = cart
        self.off0 = 0
        self.off1 = 0        # 4000-7FFF cai direto em rom[addr]

    def read_rom(self, addr):
        rom = self.cart.rom
        return rom[addr] if addr < len(rom) else 0xFF

    def write_rom(self, addr, val):
        """Sem MBC não há ninguém escutando: a escrita simplesmente some."""
        pass

    def read_ram(self, addr):
        ram = self.cart.ram
        if not ram:
            return 0xFF
        return ram[(addr - 0xA000) % len(ram)]

    def write_ram(self, addr, val):
        ram = self.cart.ram
        if ram:
            ram[(addr - 0xA000) % len(ram)] = val


class MBC1:
    """
    O primeiro e mais comum: até 2 MB de ROM e 32 KB de RAM.

    As quatro faixas de escrita, e o que cada uma comanda:

        0000-1FFF   liga a RAM (valor com nibble baixo igual a 0x0A)
        2000-3FFF   os 5 bits baixos do banco de ROM
        4000-5FFF   2 bits extras: banco de RAM OU bits altos da ROM
        6000-7FFF   modo, que decide o significado dos 2 bits acima

    Ligar a RAM com um valor específico, e não com qualquer coisa, é proteção
    contra corrupção: quando a pilha acaba ou o cartucho é removido durante o
    uso, escritas aleatórias no barramento dificilmente acertam justo 0x0A.
    """

    def __init__(self, cart):
        self.cart = cart
        self.ram_ligada = False
        self.banco_baixo = 1          # nunca pode ser 0 — ver `write_rom`
        self.banco_alto = 0
        self.modo = 0
        # Quantos bancos a ROM tem, menos 1: vira uma máscara que descarta
        # pedidos de banco além do fim do arquivo, dando a volta em vez de ler
        # lixo. É o que o hardware faz.
        self.mascara_rom = max(1, len(cart.rom) // 0x4000) - 1
        self._atualizar_offsets()

    def _banco_rom(self):
        return (((self.banco_alto << 5) | self.banco_baixo) & self.mascara_rom)

    def _banco_janela0(self):
        # No modo avançado, até a janela "fixa" pode trocar de banco. É assim
        # que um cartucho de 1 MB alcança a segunda metade da ROM.
        return ((self.banco_alto << 5) & self.mascara_rom) if self.modo else 0

    def _banco_janela1(self):
        return self._banco_rom()

    def _atualizar_offsets(self):
        """Recalcula os deslocamentos das duas janelas. Só roda ao trocar banco."""
        limite = len(self.cart.rom) - 0x4000
        b0 = self._banco_janela0() * 0x4000
        b1 = self._banco_janela1() * 0x4000
        self.off0 = b0 if 0 <= b0 <= limite else 0
        # O -0x4000 embutido já desconta o começo da janela, para que o
        # barramento possa somar o endereço cru sem subtrair nada.
        self.off1 = (b1 - 0x4000) if 0 <= b1 <= limite else -0x4000

    def read_rom(self, addr):
        rom = self.cart.rom
        if addr < 0x4000:
            banco = ((self.banco_alto << 5) & self.mascara_rom) if self.modo else 0
            end = banco * 0x4000 + addr
        else:
            end = self._banco_rom() * 0x4000 + (addr - 0x4000)
        return rom[end] if end < len(rom) else 0xFF

    def write_rom(self, addr, val):
        """
        Um comando para o MBC. O endereço escolhe qual.

        O bug do banco 0 mora aqui, e é o mais famoso da família. Escrever 0 no
        seletor NÃO seleciona o banco 0: seleciona o 1. A intenção era evitar
        que o jogo colocasse o mesmo banco nas duas janelas por engano.

        O efeito colateral é que os bancos 0x20, 0x40 e 0x60 ficam
        INALCANÇÁVEIS: para chegar ao 0x20 seria preciso escrever 0 nos cinco
        bits baixos, e isso vira 1, resultando em 0x21. Cartuchos grandes
        simplesmente desperdiçam esses três bancos, ou repetem neles o conteúdo
        de outros.
        """
        if addr < 0x2000:
            self.ram_ligada = (val & 0x0F) == 0x0A
        elif addr < 0x4000:
            v = val & 0x1F
            self.banco_baixo = v if v else 1
        elif addr < 0x6000:
            self.banco_alto = val & 0x03
        else:
            self.modo = val & 0x01
        self._atualizar_offsets()

    def _end_ram(self, addr):
        ram = self.cart.ram
        banco = self.banco_alto if self.modo else 0
        return (banco * 0x2000 + (addr - 0xA000)) % len(ram)

    def read_ram(self, addr):
        if not self.ram_ligada or not self.cart.ram:
            return 0xFF
        return self.cart.ram[self._end_ram(addr)]

    def write_ram(self, addr, val):
        if not self.ram_ligada or not self.cart.ram:
            return
        self.cart.ram[self._end_ram(addr)] = val


class MBC2:
    """
    O esquisito da família: a RAM mora dentro do próprio chip, e é minúscula.

    São 512 posições de QUATRO bits — meio byte cada, o que dá 256 bytes úteis.
    Os quatro bits altos não existem fisicamente e leem sempre 1, daí o `| 0xF0`
    na leitura. Foi projetado para jogos que precisavam guardar pouca coisa,
    como uma tabela de recordes, sem o custo de um chip de RAM separado.

    A seleção de comando também é diferente: em vez de faixas de endereço, o
    MBC2 olha o BIT 8 do endereço. Com ele em 0, a escrita liga a RAM; com ele
    em 1, troca o banco de ROM.
    """

    def __init__(self, cart):
        self.cart = cart
        self.ram_ligada = False
        self.banco = 1
        self.mascara_rom = max(1, len(cart.rom) // 0x4000) - 1
        # O tamanho vem do chip, e não do cabeçalho: é sempre este.
        cart.ram = bytearray(512)
        self._atualizar_offsets()

    def _banco_janela0(self):
        return 0

    def _banco_janela1(self):
        return self.banco & self.mascara_rom

    def _atualizar_offsets(self):
        """Recalcula os deslocamentos das duas janelas. Só roda ao trocar banco."""
        limite = len(self.cart.rom) - 0x4000
        b0 = self._banco_janela0() * 0x4000
        b1 = self._banco_janela1() * 0x4000
        self.off0 = b0 if 0 <= b0 <= limite else 0
        self.off1 = (b1 - 0x4000) if 0 <= b1 <= limite else -0x4000

    def read_rom(self, addr):
        rom = self.cart.rom
        if addr < 0x4000:
            end = addr
        else:
            end = (self.banco & self.mascara_rom) * 0x4000 + (addr - 0x4000)
        return rom[end] if end < len(rom) else 0xFF

    def write_rom(self, addr, val):
        if addr >= 0x4000:
            return
        if addr & 0x0100:
            v = val & 0x0F
            self.banco = v if v else 1      # o mesmo bug do banco 0
            self._atualizar_offsets()
        else:
            self.ram_ligada = (val & 0x0F) == 0x0A

    def read_ram(self, addr):
        # `& 0x01FF` faz a RAM de 512 posições dar a volta: ela é espelhada por
        # toda a faixa A000-BFFF, porque não há fiação para distinguir mais.
        if not self.ram_ligada:
            return 0xFF
        return self.cart.ram[(addr - 0xA000) & 0x01FF] | 0xF0

    def write_ram(self, addr, val):
        if self.ram_ligada:
            self.cart.ram[(addr - 0xA000) & 0x01FF] = val & 0x0F


class MBC3:
    """
    Até 2 MB, e a grande novidade: um relógio de tempo real com bateria.

    É o chip que fez Pokémon Ouro e Prata saberem que era de manhã mesmo depois
    de o console passar a noite desligado. O relógio conta segundos, minutos,
    horas e dias, alimentado pela mesma pilha que guarda o save.

    O acesso a ele é engenhoso: em vez de novos endereços, o relógio se disfarça
    de banco de RAM. Selecionar os "bancos" 0x08 a 0x0C faz a faixa A000-BFFF
    devolver os registradores do relógio em vez da memória.
    """

    def __init__(self, cart, com_rtc=False):
        self.cart = cart
        self.ram_ligada = False
        self.banco_rom = 1
        self.banco_ram = 0
        self.mascara_rom = max(1, len(cart.rom) // 0x4000) - 1

        self.com_rtc = com_rtc
        # segundos, minutos, horas, dias (byte baixo), flags de dias
        self.rtc = [0, 0, 0, 0, 0]
        # Uma cópia congelada, para leitura. Ver `write_rom`.
        self.rtc_travado = [0, 0, 0, 0, 0]
        self.ultimo_latch = 0xFF
        self._sub = 0                 # T-cycles acumulados rumo ao próximo segundo
        self._atualizar_offsets()

    def _banco_janela0(self):
        return 0

    def _banco_janela1(self):
        return self.banco_rom & self.mascara_rom

    def _atualizar_offsets(self):
        """Recalcula os deslocamentos das duas janelas. Só roda ao trocar banco."""
        limite = len(self.cart.rom) - 0x4000
        b1 = self._banco_janela1() * 0x4000
        self.off0 = 0
        self.off1 = (b1 - 0x4000) if 0 <= b1 <= limite else -0x4000

    def tick_rtc(self, t):
        """
        Avança o relógio. Um segundo a cada 4.194.304 T-cycles.

        No cartucho real o relógio tem cristal próprio e anda mesmo com o
        console desligado. Aqui ele anda junto com a emulação — o que significa
        que rodar o emulador em turbo faz o tempo do jogo passar mais rápido.
        """
        if not self.com_rtc or (self.rtc[4] & 0x40):   # bit 6 = relógio parado
            return
        self._sub += t
        while self._sub >= 4194304:
            self._sub -= 4194304
            self._avancar_segundo()

    def _avancar_segundo(self):
        """
        Um segundo a mais, com o carregamento em cascata escrito à mão.

        Os `return` antecipados são a cascata: se os segundos não deram a volta,
        não há nada a fazer nos minutos. O contador de dias tem 9 bits, e o bit
        7 das flags marca que ele passou de 511 — um jogo pode detectar assim
        que o cartucho ficou guardado por mais de um ano e meio.
        """
        r = self.rtc
        r[0] = (r[0] + 1) % 60
        if r[0]:
            return
        r[1] = (r[1] + 1) % 60
        if r[1]:
            return
        r[2] = (r[2] + 1) % 24
        if r[2]:
            return
        dias = ((r[4] & 0x01) << 8) | r[3]
        dias += 1
        if dias > 0x1FF:
            dias = 0
            r[4] |= 0x80              # bit 7 = passou de 511 dias
        r[3] = dias & 0xFF
        r[4] = (r[4] & 0xFE) | ((dias >> 8) & 0x01)

    def read_rom(self, addr):
        rom = self.cart.rom
        if addr < 0x4000:
            end = addr
        else:
            end = (self.banco_rom & self.mascara_rom) * 0x4000 + (addr - 0x4000)
        return rom[end] if end < len(rom) else 0xFF

    def write_rom(self, addr, val):
        """
        Comandos do MBC3, incluindo o congelamento do relógio.

        A última faixa resolve um problema sutil de leitura. O relógio anda
        enquanto é lido, e ler os cinco registradores leva alguns ciclos — dá
        tempo de o minuto virar entre a leitura das horas e a dos minutos, e o
        jogo enxergaria um horário que nunca existiu.

        A solução é congelar: escrever 0 e depois 1 nesta faixa tira uma
        fotografia do relógio, e é essa cópia parada que a leitura devolve. O
        relógio de verdade continua andando por baixo.
        """
        if addr < 0x2000:
            self.ram_ligada = (val & 0x0F) == 0x0A
        elif addr < 0x4000:
            # Sete bits, até 128 bancos. O bug do banco 0 continua aqui.
            v = val & 0x7F
            self.banco_rom = v if v else 1
            self._atualizar_offsets()
        elif addr < 0x6000:
            self.banco_ram = val & 0x0F
        else:
            if self.ultimo_latch == 0x00 and val == 0x01:
                self.rtc_travado = list(self.rtc)
            self.ultimo_latch = val

    def read_ram(self, addr):
        if not self.ram_ligada:
            return 0xFF
        if self.com_rtc and 0x08 <= self.banco_ram <= 0x0C:
            return self.rtc_travado[self.banco_ram - 0x08]
        ram = self.cart.ram
        if not ram:
            return 0xFF
        return ram[(self.banco_ram * 0x2000 + (addr - 0xA000)) % len(ram)]

    def write_ram(self, addr, val):
        """
        Grava na RAM — ou acerta o relógio, conforme o banco selecionado.

        Escrever nos segundos zera o divisor interno. Faz sentido: quem acabou
        de acertar o relógio quer que o próximo segundo comece agora, e não que
        ele avance daqui a duzentos milissegundos porque o contador já estava
        pela metade.
        """
        if not self.ram_ligada:
            return
        if self.com_rtc and 0x08 <= self.banco_ram <= 0x0C:
            i = self.banco_ram - 0x08
            if i == 0:
                self._sub = 0
            # No registrador de flags só três bits existem: o bit 0 dos dias, o
            # 6 (parar o relógio) e o 7 (estouro).
            self.rtc[i] = val & (0xC1 if i == 4 else 0xFF)
            return
        ram = self.cart.ram
        if ram:
            ram[(self.banco_ram * 0x2000 + (addr - 0xA000)) % len(ram)] = val


class MBC5:
    """
    O último da linha, e o mais bem-comportado: até 8 MB de ROM e 128 KB de RAM.

    A grande diferença é o que ele NÃO tem: o bug do banco 0. Aqui o banco 0 é
    selecionável de verdade, e nenhum banco fica inalcançável. Também ganhou um
    bit 9 separado para o número do banco, o que permitiu passar dos 2 MB.

    Foi exigido para jogos de Game Boy Color, e algumas versões traziam um motor
    de vibração — o `rumble`, controlado por um bit que rouba espaço do seletor
    de banco de RAM.
    """

    def __init__(self, cart, com_rumble=False):
        self.cart = cart
        self.ram_ligada = False
        self.banco_rom = 1
        self.banco_ram = 0
        self.com_rumble = com_rumble
        self.rumble = False
        self.mascara_rom = max(1, len(cart.rom) // 0x4000) - 1
        self._atualizar_offsets()

    def _banco_janela0(self):
        return 0

    def _banco_janela1(self):
        return self.banco_rom & self.mascara_rom

    def _atualizar_offsets(self):
        """Recalcula os deslocamentos das duas janelas. Só roda ao trocar banco."""
        limite = len(self.cart.rom) - 0x4000
        b1 = self._banco_janela1() * 0x4000
        self.off0 = 0
        self.off1 = (b1 - 0x4000) if 0 <= b1 <= limite else -0x4000

    def read_rom(self, addr):
        rom = self.cart.rom
        if addr < 0x4000:
            end = addr
        else:
            end = (self.banco_rom & self.mascara_rom) * 0x4000 + (addr - 0x4000)
        return rom[end] if end < len(rom) else 0xFF

    def write_rom(self, addr, val):
        """
        O seletor de banco vem partido em dois endereços diferentes.

        Os 8 bits baixos em 2000-2FFF e o nono bit em 3000-3FFF. Trocar de banco
        exige, portanto, duas escritas — mas em troca não há bug de banco 0 e o
        alcance vai a 512 bancos.
        """
        if addr < 0x2000:
            self.ram_ligada = (val & 0x0F) == 0x0A
        elif addr < 0x3000:
            self.banco_rom = (self.banco_rom & 0x100) | val
            self._atualizar_offsets()
        elif addr < 0x4000:
            self.banco_rom = (self.banco_rom & 0xFF) | ((val & 1) << 8)
            self._atualizar_offsets()
        elif addr < 0x6000:
            if self.com_rumble:
                # Com motor de vibração, um bit do seletor vira o liga/desliga
                # dele — e a RAM fica limitada a 8 bancos em vez de 16.
                self.rumble = (val & 0x08) != 0
                self.banco_ram = val & 0x07
            else:
                self.banco_ram = val & 0x0F

    def read_ram(self, addr):
        ram = self.cart.ram
        if not self.ram_ligada or not ram:
            return 0xFF
        return ram[(self.banco_ram * 0x2000 + (addr - 0xA000)) % len(ram)]

    def write_ram(self, addr, val):
        ram = self.cart.ram
        if not self.ram_ligada or not ram:
            return
        ram[(self.banco_ram * 0x2000 + (addr - 0xA000)) % len(ram)] = val


# ======================================================================
# O cartucho
# ======================================================================
class Cartridge:
    """
    Um arquivo de ROM, lido e interpretado.

    Todo cartucho de Game Boy traz um cabeçalho padronizado entre 0x100 e 0x14F,
    com o nome do jogo, o tipo de chip, os tamanhos de ROM e de RAM e alguns
    checksums. É lendo esses bytes que o emulador descobre qual MBC construir.
    """

    def __init__(self, data):
        self.rom = bytearray(data)
        self.title = self._ler_titulo()
        self.cart_type = self.rom[0x147]

        # O tamanho é guardado como potência: 0 significa 32 KB, 1 significa
        # 64 KB, e assim por diante. Daí o deslocamento em vez de um número.
        self.rom_size = 32768 << self.rom[0x148] if self.rom[0x148] < 9 else len(self.rom)
        self.ram_size = RAM_SIZES.get(self.rom[0x149], 0)
        self.ram = bytearray(self.ram_size)
        self.tem_bateria = self.cart_type in COM_BATERIA
        self.tem_rtc = self.cart_type in (0x0F, 0x10)

        # O byte 0x143 diz o que o cartucho espera do console:
        #   0x80  aproveita recursos do Color, mas roda num DMG
        #   0xC0  SÓ Color — um DMG de verdade mostra a tela de cartucho
        #         incompatível e se recusa a executar
        self.flag_cgb = self.rom[0x143]
        self.so_cgb = self.flag_cgb == 0xC0
        self.suporta_cgb = self.flag_cgb in (0x80, 0xC0)

        self.mbc = self._criar_mbc()

    def _ler_titulo(self):
        """
        O nome do jogo, extraído de um campo que virou bagunça com o tempo.

        O título ocupa 0x134-0x143, e esse campo tem uma história. Cartuchos
        antigos usavam os 16 bytes inteiros; depois a Nintendo foi tomando o fim
        do campo para outras coisas — o byte 0x143, o último deles, virou a flag
        de compatibilidade com o Color.

        O resultado é que é comum encontrar bytes nulos no meio do título e lixo
        binário no fim. Cortar no primeiro nulo e manter só ASCII imprimível
        evita que caracteres de controle vazem para a barra de título da janela
        ou quebrem um simples `print`.
        """
        cru = bytes(self.rom[0x134:0x144])
        cru = cru.split(b"\x00", 1)[0]
        return "".join(chr(b) for b in cru if 32 <= b < 127).strip()

    def _criar_mbc(self):
        """Constrói o controlador que o cabeçalho pede."""
        t = self.cart_type
        if t in (0x00, 0x08, 0x09):
            return SemMBC(self)
        if 0x01 <= t <= 0x03:
            return MBC1(self)
        if t in (0x05, 0x06):
            return MBC2(self)
        if t in (0x0F, 0x10):
            return MBC3(self, com_rtc=True)
        if t in (0x11, 0x12, 0x13):
            return MBC3(self, com_rtc=False)
        if t in (0x19, 0x1A, 0x1B):
            return MBC5(self)
        if t in (0x1C, 0x1D, 0x1E):
            return MBC5(self, com_rumble=True)
        # Tipo desconhecido — ROMs caseiras às vezes deixam o byte errado.
        # Tentar o MBC1 dá mais chance de funcionar do que recusar de saída.
        return MBC1(self)

    # ------------------------------------------------------------------
    @classmethod
    def from_file(cls, path):
        """Carrega um arquivo `.gb` inteiro para a memória."""
        with open(path, "rb") as f:
            return cls(f.read())

    def tipo_nome(self):
        return TIPOS.get(self.cart_type, f"desconhecido (0x{self.cart_type:02X})")

    def compatibilidade(self):
        if self.so_cgb:
            return "só Game Boy Color"
        if self.suporta_cgb:
            return "DMG + recursos de Color"
        return "Game Boy (DMG)"

    def header_checksum_ok(self):
        """
        Confere o checksum do cabeçalho, do jeito que a ROM de boot conferia.

        A conta é essa mesma: começar em zero e, para cada byte do cabeçalho,
        subtrair o byte e mais 1. No console real, um cartucho que falhasse aqui
        simplesmente não era executado — a ROM de boot travava a tela no
        logotipo.

        Este emulador não recusa nada por causa disso. ROMs de teste caseiras
        costumam ter o checksum errado e são justamente as mais interessantes de
        rodar.
        """
        x = 0
        for i in range(0x134, 0x14D):
            x = (x - self.rom[i] - 1) & 0xFF
        return x == self.rom[0x14D]

    # ------------------------------------------------------------------
    # O que o barramento chama
    # ------------------------------------------------------------------
    def read_rom(self, addr):
        return self.mbc.read_rom(addr)

    def write_rom(self, addr, val):
        self.mbc.write_rom(addr, val)

    def read_ram(self, addr):
        return self.mbc.read_ram(addr)

    def write_ram(self, addr, val):
        self.mbc.write_ram(addr, val)

    def tick(self, t):
        """Só o MBC3 tem relógio; os outros não têm o que fazer com o tempo."""
        if isinstance(self.mbc, MBC3):
            self.mbc.tick_rtc(t)

    # ------------------------------------------------------------------
    # O save
    # ------------------------------------------------------------------
    def salvar_ram(self, path):
        """
        Grava a RAM da bateria num arquivo `.sav`.

        É o equivalente digital da pilha do cartucho: sem isso, fechar o
        emulador apagaria a partida. O formato é a memória crua, sem cabeçalho
        nenhum, o que o torna compatível com praticamente todos os emuladores.
        """
        if self.tem_bateria and self.ram:
            with open(path, "wb") as f:
                f.write(self.ram)

    def carregar_ram(self, path):
        """
        Lê o `.sav` de volta, se existir.

        O recorte nos dois lados protege contra um arquivo de tamanho diferente
        do esperado — de outro emulador, ou de uma versão do jogo com mais RAM.
        Melhor carregar o que couber do que recusar o save inteiro.
        """
        import os
        if self.tem_bateria and self.ram and os.path.exists(path):
            with open(path, "rb") as f:
                dados = f.read()
            self.ram[:len(dados)] = dados[:len(self.ram)]
