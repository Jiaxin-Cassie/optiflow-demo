"""Retrieve domain skills with an optional bounded model selection step."""
from src.knowledge_delivery import norm_category
from src.prompts import SKILL_JUDGE_SYSTEM_PROMPT, SKILL_JUDGE_USER_PROMPT
from src.retrieval import similarity
from src.schemas import ActivatedSkill, SkillJudgeRecord
from src.utils import compact_text, extract_json_object, safe_json_dumps


class SkillRouterAgent:
    def __init__(self, config, llm_client=None):
        self.config = config
        self.llm_client = llm_client

    def route(self, problem, profile, skills):
        query = problem.problem_text + "\n" + safe_json_dumps(profile.model_dump())
        scored = []
        for skill in skills:
            copied = skill.model_copy(deep=True)
            copied.metadata_score = similarity(query, " ".join((skill.name, skill.description, skill.body)))
            copied.metadata_components = {"lexical_similarity": copied.metadata_score, "retriever": "bilingual_lexical"}
            scored.append(copied)
        scored.sort(key=lambda skill: (-skill.metadata_score, skill.name))
        candidate_limit = max(1, int(getattr(self.config, "max_candidate_skills", 6)))
        candidates = []
        for category in ("K1", "K2", "K3"):
            best = next((s for s in scored if norm_category(s.category) == category and s.metadata_score > 0), None)
            if best is not None and len(candidates) < candidate_limit:
                candidates.append(best)
        names = {s.name for s in candidates}
        for skill in scored:
            if len(candidates) >= candidate_limit:
                break
            if skill.name not in names and skill.metadata_score > 0:
                candidates.append(skill)
                names.add(skill.name)
        if not candidates:
            return [], [], []
        limit = max(1, int(getattr(self.config, "max_activated_skills", 4)))
        chosen = [s.name for s in candidates[:limit]]
        reason = "规则检索：词项相似度与业务词映射"
        if self.llm_client is not None and getattr(self.config, "use_llm_skill_judge", True):
            cards = [{"id": s.name, "category": s.category,
                      "description": compact_text(s.description, 320), "use_when": compact_text(s.use_when, 320),
                      "avoid_when": compact_text(s.do_not_use_when, 160)} for s in candidates]
            try:
                answer = extract_json_object(self.llm_client.chat([
                    {"role": "system", "content": SKILL_JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": SKILL_JUDGE_USER_PROMPT.format(
                        problem_text=problem.problem_text, problem_profile=safe_json_dumps(profile.model_dump()),
                        candidate_skills=safe_json_dumps(cards), max_activated_skills=limit)},
                ], agent_name="SkillJudgeAgent", max_tokens=1000))
                rows = answer.get("selected")
                if not isinstance(rows, list):
                    raise ValueError("Invalid skill selection")
                chosen = list(dict.fromkeys(row["id"] for row in rows
                                           if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] in names))[:limit]
                reason = "业务相关性筛选：模型选择候选 Skill"
            except Exception:
                reason = "规则检索降级：模型筛选暂不可用，使用已记录的候选排序"
        records = [SkillJudgeRecord(name=s.name, category=s.category, description=s.description,
                                   metadata_score=s.metadata_score, selected=s.name in chosen, reason=reason) for s in candidates]
        activated = [ActivatedSkill(name=s.name, category=s.category, description=s.description,
                                    score=s.metadata_score, metadata_score=s.metadata_score,
                                    metadata_components=s.metadata_components, selected=True,
                                    references=s.references, reason=reason) for s in candidates if s.name in chosen]
        return candidates, records, activated
