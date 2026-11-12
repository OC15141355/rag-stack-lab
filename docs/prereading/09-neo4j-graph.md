# Neo4j as a Graph Database for Graph-Backed Retrieval (GraphRAG)

Versions described: Neo4j Operations Manual "Version 2026.10 (Current)" (5.26 LTS also listed); Neo4j Helm charts 2026.10.2; `neo4j-graphrag` Python package docs (supports Neo4j >= 5.18.1, with newer features on 2026.01+). All pages checked 2026-11-13. Cypher examples below are adapted from the docs; I did not run them against a live server. Anything marked "UNVERIFIED:" was not confirmed on a page I opened.

## In one paragraph

Neo4j is a database that stores data as nodes (things) joined by relationships (typed, directed links between things), and is queried with a pattern-matching language called Cypher. It is the opposite of a table-oriented store: following a link is a direct lookup rather than a join, so questions like "who is connected to whom through three hops" stay cheap. Neo4j also has vector indexes and full-text indexes, so one database can hold text chunks with embeddings and the entities and relationships extracted from them. "GraphRAG" means using that graph during retrieval: find chunks by vector similarity, then walk the graph to pull in connected facts before handing context to an LLM. Neo4j ships an official Python package, `neo4j-graphrag`, that wraps this pattern.

## The plain version

Imagine a corkboard covered in photos of people, companies and places, with coloured string pinned between them: "works at", "owns", "lives next to". If someone asks "which of our suppliers share a director with a company we are about to buy?", you do not read a pile of reports. You put a finger on the first photo and follow the strings. A graph database is that corkboard, kept in a computer, where following a string is instant no matter how big the board gets.

Now think about an AI assistant that answers questions from your documents. The usual method finds paragraphs that sound similar to the question. That works for "what does the policy say about leave?" but fails for questions whose answer is spread across several documents and depends on how things are connected. Paragraph-matching finds paragraphs; it does not know that Person A reports to Person B who signed Contract C.

Without a graph, you would have to hope the right facts happen to sit in one paragraph. With one, the assistant first finds the likely starting paragraphs, then follows the strings to gather the linked facts around them, and answers from that fuller picture. A graph also lets you show your working: "I got this from these three connected records".

If you remember only five things:

- A graph stores things and the labelled links between them; asking "what is connected to this?" is its home ground.
- The query language, Cypher, is written as little pictures of the pattern you want, like `(person)-[:WORKS_AT]->(company)`.
- Neo4j can also do keyword and meaning-based search, so it can serve as the starting point for the walk.
- The AI model's job is to read documents and propose the things and links; those proposals need checking.
- Memory settings matter: give Neo4j a fixed, explicit amount of memory, and leave room for the meaning-search index.

## Why it exists

You know PostgreSQL. In SQL, a relationship is a foreign key and following it is a `JOIN`. Two or three joins are fine; a question like "everyone within four steps of this account" becomes a recursive CTE that gets slower and harder to read. Neo4j stores each relationship as a first-class object attached directly to its two nodes, so a traversal starts at one node and follows links without scanning tables. The trade-off: it is a poor fit for bulk aggregation over huge flat tables, where Postgres wins.

Terms:

- **Node**: one entity (a person, a document chunk). Has zero or more **labels** (`:Person`, `:Actor`) that classify it.
- **Relationship**: a connection from a source node to a target node. Always directed, and has exactly one **type** (`:ACTED_IN`).
- **Property**: key-value data on a node or relationship (`name: 'Tom Hanks'`). Together this is the **property graph model**.
- **Cypher**: Neo4j's query language. Patterns are drawn in ASCII art: `()` is a node, `-[]->` is a relationship.
- **Bolt**: Neo4j's binary client protocol (port 7687). Drivers use it.

