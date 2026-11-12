# Clio: privacy-preserving insights into how people use a chat system

## In one paragraph

Clio ("Claude insights and observations") is Anthropic's system for finding out what people use its chat product for without anyone reading individual conversations. A language model first boils each conversation down to a short, de-identified summary. The summaries are then turned into numbers (embeddings), grouped by similarity (clustering), and each group is named and described by a model. Groups are folded into a browsable hierarchy, and several privacy checks (minimum group sizes, a model-based auditor, access controls) stand between the raw data and the people looking at results. Anthropic uses it for usage reports and for spotting misuse that no single conversation reveals. Open-source reimplementations exist (OpenClio, Kura), and the same shape can be built on a self-hosted stack. In August 2026 Anthropic renamed the system "Anthropic Insights"; this document uses "Clio" because the paper and most sources do.

## The plain version

Imagine a big public library. The head librarian wants to know what people are really using the library for: homework help, job applications, tax forms, family history. One way is to follow people around and read over their shoulders. That works, but it is creepy and nobody should accept it.

Another way: every visitor gets a short note written about their visit, with no names or details, such as "looked up how to write a CV". A clerk then piles the notes together, and the librarian only ever looks at piles, each with a label like "job applications (about 400 visits)". If a pile is tiny, say two visits, it is thrown away, because a small pile can point at one person. A second clerk reads every label and strikes out any that could identify someone.

That is Clio. The "notes" are summaries written by a language model, the "piles" are groups of similar summaries, and the "clerks" are also models.

Without something like this you have two bad choices. You can know nothing about how people use the system, so you plan and defend it blind. Or you read conversations by hand, which does not scale and is a privacy problem. Ordinary dashboards show how fast the system is, not what people are asking it.

If you remember only five things:

- It answers "what are people doing with this?", not "is the system healthy?".
- A model writes a short, de-identified summary of each conversation; later steps only see summaries.
- Similar summaries are grouped, and each group gets a name.
- Small groups are hidden, and a second model checks names for anything identifying.
- It is a lens for spotting patterns and asking questions, not proof, and it is not safe by magic.

## Why it exists

Anthropic's Clio post frames two needs. The first is understanding real usage, something like Google Trends for an AI assistant, so product and policy decisions rest on evidence rather than guesses. The second is safety: some harmful uses only show up as a pattern across many conversations. In the post, Anthropic describes finding a network of automated accounts producing SEO spam, where no single conversation broke policy but the pattern did (the accounts were removed). It also describes catching violating content in translation requests that existing classifiers missed, and screening before a feature launch and during the 2024 US election period.

The constraint is privacy. The paper's own measurements show why summaries matter: in a 5,000-conversation sample, roughly 10% of raw conversations contained private information, dropping to about 1.5% after summarisation. So the design aim is that humans see only aggregates.

## How it works

Plain-language gloss first, then the specifics. All numbers below are from Anthropic's paper (arXiv 2412.13678, appendices) unless marked otherwise, and describe the 2024 research version using Claude 3-era models.

```
 conversations
      |
      v
 1. FACET EXTRACTION   (small model, per conversation)
      |   request summary, task, language, turns, "concerning" score
      v
 2. EMBED              (sentence-transformer, text -> vector)
      v
 3. CLUSTER            (k-means on the embeddings)
      v
 4. NAME + DESCRIBE    (bigger model, sees samples from the cluster)
      v
 5. HIERARCHY          (embed names, cluster again, model proposes parents)
      v
 6. PRIVACY GATES      (min unique users, model auditor, drop failures)
      v
 7. EXPLORE            (tree view, 2-D map via UMAP)
```

**Facets.** A facet is one question asked of every conversation, answered by a model. The paper's facets (Appendix G.4.1) are Request, Language, Task and "Concerning" (a safety score); turn count is another. The "Task" facet asks what the model is being asked to do. Extraction used Claude 3 Haiku at temperature 0.2. The prompt tells the model to leave out private details, which is the first privacy layer.

