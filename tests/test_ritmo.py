"""
Testes do controle de ritmo do frontend.

Estes não medem o emulador, e sim o laço que decide QUANDO desenhar e QUANTO
esperar. Ele já escondeu dois defeitos que não aparecem em nenhum teste de
precisão e que arruinavam a experiência de jogar:

  1. o emulador se achava atrasado em todo quadro e desenhava só um a cada
     quatro — 15 quadros por segundo na tela, com a máquina tendo folga;
  2. ao soltar o turbo, o prazo acumulado no futuro era pago de uma vez, e o
     jogo congelava por segundos.

O laço é reproduzido aqui com um relógio virtual. O detalhe que faz o teste
valer é o `ATRASO_DO_SONO`: o sono do sistema nunca acorda no instante exato,
e é justamente esse resto que disparava o primeiro defeito. Sem ele, a
simulação passa nas duas versões e não prova nada.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import Suite                        # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from main import (INTERVALO_DO_QUADRO, PULO_MAXIMO_PADRAO,       # noqa: E402
                  MARGEM_MINIMA, MARGEM_MAXIMA)

s = Suite("Ritmo do frontend")

ATRASO_DO_SONO = 0.0003      # 0,3 ms de excesso, típico com temporizador de 1 ms


def simular(custo_emulacao, quadros=600, turbo_ate=0, pulo_maximo=PULO_MAXIMO_PADRAO,
            pausa=None, reancorar_no_menu=True):
    """
    Roda o mesmo raciocínio de `main.rodar_com_janela`, com relógio virtual.

    `pausa` é (quadro_inicial, quantos), simulando o menu aberto: o relógio
    anda, o console não. `reancorar_no_menu` existe só para o teste poder
    comparar com a versão que não reancorava.

    Devolve (quadros desenhados, total, maior espera num único quadro).
    """
    agora = 0.0
    prazo = 0.0
    desenhados = 0
    pulados_seguidos = 0
    maior_espera = 0.0
    inicio_da_pausa, duracao_da_pausa = pausa or (0, 0)

    for i in range(quadros):
        if duracao_da_pausa and inicio_da_pausa <= i < inicio_da_pausa + duracao_da_pausa:
            # Menu aberto: nada é emulado, mas o relógio do mundo continua.
            agora += INTERVALO_DO_QUADRO + ATRASO_DO_SONO
            if reancorar_no_menu:
                prazo = agora
            continue

        turbo = i < turbo_ate

        # --- prazo deste quadro (fixado no COMEÇO, não no fim) ---
        prazo += INTERVALO_DO_QUADRO
        if turbo:
            prazo = agora
        elif not (-0.25 < prazo - agora < 0.25):
            prazo = agora + INTERVALO_DO_QUADRO

        atrasado = agora > prazo
        desenhar = (not atrasado) or pulados_seguidos >= pulo_maximo
        pulados_seguidos = 0 if desenhar else pulados_seguidos + 1
        desenhados += desenhar

        agora += custo_emulacao / 3 if turbo else custo_emulacao

        if not turbo:
            espera = max(0.0, prazo - agora)
            maior_espera = max(maior_espera, espera)
            agora += espera + ATRASO_DO_SONO

    return desenhados, quadros, maior_espera


def teste_desenha_todos_os_quadros_com_folga():
    """Com a máquina sobrando, todo quadro emulado tem de virar quadro na tela."""
    desenhados, total, _ = simular(custo_emulacao=0.005)
    s.igual(desenhados, total,
            "nenhum quadro é pulado quando há folga de sobra")


def teste_pula_quadros_quando_falta_velocidade():
    """E quando falta velocidade, pular é o comportamento certo."""
    desenhados, total, _ = simular(custo_emulacao=0.030)   # 30 ms num orçamento de 16,7
    s.checar(desenhados < total,
             "quadros são pulados quando a máquina não acompanha",
             f"desenhou {desenhados} de {total}")
    s.checar(desenhados > total // (PULO_MAXIMO_PADRAO + 2),
             "mas o teto de pulos impede a imagem de congelar",
             f"desenhou {desenhados} de {total}")


def teste_sair_do_turbo_nao_congela():
    """
    Ao soltar o turbo, o prazo não pode ter corrido para o futuro.

    Sem reancorar, cada quadro de turbo adiantava o prazo em um quadro inteiro
    enquanto o relógio real mal andava; a primeira espera depois disso pagava
    tudo de uma vez.
    """
    _, _, maior_espera = simular(custo_emulacao=0.005, quadros=400, turbo_ate=180)
    s.checar(maior_espera < 2 * INTERVALO_DO_QUADRO,
             "a maior espera continua na ordem de um quadro",
             f"maior espera = {maior_espera * 1000:.0f} ms")


def teste_fechar_o_menu_nao_deixa_rastro():
    """
    Depois de fechar o menu, o jogo tem de voltar liso — não meio segundo
    engasgado.

    É o mesmo defeito do turbo, com outra roupa: enquanto o menu está aberto o
    relógio anda e o console não. Sem reancorar o prazo, ele fica para trás, o
    emulador se acha atrasado e pula o desenho até o prazo se recuperar
    sozinho. Não trava — só fica feio exatamente no instante em que o jogador
    volta a olhar para o jogo, que é o pior momento possível.

    O quarto de segundo de tolerância do laço esconde as pausas longas (ele
    reancora sozinho quando o descompasso passa de 0,25 s); quem escapa é a
    pausa CURTA, de quem abriu o menu e fechou logo em seguida.
    """
    def desenhados_depois(reancorar):
        desenhados = 0
        agora = prazo = 0.0
        pulados = 0
        for i in range(400):
            if 100 <= i < 110:                     # ~0,17 s de menu aberto
                agora += INTERVALO_DO_QUADRO + ATRASO_DO_SONO
                if reancorar:
                    prazo = agora
                continue
            prazo += INTERVALO_DO_QUADRO
            if not (-0.25 < prazo - agora < 0.25):
                prazo = agora + INTERVALO_DO_QUADRO
            desenhar = (agora <= prazo) or pulados >= PULO_MAXIMO_PADRAO
            pulados = 0 if desenhar else pulados + 1
            if i >= 110:
                desenhados += desenhar
            agora += 0.005
            espera = max(0.0, prazo - agora)
            agora += espera + ATRASO_DO_SONO
        return desenhados

    com = desenhados_depois(True)
    sem = desenhados_depois(False)
    s.igual(com, 290, "com o prazo reancorado, todo quadro depois do menu é desenhado")
    s.checar(sem < com,
             "e sem reancorar realmente se perdem quadros (senão o teste não prova nada)",
             f"{sem} contra {com} de 290")


def esperar(prazo, agora, margem, excesso_do_sono):
    """
    Reproduz a espera do frontend com relógio virtual.

    Devolve (novo agora, nova margem). `excesso_do_sono` é quanto o sistema
    passa do instante pedido — o número que varia por máquina e que a margem
    adaptativa precisa perseguir.
    """
    alvo = prazo - margem
    if alvo > agora:
        agora = alvo + excesso_do_sono
        if excesso_do_sono > margem:
            margem = min(MARGEM_MAXIMA, excesso_do_sono * 1.25)
        elif excesso_do_sono < margem * 0.5:
            margem = max(MARGEM_MINIMA, margem * 0.9995)
    if agora < prazo:                      # gira o resto
        agora = prazo
    return agora, margem


def teste_margem_absorve_sono_grosseiro():
    """
    Num sistema em que o sono passa 5,5 ms do pedido — medido num Windows com
    PyPy — a margem fixa de 1,6 ms fazia TODO quadro terminar depois do prazo.
    A margem adaptativa tem de crescer até engolir esse erro.

    O sintoma medido é "terminar atrasado", e não "durar mais": em regime o
    quadro dura sempre um intervalo, mesmo escorregando — o que escorrega é o
    instante em que ele acaba.
    """
    excesso = 0.0055

    def rodar(adaptativa):
        agora = 0.0
        prazo = 0.0
        margem = MARGEM_MINIMA if adaptativa else 0.0016
        atrasados = 0
        for _ in range(300):
            prazo += INTERVALO_DO_QUADRO
            agora += 0.005                                   # emula
            if adaptativa:
                agora, margem = esperar(prazo, agora, margem, excesso)
            else:
                alvo = prazo - margem
                if alvo > agora:
                    agora = alvo + excesso
                if agora < prazo:
                    agora = prazo
            if agora > prazo + 1e-9:
                atrasados += 1
        return atrasados

    fixos = rodar(adaptativa=False)
    s.checar(fixos > 250,
             "a margem fixa realmente atrasava (sem isso o teste não prova nada)",
             f"{fixos} de 300 quadros atrasados")

    adaptativos = rodar(adaptativa=True)
    s.checar(adaptativos < 5,
             "a margem adaptativa entrega os quadros no prazo",
             f"{adaptativos} de 300 atrasados")


def teste_margem_encolhe_onde_o_sono_e_preciso():
    """E onde o sono é bom, ela não fica queimando CPU girando à toa."""
    agora = 0.0
    prazo = 0.0
    margem = MARGEM_MAXIMA          # começa alta de propósito
    for _ in range(20000):
        prazo += INTERVALO_DO_QUADRO
        agora += 0.005
        agora, margem = esperar(prazo, agora, margem, 0.00005)
    s.checar(margem < MARGEM_MINIMA * 3,
             "a margem encolhe quando o sono do sistema é preciso",
             f"margem final = {margem * 1000:.2f} ms")


def teste_margem_aguenta_sono_irregular():
    """
    O caso realista: o sono do sistema não erra sempre igual — às vezes passa
    1 ms, às vezes 7. A margem tem de lembrar do PIOR caso recente, senão
    encolhe nos sonos bons e é pega pelos ruins.
    """
    import random
    random.seed(9)
    agora = 0.0
    prazo = 0.0
    margem = MARGEM_MINIMA
    atrasados = 0
    for i in range(3000):
        prazo += INTERVALO_DO_QUADRO
        agora += 0.005
        excesso = random.choice([0.0005, 0.001, 0.002, 0.007])
        agora, margem = esperar(prazo, agora, margem, excesso)
        if i > 100 and agora > prazo + 1e-9:      # ignora o aquecimento
            atrasados += 1
    s.checar(atrasados < 30,
             "poucos atrasos mesmo com sono irregular",
             f"{atrasados} de 2900 quadros")


def teste_ritmo_segue_a_taxa_do_console():
    """O alvo é 59,7275 Hz do Game Boy, não os 60 Hz redondos."""
    s.checar(abs(1 / INTERVALO_DO_QUADRO - 59.7275) < 0.01,
             "o intervalo do quadro corresponde a 59,7275 Hz",
             f"{1 / INTERVALO_DO_QUADRO:.4f} Hz")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("teste_"):
            fn()
    sys.exit(0 if s.relatorio() else 1)
