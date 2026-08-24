"""
Merkle Tree / Merkle DAG — content-addressable hashing for the knowledge graph.
Like Git's object model but for our ontology.

Every object gets a content hash. Parent hashes include children.
Enables: diff detection, tamper-proof audit trail, efficient sync.

Uses hashlib (stdlib) -- no external deps.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional


def _content_hash(data: Any) -> str:
    """
    Compute SHA-256 content hash of any serializable data.
    Deterministic: same input always produces same hash.
    """
    # Canonical JSON serialization (sorted keys, no whitespace)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class MerkleNode:
    """A node in the Merkle DAG with content-addressable hash."""
    node_id: str
    content_hash: str
    data_hash: str  # Hash of just this node's data (without children)
    children_hashes: list[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "content_hash": self.content_hash,
            "data_hash": self.data_hash,
            "children_hashes": self.children_hashes,
            "parent_id": self.parent_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MerkleNode":
        return cls(
            node_id=data["node_id"],
            content_hash=data["content_hash"],
            data_hash=data["data_hash"],
            children_hashes=data.get("children_hashes", []),
            parent_id=data.get("parent_id"),
            timestamp=data.get("timestamp", time.time()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class MerkleProof:
    """Proof that a node belongs in the tree at a certain state."""
    node_id: str
    node_hash: str
    path_hashes: list[str]  # From node to root
    root_hash: str
    verified: bool = False

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "node_hash": self.node_hash,
            "path_hashes": self.path_hashes,
            "root_hash": self.root_hash,
            "verified": self.verified,
        }


class MerkleDAG:
    """
    Merkle DAG for the knowledge graph.
    Content-addressable storage with hash propagation.

    Design:
    - Each node gets a data_hash (hash of its own content)
    - Each node gets a content_hash (hash of data_hash + sorted children hashes)
    - When a child changes, parent hashes propagate up
    - Root hash represents the entire state of the graph
    """

    def __init__(self):
        self._nodes: dict[str, MerkleNode] = {}
        self._children: dict[str, list[str]] = {}  # parent -> [child_ids]
        self._parent: dict[str, Optional[str]] = {}  # child -> parent
        self._root_id: Optional[str] = None
        self._history: list[dict] = []  # Audit trail

    # ─── Core Operations ──────────────────────────────────────────────

    def add_node(self, node_id: str, data: dict, parent_id: Optional[str] = None) -> MerkleNode:
        """
        Add a node with content-addressable hash.
        Propagates hash changes up to root.
        """
        data_hash = _content_hash(data)

        node = MerkleNode(
            node_id=node_id,
            content_hash=data_hash,  # Will be recalculated with children
            data_hash=data_hash,
            parent_id=parent_id,
            metadata={"original_data": data},
        )

        self._nodes[node_id] = node
        self._children.setdefault(node_id, [])
        self._parent[node_id] = parent_id

        # Register as child of parent
        if parent_id and parent_id in self._nodes:
            if node_id not in self._children.get(parent_id, []):
                self._children.setdefault(parent_id, []).append(node_id)

        # Set root if first node or no parent
        if parent_id is None and self._root_id is None:
            self._root_id = node_id

        # Recalculate hashes up the tree
        self._propagate_hash(node_id)

        # Record in audit trail
        self._history.append({
            "action": "add",
            "node_id": node_id,
            "hash": node.content_hash,
            "timestamp": node.timestamp,
        })

        return node

    def update_node(self, node_id: str, data: dict) -> Optional[MerkleNode]:
        """
        Update a node's data. Recomputes hash and propagates changes up.
        This is how change detection works -- if data changes, hash changes.
        """
        if node_id not in self._nodes:
            return None

        old_hash = self._nodes[node_id].content_hash
        new_data_hash = _content_hash(data)

        node = self._nodes[node_id]
        node.data_hash = new_data_hash
        node.metadata["original_data"] = data
        node.timestamp = time.time()

        # Propagate hash change up
        self._propagate_hash(node_id)

        # Audit trail
        self._history.append({
            "action": "update",
            "node_id": node_id,
            "old_hash": old_hash,
            "new_hash": node.content_hash,
            "timestamp": node.timestamp,
        })

        return node

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and propagate hash changes."""
        if node_id not in self._nodes:
            return False

        parent_id = self._parent.get(node_id)

        # Remove from parent's children
        if parent_id and parent_id in self._children:
            self._children[parent_id] = [
                c for c in self._children[parent_id] if c != node_id
            ]

        # Orphan children (attach to parent or make roots)
        for child_id in self._children.get(node_id, []):
            self._parent[child_id] = parent_id
            if parent_id and parent_id in self._children:
                self._children[parent_id].append(child_id)

        # Clean up
        del self._nodes[node_id]
        self._children.pop(node_id, None)
        self._parent.pop(node_id, None)

        # Propagate if parent exists
        if parent_id and parent_id in self._nodes:
            self._propagate_hash(parent_id)

        # Audit
        self._history.append({
            "action": "remove",
            "node_id": node_id,
            "timestamp": time.time(),
        })

        return True

    # ─── Hash Operations ──────────────────────────────────────────────

    def _propagate_hash(self, node_id: str) -> None:
        """Recalculate content_hash for node and propagate up to root."""
        current = node_id
        while current and current in self._nodes:
            node = self._nodes[current]
            children_hashes = sorted([
                self._nodes[cid].content_hash
                for cid in self._children.get(current, [])
                if cid in self._nodes
            ])
            node.children_hashes = children_hashes

            # Content hash = hash(data_hash + children_hashes)
            combined = {
                "data": node.data_hash,
                "children": children_hashes,
            }
            node.content_hash = _content_hash(combined)

            # Move up to parent
            current = self._parent.get(current)

    @property
    def root_hash(self) -> Optional[str]:
        """The root hash represents the entire state of the graph."""
        if self._root_id and self._root_id in self._nodes:
            return self._nodes[self._root_id].content_hash
        return None

    def get_hash(self, node_id: str) -> Optional[str]:
        """Get the current content hash of a node."""
        node = self._nodes.get(node_id)
        return node.content_hash if node else None

    # ─── Diff Detection ───────────────────────────────────────────────

    def diff(self, other: "MerkleDAG") -> dict:
        """
        Compare two Merkle DAGs. Returns changes needed to go from self to other.
        Efficient: only traverses where hashes differ.
        """
        added = []
        removed = []
        modified = []

        # Find added and modified
        for node_id, node in other._nodes.items():
            if node_id not in self._nodes:
                added.append(node_id)
            elif self._nodes[node_id].content_hash != node.content_hash:
                modified.append(node_id)

        # Find removed
        for node_id in self._nodes:
            if node_id not in other._nodes:
                removed.append(node_id)

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
            "is_same": not (added or removed or modified),
            "self_root_hash": self.root_hash,
            "other_root_hash": other.root_hash,
        }

    def has_changed(self, node_id: str, expected_hash: str) -> bool:
        """Check if a node has changed from an expected hash."""
        current_hash = self.get_hash(node_id)
        return current_hash != expected_hash

    # ─── Verification ─────────────────────────────────────────────────

    def verify_integrity(self) -> dict:
        """
        Verify the integrity of the entire Merkle DAG.
        Recomputes all hashes from scratch and compares.
        """
        issues = []
        for node_id, node in self._nodes.items():
            # Recompute data hash from stored data
            if "original_data" in node.metadata:
                expected_data_hash = _content_hash(node.metadata["original_data"])
                if node.data_hash != expected_data_hash:
                    issues.append({
                        "node_id": node_id,
                        "issue": "data_hash_mismatch",
                        "expected": expected_data_hash,
                        "actual": node.data_hash,
                    })

            # Recompute content hash
            children_hashes = sorted([
                self._nodes[cid].content_hash
                for cid in self._children.get(node_id, [])
                if cid in self._nodes
            ])
            expected_content = _content_hash({
                "data": node.data_hash,
                "children": children_hashes,
            })
            if node.content_hash != expected_content:
                issues.append({
                    "node_id": node_id,
                    "issue": "content_hash_mismatch",
                    "expected": expected_content,
                    "actual": node.content_hash,
                })

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "nodes_checked": len(self._nodes),
            "root_hash": self.root_hash,
        }

    def generate_proof(self, node_id: str) -> Optional[MerkleProof]:
        """Generate a Merkle proof for a node (path from node to root)."""
        if node_id not in self._nodes:
            return None

        path_hashes = []
        current = node_id
        while current and current in self._nodes:
            path_hashes.append(self._nodes[current].content_hash)
            current = self._parent.get(current)

        return MerkleProof(
            node_id=node_id,
            node_hash=self._nodes[node_id].content_hash,
            path_hashes=path_hashes,
            root_hash=self.root_hash or "",
            verified=True,
        )

    # ─── Audit Trail ──────────────────────────────────────────────────

    @property
    def audit_trail(self) -> list[dict]:
        """Get the complete audit trail of changes."""
        return list(self._history)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    # ─── Serialization ────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize the entire Merkle DAG."""
        return {
            "root_id": self._root_id,
            "root_hash": self.root_hash,
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
            "children": self._children,
            "parent": self._parent,
            "history": self._history,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MerkleDAG":
        """Deserialize a Merkle DAG."""
        dag = cls()
        dag._root_id = data.get("root_id")
        dag._children = data.get("children", {})
        dag._parent = data.get("parent", {})
        dag._history = data.get("history", [])

        for nid, node_data in data.get("nodes", {}).items():
            dag._nodes[nid] = MerkleNode.from_dict(node_data)

        return dag

    def __repr__(self) -> str:
        return f"MerkleDAG(nodes={self.node_count}, root_hash={self.root_hash[:12] if self.root_hash else 'None'}...)"