Why it matters for RAG: a **knowledge graph** is a graph of entities and facts extracted from text. Neo4j's own explainer says basic RAG "relies solely on semantic search ... to retrieve and rank sets of isolated text fragments", whereas GraphRAG "uses knowledge graphs to represent and connect information" so retrieval can follow relationships. Questions that need several linked facts ("multi-hop" questions) are the target.

## How it works

### The data model and Cypher

Plain gloss: you draw the shape you are looking for, and the database finds every place in the data that has that shape.

The docs' own example creates two people and a movie in one statement:

```cypher
CREATE (:Person:Actor {name: 'Tom Hanks', born: 1956})
       -[:ACTED_IN {roles: ['Forrest']}]->
       (:Movie {title: 'Forrest Gump', released: 1994})
       <-[:DIRECTED]-(:Person {name: 'Robert Zemeckis', born: 1951})
```

Essentials (standard Cypher; the MERGE and constraint behaviour is from the Cypher manual pages I read):

```cypher
// read: who acted in what
MATCH (p:Person)-[r:ACTED_IN]->(m:Movie)
WHERE m.released > 1990
RETURN p.name, m.title, r.roles
ORDER BY m.title LIMIT 10;

// get-or-create: MERGE matches the whole pattern or creates it
MERGE (p:Person {name: 'Tom Hanks'})
  ON CREATE SET p.created = timestamp()
  ON MATCH  SET p.seen = timestamp();

// a variable-length path: people within 1 to 3 hops of Tom Hanks
MATCH path = (:Person {name: 'Tom Hanks'})-[*1..3]-(other:Person)
RETURN other.name, length(path) LIMIT 25;

// aggregation: movies per actor
MATCH (a:Actor)-[:ACTED_IN]->(m:Movie)
RETURN a.name, count(m) AS films ORDER BY films DESC;
```

Two things to know about `MERGE`: it "guarantees the existence of the pattern, not its uniqueness" under concurrent loads, so back it with a uniqueness constraint (the docs show `CREATE CONSTRAINT FOR (n:Product) REQUIRE n.id IS NODE KEY`; UNVERIFIED: that a plain `IS UNIQUE` form is also current). And an unlabelled `MATCH (n)` scans everything, so always use a label in the pattern.

### Indexes

Plain gloss: a graph walk needs a place to start, and indexes are how you find the starting nodes quickly.

- **Range/lookup indexes** on a label and property, for exact or range matching.
- **Full-text index** (Lucene-based keyword search with analysers, like Postgres full-text or BM25 in a search engine): `CREATE FULLTEXT INDEX namesAndTeams IF NOT EXISTS FOR (n:Employee|Manager) ON EACH [n.name, n.team]`. The default analyser is `standard-no-stop-words`. Query with `CALL db.index.fulltext.queryNodes("namesAndTeams", "nils") YIELD node, score`; docs say a `SEARCH` clause for full-text exists from 2026.09 in Cypher 25.
- **Vector index** (Lucene-based approximate nearest-neighbour search over embeddings, HNSW-style; the docs say vector indexes are "powered by the Apache Lucene indexing and search library"):

```cypher
CREATE VECTOR INDEX moviePlots IF NOT EXISTS
FOR (m:Movie) ON m.embedding
OPTIONS { indexConfig: {
  `vector.dimensions`: 1536,
  `vector.similarity_function`: 'cosine'
}};
SHOW VECTOR INDEXES;   // state: POPULATING, then ONLINE
```

`vector.similarity_function` accepts `'cosine'` (the docs call it generally preferred for text embeddings) or `'euclidean'`. Dimensions are optional but recommended so mismatches fail clearly. Tunables: `vector.hnsw.m` (default 16) and `vector.hnsw.ef_construction` (default 100). Quantisation (`vector.quantization.type`: `none`, `scalar`, `binary`) was introduced in 2026.06; the docs say the default is `binary` and that before release 2026.08 it was `scalar`. Index creation runs in the background.

