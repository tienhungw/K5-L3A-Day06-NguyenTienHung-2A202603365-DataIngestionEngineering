"""Day 06 pipeline. Run from starter/:

    python -m src.run prepare             # read + normalize sources, write units and manifest
    python -m src.run check-benchmark     # validate questions, verify every evidence quote
    python -m src.run ingest              # chunk, embed, store A and B (run again: nothing is duplicated)
    python -m src.run evaluate --split dev
    python -m src.run evaluate --split test
    python -m src.run audit               # export sheets for manual labelling
    python -m src.run audit-summary       # aggregate the manual labels
"""
import argparse
import csv
import hashlib
import json
import platform
import random
import statistics
import sys
import time
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from dotenv import load_dotenv

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
load_dotenv(STARTER / ".env")  # HF_HOME etc. must be set before the model is loaded

from .chunking import by_paragraph, fixed_size  # noqa: E402
from .evaluation import evaluate_query, filter_compliant, norm, summarize  # noqa: E402
from .ingestion import load_corpus  # noqa: E402
from .models import Chunk, DocumentPage  # noqa: E402

CONFIG = STARTER / "configs" / "strategies.json"
SOURCES = ROOT / "data" / "sources.json"
PROCESSED = ROOT / "data" / "processed"
UNITS = PROCESSED / "units.jsonl"
MANIFEST = ROOT / "data" / "manifest.json"
QUESTIONS = ROOT / "benchmark" / "questions.jsonl"
RESULTS = ROOT / "results"
AUDIT = RESULTS / "audit"

MIN_CONTENT_UNITS = 30
COHERENCE_SEED = 6
COHERENCE_SAMPLE = 10
COHERENCE_MIN_CHARS = 1000


# ---------------------------------------------------------------- helpers
def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def package_versions() -> dict:
    out = {"python": platform.python_version()}
    for name in ["sentence-transformers", "transformers", "torch", "chromadb", "pypdf", "olefile"]:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = None
    return out


def load_units() -> list[DocumentPage]:
    if not UNITS.exists():
        sys.exit("data/processed/units.jsonl not found: run `python -m src.run prepare` first.")
    return [DocumentPage(**row) for row in read_jsonl(UNITS)]


def load_embedder(cfg: dict):
    from .embeddings import E5Embedder
    emb = cfg["embedding"]
    return E5Embedder(emb["model"], revision=emb.get("revision"))


def open_store(cfg: dict, embedder):
    from .store import ChromaStore
    return ChromaStore(ROOT / cfg["vector_store"]["path"], embedder.model_name, embedder.dimensions)


def collections(cfg: dict) -> dict[str, dict]:
    """collection name -> chunking params (C shares B's collection)."""
    out = {}
    for key, s in cfg["strategies"].items():
        out.setdefault(s["collection"], {**s, "tag": key})
    return out


def make_chunks(units: list[DocumentPage], spec: dict) -> list[Chunk]:
    chunks = []
    for unit in units:
        if spec["chunking"] == "fixed":
            chunks.extend(fixed_size(unit, spec["size"], spec["overlap"], tag=spec["tag"]))
        elif spec["chunking"] == "paragraph":
            chunks.extend(by_paragraph(unit, spec["max_size"], tag=spec["tag"]))
        else:
            raise ValueError(f"unknown chunking {spec['chunking']}")
    return chunks


def length_stats(values: list[int]) -> dict:
    values = sorted(values)
    q = statistics.quantiles(values, n=10)
    return {"min": values[0], "p10": round(q[0]), "median": statistics.median(values),
            "mean": round(statistics.mean(values), 1), "p90": round(q[-1]), "max": values[-1],
            "total": sum(values)}


