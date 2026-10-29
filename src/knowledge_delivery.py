"""Deliver relevant domain knowledge to each modeling stage."""
from src.utils import compact_reference_text, compact_text, safe_json_dumps

def norm_category(category):
    return str(category).split('_', 1)[0]

def stage_references(references, stage):
    categories = {'K1', 'K2'} if stage == 'formulation' else {'K3'}
    return [ref for ref in references or [] if norm_category(ref.category) in categories]

def reference_payload(references, config=None):
    compact = bool(getattr(config, 'compact_prompts', False))
    limit = int(getattr(config, 'max_reference_chars', 1800))
    rows = []
    for ref in references:
        text = ref.text
        if compact and getattr(ref, 'artifact_type', '') != 'knowledge_unit':
            text = (compact_text if ref.representation_form.startswith('F') else compact_reference_text)(text, limit)
        rows.append({'reference_id': ref.reference_id, 'skill_name': ref.skill_name, 'category': ref.category, 'representation_form': ref.representation_form, 'text': text})
    return rows
