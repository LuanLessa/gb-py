"""
A Mooneye Test Suite — a régua mais fina que existe para temporização.

Se as ROMs da Blargg medem se o emulador acerta o COMPORTAMENTO do hardware, as
da Mooneye medem se ele acerta o INSTANTE. São dezenas de testes que fazem uma
coisa só: escrevem num registrador exatamente N ciclos depois de outro evento e
conferem o resultado. Errar por um único M-cycle reprova.

Foram escritas por Joonas Javanainen como parte de um projeto de pesquisa sobre
o console, e boa parte do que se sabe hoje sobre a temporização do Game Boy saiu
delas.


COMO ELAS RELATAM O RESULTADO
-----------------------------

Aqui não há texto nem serial. O protocolo é engenhoso e cabe em duas linhas: ao
terminar, a ROM coloca os seis primeiros números de Fibonacci nos registradores
e executa `ld b,b`.

    B=3  C=5  D=8  E=13  H=21  L=34      passou
    todos = 0x42                          falhou

A escolha de Fibonacci não é decoração: é uma sequência que dificilmente
apareceria por acidente nos seis registradores ao mesmo tempo. E o `ld b,b` é um
opcode que não faz nada — no emulador BGB ele funciona como ponto de parada, o
que permite examinar o estado na hora exata.

Este executor não implementa ponto de parada nenhum: ele roda a ROM por um
tempo e depois olha os registradores. Dá no mesmo, porque as ROMs entram num
laço infinito depois de anunciar o resultado.


O QUE ESTÁ FORA DE ESCOPO
-------------------------

O nome do arquivo diz qual hardware a ROM exige, e isso importa porque uma parte
da suíte testa modelos que este emulador não é:

    (sem sufixo)   qualquer modelo
    -dmgABCmgb     as revisões de DMG e o Game Boy Pocket  → vale para nós
    -dmgABC        só as revisões de DMG                   → vale para nós
    -dmg0          a primeira revisão do DMG, diferente das outras
    -mgb           só o Pocket
    -C, -cgb...    Game Boy Color
    -S, -sgb       Super Game Boy
    -A             Game Boy Advance
    -GS            Game Boy Color OU Super Game Boy

As que exigem outro hardware não contam como falha: contam como fora de escopo,
pela mesma razão explicada em `harness.py`.

    python tests/test_mooneye.py            roda tudo o que se aplica
    python tests/test_mooneye.py timer      só os grupos com "timer" no nome
    python tests/test_mooneye.py "" 1       sem paralelismo
"""

import os
import sys
import time
from multiprocessing import Pool, cpu_count

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gb.cartridge import Cartridge          # noqa: E402
from gb.machine import Machine              # noqa: E402
from gb.constants import A, B, C, D, E, H, L  # noqa: E402

# Onde procurar a suíte. A pasta vem com um nome que inclui a data da versão,
# então a busca é por padrão em vez de caminho fixo.
RAIZ_DO_PROJETO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# O resultado, em Fibonacci.
PASSOU = {B: 3, C: 5, D: 8, E: 13, H: 21, L: 34}
FALHOU = 0x42

# Sufixos que indicam hardware que este emulador não é. A comparação é por
# PREFIXO porque as revisões viram sufixos próprios: além de `-cgb` existem
# `-cgb0`, `-cgbABCDE` e outros, e listar um por um deixaria escapar o seguinte
# — foi o que aconteceu com o `-cgb0` na primeira execução.
FORA_DE_ESCOPO = ("-C", "-cgb", "-S", "-sgb", "-A", "-GS", "-mgb", "-dmg0")


def _fora_de_escopo(sufixo):
    return sufixo is not None and any(sufixo.startswith(p) for p in FORA_DE_ESCOPO)

# Tempo emulado máximo por ROM.
#
# ESTE NÚMERO JÁ MENTIU UMA VEZ, e vale contar como.
#
# A primeira versão usava 8 segundos. Para a suíte rodar mais rápido, baixei
# para 2, com o raciocínio de que "os testes da Mooneye são curtos por natureza".
# Sete testes de MBC passaram a aparecer como "esgotou o tempo sem anunciar", e
# eu os relatei como falhas do emulador — cheguei a escrever um diagnóstico
# atribuindo a causa a detalhes de máscara de bits dos controladores.
#
# Não era nada disso. Os sete PASSAM; só precisam de 3 a 6 segundos emulados.
# Eles varrem todos os valores possíveis de um registrador, e cada iteração faz
# uma comparação de memória em assembly — é trabalho de verdade, não trava.
#
# A lição: um limite de tempo que reprova um teste correto é pior do que uma
# suíte lenta, porque a suíte lenta ninguém confunde com bug. Dez segundos dão
# folga de quase o dobro do caso mais demorado que existe aqui, e só custam
# tempo nas ROMs que travam de fato — porque toda ROM que conclui, passando ou
# falhando, ANUNCIA e sai na hora.
SEGUNDOS_EMULADOS = 10


def achar_suite():
    """Localiza a pasta da Mooneye, onde ela estiver."""
    for raiz, pastas, _ in os.walk(RAIZ_DO_PROJETO):
        if "acceptance" in pastas and "emulator-only" in pastas:
            return raiz
    return None


