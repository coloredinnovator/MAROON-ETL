"""
NeMo-style Guardrails for AI classification.
Governance/safety layer around DeepSeek Bedrock calls.

Rails:
1. Only output valid JSON classifications
2. Never recommend DELETE for repos with active commits
3. Osnit repos are ALWAYS Arm C nonprofit -- never classify as Arm B
4. Agent stays on-topic (repo classification, not random chat)
5. No hallucinated categories -- must match known schema

Inspired by NVIDIA NeMo Guardrails but zero-dependency implementation.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class RailType(str, Enum):
    """Types of guardrails."""
    INPUT = "input"        # Validates input before sending to AI
    OUTPUT = "output"      # Validates AI response
    TOPICAL = "topical"    # Ensures on-topic conversation
    SAFETY = "safety"      # Prevents harmful outputs
    SCHEMA = "schema"      # Enforces output format


class Severity(str, Enum):
    """How critical is a rail violation."""
    BLOCK = "block"    # Stop execution, reject output
    WARN = "warn"      # Allow but log warning
    FIX = "fix"        # Auto-fix the output


@dataclass
class RailViolation:
    """A guardrail violation record."""
    rail_name: str
    rail_type: RailType
    severity: Severity
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    auto_fixed: bool = False

    def to_dict(self) -> dict:
        return {
            "rail_name": self.rail_name,
            "rail_type": self.rail_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "context": self.context,
            "timestamp": self.timestamp,
            "auto_fixed": self.auto_fixed,
        }


@dataclass
class Rail:
    """A single guardrail definition."""
    name: str
    rail_type: RailType
    severity: Severity
    description: str
    check_fn: Optional[Callable] = None
    fix_fn: Optional[Callable] = None
    enabled: bool = True

    def check(self, data: Any, context: dict = None) -> Optional[RailViolation]:
        """Run this rail's check. Returns violation or None if passes."""
        if not self.enabled or not self.check_fn:
            return None
        try:
            passed = self.check_fn(data, context or {})
            if not passed:
                return RailViolation(
                    rail_name=self.name,
                    rail_type=self.rail_type,
                    severity=self.severity,
                    message=self.description,
                    context=context or {},
                )
        except Exception as e:
            return RailViolation(
                rail_name=self.name,
                rail_type=self.rail_type,
                severity=Severity.WARN,
                message=f"Rail check error: {str(e)}",
                context=context or {},
            )
        return None

    def fix(self, data: Any, context: dict = None) -> Any:
        """Attempt to auto-fix a violation. Returns fixed data or original."""
        if self.fix_fn:
            return self.fix_fn(data, context or {})
        return data


