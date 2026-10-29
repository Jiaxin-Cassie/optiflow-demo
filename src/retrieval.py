"""Small bilingual lexical retriever for the product's domain skill catalog."""
from collections import Counter
import math
import re


ALIASES = {
    "生产": "production planning capacity linear integer", "工厂": "manufacturing production",
    "利润": "profit maximize objective", "成本": "cost minimize objective", "预算": "budget allocation",
    "资源": "resource capacity allocation", "工时": "labor machine capacity", "机器": "machine capacity",
    "人工": "labor workforce", "排班": "workforce scheduling integer demand", "客服": "staff workforce",
    "运输": "transportation supply demand flow", "库存": "inventory balance multi period",
    "上限": "upper bound capacity", "不能超过": "upper bound", "至少": "lower bound demand",
    "整数": "integer domain", "分配": "allocation assignment", "线性": "linear programming",
}
STOPWORDS = {"the", "and", "for", "with", "from", "this", "that", "are", "when", "only", "must"}


def tokens(text):
    text = str(text).lower()
    expanded = text + " " + " ".join(value for key, value in ALIASES.items() if key in text)
    words = [w for w in re.findall(r"[a-z][a-z0-9_]+", expanded) if w not in STOPWORDS]
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(phrase[i:i + 2] for i in range(len(phrase) - 1))
    return Counter(words)


def similarity(query, document):
    left, right = tokens(query), tokens(document)
    numerator = sum(value * right.get(key, 0) for key, value in left.items())
    denominator = math.sqrt(sum(x * x for x in left.values()) * sum(x * x for x in right.values()))
    return numerator / denominator if denominator else 0.0
