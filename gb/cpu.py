"""
O processador Sharp SM83 — o chip que executa o jogo.

Um processador faz a mesma coisa a vida inteira, num laço que nunca para:

    1. buscar      — ler da memória o byte apontado pelo PC
    2. decodificar — descobrir qual instrução aquele byte representa
    3. executar    — fazer o que a instrução manda
    4. repetir

O laço está em `step()`, no fim deste arquivo, e cabe em vinte linhas. Todo o
resto do módulo existe para dar conta dos detalhes: como cada acesso à memória
custa tempo, o que acontece quando um chip pede socorro no meio da execução, e
alguns comportamentos do chip original que parecem defeito e que os jogos usam
de propósito.

O SM83 é primo do Z80 e do 8080, sem ser nenhum dos dois. Roda a 4.194.304 Hz —
cerca de 4 MHz, umas mil vezes mais devagar que um celular de hoje.


PRECISÃO DE CICLO, E POR QUE ELA IMPORTA
----------------------------------------

Emular "o que a instrução faz" é a parte fácil. A parte difícil é emular QUANDO
ela faz.

O Game Boy não tem sistema operacional nem placa de vídeo que se vire sozinha.
Efeitos gráficos famosos funcionam porque o jogo conta ciclos: ele sabe que a
PPU leva 456 T-cycles para desenhar uma linha da tela e programa a mudança de
paleta para o instante exato entre uma linha e a próxima. Errar por um M-cycle
transforma um efeito de água ondulando numa tela tremendo.

A regra que dá essa precisão é simples e vale sem exceção:

    todo acesso ao barramento custa exatamente 1 M-cycle (4 T-cycles),
    e o resto do console avança ANTES de o acesso acontecer.

É por isso que `read8` chama `bus.tick4()` antes de ler, e não depois. No chip
real o dado só aparece no último T-cycle do M-cycle; adiantar o resto do sistema
reproduz essa ordem. Uma instrução que lê três bytes da memória avança o mundo
três vezes, no meio da própria execução — e a PPU, o timer e o som enxergam
esses avanços intercalados, como no hardware.
"""

from .constants import *
from .registradores import criar_reg16

# Erro levantado quando a CPU encontra um byte que não corresponde a instrução
# nenhuma. Ver `opcode_invalido` em `opcodes.py`.
UnknownOpcode = Exception

# Para onde a CPU pula ao atender cada interrupção, na ordem de prioridade. O
# índice é o número do bit no registrador IF: bit 0 é V-Blank e tem a maior
# prioridade, bit 4 é o joypad e tem a menor.
#
#   0x40  V-Blank  — a tela terminou de ser desenhada
#   0x48  STAT     — a PPU chegou num ponto que o jogo pediu para vigiar
#   0x50  Timer    — o contador do timer estourou
#   0x58  Serial   — a transferência pelo cabo terminou
#   0x60  Joypad   — algum botão foi pressionado
#
# Os endereços são de 8 em 8 porque cada rotina de tratamento tinha 8 bytes
# reservados. Não cabe muita coisa em 8 bytes: na prática o jogo põe ali um
# salto para a rotina de verdade.
VETORES = (0x40, 0x48, 0x50, 0x58, 0x60)


