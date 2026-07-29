"""
O cronômetro que encontra a causa dos engasgos.

Este arquivo não faz parte do console: é uma ferramenta de investigação, e nasceu
de um problema concreto. O emulador rodava a 300% da velocidade quando acelerado,
o que deveria ser folga de sobra — e mesmo assim engasgava a 60 quadros por
segundo. Sobrava capacidade e faltava fluidez ao mesmo tempo.

Medir o tempo total de cada quadro não responde isso. Diz que o quadro levou
25 ms e não diz o que fazer a respeito. A informação útil está na REPARTIÇÃO,
porque cada fase falha por um motivo diferente e pede uma correção diferente:

    eventos    ler o teclado
    emulação   rodar o console — se esta estoura, falta velocidade bruta
    desenho    converter a tela e ampliá-la
    vídeo      entregar a imagem, que pode BLOQUEAR esperando o monitor
    áudio      entregar as amostras
    espera     o limitador que segura o ritmo em 59,7 Hz

Um engasgo em "vídeo" com a emulação folgada é um problema de sincronia com a
tela, e otimizar o emulador não resolveria nada. Foi exatamente o que os dados
mostraram na primeira vez: a fase de espera respondia por 59% dos estouros
enquanto a emulação usava 4 ms de um orçamento de 16,7 — e a correção acabou
sendo pedir ao Windows um temporizador mais fino, que não tem nada a ver com
emulação.

Uma lição de método veio junto: a fase mais demorada quase nunca é a culpada. A
espera é reativa, existe só para preencher o tempo que sobrou, e por isso é a
maior fase de qualquer quadro saudável. Apontá-la de imediato levaria a otimizar
o lugar errado. Ver o critério de culpa em `relatorio`.
"""

import datetime
import platform
import sys
import time

# Sobe a cada mudança no que o relatório mede. Serve para não confundir um
# arquivo de execução antiga com um novo — já aconteceu de o relatório não ser
# regravado (uma saída por Ctrl+C pulava a gravação) e o arquivo velho passar
# por atual, levando a conclusões erradas.
VERSAO_DO_RELATORIO = 4

FASES = ("eventos", "emulação", "desenho", "vídeo", "áudio", "espera")


