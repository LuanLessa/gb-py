"""
Preferências que sobrevivem a fechar a janela.

O arquivo é um JSON simples ao lado do `main.py`. Duas regras guiam o módulo:

  * ele NUNCA pode derrubar o emulador. Um JSON corrompido, um disco cheio ou
    uma pasta sem permissão de escrita têm de virar "seguiu com os padrões", e
    não um traceback antes do jogo abrir;
  * um valor desconhecido no arquivo (escrito à mão, ou sobrado de uma versão
    anterior) tem de ser ignorado em favor do padrão. Aceitar `escala: 400`
    abriria uma janela maior que o monitor, sem volta pela própria interface.

Por isso todo valor passa por uma validação na leitura, e a gravação é
atômica: escrevemos num arquivo temporário e só então o renomeamos por cima do
antigo. Um desligamento no meio da gravação deixa o arquivo velho intacto em
vez de um pela metade.
"""

import json
import os
import tempfile

# nome → (padrão, validador)
#
# O validador devolve o valor corrigido, ou None para "descarte, use o padrão".
def _inteiro(minimo, maximo):
    def validar(v):
        if isinstance(v, bool) or not isinstance(v, int):
            return None
        return min(maximo, max(minimo, v))
    return validar


def _booleano(v):
    return v if isinstance(v, bool) else None


def _texto(v):
    return v if isinstance(v, str) else None


def _texto_ou_nada(v):
    return v if v is None or isinstance(v, str) else None


CAMPOS = {
    "ultima_rom":  (None,   _texto_ou_nada),   # caminho do último jogo aberto
    "ultima_pasta": (None,  _texto_ou_nada),   # onde o seletor estava
    "escala":      (3,      _inteiro(1, 8)),
    "som":         (True,   _booleano),
    "volume":      (70,     _inteiro(0, 100)),
    "paleta":      ("verde", _texto),
    "pulo_maximo": (3,      _inteiro(0, 10)),
}


class Preferencias:
    """
    As preferências, guardadas num arquivo JSON ao lado do programa.

    Duas regras guiam este módulo, e as duas vêm de pensar no que acontece quando
    algo dá errado.

    A primeira: ele NUNCA pode derrubar o emulador. Um JSON corrompido, um disco
    cheio, uma pasta sem permissão de escrita — tudo isso tem de virar "seguiu com
    os padrões", e não um traceback antes do jogo abrir. Perder a configuração é
    irritante; não conseguir jogar é bem pior.

    A segunda: um valor inválido no arquivo é descartado em favor do padrão. Aceitar
    `escala: 400` abriria uma janela maior que o monitor, com o menu para corrigir
    isso fora da tela — um beco sem saída criado por um número num arquivo de texto
    que alguém editou à mão.
    """
    def __init__(self, caminho=None):
        self.caminho = caminho or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "preferencias.json")
        self.caminho = os.path.abspath(self.caminho)
        self.valores = {nome: padrao for nome, (padrao, _) in CAMPOS.items()}
        self.somente_leitura = False      # vira True se a gravação falhar
        self.carregar()

    # ------------------------------------------------------------------
    def carregar(self):
        """Lê o arquivo, validando cada valor. Falhas viram silêncio e padrões."""
        try:
            with open(self.caminho, "r", encoding="utf-8") as f:
                lido = json.load(f)
        except (OSError, ValueError):
            # Arquivo ausente na primeira execução, ou ilegível. Nos dois casos
            # os padrões servem, e reclamar não ajudaria em nada.
            return

        if not isinstance(lido, dict):
            return

        for nome, (_, validar) in CAMPOS.items():
            if nome in lido:
                valor = validar(lido[nome])
                if valor is not None or lido[nome] is None:
                    self.valores[nome] = valor

    def salvar(self):
        """
        Grava as preferências. Devolve True se conseguiu.

        A gravação é ATÔMICA: escreve num arquivo temporário e só então o renomeia por
        cima do antigo. `os.replace` é atômico no Windows e no Linux, então um
        desligamento no meio do processo deixa o arquivo velho intacto — em vez de um
        arquivo pela metade, que é pior do que nenhum.
        """
        if self.somente_leitura:
            return False
        pasta = os.path.dirname(self.caminho)
        try:
            # Gravação atômica: um arquivo temporário na MESMA pasta (para o
            # rename não cruzar sistemas de arquivos) e um `os.replace`, que é
            # atômico no Windows e no POSIX.
            fd, temporario = tempfile.mkstemp(dir=pasta, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.valores, f, indent=2, ensure_ascii=False)
                os.replace(temporario, self.caminho)
            except BaseException:
                try:
                    os.unlink(temporario)
                except OSError:
                    pass
                raise
            return True
        except OSError:
            # Pasta protegida, disco cheio, jogo rodando de um pendrive só de
            # leitura... nada disso é motivo para atrapalhar a partida.
            self.somente_leitura = True
            return False

    # ------------------------------------------------------------------
    def __getitem__(self, nome):
        return self.valores[nome]

    def __setitem__(self, nome, valor):
        validar = CAMPOS[nome][1]
        corrigido = validar(valor)
        self.valores[nome] = CAMPOS[nome][0] if corrigido is None and valor is not None \
            else corrigido

    def get(self, nome, padrao=None):
        return self.valores.get(nome, padrao)
