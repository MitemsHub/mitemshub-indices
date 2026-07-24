"""Knowledge management system for research notes, decisions, and insights."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
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
    reason: str = ""  # Why it was rejected
    reason_rejected: str = ""  # Alias for test compatibility
    evidence: str = ""  # What data/results led to rejection
    category: str = "feature"  # feature, regime, execution, model, method
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    experiment_id: Optional[str] = None
    notes: str = ""

    def __post_init__(self):
        # Sync reason and reason_rejected
        if self.reason_rejected and not self.reason:
            self.reason = self.reason_rejected
        elif self.reason and not self.reason_rejected:
            self.reason_rejected = self.reason

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["reason_rejected"] = self.reason
        return d

    @classmethod
    def create(
        cls,
        title: str,
        description: str,
        reason: str,
        evidence: str,
        category: str = "feature",
        experiment_id: Optional[str] = None,
        notes: str = "",
    ) -> "RejectedIdea":
        return cls(
            idea_id=str(uuid.uuid4())[:8],
            title=title,
            description=description,
            reason=reason,
            reason_rejected=reason,
            evidence=evidence,
            category=category,
            experiment_id=experiment_id,
            notes=notes,
        )


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
    experiment_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        title: str,
        description: str,
        category: str,
        priority: str = "medium",
        estimated_effort: str = "medium",
        dependencies: List[str] = None,
        experiment_ids: List[str] = None,
    ) -> "FutureIdea":
        return cls(
            idea_id=str(uuid.uuid4())[:8],
            title=title,
            description=description,
            category=category,
            priority=priority,
            estimated_effort=estimated_effort,
            dependencies=dependencies or [],
            experiment_ids=experiment_ids or [],
        )


@dataclass
class LessonLearned:
    """A lesson learned from experience."""
    lesson_id: str
    title: str
    situation: str  # What happened
    lesson: str  # What was learned
    action: str  # What to do differently
    severity: str = "info"  # info, warning, critical
    category: str = "general"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    experiment_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(
        cls,
        title: str,
        situation: str,
        lesson: str,
        action: str,
        severity: str = "info",
        category: str = "general",
        experiment_ids: List[str] = None,
    ) -> "LessonLearned":
        return cls(
            lesson_id=str(uuid.uuid4())[:8],
            title=title,
            situation=situation,
            lesson=lesson,
            action=action,
            severity=severity,
            category=category,
            experiment_ids=experiment_ids or [],
        )


class KnowledgeBase:
    """
    Centralized knowledge management for the research platform.

    Stores:
    - Research notes (observations, findings)
    - Design decisions (with rationale)
    - Experiment summaries
    - Rejected ideas (to avoid repeating)
    - Future ideas (backlog)
    - Lessons learned (post-mortems)
    """

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.notes_file = self.storage_path / "research_notes.json"
        self.decisions_file = self.storage_path / "decisions.json"
        self.rejected_file = self.storage_path / "rejected_ideas.json"
        self.future_file = self.storage_path / "future_ideas.json"
        self.lessons_file = self.storage_path / "lessons_learned.json"
        self.experiments_file = self.storage_path / "experiment_summaries.json"

        self._notes: List[ResearchNote] = []
        self._decisions: List[DecisionRecord] = []
        self._rejected: Dict[str, RejectedIdea] = {}
        self._future: Dict[str, FutureIdea] = {}
        self._lessons: List[LessonLearned] = []
        self._experiments: Dict[str, ExperimentSummary] = {}

        self._load_all()

    def _load_all(self) -> None:
        """Load all knowledge from storage."""
        self._notes = self._load_list(self.notes_file, ResearchNote)
        self._decisions = self._load_list(self.decisions_file, DecisionRecord)
        self._rejected = {item.idea_id: item for item in self._load_list(self.rejected_file, RejectedIdea)}
        self._future = {item.idea_id: item for item in self._load_list(self.future_file, FutureIdea)}
        self._lessons = self._load_list(self.lessons_file, LessonLearned)
        self._experiments = {item.experiment_id: item for item in self._load_list(self.experiments_file, ExperimentSummary)}

    def _load_list(self, file: Path, cls) -> List:
        if file.exists():
            try:
                data = json.loads(file.read_text())
                return [cls(**item) for item in data]
            except Exception:
                return []
        return []

    def _save(self, file: Path, items: List) -> None:
        file.write_text(json.dumps([item.to_dict() for item in items], indent=2))

    def _save_dict(self, file: Path, items: Dict) -> None:
        file.write_text(json.dumps([item.to_dict() for item in items.values()], indent=2))

    def _save_all(self) -> None:
        self._save(self.notes_file, self._notes)
        self._save(self.decisions_file, self._decisions)
        self._save_dict(self.rejected_file, self._rejected)
        self._save_dict(self.future_file, self._future)
        self._save(self.lessons_file, self._lessons)
        self._save_dict(self.experiments_file, self._experiments)

    # Research Notes - main methods
    def _add_note_internal(self, note: ResearchNote) -> ResearchNote:
        self._notes.append(note)
        self._save(self.notes_file, self._notes)
        return note

    def create_note(
        self,
        title: str,
        content: str,
        category: str,
        tags: List[str] = None,
        experiment_ids: List[str] = None,
        confidence: float = 0.5,
    ) -> ResearchNote:
        """Create and add a research note."""
        note = ResearchNote.create(title, content, category, tags, experiment_ids, confidence)
        self._notes.append(note)
        self._save(self.notes_file, self._notes)
        return note

    # Alias for test compatibility
    def add_note(
        self,
        title: str,
        content: str,
        category: str,
        tags: List[str] = None,
        experiment_ids: List[str] = None,
        confidence: float = 0.5,
    ) -> ResearchNote:
        """Add a research note (alias for create_note with explicit parameter names)."""
        return self.create_note(title, content, category, tags, experiment_ids, confidence)

    def get_notes(
        self,
        category: str = None,
        tag: str = None,
        experiment_id: str = None,
        min_confidence: float = 0.0,
    ) -> List[ResearchNote]:
        notes = self._notes
        if category:
            notes = [n for n in notes if n.category == category]
        if tag:
            notes = [n for n in notes if tag in n.tags]
        if experiment_id:
            notes = [n for n in notes if experiment_id in n.experiment_ids]
        if min_confidence > 0:
            notes = [n for n in notes if n.confidence >= min_confidence]
        return sorted(notes, key=lambda n: n.updated_at, reverse=True)

    def update_note(self, note_id: str, **kwargs) -> Optional[ResearchNote]:
        for i, note in enumerate(self._notes):
            if note.note_id == note_id:
                updated = note.to_dict()
                updated.update(kwargs)
                updated["updated_at"] = datetime.utcnow().isoformat() + "Z"
                updated["version"] = note.version + 1
                self._notes[i] = ResearchNote(**updated)
                self._save(self.notes_file, self._notes)
                return self._notes[i]
        return None

    def link_experiment(self, note_id: str, experiment_id: str) -> bool:
        for i, note in enumerate(self._notes):
            if note.note_id == note_id:
                if experiment_id not in note.experiment_ids:
                    self._notes[i].experiment_ids.append(experiment_id)
                    self._save(self.notes_file, self._notes)
                    return True
        return False

    # Decisions
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
        dec = DecisionRecord.create(
            title=title,
            context=context,
            decision=decision,
            rationale=rationale,
            alternatives=alternatives,
            tradeoffs=tradeoffs,
            experiment_ids=experiment_ids,
        )
        self._decisions.append(dec)
        self._save(self.decisions_file, self._decisions)
        return dec

    # Alias for test compatibility
    def add_decision(
        self,
        title: str,
        context: str,
        decision: str,
        rationale: str,
        alternatives: List[str] = None,
        tradeoffs: Dict[str, str] = None,
        experiment_ids: List[str] = None,
    ) -> DecisionRecord:
        """Add a decision (alias for record_decision)."""
        return self.record_decision(title, context, decision, rationale, alternatives, tradeoffs, experiment_ids)

    def create_decision(
        self,
        title: str,
        context: str,
        decision: str,
        rationale: str,
        alternatives: List[str] = None,
        tradeoffs: Dict[str, str] = None,
        experiment_ids: List[str] = None,
    ) -> DecisionRecord:
        """Create a decision (alias for record_decision)."""
        return self.record_decision(title, context, decision, rationale, alternatives, tradeoffs, experiment_ids)

    def get_decisions(self, status: str = "active") -> List[DecisionRecord]:
        if status == "all":
            return self._decisions
        return [d for d in self._decisions if d.status == status]

    def supersede_decision(self, decision_id: str, new_decision_id: str) -> bool:
        for i, d in enumerate(self._decisions):
            if d.decision_id == decision_id:
                self._decisions[i].status = "superseded"
                self._decisions[i].superseded_by = new_decision_id
                self._save(self.decisions_file, self._decisions)
                return True
        return False

    # Experiment Summaries
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
        """Summarize an experiment."""
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
        self._save_dict(self.experiments_file, self._experiments)
        return summary

    # Alias for test compatibility
    def add_experiment_summary(
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
        """Add an experiment summary (alias)."""
        return self.summarize_experiment(
            experiment_id, name, hypothesis, result, key_findings, metrics, lessons_learned, follow_up
        )

    def get_experiment(self, experiment_id: str) -> Optional[ExperimentSummary]:
        return self._experiments.get(experiment_id)

    def list_experiments(self, result: str = None) -> List[ExperimentSummary]:
        exps = list(self._experiments.values())
        if result:
            exps = [e for e in exps if e.result == result]
        return sorted(exps, key=lambda e: e.created_at, reverse=True)

    # Rejected Ideas
    def record_rejection(
        self,
        title: str,
        description: str,
        reason_rejected: str,
        experiment_id: str = None,
        notes: str = "",
    ) -> RejectedIdea:
        """Record a rejected idea."""
        rejected = RejectedIdea(
            idea_id=str(uuid.uuid4())[:8],
            title=title,
            description=description,
            reason=reason_rejected,
            reason_rejected=reason_rejected,
            evidence=notes,
            category="feature",
            experiment_id=experiment_id,
            notes=notes,
        )
        self._rejected[rejected.idea_id] = rejected
        self._save_dict(self.rejected_file, self._rejected)
        return rejected

    def add_rejected(
        self,
        title: str,
        description: str,
        reason: str,
        evidence: str,
        category: str = "feature",
        experiment_id: str = None,
        notes: str = "",
    ) -> RejectedIdea:
        """Add a rejected idea."""
        rejected = RejectedIdea.create(
            title=title,
            description=description,
            reason=reason,
            evidence=evidence,
            category=category,
            experiment_id=experiment_id,
            notes=notes,
        )
        self._rejected[rejected.idea_id] = rejected
        self._save_dict(self.rejected_file, self._rejected)
        return rejected

    def get_rejected(self, category: str = None) -> List[RejectedIdea]:
        ideas = list(self._rejected.values())
        if category:
            ideas = [i for i in ideas if i.category == category]
        return sorted(ideas, key=lambda i: i.created_at, reverse=True)

    def was_rejected(self, title: str = None, description: str = None) -> List[RejectedIdea]:
        """Check if an idea was previously rejected."""
        results = []
        for r in self._rejected.values():
            if title and title.lower() in r.title.lower():
                results.append(r)
            elif description and description.lower() in r.description.lower():
                results.append(r)
        return results

    # Future Ideas
    def add_future_idea(
        self,
        title: str,
        description: str,
        category: str,
        priority: str = "medium",
        estimated_effort: str = "medium",
        dependencies: List[str] = None,
    ) -> FutureIdea:
        """Add a future idea (alias for add_future)."""
        return self.add_future(title, description, category, priority, estimated_effort, None, None)

    def add_future(
        self,
        title: str,
        description: str,
        category: str,
        priority: str = "medium",
        estimated_effort: str = "medium",
        dependencies: List[str] = None,
        experiment_ids: List[str] = None,
    ) -> FutureIdea:
        """Add a future idea."""
        idea = FutureIdea(
            idea_id=str(uuid.uuid4())[:8],
            title=title,
            description=description,
            category=category,
            priority=priority,
            estimated_effort=estimated_effort,
            dependencies=dependencies or [],
            experiment_ids=experiment_ids or [],
        )
        self._future[idea.idea_id] = idea
        self._save_dict(self.future_file, self._future)
        return idea

    def create_future(
        self,
        title: str,
        description: str,
        category: str,
        priority: str = "medium",
        estimated_effort: str = "medium",
        dependencies: List[str] = None,
        experiment_ids: List[str] = None,
    ) -> FutureIdea:
        """Create a future idea (alias)."""
        return self.add_future(title, description, category, priority, estimated_effort, dependencies, experiment_ids)

    def get_future(self, category: str = None, priority: str = None) -> List[FutureIdea]:
        ideas = list(self._future.values())
        if category:
            ideas = [i for i in ideas if i.category == category]
        if priority:
            ideas = [i for i in ideas if i.priority == priority]
        return sorted(ideas, key=lambda i: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(i.priority, 4))

    # Lessons Learned
    def add_lesson(
        self,
        title: str,
        situation: str,
        lesson: str,
        action: str,
        severity: str = "info",
        category: str = "general",
        experiment_ids: List[str] = None,
    ) -> LessonLearned:
        """Add a lesson learned."""
        lesson = LessonLearned.create(
            title=title,
            situation=situation,
            lesson=lesson,
            action=action,
            severity=severity,
            category=category,
            experiment_ids=experiment_ids,
        )
        self._lessons.append(lesson)
        self._save(self.lessons_file, self._lessons)
        return lesson

    def create_lesson(
        self,
        title: str,
        situation: str,
        lesson: str,
        action: str,
        severity: str = "info",
        category: str = "general",
        experiment_ids: List[str] = None,
    ) -> LessonLearned:
        """Create a lesson learned (alias)."""
        return self.add_lesson(title, situation, lesson, action, severity, category, experiment_ids)

    def get_lessons(self, category: str = None, severity: str = None) -> List[LessonLearned]:
        lessons = self._lessons
        if category:
            lessons = [l for l in lessons if l.category == category]
        if severity:
            lessons = [l for l in lessons if l.severity == severity]
        return sorted(lessons, key=lambda l: l.created_at, reverse=True)

    # Cross-referencing
    def get_related_knowledge(self, experiment_id: str) -> Dict[str, List]:
        """Get all knowledge linked to an experiment."""
        return {
            "notes": self.get_notes(experiment_id=experiment_id),
            "decisions": [d for d in self._decisions if experiment_id in d.experiment_ids],
            "rejected": [i for i in self._rejected.values() if i.experiment_id == experiment_id],
            "future": [i for i in self._future.values() if experiment_id in i.experiment_ids],
            "lessons": [l for l in self._lessons if experiment_id in l.experiment_ids],
        }

    def search(self, query: str) -> Dict[str, List]:
        """Full-text search across all knowledge."""
        query = query.lower()
        results = {
            "notes": [n for n in self._notes if query in n.title.lower() or query in n.content.lower()],
            "decisions": [d for d in self._decisions if query in d.title.lower() or query in d.rationale.lower()],
            "rejected": [i for i in self._rejected.values() if query in i.title.lower() or query in i.description.lower()],
            "future": [i for i in self._future.values() if query in i.title.lower() or query in i.description.lower()],
            "lessons": [l for l in self._lessons if query in l.title.lower() or query in l.lesson.lower()],
        }
        return results

    # Alias methods for test compatibility
    def search_notes(self, category: str = None, tag: str = None, query: str = None, min_confidence: float = 0.0) -> List[ResearchNote]:
        """Search notes with optional filters."""
        return self.get_notes(category=category, tag=tag, min_confidence=min_confidence)

    def list_future_ideas(self, category: str = None, priority: str = None) -> List[FutureIdea]:
        """List future ideas with optional filters."""
        return self.get_future(category=category, priority=priority)

    def list_decisions(self, status: str = "active") -> List[DecisionRecord]:
        """List decisions with optional status filter."""
        return self.get_decisions(status=status)

    def list_experiments(self, result: str = None) -> List[ExperimentSummary]:
        """List experiments with optional result filter."""
        exps = list(self._experiments.values())
        if result:
            exps = [e for e in exps if e.result == result]
        return sorted(exps, key=lambda e: e.created_at, reverse=True)

    def export_knowledge_report(self, output_path: Path) -> Path:
        """Export knowledge base to markdown (alias for export_markdown)."""
        return self.export_markdown(output_path)

    def export_markdown(self, output_path: Path) -> Path:
        """Export knowledge base to markdown for documentation."""
        lines = [
            "# Knowledge Base Export",
            f"Generated: {datetime.utcnow().isoformat()}",
            "",
        ]

        # Notes by category
        for cat in ["feature", "regime", "execution", "model", "decision", "rejected", "future"]:
            notes = self.get_notes(category=cat)
            if notes:
                lines.append(f"## {cat.title()} Notes")
                for n in notes:
                    lines.append(f"### {n.title} ({n.note_id})")
                    lines.append(f"**Confidence:** {n.confidence:.0%} | **Validated:** {n.validated}")
                    lines.append(f"**Tags:** {', '.join(n.tags) if n.tags else 'none'}")
                    lines.append(f"**Experiments:** {', '.join(n.experiment_ids) if n.experiment_ids else 'none'}")
                    lines.append("")
                    lines.append(n.content)
                    lines.append("")
                lines.append("")

        # Decisions
        decisions = self.get_decisions("active")
        if decisions:
            lines.append("## Active Decisions")
            for d in decisions:
                lines.append(f"### {d.title} ({d.decision_id})")
                lines.append(f"**Context:** {d.context}")
                lines.append(f"**Decision:** {d.decision}")
                lines.append(f"**Rationale:** {d.rationale}")
                if d.alternatives:
                    lines.append(f"**Alternatives:** {', '.join(d.alternatives)}")
                if d.tradeoffs:
                    for k, v in d.tradeoffs.items():
                        lines.append(f"**{k}:** {v}")
                lines.append("")

        # Rejected Ideas
        rejected = self.get_rejected()
        if rejected:
            lines.append("## Rejected Ideas")
            for i in rejected:
                lines.append(f"### {i.title} ({i.idea_id})")
                lines.append(f"**Reason:** {i.reason}")
                lines.append(f"**Evidence:** {i.evidence}")
                lines.append("")

        # Experiment Summaries
        experiments = self.list_experiments()
        if experiments:
            lines.append("## Experiment Summaries")
            for e in experiments:
                lines.append(f"### {e.name} ({e.experiment_id})")
                lines.append(f"**Hypothesis:** {e.hypothesis}")
                lines.append(f"**Result:** {e.result}")
                if e.key_findings:
                    lines.append(f"**Key Findings:** {', '.join(e.key_findings)}")
                if e.metrics:
                    lines.append(f"**Metrics:** {e.metrics}")
                if e.lessons_learned:
                    lines.append(f"**Lessons Learned:** {e.lessons_learned}")
                lines.append("")

        # Future Ideas
        future = self.get_future()
        if future:
            lines.append("## Future Ideas (Backlog)")
            for i in future:
                lines.append(f"### {i.title} ({i.idea_id}) [{i.priority}]")
                lines.append(f"**Category:** {i.category} | **Effort:** {i.estimated_effort}")
                lines.append(f"**Description:** {i.description}")
                if i.dependencies:
                    lines.append(f"**Dependencies:** {', '.join(i.dependencies)}")
                lines.append("")

        # Lessons
        lessons = self.get_lessons()
        if lessons:
            lines.append("## Lessons Learned")
            for l in lessons:
                lines.append(f"### {l.title} ({l.lesson_id}) [{l.severity}]")
                lines.append(f"**Situation:** {l.situation}")
                lines.append(f"**Lesson:** {l.lesson}")
                lines.append(f"**Action:** {l.action}")
                lines.append("")

        output_path.write_text("\n".join(lines))
        return output_path