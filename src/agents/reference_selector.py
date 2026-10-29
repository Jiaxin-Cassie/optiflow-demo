"""Deliver selected catalog cards to the formulation and code stages."""
from src.schemas import SelectedReference


class ReferenceSelectorAgent:
    def __init__(self, config):
        self.config = config

    def select(self, problem, profile, activated_skills):
        selected, seen = [], set()
        for skill in activated_skills:
            for ref in skill.references:
                if ref.reference_id in seen:
                    continue
                seen.add(ref.reference_id)
                selected.append(SelectedReference(
                    reference_id=ref.reference_id, skill_name=ref.skill_name, category=ref.category,
                    knowledge_category=ref.knowledge_category, artifact_type=ref.artifact_type,
                    representation_form=ref.representation_form, score=skill.score, text=ref.text,
                    text_preview=ref.text[:240], knowledge_unit=ref.knowledge_unit,
                    reason=skill.reason))
        return selected[:int(getattr(self.config, "max_references", 10))]
