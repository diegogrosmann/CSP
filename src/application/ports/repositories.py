"""
Portas da Aplicação - Interfaces para Infraestrutura

Este módulo define as interfaces (ports) que devem ser implementadas
pela camada de infraestrutura seguindo o padrão de arquitetura hexagonal.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from src.domain import CSPAlgorithm, Dataset


@runtime_checkable
class DatasetRepository(Protocol):
    """Port para repositório de datasets."""

    def save(self, dataset: Dataset, name: str) -> str:
        """
        Salva dataset com nome específico.

        Args:
            dataset: Dataset a ser salvo
            name: Nome para identificar o dataset

        Returns:
            str: Identificador ou caminho do dataset salvo
        """
        ...

    def load(self, identifier: str) -> Dataset:
        """
        Carrega dataset por identificador.

        Args:
            identifier: Identificador do dataset

        Returns:
            Dataset: Dataset carregado
        """
        ...

    def list_available(self) -> List[str]:
        """
        Lista datasets disponíveis.

        Returns:
            List[str]: Lista de identificadores disponíveis
        """
        ...

    def exists(self, identifier: str) -> bool:
        """
        Verifica se dataset existe.

        Args:
            identifier: Identificador do dataset

        Returns:
            bool: True se existe
        """
        ...

    def delete(self, identifier: str) -> bool:
        """
        Remove dataset.

        Args:
            identifier: Identificador do dataset

        Returns:
            bool: True se removido com sucesso
        """
        ...


@runtime_checkable
class AlgorithmRegistry(Protocol):
    """Port para registry de algoritmos."""

    def get_algorithm(self, name: str) -> type[CSPAlgorithm]:
        """
        Obtém classe de algoritmo por nome.

        Args:
            name: Nome do algoritmo

        Returns:
            type[CSPAlgorithm]: Classe do algoritmo
        """
        ...

    def list_algorithms(self) -> List[str]:
        """
        Lista algoritmos disponíveis.

        Returns:
            List[str]: Nomes dos algoritmos disponíveis
        """
        ...

    def register_algorithm(self, algorithm_class: type[CSPAlgorithm]) -> None:
        """
        Registra novo algoritmo.

        Args:
            algorithm_class: Classe do algoritmo a ser registrada
        """
        ...

    def algorithm_exists(self, name: str) -> bool:
        """
        Verifica se algoritmo existe.

        Args:
            name: Nome do algoritmo

        Returns:
            bool: True se existe
        """
        ...

    def get_algorithm_metadata(self, name: str) -> Dict[str, Any]:
        """
        Obtém metadados de algoritmo.

        Args:
            name: Nome do algoritmo

        Returns:
            Dict[str, Any]: Metadados do algoritmo
        """
        ...


@runtime_checkable
class ExportPort(Protocol):
    """Port para exportação de resultados."""

    def export_results(
        self, results: Dict[str, Any], format_type: str, destination: str
    ) -> str:
        """
        Exporta resultados em formato específico.

        Args:
            results: Dados dos resultados
            format_type: Formato de exportação (csv, json, xlsx, etc.)
            destination: Destino da exportação

        Returns:
            str: Caminho do arquivo exportado
        """
        ...

    def export_batch_results(
        self, batch_results: List[Dict[str, Any]], format_type: str, destination: str
    ) -> str:
        """
        Exporta resultados de batch.

        Args:
            batch_results: Lista de resultados
            format_type: Formato de exportação
            destination: Destino da exportação

        Returns:
            str: Caminho do arquivo exportado
        """
        ...

    def get_supported_formats(self) -> List[str]:
        """
        Lista formatos suportados.

        Returns:
            List[str]: Formatos disponíveis
        """
        ...

    def export_optimization_results(
        self, optimization_data: Dict[str, Any], destination: str
    ) -> str:
        """
        Exporta resultados de otimização.

        Args:
            optimization_data: Dados da otimização
            destination: Destino da exportação

        Returns:
            str: Caminho do arquivo exportado
        """
        ...


@runtime_checkable
class ExecutorPort(Protocol):
    """Port para execução de algoritmos."""

    def execute_batch(
        self, batch_config: Dict[str, Any], monitoring_service=None
    ) -> List[Dict[str, Any]]:
        """
        Executa batch de experimentos.

        Args:
            batch_config: Configuração do batch
            monitoring_service: Serviço de monitoramento (opcional)

        Returns:
            List[Dict[str, Any]]: Lista de resultados
        """
        ...

    def execute_optimization(
        self,
        algorithm_name: str,
        dataset: Dataset,
        optimization_config: Dict[str, Any],
        monitoring_service=None,
        config_index: int = 1,
        total_configs: int = 1,
        dataset_index: int = 1,
        total_datasets: int = 1,
    ) -> Dict[str, Any]:
        """
        Executa otimização de hiperparâmetros.

        Args:
            algorithm_name: Nome do algoritmo
            dataset: Dataset para otimização
            optimization_config: Configuração da otimização
            monitoring_service: Serviço de monitoramento (opcional)

        Returns:
            Dict[str, Any]: Resultados da otimização
        """
        ...

    def execute_sensitivity_analysis(
        self, algorithm_name: str, dataset: Dataset, sensitivity_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Executa análise de sensibilidade.

        Args:
            algorithm_name: Nome do algoritmo
            dataset: Dataset para análise
            sensitivity_config: Configuração da análise

        Returns:
            Dict[str, Any]: Resultados da análise
        """
        ...

    def get_execution_status(self, execution_id: str) -> str:
        """
        Obtém status de execução.

        Args:
            execution_id: ID da execução

        Returns:
            str: Status da execução
        """
        ...

    def cancel_execution(self, execution_id: str) -> bool:
        """
        Cancela execução em andamento.

        Args:
            execution_id: ID da execução

        Returns:
            bool: True se cancelada com sucesso
        """
        ...


