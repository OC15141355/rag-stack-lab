# Clio-style insights: reading one and deploying one

## In one paragraph

A Clio-style insights service reads the conversations that people have with a chat system, has a language model boil each one down to a short de-identified summary, groups similar summaries, names the groups, and shows analysts only the named groups and their sizes. This document is the practical companion to [17-clio-conversation-insights.md](17-clio-conversation-insights.md), which explains what Clio is and why it is built that way; read that first and do not expect it to be repeated here. The aim here is narrower. First, you should be able to look at an in-house Clio-style service running on Kubernetes, next to a chat portal that serves self-hosted models through OpenAI-compatible endpoints, and work out how it is configured, even without permission to read its ConfigMap. Second, you should be able to interpret its output without over-trusting it. Third, you should be able to stand up a small one yourself in a lab, using synthetic conversations and the open-source Kura library, and wrap it in a CronJob. The section on governance closes the loop: this thing reads every user's chats, so the controls matter as much as the clustering.

## The plain version

Picture a post office sorting room. Thousands of letters arrive daily. The manager does not want anyone reading the letters, but does want to know what people are writing about: birthday cards, bills, complaints, job applications. So a clerk skims each letter and writes a one-line note with no names on it. Another clerk lays the notes out on a table and slides similar ones into piles. A third clerk writes a label on each pile. The manager only ever sees labelled piles with counts, and any pile with only a couple of notes is thrown away because a tiny pile can point at one person.

A Clio-style service is that sorting room. The skimming clerk, the pile-maker and the labeller are mostly the same kind of thing: a language model, a text-to-numbers model, and a grouping algorithm. Each has settings (which model, how many piles, how small is too small, how often to run). Those settings are what a ConfigMap holds, so reading the settings tells you what the room actually does.

What this document gives you is a map from "setting name" to "what it changes", a list of questions for the person who built it, a way to learn a lot about a deployment without seeing its ConfigMap, and a lab recipe for building a small one.

Five things to remember:

- Every stage is a dial. Model choice, group count, minimum group size and schedule decide what you see, so a result without its settings is hard to interpret.
- Labels are written by a model. They are hypotheses about a group, not facts; check a label by reading a sample of what is inside.
- Missing groups are not missing activity. Small groups are suppressed on purpose, and the input may be a sample.
- You can learn a lot read-only: env var names, image tags, schedules and the project's own default config are visible even when ConfigMap values are not.
- Kura, the lab choice here, has no built-in minimum-users threshold or privacy auditor, so you add those yourself; that is also a useful warning about any in-house system.

## Anatomy of a pipeline as deployable parts

*Each stage of a Clio-style pipeline is one deployable part with its own settings, and the settings are what you would expect to see in a ConfigMap or environment.*

Names below are typical, not guaranteed; the in-house service may call them anything. The point of the "what it changes" column is that you can recognise the knob under a different name.

