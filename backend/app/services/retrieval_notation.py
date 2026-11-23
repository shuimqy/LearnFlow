import re

RULE_ID = re.compile(
    r"(?<![A-Za-z0-9_])([EI])(?:\s*_\s*(?:\{\s*(\d{1,3})\s*\}|(\d{1,3}))"
    r"|\s*(\d{1,3}))(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
RULE_ID_STYLE = re.compile(r"\\(?:mathrm|text|mathbf)\s*\{\s*([EI])\s*\}")
TEX_OPERATORS = {
    "downarrow": "↓",
    "uparrow": "↑",
    "nrightarrow": "↛",
    "oplus": "⊕",
    "Leftrightarrow": "⇔",
    "Longleftrightarrow": "⇔",
    "iff": "⇔",
    "equiv": "≡",
    "Rightarrow": "⇒",
    "Longrightarrow": "⇒",
    "implies": "⇒",
}
OPERATOR_NAMES = {
    "↓": re.compile(r"或非|\bNOR\b", re.IGNORECASE),
    "↑": re.compile(r"与非|\bNAND\b", re.IGNORECASE),
    "↛": re.compile(r"条件否定"),
    "⊕": re.compile(r"异或|\bXOR\b", re.IGNORECASE),
}
OPERATOR_DEFINITION = re.compile(
    r"(?:^|[,，;；:：⇔$])\s*([A-Za-z])\s*([↓↑↛⊕])\s*([A-Za-z])\s*[⇔↔≡=]"
)
DEFINITION_INTENT = re.compile(r"定义|等价[于为]|怎么|如何|怎样|写成|表示什么|是什么|什么意思|含义")
EXERCISE_REFERENCE = re.compile(r"习题|例\s*\d|第\s*[（(]?[a-z\d]+[）)]\s*问", re.IGNORECASE)


def normalize_notation(text: str) -> str:
    text = RULE_ID_STYLE.sub(r"\1", text)
    text = re.sub(r"\\not\s*\\(?:to|rightarrow)\b", "↛", text)
    return re.sub(r"\\([A-Za-z]+)", lambda match: TEX_OPERATORS.get(match[1], match[0]), text)


def rule_id(match: re.Match[str]) -> str:
    return match[1].upper() + next(number for number in match.groups()[1:] if number is not None)


def question_notation(question: str) -> tuple[set[str], set[str]]:
    text = normalize_notation(question)
    rules = {rule_id(match) for match in RULE_ID.finditer(text)}
    operators = set()
    if DEFINITION_INTENT.search(text) and not EXERCISE_REFERENCE.search(text):
        operators = {
            symbol for symbol, name in OPERATOR_NAMES.items() if symbol in text or name.search(text)
        }
    return rules, operators


def notation_score(text: str, rules: set[str], operators: set[str]) -> tuple[int, int]:
    matched_rules, matched_operators = set(), set()
    for line in normalize_notation(text).splitlines():
        if rules and line.lstrip().startswith("|"):
            formula_cells, _, reference = line.strip().strip("|").rpartition("|")
            match = RULE_ID.fullmatch(reference.strip(" \t$"))
            if match and any(mark in formula_cells for mark in "⇔↔≡⇒"):
                matched_rules.add(rule_id(match))
        if operators:
            matched_operators.update(
                symbol for left, symbol, right in OPERATOR_DEFINITION.findall(line) if left != right
            )
    return len(rules & matched_rules), len(operators & matched_operators)
