# OpenSearch and Elasticsearch as Vector Stores for RAG

Versions described: OpenSearch docs "latest" = 3.9 (Helm chart 3.9.0); Elasticsearch docs = Elastic Stack 9.x (the install pages pin 9.5.6). All pages checked 2026-11-13. Anything marked "UNVERIFIED:" was not confirmed on a page I opened.

## In one paragraph

OpenSearch and Elasticsearch are distributed search engines built on Apache Lucene. They store JSON documents, index them so that keyword search is fast (an "inverted index"), and rank results with a scoring formula (BM25). Both can also store embedding vectors and find the nearest ones to a query vector, using an approximate algorithm called HNSW. For RAG (retrieval-augmented generation: fetch relevant text, then give it to an LLM) the useful property is that one engine can do keyword search, vector search and a blend of the two ("hybrid search") over the same documents. OpenSearch is the Apache-2.0 fork of Elasticsearch 7.10; the two have since diverged in API names, features and licence, so the docs for one are not safe to copy-paste for the other.

## The plain version

Think of a huge library with no catalogue. If you want books about "keeping the garden alive in a dry summer", you would have to walk every shelf and read every cover. A search engine is the library's catalogue and a very fast, well-read librarian in one. At the moment books arrive, it writes an index card for every important word ("drought", "watering", "soil") listing which books mention it. Ask a question and it flips straight to the right cards, then puts the best-matching books on top.

That covers matching words. The newer trick is matching meaning. Every passage is turned into a long list of numbers that acts like a map coordinate: passages about the same idea land near each other, even if they use different words. "Keeping plants alive in a heatwave" ends up next to "drought watering tips" although they share almost no words. The engine can find the nearest neighbours on that map very quickly, and it can combine "same words" and "same meaning" into one ranked list.

Without it, an AI assistant that must answer from your own documents would have to read everything every time (far too slow and costly), or it would guess. With it, the assistant first fetches the handful of passages that matter and then answers from them.

If you remember only five things:

- It is a catalogue-and-librarian for text, spread over several machines so it stays fast and survives a failure.
- Words are matched with index cards (keyword search); meaning is matched with number maps (vector search); the best systems use both.
- The numbers for each passage must always come from the same model, with the same length, or nothing lines up.
- Memory is the main cost: vectors want to live in RAM, so sizing is arithmetic you do before you deploy.
- OpenSearch and Elasticsearch look alike but are different products; copy commands only from the docs of the one you run.

## Why it exists

You already run PostgreSQL. A search engine solves a problem Postgres handles poorly at scale: "find the most relevant documents for this free-text query, fast, across hundreds of millions of rows, and rank them." Postgres has `tsvector` full-text search and the pgvector extension, so the closest comparison is: Elasticsearch/OpenSearch is a purpose-built, horizontally sharded version of "GIN full-text index plus vector index", with a REST/JSON API instead of SQL, and with relevance ranking as its core feature rather than an add-on.

Key terms, in order:

- **Document**: one JSON object. Roughly a row.
- **Index**: a named collection of documents. Roughly a table. (Not the same word as a database index.)
- **Mapping**: the schema of an index: field names and types (`text`, `keyword`, `integer`, vector types). Roughly `CREATE TABLE`.
- **Shard**: an index is split into shards; each shard is a complete Lucene index. Shards are how data is spread over nodes. Per the OpenSearch intro, more shards is not automatically better because each is a running Lucene instance using CPU and memory.
- **Replica**: a copy of a primary shard on a different node. For failover and extra read capacity. OpenSearch creates one replica per primary by default.
- **Inverted index**: a map from each word to the list of documents containing it. Looking up "kubernetes" is a dictionary lookup, not a table scan.
- **Analyzer**: the pipeline that turns text into tokens before indexing and before querying (split on whitespace/punctuation, lowercase, optionally stem "foxes" to "fox"). If the query and the document are analysed differently, matches silently fail.
- **BM25**: the default relevance formula (OpenSearch similarity docs: "BM25 (default)"). It scores a document higher when it contains rare query words, often, in a short field.
- **Segment**: shards are stored as immutable segments that are merged in the background. This matters for vectors (below).

