# Levantamento das suítes de teste ainda não medidas

Feito em julho de 2026. As ROMs da Blargg já estavam cobertas (36/38); este
documento cobre o que faltava: a Mooneye, o dmg-acid2 e a Mealybug.

O placar atual, em uma linha: **Blargg 36/38, Mooneye 68/89, dmg-acid2 passa,
Mealybug 0/24.**

---

## Mooneye Test Suite — 68 de 89 aplicáveis (76%)

Das 115 ROMs, 24 exigem hardware que este emulador não é (Game Boy Color, Super
Game Boy, Game Boy Advance, ou a primeira revisão do DMG) e ficam fora de escopo.

    python tests/test_mooneye.py            roda tudo o que se aplica
    python tests/test_mooneye.py timer      só um grupo

| Grupo | Resultado | |
|---|---|---|
| `acceptance/bits` | **2/2** | leitura dos bits inexistentes |
| `acceptance/instr` | **1/1** | a instrução DAA |
| `acceptance/interrupts` | **1/1** | o quirk do push sobre o IE |
| `acceptance/oam_dma` | **2/2** | início, reinício e duração da cópia |
| `emulator-only/mbc2` | **7/7** | bancos, RAM de 4 bits e bits sem uso |
| `emulator-only/mbc5` | **8/8** | todos os tamanhos de ROM |
| `acceptance/timer` | 12/13 | falha só `rapid_toggle` |
| `emulator-only/mbc1` | 12/13 | falha só o multicart |
| `acceptance` (raiz) | 20/30 | os nove de temporização, mais `boot_div` |
| `acceptance/ppu` | 2/7 | temporização de interrupção de vídeo |
| `acceptance/serial` | 0/1 | alinhamento do relógio serial no boot |
| `madness` / `manual-only` / `utils` | 1/4 | casos extremos |

### Uma correção de método que rendeu sete testes

Os sete `bits_*` de MBC1 e MBC2 apareciam como falha, e este documento chegou a
trazer um diagnóstico atribuindo a causa a detalhes de máscara de bits dos
controladores. O diagnóstico estava errado: os sete **passam**.

O que havia era um limite de tempo mal escolhido no executor. Ele tinha sido
reduzido de 8 para 2 segundos emulados para a suíte terminar mais rápido, na
suposição de que os testes da Mooneye são todos curtos. Estes sete varrem todos
os valores possíveis de um registrador e comparam a memória a cada passo:
precisam de 3 a 6 segundos. Com 2, terminavam sem anunciar resultado — e "sem
anunciar" era contado como falha.

O limite agora é 10 segundos, e o comentário em `tests/test_mooneye.py` conta a
história no lugar onde ela importa. Vale a moral: um limite que reprova um teste
correto é pior do que uma suíte lenta. Ninguém confunde lentidão com defeito, mas
um falso negativo vira diagnóstico — e virou.

### As falhas, agrupadas por causa provável

**Nove testes de temporização de instrução** (`jp_timing`, `jp_cc_timing`,
`call_timing`, `call_cc_timing`, `ret_timing`, `ret_cc_timing`, `reti_timing`,
`add_sp_e_timing`, `ld_hl_sp_e_timing`) falham todos do mesmo jeito, e o
diagnóstico está feito.

Eles medem em qual M-cycle exato a instrução lê a memória, e usam o OAM DMA como
régua: durante a cópia, qualquer leitura devolve 0xFF. O teste dispara o DMA,
espera um número calibrado de ciclos, e salta para um endereço da WRAM. Se o
tempo estiver certo, o código de lá executa; se o DMA ainda estiver ativo, a CPU
lê 0xFF — que é o opcode `RST 38` — e entra num laço.

Foi exatamente o que medi: no instante do salto, o nosso DMA está no byte **155
de 160**, cinco M-cycles atrasado em relação ao esperado. A WRAM tem o código
certo (`C3 CA`); é o bloqueio do barramento que o esconde.

A hipótese óbvia — o atraso de partida do DMA — foi **testada e descartada**.
Variando o atraso de 0 a 3, o valor 2 (o que já usamos) é o único que passa nos
três testes de `oam_dma`, e nenhum valor faz os `*_timing` passarem. O erro está
em outro lugar da contagem.

**Dois testes de estado pós-boot** ainda falham: `boot_div`, que depende do byte
baixo do contador do DIV — um valor que a documentação não traz e que
`tests/varrer_div.py` procurou nos 256 candidatos possíveis sem achar; e
`boot_sclk_align`, do alinhamento do relógio serial. O `boot_hwio` passou depois
de os 40 registradores de hardware serem conferidos um a um contra a Pan Docs.

**Cinco de temporização de vídeo** (`intr_2_*`, `stat_lyc_onoff`) medem o
instante da interrupção de STAT com precisão maior do que a nossa PPU orientada a
eventos oferece.

---

## dmg-acid2 — passa

O teste de renderização do Matt Currie. Ele desenha uma carinha cujos detalhes só
saem certos se a PPU acertar prioridade de sprites, janela, espelhamento e
paletas. A nossa imagem sai correta, com o texto "HELLO WORLD!" no topo e a
assinatura embaixo.

Para reproduzir:

    python main.py roms/dmg-acid2.gb --frames 90 --png acid2.png

---

## Mealybug Tearoom — 0 de 24 com referência de DMG

Com as imagens de referência em mãos, agora há placar, e ele é zero.

    python tests/test_mealybug.py             compara com as capturas reais
    python tests/test_mealybug.py --auditar   confere o próprio comparador

Das 31 ROMs, 7 só têm captura de Game Boy Color e ficam de fora. As 24 restantes
são comparadas pixel a pixel com um PNG tirado de hardware de verdade, e o
critério é igualdade exata: um pixel diferente reprova.

O resultado não é ruído — é estrutural, e dá para ver a olho. Nossa tela sai em
faixas HORIZONTAIS, uma paleta por linha; a referência sai em faixas VERTICAIS,
com a paleta mudando no meio da linha. É exatamente o que estas ROMs testam:
elas escrevem nos registradores de vídeo enquanto a linha está sendo desenhada.

A nossa PPU desenha a linha inteira de uma vez, no fim do modo 3, usando os
registradores como estão naquele instante. Uma escrita no meio da linha não tem
onde aparecer. Passar aqui exige uma PPU pixel a pixel (com as duas filas de
pixels do hardware), que é uma reescrita do módulo de vídeo — não um ajuste.

As diferenças menores da lista (10 pixels em `m3_wx_4_change_sprites`, 432 em
`m3_obp0_change`) mostram que o resto da PPU está bom: o erro se concentra
justamente onde o registrador muda durante a linha.
