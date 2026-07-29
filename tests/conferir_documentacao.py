"""
Confere que uma passada de documentação não mexeu no comportamento.

Reescrever comentário em milhares de linhas tem um risco óbvio: junto com o
comentário, sai uma linha de código. E o pior tipo de erro assim é o que não
quebra teste nenhum — uma máscara que sumiu, um parâmetro que virou outro.

A checagem aqui não depende de ler com atenção. Ela compara a ÁRVORE SINTÁTICA
dos dois arquivos: o que o Python realmente vai executar, já sem comentários
(que o interpretador descarta) e sem docstrings (que a ferramenta remove). Se
as duas árvores forem idênticas, os arquivos executam exatamente a mesma
coisa, por mais diferente que o texto pareça.

    python tests/conferir_documentacao.py antes/ depois/
    python tests/conferir_documentacao.py antes/gb/cpu.py gb/cpu.py

Vale para qualquer refatoração que prometa não mudar comportamento, não só
para documentação.
"""

import ast
import os
import sys


def _sem_docstrings(no):
    """
    Remove as docstrings da árvore, no lugar onde elas moram.

    Uma docstring não é um tipo especial de nó: é só uma string solta como
    primeiro comando de um módulo, classe ou função. Então é isso que se
    procura — e retirá-la é o que permite comparar duas versões do mesmo
    arquivo documentadas de formas diferentes.
    """
    for filho in ast.walk(no):
        if not isinstance(filho, (ast.Module, ast.ClassDef,
                                  ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        corpo = filho.body
        if (corpo and isinstance(corpo[0], ast.Expr)
                and isinstance(corpo[0].value, ast.Constant)
                and isinstance(corpo[0].value.value, str)):
            corpo = corpo[1:]

        # Um corpo que sobrou vazio e um corpo com só um `pass` executam
        # exatamente a mesma coisa: nada. Tratá-los como formas diferentes
        # acusaria mudança de comportamento num arquivo que ganhou apenas uma
        # docstring — foi o que aconteceu com o `gb/__init__.py`, que era vazio.
        if len(corpo) == 1 and isinstance(corpo[0], ast.Pass):
            corpo = []
        filho.body = corpo
    return no


def esqueleto(caminho):
    """O código do arquivo, sem comentários e sem docstrings, como texto."""
    with open(caminho, "r", encoding="utf-8") as f:
        arvore = ast.parse(f.read(), filename=caminho)
    return ast.dump(_sem_docstrings(arvore), indent=1)


def comparar(antes, depois):
    """Devolve (iguais, motivo)."""
    try:
        a = esqueleto(antes)
    except SyntaxError as e:
        return False, f"não compila (versão antiga): {e}"
    try:
        d = esqueleto(depois)
    except SyntaxError as e:
        return False, f"não compila: {e}"

    if a == d:
        return True, ""

    # Mostrar a primeira linha diferente da árvore ajuda muito mais do que
    # dizer só "são diferentes": ela nomeia o nó que mudou.
    linhas_a, linhas_d = a.splitlines(), d.splitlines()
    for i, (la, ld) in enumerate(zip(linhas_a, linhas_d)):
        if la != ld:
            return False, (f"a árvore diverge na posição {i}:\n"
                           f"       antes: {la.strip()[:90]}\n"
                           f"      depois: {ld.strip()[:90]}")
    return False, (f"uma árvore é mais longa que a outra "
                   f"({len(linhas_a)} contra {len(linhas_d)} nós)")


def _arquivos_python(raiz):
    if os.path.isfile(raiz):
        return {os.path.basename(raiz): raiz}
    achados = {}
    for pasta, _, arquivos in os.walk(raiz):
        if "__pycache__" in pasta:
            continue
        for nome in arquivos:
            if nome.endswith(".py"):
                caminho = os.path.join(pasta, nome)
                achados[os.path.relpath(caminho, raiz)] = caminho
    return achados


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip())
        return 2

    antes, depois = argv[1], argv[2]
    if os.path.isfile(antes) != os.path.isfile(depois):
        print("compare arquivo com arquivo, ou pasta com pasta.")
        return 2

    de = _arquivos_python(antes)
    para = _arquivos_python(depois)

    problemas = 0
    conferidos = 0
    for relativo in sorted(de):
        if relativo not in para:
            print(f"  --  {relativo}: só existe na versão antiga")
            continue
        iguais, motivo = comparar(de[relativo], para[relativo])
        conferidos += 1
        if iguais:
            print(f"  ok  {relativo}")
        else:
            problemas += 1
            print(f"  XX  {relativo}: {motivo}")

    novos = sorted(set(para) - set(de))
    for relativo in novos:
        print(f"  ++  {relativo}: arquivo novo (nada a comparar)")

    print()
    if problemas:
        print(f"{problemas} de {conferidos} arquivos MUDARAM de comportamento.")
    else:
        print(f"{conferidos} arquivos conferidos: só a documentação mudou.")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
