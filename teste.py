import random
import time

def run_benchmark():
    # 1. Configuração e Criação da Lista
    print("Gerando lista de 1 milhão de valores aleatórios... aguarde.")
    
    # Valores possíveis (0, 1, 16, 17 em decimal)
    opcoes = [0b00, 0b01, 0b10, 0b11, 0b100, 0b101, 0b110] 
    
    # Gera 1 milhão de itens escolhendo aleatoriamente entre as opções
    # Usamos random.choices por ser muito mais rápido que um loop for na criação
    lista_valores = random.choices(opcoes, k=10_000_000)
    
    tamanho_lista = len(lista_valores)
    print("Lista gerada! Iniciando testes...\n")

    # ---------------------------------------------------------
    # TESTE 1: IF / ELIF / ELSE
    # ---------------------------------------------------------
    
    # Zerando contadores
    c_00 = 0
    c_01 = 0
    c_10 = 0
    c_11 = 0
    
    # 2. Marca o tempo inicial
    start_time_if = time.perf_counter()

    # 3. Loop por INDEX
    for i in range(tamanho_lista):
        val = lista_valores[i]
        
        # 4 & 5. Comparações e Somas
        if val == 0x00:
            c_00 += 1
        elif val == 0x01:
            c_01 += 1
        elif val == 0x10:
            c_10 += 1
        elif val == 0x11:
            c_11 += 1
        elif val == 0x100:
            pass  # Ignorado
        elif val == 0x101:
            pass  # Ignorado
        elif val == 0x110:
            pass  # Ignorado
            
    # 6. Termina de marcar o tempo
    end_time_if = time.perf_counter()
    tempo_total_if = end_time_if - start_time_if

    # 7. Mostra resultados do IF
    #print(f"--- Resultado IF / ELSE ---")
    print(f"Tempo: {tempo_total_if:.5f} segundos")
    #print(f"Contadores: c_00={c_00}, c_01={c_01}, c_10={c_10}, c_11={c_11}")
    #print("-" * 30 + "\n")

    # ---------------------------------------------------------
    # TESTE 2: MATCH / CASE
    # ---------------------------------------------------------
    
    # Zerando contadores novamente
    c_00 = 0
    c_01 = 0
    c_10 = 0
    c_11 = 0

    # Marca o tempo inicial
    start_time_match = time.perf_counter()

    # Loop por INDEX
    for i in range(tamanho_lista):
        val = lista_valores[i]
        
        # 8. Match Case
        match val:
            case 0x00:
                c_00 += 1
            case 0x01:
                c_01 += 1
            case 0x10:
                c_10 += 1
            case 0x11:
                c_11 += 1
            case 0x100:
                pass  # Ignorado
            case 0x101:
                pass  # Ignorado
            case 0x110:
                pass  # Ignorado

    # Termina de marcar o tempo
    end_time_match = time.perf_counter()
    tempo_total_match = end_time_match - start_time_match

    # Mostra resultados do MATCH
    #print(f"--- Resultado MATCH / CASE ---")
    print(f"Tempo: {tempo_total_match:.5f} segundos")
    #print(f"Contadores: c_00={c_00}, c_01={c_01}, c_10={c_10}, c_11={c_11}")
    #print("-" * 30)
    
    # Comparativo final
    diff = tempo_total_match - tempo_total_if
    vencedor = "IF/ELSE" if diff > 0 else "MATCH/CASE"
    print(f"\nCONCLUSÃO: {vencedor} foi mais rápido por {abs(diff):.5f} segundos.")

if __name__ == "__main__":
    # Verifica a versão do Python pois match/case exige 3.10+
    import sys
    if sys.version_info < (3, 10):
        print("Erro: Este código precisa de Python 3.10 ou superior para rodar o 'match case'.")
    else:
        run_benchmark()