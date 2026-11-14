"""Check re-ingest behaviour on a throw-away Chroma store (the real index is not touched).

Run from starter/:  python -m scripts.reingest_change_test
Scenario on 20 articles of blld-2019 with strategy B chunking:
  1. first load, 2. same data again, 3. one article edited + one removed + one metadata change,
  4. original data restored.
"""
import copy
import json
import shutil
import tempfile
from pathlib import Path

from src.run import RESULTS, load_embedder, load_units, make_chunks, read_json, CONFIG, now, sync_collection
from src.store import ChromaStore


def main() -> None:
    cfg = read_json(CONFIG)
    spec = {**cfg["strategies"]["B"], "tag": "B"}
    units = [u for u in load_units() if u.document_id == "blld-2019" and u.page <= 20]
    embedder = load_embedder(cfg)
    tmp = Path(tempfile.mkdtemp(prefix="chroma_change_test_"))
    name = "change_test"
    steps = []
    try:
        store = ChromaStore(tmp, embedder.model_name, embedder.dimensions)

        steps.append({"step": "1_first_load", **sync_collection(store, embedder, name, make_chunks(units, spec))})
        steps.append({"step": "2_same_data", **sync_collection(store, embedder, name, make_chunks(units, spec))})

        changed = copy.deepcopy(units)
        d5 = next(u for u in changed if u.page == 5)
        d5.text += "\nCâu bổ sung dùng để kiểm thử nạp lại."
        d3 = next(u for u in changed if u.page == 3)
        d3.metadata["chapter_title"] += " (sửa metadata)"
        removed = [c.chunk_id for c in make_chunks([u for u in changed if u.page == 10], spec)]
        changed = [u for u in changed if u.page != 10]
        step3 = sync_collection(store, embedder, name, make_chunks(changed, spec))
        left = store.create_schema(name).get(ids=removed)["ids"]
        d3_meta = store.create_schema(name).get(where={"page": 3}, include=["metadatas"])["metadatas"]
        steps.append({"step": "3_edit_D005_remove_D010_meta_D003", **step3,
                      "removed_ids_still_present": left,
                      "D003_chapter_title_after": sorted({m["chapter_title"] for m in d3_meta})})

        steps.append({"step": "4_restore", **sync_collection(store, embedder, name, make_chunks(units, spec))})
    finally:
        del store
        shutil.rmtree(tmp, ignore_errors=True)

    out = {"run_at": now(), "units": len(units), "strategy": "B", "steps": steps}
    (RESULTS / "reingest_change_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                                      encoding="utf-8")
    for s in steps:
        print({k: v for k, v in s.items() if k != "time_s"})


if __name__ == "__main__":
    main()
