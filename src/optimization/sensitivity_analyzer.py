"""
Módulo de análise de sensibilidade para algoritmos CSP usando SALib.

Este módulo fornece funcionalidades para analisar a sensibilidade dos algoritmos
CSP aos seus hiperparâmetros, utilizando diferentes métodos de análise como
Sobol, Morris e FAST, com suporte a execução paralela.

Classes:
    SensitivityConfig: Configuração para análise de sensibilidade
    SensitivityResult: Resultado da análise de sensibilidade
    SensitivityAnalyzer: Classe principal para análise

Funções:
    analyze_algorithm_sensitivity: Função principal para análise
    create_parameter_space: Cria espaço de parâmetros para análise
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from SALib.analyze import fast, morris, sobol
from SALib.sample import fast_sampler
from SALib.sample import morris as morris_sample
from SALib.sample import saltelli
from tqdm import tqdm

from algorithms.base import global_registry

logger = logging.getLogger(__name__)


@dataclass
class SensitivityConfig:
    """Configuração para análise de sensibilidade."""

    n_samples: int = 1000
    method: str = "sobol"  # "sobol", "morris", "fast"
    timeout_per_sample: Optional[float] = 60.0
    show_progress: bool = True
    seed: Optional[int] = None

    # Parâmetros específicos para cada método
    sobol_calc_second_order: bool = True
    morris_num_levels: int = 4
    morris_grid_jump: int = 2
    fast_m: int = 4

    # Configurações de paralelismo
    n_jobs: int = 1  # Número de jobs paralelos


@dataclass
class SensitivityResult:
    """Resultado da análise de sensibilidade."""

    parameter_names: List[str]
    method: str
    n_samples: int
    analysis_time: float

    # Índices de sensibilidade (específicos para cada método)
    first_order: Optional[Dict[str, float]] = None
    second_order: Optional[Dict[str, float]] = None
    total_order: Optional[Dict[str, float]] = None

    # Para Morris
    mu: Optional[Dict[str, float]] = None
    mu_star: Optional[Dict[str, float]] = None
    sigma: Optional[Dict[str, float]] = None

    # Para FAST
    main_effect: Optional[Dict[str, float]] = None

    # Dados brutos
    problem: Optional[Dict[str, Any]] = None
    samples: Optional[np.ndarray] = None
    outputs: Optional[np.ndarray] = None


class SensitivityAnalyzer:
    """Analisador de sensibilidade para algoritmos CSP."""

    def __init__(self, config: SensitivityConfig):
        self.config = config
        self.algorithm_class: Optional[type] = None
        self.sequences: List[str] = []
        self.alphabet: str = ""

    def _get_parameter_space(self, algorithm_name: str) -> Dict[str, Any]:
        """Obtém espaço de parâmetros para o algoritmo."""
        # Mapear algoritmos para seus espaços de parâmetros
        parameter_spaces = {
            "BLF-GA": {
                "pop_size": [30, 200],
                "max_gens": [50, 500],
                "cross_prob": [0.6, 0.95],
                "mut_prob": [0.01, 0.3],
                "elite_rate": [0.01, 0.15],
                "tournament_k": [2, 8],
                "immigrant_freq": [5, 20],
                "immigrant_ratio": [0.1, 0.4],
                "diversity_threshold": [0.2, 0.8],
                "no_improve_patience": [0.1, 0.5],
                "restart_patience": [10, 50],
                "restart_ratio": [0.2, 0.6],
                "mutation_multi_n": [1, 5],
                "refine_iter_limit": [50, 200],
                "niching_radius": [2, 8],
                "mutation_adapt_factor": [1.5, 3.0],
                "mutation_adapt_duration": [3, 10],
                "disable_elitism_gens": [3, 10],
            },
            "CSC": {
                "max_iter": [100, 1000],
                "patience": [10, 100],
                "min_improvement": [1e-6, 1e-3],
                "restart_patience": [20, 100],
                "max_restarts": [1, 10],
            },
            "H3-CSP": {
                "beam_width": [5, 50],
                "max_iterations": [50, 500],
                "diversity_factor": [0.1, 0.9],
                "local_search_iters": [10, 100],
                "restart_threshold": [10, 100],
                "max_restarts": [1, 10],
            },
            "DP-CSP": {
                "max_depth": [5, 20],
                "pruning_threshold": [0.1, 0.9],
                "memory_limit": [100, 1000],
            },
        }

        return parameter_spaces.get(algorithm_name, {})

    def _create_problem(self, algorithm_name: str) -> Dict[str, Any]:
        """Cria problema SALib para análise."""
        param_space = self._get_parameter_space(algorithm_name)

        if not param_space:
            raise ValueError(f"Espaço de parâmetros não definido para {algorithm_name}")

        problem = {
            "num_vars": len(param_space),
            "names": list(param_space.keys()),
            "bounds": list(param_space.values()),
        }

        return problem

    def _generate_samples(self, problem: Dict[str, Any]) -> np.ndarray:
        """Gera amostras baseado no método escolhido."""
        # Definir seed globalmente se especificado
        if self.config.seed is not None:
            np.random.seed(self.config.seed)

        if self.config.method == "sobol":
            return saltelli.sample(
                problem,
                self.config.n_samples,
                calc_second_order=self.config.sobol_calc_second_order,
            )
        elif self.config.method == "morris":
            return morris_sample.sample(
                problem,
                self.config.n_samples,
                num_levels=self.config.morris_num_levels,
            )
        elif self.config.method == "fast":
            return fast_sampler.sample(
                problem,
                self.config.n_samples,
                M=self.config.fast_m,
            )
        else:
            raise ValueError(f"Método desconhecido: {self.config.method}")

    def _evaluate_samples(
        self, samples: np.ndarray, problem: Dict[str, Any]
    ) -> np.ndarray:
        """Avalia amostras executando o algoritmo."""
        param_names = problem["names"]

        # Log temporário para debug
        logger.info(
            "[DEBUG] _evaluate_samples: n_jobs=%d, samples=%d",
            self.config.n_jobs,
            len(samples),
        )

        if self.config.n_jobs == 1:
            # Execução serial com barra de progresso
            logger.info("[DEBUG] Usando execução SERIAL")
            return self._evaluate_samples_serial(samples, param_names)
        else:
            # Execução paralela
            logger.info(
                "[DEBUG] Usando execução PARALELA com %d jobs", self.config.n_jobs
            )
            return self._evaluate_samples_parallel(samples, param_names)

    def _evaluate_samples_serial(
        self, samples: np.ndarray, param_names: List[str]
    ) -> np.ndarray:
        """Avalia amostras em modo serial."""
        outputs = []

        progress_bar = None
        if self.config.show_progress:
            progress_bar = tqdm(total=len(samples), desc="Avaliando amostras")

        for i, sample in enumerate(samples):
            output = self._evaluate_single_sample(sample, param_names, i)
            outputs.append(output)

            if progress_bar:
                progress_bar.update(1)

        if progress_bar:
            progress_bar.close()

        return np.array(outputs, dtype=float)

    def _evaluate_samples_parallel(
        self, samples: np.ndarray, param_names: List[str]
    ) -> np.ndarray:
        """Avalia amostras em modo paralelo."""
        import os
        import threading
        from concurrent.futures import ProcessPoolExecutor, as_completed

        # Log temporário: início do paralelismo
        thread_id = threading.get_ident()
        process_id = os.getpid()
        logger.info(
            "[PARALLEL-LOG] Análise de sensibilidade PARALELA iniciada - %d workers, %d amostras",
            self.config.n_jobs,
            len(samples),
        )
        logger.info(
            "[PARALLEL-LOG] Processo principal: PID %d, Thread %d",
            process_id,
            thread_id,
        )

        # Preparar dados para execução paralela
        tasks = [(i, sample, param_names) for i, sample in enumerate(samples)]

        # Executar em paralelo
        outputs: List[float] = [0.0] * len(samples)  # Preservar ordem

        progress_bar = None
        if self.config.show_progress:
            progress_bar = tqdm(
                total=len(samples), desc="Avaliando amostras (paralelo)"
            )

        completed_count = 0
        with ProcessPoolExecutor(max_workers=self.config.n_jobs) as executor:
            # Submeter tarefas
            future_to_index = {
                executor.submit(self._evaluate_sample_worker, task): task[0]
                for task in tasks
            }

            # Coletar resultados preservando ordem
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    output = future.result()
                    outputs[index] = output
                    completed_count += 1

                    # Log a cada 10% das amostras
                    if completed_count % max(1, len(samples) // 10) == 0:
                        logger.info(
                            "[PARALLEL-LOG] Progresso: %d/%d amostras concluídas",
                            completed_count,
                            len(samples),
                        )

                except Exception as exc:
                    logger.error("[PARALLEL-LOG] Erro na amostra %d: %s", index, exc)
                    outputs[index] = float("inf")

                if progress_bar:
                    progress_bar.update(1)

        if progress_bar:
            progress_bar.close()

        logger.info(
            "[PARALLEL-LOG] Análise de sensibilidade PARALELA concluída - %d amostras processadas",
            len(samples),
        )
        return np.array(outputs, dtype=float)

    def _evaluate_sample_worker(self, task: Tuple[int, np.ndarray, List[str]]) -> float:
        """Worker para avaliação paralela de uma amostra."""
        import threading

        index, sample, param_names = task

        # Log temporário: worker iniciado
        process_id = os.getpid()
        thread_id = threading.get_ident()
        logger.debug(
            "[PARALLEL-LOG] Worker INICIADO - Amostra %d, PID %d, Thread %d",
            index,
            process_id,
            thread_id,
        )

        result = self._evaluate_single_sample(sample, param_names, index)

        # Log temporário: worker concluído
        logger.debug(
            "[PARALLEL-LOG] Worker CONCLUÍDO - Amostra %d, Resultado: %f", index, result
        )

        return result

    def _evaluate_single_sample(
        self, sample: np.ndarray, param_names: List[str], index: int
    ) -> float:
        """Avalia uma única amostra."""
        try:
            # Converter amostra para dicionário de parâmetros
            # Converter numpy.float64 para tipos Python apropriados
            params = {}
            for name, value in zip(param_names, sample):
                # Converter para tipos apropriados baseado no nome do parâmetro
                if name in [
                    "pop_size",
                    "max_gens",
                    "tournament_k",
                    "immigrant_freq",
                    "restart_patience",
                    "mutation_multi_n",
                    "refine_iter_limit",
                    "niching_radius",
                    "mutation_adapt_duration",
                    "disable_elitismo_gens",
                    "max_iter",
                    "patience",
                    "max_restarts",
                    "beam_width",
                    "max_iterations",
                    "local_search_iters",
                    "restart_threshold",
                    "max_depth",
                    "memory_limit",
                    "morris_num_levels",
                    "morris_grid_jump",
                    "fast_m",
                ]:
                    params[name] = int(float(value))
                else:
                    params[name] = float(value)

            # Criar instância do algoritmo
            if self.algorithm_class is None:
                raise ValueError(
                    "Algorithm class not initialized. Make sure analyze() method was called with a valid algorithm name."
                )
            algorithm = self.algorithm_class(self.sequences, self.alphabet)

            # Aplicar parâmetros
            if hasattr(algorithm, "set_params"):
                algorithm.set_params(**params)
            elif hasattr(algorithm, "config") and algorithm.config is not None:
                # Atualizar configuração do algoritmo
                if hasattr(algorithm.config, "update") and callable(
                    algorithm.config.update
                ):
                    algorithm.config.update(params)
                else:
                    for key, value in params.items():
                        if hasattr(algorithm.config, key):
                            setattr(algorithm.config, key, value)
            else:
                # Tentar definir parâmetros diretamente
                for key, value in params.items():
                    if hasattr(algorithm, key):
                        setattr(algorithm, key, value)

            # Executar algoritmo
            start_time = time.time()
            result = algorithm.run()

            # Extrair distância do resultado
            if isinstance(result, tuple) and len(result) >= 2:
                center, distance = result[0], result[1]
            else:
                # Fallback para compatibilidade
                center, distance = result, float("inf")

            execution_time = time.time() - start_time

            # Verificar timeout
            if (
                self.config.timeout_per_sample
                and execution_time > self.config.timeout_per_sample
            ):
                logger.warning(
                    f"Amostra {index} excedeu timeout: {execution_time:.2f}s"
                )
                distance = float("inf")

            return float(distance)

        except Exception as e:
            logger.error(f"Erro na amostra {index}: {e}")
            return float("inf")

    def _analyze_results(
        self, problem: Dict[str, Any], outputs: np.ndarray
    ) -> Dict[str, Any]:
        """Analisa resultados usando método escolhido."""
        if self.config.method == "sobol":
            return sobol.analyze(
                problem,
                outputs,
                calc_second_order=self.config.sobol_calc_second_order,
                seed=self.config.seed,
            )
        elif self.config.method == "morris":
            return morris.analyze(problem, self.samples, outputs, seed=self.config.seed)
        elif self.config.method == "fast":
            return fast.analyze(
                problem, outputs, M=self.config.fast_m, seed=self.config.seed
            )
        else:
            raise ValueError(f"Método desconhecido: {self.config.method}")

    def analyze(
        self, algorithm_name: str, sequences: List[str], alphabet: str
    ) -> SensitivityResult:
        """Executa análise de sensibilidade."""
        logger.info(f"Iniciando análise de sensibilidade para {algorithm_name}")

        # Verificar se algoritmo existe
        if algorithm_name not in global_registry:
            raise ValueError(f"Algoritmo não encontrado: {algorithm_name}")

        self.algorithm_class = global_registry[algorithm_name]
        self.sequences = sequences
        self.alphabet = alphabet

        # Criar problema
        problem = self._create_problem(algorithm_name)
        logger.info(f"Analisando {problem['num_vars']} parâmetros: {problem['names']}")

        # Gerar amostras
        logger.info(f"Gerando amostras usando método {self.config.method}")
        samples = self._generate_samples(problem)
        self.samples = samples
        logger.info(f"Geradas {len(samples)} amostras")

        # Avaliar amostras
        start_time = time.time()
        outputs = self._evaluate_samples(samples, problem)

        # Filtrar valores inválidos - tratar de forma diferente para Morris
        valid_indices = np.isfinite(outputs)
        n_invalid = np.sum(~valid_indices)

        if n_invalid > 0:
            logger.warning(
                f"Substituindo {n_invalid} amostras inválidas por valores grandes"
            )
            # Para Morris, não podemos remover amostras, então substituímos valores inválidos
            # por um valor grande mas finito
            outputs[~valid_indices] = 1000.0  # Valor grande para indicar solução ruim

        # Executar análise
        logger.info("Executando análise de sensibilidade")
        analysis_results = self._analyze_results(problem, outputs)

        analysis_time = time.time() - start_time

        # Criar resultado
        result = SensitivityResult(
            parameter_names=problem["names"],
            method=self.config.method,
            n_samples=len(outputs),
            analysis_time=analysis_time,
            problem=problem,
            samples=samples,
            outputs=outputs,
        )

        # Extrair índices específicos para cada método
        if self.config.method == "sobol":
            result.first_order = {
                name: value
                for name, value in zip(problem["names"], analysis_results["S1"])
            }
            result.total_order = {
                name: value
                for name, value in zip(problem["names"], analysis_results["ST"])
            }
            if self.config.sobol_calc_second_order:
                # S2 é uma matriz, precisamos processar os índices de segunda ordem
                s2_matrix = analysis_results["S2"]
                result.second_order = {}
                for i in range(len(problem["names"])):
                    for j in range(i + 1, len(problem["names"])):
                        param_pair = f"{problem['names'][i]}-{problem['names'][j]}"
                        result.second_order[param_pair] = s2_matrix[i, j]

        elif self.config.method == "morris":
            result.mu = {
                name: value
                for name, value in zip(problem["names"], analysis_results["mu"])
            }
            result.mu_star = {
                name: value
                for name, value in zip(problem["names"], analysis_results["mu_star"])
            }
            result.sigma = {
                name: value
                for name, value in zip(problem["names"], analysis_results["sigma"])
            }

        elif self.config.method == "fast":
            result.first_order = {
                name: value
                for name, value in zip(problem["names"], analysis_results["S1"])
            }
            result.total_order = {
                name: value
                for name, value in zip(problem["names"], analysis_results["ST"])
            }

        logger.info(f"Análise concluída em {analysis_time:.2f}s")

        return result


def create_parameter_space(algorithm_name: str) -> Dict[str, List[float]]:
    """
    Cria espaço de parâmetros para análise de sensibilidade.

    Args:
        algorithm_name: Nome do algoritmo

    Returns:
        Dict com nomes dos parâmetros e seus intervalos
    """
    analyzer = SensitivityAnalyzer(SensitivityConfig())
    return analyzer._get_parameter_space(algorithm_name)


def analyze_algorithm_sensitivity(
    algorithm_name: str,
    sequences: List[str],
    alphabet: str,
    n_samples: int = 1000,
    method: str = "sobol",
    timeout_per_sample: Optional[float] = 60.0,
    show_progress: bool = True,
    seed: Optional[int] = None,
    yaml_config: Optional[Dict] = None,
    **kwargs,
) -> SensitivityResult:
    """
    Analisa sensibilidade de um algoritmo CSP aos seus hiperparâmetros.

    Args:
        algorithm_name: Nome do algoritmo a ser analisado
        sequences: Lista de sequências do dataset
        alphabet: Alfabeto usado nas sequências
        n_samples: Número de amostras para análise
        method: Método de análise ("sobol", "morris", "fast")
        timeout_per_sample: Timeout por amostra (segundos)
        show_progress: Mostrar barra de progresso
        seed: Seed para reprodutibilidade
        yaml_config: Configuração do YAML para paralelismo
        **kwargs: Parâmetros adicionais específicos do método

    Returns:
        SensitivityResult: Resultado da análise
    """
    from src.utils.worker_calculator import get_worker_config

    # Calcular configuração de workers
    worker_config = get_worker_config(
        yaml_config=yaml_config,
        context="salib",
        algorithm_name=algorithm_name,
        n_samples=n_samples,
    )  # Extrair configurações de paralelismo do YAML se disponível
    n_jobs = 1

    if yaml_config:
        # Tentar extrair de advanced (formato novo)
        if "advanced" in yaml_config and "parallel" in yaml_config["advanced"]:
            parallel_config = yaml_config["advanced"]["parallel"]
            yaml_n_jobs = parallel_config.get("n_jobs", 1)
            if yaml_n_jobs == -1:
                n_jobs = worker_config["salib_workers"]
            else:
                n_jobs = (
                    yaml_n_jobs if yaml_n_jobs > 0 else worker_config["salib_workers"]
                )
        # Formato legado: sensitivity_config.parallel
        elif "sensitivity_config" in yaml_config:
            sens_config = yaml_config["sensitivity_config"]
            if "parallel" in sens_config:
                yaml_n_jobs = sens_config["parallel"].get("n_jobs", 1)
                if yaml_n_jobs == -1:
                    n_jobs = worker_config["salib_workers"]
                else:
                    n_jobs = (
                        yaml_n_jobs
                        if yaml_n_jobs > 0
                        else worker_config["salib_workers"]
                    )

    # Criar configuração
    config = SensitivityConfig(
        n_samples=n_samples,
        method=method,
        timeout_per_sample=timeout_per_sample,
        show_progress=show_progress,
        seed=seed,
        n_jobs=n_jobs,
    )

    # Aplicar parâmetros específicos do método
    if method == "sobol":
        config.sobol_calc_second_order = kwargs.get("calc_second_order", True)
    elif method == "morris":
        config.morris_num_levels = kwargs.get("num_levels", 4)
        config.morris_grid_jump = kwargs.get("grid_jump", 2)
    elif method == "fast":
        config.fast_m = kwargs.get("M", 4)

    # Criar analisador
    analyzer = SensitivityAnalyzer(config)

    # Executar análise
    result = analyzer.analyze(algorithm_name, sequences, alphabet)

    return result


def run_sensitivity_with_dataset_selection():
    """
    Executa análise de sensibilidade com seleção interativa de dataset.
    """
    try:
        from src.ui.cli.menu import (
            configure_sensitivity_params,
            select_dataset_for_sensitivity,
            select_sensitivity_algorithm,
        )

        # Selecionar dataset
        sequences, alphabet, dataset_info = select_dataset_for_sensitivity()

        # Selecionar algoritmo
        algorithm_name = select_sensitivity_algorithm()

        # Configurar parâmetros
        config_dict = configure_sensitivity_params()

        # Executar análise
        print(f"\n🔬 Iniciando análise de sensibilidade do {algorithm_name}...")
        print(
            f"📊 Dataset: {dataset_info.get('type', 'N/A')} - {len(sequences)} sequências"
        )
        print(
            f"🔬 Amostras: {config_dict.get('n_samples', 1000)} | Método: {config_dict.get('method', 'sobol')}"
        )

        result = analyze_algorithm_sensitivity(
            algorithm_name=algorithm_name,
            sequences=sequences,
            alphabet=alphabet,
            n_samples=config_dict.get("n_samples", 1000),
            method=config_dict.get("method", "sobol"),
            timeout_per_sample=config_dict.get("timeout", 60),
            show_progress=True,
        )

        # Exibir resultados
        print(f"\n✅ Análise concluída!")
        print(f"⏱️ Tempo total: {result.analysis_time:.2f} segundos")
        print(f"📈 Amostras processadas: {result.n_samples}")
        print(f"🔬 Parâmetros analisados: {len(result.parameter_names)}")
        print(f"Método: {result.method}")

        # Salvar resultados
        os.makedirs("outputs/reports", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"outputs/reports/sensitivity_{algorithm_name}_{timestamp}.json"
        report = {
            "algorithm": algorithm_name,
            "dataset_info": dataset_info,
            "method": result.method,
            "n_samples": result.n_samples,
            "analysis_time": result.analysis_time,
            "parameter_names": result.parameter_names,
            "timestamp": timestamp,
        }
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str, ensure_ascii=False)
        print(f"💾 Relatório salvo em: {filename}")

    except Exception as e:
        print(f"❌ Erro na análise de sensibilidade: {e}")
        import traceback

        traceback.print_exc()
