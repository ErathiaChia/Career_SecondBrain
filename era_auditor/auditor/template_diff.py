"""Deterministic template-diff validation for presales project trees.

Validates the actual folder tree against the canonical stage tree declared in
rules/project_templates.yaml using a "required core + open extension" model:

- Core stages must exist with canonical names and canonical indices.
- Extension folders are welcome, but a letter-indexed prefix (e.g. "B.1.1.")
  must match the letter of its ancestor stage.
- Two siblings must not share the same stage prefix (index collision).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import AuditFinding, FolderRecord

# Matches "A. PreSales", "A.1. RFI_RFP_RFQ", "A.2.5 Contract", "B.1.1 Resources"
STAGE_NAME_PATTERN = re.compile(
    r"^(?P<letter>[A-Z])(?:\.(?P<indices>[0-9]+(?:\.[0-9]+)*))?\.?\s+(?P<label>.+)$"
)


@dataclass
class ParsedStage:
    letter: str
    indices: tuple[int, ...]
    label: str

    @property
    def prefix(self) -> str:
        if not self.indices:
            return self.letter
        return f"{self.letter}." + ".".join(str(i) for i in self.indices)


def parse_stage_name(name: str) -> ParsedStage | None:
    match = STAGE_NAME_PATTERN.match(name.strip())
    if not match:
        return None
    indices = match.group("indices")
    return ParsedStage(
        letter=match.group("letter"),
        indices=tuple(int(part) for part in indices.split(".")) if indices else (),
        label=match.group("label").strip(),
    )


def normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


@dataclass
class TemplateNode:
    prefix: str
    label: str
    canonical: str
    core: bool = False
    optional_wrapper: bool = False
    children: list["TemplateNode"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TemplateNode":
        return cls(
            prefix=data["prefix"],
            label=data["label"],
            canonical=data["canonical"],
            core=bool(data.get("core", False)),
            optional_wrapper=bool(data.get("optional_wrapper", False)),
            children=[cls.from_dict(child) for child in data.get("children", [])],
        )

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


class TemplateDiffer:
    """Validates initiative subtrees against the canonical stage tree."""

    def __init__(self, project_templates: dict[str, Any]):
        self.tree = [
            TemplateNode.from_dict(node)
            for node in project_templates.get("canonical_stage_tree", [])
        ]
        # Lookups by normalized label and by prefix across the whole tree.
        self.by_label: dict[str, TemplateNode] = {}
        self.by_prefix: dict[str, TemplateNode] = {}
        for root in self.tree:
            for node in root.walk():
                self.by_label.setdefault(normalize_label(node.label), node)
                self.by_prefix.setdefault(node.prefix, node)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def diff_initiative(
        self,
        initiative_path: str,
        folders_by_path: dict[str, FolderRecord],
        children_by_parent: dict[str | None, list[str]],
        enforce_core: bool = True,
    ) -> list[AuditFinding]:
        """Run all template validations for one initiative subtree."""
        findings: list[AuditFinding] = []
        findings.extend(
            self._check_subtree(initiative_path, children_by_parent, parent_stage=None)
        )
        if enforce_core:
            findings.extend(
                self._check_core_presence(initiative_path, children_by_parent)
            )
        return findings

    # ------------------------------------------------------------------
    # Core presence
    # ------------------------------------------------------------------

    def _stage_children(
        self,
        parent_path: str,
        children_by_parent: dict[str | None, list[str]],
    ) -> dict[str, ParsedStage]:
        result: dict[str, ParsedStage] = {}
        for child_path in children_by_parent.get(parent_path, []):
            name = child_path.rsplit("/", 1)[-1]
            parsed = parse_stage_name(name)
            if parsed:
                result[child_path] = parsed
        return result

    def _check_core_presence(
        self,
        initiative_path: str,
        children_by_parent: dict[str | None, list[str]],
    ) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        # Core stages may live directly under the initiative or inside the
        # optional "A. PreSales" wrapper.
        candidate_parents = [initiative_path]
        for child_path in children_by_parent.get(initiative_path, []):
            parsed = parse_stage_name(child_path.rsplit("/", 1)[-1])
            if parsed and not parsed.indices:
                candidate_parents.append(child_path)

        present_prefixes: set[str] = set()
        for parent in candidate_parents:
            for parsed in self._stage_children(parent, children_by_parent).values():
                present_prefixes.add(parsed.prefix)

        core_nodes = [
            node
            for root in self.tree
            for node in root.walk()
            if node.core
        ]
        for node in core_nodes:
            if node.prefix in present_prefixes:
                continue
            # Found under a different index? Handled by _check_subtree as
            # silent renumbering; only report truly missing stages here.
            label_found = any(
                normalize_label(parsed.label) == normalize_label(node.label)
                for parent in candidate_parents
                for parsed in self._stage_children(parent, children_by_parent).values()
            )
            if label_found:
                continue
            findings.append(
                AuditFinding(
                    folder_path=initiative_path,
                    issue_type="project_completeness",
                    severity="medium",
                    confidence=0.85,
                    suggested_action="review",
                    suggested_destination=f"{initiative_path}/{node.canonical}",
                    reasoning=(
                        f"Active presales project is missing the core template stage "
                        f"'{node.canonical}'."
                    ),
                )
            )
        return findings

    # ------------------------------------------------------------------
    # Recursive subtree validation
    # ------------------------------------------------------------------

    def _check_subtree(
        self,
        parent_path: str,
        children_by_parent: dict[str | None, list[str]],
        parent_stage: ParsedStage | None,
    ) -> list[AuditFinding]:
        findings: list[AuditFinding] = []
        stage_children = self._stage_children(parent_path, children_by_parent)

        # 1. Index collisions among siblings sharing the same stage prefix.
        collision_paths: set[str] = set()
        by_prefix: dict[str, list[tuple[str, ParsedStage]]] = {}
        for child_path, parsed in stage_children.items():
            by_prefix.setdefault(parsed.prefix, []).append((child_path, parsed))
        used_indices = {
            parsed.indices[-1]
            for parsed in stage_children.values()
            if parsed.indices
        }
        for prefix, entries in sorted(by_prefix.items()):
            if len(entries) < 2:
                continue
            keeper = self._collision_keeper(entries)
            next_index = (max(used_indices) if used_indices else 0) + 1
            for child_path, parsed in entries:
                if child_path == keeper:
                    continue
                collision_paths.add(child_path)
                proposed = self._renumbered_name(parsed, next_index)
                used_indices.add(next_index)
                next_index += 1
                findings.append(
                    AuditFinding(
                        folder_path=child_path,
                        issue_type="template_drift",
                        severity="medium",
                        confidence=0.9,
                        suggested_action="renumber",
                        suggested_destination=f"{parent_path}/{proposed}",
                        reasoning=(
                            f"Stage prefix '{prefix}.' is used by more than one sibling "
                            f"folder; renumbering to '{proposed}' keeps indices unique "
                            f"while core stages keep their canonical numbers."
                        ),
                    )
                )

        for child_path, parsed in sorted(stage_children.items()):
            name = child_path.rsplit("/", 1)[-1]

            # 2. Wrong-letter nesting: an indexed prefix must match the
            #    ancestor stage letter.
            if parent_stage is not None and parsed.letter != parent_stage.letter:
                destination = self._wrong_letter_destination(child_path, parsed)
                findings.append(
                    AuditFinding(
                        folder_path=child_path,
                        issue_type="template_drift",
                        severity="medium",
                        confidence=0.88,
                        suggested_action="move",
                        suggested_destination=destination,
                        reasoning=(
                            f"Folder prefix '{parsed.prefix}.' belongs to stage "
                            f"'{parsed.letter}.' but it is nested under stage "
                            f"'{parent_stage.prefix}.'."
                        ),
                    )
                )
                continue

            template_node = self.by_prefix.get(parsed.prefix)
            label_node = self.by_label.get(normalize_label(parsed.label))

            # 3. Canonical-name drift: prefix matches a template node but the
            #    name differs from canonical (alias spelling).
            if (
                template_node is not None
                and name != template_node.canonical
                and normalize_label(parsed.label) == normalize_label(template_node.label)
            ):
                findings.append(
                    AuditFinding(
                        folder_path=child_path,
                        issue_type="naming_inconsistency",
                        severity="low",
                        confidence=0.85,
                        suggested_action="standardize",
                        suggested_destination=template_node.canonical,
                        reasoning=(
                            f"Folder name '{name}' is an alias spelling of the canonical "
                            f"stage '{template_node.canonical}'."
                        ),
                    )
                )

            # 4. Silent renumbering: label matches a template node but the
            #    folder carries a different index. Same-depth check keeps
            #    "A.2.5. Proposal" (a collision, handled above) from matching
            #    the shallower "A.2. Proposal" template node.
            elif (
                label_node is not None
                and child_path not in collision_paths
                and parsed.prefix != label_node.prefix
                and parsed.letter == label_node.prefix[0]
                and len(parsed.indices) == label_node.prefix.count(".")
                and not self._canonical_slot_correctly_occupied(label_node, stage_children)
            ):
                findings.append(
                    AuditFinding(
                        folder_path=child_path,
                        issue_type="template_drift",
                        severity="low",
                        confidence=0.8,
                        suggested_action="renumber",
                        suggested_destination=label_node.canonical,
                        reasoning=(
                            f"Folder '{name}' matches the template stage "
                            f"'{label_node.canonical}' but carries index "
                            f"'{parsed.prefix}.' instead of '{label_node.prefix}.'."
                        ),
                    )
                )

            findings.extend(
                self._check_subtree(child_path, children_by_parent, parent_stage=parsed)
            )

        # Recurse into non-stage children too (extension folders are allowed,
        # but they may contain stage-prefixed folders deeper down).
        for child_path in children_by_parent.get(parent_path, []):
            if child_path in stage_children:
                continue
            findings.extend(
                self._check_subtree(child_path, children_by_parent, parent_stage=parent_stage)
            )

        return findings

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_slot_correctly_occupied(
        node: TemplateNode,
        stage_children: dict[str, ParsedStage],
    ) -> bool:
        """True when the canonical prefix slot is held by a folder whose label
        matches the template node; an interloper at that index does not block
        the renumber suggestion for the displaced core stage."""
        for parsed in stage_children.values():
            if parsed.prefix == node.prefix and normalize_label(parsed.label) == normalize_label(node.label):
                return True
        return False

    def _collision_keeper(self, entries: list[tuple[str, ParsedStage]]) -> str:
        """Among colliding siblings, the one matching the canonical template
        label keeps the index; otherwise the first alphabetically does."""
        for child_path, parsed in entries:
            node = self.by_prefix.get(parsed.prefix)
            if node and normalize_label(parsed.label) == normalize_label(node.label):
                return child_path
        return sorted(entries)[0][0]

    @staticmethod
    def _renumbered_name(parsed: ParsedStage, new_last_index: int) -> str:
        indices = parsed.indices[:-1] + (new_last_index,) if parsed.indices else (new_last_index,)
        prefix = f"{parsed.letter}." + ".".join(str(i) for i in indices)
        return f"{prefix}. {parsed.label}"

    def _wrong_letter_destination(self, child_path: str, parsed: ParsedStage) -> str | None:
        """Suggest moving a wrong-letter folder under its matching stage."""
        for root in self.tree:
            if root.prefix == parsed.letter:
                return f"under '{root.canonical}'"
        return None


def build_children_by_parent(folders: list[FolderRecord]) -> dict[str | None, list[str]]:
    children: dict[str | None, list[str]] = {}
    for folder in folders:
        children.setdefault(folder.parent_path, []).append(folder.path)
    for paths in children.values():
        paths.sort()
    return children

