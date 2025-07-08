"""
Orquestrador da Interface de Linha de Comando (CLI) para o CSP-BLFGA

Este módulo é o coração da aplicação, responsável por:
- **Processar Argumentos da CLI**: Utiliza `argparse` para interpretar os comandos
  e parâmetros fornecidos pelo usuário, permitindo a execução em modo
  interativo ou automatizado (silencioso).
- **Gerenciar o Fluxo de Execução**: Orquestra as diferentes funcionalidades
  da aplicação, como:
  - Execução de algoritmos individuais.
  - Execução em lote a partir de arquivos de configuração YAML.
  - Otimização de hiperparâmetros usando Optuna.
  - Análise de sensibilidade de parâmetros.
- **Interagir com o Usuário**:
  - Em modo interativo, utiliza os menus definidos em `src.ui.cli.menu`
    para guiar o usuário na seleção de datasets, algoritmos e configurações.
  - Em modo silencioso, opera com base nos argumentos fornecidos, sem
    interação, ideal para scripts e testes automatizados.
- **Integrar com o Core do Sistema**:
  - Cria e gerencia o `SchedulerExecutor`, que executa os algoritmos de
    forma controlada e robusta.
  - Invoca a `CursesExecutionMonitor` para fornecer um monitoramento
    visual em tempo real das execuções, se solicitado.
- **Coletar e Salvar Resultados**:
  - Utiliza `ResultsFormatter` para coletar os resultados das execuções.
  - Gera relatórios detalhados em formato de texto e CSV, salvando-os
    no diretório `outputs/reports`.
- **Configurar Logging**: Inicializa o sistema de logging para registrar
  informações detalhadas sobre a execução em `outputs/logs`.

Fluxos Principais:
1.  **Execução Padrão**: O usuário seleciona um dataset, um ou mais algoritmos,
    e o número de execuções. A aplicação executa os algoritmos e apresenta
    um resumo dos resultados.
2.  **Execução em Lote**: O usuário fornece um arquivo YAML com múltiplas
    configurações de execução. A aplicação processa todas as execuções
    definidas no arquivo.
3.  **Otimização**: Um workflow guiado para otimizar os hiperparâmetros de um
    algoritmo em um dataset específico.
4.  **Análise de Sensibilidade**: Um workflow para analisar o impacto de
    diferentes parâmetros no desempenho de um algoritmo.
"""

"""
Arquivo principal de execução da aplicação Closest String Problem (CSP).

Este módulo orquestra o fluxo principal da aplicação, incluindo:
    1. Seleção e leitura/geração do dataset.
    2. Seleção dos algoritmos a executar.
    3. Execução dos algoritmos selecionados.
    4. Exibição e salvamento dos resultados.

A aplicação pode ser executada em modo interativo ou automatizado (para testes).

Attributes:
    Nenhum atributo global relevante.
"""

import argparse
import logging
import os
import signal
import sys
import time
import traceback
import uuid
from datetime import datetime

from algorithms.base import global_registry
from src.core.io.results_formatter import ResultsFormatter
from src.core.report.report_utils import print_quick_summary
from src.ui.cli.console_manager import console
from src.ui.cli.menu import (
    configure_batch_optimization_params,
    configure_optimization_params,
    configure_sensitivity_params,
    menu,
    select_algorithms,
    select_dataset_for_optimization,
    select_optimization_algorithm,
    select_sensitivity_algorithm,
)
from src.ui.cli.save_wizard import ask_save_dataset
from src.utils.config import ALGORITHM_TIMEOUT, safe_input
from src.utils.logging import setup_logging

# Removed resource_monitor imports - using new scheduler system

RESULTS_DIR = "outputs/reports"
LOGS_DIR = "outputs/logs"
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)


