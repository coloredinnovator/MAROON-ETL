"""
Knowledge Graph — Palantir-style typed object graph.
Nodes (objects) with typed properties, edges (links) with relationship types.
Supports: object types, typed properties, link types, queries.

This is the core data structure. Everything else (DAG, Merkle, Semantic) builds on top.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class ObjectType(str, Enum):
    """Types of objects in the knowledge graph."""
    REPO = "repo"
    SERVICE = "service"
    TEAM = "team"
    INFRASTRUCTURE = "infrastructure"
    DATA_ASSET = "data_asset"
    AGENT = "agent"
    PRODUCT = "product"
    ORGANIZATION = "organization"


class LinkType(str, Enum):
    """Types of relationships between objects."""
    DEPENDS_ON = "DEPENDS_ON"
    OWNS = "OWNS"
    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"
    CHILD_OF = "CHILD_OF"
    SUPERSEDED_BY = "SUPERSEDED_BY"
    DUPLICATE_OF = "DUPLICATE_OF"
    RELATED_TO = "RELATED_TO"
    DEPLOYS_TO = "DEPLOYS_TO"
    BUILT_FROM = "BUILT_FROM"
    TESTED_BY = "TESTED_BY"
    MONITORED_BY = "MONITORED_BY"


class PropertyType(str, Enum):
    """Typed property value types for validation."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    LIST = "list"
    TIMESTAMP = "timestamp"


@dataclass
class PropertySchema:
    """Schema definition for a typed property."""
    name: str
    prop_type: PropertyType
    required: bool = False
    default: Any = None
    description: str = ""

    def validate(self, value: Any) -> bool:
        """Validate a value against this property schema."""
        if value is None:
            return not self.required

        type_map = {
            PropertyType.STRING: str,
            PropertyType.INTEGER: int,
            PropertyType.FLOAT: (int, float),
            PropertyType.BOOLEAN: bool,
            PropertyType.LIST: list,
            PropertyType.TIMESTAMP: (str, int, float),
        }
        expected = type_map.get(self.prop_type)
        if expected is None:
            return True
        return isinstance(value, expected)


