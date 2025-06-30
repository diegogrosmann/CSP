"""
Sistema de execução em lote para múltiplas configurações de CSP.

Classes:
    BatchConfig: Representa uma configuração de execução
    BatchExecutor: Executa sequência de configurações
"""

import json
import time
import yaml
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import uuid
import logging

from src.console_manager import console
from src.runner import execute_algorithm_runs
from src.results_formatter import ResultsFormatter
from algorithms.baseline.implementation import greedy_consensus, max_distance
from algorithms.base import global_registry
from utils.resource_monitor import check_algorithm_feasibility
from utils.config import safe_input, ALGORITHM_TIMEOUT

logger = logging.getLogger(__name__)

def list_batch_configs() -> List[Path]:
    """Lista arquivos de configuração disponíveis."""
    config_dir = Path("batch_configs")
    if not config_dir.exists():
        config_dir.mkdir(exist_ok=True)
    
    # Procurar por arquivos JSON
    json_files = list(config_dir.glob("*.json"))
    return sorted(json_files)

def select_batch_config() -> str:
    """Menu para seleção de arquivo de configuração de lote."""
    batch_dir = Path("batch_configs")
    if not batch_dir.exists():
        batch_dir.mkdir(parents=True, exist_ok=True)
        console.print("📁 Diretório batch_configs criado.")
    
    # Buscar arquivos de configuração
    config_files = []
    for pattern in ['*.yaml', '*.yml', '*.json', '*.xml']:
        config_files.extend(batch_dir.glob(pattern))
    
    if not config_files:
        console.print("❌ Nenhum arquivo de configuração encontrado em batch_configs/")
        console.print("Crie um arquivo .yaml, .json ou .xml neste diretório.")
        return ""
    
    console.print("\n📋 Arquivos de configuração disponíveis:")
    for i, config_file in enumerate(config_files, 1):
        console.print(f"  {i}) {config_file.name}")
    
    while True:
        choice = safe_input(f"\nEscolha um arquivo [1-{len(config_files)}]: ")
        if choice.isdigit() and 1 <= int(choice) <= len(config_files):
            selected_file = config_files[int(choice) - 1]
            console.print(f"✓ Selecionado: {selected_file.name}")
            return str(selected_file)
        else:
            console.print("❌ Opção inválida.")

def create_example_config():
    """Cria arquivo de configuração de exemplo."""
    config_dir = Path("batch_configs")
    config_dir.mkdir(exist_ok=True)
    
    example_config = {
        "batch_info": {
            "nome": "Experimento Exemplo CSP",
            "descricao": "Configuração de exemplo para testes comparativos",
            "timeout_global": 1800
        },
        "execucoes": [
            {
                "nome": "Sintético Pequeno",
                "dataset": {
                    "tipo": "synthetic",
                    "parametros": {
                        "n": 10,
                        "L": 50,
                        "alphabet": "ACGT",
                        "noise": 0.1
                    }
                },
                "algoritmos": ["Baseline", "BLF-GA", "H³-CSP"],
                "execucoes_por_algoritmo": 3,
                "timeout": 300
            },
            {
                "nome": "Sintético Médio",
                "dataset": {
                    "tipo": "synthetic",
                    "parametros": {
                        "n": 20,
                        "L": 100,
                        "alphabet": "ACGT",
                        "noise": 0.15
                    }
                },
                "algoritmos": ["Baseline", "BLF-GA", "CSC"],
                "execucoes_por_algoritmo": 3,
                "timeout": 600
            },
            {
                "nome": "Dataset de Arquivo",
                "dataset": {
                    "tipo": "file",
                    "parametros": {
                        "filepath": "saved_datasets/sequences.fasta"
                    }
                },
                "algoritmos": ["Baseline", "BLF-GA"],
                "execucoes_por_algoritmo": 3,
                "timeout": 900
            }
        ]
    }
    
    example_path = config_dir / "exemplo_batch.json"
    with open(example_path, 'w', encoding='utf-8') as f:
        json.dump(example_config, f, indent=2, ensure_ascii=False)
    
    console.print(f"📄 Arquivo de exemplo criado: {example_path}")
    console.print("💡 Edite este arquivo para personalizar suas configurações")

