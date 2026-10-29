"""Parse the standard five-element modeling representation."""
import re
SECTION_TITLES = {'sets': '1\\.\\s*Sets\\s*/\\s*Indices', 'parameters': '2\\.\\s*Parameters', 'decision_variables': '3\\.\\s*Decision Variables', 'objective_function': '4\\.\\s*Objective Function', 'constraints': '5\\.\\s*Constraints'}
FIELD_SECTIONS = {'data_axes': 'sets', 'method_specification': 'parameters', 'data_construction': 'parameters', 'uncertainty_specification': 'parameters', 'missing_inputs': 'parameters', 'information_structure': 'decision_variables', 'objective_specification': 'objective_function', 'business_constraints': 'constraints', 'method_counterpart': 'constraints', 'reformulation_conditions': 'constraints', 'validation_checks': 'constraints'}

def extract_sections(text):
    header = '|'.join(SECTION_TITLES.values())
    result = {}
    for (key, title) in SECTION_TITLES.items():
        match = re.search(f'(?:^|\\n)\\s*{title}\\s*(.*?)(?=\\n\\s*(?:{header})\\s*|\\Z)', text, flags=re.DOTALL | re.IGNORECASE)
        result[key] = match.group(1).strip() if match else ''
    return result

def extract_modeling_records(sections):
    records = {}
    marker = re.compile('(?m)^\\s*\\[\\[([a-z_]+)\\]\\]\\s*')
    for (key, section) in FIELD_SECTIONS.items():
        text = sections.get(section, '')
        matches = list(marker.finditer(text))
        values = []
        for (i, match) in enumerate(matches):
            if match.group(1) == key:
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                values.append(text[match.end():end].strip())
        value = '\n'.join(values)
        if not value:
            status = 'not_reported'
        elif re.match('^NOT_APPLICABLE\\b', value, re.I):
            status = 'reported_not_applicable'
        elif re.match('^MISSING\\b', value, re.I):
            status = 'reported_missing'
        else:
            status = 'reported'
        records[key] = {'section': section, 'text': value, 'status': status, 'occurrences': len(values), 'correctness': 'not_assessed'}
    return records
