"""Small text, JSON and filesystem helpers used by the product agents."""
import json
import re
from pathlib import Path
from typing import Any

def ensure_dir(path: str | Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)

def remove_think_blocks(text: str) -> str:
    return re.sub('<think>.*?</think>', '', text or '', flags=re.DOTALL | re.IGNORECASE).strip()

def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = remove_think_blocks(text)
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    match = re.search('\\{.*\\}', cleaned, flags=re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}

def extract_python_code(text: str) -> str:
    cleaned = remove_think_blocks(text)
    match = re.search('```python\\s*(.*?)```', cleaned, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search('```\\s*(.*?)```', cleaned, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return cleaned.strip()

def safe_json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=True, indent=2, default=str)

def estimate_tokens(text: str) -> int:
    return max(1, int(len(text or '') / 4))

def compact_text(text: str, max_chars: int) -> str:
    text = (text or '').strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    marker = '\n...[middle omitted for token control]...\n'
    remaining = max(0, max_chars - len(marker))
    head = remaining * 2 // 3
    tail = remaining - head
    return text[:head].rstrip() + marker + text[-tail:].lstrip()

def compact_reference_text(text: str, max_chars: int) -> str:
    headings = ('Use When', 'Algebraic Template', 'Canonical Template', 'Modeling Rule', 'Common Wrong Formulation', 'Common Errors', 'Corrected Formulation', 'Do Not Use When', 'Worked Example')
    sections = []
    for heading in headings:
        match = re.search(f'##\\s+{re.escape(heading)}\\s*(.*?)(?=\\n##\\s+|\\Z)', text or '', flags=re.DOTALL | re.IGNORECASE)
        if match and match.group(1).strip():
            sections.append(f'## {heading}\n{match.group(1).strip()}')
    compacted = '\n\n'.join(sections) if sections else text
    return compact_text(compacted, max_chars)
