import pygame
  
class CPU:
    __slots__ = ['regs', 'PC', 'SP', 'IME', 'ime_scheduled', 'HALT', 'HALT_BUG']

    def __init__(self):
        self.regs = bytearray(8) # 0:B, 1:C, 2:D, 3:E, 4:H, 5:L, 6:F, 7:A
        self.PC = 0x0100
        self.SP = 0xFFFE
        self.IME = False
        self.ime_scheduled = False
        self.HALT = False
        self.HALT_BUG = False

class GameBoy:
    __slots__ = ['CPU', 'Memory', 'cart_rom']
    COLORS = [
        (224, 248, 208), # 00: Branco (White)
        (136, 192, 112), # 01: Cinza Claro (Light Gray)
        (52, 104, 86),   # 10: Cinza Escuro (Dark Gray)
        (8, 24, 32)      # 11: Preto (Black)
    ]

    def __init__(self):
        self.CPU = CPU()
        self.Memory = bytearray(65536)
        self.cart_rom = bytearray(0)

    def load_rom(self, filename):
        print(f"Carregando ROM: {filename}...")
        try:
            with open(filename, "rb") as f:
                data = f.read()
                
            self.cart_rom = data
            limit = min(len(data), 0x8000)
            self.Memory[:limit] = data[:limit]
            
            # --- BIOS BYPASS COMPLETO ---
            cpu = self.CPU
            cpu.PC = 0x0100 
            cpu.SP = 0xFFFE 
            
            # 1. Registradores da CPU (Estado pós-BIOS)
            cpu.regs[7] = 0x01; cpu.regs[6] = 0xB0 # AF
            cpu.regs[0] = 0x00; cpu.regs[1] = 0x13 # BC
            cpu.regs[2] = 0x00; cpu.regs[3] = 0xD8 # DE
            cpu.regs[4] = 0x01; cpu.regs[5] = 0x4D # HL
            
            # 2. Configuração de Vídeo (CRUCIAL PARA VER IMAGEM!)
            # LCDC: Liga o LCD e o Background (0x91 = 10010001)
            self.Memory[0xFF40] = 0x91 
            
            # BGP (Paleta): Define as cores 0, 1, 2, 3 (0xFC = 11100100)
            # Sem isso, tudo fica da mesma cor (verde/branco)!
            self.Memory[0xFF47] = 0xFC 
            
            # OBP0/OBP1 (Paletas de Sprites)
            self.Memory[0xFF48] = 0xFF
            self.Memory[0xFF49] = 0xFF
            self.Memory[0xFF00] = 0xCF
            
            print("ROM carregada e CPU resetada com sucesso!")
            
        except FileNotFoundError:
            print("Erro: Arquivo não encontrado.")
            exit()

    def run(self):
        cpu = self.CPU
        mem = self.Memory
        regs = cpu.regs
        pc = cpu.PC
        sp = cpu.SP
        ime = cpu.IME
        ime_scheduled = cpu.ime_scheduled
        halted = cpu.HALT
        halt_bug = cpu.HALT_BUG

        # Variáveis locais para o Timer (precisão e velocidade)
        div_counter = 0
        tima_counter = 0

        # Variáveis locais da PPU

        ######
        mode = 2 # Começa em OAM Search
        scanline_counter = 0
        screen_surf = pygame.Surface((160, 144))
        ######

        pygame.init()
        # Janela escalada 3x para ficar visível (160x144 -> 480x432)
        SCALE = 3
        window = pygame.display.set_mode((160 * SCALE, 144 * SCALE))
        pygame.display.set_caption("GB-Py | Tetris a Alta Velocidade")
        clock = pygame.time.Clock()

        cycles_since_last_frame = 0
        CYCLES_PER_FRAME = 70224 # 4194304 / 60

        print("Iniciando Emulação...")

        def dma_transfer(value):
            # O valor escrito indica o endereço base (ex: 0xC1 -> 0xC100)
            source = value << 8
            # Copia 160 bytes (0xA0) para a OAM (0xFE00)

            if source > 0xF100: 
                return

            mem[0xFE00 : 0xFEA0] = mem[source : source + 160]
            # Nota: Na precisão real, isso demora 160 microsegundos e bloqueia a CPU.
            # Para agora, fazer instantâneo funciona.

        def write_byte(addr, value):
            # 1. ROM (0x0000 - 0x7FFF) - Read Only
            if addr < 0x8000:
                bank_number = value & 0x1F # Pega os 5 bits inferiores
                if bank_number == 0: bank_number = 1 # Banco 0 não pode ser selecionado aqui, vira 1

                start_addr_in_cart = bank_number * 0x4000
                    
                # Verifica se o banco existe no arquivo carregado
                if start_addr_in_cart < len(self.cart_rom):
                    # Copia 16KB do cartucho para a área de ROM trocável (4000-7FFF)
                    # Slice assignment em Python é muito rápido!
                    mem[0x4000:0x8000] = self.cart_rom[start_addr_in_cart : start_addr_in_cart + 0x4000]
                    # print(f"Banco trocado para: {bank_number}") # Debug se precisar
                return

            # 2. VRAM (0x8000 - 0x9FFF)
            elif addr < 0xA000:
                mem[addr] = value
                return

            # 3. External RAM (0xA000 - 0xBFFF)
            elif addr < 0xC000:
                mem[addr] = value
                return

            # 4. Work RAM (0xC000 - 0xDFFF) e Echo RAM (0xE000 - 0xFE00)
            elif addr < 0xFE00:
                mem[addr] = value
                # Espelhamento (Echo RAM)
                if addr < 0xE000: mem[addr + 0x2000] = value
                else:             mem[addr - 0x2000] = value
                return

            # 5. OAM (0xFE00 - 0xFE9F)
            elif addr < 0xFEA0:
                mem[addr] = value
                return

            # 6. Unusable (0xFEA0 - 0xFEFF)
            elif addr < 0xFF00:
                return 

            # 7. IO Registers (0xFF00 - 0xFF7F) - AQUI ESTÁ A CORREÇÃO!
            elif addr < 0xFF80:
                
                # JOYPAD (0xFF00): Apenas bits 4 e 5 são graváveis (seletores)
                # Os bits 0-3 são Read-Only (estado dos botões)
                if addr == 0xFF00:
                    current = mem[0xFF00]
                    mem[0xFF00] = (current & 0x0F) | (value & 0xF0)
                    return

                # DIV (0xFF04): Escrita sempre zera o registrador
                elif addr == 0xFF04:
                    mem[0xFF04] = 0
                    # Dica: Resetar o contador interno global do timer aqui seria ideal para precisão
                    return

                # LY (0xFF44): Read Only / Reset. Escrita zera o contador.
                elif addr == 0xFF44:
                    mem[0xFF44] = 0
                    return

                # DMA (0xFF46): Inicia transferência
                elif addr == 0xFF46:
                    dma_transfer(value)
                    mem[addr] = value # O valor fica salvo no registrador
                    return
                
                # STAT (0xFF41): Bits 0-2 são Read-Only (Status da PPU)
                # O jogo só pode escrever nos bits 3-6 (Interrupções)
                elif addr == 0xFF41:
                    current = mem[0xFF41]
                    # Mantém bits 0,1,2 originais e aceita a escrita no resto
                    mem[0xFF41] = (value & 0xF8) | (current & 0x07)
                    return

                # Padrão para outros IOs
                mem[addr] = value
                return

            # 8. High RAM (0xFF80 - 0xFFFE) e IE (0xFFFF)
            else:
                mem[addr] = value

        def ppu_update(cycles, interrupt_mem_ref):
            nonlocal mode
            nonlocal scanline_counter
            
            # Gerenciamento de Modos LCD (State Machine)
            
            # LCD Control (FF40) - Se bit 7 estiver 0, LCD está desligado
            lcdc = mem[0xFF40]
            if not (lcdc & 0x80):
                mem[0xFF44] = 0 # LY = 0
                scanline_counter = 0
                mode = 0 # Força HBlank/Stop
                return False # Não desenhou frame novo

            scanline_counter += cycles
            
            # Constantes de Timing (Total 456 ciclos por linha)
            # Mode 2 (OAM): ~80 ciclos
            # Mode 3 (Transfer/FIFO): ~172 ciclos
            # Mode 0 (HBlank): ~204 ciclos
            
            req_int = False # Flag para saber se pedimos interrupção LCD STAT

            # --- MÁQUINA DE ESTADOS DO PPU ---
            
            if mode == 2: # OAM Search
                if scanline_counter >= 80:
                    scanline_counter -= 80
                    mode = 3
                    
            elif mode == 3: # Pixel Transfer (Onde o FIFO trabalha)
                if scanline_counter >= 172:
                    scanline_counter -= 172
                    mode = 0
                    
                    # Fim do Mode 3: A linha inteira foi desenhada.
                    # Renderiza a linha atual (Scanline)
                    render_scanline()
                    
            elif mode == 0: # H-Blank
                if scanline_counter >= 204:
                    scanline_counter -= 204
                    
                    # Fim da linha, incrementa LY (0xFF44)
                    current_ly = mem[0xFF44]
                    current_ly += 1
                    
                    if current_ly >= 144:
                        mode = 1
                        interrupt_mem_ref[0xFF0F] |= 0x01 # VBlank Interrupt Request
                        return True # Frame novo desenhado
                    else:
                        mode = 2 # Volta para OAM Search da próxima linha

                    if current_ly > 255:
                        current_ly = 0
                        
                    mem[0xFF44] = current_ly

            elif mode == 1: # V-Blank
                if scanline_counter >= 456:
                    scanline_counter -= 456
                    
                    current_ly = mem[0xFF44]
                    current_ly += 1
                    
                    if current_ly > 153:
                        # Fim do V-Blank, volta para o topo da tela
                        mem[0xFF44] = 0
                        mode = 2
                    else:
                        mem[0xFF44] = current_ly

            current_stat = mem[0xFF41]
            mem[0xFF41] = (current_stat & 0xFC) | (mode & 0x03)
                        
            return False
        
        def render_scanline():
            # Implementação de Alta Velocidade do renderizador de Background
            
            ly = mem[0xFF44] # Linha atual
            if ly >= 144:
                return
            lcdc = mem[0xFF40]
            
            with pygame.PixelArray(screen_surf) as pixels:
                # 1. Se Background estiver desligado (Bit 0 do LCDC), desenha branco e sai
                if not (lcdc & 0x01):
                    for x in range(160):
                        pixels[x, ly] = self.COLORS[0] # type: ignore # Branco
                    return

                # 2. Configurações de Janela e Scroll
                scy = mem[0xFF42]
                scx = mem[0xFF43]
                bgp = mem[0xFF47] # Background Palette
                
                # Mapa de Tiles (Bit 3 do LCDC controla qual mapa usar: 9800 ou 9C00)
                tile_map_base = 0x9C00 if (lcdc & 0x08) else 0x9800
                
                # Dados dos Tiles (Bit 4 controla: 8000 ou 8800)
                tile_data_base = 0x8000 if (lcdc & 0x10) else 0x9000
                is_signed_addressing = not (lcdc & 0x10)

                # 3. Renderiza os 160 pixels da linha
                # Otimização: Não iteramos pixel a pixel, iteramos Tile a Tile (bloquinhos de 8)
                
                y_in_bg_map = (ly + scy) & 0xFF
                tile_row = y_in_bg_map // 8 # Qual linha de tiles estamos (0 a 31)
                
                for p in range(21): # Precisamos de 20 tiles para cobrir 160px + scroll
                    # Calcula a posição X no mapa considerando o Scroll X
                    x_in_bg_map = (scx + (p * 8)) & 0xFF
                    tile_col = x_in_bg_map // 8
                    
                    # Pega o ID do Tile no Mapa
                    tile_addr = tile_map_base + (tile_row * 32) + tile_col
                    tile_id = mem[tile_addr]
                    
                    # Calcula o endereço dos dados do Tile (16 bytes por tile)
                    if is_signed_addressing and tile_id > 127:
                        tile_id -= 256
                    
                    # Cada tile tem 16 bytes (2 bytes por linha de pixel)
                    # Precisamos da linha exata dentro do tile (0 a 7)
                    line_in_tile = (y_in_bg_map % 8) * 2
                    data_addr = tile_data_base + (tile_id * 16) + line_in_tile
                    
                    byte1 = mem[data_addr]
                    byte2 = mem[data_addr + 1]
                    
                    # Decodifica os 8 pixels desse tile
                    for bit in range(7, -1, -1):
                        pixel_x_screen = (p * 8) + (7 - bit) - (scx % 8)
                        
                        if 0 <= pixel_x_screen < 160:
                            # Combina os bits para achar a cor (0 a 3)
                            # Bit 7 do byte1 é o bit baixo, Bit 7 do byte2 é o bit alto
                            color_bit_lo = (byte1 >> bit) & 1
                            color_bit_hi = (byte2 >> bit) & 1
                            color_idx = (color_bit_hi << 1) | color_bit_lo
                            
                            # Aplica a Paleta (BGP)
                            # A paleta mapeia o color_idx para a cor real
                            mapped_color = (bgp >> (color_idx * 2)) & 0x03
                            
                            # Desenha no Framebuffer do Pygame
                            rgb = self.COLORS[mapped_color]
                            pixels[pixel_x_screen, ly] = (rgb[0] << 16) | (rgb[1] << 8) | rgb[2] # type: ignore

        
        # --- PREPARAÇÃO DO LOG ---
        log_file = open("debug.log", "w")
        instruction_count = 0
        MAX_LOGS = 50000 # Grava apenas as primeiras 50 mil instruções
        logging_active = False

        print("Emulador rodando com LOG ativado... (debug.log)")
        frame_counter = 0
        while True:
            # --- 0. GRAVAÇÃO DO LOG ---
            if logging_active:
                # Formata a string de log igual ao BGB (padrão ouro dos emuladores)
                # Ex: PC:0100 OP:00 AF:01B0 ...
                log_line = (
                    f"PC:{pc:04X} OP:{mem[pc]:02X} "
                    f"AF:{regs[7]:02X}{regs[6]:02X} "
                    f"BC:{regs[0]:02X}{regs[1]:02X} "
                    f"DE:{regs[2]:02X}{regs[3]:02X} "
                    f"HL:{regs[4]:02X}{regs[5]:02X} "
                    f"SP:{sp:04X} "
                    f"LY:{mem[0xFF44]:02X} " # Importante: Monitorar a linha da tela (LY)
                    f"LCDC:{mem[0xFF40]:02X} " # Monitorar se o LCD está ligado
                    f"BGP:{mem[0xFF47]:02X}\n" # Monitorar a Paleta
                )
                log_file.write(log_line)
                
                instruction_count += 1
                if instruction_count >= MAX_LOGS:
                    print("Limite de log atingido. Parando gravação para performance.")
                    logging_active = False
                    log_file.close()

            # --- 1. TRATAMENTO DE INTERRUPÇÕES (Dispatch) ---
            
            # Lê os registradores de controle de interrupção da memória
            ie = mem[0xFFFF]    # Interrupt Enable (Quais interrupções o jogo QUER ouvir)
            if_reg = mem[0xFF0F] # Interrupt Flag (Quais interrupções o hardware DISPAROU)
            
            # Máscara 0x1F garante que só olhamos os 5 bits válidos (0 a 4)
            # pending_interrupts são aquelas que foram pedidas E estão habilitadas
            pending_interrupts = ie & if_reg & 0x1F
            
            # A. DESPERTAR DO HALT (HALT WAKE UP)
            # O processador acorda do HALT se houver QUALQUER interrupção pendente,
            # INDEPENDENTE do estado do IME (Interrupt Master Enable).
            if halted and pending_interrupts > 0:
                halted = False
            
            # B. DISPARO DA INTERRUPÇÃO (INTERRUPT DISPATCH)
            # Só acontece se o "Interruptor Geral" (IME) estiver ligado.
            if ime and pending_interrupts > 0:
                
                # 1. Desliga o IME automaticamente (para não interromper a interrupção)
                ime = False
                
                # 2. Consome ciclos de despacho (geralmente 5 M-Cycles = 20 T-Cycles)
                # O processador gasta esse tempo empilhando o PC e mudando o fluxo.
                # Como vamos executar a interrupção AGORA, não rodaremos fetch/decode nesta volta.
                cycles = 20 
                
                # 3. Empilha o PC atual (Push PC)
                sp = (sp - 1) & 0xFFFF; write_byte(sp, (pc >> 8) & 0xFF) # High
                sp = (sp - 1) & 0xFFFF; write_byte(sp, (pc & 0xFF))      # Low
                
                # 4. Define a prioridade e o vetor de salto
                # Ordem de prioridade: VBlank(0) > LCD(1) > Timer(2) > Serial(3) > Joypad(4)
                # Verifica bit por bit, do 0 ao 4. O primeiro que achar ganha.
                
                vector = 0x0000
                bit_to_clear = 0
                
                if pending_interrupts & 0x01:   # Bit 0: V-Blank
                    vector = 0x0040
                    bit_to_clear = 0
                elif pending_interrupts & 0x02: # Bit 1: LCD STAT
                    vector = 0x0048
                    bit_to_clear = 1
                elif pending_interrupts & 0x04: # Bit 2: Timer
                    vector = 0x0050
                    bit_to_clear = 2
                elif pending_interrupts & 0x08: # Bit 3: Serial
                    vector = 0x0058
                    bit_to_clear = 3
                elif pending_interrupts & 0x10: # Bit 4: Joypad
                    vector = 0x0060
                    bit_to_clear = 4
                
                # 5. Pula para o vetor de interrupção
                pc = vector
                
                # 6. "Acknowledge": Limpa o bit da interrupção em IF (0xFF0F)
                # Dizemos ao hardware: "Já estou cuidando disso, pode apagar o pedido."
                write_byte(0xFF0F, if_reg & ~(1 << bit_to_clear))
                
                # IMPORTANTE: Se processamos uma interrupção, NÃO executamos o passo de Fetch normal.
                # Pulamos direto para o fim do loop para contar os ciclos e continuar.
                # (Assumindo que você tem lógica de contagem de tempo no final do while)
                continue
            # --- FIM DO TRATAMENTO DE INTERRUPÇÕES ---
            
            if ime_scheduled:
                ime_scheduled = False
                ime = True

            cycles = 0 # Contador de ciclos em t-states
            
            if halted:
                cycles = 4 # CPU parada gasta ciclos mas não faz nada
            else:
                opcode = mem[pc]

                if halt_bug: halt_bug = False # LÓGICA DO HALT BUG - PC não incrementa
                else: pc = (pc + 1) & 0xFFFF
                
                x = opcode >> 6         # Pega os 2 bits mais significativos que representam a categoria
                y = (opcode >> 3) & 7   # Pega os próximos 3 bits que representam o destino ou operação
                z = opcode & 7          # Pega os 3 bits menos significativos que representam a fonte ou operação
                

                if x == 0: # Quadrante 0
                    
                    if z == 0: # Colunas x0 e x8 - NOP, STOP, JR, CALL, RET...
                        
                        if y == 0: # 0x00 - NOP
                            pass # Apenas gasta os 4 ciclos do fetch padrão
                        
                        elif y == 1: # 0x08 - LD (nn), SP
                            # Única instrução que salva 16 bits na memória no padrão Little Endian
                            low_addr = mem[pc]; pc = (pc + 1) & 0xFFFF
                            high_addr = mem[pc]; pc = (pc + 1) & 0xFFFF
                            addr = (high_addr << 8) | low_addr
                            
                            # Salva SP (Low byte primeiro, depois High byte)
                            write_byte(addr, sp & 0xFF)
                            write_byte((addr + 1) & 0xFFFF, (sp >> 8) & 0xFF)
                            
                            cycles = 20 # 4(fetch) + 8(ler addr) + 8(escrever RAM)

                        elif y == 2: # 0x10 - STOP
                            # STOP tecnicamente lê um byte extra (0x00) e o ignora
                            pc = (pc + 1) & 0xFFFF
                            # Aqui você poderia setar uma flag 'stopped = True' se quisesse,
                            # mas para GB clássico ele age quase como um HALT bizarro.
                            pass 

                        elif y == 3: # 0x18 - JR e8 (Pulo Relativo Incondicional)
                            offset = mem[pc]; pc = (pc + 1) & 0xFFFF
                            
                            # Conversão para Signed Int (Complemento de 2)
                            if offset > 127: 
                                offset -= 256
                                
                            pc = (pc + offset) & 0xFFFF
                            cycles = 12 # 4(fetch) + 4(read offset) + 4(jump)

                        else: # y = 4, 5, 6, 7 -> JR cc, e8 (Pulos Condicionais)
                            # Decodifica a condição baseada no Y
                            # y=4 (NZ), y=5 (Z), y=6 (NC), y=7 (C)
                            
                            # Lê o offset ANTES de decidir (o PC sempre anda, pulando ou não)
                            offset = mem[pc]; pc = (pc + 1) & 0xFFFF
                            if offset > 127: offset -= 256
                            
                            # Verifica Flags (Registrador F é regs[6])
                            f = regs[6]
                            condition = False
                            
                            if y == 4: # NZ (Not Zero) -> Bit 7 (Z) desligado
                                condition = not (f & 0x80)
                            elif y == 5: # Z (Zero) -> Bit 7 (Z) ligado
                                condition = (f & 0x80)
                            elif y == 6: # NC (Not Carry) -> Bit 4 (C) desligado
                                condition = not (f & 0x10)
                            elif y == 7: # C (Carry) -> Bit 4 (C) ligado
                                condition = (f & 0x10)
                            
                            if condition:
                                pc = (pc + offset) & 0xFFFF
                                cycles = 12 # Pulo realizado (gasta mais tempo)
                            else:
                                cycles = 8  # Pulo não realizado (gasta menos tempo)

                    elif z == 1: # Colunas x1 e x9
                        q = y & 1 # Bit 3 de y (q) define se é LD (0) ou ADD (1)
                        p = y >> 1 # Par: 0=BC, 1=DE, 2=HL, 3=SP

                        if q == 0: # LD rr, nn (Opcode 0x01, 0x11, 0x21, 0x31)
                            low = mem[pc]; pc = (pc + 1) & 0xFFFF
                            high = mem[pc]; pc = (pc + 1) & 0xFFFF
                            val_16 = (high << 8) | low
                            
                            if p == 0:   # BC
                                regs[0] = high; regs[1] = low
                            elif p == 1: # DE
                                regs[2] = high; regs[3] = low
                            elif p == 2: # HL
                                regs[4] = high; regs[5] = low
                            elif p == 3: # SP (Variavel local int)
                                sp = val_16
                            
                            cycles += 12 # 4(op) + 8(imediato)
                        
                        else: # ADD HL, rr (Opcodes 0x09, 0x19...)
                            hl = (regs[4] << 8) | regs[5]
                            val = 0
                            if p == 0: val = (regs[0] << 8) | regs[1]
                            elif p == 1: val = (regs[2] << 8) | regs[3]
                            elif p == 2: val = hl
                            elif p == 3: val = sp
                            
                            result = hl + val
                            
                            h_check = ((hl & 0xFFF) + (val & 0xFFF)) > 0xFFF
                            c_check = result > 0xFFFF
                            
                            current_z = regs[6] & 0x80 
                            
                            new_f = current_z 
                            if h_check: new_f |= 0x20 # Bit 5
                            if c_check: new_f |= 0x10 # Bit 4
                            
                            regs[6] = new_f
                            
                            result &= 0xFFFF
                            regs[4] = result >> 8 # H
                            regs[5] = result & 0xFF # L
                            
                            cycles = 8 # 4(op) + 4(math interno)

                    elif z == 2: # Colunas x2 e xA
                        # Bit 3 de y decide se é Load TO mem ou Load FROM mem
                        is_load_from_mem = (y & 1) == 1
                        p = y >> 1 # 0=BC, 1=DE, 2=HL+, 3=HL-
                        
                        # Descobrir endereço
                        addr = 0
                        if p == 0: addr = (regs[0] << 8) | regs[1] # BC
                        elif p == 1: addr = (regs[2] << 8) | regs[3] # DE
                        elif p == 2: # HL+ (Incrementa HL depois)
                            addr = (regs[4] << 8) | regs[5]
                            # Incremento de HL tem que ser manual aqui
                            hl_val = (addr + 1) & 0xFFFF
                            regs[4] = hl_val >> 8; regs[5] = hl_val & 0xFF
                        elif p == 3: # HL- (Decrementa HL depois)
                            addr = (regs[4] << 8) | regs[5]
                            hl_val = (addr - 1) & 0xFFFF
                            regs[4] = hl_val >> 8; regs[5] = hl_val & 0xFF
                        
                        if is_load_from_mem: # LD A, (rr)
                            regs[7] = mem[addr] # Carrega em A
                            cycles = 8
                        else: # LD (rr), A
                            write_byte(addr, regs[7]) # Salva A na memória
                            cycles = 8

                    elif z == 3: # INC/DEC 16-bits (BC, DE, HL, SP)
                        # ATENÇÃO: Essas instruções NÃO afetam flags!
                        
                        q = y & 1  # 0 = INC (Col 3), 1 = DEC (Col B)
                        p = y >> 1 # 0=BC, 1=DE, 2=HL, 3=SP

                        # 1. Ler o valor atual de 16 bits
                        val = 0
                        if p == 0:   # BC
                            val = (regs[0] << 8) | regs[1]
                        elif p == 1: # DE
                            val = (regs[2] << 8) | regs[3]
                        elif p == 2: # HL
                            val = (regs[4] << 8) | regs[5]
                        elif p == 3: # SP (Variável local int)
                            val = sp

                        # 2. Executar a operação
                        if q == 0: # INC
                            val = (val + 1) & 0xFFFF
                        else:      # DEC
                            val = (val - 1) & 0xFFFF
                        
                        # 3. Salvar o valor de volta
                        if p == 0:
                            regs[0] = val >> 8
                            regs[1] = val & 0xFF
                        elif p == 1:
                            regs[2] = val >> 8
                            regs[3] = val & 0xFF
                        elif p == 2:
                            regs[4] = val >> 8
                            regs[5] = val & 0xFF
                        elif p == 3:
                            sp = val # Atualiza a variável local SP

                        cycles = 8 # 4(fetch) + 4(operação interna)

                    elif z == 4: # INC r (8-bit) - Afeta Z, N, H (NÃO AFETA C)
                        # y define o registo: 0:B, 1:C, 2:D, 3:E, 4:H, 5:L, 6:(HL), 7:A
                        
                        # 1. Obter o valor original
                        val = 0
                        addr = 0 # Usado apenas se y=6
                        
                        if y == 6: # INC (HL)
                            addr = (regs[4] << 8) | regs[5]
                            val = mem[addr]
                            cycles = 12 # 4(fetch) + 4(read) + 4(write)
                        else:
                            val = regs[y]
                            cycles = 4
                        
                        # 2. Calcular o Resultado
                        res = (val + 1) & 0xFF
                        
                        # 3. Calcular Flags
                        # H Flag: Ocorre se os 4 bits inferiores eram F (15) e viraram 0
                        h_flag = (val & 0x0F) == 0x0F
                        z_flag = (res == 0)
                        
                        # Preservar o Carry atual (Bit 4)
                        current_c = regs[6] & 0x10 
                        
                        # Montar novo F (Z N H C)
                        new_f = current_c       # Mantém C antigo
                        if z_flag: new_f |= 0x80 # Z (Bit 7)
                        # N (Bit 6) é sempre 0 no INC
                        if h_flag: new_f |= 0x20 # H (Bit 5)
                        
                        regs[6] = new_f
                        
                        # 4. Escrever de volta
                        if y == 6:
                            write_byte(addr, res)
                        else:
                            regs[y] = res

                    elif z == 5: # DEC r (8-bit) - Afeta Z, N, H (NÃO AFETA C)
                        # y define o registo: 0:B, 1:C, 2:D, 3:E, 4:H, 5:L, 6:(HL), 7:A
                        
                        val = 0
                        addr = 0
                        
                        if y == 6: # DEC (HL)
                            addr = (regs[4] << 8) | regs[5]
                            val = mem[addr]
                            cycles = 12 # 4(fetch) + 4(read) + 4(write)
                        else:
                            val = regs[y]
                            cycles = 4
                        
                        # 1. Calcular Resultado
                        res = (val - 1) & 0xFF
                        
                        # 2. Calcular Flags
                        # H Flag (Borrow): Ocorre se o nibble inferior era 0 (e virou F)
                        h_flag = (val & 0x0F) == 0
                        z_flag = (res == 0)
                        
                        # Preservar o Carry atual
                        current_c = regs[6] & 0x10
                        
                        # Montar F (Z N H C)
                        new_f = current_c        # Mantém C
                        new_f |= 0x40            # N (Bit 6) SEMPRE 1 no DEC
                        if z_flag: new_f |= 0x80 # Z (Bit 7)
                        if h_flag: new_f |= 0x20 # H (Bit 5)
                        
                        regs[6] = new_f
                        
                        # 3. Escrever de volta
                        if y == 6:
                            write_byte(addr, res)
                        else:
                            regs[y] = res

                    elif z == 6: # Colunas x6 e xE
                            val = mem[pc]
                            pc = (pc + 1) & 0xFFFF
                            
                            # y é o índice do destino (B, C, D, E, H, L, (HL), A)
                            if y != 6:
                                regs[y] = val
                                cycles = 8 # 4(op) + 4(read n)
                                
                            else:
                                addr = (regs[4] << 8) | regs[5]
                                write_byte(addr, val)
                                cycles = 12 # 4(op) + 4(read n) + 4(write ram)

                    elif z == 7: # Rotates & Flags (Accumulator Only)
                        # Todas estas instruções custam 4 ciclos
                        
                        if y <= 3: # ROTATES (RLCA, RRCA, RLA, RRA)
                            # NOTA IMPORTANTE: Estas versões específicas (0x07, 0x0F, 0x17, 0x1F)
                            # SEMPRE definem a flag Z como 0. Diferente das versões CB!
                            
                            a = regs[7]
                            carry_flag = (regs[6] >> 4) & 1 # Pega o bit C atual
                            new_c = 0
                            res = 0
                            
                            if y == 0: # RLCA (Rotate Left Circular)
                                # Bit 7 vai para Carry E para Bit 0
                                new_c = (a >> 7) & 1
                                res = ((a << 1) & 0xFF) | new_c
                                
                            elif y == 1: # RRCA (Rotate Right Circular)
                                # Bit 0 vai para Carry E para Bit 7
                                new_c = a & 1
                                res = (a >> 1) | (new_c << 7)
                                
                            elif y == 2: # RLA (Rotate Left through Carry)
                                # Bit 7 vai para Carry, Carry ANTIGO vai para Bit 0
                                new_c = (a >> 7) & 1
                                res = ((a << 1) & 0xFF) | carry_flag
                                
                            elif y == 3: # RRA (Rotate Right through Carry)
                                # Bit 0 vai para Carry, Carry ANTIGO vai para Bit 7
                                new_c = a & 1
                                res = (a >> 1) | (carry_flag << 7)
                            
                            # Atualiza A
                            regs[7] = res
                            
                            # Atualiza Flags: Z=0, N=0, H=0, C=new_c
                            # Como Z, N e H são 0, só precisamos setar o bit 4 se new_c for 1
                            regs[6] = (new_c << 4)
                            
                        else: # ESPECIAIS (DAA, CPL, SCF, CCF)
                            
                            if y == 4: # DAA (Decimal Adjust Accumulator) - O "Chefão"
                                # Ajusta A para ser um número BCD válido após soma/subtração
                                a = regs[7]
                                f = regs[6]
                                
                                n_flag = (f >> 6) & 1
                                h_flag = (f >> 5) & 1
                                c_flag = (f >> 4) & 1
                                
                                correction = 0
                                
                                if h_flag or (not n_flag and (a & 0x0F) > 9):
                                    correction |= 0x06
                                
                                if c_flag or (not n_flag and a > 0x99):
                                    correction |= 0x60
                                    c_flag = 1
                                
                                if n_flag:
                                    a = (a - correction) & 0xFF
                                else:
                                    a = (a + correction) & 0xFF
                                
                                regs[7] = a
                                
                                # Atualiza Flags: Z=calc, N=antigo, H=0, C=calc
                                new_f = (1 if a == 0 else 0) << 7  # Z
                                new_f |= (n_flag << 6)             # N (mantém)
                                new_f |= (c_flag << 4)             # C (atualizado)
                                # H (bit 5) é sempre zerado
                                
                                regs[6] = new_f

                            elif y == 5: # CPL (Complement A) -> A = NOT A
                                regs[7] ^= 0xFF
                                # Flags: Z=antigo, N=1, H=1, C=antigo
                                # Seta bits 6 (N) e 5 (H)
                                regs[6] |= 0x60 

                            elif y == 6: # SCF (Set Carry Flag)
                                # Flags: Z=antigo, N=0, H=0, C=1
                                # Preserva Z (bit 7), limpa resto, seta C (bit 4)
                                regs[6] = (regs[6] & 0x80) | 0x10

                            elif y == 7: # CCF (Complement Carry Flag)
                                # Flags: Z=antigo, N=0, H=0, C = !C
                                old_z = regs[6] & 0x80
                                old_c = (regs[6] >> 4) & 1
                                new_c = old_c ^ 1
                                regs[6] = old_z | (new_c << 4)

                        cycles = 4

                elif x == 1: # Primeiro quadrante Loads instructions
                    
                    if opcode == 0x76: # HALT
                        ie = mem[0xFFFF] # Interrupt Enable Register - 0xFFFF
                        if_flag = mem[0xFF0F] # Interrupt Flag Register - 0xFF0F
                        
                        # Verifica se há interrupções pendentes que interessam
                        interrupt_pending = (ie & if_flag) & 0x1F # (Interrupts que estão habilitados no IE e ativos no IF)

                        if ime: halted = True # CENÁRIO 1: Normal Halt - IME setado. Entra em modo suspenso.
                        else:
                            if interrupt_pending == 0: halted = True # CENÁRIO 2: Halt sem Jump - IME desligado, mas sem interrupção pendente agora.   
                            else: # CENÁRIO 3: HALT BUG - # IME desligado E tem interrupção pendente.
                                halted = False 
                                halt_bug = True 

                        cycles = 4

                    else:
                        val = 0

                        if z != 6: val = regs[z] # Z=6 não é F, é (HL)! 
                        else:
                            addr = (regs[4] << 8) | regs[5] # H=regs[4], L=regs[5]
                            val = mem[addr]
                            cycles = +4

                        if y != 6: regs[y] = val # Y=6 não é F, é (HL)!
                        else:
                            addr = (regs[4] << 8) | regs[5] # H=regs[4], L=regs[5]
                            write_byte(addr, val)
                            cycles += 4
                    cycles += 4

                elif x == 2: # ALU (Arithmetic & Logic) - Opcodes 0x80 a 0xBF
                    # z = Fonte (Registrador ou Memória)
                    # y = Operação (ADD, ADC, SUB, SBC, AND, XOR, OR, CP)
                    
                    # 1. BUSCA O VALOR DA FONTE (Operando)
                    val = 0
                    if z == 6: # Fonte é (HL)
                        addr = (regs[4] << 8) | regs[5]
                        val = mem[addr]
                        cycles = 8 # 4(fetch op) + 4(read mem)
                    else:      # Fonte é Registrador (B,C,D,E,H,L,A)
                        val = regs[z]
                        cycles = 4
                    
                    # 2. PREPARA VARIÁVEIS
                    a = regs[7] # Acumulador atual
                    res = 0     # Resultado da conta
                    
                    # Flags atuais (para ADC/SBC)
                    f = regs[6]
                    c_flag_in = (f >> 4) & 1 # Carry de entrada (0 ou 1)
                    
                    # Flags de saída (vamos calcular durante a operação)
                    # True/False ou 0/1, depois convertemos pro registrador F
                    new_z = False
                    new_n = False
                    new_h = False
                    new_c = False
                    
                    # 3. EXECUTA A OPERAÇÃO (Baseado em Y)
                    
                    if y == 0: # ADD A, r
                        res = a + val
                        
                        new_n = False # ADD limpa N
                        # H: Carry do bit 3 pro 4. (a^val^res) & 0x10 verifica se mudou o bit 4 inesperadamente
                        new_h = (a ^ val ^ res) & 0x10 
                        new_c = res > 0xFF # Carry real (maior que 255)
                        
                        regs[7] = res & 0xFF # Salva em A
                        
                    elif y == 1: # ADC A, r (Soma com Carry)
                        res = a + val + c_flag_in
                        
                        new_n = False
                        new_h = (a ^ val ^ res) & 0x10
                        new_c = res > 0xFF
                        
                        regs[7] = res & 0xFF

                    elif y == 2: # SUB A, r
                        res = a - val
                        
                        new_n = True # SUB seta N
                        new_h = (a ^ val ^ res) & 0x10
                        new_c = res < 0 # Borrow (resultado negativo)
                        
                        regs[7] = res & 0xFF

                    elif y == 3: # SBC A, r (Subtração com Carry/Borrow)
                        res = a - val - c_flag_in
                        
                        new_n = True
                        new_h = (a ^ val ^ res) & 0x10
                        new_c = res < 0
                        
                        regs[7] = res & 0xFF

                    elif y == 4: # AND A, r
                        res = a & val
                        regs[7] = res
                        
                        # Lógica fixa do AND: H=1, N=0, C=0
                        new_n = False
                        new_h = True  # Sim, AND seta Half-Carry para 1 no Game Boy!
                        new_c = False
                        
                    elif y == 5: # XOR A, r
                        res = a ^ val
                        regs[7] = res
                        
                        # Lógica fixa do XOR: H=0, N=0, C=0
                        new_n = False; new_h = False; new_c = False
                        
                    elif y == 6: # OR A, r
                        res = a | val
                        regs[7] = res
                        
                        # Lógica fixa do OR: H=0, N=0, C=0
                        new_n = False; new_h = False; new_c = False
                        
                    elif y == 7: # CP A, r (Compare)
                        # Exatamente igual ao SUB, mas NÃO salva em A (regs[7])
                        res = a - val
                        
                        new_n = True
                        new_h = (a ^ val ^ res) & 0x10
                        new_c = res < 0 
                        # Note que não fazemos regs[7] = res & 0xFF aqui!
                        
                    
                    # 4. EMPACOTA AS FLAGS
                    # Z é comum a todos (se o byte final for 0)
                    if (res & 0xFF) == 0: new_z = True
                    
                    # Monta o byte F
                    new_f_byte = 0
                    if new_z: new_f_byte |= 0x80
                    if new_n: new_f_byte |= 0x40
                    if new_h: new_f_byte |= 0x20
                    if new_c: new_f_byte |= 0x10
                    
                    regs[6] = new_f_byte

                elif x == 3: # Quadrante 3
                    # --- GRUPO Z=0: RET e High RAM Loads & SP Arithmetic (C0, C8, D0, D8, E0, E8, F0, F8) ---
                    if z == 0:
                        # --- GRUPO: RET Condicional (Opcodes C0, C8, D0, D8) ---
                        if y <= 3: 
                            # y=0: NZ, y=1: Z, y=2: NC, y=3: C
                            
                            # 1. Verifica Condição
                            f = regs[6]
                            condition_met = False
                            
                            if y == 0:   # RET NZ
                                condition_met = not (f & 0x80)
                            elif y == 1: # RET Z
                                condition_met = (f & 0x80)
                            elif y == 2: # RET NC
                                condition_met = not (f & 0x10)
                            elif y == 3: # RET C
                                condition_met = (f & 0x10)
                            
                            # 2. Executa (ou não)
                            cycles = 8 # Ciclo base se não retornar
                            
                            if condition_met:
                                cycles = 20 # Ciclo mais longo se retornar
                                
                                # POP PC da pilha
                                low = mem[sp]; sp = (sp + 1) & 0xFFFF
                                high = mem[sp]; sp = (sp + 1) & 0xFFFF
                                pc = (high << 8) | low

                        # --- GRUPO: High RAM Loads & SP Arithmetic ---
                        
                        elif y == 4: # Opcode 0xE0 - LDH (n), A
                            offset = mem[pc]; pc = (pc + 1) & 0xFFFF
                            write_byte(0xFF00 + offset, regs[7])
                            cycles = 12

                        elif y == 5: # Opcode 0xE8 - ADD SP, e8 (Atenção aqui!)
                            # Soma SP com um byte COM SINAL.
                            # As Flags H e C são calculadas baseadas no byte baixo (0xFF).
                            
                            signed_byte = mem[pc]; pc = (pc + 1) & 0xFFFF
                            
                            # Flags (Lógica Bizarra do GB para SP):
                            # H: Carry do bit 3 para 4
                            # C: Carry do bit 7 para 8 (do byte baixo!)
                            h_check = ((sp & 0x0F) + (signed_byte & 0x0F)) > 0x0F
                            c_check = ((sp & 0xFF) + (signed_byte & 0xFF)) > 0xFF
                            
                            # Flags: Z=0, N=0, H=calc, C=calc
                            new_f = 0
                            if h_check: new_f |= 0x20
                            if c_check: new_f |= 0x10
                            regs[6] = new_f
                            
                            # Converte para soma com sinal real
                            if signed_byte > 127: signed_byte -= 256
                            
                            sp = (sp + signed_byte) & 0xFFFF
                            cycles = 16

                        elif y == 6: # Opcode 0xF0 - LDH A, (n) -> CORRIGIDO (era y=5)
                            offset = mem[pc]; pc = (pc + 1) & 0xFFFF
                            regs[7] = mem[0xFF00 + offset]
                            cycles = 12

                        elif y == 7: # Opcode 0xF8 - LD HL, SP+e8
                            # Igual ao ADD SP, mas salva em HL e não muda SP
                            
                            signed_byte = mem[pc]; pc = (pc + 1) & 0xFFFF
                            
                            # Flags (Mesma lógica do ADD SP acima):
                            h_check = ((sp & 0x0F) + (signed_byte & 0x0F)) > 0x0F
                            c_check = ((sp & 0xFF) + (signed_byte & 0xFF)) > 0xFF
                            
                            new_f = 0
                            if h_check: new_f |= 0x20
                            if c_check: new_f |= 0x10
                            regs[6] = new_f
                            
                            if signed_byte > 127: signed_byte -= 256
                            
                            res = (sp + signed_byte) & 0xFFFF
                            regs[4] = res >> 8 # H
                            regs[5] = res & 0xFF # L
                            
                            cycles = 12

                    # --- GRUPO Z=1: POP & RET ---
                    elif z == 1:
                        q = y & 1
                        if q == 0: # POP rr (Opcodes C1, D1, E1, F1)
                            # Recupera da pilha (Little Endian)
                            low = mem[sp]; sp = (sp + 1) & 0xFFFF
                            high = mem[sp]; sp = (sp + 1) & 0xFFFF
                            
                            p = y >> 1 # 0=BC, 1=DE, 2=HL, 3=AF
                            if p == 3: # POP AF (Especial!)
                                regs[7] = high # A
                                regs[6] = low & 0xF0 # F (Limpa bits 0-3)
                            else:
                                idx = p * 2 # 0->0(B), 1->2(D), 2->4(H)
                                regs[idx] = high
                                regs[idx+1] = low
                            
                            cycles = 12
                        else: # Opcodes C9, D9, E9, F9 (RET, RETI, JP HL, LD SP HL)
                            # p = y >> 1 (Calculado acima)
                            # p=0 (RET), p=1 (RETI), p=2 (JP HL), p=3 (LD SP, HL)

                            if p == 0 or p == 1: # RET (0xC9) e RETI (0xD9)
                                # Ambos fazem POP do PC da pilha
                                low = mem[sp]; sp = (sp + 1) & 0xFFFF
                                high = mem[sp]; sp = (sp + 1) & 0xFFFF
                                pc = (high << 8) | low
                                
                                cycles = 16 # 4(op) + 4(pop low) + 4(pop high) + 4(jump)
                                
                                if p == 1: # RETI (Retorna e habilita interrupções)
                                    ime = True 
                                    # Nota: Dependendo de como você gerencia a variavel 'ime' local,
                                    # talvez precise atualizar 'ime = True' também.

                            elif p == 2: # JP (HL) (Opcode 0xE9)
                                # Carrega PC com o valor de HL
                                # Cuidado: Não lê a memória EM HL, apenas copia o valor do par!
                                pc = (regs[4] << 8) | regs[5]
                                cycles = 4 

                            elif p == 3: # LD SP, HL (Opcode 0xF9)
                                # Carrega SP com o valor de HL
                                sp = (regs[4] << 8) | regs[5]
                                cycles = 8

                    # --- GRUPO Z=2: Controle e IO Loads via C/Direct (E2, F2, EA, FA) ---
                    elif z == 2:
                        if y == 4: # Opcode 0xE2 - LD (C), A
                            write_byte(0xFF00 + regs[1], regs[7])
                            cycles = 8
                        elif y == 6: # Opcode 0xF2 - LD A, (C)
                            regs[7] = mem[0xFF00 + regs[1]]
                            cycles = 8
                        elif y == 5: # Opcode 0xEA - LD (nn), A
                            low = mem[pc]; pc = (pc + 1) & 0xFFFF
                            high = mem[pc]; pc = (pc + 1) & 0xFFFF
                            write_byte((high << 8) | low, regs[7])
                            cycles = 16
                        elif y == 7: # Opcode 0xFA - LD A, (nn)
                            low = mem[pc]; pc = (pc + 1) & 0xFFFF
                            high = mem[pc]; pc = (pc + 1) & 0xFFFF
                            regs[7] = mem[(high << 8) | low]
                            cycles = 16
                        else: # Opcodes C2, CA, D2, DA (JP cc, nn)
                            # 1. Lê o endereço de destino (16 bits Little Endian)
                            # O GB sempre lê os operandos, mesmo que a condição seja falsa.
                            low = mem[pc]; pc = (pc + 1) & 0xFFFF
                            high = mem[pc]; pc = (pc + 1) & 0xFFFF
                            addr = (high << 8) | low
                            
                            # 2. Verifica a condição baseada no Y
                            # y=0(NZ), y=1(Z), y=2(NC), y=3(C)
                            f = regs[6]
                            condition = False
                            
                            if y == 0:   # NZ
                                condition = not (f & 0x80)
                            elif y == 1: # Z
                                condition = (f & 0x80)
                            elif y == 2: # NC
                                condition = not (f & 0x10)
                            elif y == 3: # C
                                condition = (f & 0x10)
                            
                            # 3. Pula ou não
                            if condition:
                                pc = addr
                                cycles = 16 # 4(fetch) + 8(read nn) + 4(jump)
                            else:
                                cycles = 12 # 4(fetch) + 8(read nn) -> Ignora o pulo

                    # --- GRUPO Z=3: JP, PREFIXO CB, DI, EI ---
                    elif z == 3: # Opcodes C3, CB, D3, DB, E3, EB, F3, FB
                    
                        if y == 0: # Opcode 0xC3 - JP nn (Incondicional)
                            # Lê endereço de destino (16 bits)
                            low = mem[pc]; pc = (pc + 1) & 0xFFFF
                            high = mem[pc]; pc = (pc + 1) & 0xFFFF
                            pc = (high << 8) | low
                            
                            cycles = 16 # 4(fetch) + 8(read) + 4(jump)

                        elif y == 1: # Opcode 0xCB - PREFIXO CB (Bitwise Ops)
                            cb_op = mem[pc]; pc = (pc + 1) & 0xFFFF
                            
                            # Decodifica o CB Opcode (x, y, z novamente!)
                            cb_x = cb_op >> 6
                            cb_y = (cb_op >> 3) & 7
                            cb_z = cb_op & 7

                            val = 0
                            hl_ptr = (regs[4] << 8) | regs[5]
                            
                            if cb_z == 6: # Operando é (HL)
                                val = mem[hl_ptr]
                                cycles = 16 # Padrão para Read-Modify-Write (SET, RES, SHIFTS)
                                if cb_x == 1: # Exceção: BIT (apenas leitura)
                                    cycles = 12
                            else: # Operando é Registrador
                                val = regs[cb_z]
                                cycles = 8

                            if cb_x == 0: # --- ROTATES & SHIFTS ---
                                # cb_y define qual tipo de rotação
                                
                                f = regs[6]
                                c_flag = (f >> 4) & 1
                                new_c = 0
                                
                                if cb_y == 0:   # RLC (Rotate Left Circular)
                                    new_c = (val >> 7) & 1
                                    val = ((val << 1) & 0xFF) | new_c
                                    
                                elif cb_y == 1: # RRC (Rotate Right Circular)
                                    new_c = val & 1
                                    val = (val >> 1) | (new_c << 7)
                                    
                                elif cb_y == 2: # RL (Rotate Left through Carry)
                                    new_c = (val >> 7) & 1
                                    val = ((val << 1) & 0xFF) | c_flag
                                    
                                elif cb_y == 3: # RR (Rotate Right through Carry)
                                    new_c = val & 1
                                    val = (val >> 1) | (c_flag << 7)
                                    
                                elif cb_y == 4: # SLA (Shift Left Arithmetic)
                                    new_c = (val >> 7) & 1
                                    val = (val << 1) & 0xFF # Bit 0 vira 0
                                    
                                elif cb_y == 5: # SRA (Shift Right Arithmetic)
                                    new_c = val & 1
                                    # Mantém o bit 7 (sinal) igual ao que era antes
                                    val = (val >> 1) | (val & 0x80)
                                    
                                elif cb_y == 6: # SWAP (Troca Nibbles)
                                    # 0xAB vira 0xBA. Afeta Z. Limpa N, H, C.
                                    val = ((val & 0x0F) << 4) | ((val & 0xF0) >> 4)
                                    new_c = 0 # SWAP sempre zera C
                                    
                                elif cb_y == 7: # SRL (Shift Right Logical)
                                    new_c = val & 1
                                    val = val >> 1 # Bit 7 vira 0
                                
                                # Atualiza Flags (Z depende do resultado, N=0, H=0, C=new_c)
                                # Nota: Diferente do RLC padrão (z=7 do quad 0), o CB RLC atualiza o Z normalmente!
                                new_f = 0
                                if val == 0: new_f |= 0x80 # Z
                                if new_c:    new_f |= 0x10 # C
                                regs[6] = new_f
                                
                                # Write Back
                                if cb_z == 6: write_byte(hl_ptr, val)
                                else:         regs[cb_z] = val

                            elif cb_x == 1: # --- BIT (Testar bit) ---
                                # cb_y é o índice do bit (0-7) a testar
                                # NÃO escreve o valor de volta, apenas muda flags.
                                
                                is_bit_zero = not ((val >> cb_y) & 1)
                                
                                # Flags: Z=set se bit for 0, N=0, H=1 (Sempre!), C=mantém
                                current_c = regs[6] & 0x10
                                new_f = 0x20 | current_c # H=1 e C=antigo
                                if is_bit_zero: new_f |= 0x80
                                
                                regs[6] = new_f

                            elif cb_x == 2: # --- RES (Reset bit) ---
                                # cb_y é o índice do bit a desligar
                                val &= ~(1 << cb_y)
                                
                                # Sem flags afetadas
                                
                                if cb_z == 6: write_byte(hl_ptr, val)
                                else:         regs[cb_z] = val

                            elif cb_x == 3: # --- SET (Set bit) ---
                                # cb_y é o índice do bit a ligar
                                val |= (1 << cb_y)
                                
                                # Sem flags afetadas
                                
                                if cb_z == 6: write_byte(hl_ptr, val)
                                else:         regs[cb_z] = val

                        elif y == 6: # Opcode 0xF3 - DI (Disable Interrupts)
                            # Desliga o Interrupt Master Enable imediatamente
                            ime = False
                            cycles = 4

                        elif y == 7: # Opcode 0xFB - EI (Enable Interrupts)
                            ime_scheduled = True
                            cycles = 4
                            
                        else:
                            # Opcodes D3, DB, E3, EB são ILIGAIS no Game Boy.
                            # Geralmente travam a CPU ou não fazem nada.
                            pass

                    # --- GRUPO Z=4: CALL Condicional ---
                    elif z == 4: # Opcodes C4, CC, D4, DC (CALL cc, nn)
                        # CALL Condicional: Se a condição for true, faz CALL. Se não, segue reto.
                        
                        if y <= 3:
                            # 1. O processador SEMPRE lê o endereço de destino (nn) primeiro
                            # Isso gasta ciclos mesmo se a condição for falsa.
                            low = mem[pc]; pc = (pc + 1) & 0xFFFF
                            high = mem[pc]; pc = (pc + 1) & 0xFFFF
                            dest_addr = (high << 8) | low
                            
                            # 2. Verifica a condição (Igual ao JP e RET)
                            # y=0:NZ, y=1:Z, y=2:NC, y=3:C
                            f = regs[6]
                            condition = False
                            
                            if y == 0:   condition = not (f & 0x80) # NZ
                            elif y == 1: condition = (f & 0x80)     # Z
                            elif y == 2: condition = not (f & 0x10) # NC
                            elif y == 3: condition = (f & 0x10)     # C
                            
                            # 3. Decide se chama a função ou não
                            if condition:
                                # TRUE: Faz o PUSH do PC e Pula
                                
                                # Empilha o PC atual (que já é a instrução seguinte ao CALL)
                                sp = (sp - 1) & 0xFFFF; write_byte(sp, (pc >> 8) & 0xFF)
                                sp = (sp - 1) & 0xFFFF; write_byte(sp, (pc & 0xFF))
                                
                                pc = dest_addr
                                cycles = 24 # 4(op) + 8(read nn) + 8(push) + 4(jump)
                            else:
                                # FALSE: Não faz nada, apenas gastou tempo lendo nn
                                cycles = 12 # 4(op) + 8(read nn)
                                
                        else:
                            # Opcodes E4, EC, F4, FC são inválidos/não existem no GB.
                            pass

                    # --- GRUPO Z=5: PUSH & CALL ---
                    elif z == 5:
                        q = y & 1
                        if q == 0: # PUSH rr (Opcodes C5, D5, E5, F5)
                            p = y >> 1
                            if p == 3: # PUSH AF
                                high = regs[7]
                                low = regs[6]
                            else:
                                idx = p * 2
                                high = regs[idx]
                                low = regs[idx+1]
                            
                            # Empilha (Decrementar SP antes de escrever)
                            sp = (sp - 1) & 0xFFFF; write_byte(sp, high)
                            sp = (sp - 1) & 0xFFFF; write_byte(sp, low)
                            cycles = 16
                        else: # Opcode 0xCD - CALL nn (Incondicional)
                            # 1. Lê destino
                            low = mem[pc]; pc = (pc + 1) & 0xFFFF
                            high = mem[pc]; pc = (pc + 1) & 0xFFFF
                            dest_addr = (high << 8) | low
                            
                            # 2. Empilha PC
                            sp = (sp - 1) & 0xFFFF; write_byte(sp, (pc >> 8) & 0xFF)
                            sp = (sp - 1) & 0xFFFF; write_byte(sp, (pc & 0xFF))
                            
                            # 3. Pula
                            pc = dest_addr
                            cycles = 24 # 4(fetch) + 8(read nn) + 8(push) + 4(jump)
                    
                    # --- GRUPO Z=6: ALU A, n (Imediato) ---
                    elif z == 6: # Opcodes C6, CE, D6, DE, E6, EE, F6, FE (ALU A, n)
                        # 1. Lê o valor imediato (n)
                        val = mem[pc]; pc = (pc + 1) & 0xFFFF
                        cycles = 8 # 4(op) + 4(read n)
                        
                        # 2. Prepara variáveis
                        a = regs[7]
                        res = 0
                        
                        # Para ADC/SBC
                        f = regs[6]
                        c_in = (f >> 4) & 1
                        
                        # Flags de saída
                        new_z = False; new_n = False; new_h = False; new_c = False
                        
                        # 3. Executa a operação baseada no Y
                        
                        if y == 0: # ADD A, n
                            res = a + val
                            new_n = False
                            new_h = (a ^ val ^ res) & 0x10
                            new_c = res > 0xFF
                            regs[7] = res & 0xFF
                            
                        elif y == 1: # ADC A, n
                            res = a + val + c_in
                            new_n = False
                            new_h = (a ^ val ^ res) & 0x10
                            new_c = res > 0xFF
                            regs[7] = res & 0xFF

                        elif y == 2: # SUB A, n (Opcode D6)
                            res = a - val
                            new_n = True
                            new_h = (a ^ val ^ res) & 0x10
                            new_c = res < 0
                            regs[7] = res & 0xFF

                        elif y == 3: # SBC A, n (Opcode DE)
                            res = a - val - c_in
                            new_n = True
                            new_h = (a ^ val ^ res) & 0x10
                            new_c = res < 0
                            regs[7] = res & 0xFF

                        elif y == 4: # AND n (Opcode E6)
                            res = a & val
                            regs[7] = res
                            new_n = False; new_h = True; new_c = False # H=1 no AND
                            
                        elif y == 5: # XOR n (Opcode EE)
                            res = a ^ val
                            regs[7] = res
                            new_n = False; new_h = False; new_c = False
                            
                        elif y == 6: # OR n (Opcode F6)
                            res = a | val
                            regs[7] = res
                            new_n = False; new_h = False; new_c = False
                            
                        elif y == 7: # CP n (Opcode FE) - Compare Immediate
                            res = a - val
                            new_n = True
                            new_h = (a ^ val ^ res) & 0x10
                            new_c = res < 0
                            # NÃO salva em regs[7]!
                        
                        # 4. Empacota Flags
                        if (res & 0xFF) == 0: new_z = True
                        
                        new_f = 0
                        if new_z: new_f |= 0x80
                        if new_n: new_f |= 0x40
                        if new_h: new_f |= 0x20
                        if new_c: new_f |= 0x10
                        regs[6] = new_f

                    # --- GRUPO Z=7: RST y*8 ---
                    elif z == 7: # RST y*8 (Opcodes C7, CF, D7, DF, E7, EF, F7, FF)
                        # RST é um "Mini CALL" para endereços fixos (vetores).
                        
                        # 1. Calcula o destino (y * 8)
                        dest_addr = y << 3 
                        
                        # 2. Empilha o PC atual (Return Address)
                        # O PC aqui já aponta para a instrução seguinte (devido ao fetch do opcode)
                        sp = (sp - 1) & 0xFFFF; write_byte(sp, (pc >> 8) & 0xFF) # Push High
                        sp = (sp - 1) & 0xFFFF; write_byte(sp, (pc & 0xFF))      # Push Low
                        
                        # 3. Pula para o vetor
                        pc = dest_addr
                        
                        cycles = 16 # 4(fetch) + 8(push stack) + 4(jump)
                    
                    # --- OUTROS GRUPOS (DI, EI, ALU Immediate...) ---
                    else:
                        pass
                            

                # 3. Sincronia (PPU e Timer correm atrás)
                # --- 1. Atualização do DIV (Sempre ativo) ---
                # O DIV incrementa a cada 256 ciclos de clock (T-States)
                div_counter += cycles
                while div_counter >= 256:
                    div_counter -= 256
                    mem[0xFF04] = (mem[0xFF04] + 1) & 0xFF
                
                # --- 2. Atualização do TIMA (Controlado pelo TAC) ---
                tac = mem[0xFF07] # Timer Control
                
                # Bit 2 do TAC liga/desliga o Timer
                if tac & 0x04:
                    # Descobre a frequência baseada nos bits 1-0
                    freq_bits = tac & 0x03
                    threshold = 1024 # Padrão (freq=00 -> 4096Hz -> 1024 ciclos)
                    
                    if freq_bits == 1:   threshold = 16   # 262144Hz
                    elif freq_bits == 2: threshold = 64   # 65536Hz
                    elif freq_bits == 3: threshold = 256  # 16384Hz
                    
                    tima_counter += cycles
                    
                    while tima_counter >= threshold:
                        tima_counter -= threshold
                        
                        # Incrementa o TIMA (0xFF05)
                        tima = mem[0xFF05]
                        if tima == 0xFF:
                            # OVERFLOW!
                            mem[0xFF05] = mem[0xFF06] # Recarrega com valor do TMA (Modulo)
                            
                            # Solicita Interrupção do Timer (Bit 2 do registro IF)
                            mem[0xFF0F] |= 0x04 
                        else:
                            mem[0xFF05] = tima + 1

                # --- 4. Atualização do PPU ---
                frame_ready = ppu_update(cycles, mem)

                # --- 4. CONTROLO DE FRAMES E EVENTOS (A CORREÇÃO!) ---
                
                cycles_since_last_frame += cycles
                
                # Verifica se precisamos desenhar ou apenas processar eventos
                should_update_pygame = False
                
                # CASO 1: A PPU terminou um quadro (V-Blank normal)
                if frame_ready:
                    should_update_pygame = True
                    # Escala a imagem da PPU para a janela
                    pygame.transform.scale(screen_surf, (160 * SCALE, 144 * SCALE), window)
                
                # CASO 2: O LCD está desligado, mas passou tempo suficiente (simula 60FPS)
                elif not (mem[0xFF40] & 0x80) and cycles_since_last_frame >= CYCLES_PER_FRAME:
                    should_update_pygame = True
                    # Opcional: Pode desenhar um ecrã branco ou preto aqui para indicar LCD OFF
                    window.fill((255, 255, 255)) 

                # Se for hora de atualizar a janela (seja por VBlank ou Timeout do LCD Off)
                if should_update_pygame:
                    cycles_since_last_frame = 0 # Reseta contador

                    frame_counter += 1
                    if frame_counter % 60 == 0: # Executa a cada 60 frames (aprox 1 seg)
                        lcdc = mem[0xFF40]
                        ly = mem[0xFF44]
                        ie = mem[0xFFFF] # Interrupt Enable
                        if_reg = mem[0xFF0F] # Interrupt Flag
                        
                        print(f"STATUS -> PC:{pc:04X} | LCDC:{lcdc:02X} | LY:{ly:02X} | IE:{ie:02X} IF:{if_reg:02X}")
                    
                    pygame.display.flip()
                    #clock.tick(60) # Mantém a velocidade controlada
                    
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            raise KeyboardInterrupt
                        
                    keys = pygame.key.get_pressed()
                    
                    # O Game Boy escreve em bits 4 ou 5 para escolher o que ler:
                    # Bit 4 = 0 -> Ler Direcionais (Right, Left, Up, Down)
                    # Bit 5 = 0 -> Ler Botões (A, B, Select, Start)
                    # Lembre-se: 0 = Selecionado/Pressionado
                    
                    joypad_reg = mem[0xFF00]
                    select_buttons = not (joypad_reg & 0x20) # Bit 5
                    select_dpad = not (joypad_reg & 0x10)    # Bit 4
                    
                    # Começamos com 0xCF (tudo solto + bits inusados em 1)
                    # Bits inferiores (0-3) começam em 1 (soltos)
                    result = 0xCF 
                    
                    if select_buttons:
                        if keys[pygame.K_x]: result &= ~(0x01) # A (Tecla X)
                        if keys[pygame.K_z]: result &= ~(0x02) # B (Tecla Z)
                        if keys[pygame.K_BACKSPACE]: result &= ~(0x04) # Select
                        if keys[pygame.K_RETURN]: result &= ~(0x08) # Start
                        
                    if select_dpad:
                        if keys[pygame.K_RIGHT]: result &= ~(0x01)
                        if keys[pygame.K_LEFT]:  result &= ~(0x02)
                        if keys[pygame.K_UP]:    result &= ~(0x04)
                        if keys[pygame.K_DOWN]:  result &= ~(0x08)
                        
                    mem[0xFF00] = result

if __name__ == "__main__":
    gb = GameBoy()
    #gb.load_rom("roms/gb-test-roms-master/cpu_instrs/cpu_instrs.gb")
    #gb.load_rom("roms/dmg-acid2.gb")
    #gb.load_rom("roms/Tetris.gb")
    gb.run()