Querying (2026.01 and later prefers the `SEARCH` clause; the older procedure is deprecated from 2026.04):

```cypher
MATCH (movie:Movie)
  SEARCH movie IN (
    VECTOR INDEX moviePlots
    FOR $queryEmbedding
    LIMIT 5
  ) SCORE AS score
RETURN movie.title, score;

// older form, works on earlier versions
CALL db.index.vector.queryNodes('moviePlots', 5, $queryEmbedding)
YIELD node AS movie, score RETURN movie.title, score;
```

The doc example passes a stored vector (`FOR m.embedding`); passing a query parameter is the RAG case, and I adapted it. UNVERIFIED: that `FOR $param` is accepted in the `SEARCH` clause exactly as written. Scores are bounded 0.0 to 1.0. From 2026.01, a vector index can span several labels and carry extra "filterable" properties used in `SEARCH ... WHERE`. Community Edition can index embeddings stored as lists of numbers; the native `VECTOR` property type needs block format, available in Enterprise Edition and Aura.

### GraphRAG

Plain gloss: use meaning-search to find a good place to stand, then look around at what is connected.

```
 documents ─► chunk ─► LLM extracts entities + relationships ─► graph:
                                   (Chunk)-[:MENTIONS]->(Entity)-[:RELATED_TO]->(Entity)
                        embed chunk text ─► Chunk.embedding (vector index)

 question ─► embed ─► vector index finds top chunks ─► Cypher traverses from those chunks
          ─► chunk text + connected entities/facts ─► LLM prompt ─► answer
```

Why a graph helps beyond vectors: vector search ranks isolated chunks by similarity, so a fact that is only reachable via a chain (A mentioned in chunk 1, A related to B in chunk 7) is missed. Entity extraction turns that chain into explicit links the query can walk. The costs: extraction needs an LLM pass over the whole corpus, quality depends on the model and schema, and entity duplicates ("IBM", "I.B.M.") must be resolved.

**Neo4j's Python tooling: package `neo4j-graphrag`** (`pip install neo4j-graphrag`, Python 3.10 to 3.14; it is the renamed continuation of `neo4j-genai`, which is deprecated). Optional extras include `openai`, `ollama`, `anthropic`, `google`, `cohere`, `mistralai`, `sentence-transformers`, and `experimental`. Main pieces:

- **Retrievers** (`neo4j_graphrag.retrievers`): `VectorRetriever`, `VectorCypherRetriever` (vector hit, then your Cypher `retrieval_query` with variables `node` and `score` in scope), `HybridRetriever` and `HybridCypherRetriever` (vector index plus a full-text index), `Text2CypherRetriever` (an LLM writes the Cypher), `ToolsRetriever`, and external-vector-DB retrievers (`WeaviateNeo4jRetriever`, `PineconeNeo4jRetriever`, `QdrantNeo4jRetriever`).
- **`GraphRAG`** (`neo4j_graphrag.generation`): glue that takes a retriever and an LLM and does `rag.search(query_text=..., retriever_config={"top_k": 5})`, returning `.answer`.
- **`SimpleKGPipeline`** (`neo4j_graphrag.experimental.pipeline.kg_builder`, marked experimental): reads text or a file, has an LLM extract entities and relations guided by an optional schema, embeds chunks, and writes to Neo4j. `await kg_builder.run_async(file_path=...)`.
- **Helpers**: `create_vector_index(driver, name, label=, embedding_property=, dimensions=, similarity_fn=)`; embedder and LLM classes with base classes you can subclass for a custom backend.

Minimal use, from the docs, with a graph-traversal retriever:

