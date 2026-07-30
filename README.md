# gb-py — um Game Boy escrito em Python

Este projeto finge ser um Game Boy de 1989 com precisão suficiente para que
cartuchos de verdade não percebam a diferença. Ele roda Tetris, Zelda e Pokémon
a partir dos arquivos originais, sem depender de nada além do próprio Python.

Foi escrito para ser **lido**. Cada arquivo corresponde a uma peça de hardware
real, e a documentação explica não só o que o código faz, mas por que o console
funcionava daquele jeito — incluindo os defeitos de fábrica, que os jogos
aprenderam a usar e que um emulador precisa reproduzir fielmente.

```
python main.py                    abre a janela no seletor de jogos
python main.py --continuar        reabre o último jogo
python main.py jogo.gb            abre um jogo específico
python tests/executar_todos.py    roda a suíte de testes
```

Com janela é preciso ter o pygame (`pip install pygame`). Sem ele, o emulador
continua funcionando pelos modos de terminal descritos mais abaixo.

---

## Por onde começar a ler

**A porta de entrada é [`gb/__init__.py`](gb/__init__.py).** Ele explica o que
significa emular, apresenta o vocabulário (registrador, barramento, ciclo,
interrupção) e ensina a ler os números em hexadecimal e as operações de bits que
aparecem no projeto inteiro. Quinze minutos ali economizam horas depois.

Dali em diante, a ordem que faz sentido é esta — cada arquivo só depende dos
anteriores:

| # | Arquivo | O que tem lá |
|---|---|---|
| 1 | `gb/constants.py` | os apelidos usados em todo lugar. Cinco minutos |
| 2 | `gb/cpu.py` | o processador: buscar, decodificar, executar |
| 3 | `gb/opcodes.py` | as 512 instruções. Grande, mas repetitivo |
| 4 | `gb/machine.py` | o barramento e o mapa de memória |
| 5 | `gb/timer.py` | um contador que dispara interrupções |
| 6 | `gb/interrupts.py` | como um chip interrompe a CPU |
| 7 | `gb/ppu.py` | o vídeo: tiles, mapas, sprites, modos |
| 8 | `gb/dma.py` | a cópia automática de sprites |
| 9 | `gb/apu.py` | o som: quatro geradores de onda |
| 10 | `gb/joypad.py` `gb/serial.py` | os botões e o cabo link |
| 11 | `gb/cartridge.py` | como um jogo de 1 MB cabe num console de 64 KB |
| 12 | `gb/registradores.py` | uma otimização. Interessante depois |

Depois do console vêm `main.py` (a janela e o ritmo), `ui/` (os menus) e
`tests/`.

### Se você tiver pouco tempo

Cinco trechos que valem sozinhos, mesmo sem ler o resto:

- **`CPU.step`**, no fim de `gb/cpu.py` — o laço que move tudo, em vinte linhas.
- **`gb/timer.py`** — o arquivo inteiro. Ele mostra por que a leitura intuitiva
  ("o contador sobe a cada N ciclos") produz um emulador que roda a maioria dos
  jogos e falha em todos os testes de precisão.
- **A `DAA`**, em `gb/opcodes.py` — a instrução mais estranha do conjunto,
  explicada a partir de um problema concreto: como mostrar a pontuação na tela.
- **`texto_da_tela`**, em `tests/harness.py` — como ler o resultado de um teste
  que só escreve na tela, sem olhar um único pixel.
- **`gb/registradores.py`** — um caso em que o código elegante era seis vezes
  mais lento, com o número medido.

---

## Como usar

### Jogando

```
python main.py                    abre no seletor, na pasta roms/
python main.py --continuar        vai direto para o último jogo
python main.py jogo.gb            abre um jogo específico
python main.py --roms /caminho    outra pasta de jogos
```

| Tecla | Faz |
|---|---|
| setas | direcional |
| `Z` / `X` | A / B |
| `Enter` | Start |
| `Backspace` | Select |
| `Tab` (segurando) | turbo |
| `Esc` | abre o menu; dentro dele, volta |
| `F5` | reabre o áudio, se o som sumir |

