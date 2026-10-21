"""Import a reviewed public snapshot, validate it, and refresh deployment metadata.

Usage: python scripts/import_corpus.py /absolute/path/to/corpus.json
This script reads/writes local files only. It never fetches sites or calls a model.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("works_guide_import", ROOT / "agents" / "_guide.py")
guide = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guide
spec.loader.exec_module(guide)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    original = Path(sys.argv[1]).read_bytes()
    payload = json.loads(original)
    kb = guide.KnowledgeBase(payload)
    if not kb.sources or len(kb.sources) != len(payload.get("sources", [])):
        raise SystemExit("Rejected corpus: every source must be valid, public and on an approved HTTPS host.")
    if len({source.id for source in kb.sources}) != len(kb.sources):
        raise SystemExit("Rejected corpus: duplicate source ids.")
    if any(not source.get("text_sha256") for source in payload["sources"]):
        raise SystemExit("Rejected corpus: missing text_sha256.")
    target = ROOT / "agents" / "_knowledge" / "corpus.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(original)
    manifest = {"corpus_version": payload["version"], "source_count": len(kb.sources),
                "corpus_sha256": hashlib.sha256(original).hexdigest()}
    (ROOT / "cloud-functions" / "guide-status" / "knowledge-status.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__": main()
