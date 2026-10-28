"""Public-corpus sync regressions: in-memory HTTP only, no model/dependency."""
from copy import deepcopy
from html import escape
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_sync", ROOT / "scripts/sync_corpus.py")
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)

URL = "https://hefa.p4theater.cn/work/known"
TEXT = "A documented public installation preserves the artist statement and the named collaborators. It does not establish private facts or unseen film details."
RELEASE_READING_URLS = (
    "https://p4theater.cn/en/knowledge/shadow-counterpoint-reading/",
    "https://p4theater.cn/en/knowledge/rehearsal-to-film/",
    "https://p4theater.cn/en/knowledge/p4-spaces-and-distance/",
)


def html(url=URL, body=TEXT, extra="", head="", title="Known work"):
    raw = f'<html lang="en"><head><link rel="canonical" href="{url}">{head}</head><body><nav>Global navigation</nav><main><h1>{title}</h1><p>{body}</p>{extra}</main><footer>Global footer</footer></body></html>'
    return {"status": 200, "body": raw.encode(), "url": url, "headers": {"content-type": "text/html; charset=utf-8", "etag": '"stable"'}}


def source():
    return {"id": "reviewed-work", "url": URL, "title": "Known work", "site": "hefa", "language": "en",
            "text": "Known work\n" + TEXT, "text_sha256": sync.sha(("Known work\n" + TEXT).encode()),
            "sha256": "old-raw-sha", "fetched_at": "2026-10-21T00:00:00Z", "raw_path": "raw/reviewed.body",
            "kind": "work", "status": "documented_current_edition_event_date_unknown", "priority": 9,
            "aliases": ["旧别名", "Known work"], "author_scope": "He Fa reads; He Yu holds the candle.",
            "source_note": "Edition year is not a premiere date.", "section": "collaborative"}


def payload():
    return {"version": "reviewed-v1", "built_at": "fixed", "sources": [source()]}


def network(pages=None, additional=(), work_rows=()):
    pages = pages or {URL: html()}
    listed = [URL, *additional]
    routes = {**pages, sync.WORKS: {"status": 200, "body": json.dumps({"works": list(work_rows)}).encode(), "headers": {"etag": '"works"'}, "url": sync.WORKS}}
    for seed in sync.SEEDS:
        host = sync.urlsplit(seed).hostname
        body = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{u}</loc><lastmod>2026-10-21</lastmod></url>' for u in listed if sync.urlsplit(u).hostname == host) + '</urlset>'
        routes[seed] = {"status": 200, "body": body.encode(), "headers": {"etag": '"map"'}, "url": seed}
    calls = []
    def get(url, cached=None):
        calls.append((url, deepcopy(cached)))
        response = routes[url]
        if cached and cached.get("etag") == response["headers"].get("etag"):
            return {"status": 304, "body": b"", "headers": {}, "url": url}
        return deepcopy(response)
    return get, calls