O `Esc` abre um menu desenhado sobre o jogo congelado: continuar, reiniciar,
trocar de jogo e ajustes (som, volume, escala da janela, paleta e pulo de
quadros). Os ajustes valem na hora — trocar a paleta recolore o próprio quadro
parado atrás do menu — e ficam guardados para a próxima vez, junto da última ROM
aberta e da pasta onde você estava.

Jogos com bateria gravam o save num `.sav` ao lado da ROM, inclusive ao trocar de
jogo pelo menu.

### Sem janela

Estes modos não precisam do pygame e servem para testar, medir e depurar:

```
python main.py jogo.gb --frames 600      roda 600 quadros e relata a velocidade
python main.py jogo.gb --ascii           desenha a tela no próprio terminal
python main.py jogo.gb --png tela.png    salva a tela num arquivo
python main.py jogo.gb --serial          imprime o que a ROM mandou pela serial
```

### Opções úteis

| Opção | Para quê |
|---|---|
| `--escala N` | tamanho da janela (1 a 8) |
| `--som` / `--sem-som` | força ligar ou desligar o áudio |
| `--pulo-maximo N` | quantos quadros seguidos podem ser pulados; `0` desliga |
| `--forcar` | roda ROMs marcadas como exclusivas de Game Boy Color |
| `--sem-save` | não carrega nem grava o `.sav` |
| `--diagnostico` | mede cada fase do quadro e grava um relatório ao fechar |

---

## Como o projeto é organizado

```
main.py                 a janela, o ritmo dos quadros, o áudio e os saves
ui/
  fonte.py              uma fonte de bitmap 5x7 desenhada à mão, com acentos
  paletas.py            os quatro tons, usados pelo jogo e pelo menu
  config.py             preferências em JSON, validadas e gravadas com segurança
  biblioteca.py         a pasta de jogos e os títulos lidos dos cartuchos
  menu.py               páginas, itens e navegação — sem pygame
  desenho.py            a única parte da interface que fala com o pygame
gb/
  constants.py          apelidos dos registradores e das flags
  cpu.py                o processador Sharp SM83
  opcodes.py            as 512 instruções
  machine.py            o barramento: quem responde a cada endereço
  timer.py              DIV, TIMA, TMA, TAC
  ppu.py                o vídeo
  dma.py                a cópia automática da tabela de sprites
  apu.py                os quatro canais de som
  serial.py             o cabo link — e o terminal de depuração do console
  joypad.py             os oito botões
  interrupts.py         as cinco interrupções
  cartridge.py          o cabeçalho do cartucho e os MBCs
  registradores.py      duas formas de ver os mesmos 12 bytes
tests/                  a suíte, incluindo as ROMs de teste da Blargg
```

Uma regra atravessa a organização inteira: **`gb/` não sabe que existe uma
tela**. Ele entrega um retângulo de números e amostras de áudio, e nada mais.
Isso é o que permite testar o emulador sem abrir janela, e é a razão de ele não
depender de nada além da biblioteca padrão do Python.

O mesmo princípio se repete um nível abaixo: dentro de `ui/`, só o `desenho.py`
importa pygame. Os menus são Python puro, e por isso 144 asserções de navegação
rodam em milissegundos, sem placa de vídeo.

### O que significa "precisão de ciclo"

Emular o que cada instrução faz é a parte fácil. A difícil é emular **quando**.

Efeitos gráficos do Game Boy funcionam porque o jogo conta ciclos: ele sabe que
a PPU leva 456 ciclos para desenhar uma linha e programa a mudança de paleta
para o instante exato entre uma linha e a próxima. Errar por um M-cycle
transforma um efeito de água ondulando numa tela tremendo.

A precisão vem de duas regras simples:

1. **Todo acesso ao barramento custa exatamente 1 M-cycle**, e o resto do
   console avança *antes* do acesso — reproduzindo o hardware, onde o dado só
   aparece no último ciclo.
2. **`Machine.tick4()` avança o sistema inteiro junto.** Timer, DMA, vídeo, som
   e serial andam de quatro em quatro ciclos, intercalados com a execução. Nada
   roda "em lote" no fim do quadro.

---

## Os defeitos do hardware, reproduzidos de propósito

