"""Score retrieved evidence per query and aggregate Hit@1 / Evidence Hit@3."""
import re
import unicodedata
from collections import defaultdict
from typing import Any


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().casefold()


def gold_evidence(question: dict[str, Any]) -> list[dict[str, Any]]:
    """Primary gold plus documented alternatives, each as {source_id, page, evidence_quote}."""
    primary = {"source_id": question["gold_source_id"], "page": question["gold_page"],
               "evidence_quote": question["evidence_quote"]}
    return [primary, *question.get("alt_gold", [])]


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """A retrieved chunk is a hit when it comes from a gold source/article AND contains the
    whole evidence quote of that gold entry (whitespace/case-insensitive).

    Coherence and grounding are not derived here; they are labelled by hand.
    """
    golds = gold_evidence(question)
    ranked = []
    for rank, hit in enumerate(hits, start=1):
        meta = hit["metadata"]
        text = norm(hit["text"])
        same_unit = [g for g in golds if meta["document_id"] == g["source_id"] and meta["page"] == g["page"]]
        matched = next((g for g in same_unit if norm(g["evidence_quote"]) in text), None)
        ranked.append({
            "rank": rank,
            "chunk_id": hit["chunk_id"],
            "score": round(hit["score"], 4),
            "document_id": meta["document_id"],
            "page": meta["page"],
            "year": meta.get("year"),
            "article_title": meta.get("article_title"),
            "gold_unit": bool(same_unit),
            "evidence_hit": matched is not None,
            "metadata": meta,
            "text": hit["text"],
        })

    flags = [r["evidence_hit"] for r in ranked]
    trace = {
        "id": question["id"],
        "split": question["split"],
        "type": question.get("type"),
        "question": question["question"],
        "expected_answer": question["expected_answer"],
        "filter": question.get("filter"),
        "gold": golds,
        "hit_at_1": bool(flags[:1] and flags[0]),
        "hit_at_3": any(flags[:3]),
        "gold_unit_at_3": any(r["gold_unit"] for r in ranked[:3]),
        "first_hit_rank": next((r["rank"] for r in ranked if r["evidence_hit"]), None),
        "hits": ranked,
    }
    # gold article retrieved but no single chunk holds the whole quote
    trace["evidence_split"] = trace["gold_unit_at_3"] and not trace["hit_at_3"]
    return trace


def filter_compliant(trace: dict[str, Any]) -> bool | None:
    flt = trace.get("filter")
    if not flt:
        return None
    return all(all(h["metadata"].get(k) == v for k, v in flt.items()) for h in trace["hits"][:3])


def summarize(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in traces:
        groups[(t["strategy"], t["split"])].append(t)
    rows = []
    for (strategy, split), items in sorted(groups.items()):
        n = len(items)
        with_filter = [t for t in items if t.get("filter")]
        hit1 = sum(t["hit_at_1"] for t in items)
        hit3 = sum(t["hit_at_3"] for t in items)
        rows.append({
            "strategy": strategy,
            "split": split,
            "N": n,
            "hit_at_1": hit1,
            "hit_at_3": hit3,
            "hit_at_1_rate": round(hit1 / n, 3),
            "hit_at_3_rate": round(hit3 / n, 3),
            "gold_unit_at_3": sum(t["gold_unit_at_3"] for t in items),
            "evidence_split": sum(t["evidence_split"] for t in items),
            "filter_questions": len(with_filter),
            "filter_hit_at_3": sum(t["hit_at_3"] for t in with_filter),
            "filter_compliant": sum(bool(filter_compliant(t)) for t in with_filter),
        })
    return rows