# ---------------------------------------------------------------- prepare
def cmd_prepare(_args) -> None:
    sources = read_json(SOURCES)
    units, logs, texts = load_corpus(sources, ROOT)
    for doc_id, text in texts.items():
        (PROCESSED / f"{doc_id}.txt").parent.mkdir(parents=True, exist_ok=True)
        (PROCESSED / f"{doc_id}.txt").write_text(text, encoding="utf-8")
    write_jsonl(UNITS, ({"document_id": u.document_id, "source": u.source, "page": u.page,
                         "text": u.text, "metadata": u.metadata} for u in units))

    manifest = {
        "generated_at": now(),
        "unit_rule": ("Nguồn là .doc và HTML không phân trang. Đơn vị truy vết là một Điều "
                      "(document_id + số Điều, lưu ở trường `page`). Chỉ tính các Điều từ Điều 1 "
                      "đến Điều cuối; loại phần quốc hiệu, căn cứ ban hành, dòng thông qua, chữ ký "
                      "và footer trang web. Ranh giới char_start/char_end tính trên "
                      "data/processed/<source_id>.txt (văn bản đã chuẩn hóa)."),
        "content_units": len(units),
        "content_chars": sum(len(u.text) for u in units),
        "equivalent_1500_char_units": sum(len(u.text) for u in units) // 1500,
        "sources": [],
    }
    for source, log in zip(sources, logs):
        doc_units = [u for u in units if u.document_id == source["source_id"]]
        manifest["sources"].append({
            **source,
            "sha256": log["sha256"],
            "normalized_text": f"data/processed/{source['source_id']}.txt",
            "content_units": len(doc_units),
            "content_chars": sum(len(u.text) for u in doc_units),
            "excluded_chars": sum(len(x) + 1 for x in log["excluded_preamble_lines"] + log["excluded_tail_lines"]),
            "units": [{"unit_id": u.metadata["unit_id"], "page": u.page,
                       "title": u.metadata["article_title"], "chapter": u.metadata["chapter"],
                       "char_start": u.metadata["char_start"], "char_end": u.metadata["char_end"],
                       "char_count": u.metadata["char_count"]} for u in doc_units],
        })
    write_json(MANIFEST, manifest)
    write_json(RESULTS / "ingest_log.json", {"generated_at": now(), "sources": logs})

    for log in logs:
        print(f"{log['source_id']}: {log['units']} articles, {log['unit_chars']:,} chars, "
              f"{log['chapters']} chapters, {log['sections']} sections, "
              f"warnings={len(log['warnings'])}, errors={len(log['errors'])}")
    print(f"total: {manifest['content_units']} units, {manifest['content_chars']:,} chars "
          f"(~{manifest['equivalent_1500_char_units']} units of 1500 chars)")
    if len(units) < MIN_CONTENT_UNITS:
        sys.exit(f"only {len(units)} content units (< {MIN_CONTENT_UNITS})")


# ---------------------------------------------------------------- benchmark check
REQUIRED = ["id", "split", "type", "question", "expected_answer", "gold_source_id",
            "gold_page", "evidence_quote"]


