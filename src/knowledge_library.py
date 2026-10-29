"""Load and validate OptiFlow's reusable modeling skill catalog."""
import hashlib
import json
from pathlib import Path
from collections import Counter
from src.schemas import ReferenceKnowledge, SkillMetadata
CATEGORIES = {'K1': 'K1_Modeling_Type', 'K2': 'K2_Modeling_Technique', 'K3': 'K3_Programming_Solver'}
SEMANTIC_FORMS = ('declarative', 'formula', 'procedural', 'example')
GROUPS = {f'K2-{letter}' for letter in 'ABCDEF'}

def render_unit(unit, form='source'):
    """Render a catalog rule together with its application conditions and limits."""
    forms = unit['forms']
    if unit['category'] == 'K2' and unit.get('interpretation'):
        selected_form = 'formula' if form == 'source' else form
        if selected_form not in SEMANTIC_FORMS:
            raise ValueError(f'Unknown knowledge expression: {form}')
        return f"{unit['title']}\nWhen: {unit['applies']}\nMeaning: {unit['interpretation']}\nContent: {forms[selected_form]}\nBoundary: {unit['boundary']}"
    core = forms['formula'] if unit['category'] == 'K2' else forms['declarative']
    prefix = f"{unit['title']}\nWhen: {unit['applies']}"
    boundary = f"Boundary: {unit['boundary']}"
    application = ''.join((f'\n{label}: {unit[key]}' for (key, label) in (('application', 'Apply'), ('check', 'Check')) if unit.get(key)))
    if unit['category'] != 'K2' or form in ('source', 'formula'):
        return f'{prefix}\nRule: {core}\n{boundary}{application}'
    if form not in SEMANTIC_FORMS:
        raise ValueError(f'Unknown knowledge expression: {form}')
    labels = {'declarative': 'Explanation', 'procedural': 'Procedure', 'example': 'Illustration'}
    return f'{prefix}\n{labels[form]}: {forms[form]}\nRule: {core}\n{boundary}{application}'

def read_library(root='skill_library', extensions=()):
    path = Path(root)
    path = path if path.is_file() else path / 'knowledge.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    validate_library(data)
    if not extensions:
        return (data, path)
    components = [{'path': str(path), 'library_version': data['library_version'], 'knowledge_ids': [u['knowledge_id'] for u in data['units']]}]
    visited = {path.resolve()}
    for extension in extensions:
        (extra, extra_path) = read_library(extension)
        if extra_path.resolve() in visited:
            raise ValueError('Knowledge library specified more than once: ' + str(extra_path))
        visited.add(extra_path.resolve())
        if extra['taxonomy'] != data['taxonomy']:
            raise ValueError('Extension taxonomy must match the base library')
        for (key, record) in extra['sources'].items():
            if key in data['sources'] and data['sources'][key] != record:
                raise ValueError('Conflicting knowledge provenance: ' + key)
            data['sources'][key] = record
        data['units'].extend(extra['units'])
        data['scope'] += ' Extension: ' + extra['scope']
        components.append({'path': str(extra_path), 'library_version': extra['library_version'], 'knowledge_ids': [u['knowledge_id'] for u in extra['units']]})
    data['library_version'] = '+'.join((c['library_version'] for c in components))
    data['components'] = components
    validate_library(data)
    return (data, path)