| Part | Typical knobs (names you may meet) | What the knob changes |
|---|---|---|
| **Conversation source** (portal database or gateway logs) | `DB_HOST`/`DATABASE_URL` (usually in a Secret), `SOURCE_TABLE`, `LOOKBACK_DAYS` or `SINCE`, `MAX_CONVERSATIONS`, `SAMPLE_RATE`, `EXCLUDE_USERS`/`EXCLUDE_TAGS`, `MIN_TURNS` | Which conversations are even eligible. `SAMPLE_RATE` below 1.0 means every count you see is a fraction of reality. A lookback window sets how far back one run reaches. Exclusions may remove test accounts or opted-out users. |
| **Facet / summary extraction** (LLM call per conversation) | `SUMMARY_MODEL`, `LLM_BASE_URL`/`OPENAI_BASE_URL`, `LLM_API_KEY` (Secret), `SUMMARY_PROMPT` or prompt file, `TEMPERATURE`, `MAX_CONCURRENT_REQUESTS`, `MAX_INPUT_TOKENS`, `FACETS` | The model doing the reading, which is the biggest quality and privacy lever. The prompt decides what is kept or dropped (names, emails, companies). Concurrency trades speed against stealing GPU time from chat. Input truncation decides whether long conversations are summarised from their start only. Facets decide which questions get asked of each conversation (task, language, a safety score). |
| **Embedding** | `EMBEDDING_MODEL`, `EMBEDDING_BASE_URL`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_DIM` | What "similar" means. A different embedding model re-sorts everything, so changing it makes results non-comparable with earlier runs. Batch size matters for throughput on the embedding endpoint. |
| **Clustering** | `CLUSTER_METHOD` (`kmeans`/`hdbscan`), `N_CLUSTERS` or `CLUSTERS_PER_GROUP`/`TARGET_CLUSTER_SIZE`, `MIN_CLUSTER_SIZE` (HDBSCAN), `RANDOM_SEED`, `UMAP_N_COMPONENTS` | Granularity. With k-means the number of clusters is chosen by the operator, often as items divided by a target size; too few merges themes, too many splits them. HDBSCAN chooses its own number and labels outliers as noise, so `MIN_CLUSTER_SIZE` is its main dial. A fixed seed makes runs repeatable; without one, clusters shift between runs. |
| **Cluster labelling** (LLM) | `LABEL_MODEL`, `LABEL_TEMPERATURE`, `SAMPLES_PER_CLUSTER`, `CONTRASTIVE_SAMPLES`, `LABEL_PROMPT`, `MAX_LABEL_WORDS` | Name quality. More samples gives more representative labels but longer prompts. Contrastive samples (examples from outside the cluster) make labels more specific. A bigger model here than in the summary step is normal. |
| **Hierarchy building** | `LEVELS`/`TOP_LEVEL_CLUSTERS`, `NEIGHBOURHOOD_SIZE`/`CHILDREN_PER_PARENT`, `META_MODEL` | How many layers the tree has and how coarse the top is. Fewer, broader top-level groups read more easily and hide more detail. |
| **Privacy layers** | `MIN_UNIQUE_USERS`, `MIN_CONVERSATIONS`, `PII_STRIP` (prompt flag), `AUDITOR_MODEL`, `AUDITOR_MIN_SCORE`, `REDACT_PATTERNS` (regexes) | Whether a group is shown at all. The user threshold is the main anti-re-identification control; the conversation threshold is weaker because one heavy user can fill a group. The auditor drops groups whose name or description looks identifying. Regex redaction is a cheap backstop for emails and phone numbers. |
| **Storage** | `OUTPUT_DIR`/`OUTPUT_URI`, `S3_BUCKET`, `PGSCHEMA`/`RESULTS_TABLE`, `STORE_SUMMARIES`, `STORE_RAW`, `RETENTION_DAYS` | Where the output lives and what survives. `STORE_RAW=true` would mean the service is building a second copy of the chats, which is a red flag. Retention decides how long summaries remain. |
| **UI or report** | `UI_ENABLED`, `REPORT_FORMAT` (html/json/dashboard), `AUTH_*`/OIDC settings, `INGRESS_HOST`, `ALLOWED_GROUPS` | Who can see the results and in what form. A static HTML report in a bucket and an authenticated web app have very different exposure. |
| **Scheduling** | `schedule:` on a CronJob, `concurrencyPolicy`, `startingDeadlineSeconds`, `activeDeadlineSeconds`, `backoffLimit`, `priorityClassName`, resource requests; or a Deployment with an internal `RUN_INTERVAL` | When it runs and what it can disturb. A CronJob with `concurrencyPolicy: Forbid` and a low priority class is the polite shape for sharing GPUs with chat. A long-running service suggests an on-demand UI or incremental processing. |
| **Checkpoint / cache** | `CHECKPOINT_DIR`, `CACHE_DIR`, `RESUME` | Whether a re-run reuses earlier summaries. A cache makes runs cheap but means summaries persist on disk, which counts as stored data. |

Two reading tips. First, anything that ends in `_MODEL` tells you which model touches the data at that step; there may be two or three different ones. Second, privacy knobs that are absent are informative: if there is no `MIN_UNIQUE_USERS` or auditor setting anywhere, assume the stage does not exist until the developer says otherwise.

## Interpreting the output

*A cluster tree is a set of model-written headlines with counts; useful for spotting patterns, unreliable as a measurement until you have sampled what sits under a headline.*

**Reading the hierarchy.** Top-level clusters are broad (for example "software development and debugging"); each splits into narrower children, down to leaf clusters that are the actual groups of summaries. Bigger area on a map or bigger bar means more conversations (or more users, check which), not more importance. Look at the sibling structure too: if one parent has 30 children and another has 2, the hierarchy-building step, not the users, may be why.

**Facets and sizes.** A facet is a per-conversation attribute (language, task type, a "concerning" score, turn count). Read facet breakdowns as shares of the conversations that were analysed. Always find the denominator: how many conversations were analysed, over what window, after what exclusions and sampling. A cluster of 400 means very different things out of 1,000 and out of 100,000. Also check whether size counts conversations or distinct users; heavy users inflate the first.

**Common misreadings.**

- **Labels are model-written.** A label is a model's guess from a sample of summaries. It can be too broad, too narrow, flattering, or simply wrong, and a different seed or labelling model could name the same group differently. Treat it as a hypothesis.
- **Absent does not mean absent.** Clusters below the minimum-users threshold are removed, and with HDBSCAN outliers are labelled noise and never named. A genuine but rare use will not appear. The paper's authors themselves say rare events are detected poorly.
- **Sampling bias.** If the job samples, or only reads conversations from a window, a cluster may reflect who was active that fortnight. Portal users are also not all users; people who dislike being analysed may stop using the portal, or never started.
- **Summaries are second-hand.** Hallucination or flattening in the summary step propagates into every later step. Weaker models and non-English text make this worse.
- **Embedding artefacts.** Embeddings can group by tone, length or language rather than task. A cluster named "polite requests" may be a style cluster, not a topic.
- **Run-to-run drift.** Without a fixed seed and stable model versions, a cluster may split or merge between runs, so a "trend" can be a relabelling.
- **Causation.** "The summarisation cluster grew 40%" says nothing about why. It says something changed in what was summarised or how it was grouped.

**Validating a cluster by sampling.** Where the service lets you (or its developer can do it for you):

1. Pick a cluster that matters for a decision. Ask for 20 to 30 random summaries from it, not the nearest-to-centre ones, which are the flattering examples.
2. Read them against the label. Count how many fit. If under about 80% obviously belong, the label is poor or the cluster is a mixture.
3. Ask for 10 summaries from the sibling cluster and check you can tell the two apart; if not, k may be too high.
4. Check that no summary contains an identifying detail. Any leak means the summary prompt needs work and the case should go to the owner.
5. Compare the label with a second naming pass (a different seed or model). If the two disagree widely, the cluster is fuzzy.
6. For a count that will appear in a report, ask what the confidence is and how many users, not just conversations, are inside.

This is a human check on summaries, not on raw conversations; the point of the system is that you should not need the raw text.

## Questions to ask the developer

*A short list of questions that turns "I cannot read the ConfigMap" into an informed conversation.*

**Data source and scope**

- Which table or log does it read? Whole conversations or only the first turns? Are system prompts and uploaded files included?
- Which users and conversations are in scope, and what is excluded (test accounts, opted-out users, certain projects)?
- Is it sampling? At what rate, and is the sample uniform?
- Does it read the portal database directly, or the gateway's logs? Which credentials, and are they read-only?

**Retention and storage**

- What is stored per conversation (summary, facets, embedding, user id)? Is any raw text copied?
- How long are summaries, embeddings and checkpoints kept? Where, and who can read them?
- Is there a cache that persists summaries between runs?

**Models**

- Which model writes the summaries? Which names the clusters? Which does the privacy audit? Which produces embeddings? Are any of them outside the cluster?
- Have any of those model versions changed since the first run? What happens to historical comparability?
- Were the summary and audit steps validated against a labelled sample, and how?

**Privacy thresholds**

- What are the minimum unique users and minimum conversations per cluster? Is the user count of distinct users or just conversations?
- Is there an auditor step, with what pass mark? What happens to a failing cluster (dropped, flagged, logged)?
- How are users identified (pseudonymous id, hashed id)? Who holds the mapping?
- With the actual user population, what share of clusters does the threshold remove?

**Schedule and operations**

- CronJob or service? How often? What window does each run cover? Does a run reprocess or only add new conversations?
- What priority and resource limits does it run with, and does it share GPUs with chat?
- How are failures noticed? What happens on a partial run?

**Output and access**

- Where does the output go (bucket, database, dashboard, static page)? In what format?
- Who can see aggregates? Who, if anyone, can see raw conversations or per-user drill-down, and is that access logged?
- Is there a defined purpose (usage understanding, misuse monitoring) and a written policy? Are users told?
- Can a cluster be traced back to the conversations in it, and who is allowed to do that?

## Reading it without ConfigMap access

*Kubernetes permissions are granular, so you can often see how a workload is wired while being unable to read its configuration values.*

What you can usually learn read-only, in this order of value:

1. What kind of workload it is and when it runs.
2. Which image and tag it uses.
3. The names of environment variables and which ConfigMap or Secret each comes from.
4. The repository's own defaults.
5. Logs, if permitted.

Replace `<ns>` with the namespace.

```bash
# What is there? Workload kinds, schedule, services
kubectl get deploy,statefulset,cronjob,job,svc,ingress -n <ns>