Emular o Game Boy funcionando é fácil. Emular os **erros** dele é o que faz os
jogos rodarem — desenvolvedores da época descobriram esses comportamentos e
passaram a contar com eles.

| Comportamento | Onde |
|---|---|
| Atraso do `EI` — a chave só liga depois da instrução seguinte | `cpu.py` |
| Bug do `HALT` — a próxima instrução executa duas vezes | `cpu.py` |
| Uma interrupção pode se cancelar ao empilhar sobre o IE | `cpu.py` |
| Os 4 bits baixos do registrador F não existem e leem 0 | `cpu.py` |
| Escrever no DIV pode **incrementar** o TIMA | `timer.py` |
| O TIMA fica 1 M-cycle em zero antes de recarregar | `timer.py` |
| Escrever no TIMA durante a recarga é ignorado; no TMA, muda o valor | `timer.py` |
| STAT blocking — duas fontes ativas geram **uma** interrupção só | `ppu.py` |
| Duração variável do modo 3, conforme rolagem, janela e sprites | `ppu.py` |
| Limite de 10 sprites por linha | `ppu.py` |
| Memória de vídeo travada conforme o modo | `ppu.py` |
| Corrupção da tabela de sprites por `inc rr` sobre FEXX | `ppu.py` |
| Durante a cópia de sprites a CPU perde o barramento externo | `machine.py` |
| MBC1: o banco 0 vira 1, e três bancos ficam inalcançáveis | `cartridge.py` |
| MBC2: RAM de 512 **meio-bytes**, seletor pelo bit 8 do endereço | `cartridge.py` |
| MBC3: relógio de tempo real, congelado para leitura | `cartridge.py` |
| O relógio do som sai do bit 4 do DIV | `apu.py` |
| "Extra length clocking" ao ligar a duração na metade errada do ciclo | `apu.py` |
| Desligar o som zera os registradores — mas não a memória de onda | `apu.py` |
| Sweep que passa de 2047 desliga o canal já no disparo | `apu.py` |
| Corrupção da memória de onda ao disparar o canal 3 tocando | `apu.py` |
| Modo "zumbi" do envelope | `apu.py` |
| DAC bipolar: o digital 0 é a tensão **mínima**, e não silêncio | `apu.py` |
| Capacitor de saída removendo a corrente contínua | `apu.py` |

---

## Como se sabe que está certo

**15 suítes de testes, 176 casos, 386 asserções — todas passando.**

**ROMs de teste da Blargg: 36 de 38 aplicáveis.**

| Suíte | Resultado | O que cobre |
|---|---|---|
| `cpu_instrs` | **11/11** | as 512 instruções, flags e casos de borda |
| `instr_timing` | **1/1** | a duração de cada instrução |
| `mem_timing` | **3/3** | em qual ciclo exato cada acesso acontece |
| `mem_timing-2` | **3/3** | idem, versão mais rigorosa |
| `halt_bug` | **1/1** | o bug do HALT em todas as combinações |
| `oam_bug` | **7/8** | a corrupção da tabela de sprites |
| `dmg_sound` | **11/12** | registradores, duração, sweep, envelope, wave RAM |
| `cgb_sound` | n/a | exige Game Boy Color |
| `interrupt_time` | n/a | exige Game Boy Color |

As ROMs da Blargg são a régua com que emuladores são medidos, e vale entender
por quê. Todos os outros testes deste projeto foram escritos por quem escreveu o
emulador — e quem erra o entendimento de um comportamento erra o teste do mesmo
jeito, com os dois concordando sobre a coisa errada. As ROMs da Blargg foram
escritas por terceiros e calibradas contra o hardware real. Elas não sabem nada
sobre este projeto.

**Mooneye Test Suite: 68 de 89 aplicáveis.** Outra suíte de terceiros, mais dura
que a da Blargg em temporização. Passam inteiros os grupos de MBC2, MBC5, bits
inexistentes, DAA, interrupções e cópia de sprites; MBC1 e temporizador falham em
um caso cada. As 21 falhas restantes se concentram em dois lugares: a
temporização exata dos acessos de instruções de salto (diagnóstico feito, causa
isolada) e o instante da interrupção de vídeo.

**dmg-acid2: passa.** O teste de renderização — uma carinha que só sai certa se
prioridade de sprites, janela, espelhamento e paletas estiverem todos corretos.