## How it works

### Vectors

Plain gloss: a vector is a coordinate on a map of meaning, and "search" means finding the closest coordinates.

An **embedding** is a list of floating-point numbers (a vector) produced by a model so that texts with similar meaning give vectors that are close together. The list length is the **dimension** (e.g. 1024). Every vector in a field, and every query vector, must have the same dimension and come from the same model. If you change model you must re-embed and reindex everything.

Closeness is measured by a **space / similarity**: L2 (Euclidean distance), cosine similarity, or inner (dot) product. OpenSearch accepts `l1, l2, linf, cosinesimil, innerproduct, hamming, hammingbit` (not every engine supports each). Elasticsearch accepts `l2_norm, dot_product, cosine, max_inner_product`. Use the metric your embedding model was trained for. For cosine, Elasticsearch normalises vectors to unit length on indexing; `dot_product` requires you to supply unit-length vectors yourself.

Plain gloss on exact versus approximate: checking every house on the street versus asking the neighbours who live nearby.

**Exact k-NN** compares the query to every vector: perfectly accurate, cost grows linearly. **Approximate k-NN (ANN)** builds a data structure so only a small part of the data is examined, trading a little recall for large speed gains. The dominant structure is **HNSW** (Hierarchical Navigable Small World): a layered graph where each vector links to nearby vectors; a search enters at the sparse top layer and greedily walks down to the neighbourhood of the query. Parameters:

- `m`: links per vector. Higher = better recall, more memory. (OpenSearch Faiss/Lucene default 16, "keep between 2 and 100".)
- `ef_construction`: candidate list size while building the graph. Higher = better graph, slower indexing. (OpenSearch default 100.)
- `ef_search`: candidate list size at query time. Higher = better recall, slower. (OpenSearch Faiss default 100; the Lucene engine ignores it and uses `k`.) Elasticsearch's equivalent query-time knob is `num_candidates`.

Plain gloss on quantisation: rounding every number to fewer digits so the map takes less space, at the price of a slightly blurrier picture.

**Quantisation** shrinks vectors to save memory: scalar quantisation (float32 to int8/int4/fp16) or binary (1 bit per dimension, about 32x smaller), or product quantisation (OpenSearch Faiss). It costs some accuracy, often recovered by fetching extra candidates and rescoring with the full vectors. Elasticsearch keeps the raw floats on disk and adds the quantised copy, so disk goes up (docs: about 25% for int8, 3.1% for bbq) while RAM goes down.

Memory rule of thumb from the OpenSearch docs: HNSW needs about `1.1 * (4 * dimension + 8 * m)` bytes per vector, e.g. 1,000,000 vectors at 256 dims and m=16 is about 1.27 GB. At 1024 dims and m=16 that is about 4.7 GB per million vectors, before replicas.

### Hybrid search

Plain gloss: ask two judges (one counts matching words, one judges meaning) and merge their rankings into one.

```
 query text ──► BM25 match on text field ──► ranked list A ─┐
                                                            ├─► fuse ─► final list ─► LLM context
 query text ─► embed ─► kNN on vector field ─► ranked list B ┘
```

BM25 scores and vector scores are on different scales, so you cannot just add them. Two fusion approaches: **normalise then combine** (rescale each list, then weighted mean), or **RRF** (reciprocal rank fusion: score = sum of 1/(rank_constant + rank) over the lists, default constant 60, ignoring raw scores).

### OpenSearch specifics (3.9 docs)

Plain gloss: OpenSearch bolts vector support on as a plugin, and offers a choice of underlying libraries ("engines") that do the nearest-neighbour work.

