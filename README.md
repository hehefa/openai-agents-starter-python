# 何发与P4作品导览助手 / Works Guide

按作品、项目或问题提问，回答附官方资料出处与原文链接。资料沿既有定时流程同步已发布网页。

**[何发作品导览](https://guide.p4theater.cn/?site=hefa&lang=zh) · [P4作品导览](https://guide.p4theater.cn/?site=p4&lang=zh) · [P4经典版导览](https://guide.p4theater.cn/?site=p4&collection=classic&lang=zh) · [English](https://guide.p4theater.cn/?site=p4&lang=en)**

[P4作品与档案总导航](https://github.com/hehefa/p4-theater) · [项目、来源与公开字幕](https://github.com/hehefa/-p4-theater-archive)


A bilingual public-works guide for He Fa and P4 Theater, based on the existing EdgeOne Makers OpenAI Agents Python starter. It uses reviewed snapshots of the two official sites and links each factual answer to its source. The model is never given control of link destinations.

- App: `/`, with `?lang=zh|en&site=hefa|p4`.
- Compact iframe: `/?embed=1&site=hefa&lang=zh`.
- Preserved P4 classic site: `/?embed=1&site=p4&collection=classic&lang=zh`. This keeps P4 branding and a separate browser-session history, while preferring verified `p.p4theater.cn` evidence. The optional `collection` field is also accepted by `POST /chat`; existing callers remain unchanged and do not mix in classic-site records. An original main-site URL is never rewritten into a classic-site citation without fetching that classic page.
- Explicit model-free quotation check: add `&mode=extract`. This quotes evidence and labels its limits; it does not silently replace a failed model answer.
- `POST /chat`: bounded SSE answer; `POST /chat/stop`: cancel the actual upstream run.
- `GET /guide-status`: read-only deployment check, no model call; includes snapshot version/count/hash, model id, gateway hostname and a configuration boolean. No secrets are returned.

## Run locally

```sh
npm ci
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm run dev:agents
```

The existing gateway variables are `AI_GATEWAY_API_KEY`, `AI_GATEWAY_BASE_URL` and optional `AI_GATEWAY_MODEL`. Runtime `context.env` takes precedence over OS environment. The original model default remains `@makers/deepseek-v4-flash`; this app does not create a key, subscribe to a service or choose another provider. Missing configuration and upstream failures produce a readable retry state. Using any deployed model remains subject to that project's actual quota and pricing.

## Knowledge and response boundary

`agents/_knowledge/corpus.json` contains public snapshot text, URLs, provenance hashes and attribution/status metadata. Only HTTPS URLs on `hefa.p4theater.cn`, `p4theater.cn` or `p.p4theater.cn` are accepted. Retrieval uses local Chinese bigrams, English terms, reviewed title aliases and BM25-style scoring; no vector service is used. Source HTML and fetched receipts are retained separately in the preparation package rather than shipped as public assets. Embedding and Escape-to-close are restricted to those three exact official origins, plus the existing local development behavior.

Import a replacement **reviewed** corpus and refresh the status manifest:

```sh
.venv/bin/python scripts/import_corpus.py /absolute/path/to/corpus.json
```

### Automatic public-source sync

`.github/workflows/sync-public-knowledge.yml` runs at minute 17 of each hour and supports manual `workflow_dispatch`. It uses the repository's own `GITHUB_TOKEN` with `contents: write`; no PAT, cross-repository access, model request, paid supplier or installed crawler dependency is needed. GitHub may delay scheduled runs. The workflow has a three-minute limit and does not enable paid billing. Usage remains subject to the account's current GitHub Actions terms.

The sync reads the three public `sitemap.xml` files and He Fa's public `data/works.json`, then verifies HTML, one matching canonical, indexing eligibility and a substantial `main`/`article` body. Discovery accepts their homepages, He Fa work/catalogue/reading/reference/profile routes, the fiction-project index and its twelve bilingual encounters, plus current and classic P4 knowledge/profile/project routes or individual dated articles. The separate historical-role archive is excluded; the fiction index and encounters retain their fiction labels. Newly added home/work-directory records have low retrieval priority. Archive/year indexes, arbitrary assets, queries, off-site URLs and redirects outside the three approved hosts are excluded. Chinese URL paths are encoded for transport and canonical comparison. Existing reviewed records remain eligible even if absent from a sitemap.

Each run checks at most 256 pages and admits at most 32 new pages, with a 135-second fetch budget. Current identity/reference/film pages and changed `lastmod` entries take precedence; larger corpora rotate through remaining records. Newly discovered URLs take precedence over the previously seen backlog; remaining new candidates use recent `lastmod`/article dates first. Invalid new candidates rotate by their check time, so they cannot monopolize the same batch forever. Historical/fiction/proposal distinctions remain intact. The report includes remaining discovery and refresh counts. An optional `priority_urls` dispatch input prioritizes known public canonical URLs immediately after a site release. It does not grant access to other hosts or paths.

Discovery stops safely above 5,000 total URLs rather than allowing an unbounded crawl; the page/new-page/time/response-size limits remain unchanged. Deploy this three-site configuration only after the classic domain, certificate and canonical sitemap are publicly available: a failed seed safely stops the batch and retains the last good corpus. The schedule and token behavior follow [GitHub's event documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) and [workflow-trigger rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

Conditional sitemap/metadata/page requests use ETag/Last-Modified in an optional Actions cache. Cache checks/timestamps are never committed. Navigation, floating guide controls, scripts and forms are excluded; whitespace or navigation-only changes retain the exact old record. Reviewed metadata, roles, status and source notes remain intact during automatic body refreshes. Existing aliases are retained and new public catalogue aliases are appended, including for an unchanged HTML page. New work metadata comes from the public work catalogue; new archive articles retain historical status, and He Fa's historical fantasy remains fiction. Reclassification of reviewed metadata remains an editorial operation through the reviewed-corpus import.

A missing, noindex, noncanonical, unusually short or failed existing page aborts the batch and retains the entire previous corpus. Diagnostic stderr contains only source ids and fixed failure reasons, without response text or exceptions. Invalid new pages are skipped rather than replacing reviewed material. A successful content change updates text/raw-byte hashes and the matching deployment manifest, then commits only those two knowledge files. An old `raw_path` is removed when its HTML is replaced, because the original preparation receipt cannot attest new bytes. Concurrent pushes are never force-pushed; a conflict safely fails and the next run starts from current `main`.

For a local preview (public HTTP only, no corpus write):

```sh
python3 scripts/sync_corpus.py
python3 -m unittest discover -s tests -p test_sync_corpus.py -q
```

Add `--write` to update the local corpus and status manifest. After a bot commit, verify that EdgeOne actually created a successful deployment for that commit and that `/guide-status` matches the repository manifest. GitHub's token push does not trigger other Actions workflows; delivery to EdgeOne's separate Git integration must be verified, not assumed. Pull the resulting bot commit before running live QA, whose corpus count/hash preflight follows the local repository rather than a fixed count of 197.

The server selects up to six evidence passages, then makes at most one bounded model run. The SDK receives no tools and no source URLs. Raw upstream output is buffered until paragraph-level evidence ids, URLs, named works, dates and relevant collective credits pass checks; validated text is then released as SSE chunks. Each source card's URL comes exclusively from the accepted corpus. These checks reduce fabrication; they do not amount to a formal semantic proof of every paraphrase. Public deployment evaluation should include factual reading of model answers.

The app declines unsupported private-life questions and frame-by-frame viewing claims. Fiction, collaborations, proposals, historical records and current identity must remain distinct. Prompt/evidence instructions are treated as untrusted text.

Limits: input 1,600 characters; six context messages / 3,600 characters; six passages / 11,500 source-text characters; model generation budget 2,400 tokens; one run turn; client automatic retries disabled; 45-second model deadline. Short conversation memory lives in sessionStorage; the app does not write new conversation history into the template's persistent store. Application tracing and sensitive logging are disabled. Platform-level operational retention remains governed by EdgeOne.

The request uses DeepSeek's documented `thinking: {type: "disabled"}` via SDK `extra_body`. Loopback tests verify serialization; Makers gateway forwarding and the effect on the built-in model require live verification. SDK behavior failures log only a finite classification, never raw reasoning, answers or exception bodies.

## Verify

```sh
.venv/bin/python -m unittest discover -s tests -v
npm run build
```

Tests make no provider calls. They include retrieval, attribution, unknown/private/fiction boundaries, input/context limits, citation/URL checks, cancellation, timeout, gateway failures, a real SDK stream against a loopback fake gateway and a reasoning-only length-finish reproduction. That reproduction demonstrates a possible SDK error path; the production exception type alone does not establish its exact cause. Deployment, public iframe embedding and real quota-limited model evaluation must be verified separately.

## Code and source-material rights

Code follows the existing [MIT LICENSE](LICENSE), including retained upstream notices. The works corpus keeps its original authors, attribution and source links; the code licence does not change the rights in those texts or artworks.
