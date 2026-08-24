"""
Directed Acyclic Graph (DAG) — dependency resolution and impact analysis.
No external deps (no networkx). Pure Python topological sort, cycle detection,
build order computation, and impact propagation.

Used for: repo dependency ordering, build sequencing, change impact analysis.
"""

from __future__ import annotations

from collections import deque
from typing import Optional


class CycleDetectedError(Exception):
    """Raised when a cycle is detected in the DAG."""

    def __init__(self, cycle_path: list[str]):
        self.cycle_path = cycle_path
        super().__init__(f"Cycle detected: {' -> '.join(cycle_path)}")


class DAG:
    """
    Directed Acyclic Graph with topological sort and impact analysis.
    No external dependencies -- pure Python implementation.
    """

    def __init__(self):
        # node_id -> set of dependencies (things this node depends on)
        self._dependencies: dict[str, set[str]] = {}
        # node_id -> set of dependents (things that depend on this node)
        self._dependents: dict[str, set[str]] = {}
        # All nodes in the graph
        self._nodes: set[str] = set()

    # ─── Node Operations ──────────────────────────────────────────────

    def add_node(self, node_id: str) -> None:
        """Add a node to the DAG."""
        self._nodes.add(node_id)
        self._dependencies.setdefault(node_id, set())
        self._dependents.setdefault(node_id, set())

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and all its edges."""
        if node_id not in self._nodes:
            return False

        # Remove from others' dependents
        for dep in self._dependencies.get(node_id, set()):
            self._dependents.get(dep, set()).discard(node_id)

        # Remove from others' dependencies
        for dependent in self._dependents.get(node_id, set()):
            self._dependencies.get(dependent, set()).discard(node_id)

        self._nodes.discard(node_id)
        self._dependencies.pop(node_id, None)
        self._dependents.pop(node_id, None)
        return True

    @property
    def nodes(self) -> set[str]:
        return self._nodes.copy()

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    # ─── Edge Operations ──────────────────────────────────────────────

    def add_edge(self, from_node: str, to_node: str) -> None:
        """
        Add a dependency edge: from_node DEPENDS ON to_node.
        Validates no cycle is introduced.

        Raises CycleDetectedError if adding this edge would create a cycle.
        """
        # Auto-add nodes
        self.add_node(from_node)
        self.add_node(to_node)

        # Self-loop check
        if from_node == to_node:
            raise CycleDetectedError([from_node, to_node])

        # Check if adding this edge creates a cycle
        # (would to_node reach from_node through existing edges?)
        if self._would_create_cycle(from_node, to_node):
            cycle = self._find_cycle_path(from_node, to_node)
            raise CycleDetectedError(cycle)

        self._dependencies[from_node].add(to_node)
        self._dependents[to_node].add(from_node)

    def remove_edge(self, from_node: str, to_node: str) -> bool:
        """Remove a dependency edge."""
        if from_node not in self._dependencies:
            return False
        if to_node not in self._dependencies[from_node]:
            return False
        self._dependencies[from_node].discard(to_node)
        self._dependents[to_node].discard(from_node)
        return True

    def has_edge(self, from_node: str, to_node: str) -> bool:
        """Check if an edge exists."""
        return to_node in self._dependencies.get(from_node, set())

    # ─── Topological Sort ─────────────────────────────────────────────

    def topological_sort(self) -> list[str]:
        """
        Kahn's algorithm for topological sort.
        Returns nodes in dependency order (dependencies first).
        Raises CycleDetectedError if graph has cycles.
        """
        # Calculate in-degrees (number of dependencies)
        in_degree = {node: len(self._dependencies[node]) for node in self._nodes}

        # Start with nodes that have no dependencies
        queue = deque([n for n, d in in_degree.items() if d == 0])
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)

            # For each node that depends on this one, decrease in-degree
            for dependent in self._dependents.get(node, set()):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self._nodes):
            # Cycle exists -- find and report it
            remaining = self._nodes - set(result)
            cycle = self._find_any_cycle(remaining)
            raise CycleDetectedError(cycle)

        return result

    def build_order(self) -> list[list[str]]:
        """
        Returns build order as layers/levels.
        Each layer can be built in parallel; layers must be sequential.
        Layer 0 = no dependencies, Layer 1 = depends only on Layer 0, etc.
        """
        in_degree = {node: len(self._dependencies[node]) for node in self._nodes}
        levels: list[list[str]] = []

        current_level = [n for n, d in in_degree.items() if d == 0]
        remaining = set(self._nodes)

        while current_level:
            levels.append(sorted(current_level))
            next_level = []

            for node in current_level:
                remaining.discard(node)
                for dependent in self._dependents.get(node, set()):
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_level.append(dependent)

            current_level = next_level

        if remaining:
            raise CycleDetectedError(list(remaining)[:5])

        return levels

    # ─── Impact Analysis ──────────────────────────────────────────────

    def impact_of(self, node_id: str) -> set[str]:
        """
        What breaks if this node changes?
        Returns all transitive dependents (things that depend on this).
        """
        if node_id not in self._nodes:
            return set()

        impacted = set()
        queue = deque([node_id])

        while queue:
            current = queue.popleft()
            for dependent in self._dependents.get(current, set()):
                if dependent not in impacted:
                    impacted.add(dependent)
                    queue.append(dependent)

        return impacted

    def dependencies_of(self, node_id: str) -> set[str]:
        """
        What does this node need?
        Returns all transitive dependencies.
        """
        if node_id not in self._nodes:
            return set()

        deps = set()
        queue = deque([node_id])

        while queue:
            current = queue.popleft()
            for dep in self._dependencies.get(current, set()):
                if dep not in deps:
                    deps.add(dep)
                    queue.append(dep)

        return deps

    def critical_path(self, node_id: str) -> list[str]:
        """
        Find the longest dependency chain ending at node_id.
        This is the critical path -- the bottleneck for building this node.
        """
        if node_id not in self._nodes:
            return []

        # BFS from node_id backwards through dependencies
        longest = [node_id]
        queue = deque([(node_id, [node_id])])

        while queue:
            current, path = queue.popleft()
            for dep in self._dependencies.get(current, set()):
                new_path = path + [dep]
                if len(new_path) > len(longest):
                    longest = new_path
                queue.append((dep, new_path))

        # Return reversed (from root dependency to target)
        return list(reversed(longest))

    # ─── Roots and Leaves ─────────────────────────────────────────────

    def roots(self) -> list[str]:
        """Nodes with no dependencies (foundation layer)."""
        return sorted([n for n in self._nodes if not self._dependencies[n]])

    def leaves(self) -> list[str]:
        """Nodes with no dependents (top-level consumers)."""
        return sorted([n for n in self._nodes if not self._dependents[n]])

    # ─── Cycle Detection ──────────────────────────────────────────────

    def has_cycle(self) -> bool:
        """Check if the graph has any cycles."""
        try:
            self.topological_sort()
            return False
        except CycleDetectedError:
            return True

    def _would_create_cycle(self, from_node: str, to_node: str) -> bool:
        """Check if adding from_node -> to_node would create a cycle."""
        # A cycle exists if to_node can already reach from_node
        visited = set()
        queue = deque([from_node])

        while queue:
            current = queue.popleft()
            if current == to_node:
                return True
            if current in visited:
                continue
            visited.add(current)
            # Follow reverse: who does current depend on?
            # Actually we need to check: can to_node reach from_node via deps?
            # from_node DEPENDS_ON to_node. Cycle = to_node already depends on from_node.
            pass

        # Correct approach: check if from_node is reachable from to_node
        visited = set()
        queue = deque([to_node])
        while queue:
            current = queue.popleft()
            if current == from_node:
                return True
            if current in visited:
                continue
            visited.add(current)
            for dep in self._dependencies.get(current, set()):
                queue.append(dep)

        return False

    def _find_cycle_path(self, from_node: str, to_node: str) -> list[str]:
        """Find the cycle path that would be created."""
        # to_node -> ... -> from_node -> to_node
        path = [to_node]
        visited = set()
        queue = deque([(to_node, [to_node])])

        while queue:
            current, current_path = queue.popleft()
            if current == from_node:
                return current_path + [to_node]
            if current in visited:
                continue
            visited.add(current)
            for dep in self._dependencies.get(current, set()):
                queue.append((dep, current_path + [dep]))

        return [from_node, to_node, from_node]

    def _find_any_cycle(self, nodes: set[str]) -> list[str]:
        """Find any cycle in a set of nodes."""
        for start in nodes:
            visited = set()
            path = []
            if self._dfs_cycle(start, visited, path, nodes):
                return path
        return list(nodes)[:3]

    def _dfs_cycle(self, node: str, visited: set, path: list, scope: set) -> bool:
        """DFS-based cycle finder."""
        if node in path:
            idx = path.index(node)
            path[:] = path[idx:] + [node]
            return True
        if node in visited:
            return False
        visited.add(node)
        path.append(node)
        for dep in self._dependencies.get(node, set()):
            if dep in scope:
                if self._dfs_cycle(dep, visited, path, scope):
                    return True
        path.pop()
        return False

    # ─── Serialization ────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize DAG to dict."""
        edges = []
        for node, deps in self._dependencies.items():
            for dep in deps:
                edges.append({"from": node, "to": dep})
        return {
            "nodes": sorted(self._nodes),
            "edges": edges,
            "stats": {
                "node_count": len(self._nodes),
                "edge_count": sum(len(d) for d in self._dependencies.values()),
                "roots": self.roots(),
                "leaves": self.leaves(),
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DAG":
        """Deserialize DAG from dict."""
        dag = cls()
        for node in data.get("nodes", []):
            dag.add_node(node)
        for edge in data.get("edges", []):
            dag.add_edge(edge["from"], edge["to"])
        return dag

    @classmethod
    def from_relations(cls, relations: list[dict],
                       dependency_types: Optional[list[str]] = None) -> "DAG":
        """
        Build DAG from relation list (as in relations.py).
        Only uses DEPENDS_ON and CHILD_OF by default.
        """
        if dependency_types is None:
            dependency_types = ["DEPENDS_ON", "CHILD_OF"]

        dag = cls()
        for rel in relations:
            if rel["type"] in dependency_types:
                try:
                    dag.add_edge(rel["from"], rel["to"])
                except CycleDetectedError:
                    # Skip edges that would create cycles
                    pass
        return dag

    def __repr__(self) -> str:
        return f"DAG(nodes={len(self._nodes)}, edges={sum(len(d) for d in self._dependencies.values())})"