@dataclass
class GraphNode:
    """A node (object) in the knowledge graph."""
    node_id: str
    object_type: ObjectType
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "object_type": self.object_type.value if isinstance(self.object_type, ObjectType) else self.object_type,
            "name": self.name,
            "properties": self.properties,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GraphNode":
        obj_type = data.get("object_type", "repo")
        if isinstance(obj_type, str):
            try:
                obj_type = ObjectType(obj_type)
            except ValueError:
                obj_type = ObjectType.REPO
        return cls(
            node_id=data["node_id"],
            object_type=obj_type,
            name=data["name"],
            properties=data.get("properties", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class GraphEdge:
    """An edge (link) between two nodes in the knowledge graph."""
    source_id: str
    target_id: str
    link_type: LinkType
    properties: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "link_type": self.link_type.value if isinstance(self.link_type, LinkType) else self.link_type,
            "properties": self.properties,
            "weight": self.weight,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GraphEdge":
        link_type = data.get("link_type", "RELATED_TO")
        if isinstance(link_type, str):
            try:
                link_type = LinkType(link_type)
            except ValueError:
                link_type = LinkType.RELATED_TO
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            link_type=link_type,
            properties=data.get("properties", {}),
            weight=data.get("weight", 1.0),
            created_at=data.get("created_at", time.time()),
        )


class KnowledgeGraph:
    """
    Core knowledge graph: nodes + edges with typed properties.
    Palantir Foundry Ontology equivalent -- our differentiation layer.
    """

    def __init__(self):
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []
        # Adjacency: node_id -> list of (edge_index, direction)
        self._adjacency: dict[str, list[tuple[int, str]]] = {}
        # Schema registry for property validation
        self._schemas: dict[ObjectType, list[PropertySchema]] = {}

    # ─── Node Operations ──────────────────────────────────────────────

    def add_node(self, node_id: str, object_type: ObjectType, name: str,
                 properties: dict[str, Any] = None) -> GraphNode:
        """Add a node to the graph. Overwrites if exists."""
        node = GraphNode(
            node_id=node_id,
            object_type=object_type,
            name=name,
            properties=properties or {},
        )

        # Validate properties against schema if registered
        if object_type in self._schemas:
            self._validate_properties(node)

        self.nodes[node_id] = node
        if node_id not in self._adjacency:
            self._adjacency[node_id] = []
        return node

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and all its edges."""
        if node_id not in self.nodes:
            return False

        # Remove edges connected to this node
        self.edges = [e for e in self.edges
                      if e.source_id != node_id and e.target_id != node_id]

        # Rebuild adjacency for affected nodes
        self._rebuild_adjacency()

        del self.nodes[node_id]
        if node_id in self._adjacency:
            del self._adjacency[node_id]
        return True

    def update_node(self, node_id: str, properties: dict[str, Any]) -> Optional[GraphNode]:
        """Update properties on an existing node."""
        node = self.nodes.get(node_id)
        if node is None:
            return None
        node.properties.update(properties)
        node.updated_at = time.time()
        return node

    # ─── Edge Operations ──────────────────────────────────────────────

    def add_edge(self, source_id: str, target_id: str, link_type: LinkType,
                 properties: dict[str, Any] = None, weight: float = 1.0) -> Optional[GraphEdge]:
        """Add a directed edge between two nodes."""
        if source_id not in self.nodes or target_id not in self.nodes:
            return None

        edge = GraphEdge(
            source_id=source_id,
            target_id=target_id,
            link_type=link_type,
            properties=properties or {},
            weight=weight,
        )

        edge_idx = len(self.edges)
        self.edges.append(edge)

        self._adjacency.setdefault(source_id, []).append((edge_idx, "out"))
        self._adjacency.setdefault(target_id, []).append((edge_idx, "in"))

        return edge

    def get_edges(self, node_id: str, direction: str = "both",
                  link_type: Optional[LinkType] = None) -> list[GraphEdge]:
        """Get edges for a node. direction: 'in', 'out', or 'both'."""
        results = []
        for edge_idx, edge_dir in self._adjacency.get(node_id, []):
            if edge_idx >= len(self.edges):
                continue
            if direction != "both" and edge_dir != direction:
                continue
            edge = self.edges[edge_idx]
            if link_type and edge.link_type != link_type:
                continue
            results.append(edge)
        return results

    def get_neighbors(self, node_id: str, direction: str = "out",
                      link_type: Optional[LinkType] = None) -> list[str]:
        """Get neighbor node IDs."""
        neighbors = []
        for edge in self.get_edges(node_id, direction, link_type):
            if direction == "out":
                neighbors.append(edge.target_id)
            elif direction == "in":
                neighbors.append(edge.source_id)
            else:
                other = edge.target_id if edge.source_id == node_id else edge.source_id
                neighbors.append(other)
        return neighbors

    # ─── Query Operations ─────────────────────────────────────────────

    def query_by_type(self, object_type: ObjectType) -> list[GraphNode]:
        """Get all nodes of a given type."""
        return [n for n in self.nodes.values() if n.object_type == object_type]

    def query_by_property(self, key: str, value: Any) -> list[GraphNode]:
        """Find nodes where a property matches a value."""
        return [n for n in self.nodes.values()
                if n.properties.get(key) == value]

    def find_path(self, start_id: str, end_id: str, max_depth: int = 10) -> Optional[list[str]]:
        """BFS shortest path between two nodes."""
        if start_id not in self.nodes or end_id not in self.nodes:
            return None
        if start_id == end_id:
            return [start_id]

        visited = {start_id}
        queue = [(start_id, [start_id])]

        while queue:
            current, path = queue.pop(0)
            if len(path) > max_depth:
                break

            for neighbor in self.get_neighbors(current, direction="both"):
                if neighbor == end_id:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None  # No path found

    def subgraph(self, node_ids: list[str]) -> "KnowledgeGraph":
        """Extract a subgraph containing only the specified nodes."""
        sub = KnowledgeGraph()
        for nid in node_ids:
            node = self.nodes.get(nid)
            if node:
                sub.add_node(nid, node.object_type, node.name, node.properties.copy())

        for edge in self.edges:
            if edge.source_id in sub.nodes and edge.target_id in sub.nodes:
                sub.add_edge(edge.source_id, edge.target_id, edge.link_type,
                             edge.properties.copy(), edge.weight)
        return sub

    # ─── Schema Operations ────────────────────────────────────────────

    def register_schema(self, object_type: ObjectType, schemas: list[PropertySchema]):
        """Register property schemas for an object type."""
        self._schemas[object_type] = schemas

    def _validate_properties(self, node: GraphNode) -> bool:
        """Validate node properties against registered schema."""
        schemas = self._schemas.get(node.object_type, [])
        for schema in schemas:
            value = node.properties.get(schema.name, schema.default)
            if not schema.validate(value):
                raise ValueError(
                    f"Property '{schema.name}' on node '{node.node_id}' "
                    f"failed validation: expected {schema.prop_type.value}, "
                    f"got {type(value).__name__}"
                )
        return True

    # ─── Stats ────────────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def stats(self) -> dict:
        """Get graph statistics."""
        type_counts = {}
        for node in self.nodes.values():
            t = node.object_type.value if isinstance(node.object_type, ObjectType) else str(node.object_type)
            type_counts[t] = type_counts.get(t, 0) + 1

        link_counts = {}
        for edge in self.edges:
            t = edge.link_type.value if isinstance(edge.link_type, LinkType) else str(edge.link_type)
            link_counts[t] = link_counts.get(t, 0) + 1

        return {
            "total_nodes": self.node_count,
            "total_edges": self.edge_count,
            "node_types": type_counts,
            "link_types": link_counts,
        }

    # ─── Serialization ────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize the entire graph."""
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "stats": self.stats(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeGraph":
        """Deserialize a graph from dict."""
        graph = cls()
        for node_data in data.get("nodes", []):
            node = GraphNode.from_dict(node_data)
            graph.nodes[node.node_id] = node
            graph._adjacency.setdefault(node.node_id, [])

        for edge_data in data.get("edges", []):
            edge = GraphEdge.from_dict(edge_data)
            edge_idx = len(graph.edges)
            graph.edges.append(edge)
            graph._adjacency.setdefault(edge.source_id, []).append((edge_idx, "out"))
            graph._adjacency.setdefault(edge.target_id, []).append((edge_idx, "in"))

        return graph

    def save(self, path: str):
        """Save graph to JSON file."""
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "KnowledgeGraph":
        """Load graph from JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    # ─── Internal ─────────────────────────────────────────────────────

    def _rebuild_adjacency(self):
        """Rebuild adjacency index from edge list."""
        self._adjacency = {nid: [] for nid in self.nodes}
        for idx, edge in enumerate(self.edges):
            self._adjacency.setdefault(edge.source_id, []).append((idx, "out"))
            self._adjacency.setdefault(edge.target_id, []).append((idx, "in"))

    def __repr__(self) -> str:
        return f"KnowledgeGraph(nodes={self.node_count}, edges={self.edge_count})"