def cmd_check_benchmark(_args) -> None:
    from .evaluation import gold_evidence
    from .store import FILTER_FIELDS

    units = load_units()
    by_key = {(u.document_id, u.page): u for u in units}
    meta = {(u.document_id, u.page): {**u.metadata, "document_id": u.document_id} for u in units}
    questions = read_jsonl(QUESTIONS)
    errors, warnings, rows = [], [], []

    ids = [q.get("id") for q in questions]
    if len(set(ids)) != len(ids):
        errors.append("duplicate question ids")
    for q in questions:
        missing = [k for k in REQUIRED if q.get(k) in (None, "")]
        if missing:
            errors.append(f"{q.get('id')}: missing {missing}")
            continue
        if q["split"] not in ("dev", "test"):
            errors.append(f"{q['id']}: split must be dev or test")
        flt = q.get("filter")
        if flt:
            if set(flt) - FILTER_FIELDS:
                errors.append(f"{q['id']}: filter field not allowed {flt}")
            elif not any(all(m.get(k) == v for k, v in flt.items()) for m in meta.values()):
                errors.append(f"{q['id']}: filter value matches no unit {flt}")
        for g in gold_evidence(q):
            key = (g["source_id"], g["page"])
            unit = by_key.get(key)
            found = bool(unit) and norm(g["evidence_quote"]) in norm(unit.text)
            if not found:
                errors.append(f"{q['id']}: evidence not found in {g['source_id']} Điều {g['page']}")
            if flt and unit and not all(meta[key].get(k) == v for k, v in flt.items()):
                errors.append(f"{q['id']}: gold {g['source_id']} Điều {g['page']} violates filter {flt}")
            rows.append({"id": q["id"], "split": q["split"], "source_id": g["source_id"],
                         "page": g["page"], "evidence_found": found,
                         "evidence_chars": len(g["evidence_quote"])})
        listed = {(g["source_id"], g["page"]) for g in gold_evidence(q)}
        elsewhere = [u.metadata["unit_id"] for u in units
                     if (u.document_id, u.page) not in listed and norm(q["evidence_quote"]) in norm(u.text)]
        if elsewhere and not flt:
            warnings.append(f"{q['id']}: evidence also appears verbatim in {elsewhere}, not listed as gold")

    dev = [q for q in questions if q.get("split") == "dev"]
    test = [q for q in questions if q.get("split") == "test"]
    filt = [q for q in questions if q.get("filter")]
    if len(questions) < 20 or len(dev) < 15 or len(test) < 5:
        errors.append(f"need >=20 questions with >=15 dev / >=5 test, got {len(dev)}/{len(test)}")
    if len(filt) < 3 or not any(q["split"] == "test" for q in filt):
        errors.append("need >=3 filter questions with >=1 in test")

    report = {"checked_at": now(), "questions": len(questions), "dev": len(dev), "test": len(test),
              "filter_questions": len(filt), "filter_test": sum(q["split"] == "test" for q in filt),
              "types": {t: sum(q.get("type") == t for q in questions)
                        for t in sorted({q.get("type") for q in questions})},
              "errors": errors, "warnings": warnings, "evidence": rows}
    write_json(RESULTS / "benchmark_check.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "evidence"}, ensure_ascii=False, indent=2))
    if errors:
        sys.exit(1)


# ---------------------------------------------------------------- ingest
def meta_sha1(chunk: Chunk) -> str:
    meta = {k: v for k, v in chunk.metadata.items() if k != "meta_sha1"}
    meta.update(document_id=chunk.document_id, source=chunk.source, page=chunk.page)
    return hashlib.sha1(json.dumps(meta, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def sync_collection(store, embedder, name: str, chunks: list[Chunk]) -> dict:
    """Make the collection hold exactly `chunks`.

    Same id + same text + same metadata -> skipped; same text but new metadata -> metadata
    updated without re-embedding; new or changed text -> embedded and upserted; ids that
    no longer exist (article removed, document dropped, fewer chunks) -> deleted.
    """
    for c in chunks:
        c.metadata["meta_sha1"] = meta_sha1(c)
    store.create_schema(name)
    before = store.count(name)
    existing = store.existing(name)
    new_ids = {c.chunk_id for c in chunks}
    stale = [i for i in existing if i not in new_ids]
    embed, meta_only, unchanged = [], [], 0
    for c in chunks:
        old = existing.get(c.chunk_id)
        if old is None or old.get("text_sha1") != c.metadata["text_sha1"]:
            embed.append(c)
        elif old.get("meta_sha1") != c.metadata["meta_sha1"]:
            meta_only.append(c)
        else:
            unchanged += 1

    t1 = time.perf_counter()
    vectors = embedder.embed_documents([c.text for c in embed])
    t_embed = time.perf_counter() - t1
    t2 = time.perf_counter()
    if stale:
        store.delete(name, stale)
    if embed:
        store.upsert(name, embed, vectors)
    if meta_only:
        store.update_metadata(name, meta_only)
    t_store = time.perf_counter() - t2
    after = store.count(name)
    if after != len(chunks):
        raise RuntimeError(f"{name}: store has {after} items, expected {len(chunks)}")
    return {"count_before": before, "count_after": after, "embedded": len(embed),
            "metadata_updated": len(meta_only), "unchanged": unchanged, "deleted": len(stale),
            "time_s": {"embed": round(t_embed, 2), "store": round(t_store, 2)}}


def cmd_ingest(_args) -> None:
    cfg = read_json(CONFIG)
    units = load_units()
    t_load = time.perf_counter()
    embedder = load_embedder(cfg)
    model_load_s = time.perf_counter() - t_load
    store = open_store(cfg, embedder)
    run = {"started_at": now(), "model": embedder.model_name, "model_revision": embedder.resolved_revision,
           "dimensions": embedder.dimensions, "max_seq_length": embedder.max_seq_length,
           "model_load_s": round(model_load_s, 2), "versions": package_versions(),
           "machine": {"platform": platform.platform(), "processor": platform.processor()},
           "cost_usd": 0.0, "collections": {}}

    for name, spec in collections(cfg).items():
        t0 = time.perf_counter()
        chunks = make_chunks(units, spec)
        t_chunk = time.perf_counter() - t0
        sync = sync_collection(store, embedder, name, chunks)
        sync["time_s"] = {"chunk": round(t_chunk, 2), **sync["time_s"],
                          "total": round(t_chunk + sum(sync["time_s"].values()), 2)}
        tokens = embedder.token_counts([c.text for c in chunks])
        run["collections"][name] = {
            "strategies": [k for k, s in cfg["strategies"].items() if s["collection"] == name],
            "chunking": {k: spec[k] for k in ("chunking", "size", "overlap", "max_size") if k in spec},
            "chunk_count": len(chunks),
            "chunks_per_source": {d: sum(c.document_id == d for c in chunks)
                                  for d in sorted({c.document_id for c in chunks})},
            "chars": length_stats([len(c.text) for c in chunks]),
            "tokens": length_stats(tokens),
            "truncated_chunks": sum(t > embedder.max_seq_length for t in tokens),
            **sync,
        }
        print(f"{name}: {len(chunks)} chunks | before {sync['count_before']} -> after {sync['count_after']} | "
              f"embedded {sync['embedded']}, metadata updated {sync['metadata_updated']}, "
              f"unchanged {sync['unchanged']}, deleted {sync['deleted']} | embed {sync['time_s']['embed']}s")

    run["finished_at"] = now()
    history = RESULTS / "ingest_runs.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as f:
        f.write(json.dumps(run, ensure_ascii=False) + "\n")
    if all(c["embedded"] == c["chunk_count"] for c in run["collections"].values()):
        write_json(RESULTS / "ingest_stats.json", run)  # full build from an empty store = reference numbers


# ---------------------------------------------------------------- evaluate
def exact_top_k(collection, query_vector, k: int, where) -> list[str]:
    import numpy as np
    got = collection.get(where=where, include=["embeddings"])
    matrix = np.asarray(got["embeddings"], dtype=float)
    q = np.asarray(query_vector, dtype=float)
    sims = matrix @ q / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(q))
    return [got["ids"][i] for i in np.argsort(-sims)[:k]]


def cmd_evaluate(args) -> None:
    cfg = read_json(CONFIG)
    questions = [q for q in read_jsonl(QUESTIONS) if q["split"] == args.split]
    if not questions:
        sys.exit(f"no {args.split} questions")
    embedder = load_embedder(cfg)
    store = open_store(cfg, embedder)
    top_k = cfg["top_k"]

    t0 = time.perf_counter()
    qvecs = {q["id"]: embedder.embed_query(q["question"]) for q in questions}
    embed_s = time.perf_counter() - t0

    all_traces, ann_agree, ann_total = [], 0, 0
    for key, s in cfg["strategies"].items():
        collection = store.create_schema(s["collection"])
        traces = []
        t1 = time.perf_counter()
        for q in questions:
            filters = q.get("filter") if s["use_filter"] and q.get("filter") else None
            hits = store.search(s["collection"], qvecs[q["id"]], top_k, filters)
            trace = evaluate_query(q, hits)
            trace.update({"strategy": key, "collection": s["collection"], "filter_applied": filters,
                          "filter_compliant": filter_compliant(trace)})
            where = ({k: v for k, v in filters.items()} if filters and len(filters) == 1
                     else ({"$and": [{k: v} for k, v in filters.items()]} if filters else None))
            exact = exact_top_k(collection, qvecs[q["id"]], top_k, where)
            trace["exact_top_k"] = exact
            ann_agree += sum(h["chunk_id"] in exact for h in trace["hits"])
            ann_total += len(exact)
            traces.append(trace)
        search_s = time.perf_counter() - t1
        write_jsonl(RESULTS / "traces" / f"{key}_{args.split}.jsonl", traces)
        print(f"{key}: {len(traces)} queries, search {search_s:.2f}s")
        all_traces.extend(traces)

    rows = summarize(all_traces)
    out = {"evaluated_at": now(), "split": args.split, "model": embedder.model_name,
           "model_revision": embedder.resolved_revision, "top_k": top_k, "versions": package_versions(),
           "query_embed_s": round(embed_s, 2),
           "ann_vs_exact_top_k_overlap": f"{ann_agree}/{ann_total}", "metrics": rows}
    write_json(RESULTS / f"metrics_{args.split}.json", out)
    write_csv(RESULTS / f"metrics_{args.split}.csv", rows)
    write_csv(RESULTS / f"per_question_{args.split}.csv", [
        {"strategy": t["strategy"], "id": t["id"], "type": t["type"],
         "filter": json.dumps(t["filter"], ensure_ascii=False) if t["filter"] else "",
         "filter_applied": bool(t["filter_applied"]), "hit_at_1": int(t["hit_at_1"]),
         "hit_at_3": int(t["hit_at_3"]), "gold_unit_at_3": int(t["gold_unit_at_3"]),
         "evidence_split": int(t["evidence_split"]),
         "top3": " | ".join(f"{h['document_id']}:D{h['page']}({h['score']})" for h in t["hits"])}
        for t in all_traces])
    print(f"ANN vs exact top-{top_k} overlap: {ann_agree}/{ann_total}")
    for r in rows:
        print(f"{r['strategy']} {r['split']}: Hit@1 {r['hit_at_1']}/{r['N']}  "
              f"Hit@3 {r['hit_at_3']}/{r['N']}  gold article@3 {r['gold_unit_at_3']}/{r['N']}  "
              f"filter Hit@3 {r['filter_hit_at_3']}/{r['filter_questions']}  "
              f"filter compliant {r['filter_compliant']}/{r['filter_questions']}")


# ---------------------------------------------------------------- audit sheets
def cmd_audit(args) -> None:
    cfg = read_json(CONFIG)
    units = load_units()
    sources = {s["source_id"]: s for s in read_json(SOURCES)}
    texts = {d: (PROCESSED / f"{d}.txt").read_text(encoding="utf-8") for d in sources}
    targets = [AUDIT / n for n in ("coherence.csv", "metadata.csv", "grounding.csv")]
    if any(p.exists() for p in targets) and not args.force:
        sys.exit("audit sheets already exist (they may hold labels); use --force to overwrite")

    # Coherence: 10 positions fixed by seed before looking at any score.
    rng = random.Random(COHERENCE_SEED)
    pool = sorted((u for u in units if len(u.text) >= COHERENCE_MIN_CHARS),
                  key=lambda u: u.metadata["unit_id"])
    sample = sorted(rng.sample(pool, COHERENCE_SAMPLE), key=lambda u: u.metadata["unit_id"])
    chunk_sets = {name: make_chunks(sample, spec) for name, spec in collections(cfg).items()}
    rows = []
    for n, unit in enumerate(sample, start=1):
        pos = len(unit.text) // 2
        while unit.text[pos].isspace():
            pos += 1
        for key, s in cfg["strategies"].items():
            if key == "C":
                continue  # C uses exactly B's chunks
            covering = [c for c in chunk_sets[s["collection"]]
                        if c.page == unit.page and c.document_id == unit.document_id
                        and c.metadata["chunk_start"] <= pos < c.metadata["chunk_end"]]
            chunk = covering[0]
            rows.append({"position": f"P{n:02d}", "unit_id": unit.metadata["unit_id"],
                         "offset_in_article": pos,
                         "context": unit.text[max(0, pos - 60):pos + 60].replace("\n", " / "),
                         "strategy": key, "chunk_id": chunk.chunk_id, "chunk_chars": len(chunk.text),
                         "chunk_text": chunk.text, "label_0_2": "", "reason": "", "labeler": ""})
    write_csv(AUDIT / "coherence.csv", rows)

    # Metadata and grounding: every test question, top-3 of each strategy.
    unit_by_key = {(u.document_id, u.page): u for u in units}
    meta_rows, ground_rows = [], []
    for key in cfg["strategies"]:
        for t in read_jsonl(RESULTS / "traces" / f"{key}_test.jsonl"):
            for h in t["hits"]:
                m = h["metadata"]
                unit = unit_by_key.get((m["document_id"], m["page"]))
                offset = (unit.metadata["char_start"] + m["chunk_start"]) if unit else -1
                in_source = bool(unit) and texts[m["document_id"]][offset:offset + len(h["text"])] == h["text"]
                meta_rows.append({
                    "strategy": key, "id": t["id"], "rank": h["rank"], "chunk_id": h["chunk_id"],
                    "document_id": m["document_id"], "source": m["source"], "page_article": m["page"],
                    "year": m["year"], "law_number": m["law_number"], "article_title": m["article_title"],
                    "chapter": m["chapter"],
                    "auto_text_at_offset": in_source,
                    "auto_source_matches_manifest": m["source"] == sources[m["document_id"]]["source_url"],
                    "auto_year_matches_manifest": m["year"] == sources[m["document_id"]]["year"],
                    "auto_heading_matches": bool(unit) and unit.text.startswith(f"Điều {m['page']}. {m['article_title']}"),
                    "filter": json.dumps(t["filter"], ensure_ascii=False) if t["filter"] else "",
                    "filter_applied": bool(t["filter_applied"]),
                    "complies_with_filter": ("" if not t["filter"] else
                                             all(m.get(k) == v for k, v in t["filter"].items())),
                    "metadata_ok": "", "note": "", "labeler": ""})
            ground_rows.append({
                "strategy": key, "id": t["id"], "question": t["question"],
                "expected_answer": t["expected_answer"],
                "filter_applied": json.dumps(t["filter_applied"], ensure_ascii=False) if t["filter_applied"] else "",
                **{f"top{h['rank']}": f"[{h['document_id']} Điều {h['page']}] {h['text']}" for h in t["hits"]},
                "auto_evidence_hit_at_3": int(t["hit_at_3"]),
                "label_0_2": "", "reason": "", "labeler": ""})
    write_csv(AUDIT / "metadata.csv", meta_rows)
    write_csv(AUDIT / "grounding.csv", ground_rows)
    print(f"wrote {len(rows)} coherence rows, {len(meta_rows)} metadata rows, {len(ground_rows)} grounding rows")


def cmd_audit_summary(_args) -> None:
    def labels(rows, field):
        return [int(r[field]) for r in rows if r[field].strip() != ""]

    cfg = read_json(CONFIG)
    coherence = read_csv(AUDIT / "coherence.csv")
    metadata = read_csv(AUDIT / "metadata.csv")
    grounding = read_csv(AUDIT / "grounding.csv")
    out = []
    for key in cfg["strategies"]:
        coh_key = "B" if key == "C" else key
        coh = labels([r for r in coherence if r["strategy"] == coh_key], "label_0_2")
        meta = [r for r in metadata if r["strategy"] == key]
        meta_ok = [r for r in meta if r["metadata_ok"].strip().lower() in ("1", "true", "yes")]
        meta_filtered = {r["id"] for r in meta if r["filter"]}
        complied = {i for i in meta_filtered
                    if all(r["complies_with_filter"] == "True" for r in meta if r["id"] == i)}
        gr = labels([r for r in grounding if r["strategy"] == key], "label_0_2")
        out.append({
            "strategy": key,
            "coherence_mean": round(statistics.mean(coh), 2) if coh else None,
            "coherence_n": len(coh),
            "metadata_ok": f"{len(meta_ok)}/{len(meta)}",
            "filter_compliant": f"{len(complied)}/{len(meta_filtered)}" if meta_filtered else "N/A",
            "grounding_0_1_2": f"{gr.count(0)}/{gr.count(1)}/{gr.count(2)}",
            "grounding_mean": round(statistics.mean(gr), 2) if gr else None,
            "grounding_n": len(gr),
        })
    write_json(RESULTS / "audit_summary.json", {"generated_at": now(), "rows": out})
    for r in out:
        print(r)


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 06 data ingestion pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare").set_defaults(func=cmd_prepare)
    sub.add_parser("check-benchmark").set_defaults(func=cmd_check_benchmark)
    sub.add_parser("ingest").set_defaults(func=cmd_ingest)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--split", choices=["dev", "test"], required=True)
    ev.set_defaults(func=cmd_evaluate)
    au = sub.add_parser("audit")
    au.add_argument("--force", action="store_true")
    au.set_defaults(func=cmd_audit)
    sub.add_parser("audit-summary").set_defaults(func=cmd_audit_summary)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