class BatchConfig:
    """Representa uma configuração individual de execução."""
    
    def __init__(self, config_dict: Dict[str, Any]):
        self.nome = config_dict.get('nome', 'Execução Sem Nome')
        self.dataset_config = config_dict.get('dataset', {})
        self.algoritmos = config_dict.get('algoritmos', ['Baseline'])
        self.execucoes_por_algoritmo = config_dict.get('execucoes_por_algoritmo', 3)
        self.timeout = config_dict.get('timeout', ALGORITHM_TIMEOUT)
        
    def __str__(self):
        return f"BatchConfig({self.nome}, {len(self.algoritmos)} algoritmos, {self.execucoes_por_algoritmo} exec cada)"

class BatchExecutor:
    """Executa uma sequência de configurações em lote."""
    
    def __init__(self, config_file: str):
        self.config_file = Path(config_file)
        self.batch_info = {}
        self.execucoes = []
        self.results = {}
        self.consolidated_formatter = ResultsFormatter()
        
        # Identificador único para esta execução em lote
        self.batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        self._load_config()
        
    def _load_config(self):
        """Carrega configuração do arquivo YAML, JSON ou XML."""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                if self.config_file.suffix.lower() in ['.yaml', '.yml']:
                    config = yaml.safe_load(f)
                elif self.config_file.suffix.lower() == '.json':
                    config = json.load(f)
                elif self.config_file.suffix.lower() == '.xml':
                    config = self._parse_xml(f)
                else:
                    raise ValueError(f"Formato de arquivo não suportado: {self.config_file.suffix}")
                    
            self.batch_info = config.get('batch_info', {})
            execucoes_raw = config.get('execucoes', [])
            
            # Converte para objetos BatchConfig
            self.execucoes = [BatchConfig(exec_config) for exec_config in execucoes_raw]
            
            console.print(f"✓ Configuração carregada: {len(self.execucoes)} execuções planejadas")
            
        except Exception as e:
            console.print(f"❌ Erro ao carregar configuração: {e}")
            raise
            
    def _parse_xml(self, file_handle):
        """Converte XML para estrutura de dicionário compatível."""
        tree = ET.parse(file_handle)
        root = tree.getroot()
        
        config = {}
        
        # Parse batch_info
        batch_info_elem = root.find('batch_info')
        if batch_info_elem is not None:
            batch_info = {}
            for child in batch_info_elem:
                if child.tag in ['timeout_global'] and child.text is not None:
                    batch_info[child.tag] = int(child.text)
                else:
                    batch_info[child.tag] = child.text if child.text is not None else ""
            config['batch_info'] = batch_info
        
        # Parse execucoes
        execucoes_elem = root.find('execucoes')
        execucoes = []
        
        if execucoes_elem is not None:
            for exec_elem in execucoes_elem.findall('execucao'):
                exec_config = {}
                
                # Nome
                nome_elem = exec_elem.find('nome')
                if nome_elem is not None and nome_elem.text is not None:
                    exec_config['nome'] = nome_elem.text
                
                # Dataset
                dataset_elem = exec_elem.find('dataset')
                if dataset_elem is not None:
                    dataset_config = {}
                    
                    tipo_elem = dataset_elem.find('tipo')
                    if tipo_elem is not None and tipo_elem.text is not None:
                        dataset_config['tipo'] = tipo_elem.text
                    
                    params_elem = dataset_elem.find('parametros')
                    if params_elem is not None:
                        parametros = {}
                        for param in params_elem:
                            if param.text is None:
                                continue
                            if param.tag in ['n', 'L']:
                                parametros[param.tag] = int(param.text)
                            elif param.tag == 'noise':
                                parametros[param.tag] = float(param.text)
                            else:
                                parametros[param.tag] = param.text
                        dataset_config['parametros'] = parametros
                    
                    exec_config['dataset'] = dataset_config
                
                # Algoritmos
                algs_elem = exec_elem.find('algoritmos')
                if algs_elem is not None:
                    algoritmos = []
                    for alg_elem in algs_elem.findall('algoritmo'):
                        if alg_elem.text is not None:
                            algoritmos.append(alg_elem.text)
                    exec_config['algoritmos'] = algoritmos
                
                # Execuções por algoritmo
                exec_per_alg_elem = exec_elem.find('execucoes_por_algoritmo')
                if exec_per_alg_elem is not None and exec_per_alg_elem.text is not None:
                    exec_config['execucoes_por_algoritmo'] = int(exec_per_alg_elem.text)
                
                # Timeout
                timeout_elem = exec_elem.find('timeout')
                if timeout_elem is not None and timeout_elem.text is not None:
                    exec_config['timeout'] = int(timeout_elem.text)
                
                execucoes.append(exec_config)
        
        config['execucoes'] = execucoes
        return config

    def _generate_dataset(self, dataset_config: Dict[str, Any]) -> tuple[List[str], Dict[str, Any]]:
        """Gera ou carrega dataset baseado na configuração."""
        dataset_type = dataset_config.get('tipo', 'synthetic')
        params = dataset_config.get('parametros', {})
        
        if dataset_type == 'synthetic':
            from datasets.dataset_synthetic import generate_dataset_with_params
            return generate_dataset_with_params(params)
            
        elif dataset_type == 'file':
            from datasets.dataset_file import load_dataset_with_params
            return load_dataset_with_params(params)
            
        elif dataset_type == 'entrez':
            from datasets.dataset_entrez import fetch_dataset_with_params
            return fetch_dataset_with_params(params)
            
        else:
            raise ValueError(f"Tipo de dataset não suportado: {dataset_type}")
    
    def _execute_single_config(self, config: BatchConfig, exec_index: int) -> Dict[str, Any]:
        """Executa uma configuração individual."""
        console.print(f"\n{'='*60}")
        console.print(f"EXECUÇÃO {exec_index + 1}/{len(self.execucoes)}: {config.nome}")
        console.print(f"{'='*60}")
        
        start_time = time.time()
        result = {
            'config_nome': config.nome,
            'inicio': datetime.now().isoformat(),
            'algoritmos_executados': {},
            'erro': None,
            'tempo_total': 0.0
        }
        
        try:
            # Gerar/carregar dataset
            console.print(f"📊 Gerando dataset...")
            seqs, dataset_params = self._generate_dataset(config.dataset_config)
            
            if not seqs:
                raise ValueError("Dataset vazio gerado")
                
            alphabet = ''.join(sorted(set(''.join(seqs))))
            n, L = len(seqs), len(seqs[0])
            
            console.print(f"Dataset: n={n}, L={L}, |Σ|={len(alphabet)}")
            result['dataset_info'] = {
                'n': n, 'L': L, 'alphabet_size': len(alphabet),
                'params': dataset_params
            }
            
            # Verificar viabilidade dos algoritmos
            viable_algs = []
            for alg_name in config.algoritmos:
                is_viable, msg = check_algorithm_feasibility(n, L, alg_name)
                if is_viable:
                    viable_algs.append(alg_name)
                    console.print(f"✓ {alg_name}: viável")
                else:
                    console.print(f"⚠ {alg_name}: {msg} (pulado)")
            
            if not viable_algs:
                console.print("❌ Nenhum algoritmo viável")
                result['erro'] = "Nenhum algoritmo viável para este dataset"
                return result
            
            # Baseline
            console.print(f"\n🎯 Executando Baseline...")
            baseline_start = time.time()
            baseline_center = greedy_consensus(seqs, alphabet)
            baseline_val = max_distance(baseline_center, seqs)
            baseline_time = time.time() - baseline_start
            
            console.print(f"Baseline: dist={baseline_val}, tempo={baseline_time:.3f}s")
            
            # Criar formatter para esta execução
            exec_formatter = ResultsFormatter()
            baseline_executions = [{
                'tempo': baseline_time,
                'iteracoes': 1,
                'distancia': baseline_val,
                'melhor_string': baseline_center,
                'gap': 0.0
            }]
            exec_formatter.add_algorithm_results("Baseline", baseline_executions)
            
            # Adicionar ao formatter consolidado
            exec_key = f"{config.nome}_Baseline"
            self.consolidated_formatter.add_algorithm_results(exec_key, baseline_executions)
            
            # Executar outros algoritmos
            for alg_name in viable_algs:
                if alg_name == "Baseline":
                    continue
                    
                console.print(f"\n🔄 Executando {alg_name}...")
                
                if alg_name not in global_registry:
                    console.print(f"❌ Algoritmo '{alg_name}' não encontrado!")
                    continue
                    
                AlgClass = global_registry[alg_name]
                
                try:
                    executions = execute_algorithm_runs(
                        alg_name, AlgClass, seqs, alphabet, 
                        config.execucoes_por_algoritmo, baseline_val, 
                        console, config.timeout
                    )
                    
                    exec_formatter.add_algorithm_results(alg_name, executions)
                    
                    # Adicionar ao formatter consolidado com chave única
                    exec_key = f"{config.nome}_{alg_name}"
                    self.consolidated_formatter.add_algorithm_results(exec_key, executions)
                    
                    # Extrair melhor resultado
                    valid_results = [e for e in executions if 'distancia' in e and e['distancia'] != float('inf')]
                    if valid_results:
                        best_exec = min(valid_results, key=lambda e: e['distancia'])
                        result['algoritmos_executados'][alg_name] = {
                            'dist': best_exec['distancia'],
                            'time': best_exec['tempo'],
                            'gap': best_exec.get('gap', 0.0),
                            'status': 'sucesso'
                        }
                    else:
                        error_exec = next((e for e in executions if 'erro' in e), executions[0])
                        result['algoritmos_executados'][alg_name] = {
                            'dist': float('inf'),
                            'time': error_exec['tempo'],
                            'gap': float('inf'),
                            'status': 'erro',
                            'erro': error_exec.get('erro', 'Erro desconhecido')
                        }
                        
                except Exception as e:
                    console.print(f"❌ Erro executando {alg_name}: {e}")
                    result['algoritmos_executados'][alg_name] = {
                        'dist': float('inf'),
                        'time': 0.0,
                        'gap': float('inf'),
                        'status': 'erro',
                        'erro': str(e)
                    }
            
            # Salvar relatório individual
            report_filename = f"{self.batch_id}_{exec_index+1}_{config.nome.replace(' ', '_')}.txt"
            exec_formatter.save_detailed_report(report_filename)
            console.print(f"📄 Relatório salvo: {report_filename}")
            
        except Exception as e:
            console.print(f"❌ Erro na execução: {e}")
            logger.exception(f"Erro na execução {config.nome}")
            result['erro'] = str(e)
            
        finally:
            result['tempo_total'] = time.time() - start_time
            result['fim'] = datetime.now().isoformat()
            
        return result
    
    def execute_batch(self) -> Dict[str, Any]:
        """Executa todas as configurações em sequência."""
        console.print(f"\n🚀 INICIANDO EXECUÇÃO EM LOTE")
        console.print(f"Lote: {self.batch_info.get('nome', 'Sem nome')}")
        console.print(f"Descrição: {self.batch_info.get('descricao', 'Sem descrição')}")
        console.print(f"Total de execuções: {len(self.execucoes)}")
        
        batch_start = time.time()
        batch_result = {
            'batch_info': self.batch_info,
            'batch_id': self.batch_id,
            'inicio': datetime.now().isoformat(),
            'execucoes': [],
            'resumo': {},
            'tempo_total': 0.0
        }
        
        # Executar cada configuração
        for i, config in enumerate(self.execucoes):
            try:
                exec_result = self._execute_single_config(config, i)
                batch_result['execucoes'].append(exec_result)
                
                # Mostrar progresso
                elapsed = time.time() - batch_start
                console.print(f"\n⏱️ Execução {i+1} concluída em {exec_result['tempo_total']:.1f}s")
                console.print(f"Tempo decorrido total: {elapsed:.1f}s")
                
            except KeyboardInterrupt:
                console.print(f"\n⚠️ Execução em lote interrompida pelo usuário")
                break
            except Exception as e:
                console.print(f"\n❌ Erro fatal na execução {i+1}: {e}")
                logger.exception(f"Erro fatal na execução {config.nome}")
                continue
        
        # Finalizar lote
        batch_result['tempo_total'] = time.time() - batch_start
        batch_result['fim'] = datetime.now().isoformat()
        
        # Gerar resumo
        self._generate_batch_summary(batch_result)
        
        # Salvar relatório consolidado
        self._save_batch_report(batch_result)
        
        return batch_result
    
    def _generate_batch_summary(self, batch_result: Dict[str, Any]):
        """Gera resumo consolidado do lote."""
        total_execucoes = len(batch_result['execucoes'])
        execucoes_com_sucesso = len([e for e in batch_result['execucoes'] if not e.get('erro')])
        
        console.print(f"\n📋 RESUMO DO LOTE")
        console.print(f"{'='*50}")
        console.print(f"Total de execuções: {total_execucoes}")
        console.print(f"Execuções com sucesso: {execucoes_com_sucesso}")
        console.print(f"Taxa de sucesso: {100 * execucoes_com_sucesso / total_execucoes:.1f}%")
        console.print(f"Tempo total: {batch_result['tempo_total']:.1f}s")
        
        # Resumo por algoritmo
        alg_stats = {}
        for exec_result in batch_result['execucoes']:
            if exec_result.get('erro'):
                continue
            for alg_name, alg_result in exec_result.get('algoritmos_executados', {}).items():
                if alg_name not in alg_stats:
                    alg_stats[alg_name] = {'sucessos': 0, 'total': 0, 'tempo_medio': 0.0}
                alg_stats[alg_name]['total'] += 1
                if alg_result.get('status') == 'sucesso':
                    alg_stats[alg_name]['sucessos'] += 1
                    alg_stats[alg_name]['tempo_medio'] += alg_result.get('time', 0.0)
        
        console.print(f"\n📈 Estatísticas por algoritmo:")
        for alg_name, stats in alg_stats.items():
            taxa = 100 * stats['sucessos'] / stats['total'] if stats['total'] > 0 else 0
            tempo_med = stats['tempo_medio'] / stats['sucessos'] if stats['sucessos'] > 0 else 0
            console.print(f"  {alg_name}: {stats['sucessos']}/{stats['total']} sucessos ({taxa:.1f}%), tempo médio: {tempo_med:.3f}s")
        
        batch_result['resumo'] = {
            'total_execucoes': total_execucoes,
            'execucoes_com_sucesso': execucoes_com_sucesso,
            'taxa_sucesso': 100 * execucoes_com_sucesso / total_execucoes if total_execucoes > 0 else 0,
            'algoritmo_stats': alg_stats
        }
    
    def _save_batch_report(self, batch_result: Dict[str, Any]):
        """Salva relatório consolidado do lote."""
        # Relatório JSON detalhado
        json_filename = f"{self.batch_id}_batch_results.json"
        json_path = Path("results") / json_filename
        json_path.parent.mkdir(exist_ok=True)
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(batch_result, f, indent=2, ensure_ascii=False)
        
        console.print(f"💾 Relatório JSON salvo: {json_filename}")
        
        # Relatório consolidado de algoritmos
        consolidated_filename = f"{self.batch_id}_consolidated_algorithms.txt"
        self.consolidated_formatter.save_detailed_report(consolidated_filename)
        console.print(f"📄 Relatório consolidado salvo: {consolidated_filename}")