class SyncTests(unittest.TestCase):
    def test_verified_project_release_has_69_eligible_canonical_urls(self):
        self.assertEqual(len(sync.P4_PROJECT_SLUGS), 32)
        self.assertEqual(len(sync.P4_PROJECT_URLS), 64)
        urls = sorted(sync.P4_PROJECT_URLS | sync.P4_PARTICIPANT_URLS) + list(RELEASE_READING_URLS)
        self.assertEqual(len(set(urls)), 69)
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(sync.eligible(url))
                self.assertEqual(sync.normalized_url(url), url)

    def test_new_routes_reject_unverified_hosts_slugs_and_url_variants(self):
        for canonical in sorted(sync.P4_PROJECT_URLS | sync.P4_PARTICIPANT_URLS):
            variants = [canonical.replace("https://", "http://"),
                        canonical.replace("p4theater.cn", "unknown.p4theater.cn"),
                        canonical.replace("p4theater.cn", "hefa.p4theater.cn"),
                        canonical.replace("p4theater.cn", "p.p4theater.cn"),
                        canonical.replace("p4theater.cn", "P4THEATER.CN"),
                        canonical.replace("p4theater.cn", "p4theater.cn:443"),
                        canonical + "?page=1", canonical + "#credits", canonical.rstrip("/"),
                        canonical.replace(".cn/", ".cn//"), canonical + "../",
                        canonical.replace("projects/", "projects/../projects/") if "/projects/" in canonical else canonical + "extra/"]
            for url in variants:
                with self.subTest(url=url):
                    self.assertFalse(sync.eligible(url))
        for url in ["https://p4theater.cn/projects/unknown-project/",
                    "https://p4theater.cn/en/projects/unknown-project/",
                    "https://p4theater.cn/projects/%73hadow-counterpoint/",
                    "https://p4theater.cn/projects/Shadow-counterpoint/",
                    "https://p4theater.cn/projects/", "https://p4theater.cn/en/projects/",
                    "https://p4theater.cn/participants/someone/"]:
            self.assertFalse(sync.eligible(url), url)

    def test_new_archives_preserve_organisation_and_literal_credit_scope(self):
        for url in sorted(sync.P4_PROJECT_URLS | sync.P4_PARTICIPANT_URLS):
            with self.subTest(url=url):
                item = sync.extract(html(url), url, None, {})
                self.assertEqual(item["site"], "p4")
                self.assertNotIn("person", item)
                self.assertNotIn("people", item)
                self.assertNotIn("creators", item)
                if url in sync.P4_PROJECT_URLS:
                    self.assertEqual(item["kind"], "project_record")
                    self.assertEqual(item["status"], "documented_project_archive")
                    self.assertIn("not make every project a sole P4 or He Fa creation", item["author_scope"])
                else:
                    self.assertEqual(item["kind"], "directory")
                    self.assertEqual(item["status"], "public_directory")
                    self.assertEqual(item["priority"], 2)
                    self.assertIn("literal credited name", item["author_scope"])
                    self.assertIn("not a verified unified identity", item["author_scope"])
                old = source(); old.update(url=url, site="p4", kind="reviewed_archive", author_scope="Reviewed source-specific collective credits.")
                refreshed = sync.extract(html(url, body=TEXT + " A public source-specific addition."), url, old, {})
                for key in ("id", "kind", "status", "priority", "aliases", "author_scope", "source_note", "section"):
                    self.assertEqual(refreshed[key], old[key])

    def test_new_routes_keep_canonical_noindex_and_content_guards(self):
        for url in ("https://p4theater.cn/projects/shadow-counterpoint/", "https://p4theater.cn/en/participants/"):
            no_slash = html(url.rstrip("/")); no_slash["url"] = url
            response_redirect = html(url); response_redirect["url"] = url.rstrip("/")
            cases = [no_slash, response_redirect, html(url, body="short"),
                     html(url, head='<meta name="robots" content="noindex">')]
            for response in cases:
                with self.subTest(url=url, body=response["body"][:100]), self.assertRaises(sync.SyncError):
                    sync.extract(response, url, None, {})
            old = source(); old.update(url=url, text=TEXT * 10)
            with self.assertRaisesRegex(sync.SyncError, "empty_or_abnormal_main_content"):
                sync.extract(html(url), url, old, {})

    def test_all_committed_source_metadata_survives_body_refresh(self):
        # The committed corpus grows in normal runs; exercise every current
        # reviewed row rather than pinning an obsolete source count.
        committed = json.loads(sync.CORPUS.read_text())
        before = deepcopy(committed)
        content_fields = {"title", "text", "language", "text_sha256", "sha256", "fetched_at", "raw_path"}
        for old in committed["sources"]:
            with self.subTest(source_id=old["id"]):
                self.assertTrue(sync.safe_url(old["url"]))
                response = html(old["url"], body=escape(old["text"]) + " A source-specific public addition.", title=escape(old["title"]))
                refreshed = sync.extract(response, old["url"], old, {})
                for field in old.keys() - content_fields:
                    self.assertEqual(refreshed[field], old[field], field)
        self.assertEqual(committed, before)

    def test_69_release_sources_fit_three_normal_32_32_5_runs(self):
        # Synthetic in-memory HTTP fixtures only: this does not claim that
        # candidate website pages are deployed or publicly fetchable.
        urls = sorted(sync.P4_PROJECT_URLS) + sorted(sync.P4_PARTICIPANT_URLS) + list(RELEASE_READING_URLS)
        get, calls = network({URL: html(), **{u: html(u) for u in urls}}, urls)
        current, cache = payload(), {}
        for batch, expected in ((urls[:32], 32), (urls[32:64], 32), (urls[64:], 5)):
            calls.clear()
            current, cache, summary = sync.synchronize(current, cache, get=get, priority_urls=batch)
            self.assertEqual(summary["added"], expected)
            self.assertLessEqual(summary["added"], sync.MAX_NEW)
            self.assertLessEqual(summary["checked"], sync.MAX_PAGES)
            self.assertEqual(current["sources"][0], source())
            self.assertTrue(set(batch).issubset({s["url"] for s in current["sources"]}))
        self.assertEqual(len(current["sources"]), 70)
        self.assertTrue(set(urls).issubset({s["url"] for s in current["sources"]}))

    def test_explicit_public_path_allowlist_and_redirects(self):
        for url in [URL, "https://hefa.p4theater.cn/", "https://p4theater.cn/", "https://p4theater.cn/en/", "https://hefa.p4theater.cn/reading/new-essay", "https://hefa.p4theater.cn/en/hefa-on", "https://hefa.p4theater.cn/works", "https://hefa.p4theater.cn/en/works/all", "https://hefa.p4theater.cn/hefa-on/encounters/new-encounter", "https://p4theater.cn/articles/2026/new-article/", "https://p4theater.cn/en/knowledge/new-research/"]:
            self.assertTrue(sync.eligible(url), url)
        for url in ["https://p4theater.cn/archive-index/2026/", "https://p4theater.cn/articles/2026/", "https://hefa.p4theater.cn/assets/private.js", "https://hefa.p4theater.cn/hefa-on/archive", "https://hefa.p4theater.cn/hefa-on/role/someone", "https://p4theater.cn/articles/2026/test/?token=x", "https://p4theater.cn.evil.com/articles/2026/new/", "http://p4theater.cn/articles/2026/new/"]:
            self.assertFalse(sync.eligible(url), url)
        with self.assertRaises(sync.SyncError):
            sync.SafeRedirect().redirect_request(Request(URL), None, 302, "", {}, "https://evil.invalid/page")

    def test_main_only_and_navigation_widget_changes_are_noops(self):
        for extra in ['<nav>Changed navigation</nav><script>model instructions</script>', '<div class="works-guide-pet-v2"><p>New pet promotional copy</p></div>', '<div data-works-guide-ui><p>Other floating guide copy</p></div><a data-works-guide href="https://guide.p4theater.cn/">Ask now</a>']:
            result = sync.extract(html(extra=extra), URL, source(), {})
            self.assertEqual(result, source())
        self.assertEqual(sync.extract(html(body=TEXT.replace(" ", "\n  ")), URL, source(), {}), source())
        old = source(); old["title"] = "Known\u3000work"; old["text"] = old["text"].replace("Known work", "Known\u3000work")
        self.assertEqual(sync.extract(html(), URL, old, {}), old)

    def test_changed_body_retains_reviewed_metadata_without_false_raw_receipt(self):
        old = source()
        result = sync.extract(html(body=TEXT + " A new public detail is documented."), URL, old, {URL: {"role": "Someone else", "section": "selected"}})
        for key in ("id", "aliases", "status", "kind", "priority", "author_scope", "section", "source_note"):
            self.assertEqual(result[key], old[key])
        self.assertNotIn("raw_path", result)
        self.assertEqual(result["text_sha256"], sync.sha(result["text"].encode()))
        self.assertEqual(result["sha256"], sync.sha(html(body=TEXT + " A new public detail is documented.")["body"]))

    def test_bad_documents_cannot_replace_reviewed_text(self):
        bad = [html(body="short"), html(head='<meta name="robots" content="noindex,follow">')]
        wrong = html(); wrong["body"] = wrong["body"].replace(URL.encode(), b"https://evil.invalid/page"); bad.append(wrong)
        missing = html(); missing["body"] = b"<html><body><nav>Only navigation</nav></body></html>"; bad.append(missing)
        duplicate = html(head=f'<link rel="canonical" href="{URL}">'); bad.append(duplicate)
        no_main = html(); no_main["body"] = no_main["body"].replace(b"<main>", b"<div>").replace(b"</main>", b"</div>"); bad.append(no_main)
        for response in bad:
            with self.subTest(response=response["body"][:100]), self.assertRaises(sync.SyncError):
                sync.extract(response, URL, source(), {})

    def test_new_sources_keep_fiction_proposal_and_historical_boundaries(self):
        fixtures = [("https://hefa.p4theater.cn/hefa-on/encounters/new-fiction", {}, "creative_fiction"),
                    ("https://hefa.p4theater.cn/work/new-proposal", {"section": "proposal", "role": "Joint proposal", "aliases": ["提案"]}, "proposal_not_confirmed_implemented"),
                    ("https://p4theater.cn/articles/2026/new-article/", {}, "historical_document"),
                    ("https://hefa.p4theater.cn/work/forest-misremembered-someone", {}, "documented_current_edition_event_date_unknown")]
        for url, meta, status in fixtures:
            with self.subTest(url=url):
                item = sync.extract(html(url), url, None, {url: meta})
                self.assertEqual(item["status"], status)
                if meta:
                    self.assertEqual(item["author_scope"], "Joint proposal")
                    self.assertIn("提案", item["aliases"])

    def test_unicode_canonical_urls_are_verified_and_transport_safe(self):
        url = "https://p4theater.cn/articles/2026/2026-10-21-新文章/"
        encoded = sync.normalized_url(url)
        self.assertTrue(encoded.isascii())
        response = html(url); response["url"] = encoded
        item = sync.extract(response, encoded, None, {})
        self.assertEqual(item["url"], encoded)
        self.assertTrue(sync.eligible(encoded))

    def test_new_home_and_work_catalogues_have_directory_priority(self):
        for url in ["https://hefa.p4theater.cn/", "https://p4theater.cn/", "https://hefa.p4theater.cn/en/works/all"]:
            item = sync.extract(html(url), url, None, {})
            self.assertEqual(item["kind"], "directory")
            self.assertLess(item["priority"], 5)

    def test_new_page_discovery_is_bounded_and_canonical_validated(self):
        urls = [f"https://p4theater.cn/articles/2026/new-{i}/" for i in range(4)]
        get, calls = network({URL: html(), **{u: html(u) for u in urls}}, urls)
        candidate, cache, summary = sync.synchronize(payload(), {}, get=get, max_pages=3, max_new=2)
        self.assertEqual(summary["checked"], 3)
        self.assertEqual(summary["added"], 2)
        self.assertEqual(summary["remaining_discoverable"], 2)
        self.assertEqual(len(candidate["sources"]), 3)
        self.assertEqual(candidate["sources"][0], source())
        self.assertTrue(all(sync.safe_url(s["url"]) for s in candidate["sources"]))
        self.assertEqual(len(calls), len(sync.SEEDS) + 1 + 3)  # Sitemaps, work metadata, and bounded HTML pages.

    def test_classic_discovery_keeps_its_verified_host_and_historical_status(self):
        url = "https://p.p4theater.cn/articles/2026/classic-record/"
        get, _ = network({URL: html(), url: html(url)}, [url])
        candidate, _, summary = sync.synchronize(payload(), {}, get=get)
        item = next(item for item in candidate["sources"] if item["url"] == url)
        self.assertEqual(summary["added"], 1)
        self.assertEqual(item["site"], "p4")
        self.assertEqual(item["status"], "historical_document")
        wrong = html(url)
        wrong["body"] = wrong["body"].replace(url.encode(), b"https://p4theater.cn/articles/2026/classic-record/")
        with self.assertRaisesRegex(sync.SyncError, "canonical_mismatch"):
            sync.extract(wrong, url, None, {})

    def test_classic_failed_reviewed_source_keeps_previous_corpus(self):
        url = "https://p.p4theater.cn/articles/2026/classic-record/"
        old = payload()
        old["sources"][0].update(url=url, id="classic-reviewed", site="p4")
        before = json.dumps(old, sort_keys=True)
        get, _ = network({URL: html(), url: html(url, body="unusable")}, [url])
        with self.assertRaisesRegex(sync.SyncError, "reviewed_source_refresh_failed"):
            sync.synchronize(old, {}, get=get)
        self.assertEqual(json.dumps(old, sort_keys=True), before)

    def test_three_site_discovery_exceeds_old_cap_but_remains_bounded(self):
        urls = [f"https://p.p4theater.cn/articles/2026/record-{i}/" for i in range(2700)]
        get, _ = network(additional=urls)
        discovered, _ = sync.discover(get)
        self.assertEqual(len(discovered), 2701)
        with patch.object(sync, "MAX_DISCOVERED", 100), self.assertRaisesRegex(sync.SyncError, "discovery_limit_exceeded"):
            sync.discover(get)

    def test_unchanged_run_uses_conditional_seed_and_page_cache_without_churn(self):
        get, calls = network()
        candidate, cache, summary = sync.synchronize(payload(), {}, get=get)
        self.assertEqual(candidate, payload())
        self.assertFalse(summary["changed"])
        calls.clear()
        candidate, _, summary = sync.synchronize(candidate, cache, get=get)
        self.assertEqual(candidate, payload())
        self.assertFalse(summary["changed"])
        self.assertTrue(all(saved.get("etag") for _, saved in calls))

    def test_stale_page_validator_cannot_hide_updated_corpus(self):
        get, calls = network()
        cache = {"pages": {URL: {"etag": '"stable"', "text_sha256": "different-snapshot"}}}
        sync.synchronize(payload(), cache, get=get)
        self.assertIsNone(next(saved for url, saved in calls if url == URL))

    def test_public_alias_growth_preserves_reviewed_names_and_is_idempotent(self):
        rows = [{"zh": {"url": URL, "title": "New public alias", "titles": {"zh": "新公开名称", "en": "New public alias"}}}]
        get, _ = network(work_rows=rows)
        candidate, cache, summary = sync.synchronize(payload(), {}, get=get)
        item = candidate["sources"][0]
        self.assertTrue(summary["changed"])
        self.assertEqual(item["aliases"], [*source()["aliases"], "新公开名称", "New public alias"])
        for key in ("status", "author_scope", "source_note", "fetched_at", "sha256"):
            self.assertEqual(item[key], source()[key])
        unchanged, _, summary = sync.synchronize(candidate, cache, get=get)
        self.assertFalse(summary["changed"])
        self.assertEqual(unchanged, candidate)

    def test_existing_corpus_larger_than_run_cap_rotates_instead_of_starving(self):
        old = payload(); old["sources"] = []
        pages = {}
        for index in range(sync.MAX_PAGES + 3):
            item = source(); item.update(id=f"work-{index}", url=f"https://hefa.p4theater.cn/work/known-{index}")
            old["sources"].append(item); pages[item["url"]] = html(item["url"])
        get, calls = network(pages, list(pages))
        cache, checked = {}, set()
        for iteration in range(2):
            calls.clear()
            with patch.object(sync.time, "time", return_value=1000 + iteration):
                candidate, cache, summary = sync.synchronize(old, cache, get=get, max_new=0)
            checked.update(url for url, _ in calls if url in pages)
            self.assertLessEqual(summary["checked"], sync.MAX_PAGES)
            self.assertEqual(candidate, old)
        self.assertEqual(checked, set(pages))

    def test_invalid_new_candidates_rotate_and_do_not_starve_valid_articles(self):
        invalid = [f"https://hefa.p4theater.cn/reading/invalid-{i}" for i in range(5)]
        valid = "https://p4theater.cn/articles/2026/new-good/"
        pages = {URL: html(), valid: html(valid), **{u: html(u, body="short") for u in invalid}}
        get, calls = network(pages, [*invalid, valid])
        current, cache, visited = payload(), {}, set()
        for iteration in range(3):
            calls.clear()
            with patch.object(sync.time, "time", return_value=2000 + iteration):
                current, cache, _ = sync.synchronize(current, cache, get=get, max_pages=4, max_new=2)
            visited.update(url for url, _ in calls)
        self.assertTrue(set(invalid + [valid]).issubset(visited))
        self.assertIn(valid, {s["url"] for s in current["sources"]})

    def test_newly_discovered_release_beats_historical_backlog(self):
        backlog = [f"https://p4theater.cn/articles/2020/2020-01-01-old-{i}/" for i in range(4)]
        latest = "https://p4theater.cn/articles/2026/2026-10-21-latest/"
        pages = {URL: html(), **{u: html(u) for u in [*backlog, latest]}}
        get, calls = network(pages, [*backlog, latest])
        cache = {"discovered": [URL, *backlog]}
        candidate, _, summary = sync.synchronize(payload(), cache, get=get, max_pages=2, max_new=1)
        self.assertEqual(summary["added"], 1)
        self.assertIn(latest, {s["url"] for s in candidate["sources"]})

    def test_failed_existing_source_preserves_whole_previous_good_payload(self):
        old = payload()
        get, _ = network({URL: html(body="unusable")})
        with self.assertRaisesRegex(sync.SyncError, "reviewed_source_refresh_failed"):
            sync.synchronize(old, {}, get=get)
        self.assertEqual(old, payload())

    def test_failure_diagnostics_include_only_source_id_and_allowlisted_reason(self):
        get, _ = network()
        def failing(url, cache=None):
            if url == URL:
                raise RuntimeError("upstream-secret-or-body-must-not-be-logged")
            return get(url, cache)
        with patch("sys.stderr", new_callable=io.StringIO) as errors, self.assertRaises(sync.SyncError):
            sync.synchronize(payload(), {}, get=failing)
        diagnostic = json.loads(errors.getvalue())
        self.assertEqual(diagnostic, {"reviewed_source_failures": [{"id": "reviewed-work", "reason": "source_validation_failed"}]})
        self.assertNotIn("secret", errors.getvalue())

    def test_new_noindex_is_skipped_without_erasing_existing_sources(self):
        url = "https://p4theater.cn/articles/2026/not-public/"
        get, _ = network({URL: html(), url: html(url, head='<meta name="robots" content="noindex">')}, [url])
        candidate, _, summary = sync.synchronize(payload(), {}, get=get)
        self.assertEqual(candidate, payload())
        self.assertEqual(summary["skipped_new"], 1)

    def test_manual_priority_selects_new_published_url_without_cross_repo_access(self):
        url = "https://p4theater.cn/articles/2026/just-published/"
        get, calls = network({URL: html(), url: html(url)}, [])
        candidate, _, summary = sync.synchronize(payload(), {}, get=get, priority_urls=[url])
        self.assertEqual(summary["added"], 1)
        self.assertIn(url, {s["url"] for s in candidate["sources"]})
        with self.assertRaisesRegex(sync.SyncError, "invalid_priority_url"):
            sync.synchronize(payload(), {}, get=get, priority_urls=["https://evil.invalid/page"])

    def test_write_refreshes_matching_manifest_and_failure_leaves_files_intact(self):
        with tempfile.TemporaryDirectory() as temp:
            corpus, manifest, cache = [Path(temp) / name for name in ("corpus.json", "manifest.json", "cache.json")]
            sync.atomic_json(corpus, payload()); sync.atomic_json(manifest, {"old": True})
            before = corpus.read_bytes(), manifest.read_bytes()
            with patch.object(sync, "CORPUS", corpus), patch.object(sync, "MANIFEST", manifest), patch.object(sys, "argv", ["sync", "--write", "--cache", str(cache)]), patch("sys.stdout", new_callable=io.StringIO), patch.object(sync, "synchronize", side_effect=sync.SyncError("reviewed_source_refresh_failed")):
                self.assertEqual(sync.main(), 1)
            self.assertEqual((corpus.read_bytes(), manifest.read_bytes()), before)
            changed = payload(); changed["version"] = "next"
            with patch.object(sync, "CORPUS", corpus), patch.object(sync, "MANIFEST", manifest), patch.object(sys, "argv", ["sync", "--write", "--cache", str(cache)]), patch("sys.stdout", new_callable=io.StringIO), patch.object(sync, "synchronize", return_value=(changed, {}, {"changed": True})):
                self.assertEqual(sync.main(), 0)
            self.assertEqual(json.loads(manifest.read_text())["corpus_sha256"], sync.sha(corpus.read_bytes()))

    def test_manifest_write_failure_rolls_back_corpus(self):
        with tempfile.TemporaryDirectory() as temp:
            corpus, manifest, cache = [Path(temp) / name for name in ("corpus.json", "manifest.json", "cache.json")]
            sync.atomic_json(corpus, payload()); sync.atomic_json(manifest, {"old": True})
            previous = corpus.read_bytes(), manifest.read_bytes()
            changed = payload(); changed["version"] = "next"
            write = sync.atomic_json
            def fail_manifest(path, value):
                if path == manifest:
                    raise OSError("simulated filesystem failure")
                write(path, value)
            with patch.object(sync, "CORPUS", corpus), patch.object(sync, "MANIFEST", manifest), patch.object(sys, "argv", ["sync", "--write", "--cache", str(cache)]), patch("sys.stdout", new_callable=io.StringIO), patch.object(sync, "synchronize", return_value=(changed, {}, {"changed": True})), patch.object(sync, "atomic_json", side_effect=fail_manifest):
                self.assertEqual(sync.main(), 1)
            self.assertEqual((corpus.read_bytes(), manifest.read_bytes()), previous)


if __name__ == "__main__":
    unittest.main()
