"""Knowledge management system for research notes, decisions, and insights."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ResearchNote:
    """A single research note/observation."""
    note_id: str
    title: str
    content: str
    category: str  # feature, regime, execution, model, decision, rejected, future
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    experiment_ids: List[str] = field(default_factory=list)
    confidence: float = 0.5  # 0-1 confidence in the finding
    validated: bool = False
    version: int = 1
    supersedes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        title: str,
        content: str,
        category: str,
        tags: List[str] = None,
        experiment_ids: List[str] = None,
        confidence: float = 0.5,
    ) -> "ResearchNote":
        return cls(
            note_id=str(uuid.uuid4())[:8],
            title=title,
            content=content,
            category=category,
            tags=tags or [],
            experiment_ids=experiment_ids or [],
            confidence=confidence,
        )


@dataclass
class DecisionRecord:
    """A design decision with rationale."""
    decision_id: str
    title: str
    context: str  # What situation prompted this decision
    decision: str  # What was decided
    rationale: str  # Why this decision was made
    alternatives: List[str] = field(default_factory=list)  # What else was considered
    tradeoffs: Dict[str, str] = field(default_factory=dict)  # pros/cons
    status: str = "active"  # active, superseded, reverted
    superseded_by: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    experiment_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        title: str,
        context: str,
        decision: str,
        rationale: str,
        alternatives: List[str] = None,
        tradeoffs: Dict[str, str] = None,
        experiment_ids: List[str] = None,
    ) -> "DecisionRecord":
        return cls(
            decision_id=str(uuid.uuid4())[:8],
            title=title,
            context=context,
            decision=decision,
            rationale=rationale,
            alternatives=alternatives or [],
            tradeoffs=tradeoffs or {},
            experiment_ids=experiment_ids or [],
        )


@dataclass
class ExperimentSummary:
    """Summary of an experiment for the knowledge base."""
    experiment_id: str
    name: str
    hypothesis: str
    result: str  # confirmed, rejected, inconclusive
    key_findings: List[str]
    metrics: Dict[str, Any]
    lessons_learned: str
    follow_up: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RejectedIdea:
    """An idea that was tested and rejected."""
    idea_id: str
    title: str
    description: str
    reason_rejected: str
    experiment_id: Optional[str] = None
    date_rejected: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FutureIdea:
    """An idea for future investigation."""
    idea_id: str
    title: str
    description: str
    category: str  # feature, model, regime, execution, infrastructure
    priority: str = "medium"  # low, medium, high, critical
    estimated_effort: str = "medium"  # low, medium, high
    dependencies: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class KnowledgeBase:
    """
    Central knowledge management system.

    Stores:
    - Research notes and observations
    - Design decisions with rationale
    - Experiment summaries
    - Rejected ideas (to avoid re-work)
    - Future ideas (backlog)
    """

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self._notes: Dict[str, ResearchNote] = {}
        self._decisions: Dict[str, DecisionRecord] = {}
        self._experiments: Dict[str, ExperimentSummary] = {}
        self._rejected: Dict[str, RejectedIdea] = {}
        self._future: Dict[str, FutureIdea] = {}

        self._load_all()

    def _load_all(self) -> None:
        """Load all knowledge from storage."""
        for category, container in [
            ("notes", self._notes),
            ("decisions", self._decisions),
            ("experiments", self._experiments),
            ("rejected", self._rejected),
            ("future", self._future),
        ]:
            file = self.storage_path / f"{category}.json"
            if file.exists():
                try:
                    data = json.loads(file.read_text())
                    for item in data:
                        item_id = item.get(f"{category[:-1]}_id") or item.get("note_id") or item.get("decision_id") or item.get("experiment_id") or item.get("idea_id")
                        if item_id:
                            container[item_id] = item
                except Exception:
                    pass

    def _save_all(self) -> None:
        """Save all knowledge to storage."""
        for category, container in [
            ("notes", self._notes),
            ("decisions", self._decisions),
            ("experiments", self._experiments),
            ("rejected", self._rejected),
            ("future", self._future),
        ]:
            file = self.storage_path / f"{category}.json"
            data = list(container.values())
            file.write_text(json.dumps(data, indent=2))

    # ========== Notes ==========

    def add_note(
        self,
        title: str,
        content: str,
        category: str,
        tags: List[str] = None,
        experiment_ids: List[str] = None,
        confidence: float = 0.5,
    ) -> ResearchNote:
        """Add a research note."""
        note = ResearchNote.create(
            title=title,
            content=content,
            category=category,
            tags=tags,
            experiment_ids=experiment_ids,
            confidence=confidence,
        )
        self._notes[note.note_id] = note
        self._save_all()
        return note

    def update_note(self, note_id: str, **kwargs) -> Optional[ResearchNote]:
        """Update a note."""
        note = self._notes.get(note_id)
        if not note:
            return None

        # Create new version
        data = asdict(note)
        data.update(kwargs)
        data["updated_at"] = datetime.utcnow().isoformat() + "Z"
        data["version"] = note.version + 1

        updated = ResearchNote(**data)
        self._notes[note_id] = updated
        self._save_all()
        return updated

    def get_note(self, note_id: str) -> Optional[ResearchNote]:
        return self._notes.get(note_id)

    def search_notes(
        self,
        category: str = None,
        tag: str = None,
        query: str = None,
        min_confidence: float = 0.0,
    ) -> List[ResearchNote]:
        """Search notes with filters."""
        results = []
        for note in self._notes.values():
            if category and note.category != category:
                continue
            if tag and tag not in note.tags:
                continue
            if query and query.lower() not in (note.title + " " + note.content).lower():
                continue
            if note.confidence < min_confidence:
                continue
            results.append(note)
        return sorted(results, key=lambda n: n.updated_at, reverse=True)

    def get_notes_by_experiment(self, experiment_id: str) -> List[ResearchNote]:
        """Get all notes linked to an experiment."""
        return [n for n in self._notes.values() if experiment_id in n.experiment_ids]

    # ========== Decisions ==========

    def record_decision(
        self,
        title: str,
        context: str,
        decision: str,
        rationale: str,
        alternatives: List[str] = None,
        tradeoffs: Dict[str, str] = None,
        experiment_ids: List[str] = None,
    ) -> DecisionRecord:
        """Record a design decision."""
        decision = DecisionRecord.create(
            title=title,
            context=context,
            decision=decision,
            rationale=rationale,
            alternatives=alternatives,
            tradeoffs=tradeoffs,
            experiment_ids=experiment_ids,
        )
        self._decisions[decision.decision_id] = decision
        self._save_all()
        return decision

    def supersede_decision(self, decision_id: str, new_decision_id: str) -> bool:
        """Mark a decision as superseded."""
        old = self._decisions.get(decision_id)
        new = self._decisions.get(new_decision_id)
        if not old or not new:
            return False
        old.status = "superseded"
        old.superseded_by = new_decision_id
        new.status = "active"
        self._save_all()
        return True

    def get_decision(self, decision_id: str) -> Optional[DecisionRecord]:
        return self._decisions.get(decision_id)

    def list_decisions(self, status: str = "active") -> List[DecisionRecord]:
        """List decisions by status."""
        return [d for d in self._decisions.values() if d.status == status]

    # ========== Experiments ==========

    def summarize_experiment(
        self,
        experiment_id: str,
        name: str,
        hypothesis: str,
        result: str,
        key_findings: List[str],
        metrics: Dict[str, Any],
        lessons_learned: str,
        follow_up: List[str] = None,
    ) -> ExperimentSummary:
        """Create an experiment summary for the knowledge base."""
        summary = ExperimentSummary(
            experiment_id=experiment_id,
            name=name,
            hypothesis=hypothesis,
            result=result,
            key_findings=key_findings,
            metrics=metrics,
            lessons_learned=lessons_learned,
            follow_up=follow_up or [],
        )
        self._experiments[experiment_id] = summary
        self._save_all()
        return summary

    def get_experiment(self, experiment_id: str) -> Optional[ExperimentSummary]:
        return self._experiments.get(experiment_id)

    def list_experiments(self, result: str = None) -> List[ExperimentSummary]:
        """List experiments, optionally filtered by result."""
        exps = list(self._experiments.values())
        if result:
            exps = [e for e in exps if e.result == result]
        return sorted(exps, key=lambda e: e.created_at, reverse=True)

    # ========== Rejected Ideas ==========

    def record_rejection(
        self,
        title: str,
        description: str,
        reason_rejected: str,
        experiment_id: str = None,
        notes: str = "",
    ) -> RejectedIdea:
        """Record a rejected idea to avoid re-work."""
        rejected = RejectedIdea(
            idea_id=str(uuid.uuid4())[:8],
            title=title,
            description=description,
            reason_rejected=reason_rejected,
            experiment_id=experiment_id,
            notes=notes,
        )
        self._rejected[rejected.idea_id] = rejected
        self._save_all()
        return rejected

    def was_rejected(self, title: str = None, description: str = None) -> List[RejectedIdea]:
        """Check if an idea was previously rejected."""
        results = []
        for r in self._rejected.values():
            if title and title.lower() in r.title.lower():
                results.append(r)
            elif description and description.lower() in r.description.lower():
                results.append(r)
        return results

    # ========== Future Ideas ==========

    def add_future_idea(
        self,
        title: str,
        description: str,
        category: str,
        priority: str = "medium",
        estimated_effort: str = "medium",
        dependencies: List[str] = None,
    ) -> FutureIdea:
        """Add an idea for future investigation."""
        idea = FutureIdea(
            idea_id=str(uuid.uuid4())[:8],
            title=title,
            description=description,
            category=category,
            priority=priority,
            estimated_effort=estimated_effort,
            dependencies=dependencies or [],
        )
        self._future[idea.idea_id] = idea
        self._save_all()
        return idea

    def list_future_ideas(self, category: str = None, priority: str = None) -> List[FutureIdea]:
        """List future ideas with optional filters."""
        ideas = list(self._future.values())
        if category:
            ideas = [i for i in ideas if i.category == category]
        if priority:
            ideas = [i for i in ideas if i.priority == priority]
        return sorted(ideas, key=lambda i: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(i.priority, 4))

    # ========== Cleanup & Archival ==========

    def cleanup(
        self,
        max_days: int = 90,
        archive_dir: Path | None = None,
    ) -> dict[str, int]:
        """Remove (or archive) entries older than `max_days` days.

        Args:
            max_days: Entries with no update within this many days are pruned.
                      Default 90 days (~3 months). Set to 0 to disable cleanup.
            archive_dir: If provided, pruned entries are saved as a timestamped
                         JSON file here instead of being permanently deleted.

        Returns:
            A dict with counts of pruned entries per category:
            ``{"notes": N, "decisions": N, "experiments": N, ...}``
        """
        if max_days <= 0:
            return {}

        cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
        pruned: dict[str, list[dict[str, Any]]] = {
            "notes": [],
            "decisions": [],
            "experiments": [],
            "rejected": [],
            "future": [],
        }

        def _older_than(timestamp_str: str | None) -> bool:
            """Check if an ISO timestamp is older than the cutoff."""
            if not timestamp_str:
                return False
            try:
                dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                return dt < cutoff
            except (ValueError, TypeError):
                return False

        def _prune_container(
            container: dict[str, Any],
            category: str,
            time_field: str = "created_at",
        ) -> None:
            stale_ids = [
                id_ for id_, entry in container.items()
                if _older_than(getattr(entry, time_field, None) if hasattr(entry, time_field) else entry.get(time_field))
            ]
            for id_ in stale_ids:
                pruned[category].append(container.pop(id_))

        _prune_container(self._notes, "notes", "updated_at")
        _prune_container(self._decisions, "decisions", "created_at")
        _prune_container(self._experiments, "experiments", "created_at")
        _prune_container(self._rejected, "rejected", "date_rejected")
        _prune_container(self._future, "future", "created_at")

        # Archive to a timestamped file if requested
        if archive_dir is not None and any(pruned.values()):
            archive_path = Path(archive_dir)
            archive_path.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            archive_file = archive_path / f"knowledge_archive_{timestamp}.json"
            archive_file.write_text(
                json.dumps(pruned, indent=2, default=str),
                encoding="utf-8",
            )

        if any(pruned.values()):
            self._save_all()

        return {cat: len(items) for cat, items in pruned.items()}

    # ========== Export & Reporting ==========

    def export_knowledge_report(self, output_path: Path, since: str = None) -> Path:
        """Export comprehensive knowledge report as markdown."""
        lines = [
            "# Knowledge Base Report",
            f"Generated: {datetime.utcnow().isoformat()}",
            "",
        ]

        if since:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            notes = [n for n in self._notes.values() if datetime.fromisoformat(n.updated_at.replace("Z", "+00:00")) > since_dt]
            decisions = [d for d in self._decisions.values() if datetime.fromisoformat(d.created_at.replace("Z", "+00:00")) > since_dt]
            experiments = [e for e in self._experiments.values() if datetime.fromisoformat(e.created_at.replace("Z", "+00:00")) > since_dt]
        else:
            notes = list(self._notes.values())
            decisions = list(self._decisions.values())
            experiments = list(self._experiments.values())

        lines.append(f"## Summary")
        lines.append(f"- Research Notes: {len(notes)}")
        lines.append(f"- Decisions: {len(decisions)}")
        lines.append(f"- Experiments: {len(experiments)}")
        lines.append(f"- Rejected Ideas: {len(self._rejected)}")
        lines.append(f"- Future Ideas: {len(self._future)}")
        lines.append("")

        # Decisions
        if decisions:
            lines.append("## Design Decisions")
            for d in sorted(decisions, key=lambda d: d.created_at):
                lines.append(f"### {d.title} ({d.decision_id})")
                lines.append(f"**Context:** {d.context}")
                lines.append(f"**Decision:** {d.decision}")
                lines.append(f"**Rationale:** {d.rationale}")
                if d.alternatives:
                    lines.append(f"**Alternatives Considered:** {', '.join(d.alternatives)}")
                if d.tradeoffs:
                    lines.append("**Tradeoffs:**")
                    for k, v in d.tradeoffs.items():
                        lines.append(f"- {k}: {v}")
                lines.append(f"**Status:** {d.status}")
                lines.append("")

        # Experiments
        if experiments:
            lines.append("## Experiments")
            for e in sorted(experiments, key=lambda e: e.created_at):
                lines.append(f"### {e.name} ({e.experiment_id})")
                lines.append(f"**Hypothesis:** {e.hypothesis}")
                lines.append(f"**Result:** {e.result}")
                if e.key_findings:
                    lines.append("**Key Findings:**")
                    for f in e.key_findings:
                        lines.append(f"- {f}")
                if e.metrics:
                    lines.append("**Metrics:**")
                    for k, v in e.metrics.items():
                        lines.append(f"- {k}: {v}")
                lines.append(f"**Lessons Learned:** {e.lessons_learned}")
                if e.follow_up:
                    lines.append("**Follow-up:**")
                    for f in e.follow_up:
                        lines.append(f"- {f}")
                lines.append("")

        # Notes by category
        if notes:
            lines.append("## Research Notes")
            for cat in ["feature", "regime", "execution", "model", "decision", "rejected", "future"]:
                cat_notes = [n for n in notes if n.category == cat]
                if not cat_notes:
                    continue
                lines.append(f"### {cat.title()}")
                for n in sorted(cat_notes, key=lambda n: n.updated_at, reverse=True):
                    lines.append(f"#### {n.title} ({n.note_id})")
                    lines.append(f"**Confidence:** {n.confidence:.0%} | **Tags:** {', '.join(n.tags) or 'none'}")
                    lines.append(n.content)
                    lines.append("")

        # Rejected ideas
        if self._rejected:
            lines.append("## Rejected Ideas")
            for r in self._rejected.values():
                lines.append(f"### {r.title} ({r.idea_id})")
                lines.append(f"**Reason:** {r.reason_rejected}")
                lines.append(f"**Description:** {r.description}")
                if r.notes:
                    lines.append(f"**Notes:** {r.notes}")
                lines.append("")

        # Future ideas
        if self._future:
            lines.append("## Future Ideas")
            for cat in ["feature", "model", "regime", "execution", "infrastructure"]:
                cat_ideas = [i for i in self._future.values() if i.category == cat]
                if not cat_ideas:
                    continue
                lines.append(f"### {cat.title()}")
                for i in sorted(cat_ideas, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.priority, 4)):
                    lines.append(f"- **{i.title}** ({i.priority} priority, {i.estimated_effort} effort): {i.description}")
                lines.append("")

        output_path.write_text("\n".join(lines))
        return output_path

    def export_to_json(self, output_path: Path) -> Path:
        """Export entire knowledge base as JSON."""
        data = {
            "notes": {k: asdict(v) for k, v in self._notes.items()},
            "decisions": {k: asdict(v) for k, v in self._decisions.items()},
            "experiments": {k: asdict(v) for k, v in self._experiments.items()},
            "rejected": {k: asdict(v) for k, v in self._rejected.items()},
            "future": {k: asdict(v) for k, v in self._future.items()},
            "exported_at": datetime.utcnow().isoformat() + "Z",
        }
        output_path.write_text(json.dumps(data, indent=2))
        return output_path