class NeMoGuardrails:
    """
    NeMo-style guardrails engine for AI classification safety.
    Zero external dependencies. Enforces rules around LLM outputs.
    """

    # Known valid categories (must match categories.yaml)
    VALID_CATEGORIES = {
        "core_infrastructure", "products", "intelligence", "agents",
        "data_layer", "governance", "verticals", "research",
        "delivery", "meta_ops", "aws_infra",
    }

    # Valid actions
    VALID_ACTIONS = {"KEEP", "MERGE", "REBUILD", "ARCHIVE", "DELETE"}

    # Osnit-related identifiers (ALWAYS Arm C nonprofit)
    OSNIT_IDENTIFIERS = {"osnit", "maroon-osnit", "osnit-playbooks", "maroon-osnit-playbooks"}

    def __init__(self):
        self._rails: dict[str, Rail] = {}
        self._violations: list[RailViolation] = []
        self._stats = {"checks": 0, "passes": 0, "violations": 0, "fixes": 0}
        # Register default rails
        self._register_default_rails()

    # ─── Rail Registration ────────────────────────────────────────────

    def register_rail(self, rail: Rail) -> None:
        """Register a guardrail."""
        self._rails[rail.name] = rail

    def disable_rail(self, name: str) -> bool:
        """Disable a specific rail."""
        if name in self._rails:
            self._rails[name].enabled = False
            return True
        return False

    def enable_rail(self, name: str) -> bool:
        """Enable a specific rail."""
        if name in self._rails:
            self._rails[name].enabled = True
            return True
        return False

    # ─── Validation ───────────────────────────────────────────────────

    def validate_input(self, prompt: str, context: dict = None) -> dict:
        """Validate an input prompt before sending to AI."""
        result = self._run_rails(RailType.INPUT, prompt, context)
        # Also run topical rails on input
        topical_result = self._run_rails(RailType.TOPICAL, prompt, context)
        result["violations"].extend(topical_result["violations"])
        result["passed"] = result["passed"] and topical_result["passed"]
        result["blocked"] = result["blocked"] or topical_result["blocked"]
        return result

    def validate_output(self, response: Any, context: dict = None) -> dict:
        """Validate AI response before accepting it."""
        return self._run_rails(RailType.OUTPUT, response, context)

    def validate_classification(self, classification: dict, repo_data: dict = None) -> dict:
        """
        Validate a repo classification output.
        This is the main entry point for checking AI classification results.
        """
        context = {"repo_data": repo_data or {}, "classification": classification}
        result = self._run_rails(RailType.OUTPUT, classification, context)

        # Also run schema rails
        schema_result = self._run_rails(RailType.SCHEMA, classification, context)
        result["violations"].extend(schema_result["violations"])
        result["passed"] = result["passed"] and schema_result["passed"]

        # Also run safety rails
        safety_result = self._run_rails(RailType.SAFETY, classification, context)
        result["violations"].extend(safety_result["violations"])
        result["passed"] = result["passed"] and safety_result["passed"]

        return result

    def _run_rails(self, rail_type: RailType, data: Any, context: dict = None) -> dict:
        """Run all rails of a given type."""
        violations = []
        fixed_data = data

        for rail in self._rails.values():
            if rail.rail_type != rail_type or not rail.enabled:
                continue

            self._stats["checks"] += 1
            violation = rail.check(data, context)

            if violation:
                self._stats["violations"] += 1
                self._violations.append(violation)

                if rail.severity == Severity.FIX and rail.fix_fn:
                    fixed_data = rail.fix(fixed_data, context)
                    violation.auto_fixed = True
                    self._stats["fixes"] += 1

                if rail.severity == Severity.BLOCK:
                    violations.append(violation)
                elif rail.severity == Severity.WARN:
                    violations.append(violation)
            else:
                self._stats["passes"] += 1

        blocked = any(v.severity == Severity.BLOCK for v in violations)

        return {
            "passed": not blocked,
            "violations": violations,
            "data": fixed_data,
            "blocked": blocked,
        }

    # ─── Default Rails ────────────────────────────────────────────────

    def _register_default_rails(self):
        """Register the core guardrails for Maroon classification."""

        # RAIL 1: Output must be valid JSON
        def check_valid_json(data, ctx):
            if isinstance(data, dict):
                return True
            if isinstance(data, str):
                try:
                    json.loads(data)
                    return True
                except (json.JSONDecodeError, TypeError):
                    return False
            return False

        def fix_json(data, ctx):
            if isinstance(data, str):
                # Try to extract JSON from response
                match = re.search(r'\{[^{}]*\}', data, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group())
                    except json.JSONDecodeError:
                        pass
            return data

        self.register_rail(Rail(
            name="valid_json_output",
            rail_type=RailType.SCHEMA,
            severity=Severity.FIX,
            description="AI output must be valid JSON classification",
            check_fn=check_valid_json,
            fix_fn=fix_json,
        ))

        # RAIL 2: Never DELETE repos with active commits
        def check_no_delete_active(data, ctx):
            if not isinstance(data, dict):
                return True
            action = data.get("recommended_action", "").upper()
            if action != "DELETE":
                return True
            repo_data = ctx.get("repo_data", {})
            commits = repo_data.get("commit_count_30d", 0)
            return commits == 0  # Only allow DELETE if no recent commits

        self.register_rail(Rail(
            name="no_delete_active_repos",
            rail_type=RailType.SAFETY,
            severity=Severity.BLOCK,
            description="Never recommend DELETE for repos with active commits in last 30 days",
            check_fn=check_no_delete_active,
        ))

        # RAIL 3: Osnit is ALWAYS Arm C nonprofit
        def check_osnit_arm_c(data, ctx):
            if not isinstance(data, dict):
                return True
            repo_data = ctx.get("repo_data", {})
            repo_name = repo_data.get("name", "").lower()

            # Check if this is an osnit repo
            is_osnit = any(oid in repo_name for oid in self.OSNIT_IDENTIFIERS)
            if not is_osnit:
                return True

            # Must be classified as intelligence/arm_c_nonprofit
            category = data.get("category", "")
            subcategory = data.get("subcategory", "")
            return category == "intelligence" and subcategory == "arm_c_nonprofit"

        def fix_osnit(data, ctx):
            if isinstance(data, dict):
                repo_data = ctx.get("repo_data", {})
                repo_name = repo_data.get("name", "").lower()
                is_osnit = any(oid in repo_name for oid in self.OSNIT_IDENTIFIERS)
                if is_osnit:
                    data["category"] = "intelligence"
                    data["subcategory"] = "arm_c_nonprofit"
                    data["_guardrail_override"] = "osnit_arm_c_enforced"
            return data

        self.register_rail(Rail(
            name="osnit_always_arm_c",
            rail_type=RailType.SAFETY,
            severity=Severity.FIX,
            description="Osnit repos ALWAYS Arm C nonprofit -- never classify as Arm B",
            check_fn=check_osnit_arm_c,
            fix_fn=fix_osnit,
        ))

        # RAIL 4: Stay on topic (repo classification only)
        def check_on_topic(data, ctx):
            if isinstance(data, str):
                off_topic_signals = [
                    "I cannot", "I'm sorry", "as an AI",
                    "I don't have access", "let me tell you a joke",
                    "here's a poem", "once upon a time",
                ]
                lower = data.lower()
                return not any(signal.lower() in lower for signal in off_topic_signals)
            return True

        self.register_rail(Rail(
            name="stay_on_topic",
            rail_type=RailType.TOPICAL,
            severity=Severity.BLOCK,
            description="Agent must stay on-topic: repo classification only",
            check_fn=check_on_topic,
        ))

        # RAIL 5: Category must be valid
        def check_valid_category(data, ctx):
            if not isinstance(data, dict):
                return True
            category = data.get("category")
            if category is None:
                return True  # No category yet -- may be unmapped
            return category in self.VALID_CATEGORIES

        self.register_rail(Rail(
            name="valid_category",
            rail_type=RailType.SCHEMA,
            severity=Severity.BLOCK,
            description="Classification must use a known valid category",
            check_fn=check_valid_category,
        ))

        # RAIL 6: Action must be valid
        def check_valid_action(data, ctx):
            if not isinstance(data, dict):
                return True
            action = data.get("recommended_action")
            if action is None:
                return True
            return action.upper() in self.VALID_ACTIONS

        self.register_rail(Rail(
            name="valid_action",
            rail_type=RailType.SCHEMA,
            severity=Severity.BLOCK,
            description="Recommended action must be one of: KEEP, MERGE, REBUILD, ARCHIVE, DELETE",
            check_fn=check_valid_action,
        ))

        # RAIL 7: No hallucinated repo names
        def check_no_hallucination(data, ctx):
            if not isinstance(data, dict):
                return True
            # If there's a name in output, it should match the input
            output_name = data.get("name", "")
            repo_data = ctx.get("repo_data", {})
            input_name = repo_data.get("name", "")
            if output_name and input_name:
                return output_name == input_name
            return True

        self.register_rail(Rail(
            name="no_hallucinated_names",
            rail_type=RailType.OUTPUT,
            severity=Severity.BLOCK,
            description="AI must not hallucinate repo names -- output name must match input",
            check_fn=check_no_hallucination,
        ))

    # ─── Statistics & Audit ───────────────────────────────────────────

    @property
    def violation_count(self) -> int:
        return len(self._violations)

    @property
    def stats(self) -> dict:
        return {
            **self._stats,
            "rails_registered": len(self._rails),
            "rails_enabled": sum(1 for r in self._rails.values() if r.enabled),
        }

    @property
    def violations(self) -> list[RailViolation]:
        return list(self._violations)

    def clear_violations(self) -> None:
        """Clear violation history."""
        self._violations.clear()

    def get_rail_names(self) -> list[str]:
        """Get all registered rail names."""
        return list(self._rails.keys())

    def to_dict(self) -> dict:
        """Serialize guardrails state."""
        return {
            "rails": {
                name: {
                    "name": rail.name,
                    "type": rail.rail_type.value,
                    "severity": rail.severity.value,
                    "description": rail.description,
                    "enabled": rail.enabled,
                }
                for name, rail in self._rails.items()
            },
            "stats": self.stats,
            "violations": [v.to_dict() for v in self._violations[-50:]],  # Last 50
        }

    def __repr__(self) -> str:
        return (f"NeMoGuardrails(rails={len(self._rails)}, "
                f"violations={self.violation_count})")