**Mealybug Tearoom: 0 de 24.** Estas comparam a tela pixel a pixel com uma
captura de hardware real, e mudam registradores de vídeo *no meio* de uma linha.
Nossa PPU desenha a linha inteira de uma vez, então uma escrita no meio dela não
tem onde aparecer. Passar aqui exige uma PPU pixel a pixel — reescrita do módulo
de vídeo, não ajuste. O detalhe está em `levantamento-suites.md`.

### Rodando os testes

```
python tests/executar_todos.py            tudo
python tests/executar_todos.py --rapido   só os unitários, em segundos
python tests/test_blargg.py               só as ROMs, distribuídas entre núcleos
python tests/test_blargg.py cpu           só um grupo
python tests/test_mooneye.py              a suíte da Mooneye
python tests/test_mealybug.py             comparação de imagem com hardware real
python tests/test_timer.py                um arquivo isolado
```

Cada arquivo de teste é um programa comum e roda sozinho. Não há pytest: o mini
framework em `tests/harness.py` tem trinta linhas, e o motivo da escolha está
documentado lá.

As ROMs levam vários minutos em Python puro — algumas gastam dezenas de segundos
*emulados* só esperando contadores expirarem. O executor guarda o resultado de
cada uma, então dá para interromper com Ctrl+C e retomar.

### Testando o que normalmente não se testa

Dois arquivos cobrem o frontend, que costuma ficar de fora por precisar de
janela — e é justamente onde moravam os defeitos que mais estragavam a
experiência de jogar, invisíveis para qualquer teste de precisão.

`test_ritmo.py` reproduz o laço de quadros com um relógio virtual. `test_ui.py`
exercita os menus direto e entrega ao desenho um pygame de mentira que, em vez
de pintar, anota onde cada retângulo caiu — o bastante para provar que nada
escapa da janela, de 160x144 até 1280x1152. `test_frontend.py` roda o laço
inteiro com um roteiro de teclas.

Há ainda uma ferramenta de manutenção: `tests/conferir_documentacao.py` compara
a árvore sintática de duas versões do código, ignorando comentários e
docstrings. Ela prova que uma passada de documentação não mexeu em nada que
execute — foi assim que as 14 mil linhas deste projeto foram redocumentadas com
segurança.

---

## Desempenho

Python é uma escolha ruim para emular um processador, e o projeto assume isso.
A meta é acompanhar o console em tempo real, o que significa 4,2 milhões de
ciclos por segundo.

```
python tests/benchmark.py jogo.gb            velocidade bruta
python tests/benchmark.py jogo.gb --som      quanto o áudio custa
python tests/benchmark.py jogo.gb --perfil   onde o tempo está indo
python tests/benchmark.py jogo.gb --regs     compara as duas visões de registrador
```

O número que importa é o **"x tempo real"**. Olhar os quadros por segundo na
barra de título não mede o emulador: mede o limitador, que segura tudo em 59,7
de propósito.

### Vai rodar liso na sua máquina?

O requisito é objetivo: **4,19 MHz efetivos**, que é o relógio de um Game Boy.
O benchmark mostra quantos a sua máquina entrega.

    python tests/benchmark.py jogo.gb
      sem áudio        57.2 fps   0.95x tempo real   4.00 MHz

Acima de 4,19 MHz o jogo roda na velocidade certa com todos os quadros
desenhados; abaixo, o emulador começa a pular desenhos para manter o ritmo. O
desenho em si não pesa — a conversão de uma tela leva 58 µs, ou 0,3% do
orçamento de um quadro. O gargalo é sempre a emulação.

Dá para conferir sem benchmark, jogando: a barra de título mostra
`60 fps (100% da velocidade real)` quando está tudo desenhado, e acrescenta
`, N na tela` quando começa a pular. A segunda forma significa que a máquina
está no limite.

Medições nossas, para calibrar a expectativa: um computador atual roda Zelda a
100% sob CPython, com todos os quadros. Uma máquina modesta pode precisar do
PyPy — e o emulador avisa sozinho quando for o caso, com o número medido ali.

Rodar sob **PyPy** em vez do Python comum faz a maior diferença isolada — o
emulador passa de arrastado para folgado.

