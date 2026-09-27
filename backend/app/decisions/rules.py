"""Deterministic, evidence-bound decision rules.

Thresholds are never hard-coded: every rule reads its requirement from a sentence found in the
organisation's own indexed chunks. If the required policy sentences are absent, the rule reports
missing evidence instead of deciding.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.kb.index import IndexedChunk
from app.retrieval.text import sentences


@dataclass(frozen=True)
class Span:
    chunk: IndexedChunk
    quote: str


@dataclass
class Check:
    id: str
    label: str
    requirement: str
    result: bool | None
    observed: str | None
    spans: list[Span]


@dataclass
class RuleOutcome:
    rule_set: str
    category: Literal["multi_condition", "policy"]
    verdict: Literal["eligible", "not_eligible", "needs_info", "required", "not_required"]
    checks: list[Check]
    missing_fields: list[str]
    answer: str
    follow_up_question: str | None = None
    notes: list[Span] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round(sum(1 for c in self.checks if c.result) / len(self.checks), 3)


@dataclass(frozen=True)
class MissingEvidence:
    rule_set: str
    missing: list[str]


@dataclass(frozen=True)
class Conversation:
    question: str
    user_text: str
    pending_field: str | None

    @property
    def lowered(self) -> str:
        return self.user_text.lower()


def find_span(chunks: Sequence[IndexedChunk], pattern: str) -> tuple[Span, re.Match[str]] | None:
    expression = re.compile(pattern, re.IGNORECASE)
    for chunk in chunks:
        for sentence in sentences(chunk.text):
            match = expression.search(sentence)
            if match:
                return Span(chunk, sentence), match
    return None


def number(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def first_group(text: str, patterns: Sequence[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def bare_number(conversation: Conversation, field_name: str) -> str | None:
    if conversation.pending_field != field_name:
        return None
    match = re.fullmatch(
        r"\s*(?:it is |it's |my \w+ is )?(\d+(?:\.\d+)?)\s*\.?\s*", conversation.question, re.I
    )
    return match.group(1) if match else None


def verdict_of(checks: Sequence[Check]) -> Literal["eligible", "not_eligible", "needs_info"]:
    if any(c.result is False for c in checks):
        return "not_eligible"
    if any(c.result is None for c in checks):
        return "needs_info"
    return "eligible"


def fmt(value: Decimal) -> str:
    return format(value.normalize(), "f") if value == value.to_integral() else str(value)


ELIGIBILITY_INTENT = r"\b(eligib\w*|qualify|can i|could i|am i|do i meet|may i|allowed)\b"
ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "1st": 1,
    "2nd": 2,
    "3rd": 3,
    "4th": 4,
    "5th": 5,
}
FOLLOW_UPS = {
    "gpa": "What is your GPA on the 4.00 scale?",
    "year": "Which year of study are you enrolled in?",
    "existing_scholarships": "Do you currently hold any other scholarships (for example sports, "
    "merit, or need-based), or none?",
    "tenure_months": "How many completed months of service do you have?",
    "rating": "What is your latest performance rating on the 1-to-5 scale?",
    "role": "What is your job role?",
}


def follow_up(missing: Sequence[str]) -> str | None:
    return " ".join(FOLLOW_UPS[name] for name in missing) or None


def summarize(
    title: str, outcome_verdict: str, checks: Sequence[Check], missing: Sequence[str]
) -> str:
    wording = {
        "eligible": "Eligible",
        "not_eligible": "Not eligible",
        "needs_info": "More information needed",
    }
    parts = [f"{wording[outcome_verdict]} for {title}."]
    for check in checks:
        state = {True: "met", False: "NOT met", None: "unknown"}[check.result]
        observed = f" (you: {check.observed})" if check.observed else ""
        parts.append(f"{check.label}: {state} - requirement: {check.requirement}{observed}.")
    if outcome_verdict == "not_eligible":
        parts.append("All conditions must hold, so one failed condition makes you ineligible.")
    if missing:
        parts.append(follow_up(missing) or "")
    return " ".join(part for part in parts if part)


def scholarship(
    conv: Conversation, chunks: Sequence[IndexedChunk]
) -> RuleOutcome | MissingEvidence | None:
    text = conv.lowered
    if not re.search(r"merit (scholarship|funding|award)", text) or not re.search(
        ELIGIBILITY_INTENT + r"|\b(get|receive)\b", text
    ):
        return None
    year_ev = find_span(chunks, r"enrolled in year (\d+) or higher")
    gpa_ev = find_span(chunks, r"GPA of at least (\d\.\d+)")
    stack_ev = find_span(
        chunks, r"cannot be combined with other scholarships, except need-based awards"
    )
    missing = [
        n
        for n, ev in (("year rule", year_ev), ("GPA rule", gpa_ev), ("stacking rule", stack_ev))
        if ev is None
    ]
    if year_ev is None or gpa_ev is None or stack_ev is None:
        return MissingEvidence("merit_scholarship_eligibility", missing)
    sports_ev = find_span(
        chunks, r"Sports scholarships and other merit scholarships are not allowed"
    )
    mixed_ev = find_span(
        chunks, r"both a sports scholarship and a need-based award does not satisfy"
    )

    year_value = first_group(
        text,
        [
            r"\byear (?:is )?(\d)\b",
            r"\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th)[- ]year\b",
        ],
    )
    year = None if year_value is None else ORDINALS.get(year_value.lower()) or int(year_value)
    gpa = number(
        first_group(
            text,
            [
                r"\bgpa\b(?: is| of)?(?: exactly)?\s*(\d(?:\.\d+)?)",
                r"(\d\.\d+)\s*(?:/\s*4(?:\.0+)?\s*)?gpa",
            ],
        )
        or bare_number(conv, "gpa")
    )

    scrubbed = re.sub(r"(the |this )?merit scholarship", " ", text)
    sports = "sport" in scrubbed and "scholarship" in scrubbed
    other_merit = bool(re.search(r"\b(another|other|existing) merit (scholarship|award)", text))
    need = bool(re.search(r"need[- ]based", scrubbed))
    none = bool(
        re.search(
            r"\bno (existing |other )?(scholarships?|awards?)\b|\bnone\b"
            r"|without (any )?scholarships?"
            r"|(don't|do not) (have|hold) any (other )?scholarships?",
            scrubbed,
        )
    )

    year_req, gpa_req = int(year_ev[1].group(1)), Decimal(gpa_ev[1].group(1))
    stacking_spans = [stack_ev[0]] + (
        [sports_ev[0]] if sports_ev and (sports or other_merit) else []
    )
    if sports and need and mixed_ev:
        stacking_spans.append(mixed_ev[0])
    if sports or other_merit:
        stacking, held = (
            False,
            ", ".join(
                x
                for x, f in (
                    ("sports scholarship", sports),
                    ("other merit scholarship", other_merit),
                    ("need-based award", need),
                )
                if f
            ),
        )
    elif need:
        stacking, held = True, "need-based award only"
    elif none:
        stacking, held = True, "no existing scholarships"
    else:
        stacking, held = None, None
    checks = [
        Check(
            "year_met",
            "Year of study",
            f"year {year_req} or higher",
            None if year is None else year >= year_req,
            None if year is None else f"year {year}",
            [year_ev[0]],
        ),
        Check(
            "gpa_met",
            "GPA",
            f"at least {gpa_ev[1].group(1)} on a 4.00 scale",
            None if gpa is None else gpa >= gpa_req,
            None if gpa is None else fmt(gpa),
            [gpa_ev[0]],
        ),
        Check(
            "stacking_met",
            "Scholarship stacking",
            "only need-based existing scholarships (or none)",
            stacking,
            held,
            stacking_spans,
        ),
    ]
    missing_fields = [
        name
        for name, check in zip(("year", "gpa", "existing_scholarships"), checks, strict=True)
        if check.result is None
    ]
    verdict = verdict_of(checks)
    if verdict != "needs_info":
        missing_fields = []
    return RuleOutcome(
        "merit_scholarship_eligibility",
        "multi_condition",
        verdict,
        checks,
        missing_fields,
        summarize("the Merit Scholarship", verdict, checks, missing_fields),
        follow_up(missing_fields),
    )


def singular(role: str) -> str:
    role = role.strip().lower()
    return role[:-1] if role.endswith("s") else role


def role_list(fragment: str) -> list[str]:
    return [
        singular(part) for part in re.split(r",\s*(?:and\s+)?|\s+and\s+", fragment) if part.strip()
    ]


def remote_work(
    conv: Conversation, chunks: Sequence[IndexedChunk]
) -> RuleOutcome | MissingEvidence | None:
    text = conv.lowered
    if "remote" not in text or not re.search(ELIGIBILITY_INTENT + r"|\brequest\b", text):
        return None
    tenure_ev = find_span(chunks, r"at least (\d+) completed months of service")
    rating_ev = find_span(chunks, r"performance rating of at least (\d(?:\.\d+)?)")
    onsite_ev = find_span(chunks, r"^(.+?) are on-site roles")
    if tenure_ev is None or rating_ev is None or onsite_ev is None:
        return MissingEvidence(
            "remote_work_eligibility",
            [
                n
                for n, e in (
                    ("tenure rule", tenure_ev),
                    ("rating rule", rating_ev),
                    ("on-site role list", onsite_ev),
                )
                if e is None
            ],
        )
    allowed_ev = find_span(chunks, r"^(.+?) are not designated on-site roles")
    approval_ev = find_span(chunks, r"manager must approve")
    onsite = role_list(onsite_ev[1].group(1))
    allowed = role_list(allowed_ev[1].group(1)) if allowed_ev else []

    months = number(
        first_group(text, [r"(\d+(?:\.\d+)?)\s*(?:completed\s+)?months?"])
        or bare_number(conv, "tenure_months")
    )
    years = number(first_group(text, [r"(\d+(?:\.\d+)?)\s*years? of (?:service|experience)"]))
    if months is None and years is not None:
        months = years * 12
    rating = number(
        first_group(
            text,
            [
                r"rating (?:of |is )?(?:exactly )?(\d(?:\.\d+)?)",
                r"(\d(?:\.\d+)?)\s*(?:performance )?rating",
            ],
        )
        or bare_number(conv, "rating")
    )
    role = next(
        (r for r in onsite + allowed if re.search(r"\b" + re.escape(r) + r"s?\b", text)), None
    )
    role_spans = [onsite_ev[0]] + ([allowed_ev[0]] if allowed_ev and role in allowed else [])
    tenure_req, rating_req = Decimal(tenure_ev[1].group(1)), Decimal(rating_ev[1].group(1))
    checks = [
        Check(
            "tenure_met",
            "Service",
            f"at least {fmt(tenure_req)} completed months",
            None if months is None else months >= tenure_req,
            None if months is None else f"{fmt(months)} months",
            [tenure_ev[0]],
        ),
        Check(
            "rating_met",
            "Performance rating",
            f"at least {rating_ev[1].group(1)} on a 1-to-5 scale",
            None if rating is None else rating >= rating_req,
            None if rating is None else fmt(rating),
            [rating_ev[0]],
        ),
        Check(
            "role_met",
            "Role",
            "not a designated on-site role",
            None if role is None else role not in onsite,
            role,
            role_spans,
        ),
    ]
    verdict = verdict_of(checks)
    missing_fields = (
        [
            n
            for n, c in zip(("tenure_months", "rating", "role"), checks, strict=True)
            if c.result is None
        ]
        if verdict == "needs_info"
        else []
    )
    answer = summarize("requesting remote work", verdict, checks, missing_fields)
    notes: list[Span] = []
    if verdict == "eligible" and approval_ev:
        notes.append(approval_ev[0])
        answer += (
            " Eligibility does not approve a schedule: a manager must still approve"
            " your proposed remote-working days."
        )
    return RuleOutcome(
        "remote_work_eligibility",
        "multi_condition",
        verdict,
        checks,
        missing_fields,
        answer,
        follow_up(missing_fields),
        notes,
    )


def travel_approval(
    conv: Conversation, chunks: Sequence[IndexedChunk]
) -> RuleOutcome | MissingEvidence | None:
    text = conv.question.lower()
    amount = number(
        first_group(text, [r"(?:usd|\$)\s*(\d+(?:\.\d+)?)", r"(\d+(?:\.\d+)?)\s*(?:usd|dollars)"])
    )
    if amount is None or "approval" not in text or not re.search(r"expense|travel|claim", text):
        return None
    rule_ev = find_span(chunks, r"expense above USD (\d+(?:\.\d+)?) requires manager approval")
    if rule_ev is None:
        return MissingEvidence("travel_advance_approval", ["advance approval threshold"])
    threshold = Decimal(rule_ev[1].group(1))
    required = amount > threshold
    check = Check(
        "advance_approval_required",
        "Advance manager approval",
        f"required when a planned expense is above USD {fmt(threshold)}",
        required,
        f"USD {amount}",
        [rule_ev[0]],
    )
    answer = (
        f"{'Yes' if required else 'No'}. A planned expense of USD {amount} is "
        f"{'above' if required else 'not above'} the USD {fmt(threshold)} threshold, so advance "
        f"manager approval is {'required' if required else 'not required'} under the amount rule."
    )
    receipt_ev = find_span(chunks, r"receipt and business-purpose requirements")
    return RuleOutcome(
        "travel_advance_approval",
        "policy",
        "required" if required else "not_required",
        [check],
        [],
        answer,
        notes=[receipt_ev[0]] if receipt_ev and not required else [],
    )


RULES: tuple[
    Callable[[Conversation, Sequence[IndexedChunk]], RuleOutcome | MissingEvidence | None], ...
] = (
    scholarship,
    remote_work,
    travel_approval,
)


def evaluate(
    conv: Conversation, chunks: Sequence[IndexedChunk]
) -> RuleOutcome | MissingEvidence | None:
    for rule in RULES:
        outcome = rule(conv, chunks)
        if outcome is not None:
            return outcome
    return None


def classify(question: str) -> Literal["comparison", "procedural", "policy", "direct"]:
    text = question.lower()
    if re.search(r"\b(compare|comparison|versus|vs\.?|difference between)\b", text):
        return "comparison"
    if re.search(r"\b(walk me through|how do i|how can i|how to|steps?|procedure|process)\b", text):
        return "procedural"
    if re.search(r"\b(require|allowed|permitted|combined|policy|rule)\b", text):
        return "policy"
    return "direct"
