from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from . import lexicon
from .contracts import CleanFeedback, ExtractedInsight
from .text import clean_clause, sentence_case, split_clauses, split_sentences, to_neutral_statement, tokenize


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insight_id(feedback_id: str, evidence: str, aspect: str | None, symptom: str | None) -> str:
    raw = f"{feedback_id}|{evidence}|{aspect}|{symptom}".encode("utf-8")
    return "IN-" + hashlib.sha1(raw).hexdigest()[:16]


def _title(aspect: lexicon.Aspect | None, symptom: lexicon.Symptom | None, intent: lexicon.Intent | None, statement: str) -> str:
    if aspect and symptom:
        return sentence_case(f"{aspect.label}: {symptom.label}")[:155]
    if aspect and intent:
        return sentence_case(f"{aspect.label}: {intent.label}")[:155]
    if aspect:
        return sentence_case(f"Reported issue in {aspect.label}")[:155]
    if symptom:
        return sentence_case(symptom.label)[:155]
    return sentence_case(statement)[:155] or "Reported customer issue"


def _statement(clause: str, aspect: lexicon.Aspect | None, symptom: lexicon.Symptom | None, intent: lexicon.Intent | None) -> str:
    neutral = to_neutral_statement(clause)
    words = tokenize(neutral)
    if len(words) >= 3:
        return neutral
    if aspect and symptom:
        return f"Customers report {symptom.label.lower()} in {aspect.label.lower()}."
    if aspect:
        return f"Customers report an issue in {aspect.label.lower()}."
    if symptom:
        return f"Customers report that {symptom.label.lower()}."
    if intent:
        return f"Customers cannot complete the task to {intent.label.lower()}."
    return neutral or "Customers report an unspecified issue."


def _is_problem(sentiment: str, symptom: lexicon.Symptom | None, reported_outcome: str) -> bool:
    if sentiment in ("negative", "mixed"):
        return True
    if symptom is not None and sentiment != "positive":
        return True
    return reported_outcome in ("blocked", "failed", "abandoned")


def extract_insights(record: CleanFeedback, model_id: str = "rules-v1") -> list[ExtractedInsight]:
    text = record.feedback_text_redacted
    global_context = f"{record.feedback_title} {text}"
    global_aspect = lexicon.best_entity(global_context, lexicon.ASPECTS)
    global_intent = lexicon.best_entity(global_context, lexicon.INTENTS)
    insights: list[ExtractedInsight] = []
    seen: set[tuple[str, str, str]] = set()

    for sentence_index, sentence in enumerate(split_sentences(text)):
        inherited_aspect = global_aspect if isinstance(global_aspect, lexicon.Aspect) else None
        inherited_intent = global_intent if isinstance(global_intent, lexicon.Intent) else None
        clauses = split_clauses(sentence.text, offset=sentence.start)
        for clause in clauses:
            evidence = clause.text.strip()
            cleaned = clean_clause(evidence)
            if len(tokenize(cleaned)) < 2:
                continue

            local_aspects = lexicon.match_entities(cleaned, lexicon.ASPECTS)
            local_intents = lexicon.match_entities(cleaned, lexicon.INTENTS)
            local_symptoms = lexicon.match_entities(cleaned, lexicon.SYMPTOMS)
            sentiment_label, sentiment_score = lexicon.sentiment(cleaned)
            reported_outcome = lexicon.outcome(cleaned)

            # Filler, emotion-only and generic preamble clauses are not evidence.
            # Require at least one local anchor in the clause itself.
            if not local_aspects and not local_intents and not local_symptoms:
                continue

            aspect = local_aspects[0][0] if local_aspects else None
            intent = local_intents[0][0] if local_intents else None
            symptom = local_symptoms[0][0] if local_symptoms else None

            # Reconcile the local aspect with the customer's primary task. This
            # prevents incidental words (for example "transaction reference")
            # from overriding the object being discussed (for example a statement).
            if intent is not None and intent.node_hint:
                intent_module = intent.node_hint.split(".")[0]
                if aspect is None or aspect.node_id.split(".")[0] != intent_module:
                    exact = [item for item, _ in local_aspects if item.node_id == intent.node_hint]
                    same_module = [
                        item for item, _ in local_aspects if item.node_id.split(".")[0] == intent_module
                    ]
                    if exact:
                        aspect = exact[0]
                    elif same_module:
                        aspect = same_module[0]
                    else:
                        aspect = None

            if aspect is None and symptom is not None and inherited_aspect is not None:
                if intent is None or inherited_aspect.node_id.split(".")[0] == (intent.node_hint or "").split(".")[0]:
                    aspect = inherited_aspect

            if intent is None and aspect is not None:
                intent = inherited_intent
                if intent is None:
                    intent = next((item for item in lexicon.INTENTS if item.node_hint == aspect.node_id), None)
            if aspect is not None:
                inherited_aspect = aspect
            if intent is not None:
                inherited_intent = intent

            # Skip pure filler/emotion clauses with no linguistic anchor.
            if aspect is None and symptom is None and intent is None:
                continue
            if len(tokenize(cleaned)) < 3 and not local_symptoms:
                continue

            is_problem = _is_problem(sentiment_label, symptom, reported_outcome)
            statement = _statement(cleaned, aspect, symptom, intent) if is_problem else None
            key = (evidence.lower(), aspect.key if aspect else "", symptom.key if symptom else "")
            if key in seen:
                continue
            seen.add(key)

            signal_count = sum(
                [aspect is not None, symptom is not None, intent is not None, sentiment_label != "neutral"]
            )
            confidence = min(0.95, 0.46 + 0.13 * signal_count + (0.06 if is_problem else 0.0))
            node_id = aspect.node_id if aspect else (intent.node_hint if intent else None)

            insights.append(
                ExtractedInsight(
                    insight_id=_insight_id(record.feedback_id, evidence, aspect.key if aspect else None, symptom.key if symptom else None),
                    feedback_id=record.feedback_id,
                    sentence_index=sentence_index,
                    customer_intent=intent.key if intent else None,
                    aspect=aspect.key if aspect else None,
                    journey_node_id=node_id,
                    reported_problem=statement,
                    reported_symptom=symptom.label if symptom else ("reported issue" if is_problem else None),
                    symptom_category=symptom.category if symptom else ("general" if is_problem else None),
                    sentiment=sentiment_label,  # type: ignore[arg-type]
                    sentiment_score=sentiment_score,
                    emotion=lexicon.emotion(cleaned, sentiment_label),
                    customer_effort=lexicon.effort(cleaned),  # type: ignore[arg-type]
                    reported_outcome=reported_outcome,  # type: ignore[arg-type]
                    evidence_span=evidence,
                    language=record.language or "en",
                    model_id=model_id,
                    extraction_timestamp=_now(),
                    extraction_method="rules",
                    confidence=round(confidence, 3),
                    is_problem=is_problem,
                )
            )

    # Guard: every evidence span must be an exact substring of the redacted source.
    return [item for item in insights if item.evidence_span in text]