**Embedding.** An embedding is a list of numbers (here 768) that represents the meaning of a piece of text, arranged so that texts with similar meaning get nearby lists. Clio used the sentence-transformer all-mpnet-base-v2. Two summaries about "Python web scraping" end up close together; one about "grief poetry" lands far away. Distance between vectors is how "similar" is computed.

**Clustering.** Clustering means sorting items into groups of near neighbours without being told the groups in advance. Clio uses k-means: pick k centres, assign each point to its nearest centre, move the centres to the average of their points, repeat. Choosing k is the awkward part. The paper says only that k varies with the number of conversations (exact values withheld). Kura's author calls his own choice (items divided by a target cluster size) arbitrary.

**Naming.** For each cluster, a model (Claude 3.5 Sonnet, temperature 1) sees 50 random summaries from inside the cluster and 50 nearest-to-the-centre summaries from outside it. The outside examples make the name specific ("contrastive" naming). It writes a two-sentence past-tense description and a name of at most ten words, again told to exclude private information.

**Hierarchy.** Thousands of small clusters are unreadable, so the cluster names and descriptions are themselves embedded and clustered into "neighbourhoods" (k chosen so there are about 40 clusters per neighbourhood). A model proposes parent categories per neighbourhood, proposals are deduplicated, each lower cluster is assigned to its best parent, and parents are renamed from their children. Levels are added until the target number of top-level clusters is reached. The paper's cost example uses 10 / 100 / 1,000 clusters across three levels.

**Privacy gates.**