# Schedule and recent runs
kubectl get cronjob -n <ns> -o wide
kubectl get jobs -n <ns> --sort-by=.metadata.creationTimestamp

# The pod template: image, command, args, resources, env var names, volumes
kubectl describe cronjob <name> -n <ns>
kubectl describe deploy <name> -n <ns>

# Compact view of just the image and env names (read-only)
kubectl get cronjob <name> -n <ns> \
  -o jsonpath='{.spec.schedule}{"\n"}{.spec.concurrencyPolicy}{"\n"}{range .spec.jobTemplate.spec.template.spec.containers[*]}{.image}{"\n"}{end}'

kubectl get cronjob <name> -n <ns> -o json \
  | jq '.spec.jobTemplate.spec.template.spec.containers[] | {image, args, envFrom, env: [.env[]? | {name, from: (.valueFrom // .value)}]}'
```

In the `describe` output, look at three places:

- **Image and tag.** `registry/clio-insights:1.4.2` tells you the version to look up in the repo; `:latest` tells you results may change without anyone editing config. A digest (`@sha256:...`) pins it exactly.
- **Environment.** Entries such as `SUMMARY_MODEL: <set to the key 'summary_model' of config map 'insights-config'>` show the variable name and which ConfigMap supplies it, but not the value. `envFrom` shows only the ConfigMap name; the keys inside stay hidden. Inline `value:` entries are shown in full.
- **Volumes and mounts.** A PVC means output or cache lives on disk; a mounted ConfigMap or Secret may hold a prompt file; `emptyDir` means outputs are lost unless pushed elsewhere.

```bash
# Logs, if your role allows pods/log
kubectl logs -n <ns> job/<latest-job> --tail=200
kubectl logs -n <ns> deploy/<name> --since=1h

