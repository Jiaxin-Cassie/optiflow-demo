"""Compatibility entry point; one canonical knowledge unit per selectable item."""
from src.knowledge_library import load_knowledge


def load_skills(skill_root="skill_library", extensions=()):
    return load_knowledge(skill_root, extensions)