- The summarisation prompts omit private details.
- Clusters must meet a minimum number of unique users (and conversations). The paper and Anthropic's post do not give the production value. The Economic Index report uses much larger thresholds for its own publication (see below).
- A privacy auditor model (Claude 3.5 Sonnet, temperature 0.05) rates cluster summaries 1 to 5: 1 identifiable to an individual, 2 to a specific group, 3 to thousands, 4 identifiable only with significant context, 5 not identifiable. 3 or above counts as acceptable. The auditor scored 98% on a 1,237-example validation set. In the 5,000-conversation sample, almost all cluster summaries rated 5, a few 4, none 3 or below.
- Only higher-level clusters are shown to human analysts; access controls, data minimisation and retention limits apply (Anthropic's post).

**Map view.** UMAP is a method that squashes high-dimensional vectors down to 2-D points so that near neighbours stay near, giving a scatter plot. Clio's projector used n_neighbors 15, min_dist 0, cosine metric, and it only affects the exploration interface, not the numbers in the paper.

**Validation numbers.** Reconstruction test: on 19,476 synthetic transcripts the pipeline recovered the right underlying topic 94% of the time versus 5% for random guessing. For safety, per-cluster Clio "concern" scores correlated with Anthropic's Trust and Safety classifier flag rate at r = 0.71. Cost: $48.81 for 100,000 conversations (about $0.0005 each), nearly all of it facet extraction.

**Authors' stated limits.** Summaries can hallucinate or misread context; clustering handles outliers poorly and labels can be too broad; intent cannot be fully inferred; rare events are detected poorly; there is a privacy-versus-granularity trade-off; and results are specific to Claude.ai. Anthropic's post adds that false positives are why Clio output is not used for automated enforcement "at this time", that the safeguards might miss some private information, and that some users may find the whole thing invasive.

**What later work did.**

- Education report (April 2025): about 1 million Free/Pro conversations from higher-education email domains, filtered by Clio to 574,740 student-related ones from an 18-day window; computer science was heavily overrepresented. Caveats include faculty accounts being counted as students.
- Economic Index (September 2025): 1 million claude.ai conversations and 1 million API transcripts classified by O*NET task and a bottom-up request taxonomy. Publication thresholds: cells under 15 conversations and 5 unique accounts dropped; bottom-up request clusters need at least 500 conversations and 250 accounts.
- Independent-research pilot (August 2026): the tool, now named Anthropic Insights, let three outside groups (Stanford SALT Lab, Oxford Human Information Processing Lab, METR) ask their own questions of about 250,000 conversations. They saw only aggregated categories and percentages, an Imperial College London audit reviewed privacy, and Anthropic itself called the pilot slow and resource-intensive and noted that poorly worded questions give misleading categories that are hard to catch since nobody reads the conversations.

**A tiny worked example (invented data).** Ten conversations after step 1 has turned each into a de-identified summary:

1. User asked how to reset a forgotten SQL Server password.
2. User wanted a Python script to parse a CSV and plot a column.
3. User asked for help writing a cover letter for a logistics role.
4. User asked why a Kubernetes pod stays in Pending.
5. User asked for a shorter, more polite version of an email to a supplier.
6. User asked how to tidy a CV summary section.
7. User asked for a Bash one-liner to find large files.
8. User asked for feedback on a draft LinkedIn "about" paragraph.
9. User asked how to make a regex match dates like 2026-11-13.
10. User asked to rewrite a meeting follow-up email to sound friendlier.

After embedding and clustering with k = 3, you would expect:

- Cluster A, "Writing and debugging scripts and commands": 1, 2, 4, 7, 9 (5 conversations, 5 users).
- Cluster B, "Job applications and professional profiles": 3, 6, 8 (3 conversations).
- Cluster C, "Polishing workplace emails": 5, 10 (2 conversations).

With a minimum of 3 unique users, cluster C would be hidden from the dashboard. A real run would have thousands of items and far more clusters; the point here is the shape: summaries in, named groups with counts out, small groups suppressed. (Cluster A is also a candidate for a second-level split into "scripting" and "infrastructure troubleshooting".)

## How you would build one

*Everything in this section is design guidance, not a description of any product.*

**Where the data comes from.** Either the chat portal's own database (conversations, user ids, timestamps) or the gateway's logs. LiteLLM's spend logs hold request metadata and, only if enabled, message bodies; check what yours stores and whether storing prompts is acceptable (see governance below). You need three fields per conversation: a stable pseudonymous user id (for the unique-users threshold), the text, and a timestamp.

**Batch job.** Run it nightly or weekly, not per request.

1. Read conversations not yet processed.
2. Summarise each with the self-hosted LLM through the gateway (one short call per conversation, instruction to drop names, emails, companies, places). Store the summary, language, turn count; do not copy the raw text anywhere new.
3. Embed summaries with the embedding NIM. UNVERIFIED: that the NIM embedding model you deploy exposes an OpenAI-compatible `/v1/embeddings` route and whether it needs extra parameters (some retrieval embedding models distinguish query and passage inputs); check the NIM's docs.
4. Cluster. k-means is simple and is what Clio used; HDBSCAN (a density-based method that picks the number of clusters itself and labels outliers as noise) avoids choosing k and handles odd shapes, but UNVERIFIED: no source I opened compared them for this use. Tip: HDBSCAN tends to work better after UMAP reduces the vectors to ~10-50 dimensions.
5. Name each cluster with the LLM using in-cluster and nearest-outside samples.
6. Apply gates: drop clusters below N unique users, run an auditor prompt, then store.
7. Optionally build a second level by clustering the cluster names.

```python
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import normalize
import umap  # umap-learn

# summaries: list[dict(user_id=..., text=...)]  produced by the LLM step
texts = [s["text"] for s in summaries]
users = np.array([s["user_id"] for s in summaries])

X = normalize(embed(texts))            # embed() -> (n, d) via the embedding NIM
k = max(2, len(texts) // 100)          # target ~100 items per cluster; arbitrary
labels = KMeans(n_clusters=k, n_init="auto", random_state=0).fit_predict(X)

MIN_USERS = 10                         # policy choice, not a Clio constant
clusters = []
for c in range(k):
    idx = np.where(labels == c)[0]
    if len(set(users[idx])) < MIN_USERS:
        continue                       # too few distinct people: suppress
    centre = X[idx].mean(axis=0)
    near = idx[np.argsort(-(X[idx] @ centre))[:50]]
    outside = np.where(labels != c)[0]
    contrast = outside[np.argsort(-(X[outside] @ centre))[:50]]
    name, desc = llm_name(
        inside=[texts[i] for i in near],
        outside=[texts[i] for i in contrast],
    )
    if audit(name, desc) < 3:          # 1-5 scale, as in the paper
        continue
    clusters.append(dict(id=c, name=name, desc=desc, n=len(idx),
                         users=len(set(users[idx]))))

xy = umap.UMAP(n_neighbors=15, min_dist=0, metric="cosine").fit_transform(X)
```

`embed`, `llm_name` and `audit` are your own thin wrappers around the gateway.

**Kubernetes shape.** A CronJob running one container image (Python, scikit-learn, umap-learn) that talks to the gateway for LLM and embedding calls and writes results to Postgres or OpenSearch. The summarisation step is the expensive one and parallelises well; clustering needs only CPU. If your cluster uses a GPU batch scheduler such as Volcano, run the job as a low-priority batch job so interactive chat preempts it. Keep it idempotent: record the last processed timestamp so a re-run does not double-count.

**Storage and display.** Store per-cluster rows (name, description, size, unique users, time window, parent) and the 2-D coordinates; do not store raw text. OpenSearch can hold them and Grafana can chart cluster size over time. A cluster tree and scatter plot may need a small custom page; OpenClio generates a static site you can borrow ideas from.

**Cost and GPU contention.** Summarisation is one LLM call per conversation, which in the paper was about 92% of total cost. On your own hardware the cost is GPU time, not dollars, and it competes with chat. Mitigate by running off-hours, summarising only new conversations, capping summary length, sampling (you rarely need every conversation), and using a smaller model for summaries than for naming.

**Governance questions to settle before writing code.**

- Consent and notice: do users know conversations are analysed in aggregate? Anthropic notes some users may find it invasive and chose transparency.
- Retention: how long are raw conversations and summaries kept?
- Who sees what: analysts see top-level clusters only; individual-level drill-down is a separate, audited process or does not exist.
- Re-identification in small organisations: with 80 users, a "minimum 10 unique users" gate may suppress nearly everything, and a cluster of 10 may still point at one team. Coarser categories, longer time windows, or a fixed taxonomy you define up front may serve better than bottom-up clusters.
- Purpose limitation: decide up front whether this is for usage understanding only or also for misuse monitoring, and write it down.

**Existing open-source implementations.**

- OpenClio (github.com/Phylliida/OpenClio): MIT licence, about 97 stars, 93 commits, no releases listed; runs on local LLMs via vLLM (example Qwen3-8B) with a sentence-transformers embedding model; outputs a static website with a cluster tree and UMAP plot. A third-party listing suggests it may not be actively maintained (UNVERIFIED; no dates visible on the repo page I opened).
- Kura (github.com/567-labs/kura): MIT licence, about 541 stars, 261 commits, no releases listed, described as under active development; pipeline of summarisation, base clustering, meta-clustering, dimensionality reduction, with caching and checkpointing. UNVERIFIED: which models it supports and whether it can point at a self-hosted OpenAI-compatible endpoint.
- UNVERIFIED: I did not run either; check that either one's PII handling is adequate before use. Kura's author himself says his PII removal is basic and relies only on the summarisation prompt.

## How it fits the stack

Ordinary observability (Prometheus metrics, OpenTelemetry traces, gateway spend logs) tells you how the system behaves: latency, error rate, tokens, cost per key. A Clio-style layer tells you what people are doing with it: topics, tasks, languages, misuse patterns. They share inputs (the gateway sees every request) but ask different questions, and one cannot substitute for the other. A latency spike has a cause in metrics; "usage of the portal for summarising legal documents tripled" does not appear there.

In this project the pieces line up: the portal DB or gateway logs are the source; the self-hosted LLM does summaries and naming; the embedding NIM does vectors; OpenSearch or Postgres stores results; a dashboard displays them; a CronJob or batch job schedules it. Operationally, treat the output as a new sensitive dataset: it needs its own access control and retention, apart from the Prometheus/Grafana side where per-user detail is typically already restricted.

## What goes wrong

- **Cluster names that leak.** A name like "Drafting a termination letter for an employee at X" identifies someone. This is why the auditor exists, and why the paper rates names, not just summaries.
- **Tiny clusters.** Few unique users means a cluster is effectively one person's habit. Count distinct users, not conversations: one heavy user can fill a cluster alone.
- **Meaningless clusters.** k too large splits one theme; too small merges unrelated ones. Embeddings may group by style or language rather than task. Always read samples (of summaries) before trusting a label. The paper lists overly broad labels and poor outlier handling.
- **Model bias in summaries.** A summary is a model's opinion. It can hallucinate, flatten nuance, and be worse in languages or domains the model handles poorly. The Insights pilot noted wrongly framed questions yield misleading categories that are hard to spot because nobody reads the underlying text.
- **Small models in the loop.** UNVERIFIED: how well a self-hosted model matches the paper's Claude models on summarisation faithfulness and on privacy auditing; the auditor's 98% figure is for Claude 3.5 Sonnet on Anthropic's test set. Validate yours on a labelled sample.
- **Cost and contention.** One LLM call per conversation adds up and may starve chat.
- **Misuse of the tool itself.** It could become employee surveillance. Anthropic notes inappropriate monitoring as a risk and mitigates it with access controls and data minimisation; Clio output is not used for automated enforcement.
- **Rare events.** The authors state Clio detects rare events poorly; do not rely on it to catch a single bad actor.

## Check yourself

1. Why does Clio cluster summaries instead of raw conversations, and what privacy property does that give you?
2. In your own words, what is an embedding, and what does "close together" mean for two of them?
3. Why does the cluster-naming prompt include examples from outside the cluster?
4. Why is the minimum threshold counted in unique users rather than conversations?
5. A cluster scores 2 on the auditor's 1 to 5 scale. What does that mean, and what should happen to the cluster?
6. Your organisation has 60 users. What happens to a "minimum 10 users per cluster" rule, and what alternatives would you consider?
7. How would a summarisation job on the same GPUs as interactive chat be scheduled so it does not hurt chat latency?
8. Give one question that Prometheus and gateway spend logs can answer and one that only a Clio-style layer can, and explain why.

## References

All checked 2026-11-13.

- Anthropic, "Clio: Privacy-preserving insights into real-world Claude.ai usage": https://www.anthropic.com/research/clio (checked 2026-11-13)
- Tamkin et al., "Clio: Privacy-Preserving Insights into Real-World AI Use", arXiv:2412.13678: https://arxiv.org/abs/2412.13678 and HTML https://arxiv.org/html/2412.13678 (checked 2026-11-13; the HTML was read in two chunks, the last ~6,000 characters were not read)
- Anthropic, Economic Index September 2025 report: https://www.anthropic.com/research/anthropic-economic-index-september-2025-report (checked 2026-11-13)
- Anthropic, Education Report, how university students use Claude: https://www.anthropic.com/news/anthropic-education-report-how-university-students-use-claude (checked 2026-11-13)
- Anthropic, enabling independent research with Anthropic Insights (formerly Clio): https://www.anthropic.com/research/enabling-independent-research (checked 2026-11-13)
- OpenClio: https://github.com/Phylliida/OpenClio (checked 2026-11-13)
- Kura: https://github.com/567-labs/kura (checked 2026-11-13)
- Ivan Leo, "Using language models to make sense of chat data without compromising user privacy": https://ivanleomk-github-io.pages.dev/blog/understanding-user-conversations (checked 2026-11-13)

Note: the 2026-08-24 rename to "Anthropic Insights" was read in a search-result snippet and a related-articles note on the Clio page, and is confirmed by the independent-research post's wording "formerly Clio".