class Cronometro:
    """
    Mede quanto tempo cada fase de um quadro levou.

    Um cronômetro por fase, e não um por quadro. A diferença é o que faz a
    ferramenta valer: saber que o quadro levou 25 ms não diz nada sobre o que
    fazer a respeito, enquanto saber que 20 desses 25 foram gastos esperando o
    monitor manda otimizar um lugar completamente diferente de onde se olharia.
    """
    def __init__(self, orcamento_ms=None):
        # O quadro do Game Boy são 70224 ciclos a 4194304 Hz = 16,7427 ms.
        # Usar "1000/59,7" arredondado deslocava a fronteira e contava como
        # estouro quadros que estavam no ponto.
        self.orcamento_ms = orcamento_ms or (70224 / 4194304 * 1000.0)
        self.quadros = []          # lista de dicionários, um por quadro
        self._t = None
        self._atual = None

    # ------------------------------------------------------------------
    def novo_quadro(self):
        """Começa a medir um quadro. Zera as fases e marca o instante inicial."""
        self._atual = {f: 0.0 for f in FASES}
        self._atual["desenhou"] = True
        self._atual["turbo"] = False
        self._t = time.perf_counter()

    def marcar(self, fase):
        """
        Fecha a fase que estava correndo e começa a próxima.

        O tempo é medido entre marcações consecutivas, então a ordem das chamadas no
        laço do frontend define o que cada fase significa.
        """
        agora = time.perf_counter()
        self._atual[fase] = (agora - self._t) * 1000.0
        self._t = agora

    def fim_do_quadro(self, desenhou=True, turbo=False):
        """
        Fecha o quadro e o guarda.

        `desenhou` e `turbo` são anotados porque mudam a leitura do resultado: um
        quadro pulado de propósito não é um quadro lento, e no turbo não existe
        orçamento a cumprir.
        """
        self._atual["desenhou"] = desenhou
        self._atual["turbo"] = turbo
        self._atual["total"] = sum(self._atual[f] for f in FASES)
        self.quadros.append(self._atual)

    # ------------------------------------------------------------------
    def relatorio(self):
        """
        Monta o relatório em texto.

        A estrutura segue a ordem em que as perguntas aparecem na prática: primeiro
        quantos quadros chegaram à tela (que é o que se percebe jogando), depois onde
        o tempo foi gasto, depois quem causou os estouros, e por fim os piores casos
        individuais.

        Os percentis importam mais do que a média aqui. Engasgo é fenômeno de cauda:
        uma média boa convive perfeitamente com um quadro em cada cem levando 80 ms,
        e é justamente esse quadro que o jogador sente.
        """
        if not self.quadros:
            return "nenhum quadro medido"

        linhas = []
        add = linhas.append

        add("=" * 66)
        add(" DIAGNÓSTICO DE ENGASGOS — gb-py")
        add("=" * 66)
        agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        add(f" gerado em {agora}   (formato v{VERSAO_DO_RELATORIO})")
        add(f" {platform.python_implementation()} {platform.python_version()}"
            f" em {platform.machine()} / {platform.system()}")
        add(f" quadros medidos: {len(self.quadros)}"
            f"   orçamento por quadro: {self.orcamento_ms:.2f} ms")
        normais = [q for q in self.quadros if not q["turbo"]]
        em_turbo = len(self.quadros) - len(normais)
        desenhados = sum(1 for q in self.quadros if q["desenhou"])
        add(f" quadros desenhados: {desenhados}"
            f"   pulados: {len(self.quadros) - desenhados}")
        if em_turbo:
            add(f" quadros em turbo: {em_turbo}"
                f"   (no turbo o desenho é pulado de propósito)")
        if normais:
            d = sum(1 for q in normais if q["desenhou"])
            add(f" fora do turbo: {d}/{len(normais)} desenhados"
                f" ({100 * d / len(normais):.0f}%)"
                f"   <- ESTE é o número que decide a fluidez")
        add("")

        add(" TEMPO POR FASE (ms)")
        add(f" {'fase':<10} {'mediana':>9} {'p95':>9} {'p99':>9} {'pior':>9}"
            f" {'% do total':>11}")
        add(" " + "-" * 62)

        soma_total = sum(q["total"] for q in self.quadros)
        for fase in FASES + ("total",):
            v = sorted(q[fase] for q in self.quadros)
            n = len(v)
            soma = sum(v)
            add(f" {fase:<10} {v[n // 2]:9.2f} {v[int(n * .95)]:9.2f}"
                f" {v[min(n - 1, int(n * .99))]:9.2f} {v[-1]:9.2f}"
                f" {100 * soma / soma_total:10.1f}%")
        add("")

        # O turbo não tem orçamento a cumprir: incluí-lo aqui poluiria a conta.
        estourados = [q for q in self.quadros
                      if not q["turbo"] and q["total"] > self.orcamento_ms]
        base = len(normais) or 1
        add(f" QUADROS ACIMA DO ORÇAMENTO: {len(estourados)}/{len(normais)}"
            f" ({100 * len(estourados) / base:.1f}%)   [turbo não conta]")

        if estourados:
            # De quem é a culpa nos quadros que estouraram?
            #
            # Não basta pegar a maior fase: a ESPERA é reativa — ela existe só
            # para preencher o tempo que sobrou, então costuma ser a maior fase
            # de qualquer quadro saudável. Apontá-la como culpada mandaria
            # otimizar o limitador quando o problema é outro.
            #
            # O certo é olhar primeiro o TRABALHO (tudo menos a espera). Se ele
            # sozinho já estourou o orçamento, a culpa é da maior fase dele.
            # Só quando o trabalho coube e mesmo assim o quadro estourou é que
            # a espera é de fato a responsável — aí ela dormiu demais.
            trabalho = [f for f in FASES if f != "espera"]
            culpa = {}
            for q in estourados:
                soma_trabalho = sum(q[f] for f in trabalho)
                if soma_trabalho > self.orcamento_ms:
                    pior = max(trabalho, key=lambda f: q[f])
                else:
                    pior = "espera"
                culpa[pior] = culpa.get(pior, 0) + 1
            add(" quem realmente causou cada estouro:")
            for fase, n in sorted(culpa.items(), key=lambda kv: -kv[1]):
                add(f"   {fase:<10} {n:4d}  ({100 * n / len(estourados):.0f}%)")
            add("")

            add(" OS 10 PIORES QUADROS")
            add(f" {'total':>8} " + " ".join(f"{f:>8}" for f in FASES))
            add(" " + "-" * 62)
            for q in sorted(self.quadros, key=lambda q: -q["total"])[:10]:
                add(f" {q['total']:8.2f} "
                    + " ".join(f"{q[f]:8.2f}" for f in FASES))
        add("")

        add(" LEITURA DO RESULTADO")
        add("   um quadro perfeito dura exatamente o orçamento: nem mais, nem")
        add("   menos. Se a MEDIANA do total bate com ele, o ritmo está certo")
        add("   e o que sobra é a cauda.")
        add("")
        add("   emulação alta  → falta velocidade bruta; otimizar o emulador")
        add("   vídeo alto     → o flip() está esperando o vsync do monitor")
        add("   espera alta    → o limitador de quadros está dormindo demais")
        add("   áudio alto     → o mixer está bloqueando na entrega")
        add("   picos isolados → coleta de lixo ou compilação do JIT")
        add("=" * 66)
        return "\n".join(linhas)

    def salvar(self, caminho):
        """
        Grava o relatório e, abaixo dele, os dados brutos de cada quadro.

        O formato é separado por ponto e vírgula, para poder ser aberto numa planilha
        e virar gráfico. O relatório em texto responde às perguntas comuns; os dados
        brutos existem para as perguntas que ninguém previu.
        """
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(self.relatorio() + "\n")
            f.write("\n\n--- dados brutos (ms por quadro) ---\n")
            f.write("total;" + ";".join(FASES) + ";desenhou;turbo\n")
            for q in self.quadros:
                f.write(f"{q['total']:.3f};"
                        + ";".join(f"{q[f]:.3f}" for f in FASES)
                        + f";{int(q['desenhou'])};{int(q['turbo'])}\n")
        return caminho
