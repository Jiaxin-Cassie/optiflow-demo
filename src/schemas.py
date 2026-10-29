"""Typed contracts shared by the modeling agents and task adapter."""
from typing import Any
from pydantic import BaseModel, Field


class Problem(BaseModel):
    problem_id: str
    problem_text: str


class ProblemProfile(BaseModel):
    optimization_type: str = 'unknown'
    problem_types: list[str] = Field(default_factory=list)
    problem_domain: str = 'unknown'
    objective_type: str = 'unknown'
    entities: list[str] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)
    decision_targets: list[str] = Field(default_factory=list)
    constraint_patterns: list[str] = Field(default_factory=list)
    structural_patterns: list[str] = Field(default_factory=list)
    recommended_solver: str = 'unknown'
    explicit_objective: str = ''
    resource_relations: list[str] = Field(default_factory=list)
    demand_relations: list[str] = Field(default_factory=list)
    time_relations: list[str] = Field(default_factory=list)
    conditional_relations: list[str] = Field(default_factory=list)
    explicit_restrictions: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)

class ReferenceKnowledge(BaseModel):
    text_preview: str = ''
    knowledge_unit: dict[str, Any] = Field(default_factory=dict)
    reference_id: str
    skill_name: str
    category: str
    path: str
    text: str
    knowledge_category: str = 'unknown'
    artifact_type: str = 'knowledge_component'
    representation_form: str = 'source'
    source_skill_path: str = ''
    score: float = 0.0

class SkillMetadata(BaseModel):
    knowledge_unit: dict[str, Any] = Field(default_factory=dict)
    name: str
    category: str
    description: str
    path: str
    body: str
    knowledge_category: str = 'unknown'
    artifact_type: str = 'knowledge_component'
    representation_form: str = 'structured_reference'
    contract: dict[str, Any] = Field(default_factory=dict)
    script_paths: list[str] = Field(default_factory=list)
    validator_paths: list[str] = Field(default_factory=list)
    use_when: str = ''
    do_not_use_when: str = ''
    references: list[ReferenceKnowledge] = Field(default_factory=list)
    metadata_score: float = 0.0
    metadata_components: dict[str, Any] = Field(default_factory=dict)

class ActivatedSkill(BaseModel):
    name: str
    category: str
    description: str = ''
    score: float = 0.0
    reason: str = ''
    metadata_score: float = 0.0
    metadata_components: dict[str, Any] = Field(default_factory=dict)
    judge_scores: dict[str, float] = Field(default_factory=dict)
    skill_score: float = 0.0
    selected: bool = True
    references: list[ReferenceKnowledge] = Field(default_factory=list)

class SkillJudgeRecord(BaseModel):
    name: str
    category: str
    description: str = ''
    metadata_score: float = 0.0
    metadata_components: dict[str, Any] = Field(default_factory=dict)
    judge_scores: dict[str, float] = Field(default_factory=dict)
    skill_score: float = 0.0
    selected: bool = False
    reason: str = ''

class SelectedReference(BaseModel):
    knowledge_unit: dict[str, Any] = Field(default_factory=dict)
    reference_id: str
    skill_name: str
    category: str
    knowledge_category: str = 'unknown'
    artifact_type: str = 'knowledge_component'
    representation_form: str = 'source'
    score: float = 0.0
    similarity: float | None = None
    final_score: float | None = None
    threshold: float | None = None
    passed_threshold: bool = True
    forced_keep: bool = False
    rerank_bonus: float = 0.0
    structural_trigger: str = ''
    text: str
    text_preview: str = ''
    reason: str = ''

class FiveElementFormulation(BaseModel):
    sets: str = ''
    parameters: str = ''
    decision_variables: str = ''
    objective_function: str = ''
    constraints: str = ''
    fef_text: str = ''
    modeling_records: dict[str, Any] = Field(default_factory=dict)

class ExecutionResult(BaseModel):
    solver_record: dict[str, Any] = Field(default_factory=dict)
    code_executable: bool
    solver_status: str = 'unknown'
    solver_status_normalized: str = 'unknown'
    stdout: str = ''
    stderr: str = ''
    returncode: int | None = None
    objective_value: float | None = None
    optimality_gap: float | None = None
    variable_values: dict[str, float] = Field(default_factory=dict)
    objective_parsed: bool = False
    objective_match: bool = False
    pipeline_success: bool = False
    solution_success: bool = False
    strict_success: bool = False