class CPU:
    def __init__(self, bus=None, reg16=None):
        # O `bus` é opcional só para que os testes possam examinar o banco de
        # registradores isoladamente. Uma CPU sem barramento não executa nada:
        # ela não teria de onde buscar as instruções.

        # ------------------------------------------------------------------
        # O banco de registradores
        # ------------------------------------------------------------------
        # Doze bytes crus, e duas maneiras de olhar para eles: como 8
        # registradores de 8 bits (`reg8`) e como 6 pares de 16 bits (`reg16`).
        # Não são duas cópias — é a MESMA memória vista de dois jeitos. Escrever
        # em `reg8[B]` muda o valor lido em `reg16[BC]`, exatamente como no chip.
        #
        # Fazer assim evita o trabalho de manter duas representações em
        # sincronia, que é uma fonte clássica de bug: basta esquecer de
        # atualizar uma delas em um lugar.
        #
        # Como a visão de 16 bits é construída depende do interpretador, por
        # razões de desempenho medidas — ver `registradores.py`.
        self.reg_buffer = bytearray(12)
        self.reg8 = self.reg_buffer
        self.reg16 = criar_reg16(self.reg_buffer, forcar=reg16)

        self.bus = bus

        # ------------------------------------------------------------------
        # Interrupções
        # ------------------------------------------------------------------
        # `ime` é a chave geral: com ela desligada, nenhuma interrupção é
        # atendida, por mais que o hardware insista.
        self.ime = False

        # A instrução EI liga a chave, mas com um M-cycle de atraso: ela só
        # passa a valer depois que a PRÓXIMA instrução terminar. Este campo
        # guarda esse "vai ligar daqui a pouco". O atraso é do chip real, e o
        # padrão `EI; RET` no fim de uma rotina depende dele.
        self.ime_pending = False

        # ------------------------------------------------------------------
        # Estados de baixo consumo
        # ------------------------------------------------------------------
        # HALT desliga a CPU e deixa o resto do console andando. É assim que os
        # jogos economizam pilha: em vez de ficar num laço vazio esperando a
        # tela terminar, mandam HALT e a interrupção de V-Blank acorda a CPU. Um
        # jogo típico passa a maior parte do tempo em HALT.
        self.halted = False

        # STOP congela o console inteiro, inclusive a tela. Só o joypad acorda.
        self.stopped = False

        # Um defeito do chip original, reproduzido de propósito. Ver `fetch8`.
        self.halt_bug = False

        # As tabelas que traduzem byte em função. O import fica aqui dentro, e
        # não no topo do arquivo, porque `gb.opcodes` importa `gb.cpu`: fazer os
        # dois no topo criaria um ciclo de importação que o Python recusa.
        # Adiar até a construção do objeto quebra o ciclo, porque a essa altura
        # ambos os módulos já terminaram de carregar.
        from .opcodes import opcode, opcodeCB
        self.opcode = opcode
        self.opcodeCB = opcodeCB

    # ------------------------------------------------------------------
    # Estado inicial
    # ------------------------------------------------------------------
    def reset_pos_boot(self, cart=None):
        """
        Coloca os registradores como estariam logo após a ROM de boot terminar.

        Todo Game Boy tem uma ROM de 256 bytes gravada de fábrica: é ela que
        mostra o logotipo da Nintendo descendo, toca o som de abertura e confere
        se o cartucho é legítimo. Ao terminar, ela entrega o controle ao jogo com
        os registradores em valores conhecidos.

        Este emulador pula a animação e começa direto do resultado. Os valores
        abaixo são os medidos num DMG real; jogos os assumem, e alguns até
        dependem disso — dá para descobrir em qual modelo de console se está
        rodando examinando o que veio em A.

        O REGISTRADOR F É O CASO INTERESSANTE

        Ele não tem valor fixo, e o motivo é bonito: a última coisa que a ROM de
        boot faz antes de entregar o controle é conferir o checksum do cabeçalho
        do cartucho. Essa comparação deixa rastro nas flags, e o rastro chega até
        o jogo.

        Se o checksum guardado em 0x14D for zero, a comparação não gera "vai um"
        nem meio-carry, e as duas flags saem limpas. Qualquer outro valor liga as
        duas. Ou seja: um byte do cartucho decide o estado de dois bits do
        processador, e isso é observável.

        Nenhum jogo comercial depende disso. A ROM `boot_regs-dmgABC` da Mooneye
        depende, e é justo aí que a diferença entre "aproximado" e "correto"
        aparece.
        """
        self.reg8[A] = 0x01
        self.reg8[B] = 0x00; self.reg8[C] = 0x13
        self.reg8[D] = 0x00; self.reg8[E] = 0xD8
        self.reg8[H] = 0x01; self.reg8[L] = 0x4D

        # Z sempre ligado; N sempre desligado. H e C dependem do cartucho.
        checksum_zerado = cart is not None and len(cart.rom) > 0x14D \
            and cart.rom[0x14D] == 0x00
        self.reg8[F] = 0x80 if checksum_zerado else 0xB0

        self.reg16[SP] = 0xFFFE       # a pilha começa no topo da memória
        self.reg16[PC] = 0x0100       # e o jogo sempre começa em 0x0100
        self.ime = False
        self.ime_pending = False
        self.halted = False
        self.stopped = False
        self.halt_bug = False

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------
    def getFlag(self, flag):
        """Devolve True se a flag estiver ligada. `flag` é uma das FLAG_*."""
        return (self.reg8[F] & flag) != 0

    def setFlag(self, flag, value):
        """Liga ou desliga uma flag, sem tocar nas outras três."""
        if value:
            self.reg8[F] |= flag        # liga o bit
        else:
            self.reg8[F] &= ~flag       # desliga o bit

    def write_af(self, value):
        """
        Escreve no par AF, respeitando um detalhe físico do chip.

        Os quatro bits de baixo de F não existem: não há transistor ali. Escrever
        1 neles não guarda nada, e lê-los devolve sempre 0. `& 0xFFF0` zera esses
        quatro bits antes de guardar.

        Sem isso, um `PUSH AF` seguido de `POP AF` devolveria um valor diferente
        do que o console devolveria — e existe teste que confere exatamente isso.
        """
        self.reg16[AF] = value & 0xFFF0

    # ------------------------------------------------------------------
    # Acesso ao barramento
    # ------------------------------------------------------------------
    # Os três métodos abaixo são o único caminho da CPU para o mundo. Todos
    # gastam 1 M-cycle, e todos avançam o resto do console ANTES de fazer o
    # acesso — a ordem que reproduz o hardware, explicada no topo do arquivo.

    def read8(self, addr):
        """Lê um byte. Custa 1 M-cycle."""
        self.bus.tick4()
        return self.bus.bus_read(addr & 0xFFFF)

    def write8(self, addr, value):
        """Escreve um byte. Custa 1 M-cycle."""
        self.bus.tick4()
        self.bus.bus_write(addr & 0xFFFF, value & 0xFF)

    def fetch8(self):
        """
        Lê o byte apontado pelo PC e avança o ponteiro.

        É a operação mais frequente que existe no emulador: toda instrução começa
        por aqui, e as maiores fazem isso quatro vezes. Por isso o caminho comum
        — buscar da ROM do cartucho — está escrito à mão em vez de passar por
        `read8` → `bus_read` → MBC. São três chamadas de método economizadas para
        o que, no fim, é uma soma e um acesso a um `bytearray`.

        Endereços fora da ROM caem no caminho normal. Código rodando fora da ROM
        existe (rotinas copiadas para a memória rápida, por exemplo), mas é raro
        o bastante para não valer duplicar aqui a lógica inteira do barramento.
        """
        bus = self.bus
        bus.tick4()

        pc = self.reg16[PC]
        if pc < 0x8000 and not bus.dma.ativo:
            # `off0` e `off1` são deslocamentos que o cartucho mantém
            # atualizados para indicar qual banco está visível em cada metade da
            # janela de ROM. Somá-los ao endereço dá a posição real dentro do
            # arquivo. Ver `cartridge.py`.
            mbc = bus.mbc
            i = pc + (mbc.off0 if pc < 0x4000 else mbc.off1)
            data = bus.rom[i] if i < bus.rom_len else 0xFF
        else:
            data = bus.bus_read(pc)

        if self.halt_bug:
            # O bug do HALT, reproduzido fielmente.
            #
            # No chip original, quando um HALT é executado com as interrupções
            # desligadas e há uma interrupção pendente, o processador lê o
            # próximo byte mas ESQUECE de avançar o PC. A instrução seguinte
            # acaba executada duas vezes.
            #
            # É um defeito de verdade, e está no manual da Nintendo como algo a
            # evitar. Mas é previsível, e ROMs de teste o exercitam — a
            # `halt_bug.gb` reprova qualquer emulador que não o reproduza.
            self.halt_bug = False
        else:
            self.reg16[PC] = (pc + 1) & 0xFFFF
        return data

    def fetch16(self):
        """
        Lê dois bytes seguidos e monta um valor de 16 bits. Custa 2 M-cycles.

        O byte de baixo vem primeiro. Isso se chama little-endian, e é a
        convenção do SM83: `LD HL, $1234` fica gravado na ROM como 21 34 12.
        Parece trocado ao ler um dump de memória, e é assim mesmo.
        """
        low = self.fetch8()
        high = self.fetch8()
        return (high << 8) | low

    # ------------------------------------------------------------------
    # A pilha
    # ------------------------------------------------------------------
    # A pilha é uma região de memória onde a CPU guarda coisas temporariamente —
    # principalmente o endereço de retorno de uma sub-rotina. O registrador SP
    # aponta para o topo.
    #
    # Ela cresce para BAIXO: empilhar diminui o SP. O motivo é prático — a pilha
    # começa no fim da memória e cresce em direção aos dados, que crescem no
    # sentido contrário, então as duas só colidem quando a memória acabou mesmo.

    def bug_oam(self, endereco):
        """
        Dispara a corrupção da OAM quando o ponteiro da pilha passa por FEXX.

        Outro defeito do console original. A região FE00-FEFF guarda a tabela de
        sprites (a OAM), e o chip tem uma falha elétrica ali: mexer no ponteiro
        de 16 em 16 bits enquanto ele aponta para essa faixa embaralha uma linha
        inteira da tabela.

        Nenhum jogo faz isso de propósito — é receita para bug gráfico. Mas a ROM
        de teste `oam_bug.gb` faz, e conferir esse comportamento é uma das formas
        de medir quão fiel um emulador é. Os detalhes de como a corrupção
        embaralha os bytes estão em `ppu.py`.
        """
        if 0xFE00 <= endereco <= 0xFEFF:
            self.bus.ppu.corrupcao_oam_escrita()

    def push16(self, value):
        """Empilha um valor de 16 bits: primeiro o byte alto, depois o baixo."""
        sp = self.reg16[SP]
        self.bug_oam(sp)
        sp = (sp - 1) & 0xFFFF
        self.write8(sp, (value >> 8) & 0xFF)
        self.bug_oam(sp)
        sp = (sp - 1) & 0xFFFF
        self.write8(sp, value & 0xFF)
        self.reg16[SP] = sp

    def pop16(self):
        """
        Desempilha um valor de 16 bits.

        Aqui mora um detalhe do bug da OAM que custou várias tentativas para
        acertar. O POP dispara a corrupção UMA vez só, no M-cycle da primeira
        leitura, e o endereço que aparece no barramento naquele instante é o JÁ
        INCREMENTADO (SP+1), não o SP.

        As duas alternativas erradas falham em testes diferentes: disparar nos
        dois M-cycles faz a ROM `3-non_causes` acusar corrupção onde não deveria
        haver; usar o SP sem incrementar faz a `2-causes` não detectar a sequência
        `LD SP,$FDFF : POP BC`, que corrompe de verdade.
        """
        sp = self.reg16[SP]
        low = self.read8(sp)

        if 0xFE00 <= (sp + 1) & 0xFFFF <= 0xFEFF:
            self.bus.ppu.corrupcao_oam_leitura_incremento()

        high = self.read8((sp + 1) & 0xFFFF)
        self.reg16[SP] = (sp + 2) & 0xFFFF
        return (high << 8) | low

    # ------------------------------------------------------------------
    # Atendimento de interrupção
    # ------------------------------------------------------------------
    def servir_interrupcao(self):
        """
        Larga o que estava fazendo e pula para a rotina de tratamento.

        Custa 5 M-cycles (20 T-cycles), e o que acontece em cada um importa:

            M1, M2 : dois ciclos internos, em que a CPU "percebe" o pedido
            M3     : SP--, escreve na pilha o byte ALTO do PC
            M4     : SP--, escreve o byte BAIXO  ← o IE é lido de novo aqui
            M5     : ciclo interno; o PC recebe o endereço da rotina

        A ordem esconde uma esquisitice aproveitável. Como o endereço de retorno
        é empilhado ANTES de o destino ser decidido, uma pilha posicionada em
        0xFFFE/0xFFFF faz o próprio empilhamento sobrescrever o registrador IE —
        que é justamente quem diz quais interrupções estão habilitadas. O pedido
        pode então ser cancelado por si mesmo, e a CPU pula para 0x0000.

        Parece absurdo, e é. Mas o hardware faz isso, e há teste que confere.
        """
        self.ime = False              # atender desliga a chave geral

        self.bus.tick4()      # M1 — ciclo interno
        self.bus.tick4()      # M2 — ciclo interno

        pc = self.reg16[PC]
        sp = (self.reg16[SP] - 1) & 0xFFFF
        self.write8(sp, (pc >> 8) & 0xFF)     # M3 — byte alto do retorno

        # Só agora o destino é decidido, com o valor ATUAL de IE e IF. Se o
        # empilhamento acima tiver mexido no IE, é este `pendentes` que muda.
        pendentes = self.bus.ie & self.bus.if_ & 0x1F

        sp = (sp - 1) & 0xFFFF
        self.write8(sp, pc & 0xFF)            # M4 — byte baixo do retorno
        self.reg16[SP] = sp

        if pendentes == 0:
            self.reg16[PC] = 0x0000
        else:
            # Entre várias interrupções pendentes, vence a de menor número de
            # bit. `pendentes & -pendentes` isola o bit ligado mais à direita —
            # um truque clássico, que funciona pela forma como números negativos
            # são representados — e `.bit_length() - 1` converte esse bit em seu
            # índice. Para 0b10100, o resultado é 2.
            bit = (pendentes & -pendentes).bit_length() - 1
            self.bus.if_ &= ~(1 << bit)       # marca só esta como atendida
            self.reg16[PC] = VETORES[bit]

        self.bus.tick4()      # M5 — ciclo interno

    # ------------------------------------------------------------------
    # O laço principal
    # ------------------------------------------------------------------
    def step(self):
        """
        Executa um passo: uma instrução, um ciclo parado, ou uma interrupção.

        Esta função é chamada milhões de vezes por segundo e é o centro de tudo.
        A ordem das verificações não é arbitrária — ela reproduz a ordem em que o
        chip real toma as mesmas decisões.
        """
        # Um pedido de interrupção existe quando o hardware sinalizou (IF) E o
        # jogo declarou interesse (IE). Os dois registradores têm 5 bits úteis.
        pendentes = self.bus.ie & self.bus.if_ & 0x1F

        # --- Sair do HALT ---
        # Detalhe importante e fácil de errar: o HALT termina assim que houver
        # QUALQUER interrupção pendente, mesmo com a chave geral desligada. O
        # `ime` decide apenas se a rotina de tratamento será chamada — não se a
        # CPU acorda. Trocar essas duas coisas trava jogos que usam HALT com as
        # interrupções desligadas de propósito.
        if self.halted:
            if pendentes:
                self.halted = False
            else:
                self.bus.tick4()      # dormindo, mas o tempo passa
                return

        # --- STOP ---
        if self.stopped:
            if self.bus.if_ & 0x10:   # bit 4 = joypad, o único que acorda
                self.stopped = False
            else:
                self.bus.tick4()
                return

        # --- Atender uma interrupção, se houver ---
        if self.ime and pendentes:
            self.ime_pending = False
            self.servir_interrupcao()
            return

        # --- O atraso do EI ---
        # A instrução EI marcou `ime_pending` e permitiu que UMA instrução
        # rodasse antes de a chave ligar de fato. Se o fluxo chegou até aqui,
        # essa instrução já passou, e agora a chave liga.
        if self.ime_pending:
            self.ime_pending = False
            self.ime = True

        # --- Buscar, decodificar, executar ---
        opc = self.fetch8()
        if opc == 0xCB:
            # 0xCB não é uma instrução: é um aviso de que a instrução de verdade
            # está no PRÓXIMO byte, e deve ser procurada na segunda tabela.
            #
            # O motivo é aritmético. Um byte comporta 256 valores, e o SM83
            # precisa de mais que isso. Reservar um byte como prefixo dobra o
            # espaço disponível: 255 instruções diretas, mais 256 acessíveis pelo
            # prefixo. O preço é que as prefixadas custam 1 M-cycle a mais, já
            # que exigem duas buscas.
            self.opcodeCB[self.fetch8()](self)
        else:
            # `self.opcode` é uma lista de 256 funções, indexada pelo byte lido.
            # Decodificar é isso: um acesso a uma lista. Nada de cadeia de `if`.
            self.opcode[opc](self)