```python
from neo4j import GraphDatabase
from neo4j_graphrag.retrievers import VectorCypherRetriever
from neo4j_graphrag.generation import GraphRAG

driver = GraphDatabase.driver("neo4j://localhost:7687", auth=("neo4j", "password"))
retriever = VectorCypherRetriever(
    driver, index_name="chunk-index", embedder=embedder,
    retrieval_query="""
      OPTIONAL MATCH (node)-[:MENTIONS]->(e:Entity)
      RETURN node.text AS text, collect(e.name) AS entities, score""")
rag = GraphRAG(retriever=retriever, llm=llm)
print(rag.search(query_text="...", retriever_config={"top_k": 5}).answer)
```

`embedder` and `llm` are objects from `neo4j_graphrag.embeddings` / `neo4j_graphrag.llm`. UNVERIFIED: whether the stock `OpenAIEmbeddings`/`OpenAILLM` classes accept a custom base URL, which you would need to point them at an NVIDIA NIM's OpenAI-compatible endpoint; otherwise write a small subclass of the embedder base class.

## How you run it

**Ports and protocols.** Bolt on 7687 (drivers, `cypher-shell`; URI schemes `neo4j://` routed, `bolt://` direct), HTTP 7474 and HTTPS 7473 (Browser UI), backup 6362, cluster traffic 6000. Applications use Bolt via an official driver.

**Kubernetes with the official Helm chart** (`neo4j/neo4j`, chart 2026.10.2, labelled by Neo4j as the recommended way to run on Kubernetes):

```bash
helm repo add neo4j https://helm.neo4j.com/neo4j
helm repo update
kubectl create namespace neo4j
cat > my-neo4j.values.yaml <<'EOF'
neo4j:
  name: my-standalone          # mandatory, unique per namespace
  resources:
    cpu: "2"
    memory: "5Gi"              # minimum is 0.5 CPU / 2GB
  # password: "..."            # if unset, a random one is generated and printed
  # edition: "enterprise"      # default is Community
  # acceptLicenseAgreement: "yes"   # or "eval"
volumes:
  data:
    mode: "dynamic"
    dynamic:
      storageClassName: <your-storageclass>   # check the docs for your platform's keys
config:
  server.memory.heap.initial_size: "3G"
  server.memory.heap.max_size: "3G"
  server.memory.pagecache.size: "1G"
EOF
helm install my-neo4j-release neo4j/neo4j --namespace neo4j -f my-neo4j.values.yaml
kubectl rollout status --watch --timeout=600s statefulset/my-neo4j-release -n neo4j
```

