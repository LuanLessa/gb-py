"""
================================================================================
 gb — o Game Boy por dentro
================================================================================

Esta pasta é o console. Cada arquivo aqui corresponde a uma peça de hardware
real do Game Boy de 1989, e o programa todo faz uma coisa só: fingir ser esse
hardware bem o suficiente para que um cartucho de verdade não perceba a
diferença.

Vale explicar o que "emular" significa, porque a palavra é usada de forma
solta. O cartucho de Tetris contém um programa escrito para um processador
específico, o Sharp SM83. Esse programa manda coisas como "some 1 ao
registrador B" e "escreva 0x91 no endereço 0xFF40". Nenhum computador moderno
entende essas ordens. O que este projeto faz é ler cada ordem, uma por uma, e
executar em Python o efeito que ela teria no chip original — mantendo, em
variáveis, uma cópia de todo o estado interno do console: os registradores, a
memória, o que está na tela, quantos ciclos já se passaram.

O programa do cartucho não sabe de nada disso. Ele pede para ler o botão A, e
alguém devolve um valor. Se o valor estiver certo e chegar no momento certo, o
jogo funciona.


--------------------------------------------------------------------------------
 POR ONDE COMEÇAR
--------------------------------------------------------------------------------

Os arquivos abaixo estão na ordem em que fazem sentido para quem chega agora.
Cada um só depende dos anteriores.

    constants.py     Os apelidos usados no projeto inteiro. Cinco minutos.

    cpu.py           O processador: como ele busca, decide e executa. É o
                     coração, e o resto do console gira em torno dele.

    opcodes.py       As 512 instruções que a CPU sabe executar. Arquivo
                     grande, mas repetitivo: entendidas dez, entendidas todas.

    machine.py       O barramento. Decide quem responde a cada endereço e
                     distribui o tempo entre os chips.

    timer.py         Um contador que dispara interrupções. Pequeno, e o
                     primeiro lugar onde a precisão de tempo aparece.

    interrupts.py    Como um chip interrompe a CPU no meio do trabalho.

    ppu.py           O vídeo. Monta a imagem linha por linha, do jeito que uma
                     TV de tubo faria.

    dma.py           Uma cópia de memória que o hardware faz sozinho.

    apu.py           O som: quatro canais, cada um com um jeito próprio de
                     gerar onda.

    joypad.py        Os oito botões.
    serial.py        O cabo que ligava dois Game Boys.

    cartridge.py     O cartucho, e o chip dentro dele que permite jogos
                     maiores do que a memória endereçável do console.

    registradores.py Uma otimização. Interessante depois, dispensável agora.

Fora desta pasta: `main.py` abre a janela e cuida do ritmo, `ui/` desenha os
menus, e `tests/` prova que tudo isso está certo.


--------------------------------------------------------------------------------
 VOCABULÁRIO
--------------------------------------------------------------------------------

Sete palavras aparecem o tempo todo daqui para a frente.

REGISTRADOR
    Uma variável que mora dentro do processador. O SM83 tem sete de 8 bits
    (A, B, C, D, E, H, L), e são o único lugar onde ele consegue fazer conta.
    Somar dois números guardados na memória exige trazer os dois para
    registradores, somar, e devolver o resultado. Daí a quantidade de
    instruções que só movem dados de um lado para o outro.

ENDEREÇO
    Um número que identifica uma posição de memória. O Game Boy usa 16 bits,
    então existem 65.536 endereços, de 0x0000 a 0xFFFF. Nem todos são memória:
    alguns são "torneiras" ligadas direto no hardware, e escrever neles liga o
    som ou muda a tela.

BARRAMENTO
    O caminho por onde a CPU conversa com o resto. Quando ela pede o endereço
    0x8000, o barramento é quem sabe que ali quem responde é a memória de
    vídeo. Está em `machine.py`.

T-CYCLE e M-CYCLE
    As batidas do relógio do console. São 4.194.304 T-cycles por segundo. Um
    M-cycle são 4 T-cycles, e é o tempo mínimo de qualquer acesso à memória.
    Instruções são medidas em M-cycles: um `NOP` gasta 1, um `LD B, C` gasta 1,
    um `CALL` gasta 6.

INTERRUPÇÃO
    Um pedido de socorro do hardware. Quando a tela termina de ser desenhada, a
    PPU avisa a CPU, que larga o que estava fazendo e pula para uma rotina de
    tratamento. É assim que um jogo sabe a hora de atualizar a imagem sem ficar
    perguntando o tempo todo.

OPCODE
    O byte que representa uma instrução. 0x04 significa "some 1 em B". O nome
    legível — `INC B` — chama-se mnemônico e existe só para humanos; na ROM
    está gravado o byte.

FRAMEBUFFER
    O retângulo de 160x144 posições onde a imagem é montada antes de ir para a
    tela. Cada posição guarda 0, 1, 2 ou 3 — os quatro tons do console.


--------------------------------------------------------------------------------
 COMO LER OS NÚMEROS E OS OPERADORES DE BITS
--------------------------------------------------------------------------------

Esta parte do guia existe para não repetir a mesma explicação em quarenta
arquivos. Documentação de hardware é escrita em hexadecimal e em bits, e o
código acompanha.

HEXADECIMAL — o prefixo 0x

    0xFF40 é um número na base 16. Cada dígito hexadecimal vale exatamente
    4 bits, então dois dígitos formam um byte e quatro formam um endereço. A
    vantagem sobre decimal é essa correspondência direta:

        0xFF  = 255       = 11111111
        0x80  = 128       = 10000000
        0x0F  = 15        = 00001111

    Reconhecer 0x80 como "só o bit mais alto" é imediato; reconhecer 128 como a
    mesma coisa, não. Por isso a documentação da Nintendo, os manuais e este
    código usam hexadecimal para tudo que seja endereço, máscara ou opcode.

    Em Python, 0b10000000 também funciona e é a mesma coisa escrita em binário.

& — a máscara

    O operador `&` compara bit a bit e só deixa passar onde os DOIS lados têm 1.
    Serve para ficar apenas com uma parte do número:

        0b10110101 & 0b00001111  =  0b00000101
        (o valor)    (a máscara)    (só os 4 bits de baixo sobreviveram)

    O uso mais comum no projeto é `& 0xFF`. Ele existe por uma diferença
    incômoda entre Python e hardware: um registrador de 8 bits guarda no máximo
    255, e 255 + 1 volta para 0. Em Python, um inteiro cresce para sempre, e
    255 + 1 dá 256. A máscara corta o excesso e devolve o comportamento do chip:

        (255 + 1) & 0xFF  =  0        # como no console
        255 + 1           =  256      # como em Python, e errado aqui

    A mesma ideia com `& 0xFFFF` para valores de 16 bits.

| — ligar bits

    Deixa passar onde QUALQUER um dos lados tem 1. Usado para ligar um bit sem
    tocar nos outros:

        valor |= 0b00000100      # liga o bit 2, seja lá como estavam os demais

& ~ — desligar bits

    `~` inverte todos os bits, então `& ~x` desliga exatamente os bits que `x`
    tinha ligados:

        valor &= ~0b00000100     # desliga o bit 2, preserva o resto

^ — inverter bits

    Troca 1 por 0 e 0 por 1 nas posições marcadas. `x ^ 0xFF` inverte o byte
    inteiro.

<< e >> — empurrar os bits

    `<<` empurra para a esquerda, `>>` para a direita. Empurrar 8 casas move um
    byte inteiro de posição, e é assim que dois bytes viram um número de 16 bits
    e vice-versa:

        (alto << 8) | baixo      # junta dois bytes num valor de 16 bits
        (valor >> 8) & 0xFF      # extrai o byte alto
        valor & 0xFF             # extrai o byte baixo

TESTAR UM BIT

    A combinação `(valor >> n) & 1` aparece dezenas de vezes. Ela empurra o bit
    n até a posição zero e descarta todo o resto, sobrando 0 ou 1:

        (0b10110101 >> 2) & 1  =  1     # o bit 2 está ligado

    Quando só interessa saber se está ligado, `valor & (1 << n)` também serve —
    o resultado não é 1, mas é diferente de zero, que em Python já conta como
    verdadeiro.


--------------------------------------------------------------------------------
 CONVENÇÕES DESTE CÓDIGO
--------------------------------------------------------------------------------

Nomes em português, com uma exceção: siglas e nomes de instruções ficam como
estão na documentação do console. `TIMA`, `LCDC`, `LD_r8_n8` e `FLAG_Z` são os
nomes oficiais, e traduzi-los deixaria o código impossível de comparar com
qualquer manual ou site de referência.

Um `_` na frente de um método (`_avaliar_borda`) significa "isto é assunto
interno da classe". Python não impede ninguém de chamar assim mesmo — é um
combinado entre programadores, não uma trava.

`bytearray` é usado para toda memória do console. É uma sequência de bytes que
pode ser modificada no lugar, ao contrário de `bytes`, e cada posição só aceita
valores de 0 a 255 — o que dá de graça uma checagem que a memória de verdade
também tem.

Endereços aparecem sem o prefixo `0x` quando estão em texto corrido (FF40) e
com ele quando são código (0xFF40), seguindo os manuais originais.
"""