- Vector support is the **k-NN plugin**. Create the index with `"index.knn": true` and map the field as `knn_vector` with required `dimension` (1 to 16,000). Optional: `data_type` (`float` default, `byte`, `binary`, `half_float`), `space_type`, `mode` (`in_memory` default, or `on_disk`), `compression_level` (`1x` to `32x`), and a `method` object.
- **Engines**: `faiss` (default per the methods page; HNSW and IVF, plus PQ/SQ encoders), `lucene` (HNSW, good filtering, suits smaller deployments), `nmslib` (deprecated), `jvector` (separate plugin). The `engine` default in the method definition is `faiss`.
- **Queries**: `knn` query (`vector`, `k` up to 10,000, optional `filter`, `method_parameters.ef_search`, `rescore`), and `neural` query (give text; the cluster embeds it with a deployed ML model).
- **Hybrid**: a `hybrid` query (up to 5 sub-queries) is run with a **search pipeline** whose `phase_results_processors` contain either `normalization-processor` (techniques `min_max` default, `l2`, `z_score`; combination `arithmetic_mean` default, `geometric_mean`, `harmonic_mean`, with `weights`) or `score-ranker-processor` (RRF, `rank_constant` default 60, introduced 2.19).
- **Ingest pipelines**: the `text_embedding` processor takes `model_id` and `field_map` (text field to vector field) and calls an ML model at index time. Models are registered through ml-commons; connectors exist for hosted services (the connectors page lists SageMaker, OpenAI, Cohere, Bedrock, Vertex AI) via "connector blueprints".
- **`semantic` field type** exists in OpenSearch 3.x docs (neural query accepts "a vector or semantic field"); I did not read its details.

### Elasticsearch specifics (9.x docs)

Plain gloss: Elasticsearch builds vector support into one field type and lets you describe a search as a small tree of ranking steps ("retrievers").