Installs a StatefulSet. `neo4j.password` cannot be `neo4j`. Do not commit a real password; for GitOps use a Secret mechanism (UNVERIFIED: the chart's supported way to reference an existing Secret; the pages I read show plain `neo4j.password` only). The storage keys under `volumes.data.dynamic` are shown in the docs per cloud; I only confirmed `mode: "dynamic"`.

**Memory (the setting that bites).**
- The JVM **heap** holds query and transaction working memory. Set `server.memory.heap.initial_size` equal to `server.memory.heap.max_size` to avoid full garbage-collection pauses.
- The **page cache** (`server.memory.pagecache.size`) caches the on-disk graph store; the docs' production example sizes it at 1.2 times the data and native-index volume reported by `neo4j-admin server memory-recommendation`.
- On Kubernetes, heap + page cache + 1 GB headroom must be less than the container memory limit, or the kernel kills the pod (OOMKilled).
- **Vector indexes live in OS memory, not the page cache**, so leave RAM free beyond heap and page cache for them. Docs also recommend swap off on a dedicated server.
- Docs recommend always setting heap and page cache explicitly.

**Community vs Enterprise.** Per the introduction page: Community is "fully functional" (ACID transactions, Cypher, drivers) and suited to single-instance use. Enterprise adds clustering, online backup, role-based access control and LDAP. The feature table also lists "multiple databases beyond the system and default databases" and composite databases; UNVERIFIED: which edition column those fall in (I read the row labels only). Vector and full-text indexes are in both. The Community licence terms: UNVERIFIED (not read). The chart installs Community by default; for Enterprise set `edition` and `acceptLicenseAgreement` (valid licence, or `"eval"` for the evaluation licence). Practical consequence for this stack: a single Community pod has no online backup, so plan backups as offline `neo4j-admin` dump and load (the Kubernetes docs list "Dump and load databases (offline)" and "Back up and restore a single database (online)").

**Tools.**

```bash
# interactive shell inside the cluster (image tag is an example; match your server version)
kubectl run --rm -it -n neo4j --image "neo4j:<version>" cypher-shell -- \
  cypher-shell -a "neo4j://my-neo4j-release.neo4j.svc.cluster.local:7687" -u neo4j -p "$NEO4J_PASSWORD"

# run a file non-interactively, plain output
cypher-shell -a neo4j://localhost:7687 -u neo4j -p "$NEO4J_PASSWORD" --format plain -f example.cypher

# reach the browser UI and Bolt from your laptop
kubectl port-forward -n neo4j svc/my-neo4j-release 7474:7474 7687:7687
```

`cypher-shell` needs a semicolon at the end of each statement and Java 21 if installed standalone; `--access-mode read` restricts to reads. Neo4j Browser (http://localhost:7474) is the developer UI for running Cypher and visualising results; it ships with both editions. UNVERIFIED: the exact Service name the chart creates for port-forward (the install output shows the cluster-local address `my-neo4j-release.neo4j.svc.cluster.local`, so check `kubectl get svc -n neo4j`).

**Everyday Cypher for operations.**

```cypher
SHOW INDEXES;                       // state and population percent
SHOW VECTOR INDEXES;
MATCH (n) RETURN labels(n) AS labels, count(*) AS n;   // counts per label (full scan; fine for dev)
CREATE CONSTRAINT FOR (c:Chunk) REQUIRE c.id IS NODE KEY;   // syntax as shown in the docs for Product
```

## How it fits the stack

```
 ingestion job ─► embedding NIM ─► chunk vectors ─┐
        │                                         ├─► Neo4j (Bolt 7687): Chunk nodes + vector index
        └─► LLM entity extraction ─► entities/relationships ┘
 RAG service ─► embedding NIM (query vector) ─► Neo4j vector search + traversal ─► LLM ─► answer
```

Neo4j calls nothing: it is passive storage and search. The RAG service (or the `neo4j-graphrag` library inside it) calls it over Bolt with a driver. The embedding NIM is called by the service, not by Neo4j, so the vector dimension in the index must equal the NIM model's output dimension (UNVERIFIED: the dimension of the chosen NIM model). The same LLM that generates answers can also run `SimpleKGPipeline` extraction, though extraction is a batch job and is the expensive step. In this stack, Neo4j typically complements, not replaces, the OpenSearch/Elasticsearch store: the search engine does bulk keyword and vector retrieval, Neo4j adds relationships; alternatively Neo4j's own vector and full-text indexes can handle both for a smaller corpus. Keep a shared chunk ID in both stores so results can be joined in the service.

## What goes wrong

- **Pod OOMKilled**: heap + page cache + vector index memory exceed the container limit. Set the three memory parameters explicitly and keep the 1 GB headroom.
- **Vector query returns nothing right after load**: the index is still `POPULATING`; check `SHOW VECTOR INDEXES` and wait for `ONLINE`.
- **Dimension mismatch errors**: the index was created with different `vector.dimensions` than the embeddings. Drop and recreate the index (and re-embed if the model changed).
- **`MERGE` creating duplicates**: no uniqueness constraint, or merging on the whole pattern including properties that vary. Merge on a key property, set the rest with `ON CREATE SET`.
- **Slow queries**: no starting index, so `MATCH (n:Label {prop: ...})` scans every node of that label; or unbounded variable-length paths (`[*]`) that explode. Bound them (`[*1..3]`).
- **Entity duplicates and noisy extraction**: the LLM names the same thing differently; supply a schema, add a resolver step, and inspect samples before loading in bulk.
- **Text2Cypher gives wrong or unsafe queries**: an LLM-written query can be wrong; use a read-only database user (role-based access needs Enterprise) and `--access-mode read`-style restrictions.
- **Cannot connect with `neo4j://` through a plain port-forward**: routed URIs ask the server for a routing table with its advertised address. UNVERIFIED: exact behaviour with the Helm chart; use `bolt://localhost:7687` for single-instance port-forwards if routing fails.
- **Browser shows no data**: wrong database selected, or login with the default password `neo4j`, which the chart refuses.
- **Version drift in examples**: Neo4j now uses year-based versions (2026.10) with Cypher 25 and Cypher 5 side by side; features such as the `SEARCH` clause need 2026.01 or later. Check your server version before copying a snippet.

## Check yourself

1. What are the four building blocks of the property graph model, and which of them can carry properties?
2. Write the Cypher pattern for "people who acted in a movie directed by Robert Zemeckis" and explain why a `MATCH (n)` with no label is a problem.
3. What is the difference between `CREATE` and `MERGE`, and what protects `MERGE` against duplicates under concurrent writes?
4. Name the two kinds of index you need for a hybrid retriever, and say what `VectorCypherRetriever` adds on top of a plain vector search.
5. A question needs a fact from chunk 1 and a fact from chunk 7 that are connected only via a shared entity. Why does plain vector search miss it and how does the graph fix it? What is the cost of building that graph?
6. Your Neo4j pod has a 6 GiB memory limit. Propose heap and page cache values and explain why the vector index changes your answer.
7. What can Community Edition not do that matters for backups and access control, and what would you do about backups with it?
8. Which port do application drivers use, which port serves the Browser UI, and what is the difference between `bolt://` and `neo4j://` URIs?

## References

All opened and read on 2026-11-13.

- Graph database concepts (property graph model): https://neo4j.com/docs/getting-started/appendix/graphdb-concepts/
- Cypher manual, MERGE (ON CREATE/ON MATCH, constraints): https://neo4j.com/docs/cypher-manual/current/clauses/merge/
- Cypher manual, patterns: https://neo4j.com/docs/cypher-manual/current/patterns/
- Cypher manual, vector indexes (Neo4j 2026.x; `CREATE VECTOR INDEX`, `SEARCH`, quantisation): https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- Cypher manual, full-text indexes: https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/full-text-indexes/
- neo4j-graphrag for Python (overview, install, extras): https://neo4j.com/docs/neo4j-graphrag-python/current/
- neo4j-graphrag user guide, RAG (retrievers, `GraphRAG`): https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html
- neo4j-graphrag user guide, Knowledge Graph builder (`SimpleKGPipeline`): https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_kg_builder.html
- What is GraphRAG (Neo4j blog): https://neo4j.com/blog/genai/what-is-graphrag/
- Operations Manual 2026.10, introduction (Community vs Enterprise): https://neo4j.com/docs/operations-manual/current/introduction/
- Operations Manual, Kubernetes overview: https://neo4j.com/docs/operations-manual/current/kubernetes/
- Helm chart repository setup (chart 2026.10.2): https://neo4j.com/docs/operations-manual/current/kubernetes/helm-charts-setup/
- Standalone quickstart: https://neo4j.com/docs/operations-manual/current/kubernetes/quickstart-standalone/ (pages: .../prerequisites/, .../create-value-file/, .../install-neo4j/)
- Customizing the Helm chart (resources, heap, page cache): https://neo4j.com/docs/operations-manual/current/kubernetes/configuration/
- Memory configuration: https://neo4j.com/docs/operations-manual/current/performance/memory-configuration/
- Ports: https://neo4j.com/docs/operations-manual/current/configuration/ports/
- Cypher Shell: https://neo4j.com/docs/operations-manual/current/cypher-shell/
- Neo4j Browser: https://neo4j.com/docs/browser-manual/current/