def signal_handler(signum, frame):
    """Handler para sinais de interrupção.

    Args:
        signum (int): Número do sinal recebido.
        frame (frame object): Frame atual de execução.
    """
    print("\n\nOperação cancelada pelo usuário. Encerrando.")
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Closest String Problem (CSP) - Execução principal"
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Executa em modo silencioso (sem prints interativos)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        choices=["synthetic", "file", "entrez", "batch"],
        help="Fonte do dataset",
    )
    parser.add_argument(
        "--algorithms",
        type=str,
        nargs="+",
        help="Algoritmos a executar (nomes separados por espaço)",
    )
    parser.add_argument(
        "--num-execs", type=int, help="Número de execuções por algoritmo"
    )
    parser.add_argument("--timeout", type=int, help="Timeout por execução (segundos)")
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=4,
        help="Número de workers paralelos (padrão: 4)",
    )
    args = parser.parse_args()

    silent = args.silent

    # Usar sempre console simples
    def silent_print(*a, **k):
        pass

    p = print if not silent else silent_print
    cprint = console.print if not silent else silent_print

    # Mostrar o número do processo (PID) logo no início
    p(f"[PID] Processo em execução: {os.getpid()}")

    # Configurar handlers de sinal para saída limpa
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        uid = uuid.uuid4().hex[:8]
        base_name = f"{ts}_{uid}"
        # Passa silent para setup_logging
        setup_logging(base_name, silent=silent)

        # Se modo silencioso, use defaults para qualquer parâmetro não informado
        if silent:
            if not args.dataset:
                args.dataset = "synthetic"
            if not args.algorithms:
                args.algorithms = [
                    "Baseline"
                ]  # Usar Baseline em vez de BLF-GA para testes
            if not args.num_execs:
                args.num_execs = 1
            if not args.timeout:
                args.timeout = ALGORITHM_TIMEOUT

        # Dataset
        params = {}
        seqs = []
        seed = None

        # Escolha do dataset
        if args.dataset:
            choice = args.dataset
            if args.dataset == "synthetic":
                from src.datasets.dataset_synthetic import generate_dataset

                seqs, p = generate_dataset(silent=silent)
                logging.debug(f"[main] Parâmetros do dataset: {p}")
                params = {"dataset_source": "1"}
                params.update(p)
            elif args.dataset == "file":
                from src.datasets.dataset_file import load_dataset

                seqs, p = load_dataset(silent=silent)
                params = {"dataset_source": "2"}
                params.update(p)
            elif args.dataset == "entrez":
                from src.datasets.dataset_entrez import fetch_dataset

                seqs, p = fetch_dataset()
                params = {"dataset_source": "3"}
                params.update(p)
            elif args.dataset == "batch":
                from src.ui.cli.batch_executor import execute_batch_config

                # Perguntar pelo arquivo de configuração se não especificado
                if not silent:
                    config_file = safe_input(
                        "Arquivo de configuração [batch_configs/exemplo.yaml]: "
                    ).strip()
                    if not config_file:
                        config_file = "batch_configs/exemplo.yaml"
                else:
                    config_file = "batch_configs/exemplo.yaml"

                try:
                    cprint(f"� Executando batch: {config_file}")

                    # Executar batch (usa curses por padrão se não em modo silencioso)
                    use_curses = not silent
                    batch_results = execute_batch_config(
                        config_file, use_curses=use_curses, silent=silent
                    )

                    cprint(
                        f"✅ Batch concluído! {len(batch_results)} execuções processadas"
                    )
                    return

                except Exception as e:
                    cprint(f"❌ Erro na execução do batch: {e}")
                    logging.exception("Erro na execução do batch", exc_info=e)
                    return
            else:
                cprint("❌ Fonte de dataset inválida.")
                return
        else:
            # Fluxo interativo
            choice = menu()
            params = {"dataset_source": choice}

            if choice == "4":
                # Execução em lote
                from src.ui.cli.batch_executor import execute_batch_config
                from src.ui.cli.menu import select_yaml_batch_file

                try:
                    config_file = select_yaml_batch_file()
                    if not config_file:
                        cprint(
                            "❌ Nenhum arquivo selecionado. Voltando ao menu principal."
                        )
                        return

                    cprint(f"📋 Executando batch: {config_file}")

                    # Executar batch com curses se não em modo silencioso
                    use_curses = not silent
                    batch_results = execute_batch_config(
                        config_file, use_curses=use_curses, silent=silent
                    )

                    cprint(
                        f"✅ Batch concluído! {len(batch_results)} execuções processadas"
                    )
                    return

                except Exception as e:
                    cprint(f"❌ Erro na execução do batch: {e}")
                    logging.exception("Erro na execução do batch", exc_info=e)
                return
            elif choice == "5":
                # Otimização de hiperparâmetros (interativo)
                try:
                    from src.ui.cli.menu import interactive_optimization_menu

                    interactive_optimization_menu()
                except Exception as e:
                    cprint(f"❌ Erro na otimização: {e}")
                    logging.exception("Erro na otimização", exc_info=e)
                return
            elif choice == "6":
                # Análise de sensibilidade
                try:
                    from src.ui.cli.menu import interactive_sensitivity_menu

                    interactive_sensitivity_menu()
                except Exception as e:
                    cprint(f"❌ Erro na análise de sensibilidade: {e}")
                    logging.exception("Erro na análise de sensibilidade", exc_info=e)
                return
            elif choice in ["1", "2", "3"]:
                try:
                    if choice == "1":
                        from src.datasets.dataset_synthetic import generate_dataset

                        seqs, p = generate_dataset(silent=silent)
                        logging.debug(f"[main] Parâmetros do dataset: {p}")
                        params.update(p)
                        if not silent:
                            ask_save_dataset(seqs, "synthetic", p)
                    elif choice == "2":
                        from src.datasets.dataset_file import load_dataset

                        seqs, p = load_dataset(silent=silent)
                        params.update(p)
                    elif choice == "3":
                        from src.datasets.dataset_entrez import fetch_dataset

                        seqs, p = fetch_dataset()
                        params.update(p)
                        ask_save_dataset(seqs, "entrez", p)
                except Exception as exc:
                    cprint(f"Erro: {exc}")
                    logging.exception("Erro ao carregar dataset", exc_info=exc)
                    return

        # Após carregar o dataset, extrair informações extras se disponíveis
        seed = params.get("seed")
        logging.debug(f"[main] seed: {seed}")

        # Exibir distância da string base se disponível
        distancia_base = params.get("distancia_string_base")
        if distancia_base is not None:
            cprint(f"Distância da string base: {distancia_base}")

        if not seqs:
            cprint("Nenhuma sequência lida.")
            return

        alphabet = "".join(sorted(set("".join(seqs))))
        n, L = len(seqs), len(seqs[0])
        cprint(f"\nDataset: n={n}, L={L}, |Σ|={len(alphabet)}")

        # Log simplificado do dataset
        logging.debug(f"[DATASET] n={n}, L={L}, |Σ|={len(alphabet)}")
        if len(seqs) <= 5:
            logging.debug(f"[DATASET] Strings: {seqs}")
        else:
            logging.debug(f"[DATASET] {len(seqs)} strings (primeiras 2: {seqs[:2]})")

        # Verificação de recursos do sistema (simplificada)
        # TODO: Implementar verificação com novo sistema de monitoramento
        cprint("Sistema de recursos atualizado - verificação de memória disponível")

        # Algoritmos
        if args.algorithms:
            algs = args.algorithms
        else:
            algs = select_algorithms()
        if not algs:
            cprint("Nenhum algoritmo selecionado.")
            return

        # TODO: Implementar verificação de viabilidade com novo sistema
        # Por enquanto, todos os algoritmos são considerados viáveis
        viable_algs = algs
        for alg_name in algs:
            cprint(f"✓ {alg_name}: Algoritmo selecionado")

        if not viable_algs:
            cprint("Nenhum algoritmo selecionado.")
            return

        # Número de execuções e timeout
        if args.num_execs:
            num_execs = args.num_execs
        else:
            runs = safe_input("\nNº execuções p/ algoritmo [3]: ")
            num_execs = int(runs) if runs.isdigit() and int(runs) > 0 else 3
        if args.timeout:
            timeout = args.timeout
        else:
            default_timeout = ALGORITHM_TIMEOUT
            timeout_input = safe_input(
                f"\nTimeout por execução em segundos [{default_timeout}]: "
            )
            timeout = (
                int(timeout_input)
                if timeout_input.isdigit() and int(timeout_input) > 0
                else default_timeout
            )
        cprint(f"Timeout configurado: {timeout}s por execução")

        # Configurar número de workers externos
        # Se não foi fornecido via linha de comando e não está em modo silencioso, perguntar
        if not hasattr(args, "workers_provided") and not silent:
            # Verificar se o valor foi fornecido via linha de comando
            workers_provided = "--workers" in sys.argv or "-w" in sys.argv
            if not workers_provided:
                workers_input = safe_input(f"\nNúmero de workers externos [4]: ")
                external_workers = (
                    int(workers_input)
                    if workers_input.isdigit() and int(workers_input) > 0
                    else 4
                )
            else:
                external_workers = args.workers
        else:
            external_workers = args.workers

        # Execução dos algoritmos
        cprint("\n" + "=" * 50)
        cprint("EXECUTANDO ALGORITMOS")
        cprint("=" * 50)

        # Configurar workers para execução
        import multiprocessing

        cpu_count = multiprocessing.cpu_count()

        # Verificar se algum algoritmo suporta paralelismo interno
        has_internal_parallel = any(
            getattr(global_registry[alg_name], "supports_internal_parallel", False)
            for alg_name in viable_algs
            if alg_name in global_registry
        )

        # Configurar workers internos baseado no número de CPUs e workers externos
        if has_internal_parallel:
            internal_workers = max(1, cpu_count // external_workers)
        else:
            internal_workers = max(1, cpu_count // external_workers)

        # Configurar variável de ambiente para workers internos
        os.environ["INTERNAL_WORKERS"] = str(internal_workers)

        cprint("🔧 Configuração de paralelismo:")
        cprint(f"   - CPUs disponíveis: {cpu_count}")
        cprint(f"   - Workers externos: {external_workers}")
        cprint(f"   - Workers internos: {internal_workers}")
        cprint(f"   - Paralelismo interno detectado: {has_internal_parallel}")

        # Perguntar sobre interface curses para monitoramento (apenas se não em modo silencioso)
        use_curses_monitoring = False
        if not silent:
            curses_input = (
                safe_input("\n🖥️  Usar interface curses para monitoramento? (S/n): ")
                .lower()
                .strip()
            )
            use_curses_monitoring = curses_input in ["", "s", "sim", "y", "yes"]
            if use_curses_monitoring:
                cprint(
                    "💡 Usando interface curses para monitoramento - Pressione 'q' para sair"
                )
            else:
                cprint("💡 Usando modo tradicional para monitoramento")

        cprint(
            f"🚀 Executando {len(viable_algs)} algoritmos (algoritmos determinísticos: 1 execução, não-determinísticos: {num_execs} execuções)"
        )

        if use_curses_monitoring:
            # Usar nova interface curses para execução
            from src.ui.curses_integration import CursesExecutionMonitor

            try:
                monitor = CursesExecutionMonitor(
                    max_workers=external_workers, timeout=timeout
                )

                # Executar algoritmos com monitoramento curses (com múltiplas execuções)
                algorithm_results = monitor.execute_algorithms(
                    algorithm_names=viable_algs,
                    seqs=seqs,
                    alphabet=alphabet,
                    num_execs=num_execs,
                    dataset_params=params,  # Passar parâmetros do dataset
                )

                # Converter TaskResult para formato esperado
                formatter = ResultsFormatter()
                results = {}

                for alg_name, task_results in algorithm_results.items():
                    if isinstance(task_results, list) and len(task_results) > 0:
                        # Múltiplas execuções - processar todas
                        executions = []
                        for task_result in task_results:
                            if task_result.success and task_result.distance is not None:
                                execution_result = {
                                    "tempo": task_result.time,
                                    "distancia": task_result.distance,
                                    "melhor_string": task_result.center or "",
                                    "iteracoes": task_result.metadata.get(
                                        "iteracoes", 0
                                    ),
                                    "seed": seed,
                                }
                            else:
                                execution_result = {
                                    "tempo": 0.0,
                                    "distancia": float("inf"),
                                    "melhor_string": "",
                                    "iteracoes": 0,
                                    "seed": seed,
                                }
                            executions.append(execution_result)

                        formatter.add_algorithm_results(alg_name, executions)

                        # Encontrar melhor resultado
                        valid_results = [
                            e for e in executions if e["distancia"] != float("inf")
                        ]

                        if valid_results:
                            best_exec = min(valid_results, key=lambda e: e["distancia"])
                            dist_base = params.get("distancia_string_base", "-")
                            results[alg_name] = {
                                "dist": best_exec["distancia"],
                                "dist_base": dist_base,
                                "time": best_exec["tempo"],
                            }
                        else:
                            results[alg_name] = {
                                "dist": "-",
                                "dist_base": "-",
                                "time": "-",
                                "warn": "Todas as execuções falharam",
                            }
                    else:
                        # Resultado único ou erro
                        results[alg_name] = {
                            "dist": "-",
                            "dist_base": "-",
                            "time": "-",
                            "warn": "Erro na execução",
                        }

            except Exception as e:
                cprint(f"❌ Erro na interface curses: {e}")
                cprint("🔄 Fallback para execução tradicional...")
                use_curses_monitoring = False

        if not use_curses_monitoring:
            # Execução tradicional usando novo sistema
            from src.core.interfaces import TaskStatus, create_executor

            formatter = ResultsFormatter()
            results = {}

            # Criar executor único para todas as execuções
            executor = create_executor(
                timeout_seconds=timeout, max_workers=external_workers
            )

            try:
                # Executar algoritmos usando novo executor
                for alg_name in viable_algs:
                    if alg_name not in global_registry:
                        cprint(f"ERRO: Algoritmo '{alg_name}' não encontrado!")
                        continue

                    AlgClass = global_registry[alg_name]

                    # Verificar se o algoritmo é determinístico
                    is_deterministic = getattr(AlgClass, "is_deterministic", False)
                    actual_num_execs = 1 if is_deterministic else num_execs

                    if is_deterministic:
                        cprint(
                            f"  🔒 {alg_name} é determinístico - executando apenas 1 vez"
                        )
                    else:
                        cprint(
                            f"  🎲 {alg_name} é não-determinístico - executando {actual_num_execs} vezes"
                        )

                    logging.debug(
                        f"[ALG_EXEC] Iniciando {alg_name} com {actual_num_execs} execuções (determinístico: {is_deterministic})"
                    )

                    executions = []

                    # Submeter múltiplas execuções baseado no tipo do algoritmo
                    for i in range(actual_num_execs):
                        if actual_num_execs == 1:
                            cprint(f"  Executando {alg_name}")
                        else:
                            cprint(
                                f"  Executando {alg_name} - Run {i+1}/{actual_num_execs}"
                            )
                        instance = AlgClass(seqs, alphabet)
                        handle = executor.submit(instance)

                        # Aguardar conclusão
                        while executor.poll(handle) == TaskStatus.RUNNING:
                            time.sleep(0.1)

                        result = executor.result(handle)

                        if isinstance(result, Exception):
                            execution_result = {
                                "tempo": 0.0,
                                "distancia": float("inf"),
                                "melhor_string": "",
                                "iteracoes": 0,
                                "seed": seed,
                            }
                        else:
                            # Extrair tempo do metadata se disponível
                            metadata = result.get("metadata", {})
                            execution_time = metadata.get("execution_time", 0.0)
                            if execution_time == 0.0:
                                execution_time = metadata.get(
                                    "tempo", metadata.get("time", 0.0)
                                )

                            execution_result = {
                                "tempo": execution_time,
                                "distancia": result.get(
                                    "distance", result.get("distancia", float("inf"))
                                ),
                                "melhor_string": result.get(
                                    "center", result.get("melhor_string", "")
                                ),
                                "iteracoes": result.get("metadata", {}).get(
                                    "iteracoes", 0
                                ),
                                "seed": seed,
                            }

                        executions.append(execution_result)

                    # Processar resultados para este algoritmo
                    formatter.add_algorithm_results(alg_name, executions)

                    valid_results = [
                        e
                        for e in executions
                        if "distancia" in e and e["distancia"] != float("inf")
                    ]

                    if valid_results:
                        best_exec = min(valid_results, key=lambda e: e["distancia"])
                        dist_base = params.get("distancia_string_base", "-")
                        results[alg_name] = {
                            "dist": best_exec["distancia"],
                            "dist_base": dist_base,
                            "time": best_exec["tempo"],
                        }
                        cprint(
                            f"  ✅ {alg_name}: {len(valid_results)}/{actual_num_execs} execuções válidas, melhor distância: {best_exec['distancia']}"
                        )
                    else:
                        results[alg_name] = {
                            "dist": "-",
                            "dist_base": "-",
                            "time": "-",
                        }
                        cprint(f"  ❌ {alg_name}: Todas as execuções falharam")

            finally:
                # Garantir que o executor seja encerrado
                if hasattr(executor, "shutdown"):
                    executor.shutdown(wait=True)

        # Exibir resumo dos resultados
        print_quick_summary(results, console)

        cprint("\n📄 Gerando relatório detalhado...")
        # Adicionar informações básicas ao formatter para o relatório
        if hasattr(formatter, "__dict__"):
            # Captura todas as strings base e suas distâncias
            base_strings_info = []
            for _, execs in formatter.results.items():
                for exec_data in execs:
                    if exec_data.get("melhor_string"):
                        base_strings_info.append(
                            {
                                "base_string": exec_data["melhor_string"],
                                "distancia_string_base": params.get(
                                    "distancia_string_base", "-"
                                ),
                            }
                        )
            formatter.extra_info = {
                "seed": seed,
                "params": params,
                "dataset_strings": seqs,
                "base_strings_info": base_strings_info,
            }
            logging.debug("[main] formatter configurado")

        # Usar estrutura padronizada outputs/reports com timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_dir = os.path.join("outputs", "reports", timestamp)
        os.makedirs(results_dir, exist_ok=True)
        txt_path = os.path.join(results_dir, f"{base_name}.txt")
        csv_path = os.path.join(results_dir, f"{base_name}.csv")

        formatter.save_detailed_report(txt_path)

        # Salvar resultados detalhados em CSV
        formatter.export_to_csv(csv_path)
        cprint(f"📄 Resultados detalhados exportados para CSV: {csv_path}")

        # Sucesso - retornar 0 explicitamente
        if silent:
            sys.exit(0)

    except Exception as e:
        if not silent:
            console.print(f"\nERRO FATAL: {e}")
            traceback.print_exc()
        else:
            logging.exception("Erro fatal durante execução", exc_info=e)
        sys.exit(1)


def generate_dataset_automated():
    """Gera dataset sintético com valores padrão para testes automatizados.

    Utiliza parâmetros fixos para garantir reprodutibilidade em testes.

    Returns:
        tuple: Lista de strings do dataset e dicionário de parâmetros utilizados.
    """
    from src.datasets.dataset_synthetic import SYNTHETIC_DEFAULTS

    n = SYNTHETIC_DEFAULTS["n"]
    L = SYNTHETIC_DEFAULTS["L"]
    alphabet = SYNTHETIC_DEFAULTS["alphabet"]
    noise = SYNTHETIC_DEFAULTS["noise"]
    fully_random = False
    seed = 42
    params = {
        "n": n,
        "L": L,
        "alphabet": alphabet,
        "noise": noise,
        "fully_random": fully_random,
        "seed": seed,
    }
    import random

    rng = random.Random(seed)
    base_string = "".join(rng.choices(alphabet, k=L))
    data = []
    for _ in range(n):
        s = list(base_string)
        num_mut = int(round(noise * L))
        mut_pos = rng.sample(range(L), num_mut) if num_mut > 0 else []
        for pos in mut_pos:
            orig = s[pos]
            alt = rng.choice([c for c in alphabet if c != orig])
            s[pos] = alt
        new_s = "".join(s)
        data.append(new_s)
    return data, params


def run_optimization_workflow():
    """Executa o workflow de otimização de hiperparâmetros."""
    from src.optimization.optuna_optimizer import optimize_algorithm

    console.print("\n=== Otimização de Hiperparâmetros ===")

    # Perguntar tipo de otimização
    print("\nTipo de otimização:")
    print("1) Otimização simples")
    print("2) Otimização em lote (múltiplas configurações)")

    opt_type = safe_input("Escolha [1]: ")

    if opt_type == "2":
        run_batch_optimization_workflow()
        return

    # Selecionar algoritmo
    algorithm_name = select_optimization_algorithm()
    if not algorithm_name:
        console.print("❌ Nenhum algoritmo selecionado.")
        return

    # Selecionar dataset
    seqs, alphabet, dataset_info = select_dataset_for_optimization()

    # Configurar parâmetros
    config = configure_optimization_params()

    try:
        result = optimize_algorithm(
            algorithm_name=algorithm_name,
            sequences=seqs,
            alphabet=alphabet,
            n_trials=config["n_trials"],
            timeout_per_trial=config["timeout"],
            show_progress=True,
        )

        console.print("\n✅ Otimização concluída!")
        console.print(f"Melhor valor: {result.best_value}")
        console.print(f"Melhores parâmetros: {result.best_params}")

        # Salvar visualizações se solicitado
        if config["save_plots"]:
            from src.optimization.visualization import OptimizationVisualizer

            visualizer = OptimizationVisualizer(result)
            plots_dir = os.path.join(RESULTS_DIR, "optimization_plots")
            os.makedirs(plots_dir, exist_ok=True)

            # Salvar gráficos
            history_path = os.path.join(plots_dir, f"{algorithm_name}_history.png")
            importance_path = os.path.join(
                plots_dir, f"{algorithm_name}_importance.png"
            )

            visualizer.plot_optimization_history(save_path=history_path)
            visualizer.plot_parameter_importance(save_path=importance_path)

            console.print(f"📊 Gráficos salvos em: {plots_dir}")

        # Salvar resultados
        import json

        results_path = os.path.join(
            RESULTS_DIR,
            f"optimization_{algorithm_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        with open(results_path, "w") as f:
            json.dump(
                {
                    "best_params": result.best_params,
                    "best_value": result.best_value,
                    "n_trials": result.n_trials,
                    "study_name": result.study_name,
                    "optimization_time": result.optimization_time,
                    "all_trials": result.all_trials,
                },
                f,
                indent=2,
                default=str,
            )

        console.print(f"💾 Resultados salvos em: {results_path}")

    except Exception as e:
        console.print(f"❌ Erro durante otimização: {e}")
        logging.exception("Erro na otimização", exc_info=e)


def run_batch_optimization_workflow():
    """Executa workflow de otimização em lote com múltiplas configurações."""
    import json
    import os
    from datetime import datetime

    from src.optimization.optuna_optimizer import optimize_algorithm

    console.print("\n=== Otimização em Lote ===")

    # Configurar parâmetros do batch
    batch_config = configure_batch_optimization_params()

    console.print(f"🔧 Configuração do batch:")
    console.print(f"   - Trials por configuração: {batch_config['n_trials']}")
    console.print(f"   - Timeout por trial: {batch_config['timeout']}s")
    console.print(f"   - Configurações de dataset: {batch_config['n_configs']}")
    console.print(f"   - Algoritmos: {', '.join(batch_config['algorithms'])}")

    # Confirmar execução
    confirm = safe_input("\n🚀 Iniciar otimização em lote? (S/n): ")
    if confirm.lower() in ["n", "no", "nao"]:
        console.print("❌ Operação cancelada.")
        return

    # Armazenar resultados
    batch_results = {
        "batch_info": {"timestamp": datetime.now().isoformat(), "config": batch_config},
        "results": [],
    }

    # Executar para cada configuração de dataset
    for config_idx in range(batch_config["n_configs"]):
        console.print(f"\n📊 Configuração {config_idx + 1}/{batch_config['n_configs']}")

        # Gerar/selecionar dataset para esta configuração
        seqs, alphabet, dataset_info = select_dataset_for_optimization()

        config_results = {
            "config_index": config_idx + 1,
            "dataset_info": dataset_info,
            "algorithms": {},
        }

        # Executar otimização para cada algoritmo
        for alg_name in batch_config["algorithms"]:
            console.print(f"\n🔬 Otimizando {alg_name}...")

            try:
                result = optimize_algorithm(
                    algorithm_name=alg_name,
                    sequences=seqs,
                    alphabet=alphabet,
                    n_trials=batch_config["n_trials"],
                    timeout_per_trial=batch_config["timeout"],
                    show_progress=True,
                )

                config_results["algorithms"][alg_name] = {
                    "best_value": result.best_value,
                    "best_params": result.best_params,
                    "n_trials": result.n_trials,
                    "optimization_time": result.optimization_time,
                    "study_name": result.study_name,
                }

                console.print(f"✅ {alg_name}: Melhor valor = {result.best_value}")

            except Exception as e:
                console.print(f"❌ Erro em {alg_name}: {e}")
                config_results["algorithms"][alg_name] = {
                    "error": str(e),
                    "best_value": float("inf"),
                }

        batch_results["results"].append(config_results)

    # Salvar resultados se solicitado
    if batch_config["save_results"]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_dir = os.path.join("outputs", "reports")
        os.makedirs(results_dir, exist_ok=True)

        results_file = os.path.join(results_dir, f"batch_optimization_{timestamp}.json")

        with open(results_file, "w") as f:
            json.dump(batch_results, f, indent=2, default=str)

        console.print(f"💾 Resultados salvos em: {results_file}")

    # Exibir resumo
    console.print("\n📊 Resumo da Otimização em Lote:")
    console.print("=" * 50)

    for result in batch_results["results"]:
        config_idx = result["config_index"]
        console.print(f"\n📋 Configuração {config_idx}:")
        console.print(f"   Dataset: {result['dataset_info'].get('type', 'N/A')}")

        for alg_name, alg_result in result["algorithms"].items():
            if "error" in alg_result:
                console.print(f"   ❌ {alg_name}: {alg_result['error']}")
            else:
                console.print(f"   ✅ {alg_name}: {alg_result['best_value']:.6f}")


def run_sensitivity_workflow():
    """Executa o workflow de análise de sensibilidade."""
    from src.datasets.dataset_synthetic import generate_dataset
    from src.optimization.sensitivity_analyzer import analyze_algorithm_sensitivity

    console.print("\n=== Análise de Sensibilidade ===")

    # Selecionar algoritmo
    algorithm_name = select_sensitivity_algorithm()
    if not algorithm_name:
        console.print("❌ Nenhum algoritmo selecionado.")
        return

    # Configurar parâmetros
    config = configure_sensitivity_params()

    # Gerar dataset para análise
    console.print("\n📊 Gerando dataset para análise...")
    seqs, _ = generate_dataset(silent=True)

    console.print(
        f"✅ Dataset gerado: {len(seqs)} sequências de tamanho {len(seqs[0])}"
    )

    # Executar análise de sensibilidade
    alphabet = "".join(sorted(set("".join(seqs))))

    try:
        result = analyze_algorithm_sensitivity(
            algorithm_name=algorithm_name,
            sequences=seqs,
            alphabet=alphabet,
            n_samples=config["n_samples"],
            timeout_per_sample=config.get("timeout", 60),
            show_progress=True,
        )

        console.print("\n✅ Análise de sensibilidade concluída!")
        console.print(f"Parâmetros analisados: {len(result.parameter_names)}")

        # Mostrar principais parâmetros sensíveis baseado no método
        console.print("\n📈 Parâmetros mais sensíveis:")
        if result.method == "sobol" and result.total_order:
            # Para Sobol, usar índices de ordem total
            sorted_params = sorted(
                result.total_order.items(), key=lambda x: x[1], reverse=True
            )
            for param, value in sorted_params[:5]:
                console.print(f"  • {param}: {value:.4f}")
        elif result.method == "morris" and result.mu_star:
            # Para Morris, usar mu_star
            sorted_params = sorted(
                result.mu_star.items(), key=lambda x: x[1], reverse=True
            )
            for param, value in sorted_params[:5]:
                console.print(f"  • {param}: {value:.4f}")
        elif result.method == "fast" and result.first_order:
            # Para FAST, usar índices de primeira ordem
            sorted_params = sorted(
                result.first_order.items(), key=lambda x: x[1], reverse=True
            )
            for param, value in sorted_params[:5]:
                console.print(f"  • {param}: {value:.4f}")

        # Salvar visualizações se solicitado
        if config["save_plots"]:
            from src.optimization.visualization import SensitivityVisualizer

            visualizer = SensitivityVisualizer(result)
            plots_dir = os.path.join(RESULTS_DIR, "sensitivity_plots")
            os.makedirs(plots_dir, exist_ok=True)

            # Salvar gráficos
            sensitivity_path = os.path.join(
                plots_dir, f"{algorithm_name}_sensitivity.png"
            )
            visualizer.plot_sensitivity_indices(save_path=sensitivity_path)

            console.print(f"📊 Gráficos salvos em: {plots_dir}")

        # Salvar resultados
        import json

        results_path = os.path.join(
            RESULTS_DIR,
            f"sensitivity_{algorithm_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        with open(results_path, "w") as f:
            json.dump(
                {
                    "method": result.method,
                    "parameter_names": result.parameter_names,
                    "first_order": result.first_order,
                    "total_order": result.total_order,
                    "second_order": result.second_order,
                    "mu": result.mu,
                    "mu_star": result.mu_star,
                    "sigma": result.sigma,
                    "main_effect": result.main_effect,
                    "n_samples": result.n_samples,
                    "analysis_time": result.analysis_time,
                },
                f,
                indent=2,
                default=str,
            )

        console.print(f"💾 Resultados salvos em: {results_path}")

    except Exception as e:
        console.print(f"❌ Erro durante análise de sensibilidade: {e}")
        logging.exception("Erro na análise de sensibilidade", exc_info=e)