# Interfaces ABC alternativas para casos onde Protocol não é adequado


class AbstractDatasetRepository(ABC):
    """Interface ABC para repositório de datasets."""

    @abstractmethod
    def save(self, dataset: Dataset, name: str) -> str:
        """Salva dataset com nome específico."""
        pass

    @abstractmethod
    def load(self, identifier: str) -> Dataset:
        """Carrega dataset por identificador."""
        pass

    @abstractmethod
    def list_available(self) -> List[str]:
        """Lista datasets disponíveis."""
        pass

    @abstractmethod
    def exists(self, identifier: str) -> bool:
        """Verifica se dataset existe."""
        pass

    @abstractmethod
    def delete(self, identifier: str) -> bool:
        """Remove dataset."""
        pass


class AbstractAlgorithmRegistry(ABC):
    """Interface ABC para registry de algoritmos."""

    @abstractmethod
    def get_algorithm(self, name: str) -> type[CSPAlgorithm]:
        """Obtém classe de algoritmo por nome."""
        pass

    @abstractmethod
    def list_algorithms(self) -> List[str]:
        """Lista algoritmos disponíveis."""
        pass

    @abstractmethod
    def register_algorithm(self, algorithm_class: type[CSPAlgorithm]) -> None:
        """Registra novo algoritmo."""
        pass

    @abstractmethod
    def algorithm_exists(self, name: str) -> bool:
        """Verifica se algoritmo existe."""
        pass

    @abstractmethod
    def get_algorithm_metadata(self, name: str) -> Dict[str, Any]:
        """Obtém metadados de algoritmo."""
        pass


class AbstractExportPort(ABC):
    """Interface ABC para exportação de resultados."""

    @abstractmethod
    def export_results(
        self, results: Dict[str, Any], format_type: str, destination: str
    ) -> str:
        """Exporta resultados em formato específico."""
        pass

    @abstractmethod
    def export_batch_results(
        self, batch_results: List[Dict[str, Any]], format_type: str, destination: str
    ) -> str:
        """Exporta resultados de batch."""
        pass

    @abstractmethod
    def get_supported_formats(self) -> List[str]:
        """Lista formatos suportados."""
        pass

    @abstractmethod
    def export_optimization_results(
        self, optimization_data: Dict[str, Any], destination: str
    ) -> str:
        """Exporta resultados de otimização."""
        pass


class AbstractExecutorPort(ABC):
    """Interface ABC para execução de algoritmos."""

    @abstractmethod
    def execute_batch(self, batch_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Executa batch de experimentos."""
        pass

    @abstractmethod
    def execute_optimization(
        self,
        algorithm_name: str,
        dataset: Dataset,
        optimization_config: Dict[str, Any],
        monitoring_service=None,
        config_index: int = 1,
        total_configs: int = 1,
        dataset_index: int = 1,
        total_datasets: int = 1,
    ) -> Dict[str, Any]:
        """Executa otimização de hiperparâmetros."""
        pass

    @abstractmethod
    def execute_sensitivity_analysis(
        self, algorithm_name: str, dataset: Dataset, sensitivity_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Executa análise de sensibilidade."""
        pass

    @abstractmethod
    def get_execution_status(self, execution_id: str) -> str:
        """Obtém status de execução."""
        pass

    @abstractmethod
    def cancel_execution(self, execution_id: str) -> bool:
        """Cancela execução em andamento."""
        pass