def validate_library(data):
    if data.get('schema_version') != 3 or data.get('counting_unit') != 'knowledge_id':
        raise ValueError('Expected canonical knowledge schema v3')
    (seen, cores) = (set(), set())
    units = data.get('units', [])
    if not units:
        raise ValueError('Knowledge library is empty')
    for unit in units:
        for key in ('knowledge_id', 'title', 'category', 'group', 'applies', 'boundary', 'forms', 'sources'):
            if not unit.get(key):
                raise ValueError(f'Missing {key} in knowledge unit')
        uid = unit['knowledge_id']
        if uid in seen or not uid.startswith(unit['category'].lower() + '.'):
            raise ValueError(f'Duplicate or invalid knowledge ID: {uid}')
        seen.add(uid)
        if unit['category'] not in CATEGORIES:
            raise ValueError(f'Unknown category in {uid}')
        if unit['category'] == 'K2' and unit['group'] not in GROUPS:
            raise ValueError(f'Unknown K2 group in {uid}')
        if data.get('operational_protocol') == 'shared_application_checks_v1' and unit['category'] == 'K2' and (unit.get('knowledge_scope', 'general') == 'general'):
            for key in ('application', 'check'):
                if not isinstance(unit.get(key), str) or not unit[key].strip():
                    raise ValueError(f'Missing {key} in operational knowledge unit {uid}')
        if data.get('operational_protocol') == 'aligned_knowledge_views_v2' and unit['category'] == 'K2' and (unit.get('knowledge_scope', 'general') == 'general'):
            if not isinstance(unit.get('interpretation'), str) or not unit['interpretation'].strip():
                raise ValueError(f'Missing interpretation in aligned knowledge unit {uid}')
            if len(set((unit['forms'].get(f) for f in SEMANTIC_FORMS))) != len(SEMANTIC_FORMS):
                raise ValueError(f'Aligned knowledge views must be distinct: {uid}')
        if unit.get('knowledge_scope', 'general') not in ('general', 'uncertainty'):
            raise ValueError('Invalid knowledge scope: ' + uid)
        required = SEMANTIC_FORMS if unit['category'] == 'K2' else ('declarative',)
        for form in required:
            if not isinstance(unit['forms'].get(form), str) or not unit['forms'][form].strip():
                raise ValueError(f'Missing {form} in {uid}')
        if any((s not in data['sources'] for s in unit['sources'])):
            raise ValueError(f'Unknown provenance source in {uid}')
        core = unit['forms'].get('formula', unit['forms']['declarative'])
        normalized = ' '.join(core.casefold().split())
        if normalized in cores:
            raise ValueError(f'Duplicate core rule: {uid}')
        cores.add(normalized)
    return {'library_version': data['library_version'], 'counting_unit': 'knowledge_id', 'unit_count': len(units), 'category_counts': dict(Counter((u['category'] for u in units))), 'k2_group_counts': dict(Counter((u['group'] for u in units if u['category'] == 'K2'))), 'source_payload_characters': sum((len(render_unit(u)) for u in units)), 'scope_counts': dict(Counter((u.get('knowledge_scope', 'general') for u in units))), 'expert_review_status': 'not_independently_expert_reviewed', 'validation_scope': 'schema, IDs, exact duplicate cores, provenance and shared-core retention; not semantic proof'}

def load_knowledge(root='skill_library', extensions=()):
    (data, path) = read_library(root, extensions)
    origins = {uid: c for c in data.get('components', []) for uid in c['knowledge_ids']}
    result = []
    for item in data['units']:
        unit = dict(item)
        unit['source_records'] = {key: data['sources'][key] for key in item['sources']}
        unit['library_version'] = data['library_version']
        origin = origins.get(item['knowledge_id'])
        source_path = origin['path'] if origin else str(path)
        if origin:
            unit['component_library_version'] = origin['library_version']
        unit['taxonomy_definition'] = data['taxonomy'][item['category']]
        unit['scope'] = data['scope']
        (uid, category) = (unit['knowledge_id'], CATEGORIES[unit['category']])
        text = render_unit(unit)
        ref = ReferenceKnowledge(reference_id=uid, skill_name=uid, category=category, knowledge_category=unit['category'], artifact_type='knowledge_unit', representation_form='source', path=source_path, source_skill_path=source_path, text=text, knowledge_unit=unit)
        result.append(SkillMetadata(name=uid, category=category, description=unit['applies'], path=source_path, body=text, knowledge_category=unit['category'], artifact_type='knowledge_unit', representation_form='source', use_when=unit['applies'], do_not_use_when=unit['boundary'], references=[ref], knowledge_unit=unit))
    return result

def unit_fingerprint(unit):
    return hashlib.sha256(json.dumps(unit, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
