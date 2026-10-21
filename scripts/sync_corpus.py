#!/usr/bin/env python3
"""Bounded public-site sync. Standard library only; no model or private API.

Only --write updates corpus/manifest. HTTP caches are local/Actions cache data,
never deployment inputs. Failed validation leaves the previous corpus intact.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "agents/_knowledge/corpus.json"
MANIFEST = ROOT / "cloud-functions/guide-status/knowledge-status.json"
HOSTS = {"hefa.p4theater.cn", "p4theater.cn"}
SEEDS = [f"https://{host}/sitemap.xml" for host in sorted(HOSTS)]
WORKS = "https://hefa.p4theater.cn/data/works.json"
MAX_BYTES = 4 * 1024 * 1024
MAX_DISCOVERED = 2500
MAX_PAGES = 256
MAX_NEW = 32
TIME_BUDGET = 135
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
DROP_TAGS = {"script", "style", "noscript", "nav", "footer", "form", "button"}
DROP_CLASSES = {"hf-site-entry", "re-exact-return", "pf-inline-links", "pf-chapter-nav", "wp-chapters", "wp-sections", "hf-site-action", "works-guide-dialog", "works-guide-launcher", "works-guide-pet", "lh-guide-links"}
SOURCE_FAILURE_REASONS = {"redirect_outside_public_allowlist", "conditional_redirect_changed", "public_http_failed", "invalid_http_response", "response_too_large", "not_html", "noindex", "invalid_html", "missing_or_ambiguous_canonical", "canonical_mismatch", "reviewed_canonical_changed", "missing_main_content", "missing_or_error_title", "empty_or_abnormal_main_content", "sync_time_budget_exceeded"}


class SyncError(ValueError):
    """Fixed reason only: no upstream text, URLs or environment values."""


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_url(value: str) -> bool:
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname in HOSTS and not p.username and not p.password
                and p.port in (None, 443) and not p.query and not p.fragment
                and not any(c.isspace() or ord(c) < 32 for c in value) and "\\" not in value)
    except (ValueError, TypeError):
        return False


def eligible(url: str) -> bool:
    if not safe_url(url):
        return False
    p = urlsplit(url)
    path = re.sub(r"^/en(?=/|$)", "", p.path).strip("/")
    if p.hostname == "hefa.p4theater.cn":
        return bool(re.fullmatch(r"(?:|about|reference|writing|reading|works(?:/(?:all|early|collaborative|proposals))?|work/[a-z0-9-]+(?:/performance)?|reading/[a-z0-9-]+(?:/chapters/\d+)?|hefa-on(?:/encounters/[a-z0-9-]+)?)", path))
    return bool(re.fullmatch(r"(?:|about/p4-theater|hefa|he-fa|shoot-self-with-you|human-surrender|real-image|agt|chinese-experimental-theater|knowledge(?:/[a-z0-9-]+)?|articles/(?:19|20)\d{2}/[^/]+)", path))


def normalized_url(url: str) -> str:
    if not safe_url(url):
        raise SyncError("url_outside_public_allowlist")
    parts = urlsplit(url)
    path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
    path = re.sub(r"%[a-fA-F0-9]{2}", lambda match: match[0].upper(), path)
    return urlunsplit(("https", parts.hostname, path, "", ""))


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_url(newurl):
            raise SyncError("redirect_outside_public_allowlist")
        return super().redirect_request(req, fp, code, msg, headers, normalized_url(newurl))


def fetch(url: str, cached: dict | None = None) -> dict:
    if not safe_url(url):
        raise SyncError("request_outside_public_allowlist")
    headers = {"User-Agent": "P4WorksGuideSync/1.0 (public canonical text)", "Accept": "text/html,application/json,application/xml,text/xml"}
    for field, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
        if cached and isinstance(cached.get(field), str) and len(cached[field]) < 500:
            headers[header] = cached[field]
    try:
        response = build_opener(SafeRedirect()).open(Request(normalized_url(url), headers=headers), timeout=10)
    except HTTPError as exc:
        if exc.code == 304 and cached:
            if normalized_url(exc.url).rstrip("/") != normalized_url(url).rstrip("/"):
                raise SyncError("conditional_redirect_changed") from None
            return {"status": 304, "body": b"", "headers": {}, "url": url}
        raise SyncError(f"http_{exc.code}") from None
    except SyncError:
        raise
    except Exception:
        raise SyncError("public_http_failed") from None
    with response:
        if response.status != 200 or not safe_url(response.geturl()):
            raise SyncError("invalid_http_response")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise SyncError("response_too_large")
        return {"status": 200, "body": body, "headers": {k.lower(): v for k, v in response.headers.items()}, "url": response.geturl()}


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def nodes(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.nodes()

    def text(self):
        classes = set((self.attrs.get("class") or "").split())
        if self.tag in DROP_TAGS or classes & DROP_CLASSES or any(c.startswith("works-guide-") for c in classes) or any(k in self.attrs for k in ("data-works-guide", "data-guide-pet", "data-works-guide-ui")):
            return []
        lines = []
        for child in self.children:
            if isinstance(child, Node):
                lines.extend(child.text())
            elif child.strip():
                lines.append(re.sub(r"\s+", " ", child).strip())
        return lines


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def extract(response: dict, requested: str, old: dict | None, work_meta: dict) -> dict:
    if "text/html" not in response["headers"].get("content-type", "").lower():
        raise SyncError("not_html")
    if "noindex" in response["headers"].get("x-robots-tag", "").lower():
        raise SyncError("noindex")
    try:
        document = Document(response["body"].decode("utf-8", "strict"))
    except (ValueError, UnicodeError, RecursionError):
        raise SyncError("invalid_html") from None
    nodes = list(document.root.nodes())
    canonical_links = [n.attrs.get("href", "") for n in nodes if n.tag == "link" and "canonical" in n.attrs.get("rel", "").lower().split()]
    if len(canonical_links) != 1:
        raise SyncError("missing_or_ambiguous_canonical")
    canonical = urljoin(response["url"], canonical_links[0])
    if not safe_url(canonical) or normalized_url(canonical).rstrip("/") != normalized_url(response["url"]).rstrip("/") or urlsplit(canonical).hostname != urlsplit(requested).hostname:
        raise SyncError("canonical_mismatch")
    canonical = normalized_url(canonical)
    if old and canonical.rstrip("/") != normalized_url(old["url"]).rstrip("/"):
        raise SyncError("reviewed_canonical_changed")
    if any(n.tag == "meta" and n.attrs.get("name", "").lower() in {"robots", "googlebot", "bingbot"} and "noindex" in n.attrs.get("content", "").lower() for n in nodes):
        raise SyncError("noindex")
    main = next((n for n in nodes if n.tag == "main"), None) or next((n for n in nodes if n.tag == "article"), None)
    if main is None:
        raise SyncError("missing_main_content")
    heading = next((n for n in main.nodes() if n.tag == "h1"), None) or next((n for n in nodes if n.tag == "title"), None)
    title = " ".join(heading.text()) if heading else ""
    if not title or re.match(r"^(?:404\b|page not found|not found|页面不存在)", title, re.I):
        raise SyncError("missing_or_error_title")
    path = urlsplit(canonical).path
    if path.rstrip("/") in {"/hefa-on", "/en/hefa-on"}:
        main = next((n for n in main.nodes() if "he-intro" in n.attrs.get("class", "").split()), main)
    text = "\n".join(main.text()).strip()
    if len(text) < 80 or len(text) > 250000 or (old and len(text) < len(old["text"]) * .3):
        raise SyncError("empty_or_abnormal_main_content")
    language = next((n.attrs.get("lang", "") for n in nodes if n.tag == "html"), "")
    language = "en" if language.lower().startswith("en") or "/en/" in path else "zh"
    if old:
        # Reviewed status/role/aliases survive automatic body refreshes. A style
        # or navigation-only HTML change must not churn timestamps or raw hashes.
        if re.sub(r"\s+", " ", title) == re.sub(r"\s+", " ", old["title"]) and re.sub(r"\s+", " ", text) == re.sub(r"\s+", " ", old["text"]) and language == old["language"]:
            return deepcopy(old)
        item = deepcopy(old)
        item.pop("raw_path", None)  # An old raw-HTML receipt cannot attest new bytes.
    else:
        site = "hefa" if urlsplit(canonical).hostname == "hefa.p4theater.cn" else "p4"
        meta = work_meta.get(canonical) or work_meta.get(canonical.removesuffix("/performance"), {})
        kind = "work" if "/work/" in path else "reference" if path.rstrip("/").endswith("reference") else "research" if re.search(r"/reading|/knowledge", path) else "public_page"
        status = "public_snapshot"
        if meta.get("section") == "proposal":
            kind, status = "proposal", "proposal_not_confirmed_implemented"
        elif meta.get("section") == "collaborative":
            status = "documented_collaboration"
        elif meta.get("section") == "early":
            status = "documented_early_work"
        if "hefa-on" in path:
            kind, status = "fiction", "creative_fiction"
        elif "/articles/" in path:
            kind, status = "historical_record", "historical_document"
        directory = re.sub(r"^/en(?=/|$)", "", path).strip("/") in {"", "works", "works/all", "works/early", "works/collaborative", "works/proposals"}
        if directory:
            kind, status = "directory", "public_directory"
        if "forest-misremembered-someone" in path:
            status = "documented_current_edition_event_date_unknown"
        item = {"id": site + "-" + sha(canonical.encode())[:16], "url": canonical, "site": site,
                "kind": kind, "status": status, "priority": 2 if directory else 8 if kind == "work" else 5,
                "aliases": list(dict.fromkeys(meta.get("aliases", []) + [title])),
                "author_scope": meta.get("role") or "Official public source. Preserve named authors and collective credits; historical records do not establish current identity or realization of proposals."}
        if kind == "fiction":
            item["author_scope"] = "Fictional AI-assisted creative theatre; historical encounters are invented, not real biography."
        for field in ("date", "date_precision", "section", "role", "medium", "source_note"):
            if meta.get(field):
                item[field] = meta[field]
    item.update(title=title, text=text, language=language, text_sha256=sha(text.encode()),
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), sha256=sha(response["body"]))
    return item


def discover(get) -> tuple[dict, dict]:
    urls, metadata = {}, {}
    for seed in SEEDS:
        response = get(seed)
        try:
            root = ET.fromstring(response["body"])
        except ET.ParseError:
            raise SyncError("invalid_sitemap") from None
        if root.tag.rsplit("}", 1)[-1] != "urlset":
            raise SyncError("expected_site_urlset")
        for entry in root:
            values = {n.tag.rsplit("}", 1)[-1]: n.text or "" for n in entry if n.tag.rsplit("}", 1)[-1] in {"loc", "lastmod"}}
            url = values.get("loc", "")
            if not safe_url(url) or urlsplit(url).hostname != urlsplit(seed).hostname:
                raise SyncError("invalid_sitemap_url")
            urls[normalized_url(url)] = values.get("lastmod", "")
        if len(urls) > MAX_DISCOVERED:
            raise SyncError("discovery_limit_exceeded")
    try:
        public_works = json.loads(get(WORKS)["body"])
        for work in public_works["works"]:
            aliases = list((work.get("zh", {}).get("titles") or {}).values())
            for language in ("zh", "en"):
                row = work.get(language, {})
                if row.get("url"):
                    if not safe_url(row["url"]) or urlsplit(row["url"]).hostname != "hefa.p4theater.cn":
                        raise SyncError("invalid_work_metadata_url")
                    url = normalized_url(row["url"])
                    metadata[url] = {**row, "aliases": aliases}
                    urls.setdefault(url, row.get("record_modified", ""))
    except (ValueError, KeyError, TypeError):
        raise SyncError("invalid_public_work_metadata") from None
    if len(urls) > MAX_DISCOVERED:
        raise SyncError("discovery_limit_exceeded")
    return urls, metadata


def validate(payload):
    spec = importlib.util.spec_from_file_location("sync_guide_validation", ROOT / "agents/_guide.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    kb = module.KnowledgeBase(payload)
    sources = payload.get("sources", [])
    if not sources or len(kb.sources) != len(sources) or len({s["id"] for s in sources}) != len(sources) or len({s["url"] for s in sources}) != len(sources):
        raise SyncError("invalid_candidate_corpus")
    if any(not safe_url(s["url"]) or not s.get("text_sha256") for s in sources):
        raise SyncError("invalid_candidate_provenance")


def synchronize(payload, cache, *, get=fetch, max_pages=MAX_PAGES, max_new=MAX_NEW, priority_urls=(), budget=TIME_BUDGET):
    started = time.monotonic()
    if not 1 <= max_pages <= MAX_PAGES or not 0 <= max_new <= min(MAX_NEW, max_pages):
        raise SyncError("invalid_sync_bounds")
    validate(payload)
    seed_state = deepcopy(cache.get("seeds", {})) if isinstance(cache.get("seeds"), dict) else {}
    def seed_get(url):
        saved = seed_state.get(url, {})
        body = saved.get("body", "").encode() if isinstance(saved.get("body"), str) else b""
        valid = bool(body and sha(body) == saved.get("body_sha256") and saved.get("url") == url)
        response = get(url, saved if valid else None)
        if response["status"] == 304 and valid:
            return {"status": 200, "body": body, "headers": {}, "url": url}
        if response["status"] != 200:
            raise SyncError("invalid_discovery_response")
        seed_state[url] = {"body": response["body"].decode("utf-8"), "body_sha256": sha(response["body"]), "url": url,
                           "etag": response["headers"].get("etag", ""), "last_modified": response["headers"].get("last-modified", "")}
        return response
    discovered, work_meta = discover(seed_get)
    old_by_url = {s["url"]: s for s in payload["sources"]}
    state = deepcopy(cache.get("pages", {})) if isinstance(cache.get("pages"), dict) else {}
    if any(not safe_url(u) or (u not in old_by_url and not eligible(u)) for u in priority_urls):
        raise SyncError("invalid_priority_url")
    known_keys = {normalized_url(u).rstrip("/"): u for u in old_by_url}
    priorities = {known_keys.get(normalized_url(u).rstrip("/"), normalized_url(u)) for u in priority_urls}
    def rank(url):
        item = state.get(url, {})
        important = urlsplit(url).path.rstrip("/") in {"", "/en", "/about", "/en/about", "/reference", "/en/reference", "/hefa", "/en/he-fa", "/shoot-self-with-you", "/en/shoot-self-with-you"}
        modified = discovered.get(url, "") and discovered.get(url) != item.get("sitemap_lastmod")
        return (url not in priorities, not important, not modified, item.get("checked_at", 0), url)
    existing = sorted(old_by_url, key=rank)
    previous_discovery = set(cache.get("discovered", [])) if isinstance(cache.get("discovered"), list) else None
    def new_rank(url):
        date = re.search(r"(?:19|20)\d{2}-\d{2}-\d{2}", url)
        lastmod = re.match(r"\d{4}-\d{2}-\d{2}", discovered.get(url, ""))
        newest = max(int(match[0].replace("-", "")) for match in (date, lastmod) if match) if date or lastmod else 0
        checked = state.get(url, {}).get("checked_at", 0)
        newly_published = previous_discovery is not None and url not in previous_discovery
        return (url not in priorities, not newly_published, checked > 0, -newest if not checked else 0, checked, url)
    new = sorted((u for u in set(discovered) | priorities if u not in old_by_url and eligible(u)), key=new_rank)[:max_new]
    selected = existing[:max_pages - len(new)] + new
    updates, failures, skipped = {}, [], []
    def refresh(url):
        if time.monotonic() - started > budget:
            raise SyncError("sync_time_budget_exceeded")
        old = old_by_url.get(url)
        saved = state.get(url, {})
        validators = saved if old and saved.get("text_sha256") == old.get("text_sha256") else None
        response = get(url, validators)
        item = deepcopy(old) if response["status"] == 304 and old else extract(response, url, old, work_meta)
        # Public catalogue aliases can grow without discarding reviewed names,
        # roles or statuses, even when the HTML itself returns 304 unchanged.
        meta = work_meta.get(item["url"], {})
        published_aliases = [*meta.get("aliases", []), meta.get("title", "")]
        aliases = list(item.get("aliases", []))
        for alias in published_aliases:
            if isinstance(alias, str) and alias.strip() and alias[:160] not in aliases:
                aliases.append(alias[:160])
        item["aliases"] = aliases
        page_state = {"text_sha256": item["text_sha256"], "checked_at": int(time.time()), "sitemap_lastmod": discovered.get(url, "")}
        for field, header in (("etag", "etag"), ("last_modified", "last-modified")):
            value = response["headers"].get(header) or (saved.get(field) if response["status"] == 304 else None)
            if value:
                page_state[field] = value
        return item, page_state
    pool = ThreadPoolExecutor(max_workers=16)
    jobs = {pool.submit(refresh, url): url for url in selected}
    try:
        for future in as_completed(jobs, timeout=max(1, budget - (time.monotonic() - started))):
            url = jobs[future]
            try:
                item, page_state = future.result()
                updates[url], state[url] = item, page_state
            except Exception as exc:
                raw_reason = str(exc) if isinstance(exc, SyncError) else ""
                reason = raw_reason if raw_reason in SOURCE_FAILURE_REASONS or re.fullmatch(r"http_(?:400|401|403|404|408|410|429|500|502|503|504)", raw_reason) else "source_validation_failed"
                if url in old_by_url:
                    failures.append({"id": old_by_url[url]["id"][:100], "reason": reason})
                else:
                    skipped.append(reason)
                    state[url] = {"checked_at": int(time.time())}
        if failures:
            print(json.dumps({"reviewed_source_failures": failures}), file=sys.stderr)
            raise SyncError("reviewed_source_refresh_failed")
    except TimeoutError:
        raise SyncError("sync_time_budget_exceeded") from None
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    if time.monotonic() - started > budget + 12:
        raise SyncError("sync_time_budget_exceeded")
    candidate = deepcopy(payload)
    candidate["sources"] = [updates.get(s["url"], s) for s in payload["sources"]]
    candidate["sources"].extend(updates[u] for u in new if u in updates)
    changed = candidate["sources"] != payload["sources"]
    if changed:
        content_digest = sha(json.dumps(candidate["sources"], ensure_ascii=False, sort_keys=True).encode())[:16]
        candidate.update(version="works-guide-public-sync-" + content_digest, built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        validate(candidate)
    summary = {"changed": changed, "source_count": len(candidate["sources"]), "checked": len(selected), "added": len(candidate["sources"]) - len(payload["sources"]), "skipped_new": len(skipped), "pending_existing": max(0, len(existing) - (max_pages - len(new))), "remaining_discoverable": sum(u not in {s["url"] for s in candidate["sources"]} and eligible(u) for u in discovered)}
    return candidate, {"version": 1, "pages": state, "seeds": seed_state, "discovered": sorted(discovered)}, summary


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--cache", type=Path, default=ROOT / ".sync-cache/state.json")
    parser.add_argument("--priority-urls", default="", help="Optional comma/space separated public canonical URLs after a site release")
    args = parser.parse_args()
    try:
        try:
            cache = json.loads(args.cache.read_text()) if args.cache.exists() else {}
            if not isinstance(cache, dict):
                cache = {}
        except (ValueError, OSError):
            cache = {}  # The cache is optional and must not block safe re-fetching.
        candidate, state, summary = synchronize(json.loads(CORPUS.read_text()), cache, priority_urls=args.priority_urls.replace(",", " ").split())
        if args.write and summary["changed"]:
            serialized = (json.dumps(candidate, ensure_ascii=False, indent=2) + "\n").encode()
            manifest = {"corpus_version": candidate["version"], "source_count": len(candidate["sources"]), "corpus_sha256": sha(serialized)}
            # Both files are validated first and enter one Git commit together.
            previous = {path: path.read_bytes() for path in (CORPUS, MANIFEST)}
            try:
                atomic_json(CORPUS, candidate)
                atomic_json(MANIFEST, manifest)
            except OSError:
                for path, original in previous.items():
                    if path.read_bytes() != original:
                        path.write_bytes(original)
                raise SyncError("knowledge_write_failed") from None
        try:
            atomic_json(args.cache, state)
        except OSError:
            pass  # Cache persistence is optional; validated knowledge is not.
        print(json.dumps({**summary, "written": args.write and summary["changed"]}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"written": False, "reason": str(exc) if isinstance(exc, SyncError) else "sync_failed", "previous_committed_corpus_retained": True}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
