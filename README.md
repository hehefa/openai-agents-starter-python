# 作品导览 / Works guide

A bilingual public-works guide for He Fa and P4 Theater, based on the existing EdgeOne Makers OpenAI Agents Python starter. It uses reviewed snapshots of the two official sites and links each factual answer to its source. The model is never given control of link destinations.

- App: `/`, with `?lang=zh|en&site=hefa|p4`.
- Compact iframe: `/?embed=1&site=hefa&lang=zh`.
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

`agents/_knowledge/corpus.json` contains public snapshot text, URLs, provenance hashes and attribution/status metadata. Only HTTPS URLs on `hefa.p4theater.cn` or `p4theater.cn` are accepted. Retrieval uses local Chinese bigrams, English terms, reviewed title aliases and BM25-style scoring; no vector service is used. Source HTML and fetched receipts are retained separately in the preparation package rather than shipped as public assets.

Import a replacement **reviewed** corpus and refresh the status manifest:

```sh
.venv/bin/python scripts/import_corpus.py /absolute/path/to/corpus.json
```

The server selects up to six evidence passages, then makes at most one bounded model run. The SDK receives no tools and no source URLs. Raw upstream output is buffered until paragraph-level evidence ids, URLs, named works, dates and relevant collective credits pass checks; validated text is then released as SSE chunks. Each source card's URL comes exclusively from the accepted corpus. These checks reduce fabrication; they do not amount to a formal semantic proof of every paraphrase. Public deployment evaluation should include factual reading of model answers.

The app declines unsupported private-life questions and frame-by-frame viewing claims. Fiction, collaborations, proposals, historical records and current identity must remain distinct. Prompt/evidence instructions are treated as untrusted text.

Limits: input 1,600 characters; six context messages / 3,600 characters; six passages / 11,500 source-text characters; model generation budget 2,400 tokens; one run turn; client automatic retries disabled; 45-second model deadline. Short conversation memory lives in sessionStorage; the app does not write new conversation history into the template's persistent store. Application tracing and sensitive logging are disabled. Platform-level operational retention remains governed by EdgeOne.

## Verify

```sh
.venv/bin/python -m unittest discover -s tests -v
npm run build
```

Tests make no provider calls. They include retrieval, attribution, unknown/private/fiction boundaries, input/context limits, citation/URL checks, cancellation, timeout, gateway failures, a real SDK stream against a loopback fake gateway and a reasoning-only length-finish reproduction. That reproduction demonstrates a possible SDK error path; the production exception type alone does not establish its exact cause. Deployment, public iframe embedding and real quota-limited model evaluation must be verified separately.
