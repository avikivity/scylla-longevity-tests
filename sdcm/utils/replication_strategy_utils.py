import ast
import re

from contextlib import ContextDecorator
from typing import Callable, Dict

from sdcm.cluster import BaseNode


class ReplicationStrategy:  # pylint: disable=too-few-public-methods

    @classmethod
    def from_string(cls, replication_string):
        replication_value = re.search(r".*replication[\s]*=[\s]*(\{.*\})", replication_string, flags=re.IGNORECASE)
        strategy_params = ast.literal_eval(replication_value[1])
        strategy_class = strategy_params.pop("class")
        for class_ in replication_strategies:
            if strategy_class == class_.class_:
                return class_(**strategy_params)
        raise ValueError(f"Couldn't find such replication strategy: {replication_value}")


class SimpleReplicationStrategy(ReplicationStrategy):

    class_: str = 'SimpleStrategy'

    def __init__(self, replication_factor: int):
        self.replication_factor = replication_factor

    def __str__(self):
        return f"{{'class': '{self.class_}', 'replication_factor': {self.replication_factor}}}"


class NetworkTopologyReplicationStrategy(ReplicationStrategy):

    class_: str = 'NetworkTopologyStrategy'

    def __init__(self, **replication_factors: int):
        self.replication_factors = replication_factors

    def __str__(self):
        factors = ', '.join([f"'{key}': {value}" for key, value in self.replication_factors.items()])
        return f"{{'class': '{self.class_}', {factors}}}"


replication_strategies = [SimpleReplicationStrategy, NetworkTopologyReplicationStrategy]


class temporary_replication_strategy_setter(ContextDecorator):  # pylint: disable=invalid-name
    """Context manager that allows to set replication strategy
     and preserves all modified keyspaces for automatic rollback on exit."""

    def __init__(self, node: BaseNode) -> None:
        self.node = node
        self.preserved: Dict[str, ReplicationStrategy] = {}

    def __enter__(self) -> Callable[..., None]:
        return self

    def __exit__(self, *exc) -> bool:
        self(**self.preserved)
        return False

    def _preserve_replication_strategy(self, keyspace: str) -> None:
        if keyspace in self.preserved:
            return  # already preserved
        create_ks_statement = self.node.run_cqlsh(f"describe {keyspace}").stdout.splitlines()[1]
        self.preserved[keyspace] = (ReplicationStrategy.from_string(create_ks_statement))

    def __call__(self, **keyspaces: ReplicationStrategy) -> None:
        for keyspace, strategy in keyspaces.items():
            self._preserve_replication_strategy(keyspace)
            cql = f"ALTER KEYSPACE {keyspace} WITH replication = {strategy}"
            self.node.run_cqlsh(cql)
