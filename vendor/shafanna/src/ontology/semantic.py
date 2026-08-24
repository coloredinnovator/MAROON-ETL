"""
Semantic Layer — Palantir-style interfaces, actions, and object type registry.
Provides polymorphic shapes (anything "deployable", anything "data-producing"),
action definitions (what can be done to/with objects), and type system enforcement.

This sits on top of the KnowledgeGraph and adds business semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .knowledge_graph import GraphNode, KnowledgeGraph, ObjectType, LinkType


class InterfaceType(str, Enum):
    """Polymorphic interfaces -- any object can implement multiple."""
    DEPLOYABLE = "deployable"
    DATA_PRODUCING = "data_producing"
    DATA_CONSUMING = "data_consuming"
    TESTABLE = "testable"
    MONITORABLE = "monitorable"
    ARCHIVABLE = "archivable"
    BILLABLE = "billable"
    SECURED = "secured"


@dataclass
class Interface:
    """
    A polymorphic shape that objects can implement.
    Like a trait/interface -- defines required properties and capabilities.
    """
    name: InterfaceType
    description: str
    required_properties: list[str] = field(default_factory=list)
    optional_properties: list[str] = field(default_factory=list)

    def is_satisfied_by(self, node: GraphNode) -> bool:
        """Check if a node satisfies this interface."""
        for prop in self.required_properties:
            if prop not in node.properties:
                return False
        return True

    def to_dict(self) -> dict:
        return {
            "name": self.name.value,
            "description": self.description,
            "required_properties": self.required_properties,
            "optional_properties": self.optional_properties,
        }


@dataclass
class Action:
    """
    An action that can be performed on objects.
    Actions have preconditions and effects.
    """
    name: str
    description: str
    applies_to: list[ObjectType] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    effects: list[str] = field(default_factory=list)
    requires_interfaces: list[InterfaceType] = field(default_factory=list)

    def can_apply_to(self, node: GraphNode) -> bool:
        """Check if this action can be applied to a node."""
        if self.applies_to and node.object_type not in self.applies_to:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "applies_to": [t.value for t in self.applies_to],
            "preconditions": self.preconditions,
            "effects": self.effects,
            "requires_interfaces": [i.value for i in self.requires_interfaces],
        }


class SemanticLayer:
    """
    Semantic layer on top of the KnowledgeGraph.
    Provides: interfaces, actions, type enrichment, and business logic.
    """

    def __init__(self, graph: Optional[KnowledgeGraph] = None):
        self.graph = graph or KnowledgeGraph()
        self._interfaces: dict[InterfaceType, Interface] = {}
        self._actions: dict[str, Action] = {}
        self._node_interfaces: dict[str, set[InterfaceType]] = {}
        # Initialize default interfaces and actions
        self._register_defaults()

    # ─── Interface Operations ─────────────────────────────────────────

    def register_interface(self, interface: Interface) -> None:
        """Register an interface definition."""
        self._interfaces[interface.name] = interface

    def assign_interface(self, node_id: str, interface_type: InterfaceType) -> bool:
        """Assign an interface to a node (mark it as implementing that shape)."""
        node = self.graph.get_node(node_id)
        if not node:
            return False

        iface = self._interfaces.get(interface_type)
        if not iface:
            return False

        # Check if node satisfies the interface
        if not iface.is_satisfied_by(node):
            return False

        self._node_interfaces.setdefault(node_id, set()).add(interface_type)
        return True

    def get_interfaces(self, node_id: str) -> list[InterfaceType]:
        """Get all interfaces a node implements."""
        return list(self._node_interfaces.get(node_id, set()))

    def query_by_interface(self, interface_type: InterfaceType) -> list[GraphNode]:
        """Find all nodes implementing a given interface."""
        results = []
        for node_id, interfaces in self._node_interfaces.items():
            if interface_type in interfaces:
                node = self.graph.get_node(node_id)
                if node:
                    results.append(node)
        return results

    # ─── Action Operations ────────────────────────────────────────────

    def register_action(self, action: Action) -> None:
        """Register an action definition."""
        self._actions[action.name] = action

    def get_available_actions(self, node_id: str) -> list[Action]:
        """Get all actions that can be performed on a node."""
        node = self.graph.get_node(node_id)
        if not node:
            return []

        available = []
        for action in self._actions.values():
            if action.can_apply_to(node):
                # Check interface requirements
                node_ifaces = self._node_interfaces.get(node_id, set())
                if all(req in node_ifaces for req in action.requires_interfaces):
                    available.append(action)
        return available

    def execute_action(self, action_name: str, node_id: str,
                       params: dict[str, Any] = None) -> dict:
        """
        Execute an action on a node (returns result metadata).
        Actual effects are described, not performed -- this is a planning layer.
        """
        action = self._actions.get(action_name)
        if not action:
            return {"success": False, "error": f"Unknown action: {action_name}"}

        node = self.graph.get_node(node_id)
        if not node:
            return {"success": False, "error": f"Node not found: {node_id}"}

        if not action.can_apply_to(node):
            return {"success": False, "error": f"Action '{action_name}' cannot apply to {node.object_type.value}"}

        return {
            "success": True,
            "action": action_name,
            "node_id": node_id,
            "node_type": node.object_type.value,
            "effects": action.effects,
            "preconditions_checked": action.preconditions,
            "params": params or {},
        }

    # ─── Object Type Registry ─────────────────────────────────────────

    def enrich_node(self, node_id: str, auto_interfaces: bool = True) -> Optional[GraphNode]:
        """
        Enrich a node with semantic metadata.
        Auto-detects applicable interfaces based on properties.
        """
        node = self.graph.get_node(node_id)
        if not node:
            return None

        if auto_interfaces:
            for iface_type, iface in self._interfaces.items():
                if iface.is_satisfied_by(node):
                    self._node_interfaces.setdefault(node_id, set()).add(iface_type)

        return node

    def classify_object_type(self, properties: dict) -> ObjectType:
        """Infer the best ObjectType for given properties."""
        # Heuristic classification
        lang = properties.get("language", "").lower()
        name = properties.get("name", "").lower()
        desc = properties.get("description", "").lower()

        if "agent" in name or "orchestrator" in name:
            return ObjectType.AGENT
        if "terraform" in name or "infra" in name or "aws" in name:
            return ObjectType.INFRASTRUCTURE
        if "data" in name or "dataset" in name or "corpus" in name:
            return ObjectType.DATA_ASSET
        if any(kw in name for kw in ["council", "market", "medical", "safespace"]):
            return ObjectType.PRODUCT
        if "team" in name or "org" in name:
            return ObjectType.TEAM
        if "api" in name or "service" in name:
            return ObjectType.SERVICE
        return ObjectType.REPO

    # ─── OKF (Open Knowledge Framework) ──────────────────────────────

    def to_okf(self) -> dict:
        """
        Export the semantic layer as Open Knowledge Framework (OKF) compatible format.
        Google OKF / W3C style linked data representation.
        """
        objects = []
        for node_id, node in self.graph.nodes.items():
            obj = {
                "@id": node_id,
                "@type": node.object_type.value,
                "name": node.name,
                "properties": node.properties,
                "interfaces": [i.value for i in self._node_interfaces.get(node_id, set())],
            }
            objects.append(obj)

        links = []
        for edge in self.graph.edges:
            link = {
                "@source": edge.source_id,
                "@target": edge.target_id,
                "@type": edge.link_type.value,
                "properties": edge.properties,
                "weight": edge.weight,
            }
            links.append(link)

        return {
            "@context": {
                "@vocab": "https://schema.org/",
                "okf": "https://openknowledge.org/schema/",
                "maroon": "https://maroontechnologies.com/ontology/",
            },
            "@graph": {
                "objects": objects,
                "links": links,
            },
            "interfaces": {k.value: v.to_dict() for k, v in self._interfaces.items()},
            "actions": {k: v.to_dict() for k, v in self._actions.items()},
            "stats": {
                "total_objects": len(objects),
                "total_links": len(links),
                "interface_assignments": sum(len(v) for v in self._node_interfaces.values()),
            },
        }

    @classmethod
    def from_okf(cls, data: dict) -> "SemanticLayer":
        """Import from OKF format."""
        graph_data = data.get("@graph", {})

        graph = KnowledgeGraph()
        for obj in graph_data.get("objects", []):
            obj_type = obj.get("@type", "repo")
            try:
                otype = ObjectType(obj_type)
            except ValueError:
                otype = ObjectType.REPO
            graph.add_node(obj["@id"], otype, obj.get("name", ""), obj.get("properties", {}))

        for link in graph_data.get("links", []):
            link_type = link.get("@type", "RELATED_TO")
            try:
                ltype = LinkType(link_type)
            except ValueError:
                ltype = LinkType.RELATED_TO
            graph.add_edge(link["@source"], link["@target"], ltype,
                           link.get("properties", {}), link.get("weight", 1.0))

        layer = cls(graph)
        return layer

    # ─── Statistics ───────────────────────────────────────────────────

    def stats(self) -> dict:
        """Get semantic layer statistics."""
        return {
            "graph_stats": self.graph.stats(),
            "registered_interfaces": len(self._interfaces),
            "registered_actions": len(self._actions),
            "nodes_with_interfaces": len(self._node_interfaces),
            "total_interface_assignments": sum(
                len(v) for v in self._node_interfaces.values()
            ),
        }

    # ─── Default Registrations ────────────────────────────────────────

    def _register_defaults(self):
        """Register default interfaces and actions for Maroon ontology."""
        # Interfaces
        self.register_interface(Interface(
            name=InterfaceType.DEPLOYABLE,
            description="Can be deployed to an environment",
            required_properties=["has_docker"],
            optional_properties=["deploy_target", "deploy_method"],
        ))
        self.register_interface(Interface(
            name=InterfaceType.DATA_PRODUCING,
            description="Produces data outputs",
            required_properties=[],
            optional_properties=["output_format", "output_target"],
        ))
        self.register_interface(Interface(
            name=InterfaceType.DATA_CONSUMING,
            description="Consumes data inputs",
            required_properties=[],
            optional_properties=["input_sources", "input_format"],
        ))
        self.register_interface(Interface(
            name=InterfaceType.TESTABLE,
            description="Has test coverage",
            required_properties=["has_tests"],
            optional_properties=["test_framework", "coverage"],
        ))
        self.register_interface(Interface(
            name=InterfaceType.MONITORABLE,
            description="Can be monitored",
            required_properties=[],
            optional_properties=["monitoring_endpoint", "health_check"],
        ))
        self.register_interface(Interface(
            name=InterfaceType.ARCHIVABLE,
            description="Can be safely archived",
            required_properties=[],
            optional_properties=["archive_reason", "archived_at"],
        ))

        # Actions
        self.register_action(Action(
            name="deploy",
            description="Deploy the object to target environment",
            applies_to=[ObjectType.REPO, ObjectType.SERVICE],
            preconditions=["has_docker", "has_tests"],
            effects=["service_running", "endpoint_available"],
            requires_interfaces=[InterfaceType.DEPLOYABLE],
        ))
        self.register_action(Action(
            name="rebuild",
            description="Rebuild the object from scratch",
            applies_to=[ObjectType.REPO, ObjectType.SERVICE, ObjectType.INFRASTRUCTURE],
            preconditions=["has_real_code"],
            effects=["rebuilt", "version_incremented"],
        ))
        self.register_action(Action(
            name="archive",
            description="Archive the object (no longer active)",
            applies_to=[ObjectType.REPO, ObjectType.DATA_ASSET],
            preconditions=["no_active_dependents"],
            effects=["archived", "removed_from_active"],
        ))
        self.register_action(Action(
            name="classify",
            description="Classify/reclassify the object in the ontology",
            applies_to=list(ObjectType),
            preconditions=[],
            effects=["category_assigned", "properties_updated"],
        ))
        self.register_action(Action(
            name="merge",
            description="Merge this object into another (dedup)",
            applies_to=[ObjectType.REPO],
            preconditions=["duplicate_identified"],
            effects=["merged", "redirect_created"],
        ))

    def __repr__(self) -> str:
        return (f"SemanticLayer(graph={self.graph}, "
                f"interfaces={len(self._interfaces)}, "
                f"actions={len(self._actions)})")