def hardware_do_nome(nome):
    """
    Devolve o sufixo de hardware do nome do arquivo, ou None.

    O sufixo é o que vem depois do último `-` antes da extensão, e só conta como
    sufixo de hardware se estiver na lista conhecida — nomes como
    `di_timing-GS.gb` têm sufixo, mas `add_sp_e_timing.gb` não tem.
    """
    base = os.path.splitext(nome)[0]
    if "-" not in base:
        return None
    sufixo = "-" + base.rsplit("-", 1)[1]
    return sufixo


def se_aplica(nome):
    """Esta ROM pode ser executada num DMG?"""
    return not _fora_de_escopo(hardware_do_nome(nome))


def rodar_uma(caminho):
    """
    Roda uma ROM e lê os registradores no fim.

    Devolve "passou", "falhou" ou "indeciso" — o último para as ROMs que
    esgotaram o tempo sem anunciar nada, o que costuma significar que o emulador
    travou em algum lugar.
    """
    nome = os.path.basename(caminho)
    try:
        cart = Cartridge.from_file(caminho)
        m = Machine(cart)
        m.reset()
    except Exception as e:
        return nome, "erro", f"{type(e).__name__}: {e}"

    limite = 4194304 * SEGUNDOS_EMULADOS
    reg = m.cpu.reg8
    try:
        while m.cycles < limite:
            for _ in range(20000):
                m.cpu.step()
            # Confere o padrão a cada lote. As ROMs ficam num laço depois de
            # anunciar, então não há risco de perder o instante.
            if all(reg[r] == v for r, v in PASSOU.items()):
                return nome, "passou", ""
            if all(reg[r] == FALHOU for r in (B, C, D, E, H, L)):
                return nome, "falhou", "registradores em 0x42"
    except Exception as e:
        pc = m.cpu.reg16[5]
        return nome, "erro", f"{type(e).__name__}: {e} (PC={pc:04X})"

    if all(reg[r] == v for r, v in PASSOU.items()):
        return nome, "passou", ""
    if all(reg[r] == FALHOU for r in (B, C, D, E, H, L)):
        return nome, "falhou", "registradores em 0x42"
    return nome, "indeciso", "esgotou o tempo sem anunciar"


def _tarefa(args):
    grupo, caminho = args
    nome, veredito, motivo = rodar_uma(caminho)
    return grupo, nome, veredito, motivo


def main(argv):
    filtro = argv[1] if len(argv) > 1 else ""
    processos = int(argv[2]) if len(argv) > 2 else max(1, cpu_count())

    suite = achar_suite()
    if suite is None:
        print("não achei a pasta da Mooneye (procurei por 'acceptance' + "
              "'emulator-only' a partir da raiz do projeto).")
        return 2

    print("=" * 70)
    print(" MOONEYE TEST SUITE")
    print("=" * 70)
    print(f" suíte em: {os.path.relpath(suite, RAIZ_DO_PROJETO)}")

    tarefas = []
    ignoradas = []
    for raiz, _, arquivos in os.walk(suite):
        for nome in sorted(arquivos):
            if not nome.endswith(".gb"):
                continue
            caminho = os.path.join(raiz, nome)
            grupo = os.path.relpath(raiz, suite).replace("\\", "/")
            if grupo == ".":
                grupo = "(raiz)"
            if filtro and filtro not in grupo and filtro not in nome:
                continue
            if not se_aplica(nome):
                ignoradas.append((grupo, nome, hardware_do_nome(nome)))
                continue
            tarefas.append((grupo, caminho))

    print(f" {len(tarefas)} ROMs aplicáveis, {len(ignoradas)} fora de escopo")
    print(f" rodando em {processos} processo(s)\n")

    t0 = time.time()
    resultados = []
    # `imap_unordered` entrega cada resultado assim que ele sai, em vez de
    # esperar por todos. Numa suíte que leva minutos, ver o progresso é a
    # diferença entre acompanhar e ficar adivinhando se travou.
    if processos > 1:
        with Pool(processos) as p:
            for i, r in enumerate(p.imap_unordered(_tarefa, tarefas), 1):
                resultados.append(r)
                marca = "x" if r[2] != "passou" else "."
                print(f"   [{i:>3}/{len(tarefas)}] {marca} {r[1]}", flush=True)
    else:
        for i, t_ in enumerate(tarefas, 1):
            r = _tarefa(t_)
            resultados.append(r)
            marca = "x" if r[2] != "passou" else "."
            print(f"   [{i:>3}/{len(tarefas)}] {marca} {r[1]}", flush=True)
    print()

    # ------------------------------------------------------------------
    por_grupo = {}
    for grupo, nome, veredito, motivo in resultados:
        por_grupo.setdefault(grupo, []).append((nome, veredito, motivo))

    total_ok = 0
    for grupo in sorted(por_grupo):
        itens = sorted(por_grupo[grupo])
        ok = sum(1 for _, v, _ in itens if v == "passou")
        total_ok += ok
        marca = "OK " if ok == len(itens) else "   "
        print(f" {marca} {grupo:<28} {ok}/{len(itens)}")
        for nome, veredito, motivo in itens:
            if veredito != "passou":
                extra = f"  ({motivo})" if motivo else ""
                print(f"       x {nome:<44}{extra}")

    print()
    print("=" * 70)
    n = len(resultados)
    print(f" TOTAL: {total_ok}/{n} aplicáveis"
          f"   ({100 * total_ok / n:.0f}%)" if n else " nada rodou")
    if ignoradas:
        print(f" fora de escopo: {len(ignoradas)} ROMs que exigem outro modelo")
    print(f" tempo: {time.time() - t0:.0f}s")
    print("=" * 70)
    return 0 if total_ok == n else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