As otimizações aplicadas estão comentadas onde moram, com o número medido junto.
As três mais instrutivas:

- **`gb/registradores.py`** — a forma elegante de expressar a união entre
  registradores de 8 e 16 bits é justamente a que o compilador do PyPy não
  otimiza. Trocar por código aparentemente pior deu **6,2 vezes** mais
  velocidade.
- **`APU.sincronizar`** — o estado dos canais de som só é observável em três
  momentos, então o tempo é acumulado e pago neles, em vez de quatro chamadas de
  método por M-cycle. O resultado é idêntico, e não aproximado.
- **`PPU.linha_traduzida`** — um cache que existe porque a versão anterior
  alocava trezentos mil objetos por segundo, e o coletor de lixo devolvia isso
  em forma de engasgos no meio do jogo.

### Quando sobra velocidade e a imagem ainda engasga

Nesse caso o problema não é o emulador: é sincronização. O diagnóstico separa o
quadro em fases e diz quem está travando.

```
python main.py jogo.gb --som --diagnostico
```

| Fase que domina | Significa |
|---|---|
| `emulação` | falta velocidade bruta |
| `vídeo` | a entrega da imagem está esperando o monitor |
| `espera` | o limitador está dormindo demais |
| `áudio` | o mixer está bloqueando |
| picos isolados | coleta de lixo ou compilação do JIT |

Uma lição de método saiu daí: a fase mais demorada quase nunca é a culpada. A
espera é reativa — existe para preencher o tempo que sobrou — e por isso é a
maior fase de qualquer quadro saudável.

### Pulo de quadro

Quando a máquina não acompanha, existem duas saídas: o jogo roda em câmera lenta
ou aparecem menos quadros. O emulador escolhe a segunda, porque a emulação
continua exata — a CPU, os tempos e as interrupções seguem idênticos, e só o
desenho é pulado. O jogo mantém a velocidade certa.

Use `--pulo-maximo 0` para desligar e aceitar a câmera lenta.

> **Sobre "destravar o FPS":** num Game Boy, quadros por segundo *é* velocidade.
> Um quadro são exatamente 70224 ciclos; não há como desenhar mais rápido sem o
> jogo rodar acelerado — que é o que a tecla `Tab` faz de propósito. Um emulador
> mostrando 50 fps está a 0,83x, e não travado abaixo do que consegue.

---

## Limitações conhecidas

**Este é um emulador de Game Boy original (DMG).** Recursos exclusivos do Game
Boy Color — paletas coloridas, HDMA, banco duplo de memória, velocidade dobrada
— não são emulados. ROMs marcadas como exclusivas de Color são recusadas com
uma explicação, em vez de rodarem produzindo resultado errado em silêncio.

Duas ROMs de teste ainda falham, e nenhuma delas afeta jogos comerciais — são
justamente os comportamentos que os desenvolvedores da época aprenderam a
evitar:

- **`dmg_sound 10-wave trigger while on`** — a corrupção da memória de onda ao
  redisparar o canal. A leitura e a escrita durante a reprodução passam com a
  mesma janela de acesso, então a janela está certa; o que não bate é o efeito
  do redisparo. Três hipóteses já foram varridas sem sucesso: a condição de
  disparo, qual byte é copiado e o atraso do timer.

  Uma medição útil para quem for continuar: o teste faz o primeiro disparo com
  período de 212 clocks, caindo de 2 em 2, e só depois encurta o período para 4.
  Ou seja, ele varre o redisparo *através* da fronteira da busca — e nas
  primeiras iterações o canal sequer chega a buscar uma amostra entre os dois
  disparos, o que torna "timer igual a 4" e "acabou de buscar" condições
  **diferentes**, e não equivalentes como parece.

- **`oam_bug 8-instr_effect`** — o padrão de corrupção do `POP rr`. Qual
  instrução corrompe e em qual fileira já está certo; falta a fórmula exata
  desta variante.

---

## Créditos

As ROMs de teste em `tests/roms/` são de Shay Green (blargg) e da suíte Mooneye,
de Joonas Javanainen. Elas são o motivo de este emulador poder afirmar qualquer
coisa sobre a própria correção.