- Field type `dense_vector` with `dims`, optional `similarity`, `element_type` (`float` default, `byte`, `bit`), `index_options.type`. Indexing for kNN is on by default. `dense_vector` fields are excluded from `_source` by default (vectors do not come back in search hits unless you ask).
- Default index type for float vectors (per the docs' default-quantisation section): `bbq_hnsw` for 384 or more dimensions, `int8_hnsw` below that; `bbq_disk` is the default "when available under the current license". The page is version-conditional (it also says "In Elastic Stack 9.0, float dense vector fields are always indexed as int8_hnsw"), so pin `index_options` explicitly if you care.
- **kNN search**: top-level `knn` option in `_search` (`field`, `query_vector`, `k`, `num_candidates`, `filter`, or `query_vector_builder` to embed text server-side), or a `knn` query usable inside `bool`.
- **Retrievers**: a `retriever` tree replaces `query`/`knn` at the top level. Types include `standard`, `knn`, `rrf`, `linear`, `text_similarity_reranker`, `rescorer`. `rrf` takes `retrievers`, `rank_constant` (default 60), `rank_window_size` (default 10), optional per-retriever `weight`.
- **`semantic_text`**: a field type that calls an inference endpoint at index time, picks dense or sparse vector mapping, and chunks long text automatically; no ingest pipeline needed. The docs warn it "typically calls the Inference API, which requires an appropriate license".

### Where they differ

Plain gloss: same ancestor, now two products with different names for the same ideas.

| Topic | OpenSearch 3.9 | Elasticsearch 9.x |
|---|---|---|
| Licence | Apache 2.0, run by the OpenSearch Software Foundation | Source available under SSPL 1.0, AGPLv3 or Elastic License 2.0 (AGPLv3 added Sept 2024 per Elastic's FAQ); default binary distribution is under ELv2 per secondary reports. Some features (e.g. `semantic_text` inference) are licence-gated |
| Vector field | `knn_vector` + `index.knn: true` | `dense_vector` (indexed by default) |
| Engines | faiss, lucene, nmslib (deprecated), jvector | Lucene only (HNSW, flat, int8/int4/bbq variants) |
| Query-time knob | `ef_search` (index setting or `method_parameters`) | `num_candidates` |
| kNN query shape | `query.knn.<field>.{vector,k}` | top-level `knn.{field,query_vector,k,num_candidates}` or `knn` query |
| Hybrid | `hybrid` query + search pipeline (`normalization-processor` or `score-ranker-processor`) | `retriever` tree (`rrf`, `linear`) |
| Auto-embedding | ingest `text_embedding` processor + ml-commons model; `neural` query | `semantic_text` + inference endpoints; `query_vector_builder` |
| K8s operator | `opensearch-k8s-operator` (Apache-2.0) | ECK (`eck-operator` Helm chart) |
| Default HTTPS/auth | demo security config; admin password required since 2.12 | security on by default; `elastic` user password generated |

## How you run it

**Kernel prerequisite (both).** Each node needs `vm.max_map_count >= 262144` (OpenSearch docs state the pods otherwise fail bootstrap checks and CrashLoopBackOff). The OpenSearch Helm chart can set it with `sysctlInit.enabled: true` (privileged init container). Pinned versions below are the doc versions; check for newer ones.

**Single node on Docker (OpenSearch)** - one node, demo TLS, custom admin password required:

```bash
docker run -d -p 9200:9200 -e "discovery.type=single-node" \
  -e "OPENSEARCH_INITIAL_ADMIN_PASSWORD=<strong-password>" \
  opensearchproject/opensearch:latest
curl https://localhost:9200 -ku admin:'<strong-password>'
```

`discovery.type=single-node` skips cluster-formation bootstrap checks. `-k` skips verification of the demo self-signed certificate (dev only). Heap is set with `OPENSEARCH_JAVA_OPTS="-Xms2g -Xmx2g"`.

**Single node on Docker (Elasticsearch)** - security and TLS auto-configured, password printed on first start:

```bash
docker network create elastic
docker run --name es01 --net elastic -p 9200:9200 -it -m 6GB \
  docker.elastic.co/elasticsearch/elasticsearch:9.5.6
# copy the printed elastic password, then:
docker cp es01:/usr/share/elasticsearch/config/certs/http_ca.crt .
curl --cacert http_ca.crt -u elastic:$ELASTIC_PASSWORD https://localhost:9200
```

UNVERIFIED: the exact `docker cp` source path for `http_ca.crt` (the page I read shows the curl line but I did not confirm the copy command).

**OpenSearch on Kubernetes with Helm** (official chart, default is a 3-node cluster, at least 8 GiB memory recommended):

```bash
helm repo add opensearch https://opensearch-project.github.io/helm-charts/
helm repo update
cat > values.yaml <<'EOF'
config:
  opensearch.yml: |-
    cluster.name: opensearch-cluster
    network.host: 0.0.0.0
extraEnvs:
  - name: OPENSEARCH_INITIAL_ADMIN_PASSWORD
    value: <custom-admin-password>   # use a Secret reference in real GitOps
sysctlInit:
  enabled: true
EOF
helm install my-deployment opensearch/opensearch -f values.yaml
```

Installs chart `opensearch/opensearch` 3.9.0. Pods are named `opensearch-cluster-master-N`. The docs put the password in plain `values.yaml`; in a GitOps repo, inject it from a SOPS or external Secret instead (the chart's `extraEnvs` accepts normal env `valueFrom`: UNVERIFIED for this chart).

**OpenSearch operator alternative**: `helm repo add opensearch-operator https://opensearch-project.github.io/opensearch-k8s-operator/` then `helm install opensearch-operator opensearch-operator/opensearch-operator`; you then create an `OpenSearchCluster` custom resource (API group moving from `opensearch.opster.io` to `opensearch.org`; both supported). Operator 3.0.0 lists support for OpenSearch 2.19.2 through latest 3.x. I did not read a cluster manifest.

**Elasticsearch on Kubernetes with ECK**:

```bash
helm repo add elastic https://helm.elastic.co && helm repo update
helm install elastic-operator elastic/eck-operator -n elastic-system --create-namespace
cat <<EOF | kubectl apply -f -
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata:
  name: quickstart
spec:
  version: 9.5.6
  nodeSets:
  - name: default
    count: 1
    config:
      node.store.allow_mmap: false
EOF
PASSWORD=$(kubectl get secret quickstart-es-elastic-user -o go-template='{{.data.elastic | base64decode}}')
kubectl port-forward service/quickstart-es-http 9200
```

First command installs the operator and CRDs; the manifest requests a one-node cluster. `allow_mmap: false` avoids the `vm.max_map_count` requirement but, per the docs, has performance implications; remove it for production and set the sysctl. ECK enables HTTPS with a per-cluster CA (secret `quickstart-es-http-certs-public`) and stores the `elastic` password in secret `quickstart-es-elastic-user`. A node needs about 2 GiB free memory or the pod stays Pending.

**Heap and memory sizing.**
- Elasticsearch sizes the JVM heap automatically from node roles and RAM; the docs recommend the default for most production use. Override only with care.
- OpenSearch: set `-Xms` equal to `-Xmx` via `OPENSEARCH_JAVA_OPTS`. The sample compose file comment says to set it to "at least 50% of system RAM"; the opposite pressure comes from vectors: the k-NN native (Faiss) indexes live outside the heap, and `knn.memory.circuit_breaker.limit` defaults to 50% of the RAM left after the JVM. So in practice leave plenty of RAM outside the heap for vectors and the OS page cache. Use the per-vector formula above to size.
- Faiss native indexes load into memory on first search; the warmup API loads them ahead of time.

**Create a vector index and use it (OpenSearch, cluster at `$OS`):**

```bash
# 1. index with a text field and a 1024-dim HNSW vector field
curl -ku admin:$PW -XPUT $OS/docs -H 'Content-Type: application/json' -d '{
  "settings": {"index": {"knn": true, "knn.algo_param.ef_search": 100}},
  "mappings": {"properties": {
    "text": {"type": "text"},
    "embedding": {"type": "knn_vector", "dimension": 1024,
      "method": {"name": "hnsw", "engine": "faiss", "space_type": "innerproduct",
                 "parameters": {"ef_construction": 128, "m": 16}}}}}}'

# 2. index one document (vector abbreviated; must have 1024 numbers)
curl -ku admin:$PW -XPOST "$OS/docs/_doc/1?refresh=true" -H 'Content-Type: application/json' \
  -d '{"text": "Velero backs up namespaces", "embedding": [0.01, 0.02, "..."]}'

# 3. approximate kNN query
curl -ku admin:$PW -XGET $OS/docs/_search -H 'Content-Type: application/json' -d '{
  "size": 5, "_source": ["text"],
  "query": {"knn": {"embedding": {"vector": [0.01, 0.02, "..."], "k": 5}}}}'

# 4. hybrid: pipeline once, then query
curl -ku admin:$PW -XPUT $OS/_search/pipeline/hybrid-rrf -H 'Content-Type: application/json' -d '{
  "phase_results_processors": [{"score-ranker-processor": {"combination": {"technique": "rrf"}}}]}'
curl -ku admin:$PW -XGET "$OS/docs/_search?search_pipeline=hybrid-rrf" -H 'Content-Type: application/json' -d '{
  "size": 5,
  "query": {"hybrid": {"queries": [
    {"match": {"text": "backup namespaces"}},
    {"knn": {"embedding": {"vector": [0.01, 0.02, "..."], "k": 20}}}]}}}'

# 5. health and inventory
curl -ku admin:$PW "$OS/_cluster/health?pretty"
curl -ku admin:$PW "$OS/_cat/indices?v"
```

The `"..."` placeholders are not valid JSON numbers; fill in the real 1024 values from your embedding service. Space choice: use `innerproduct` or `cosinesimil` to match the model (see "Where they differ"; check the model card). For min-max/weighted fusion replace the pipeline body with `normalization-processor` (`normalization.technique: min_max`, `combination.technique: arithmetic_mean`, `parameters.weights: [0.3, 0.7]`).

**Same thing on Elasticsearch:**

```bash
curl --cacert ca.crt -u elastic:$PW -XPUT $ES/docs -H 'Content-Type: application/json' -d '{
  "mappings": {"properties": {
    "text": {"type": "text"},
    "embedding": {"type": "dense_vector", "dims": 1024, "similarity": "cosine"}}}}'

curl --cacert ca.crt -u elastic:$PW -XPOST $ES/docs/_search -H 'Content-Type: application/json' -d '{
  "retriever": {"rrf": {
    "retrievers": [
      {"standard": {"query": {"match": {"text": "backup namespaces"}}}},
      {"knn": {"field": "embedding", "query_vector": [0.01, 0.02, "..."], "k": 20, "num_candidates": 100}}],
    "rank_window_size": 50}}}'

curl --cacert ca.crt -u elastic:$PW "$ES/_cluster/health?pretty"
curl --cacert ca.crt -u elastic:$PW "$ES/_cat/indices?v"
```

Creates the index (the default index type is chosen by the engine since none is given), then a hybrid RRF search of BM25 plus kNN. Cluster health `green` = all primaries and replicas allocated; `yellow` = replicas unassigned (normal on a single node with the default 1 replica); `red` = a primary is missing.

## How it fits the stack

```
 documents ─► chunker ─► embedding NIM (HTTP) ─► vectors ─┐
                                                           ├─► _bulk into OpenSearch/Elasticsearch
 user question ─► embedding NIM ─► query vector ───────────┤
                                                           ▼
                        hybrid search (BM25 + kNN) ─► top chunks ─► LLM prompt ─► answer
```

The RAG service is the caller. At ingest time it splits documents into chunks (a few hundred tokens each), asks the embedding NIM for a vector per chunk, and bulk-indexes `{text, embedding, metadata}`. At query time it embeds the question with the same model, runs a hybrid query with optional metadata filters (tenant, source, date), and passes the top chunks to the LLM. Two designs:

1. **Client-side embedding** (simplest, recommended to start): your service calls the NIM and sends plain vectors. The search engine knows nothing about the model. Works identically on both engines.
2. **Server-side embedding**: OpenSearch (`text_embedding` processor, `neural` query, ml-commons connector) or Elasticsearch (`semantic_text`, inference endpoints, `query_vector_builder`) calls the model for you. Elasticsearch's OpenAI-style inference service has a `url` setting; the connectors page for OpenSearch lists blueprints for hosted services. UNVERIFIED: whether either engine can be pointed at an NVIDIA embedding NIM's OpenAI-compatible endpoint, and the NIM's output dimension and any query-versus-passage input flag; check the NIM model card. Note the OpenSearch docs warn embedding models truncate at their token limit (typically 512 for BERT-based models), so chunk size must fit the model.

It calls nothing else. It is called over HTTPS port 9200 with basic auth or an API key (Elasticsearch) / admin or role users (OpenSearch). Monitoring: OpenSearch/Elasticsearch metrics can be scraped into Prometheus via an exporter. UNVERIFIED: which exporter or built-in endpoint to use.

## What goes wrong

- **Pods CrashLoopBackOff at start**: `vm.max_map_count` too low (bootstrap check). Set the sysctl or enable the chart's `sysctlInit`.
- **OpenSearch refuses to start with a password error**: since 2.12 `OPENSEARCH_INITIAL_ADMIN_PASSWORD` is mandatory and must pass a strength check; read the pod log.
- **Cluster `yellow` forever on a single node**: replicas cannot sit on the same node as their primary. Set `number_of_replicas: 0` on dev indices.
- **Dimension mismatch** (`vector has N dimensions, mapping says M`): you changed model or truncated vectors. Mapping dimensions cannot be altered; create a new index and reindex.
- **Wrong or missing `index.knn: true`** on OpenSearch: dynamic-mapping docs state you cannot enable ANN on an existing index; reindex into a new one.
- **Bad recall**: `k`, `ef_search`/`num_candidates` too small, or the similarity does not match the model. Raise the query-time knob first; it is cheap to try.
- **Filters returning too few hits**: OpenSearch notes filters are applied to ANN results for the native engines unless using a filter-capable engine setup; use `faiss` or `lucene` with the `filter` clause and check result counts against an exact search.
- **Hybrid scores look odd**: min-max normalisation depends on how many results each clause returns; one clause missing a document halves its score under `arithmetic_mean`. RRF avoids score-scale issues.
- **OOM or circuit breaker trips**: too many vectors for RAM. Check `knn.memory.circuit_breaker.limit`; use quantisation (`compression_level`, `bbq`/`int8`) or `on_disk` mode.
- **Slow search after bulk loads**: many small segments or cold native indexes. Set `refresh_interval` to `-1` during bulk load and re-enable it afterwards; use the warmup API.
- **`semantic_text` operations fail**: licence level does not cover inference; check `_license`.
- **Elasticsearch search hits lack the vector**: vectors are excluded from `_source` by default; this is intended.

## Check yourself

1. What is the difference between a shard and a replica, and why is a single-node cluster usually `yellow`?
2. Why must the index-time analyzer and the query-time analyzer agree for a `text` field?
3. Given 5 million 1024-dimension float vectors with `m=16`, roughly how much native memory does HNSW need in OpenSearch, and what two settings could cut it?
4. What does `ef_search` (OpenSearch) / `num_candidates` (Elasticsearch) trade off, and what happens to recall if you set it equal to `k`?
5. Why can't you add a BM25 score and a cosine score directly, and how do min-max normalisation and RRF each solve that?
6. Name the OpenSearch objects needed for a hybrid query and the Elasticsearch objects that replace them.
7. If you swap the embedding model for one with a different dimension, what must you do to the index and why?
8. Where would you inject the admin password for the OpenSearch Helm chart in a GitOps repo, and how do you confirm the cluster is healthy afterwards?

## References

All opened and read on 2026-11-13.

- OpenSearch docs home, "Version 3.9": https://docs.opensearch.org/latest/about/
- k-NN vector field (`knn_vector`, parameters, `mode`, `compression_level`): https://docs.opensearch.org/latest/mappings/supported-field-types/knn-vector/
- Methods and engines (faiss, lucene, nmslib, jvector; HNSW/IVF parameters; memory estimate): https://docs.opensearch.org/latest/mappings/supported-field-types/knn-methods-engines/
- Approximate k-NN search: https://docs.opensearch.org/latest/vector-search/vector-search-techniques/approximate-knn/
- k-NN query: https://docs.opensearch.org/latest/query-dsl/specialized/k-nn/index/
- Neural query: https://docs.opensearch.org/latest/query-dsl/specialized/neural/
- Hybrid query: https://docs.opensearch.org/latest/query-dsl/compound/hybrid/
- Normalization processor: https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/
- Score ranker processor (RRF): https://docs.opensearch.org/latest/search-plugins/search-pipelines/score-ranker-processor/
- Text embedding processor: https://docs.opensearch.org/latest/ingest-pipelines/processors/text-embedding/
- ML connectors: https://docs.opensearch.org/latest/ml-commons-plugin/remote-models/connectors/
- k-NN settings (circuit breaker): https://docs.opensearch.org/latest/vector-search/settings/
- Vector search performance tuning (search/indexing): https://docs.opensearch.org/latest/vector-search/performance-tuning-search/ and .../performance-tuning-indexing/
- Install with Docker: https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker/
- Install with Helm (chart 3.9.0): https://docs.opensearch.org/latest/install-and-configure/install-opensearch/helm/
- OpenSearch Kubernetes operator: https://github.com/opensearch-project/opensearch-k8s-operator
- Getting started intro (shards, replicas, inverted index): https://docs.opensearch.org/latest/getting-started/intro/
- Similarity (BM25 default): https://docs.opensearch.org/latest/mappings/mapping-parameters/similarity/
- Cluster health: https://docs.opensearch.org/latest/api-reference/cluster-api/cluster-health/
- Elasticsearch dense_vector (Elastic Stack 9.x): https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector
- kNN search in Elasticsearch: https://www.elastic.co/docs/solutions/search/vector/knn and .../knn/approximate-knn
- Retrievers and RRF retriever: https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers and .../retrievers/rrf-retriever
- semantic_text field: https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/semantic-text and tutorial https://www.elastic.co/docs/solutions/search/semantic-search/semantic-search-semantic-text
- Create OpenAI inference endpoint: https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-inference-put-openai
- Install Elasticsearch with Docker (9.5.6): https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-basic
- Important settings (heap): https://www.elastic.co/docs/deploy-manage/deploy/self-managed/important-settings-configuration
- ECK Helm install: https://www.elastic.co/docs/deploy-manage/deploy/cloud-on-k8s/install-using-helm-chart ; quickstart: .../elasticsearch-deployment-quickstart
- Elastic licensing FAQ (SSPL, ELv2, AGPLv3): https://www.elastic.co/pricing/faq/licensing
- Text analysis overview: https://www.elastic.co/docs/manage-data/data-store/text-analysis
