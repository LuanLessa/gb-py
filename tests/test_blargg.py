"""
As ROMs de teste da Blargg — a régua com que emuladores são medidos.

Todos os testes das outras pastas foram escritos por quem escreveu o emulador, e
isso é um limite conhecido: quem erra o entendimento de um comportamento erra o
teste do mesmo jeito, e os dois concordam alegremente sobre a coisa errada.

As ROMs daqui não têm esse problema. São programas de Game Boy escritos por
terceiros, calibrados contra o hardware de verdade, e não sabem nada sobre este
projeto. Elas exercitam comportamentos que ninguém pensaria em testar — o valor
exato dos bits que não existem num registrador, o M-cycle preciso em que um
contador recarrega, o que acontece ao escrever num registrador no instante em
que outro chip o está lendo.

Passar nelas é o que separa "roda a maioria dos jogos" de "é um emulador".

    python tests/test_blargg.py            tudo
    python tests/test_blargg.py cpu        só os grupos com "cpu" no nome
    python tests/test_blargg.py "" 1       tudo, sem paralelismo
    python tests/test_blargg.py --limpar   ignora o cache e roda tudo de novo
    python tests/test_blargg.py --resumo   só reimprime o placar já apurado

Emulação em Python puro roda a cerca de metade da velocidade real, e as ROMs de
som gastam dezenas de segundos EMULADOS só esperando contadores de duração
expirarem. Daí as duas providências: distribuir as ROMs entre os núcleos
disponíveis, e guardar o resultado de cada uma para poder retomar.
"""

import glob
import json
import multiprocessing
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import ROMS, rodar_rom       # noqa: E402

# Cada ROM concluída é anotada aqui. Rodar a suíte inteira em Python leva
# vários minutos; se a execução for interrompida, a próxima retoma de onde
# parou em vez de recomeçar do zero.
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".resultados.json")

# (nome do grupo, padrão de arquivos, tempo EMULADO máximo em segundos)
GRUPOS = [
    ("cpu_instrs",     "blargg/cpu_instrs/individual/*.gb",        60),
    ("instr_timing",   "blargg/instr_timing/instr_timing.gb",      20),
    ("mem_timing",     "blargg/mem_timing/individual/*.gb",        20),
    ("mem_timing-2",   "blargg/mem_timing-2/rom_singles/*.gb",     20),
    ("halt_bug",       "blargg/halt_bug.gb",                       20),
    ("oam_bug",        "blargg/oam_bug/rom_singles/*.gb",          60),
    ("dmg_sound",      "blargg/dmg_sound/rom_singles/*.gb",       180),
    ("cgb_sound",      "blargg/cgb_sound/rom_singles/*.gb",       180),
]

# ROMs que NÃO podem passar num emulador de Game Boy DMG. As marcadas com
# 0xC0 no cabeçalho são detectadas sozinhas pelo harness; esta lista é só para
# as que "parecem" de DMG mas foram montadas esperando um Color.
INAPLICAVEIS = {
    "interrupt_time.gb": "exige Game Boy Color (modo de velocidade dobrada)",
}


def _tarefa(args):
    grupo, path, limite = args
    r = rodar_rom(path, max_segundos_emulados=limite)
    # A chave é o caminho relativo, e não o nome do arquivo: grupos diferentes
    # têm ROMs homônimas (mem_timing e mem_timing-2, por exemplo).
    return {"chave": os.path.relpath(path, ROMS), "grupo": grupo,
            "nome": r.nome, "passou": r.passou, "texto": r.texto,
            "motivo": r.motivo, "segundos": r.segundos,
            "aplicavel": r.aplicavel}


def carregar_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return {d["chave"]: d for d in json.load(f)}
    except (OSError, ValueError):
        return {}


def gravar_cache(feitos):
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(list(feitos.values()), f, ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE)


def inconclusivo(d):
    """Estourar o tempo não é o mesmo que falhar: a ROM só não terminou."""
    return "estourou" in (d.get("motivo") or "")


def linha(d):
    if not d.get("aplicavel", True):
        marca = "n/a"
    elif inconclusivo(d):
        marca = "LENTA"
    else:
        marca = "PASSOU" if d["passou"] else "FALHOU"
    extra = d["motivo"] or d["texto"]
    return f"  {marca:>6}  {d['nome']:<32} {extra}   [{d['segundos']:.0f}s]"


def main():
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    opcoes = {a for a in sys.argv[1:] if a.startswith("--")}

    filtro = argumentos[0] if argumentos else ""
    processos = int(argumentos[1]) if len(argumentos) > 1 else max(1, os.cpu_count() or 1)

    feitos = {} if "--limpar" in opcoes else carregar_cache()
    if "--limpar" in opcoes:
        gravar_cache(feitos)

    so_resumo = "--resumo" in opcoes      # não roda nada, só relê o cache

    tarefas = []
    ordem = []
    for nome, padrao, limite in GRUPOS:
        if filtro and filtro not in nome:
            continue
        arquivos = sorted(glob.glob(os.path.join(ROMS, padrao)))
        if not arquivos:
            print(f"[{nome}] nenhuma ROM encontrada")
            continue
        ordem.append(nome)
        if so_resumo:
            continue
        for path in arquivos:
            if os.path.relpath(path, ROMS) in feitos:
                continue
            tarefas.append((nome, path, limite))

    if tarefas:
        print(f"{len(tarefas)} ROMs a rodar ({len(feitos)} já em cache), "
              f"{processos} processo(s)\n", flush=True)
        t0 = time.time()
        try:
            if processos > 1:
                with multiprocessing.Pool(processos) as pool:
                    # chunksize=1: cada resultado aparece assim que fica pronto
                    for d in pool.imap_unordered(_tarefa, tarefas, chunksize=1):
                        print(linha(d), flush=True)
                        feitos[d["chave"]] = d
                        gravar_cache(feitos)
            else:
                for t in tarefas:
                    d = _tarefa(t)
                    print(linha(d), flush=True)
                    feitos[d["chave"]] = d
                    gravar_cache(feitos)
        except KeyboardInterrupt:
            print(f"\ninterrompido após {time.time() - t0:.0f}s — "
                  f"rode de novo para continuar de onde parou")
            return 2

    # ------------------------------------------------------------------
    print("\n" + "=" * 64)
    total_ok = total = 0
    for nome in ordem:
        todos = [d for d in feitos.values() if d["grupo"] == nome]
        if not todos:
            continue
        aplicaveis = [d for d in todos if d.get("aplicavel", True)]
        do_grupo = [d for d in aplicaveis if not inconclusivo(d)]
        fora = len(todos) - len(aplicaveis)
        lentas = len(aplicaveis) - len(do_grupo)

        if not do_grupo:
            print(f" n/a  {nome:<18} {fora} ROM(s) exigem Game Boy Color")
            continue

        ok = sum(d["passou"] for d in do_grupo)
        marca = "OK" if ok == len(do_grupo) else "--"
        sufixo = f"   (+{fora} n/a)" if fora else ""
        if lentas:
            sufixo += f"   (+{lentas} sem veredito: lenta demais para o limite)"
        print(f" {marca}  {nome:<18} {ok}/{len(do_grupo)}{sufixo}")
        for d in sorted(do_grupo, key=lambda d: d["chave"]):
            if not d["passou"]:
                print(f"        x {d['nome']}: {d['motivo'] or d['texto']}")
        total_ok += ok
        total += len(do_grupo)
    print("=" * 64)
    print(f" TOTAL: {total_ok}/{total}")

    for nome, motivo in INAPLICAVEIS.items():
        print(f" n/a  {nome}: {motivo}")

    return 0 if total_ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