# What am I allowed to do here?
kubectl auth can-i --list -n <ns>
kubectl auth can-i get configmaps -n <ns>
kubectl auth can-i get secrets -n <ns>
```

**Why you can see a pod spec but not ConfigMap data.** Kubernetes RBAC grants are per resource type, per verb. A role with `get`/`list` on `pods`, `deployments` and `cronjobs` shows the pod template, which contains env var names and the names of the ConfigMaps they reference, because that is part of the workload object. The ConfigMap's data lives in a separate resource, `configmaps`, which needs its own grant. A role without it gets `Forbidden` on `kubectl get configmap`. The same applies to Secrets. `kubectl describe` on a pod also resolves nothing from the ConfigMap; it only prints the reference. The reverse is also true: someone with `configmaps` access but not `deployments` can read values without knowing which workload consumes them. Cluster-level aggregate roles such as `view` deliberately exclude Secrets, and some platforms exclude ConfigMaps in sensitive namespaces too.

Log content is the other open door: services often log their effective config at start-up (model names, thresholds, window) and summarise each run (conversations read, summaries made, clusters kept, clusters suppressed). Do not assume logs are safe to read; they should not contain conversation text, and if they do, report that to the owner rather than copying it.

**The repository is the second source.** The image tag identifies the version; the repo for that version usually has `.env.example`, a settings class (for example a Pydantic `BaseSettings` whose field names map to env vars), a Helm `values.yaml` or a default `config.yaml`, and the prompt files. Compare the env var names from `describe` with the settings class: any variable named in the pod spec is overriding a default, and any default not overridden is what the service uses. That gives you almost a full picture of the configuration, minus the overridden values, and you can then ask the developer a very specific question ("is `MIN_UNIQUE_USERS` still the default of 10, or overridden to something else?").

What you will not learn this way: the values of overridden settings, the Secret contents, the actual prompt text if it is a mounted file, and whether the running code matches the repo at that tag.

## Deploying one in a lab

*Use Kura to run the whole pipeline once over made-up conversations, then wrap that run in a CronJob with a ConfigMap, a Secret and a volume for the output.*

### Choosing Kura over OpenClio

Findings checked on 2026-11-18 via the GitHub API and package pages:

| | Kura (`jxnl/kura`, formerly `567-labs/kura`) | OpenClio (`Phylliida/OpenClio`) |
|---|---|---|
| Licence | MIT per the repo page (the API returned no licence field) | MIT |
| Last push to default branch | 2025-09-10 | 2025-08-19 |
| Stars | 541 | 97 |
| Package | PyPI `kura` 0.5.4, 2025-09-09 | install from git only |
| Pipeline | summarise, base clusters (k-means), meta-clusters, UMAP projection, checkpoints | facets, embed, cluster, hierarchy, static HTML site |
| LLM backend | `instructor` provider strings (default `openai/gpt-4o-mini`) | vLLM in-process (example `Qwen/Qwen3-8B`) |

Neither has seen a commit in about 14 months, so treat both as frozen code to pin, not live projects. Kura is chosen because it is a normal Python package with a stable step-by-step API, checkpoints that make a CronJob cheap to resume, a CLI, and a design where the LLM is reached over the OpenAI protocol, which suits a gateway or NIM endpoint. OpenClio runs the model inside its own process through vLLM, which does not fit an already-deployed endpoint, though its static HTML output and facet prompts are worth reading. UNVERIFIED: whether OpenClio can be pointed at a remote OpenAI-compatible server rather than loading vLLM locally.

What Kura does not have, from reading its source: no `base_url` parameter on `SummaryModel`, `ClusterDescriptionModel` or `OpenAIEmbeddingModel` (the OpenAI client is created with no arguments, so the OpenAI SDK's environment variables apply), no minimum-users threshold, and no privacy auditor. Its PII protection is the instruction in the summary prompt. You will add a user threshold yourself below.

UNVERIFIED: that `instructor.from_provider("openai/<model>", async_client=True)` honours `OPENAI_BASE_URL` and strips the `openai/` prefix when talking to a non-OpenAI server. It builds an OpenAI client, which normally reads the variable, but test it with the smoke call below. UNVERIFIED: that your chat model supports the structured/tool-call output instructor uses by default; a model that cannot return valid structured output will make the summary step fail or retry.

### Runbook

Prerequisites: Python 3.10 or later, `uv`, and an OpenAI-compatible endpoint that serves both a chat model and an embedding model. In the lab this is the gateway, or a local server such as Ollama, which exposes `/v1/chat/completions` and `/v1/embeddings`.

**1. Project and pin.**

```bash
mkdir -p ~/lab/clio-lab && cd ~/lab/clio-lab
uv init --python 3.12 --no-readme
uv add "kura==0.5.4" rich
```

Expected: `uv` creates `pyproject.toml` and resolves roughly a hundred packages (scikit-learn, umap-learn, hdbscan, instructor, FastAPI and others). The first run is slow because `hdbscan` and `umap-learn` pull in numba and compiled wheels.

**2. Point the OpenAI SDK at your endpoint.**

```bash
export OPENAI_BASE_URL="http://localhost:11434/v1"     # or the gateway's /v1
export OPENAI_API_KEY="lab-key"                         # any non-empty value for Ollama
export SUMMARY_MODEL="openai/qwen3:8b"                  # provider prefix + served model name
export EMBED_MODEL="nomic-embed-text"                   # the embedding model name on that endpoint
```

Smoke test both routes before running anything big:

```bash
curl -s "$OPENAI_BASE_URL/models" -H "Authorization: Bearer $OPENAI_API_KEY" | head -c 300
curl -s "$OPENAI_BASE_URL/embeddings" -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$EMBED_MODEL\",\"input\":\"hello\"}" | head -c 200
```

Expected: a JSON list of models, then an embedding response beginning `{"object":"list","data":[{"object":"embedding","embedding":[...`. For a retrieval NIM, UNVERIFIED: it may additionally require an `input_type` field (query or passage), which Kura's embedding client does not send, so that NIM would fail unless you wrap it.

**3. Generate synthetic conversations.** Never test on real chats. This script writes 300 invented conversations from 6 topics across 40 fake users, with one topic deliberately used by only 2 users so you can watch suppression work.

```python
# gen_synthetic.py
import json, random
from datetime import datetime, timedelta, timezone

random.seed(7)
TOPICS = {
    "sql": ["How do I fix a slow SQL JOIN on two large tables?",
            "Explain window functions in SQL with an example.",
            "Why does my GROUP BY return duplicate rows?"],
    "python": ["Write a Python function to parse a CSV and plot a column.",
               "How do I use asyncio.gather with a rate limit?",
               "Why is my list comprehension raising a KeyError?"],
    "cv": ["Help me tidy the summary section of my CV.",
           "Write a cover letter for a logistics coordinator role.",
           "Give feedback on my LinkedIn about paragraph."],
    "email": ["Make this email to a supplier shorter and more polite.",
              "Rewrite my meeting follow-up to sound friendlier.",
              "Draft a reminder about an unpaid invoice, firm but kind."],
    "k8s": ["Why does my pod stay in Pending?",
            "How do I read a CrashLoopBackOff event?",
            "Explain requests versus limits for memory."],
    "poetry": ["Write a short poem about autumn rain.",
               "Help me with a haiku about a missed train."],   # rare topic
}
WEIGHTS = {"sql": 5, "python": 6, "cv": 4, "email": 5, "k8s": 4, "poetry": 1}
users = [f"u{i:02d}" for i in range(40)]
poetry_users = users[:2]

out = []
now = datetime(2026, 11, 1, tzinfo=timezone.utc)
for n in range(300):
    topic = random.choices(list(WEIGHTS), weights=WEIGHTS.values())[0]
    user = random.choice(poetry_users if topic == "poetry" else users)
    q = random.choice(TOPICS[topic])
    t = now + timedelta(minutes=n * 17)
    out.append({
        "chat_id": f"c{n:04d}", "user_id": user, "topic": topic,
        "created_at": t.isoformat(),
        "messages": [
            {"role": "user", "content": q, "created_at": t.isoformat()},
            {"role": "assistant", "content": "(synthetic answer)",
             "created_at": (t + timedelta(seconds=5)).isoformat()},
        ],
    })
json.dump(out, open("synthetic.json", "w"), indent=1)
print(len(out), "conversations,", len({c["user_id"] for c in out}), "users")
```

```bash
uv run python gen_synthetic.py
```

Expected: `300 conversations, 40 users` (the user count may be slightly lower).

**4. The pipeline.** This follows Kura's published quickstart, swapping the dataset for the synthetic file and adding a post-filter that applies a minimum-unique-users rule. The embedding model is passed explicitly because the default is OpenAI's `text-embedding-3-small`.

```python
# run_pipeline.py
import asyncio, json, os, sys
from collections import defaultdict
from datetime import datetime
from rich.console import Console
from kura.cache import DiskCacheStrategy
from kura.summarisation import summarise_conversations, SummaryModel
from kura.cluster import (generate_base_clusters_from_conversation_summaries,
                          ClusterDescriptionModel)
from kura.embedding import OpenAIEmbeddingModel
from kura.meta_cluster import reduce_clusters_from_base_clusters, MetaClusterModel
from kura.dimensionality import reduce_dimensionality_from_clusters, HDBUMAP
from kura.types import Conversation, Message
from kura.checkpoints import JSONLCheckpointManager

IN = sys.argv[1]
OUT = sys.argv[2]
MIN_USERS = int(os.environ.get("MIN_UNIQUE_USERS", "5"))
MODEL = os.environ["SUMMARY_MODEL"]
EMBED = os.environ["EMBED_MODEL"]
CONC = int(os.environ.get("MAX_CONCURRENT_REQUESTS", "8"))

async def main():
    console = Console()
    raw = json.load(open(IN))
    owner = {c["chat_id"]: c["user_id"] for c in raw}
    convs = [Conversation(
        chat_id=c["chat_id"],
        created_at=datetime.fromisoformat(c["created_at"]),
        messages=[Message(created_at=datetime.fromisoformat(m["created_at"]),
                          role=m["role"], content=m["content"])
                  for m in c["messages"]],
        metadata={},               # keep user ids OUT of what the LLM sees
    ) for c in raw]

    ckpt = JSONLCheckpointManager(f"{OUT}/checkpoints", enabled=True)
    summaries = await summarise_conversations(
        convs,
        model=SummaryModel(model=MODEL, max_concurrent_requests=CONC,
                           console=console,
                           cache=DiskCacheStrategy(cache_dir=f"{OUT}/.summary")),
        checkpoint_manager=ckpt)
    clusters = await generate_base_clusters_from_conversation_summaries(
        summaries,
        model=ClusterDescriptionModel(model=MODEL, max_concurrent_requests=CONC,
                                      console=console),
        embedding_model=OpenAIEmbeddingModel(model_name=EMBED),
        checkpoint_manager=ckpt)
    meta = await reduce_clusters_from_base_clusters(
        clusters, model=MetaClusterModel(model=MODEL, console=console),
        checkpoint_manager=ckpt)
    projected = await reduce_dimensionality_from_clusters(
        meta, model=HDBUMAP(), checkpoint_manager=ckpt)

    # Privacy gate Kura does not provide: count distinct users per cluster.
    # UNVERIFIED: the cluster object exposes .chat_ids, .name, .description.
    report, hidden = [], 0
    for c in clusters:
        users = {owner[i] for i in c.chat_ids}
        if len(users) < MIN_USERS:
            hidden += 1
            continue
        report.append({"name": c.name, "description": c.description,
                       "conversations": len(c.chat_ids), "users": len(users)})
    report.sort(key=lambda r: -r["conversations"])
    json.dump({"min_unique_users": MIN_USERS, "hidden_clusters": hidden,
               "clusters": report}, open(f"{OUT}/report.json", "w"), indent=1)
    console.print(f"{len(report)} clusters shown, {hidden} suppressed")

asyncio.run(main())
```

**5. Run it.**

```bash
mkdir -p out
uv run python run_pipeline.py synthetic.json out
```

Expected: progress bars for summarising (300 calls) and cluster naming (about 30 clusters, since Kura's default k-means makes `ceil(n / 10)` clusters), then `NN clusters shown, M suppressed`. A small 8B model on a laptop may take several minutes. Look at `out/checkpoints/` (JSONL files for each stage; UNVERIFIED: the exact filenames, expected to resemble `summaries`, `clusters`, `meta_clusters`, `dimensionality`) and `out/report.json`.

**6. Check the output like an analyst.** Expect labels such as "Troubleshooting Kubernetes pod scheduling" and "SQL query performance and joins". Check that the two-user poetry group is absent from `report.json` (it was suppressed by the threshold) and that it appears in `hidden_clusters`. Open five summaries from one cluster in the `summaries` checkpoint and judge them against the label as described above. Expect some clusters to be near-duplicates of each other: with 30 clusters over six topics, k is too high for this data, a good demonstration of the k choice. Re-run with the same input; the disk cache and checkpoints should make it finish in seconds. UNVERIFIED: that a re-run reuses all checkpoints rather than recomputing some stages.

Kura also ships a `kura` CLI and a web app (the entry point is `kura.cli.cli:app`); UNVERIFIED: its subcommands and whether the app reads these checkpoint files without extra steps. Read the docs for the pinned version before relying on it.

### Packaging as a Kubernetes CronJob

The container image holds the code and dependencies only. Configuration goes in a ConfigMap, the endpoint key in a Secret, and output on a PVC. Build the image first.

```dockerfile
# Dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY run_pipeline.py gen_synthetic.py ./
USER 10001:10001
ENTRYPOINT ["uv", "run", "--no-sync", "python", "run_pipeline.py"]
```

```bash
docker build -t registry.lab.example/clio-lab:0.1.0 .
docker push registry.lab.example/clio-lab:0.1.0
```

UNVERIFIED: that `hdbscan` and `umap-learn` build cleanly on `python:3.12-slim` without extra system packages (a compiler may be needed if no wheel exists). If the build fails, use a `-bullseye` base or install `build-essential` in a builder stage.

```yaml
# clio-lab.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: clio-lab
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: insights-config
  namespace: clio-lab
data:
  OPENAI_BASE_URL: "http://litellm.gateway.svc.cluster.local:4000/v1"
  SUMMARY_MODEL: "openai/glm-5.2"
  EMBED_MODEL: "nemotron-embed"
  MAX_CONCURRENT_REQUESTS: "8"
  MIN_UNIQUE_USERS: "5"
  INPUT_FILE: "/data/in/synthetic.json"
  OUTPUT_DIR: "/data/out"
---
apiVersion: v1
kind: Secret
metadata:
  name: insights-secrets
  namespace: clio-lab
type: Opaque
stringData:
  OPENAI_API_KEY: "replace-me-with-a-virtual-key"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: insights-data
  namespace: clio-lab
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 5Gi
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: insights
  namespace: clio-lab
spec:
  schedule: "0 2 * * 0"            # 02:00 every Sunday, cluster time zone
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 3600
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 1
      activeDeadlineSeconds: 14400
      template:
        metadata:
          labels:
            app: insights        # label on the pod template, not only the CronJob
        spec:
          restartPolicy: Never
          securityContext:
            runAsNonRoot: true
            runAsUser: 10001
            fsGroup: 10001
          containers:
            - name: insights
              image: registry.lab.example/clio-lab:0.1.0
              args: ["$(INPUT_FILE)", "$(OUTPUT_DIR)"]
              envFrom:
                - configMapRef:
                    name: insights-config
                - secretRef:
                    name: insights-secrets
              resources:
                requests: {cpu: "500m", memory: "1Gi"}
                limits:   {cpu: "2",    memory: "4Gi"}
              volumeMounts:
                - name: data
                  mountPath: /data
              securityContext:
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: false   # numba/umap write caches; see note
                capabilities: {drop: ["ALL"]}
          volumes:
            - name: data
              persistentVolumeClaim:
                claimName: insights-data
```

Notes on the manifest:

- The `args` use `$(VAR)` expansion from the container's env, which Kubernetes supports for variables defined in the same container, including those from `envFrom`. UNVERIFIED: expansion of `envFrom` variables in `args` on your cluster version; if it does not expand, hard-code the paths.
- `OPENAI_BASE_URL` in the ConfigMap and `OPENAI_API_KEY` in the Secret are what make Kura talk to the gateway; this is the same split you would look for in the in-house service.
- Create a dedicated gateway virtual key with a budget cap for the job, so a runaway run is bounded.
- The input file must be on the PVC: copy `synthetic.json` to `/data/in/` using a one-off pod, or bake it into the image for the lab. In a real deployment the job would read the portal database instead, through a read-only role.
- `readOnlyRootFilesystem` is left off because numba and umap may write caches; if you want it on, mount an `emptyDir` at `/tmp` and set `NUMBA_CACHE_DIR=/tmp`.
- For object storage instead of a PVC, add a final step that copies `report.json` to a bucket (S3-compatible) using credentials from the Secret, and leave the checkpoints out of the bucket, since they contain summaries.
- To share GPUs politely, give the pod's `priorityClassName` a low value and keep `MAX_CONCURRENT_REQUESTS` small.

Deploy and trigger a run now rather than waiting for Sunday:

```bash
kubectl apply -f clio-lab.yaml
kubectl create job -n clio-lab --from=cronjob/insights insights-manual-1
kubectl logs -n clio-lab -f job/insights-manual-1
```

Expected: the same progress output as in the local run, ending with `N clusters shown, M suppressed`. Then inspect the output:

```bash
kubectl get cronjob,job,pod -n clio-lab
kubectl run -n clio-lab peek --rm -it --restart=Never --image=busybox \
  --overrides='{"spec":{"containers":[{"name":"peek","image":"busybox","command":["sh","-c","head -c 1500 /data/out/report.json"],"volumeMounts":[{"name":"d","mountPath":"/data"}]}],"volumes":[{"name":"d","persistentVolumeClaim":{"claimName":"insights-data"}}]}}'
```

Because the PVC is `ReadWriteOnce`, the peek pod may need to run on the same node as nothing else is using it; run it when no job is active.

Now you can do the exercise from the earlier sections in reverse: run the commands from "Reading it without ConfigMap access" against `clio-lab`, then restrict a test ServiceAccount from reading ConfigMaps (`kubectl auth can-i get configmaps --as=system:serviceaccount:clio-lab:reader -n clio-lab`) and confirm that `describe cronjob` still shows `OPENAI_BASE_URL` as an `envFrom` reference but not its value.

## Governance angle

*This service reads every user's conversations, so its risk is the risk of a second, aggregated copy of everything people said, and its controls should be judged that way.*

Why it is sensitive:

- It touches all chats, including personal, medical, legal and employment topics that people typed into a tool they may have thought of as private.
- The output feels safe because it is aggregated, yet small groups, re-identifiable labels and per-user drill-down can undo that. In a small user base, a "group of ten" may point at one team.
- It can drift into surveillance. A tool built for "what is the portal used for" can be repurposed to find out what a named person asked.
- The intermediate data (summaries, embeddings, checkpoints, caches) is still derived from private text and still counts as stored data.
- Summaries are model-written and models err; acting on a mislabelled cluster can mean acting on a falsehood about people.

Controls to expect, and ask to see:

- **Written purpose and policy,** stating what it is for (usage understanding, capacity planning, misuse monitoring) and what it is not for (individual performance review, automated enforcement).
- **Notice to users,** such as a line in the portal terms or a privacy page saying conversations are analysed in aggregate.
- **Data minimisation:** raw text read and discarded, not copied; summaries stripped of identifiers; user ids pseudonymised, with the mapping held separately.
- **Thresholds:** a minimum number of distinct users per cluster, appropriate to the real population, and suppression of the rest.
- **Privacy auditor or equivalent review** of labels before publication, validated against labelled examples, not trusted by default.
- **Access control:** aggregate reports to the intended analysts; raw conversation access, if it exists at all, separate, justified, time-limited and logged; no standing person-to-conversation lookup.
- **Retention limits** on summaries, embeddings and checkpoints, and a deletion path when a user leaves or opts out.
- **Segregated storage and credentials:** a read-only database role for the source, a dedicated gateway key for the job, output stored apart from general dashboards.
- **Review of changes:** the prompts, thresholds and model choices are in version control, and changes to them are reviewed, since a lowered threshold is a privacy change.
- **Human-validated quality,** because the labels drive decisions.

## Check yourself

1. Name three settings in a Clio-style ConfigMap that change what a viewer sees without changing any conversation, and say what each does.
2. Why is `SAMPLE_RATE: 0.1` important to know before reading a cluster of 400?
3. A report shows no cluster about a sensitive topic you know people discuss. Give three reasons that could be true without the topic being absent.
4. You have `get` on Deployments but not ConfigMaps. What can you learn from `kubectl describe deploy`, and what can you not?
5. What does it tell you if the pod spec shows `envFrom` with a ConfigMap name, but you see no individual env var names?
6. You find no setting resembling a minimum-user threshold in the settings class. What do you conclude and what do you ask?
7. How would you check a cluster labelled "Customer complaints handling" is what it says?
8. Why does the lab pipeline keep user ids out of the data given to the LLM but still use them afterwards?
9. Why is a CronJob with `concurrencyPolicy: Forbid` and a low priority a good shape for sharing GPUs with a chat portal?
10. Kura chooses k-means clusters as `ceil(n / clusters_per_group)`. With 300 conversations in six real topics, what goes wrong and how could you spot it?

## References

All checked 2026-11-18 unless noted.

- Background in this repo: [17-clio-conversation-insights.md](17-clio-conversation-insights.md)
- Tamkin et al., "Clio: Privacy-Preserving Insights into Real-World AI Use", arXiv:2412.13678, submitted 2024-12-18, version 1 listed: https://arxiv.org/abs/2412.13678
- Kura repository (MIT per repo page; 541 stars; default branch last pushed 2025-09-10 per GitHub API): https://github.com/jxnl/kura
- Kura on PyPI, version 0.5.4, released 2025-09-09: https://pypi.org/project/kura/
- Kura source files read on `main`: `README.md`, `pyproject.toml`, `kura/summarisation.py`, `kura/cluster.py`, `kura/embedding.py`, `kura/types/conversation.py` (via raw.githubusercontent.com)
- OpenClio repository (MIT; 97 stars; last pushed 2025-08-19 per GitHub API; not archived): https://github.com/Phylliida/OpenClio
- Kubernetes documentation on RBAC authorization, CronJob, and defining environment variables for a container: https://kubernetes.io/docs/ (not re-fetched in this session; behaviours described are from established Kubernetes semantics, so verify against your cluster version)
- OpenAI SDK environment variables `OPENAI_BASE_URL` and `OPENAI_API_KEY`: UNVERIFIED in this session; documented behaviour of the official Python SDK, to be confirmed with the smoke test above.

Items marked `UNVERIFIED:` in the text were not confirmed by reading sources or running code in this session; nothing in the runbook or the YAML was executed.
