# Speech models (ASR/TTS) and the NIM Operator

Date: 2026-11-19. Research note, not a deployed system. Operator facts come from `NVIDIA/k8s-nim-operator` at tag `v3.1.4` (source tarball read locally). Speech NIM facts come from NVIDIA's current speech NIM docs (`docs.nvidia.com/nim/speech/latest`, pages last updated 2026-11-06). LLM-side background: [08-target-state-reference](08-target-state-reference.md).

## Summary

- NVIDIA ships speech NIMs for ASR (Whisper Large v3, Canary 1b, Parakeet CTC/TDT/RNNT, Nemotron ASR Streaming, Nemotron Transcribe) and TTS (Magpie TTS Multilingual, Magpie TTS Zeroshot, Chatterbox TTS Multilingual). Almost all serve gRPC on 50051 and HTTP on 9000. The model is chosen at start-up with `NIM_TAGS_SELECTOR`, not by image name alone.
- Whisper Large v3 as a NIM has an OpenAI-style `POST /v1/audio/transcriptions` (multipart form: `file`, `language`). It is offline only, needs about 12.5 GB GPU memory, and the NIM docs ask for a GPU with 16 GB VRAM.
- The operator has no speech-specific support, but it does not need any. v3.1.4 ships one Riva TTS sample (`NIMCache` plus `NIMService` with `port: 9000`, `grpcPort: 50051`). So a speech NIM fits the same two-object pattern as an LLM NIM, with the caveats in section 2.
- A community Whisper container is not a NIM. `NIMService` is built around NIM conventions (named probes, `/v1/health/*`, `NIM_*` env), so it can often run but is a poor fit. The honest option is to leave it as a plain `Deployment`, or to replace it with the Whisper NIM.
- Both the operator's default probes and the speech NIM's documented health path are `/v1/health/ready` on the HTTP port. That lines up as long as `expose.service.port` is set to 9000, not left at the operator default 8000.

## The plain version

Picture the model platform as a kitchen. The big language models are the main chefs, and the operator is the kitchen manager who orders ingredients (weights), puts them on a shelf, and starts each chef when the shelf is full. Speech models are two extra staff: a listener (speech to text) and a speaker (text to speech).

NVIDIA sells ready-made listeners and speakers. They work almost like the language chefs: they download their own ingredients on first start, they open two doors (a web door on 9000 and a gRPC door on 50051), and they say "ready" at the same address. So the kitchen manager can run them with the same two order forms. NVIDIA even ships one sample for a speaker.

The catch is the listener the platform runs today. It is believed to be an open-source Whisper packed by someone else, not an NVIDIA product. The manager's forms are written for NVIDIA's packaging. A different package might work if it answers the same questions, but nobody at NVIDIA promises it, and the forms control things (the ports, the shelf path, the health check) that a different package may do differently.

So the sensible plan has three branches. If the listener is already NVIDIA's, move it onto the forms. If it is the open-source one, either swap it for NVIDIA's Whisper, or leave it as a plain deployment and file it in the same repository next to the forms. The speaker, if there is one, follows whichever branch matches its package. Speech models are small compared with the language models, so the shelf and the risk are small too.

## 1. Which speech NIMs exist

Source: [ASR model index](https://docs.nvidia.com/nim/speech/latest/asr/deploy-asr-models/index.html), [ASR support matrix](https://docs.nvidia.com/nim/speech/latest/reference/support-matrix/asr.html), [TTS deploy page](https://docs.nvidia.com/nim/speech/latest/tts/deploy-tts-model.html).

Image pattern in the current docs: `nvcr.io/nim/nvidia/$CONTAINER_ID:latest`. Older Riva releases used shared images (`nvcr.io/nim/nvidia/riva-asr`, `riva-tts`) with the model picked by selector; the operator sample still uses `riva-tts:1.3.0`. Check which style your registry mirror holds.

### ASR

| Model | `CONTAINER_ID` | Example `NIM_TAGS_SELECTOR` | GPU mem (GB) |
|---|---|---|---|
| Whisper Large v3 (offline) | `whisper-large-v3` | `name=whisper-large-v3,mode=ofl` | 12.5 |
| Canary 1b Multilingual (offline) | `canary-1b` | `mode=ofl` | 13.4 |
| Parakeet 0.6b CTC English | `parakeet-0-6b-ctc-en-us` | `name=parakeet-0-6b-ctc-en-us,mode=ofl,diarizer=disabled,vad=default` | 11.9 (offline), 3.1 (streaming) |
| Parakeet 1.1b CTC English | `parakeet-1-1b-ctc-en-us` | `diarizer=disabled,mode=ofl,vad=default` | 5.8 |
| Parakeet 0.6b TDT | `parakeet-0.6b-tdt` | `type=default` | 13.8 |
| Parakeet 1.1b RNNT Multilingual | `parakeet-1-1b-rnnt-multilingual` | `diarizer=sortformer,mode=ofl,type=default,vad=silero` | 25.6 |
| Parakeet CTC vi / es / zh-CN / zh-TW | `parakeet-ctc-0.6b-{vi,es,zh-cn,zh-tw}` | `mode=ofl,vad=default,diarizer=disabled` | 5.2 to 7.3 |
| Nemotron ASR Streaming | `nemotron-asr-streaming` | see support matrix | UNVERIFIED |
| Nemotron Transcribe | `nemotron-transcribe` | see its own guide | UNVERIFIED |

General ASR requirement: compute capability 8.0 or higher and at least 16 GB VRAM; A10, A30, A100, L4, L40, H100 and recent GeForce are listed; NVIDIA driver 535 or newer. Parakeet, Canary and Whisper are listed with CPU memory of 4 to 7 GB.

Notes:

- Whisper and Canary are offline (batch) only. Streaming needs a Parakeet or Nemotron streaming profile.
- Nemotron Transcribe is HTTP only on 9000, "does not run Triton", and uses an OpenAI-compatible API.
- A NVIDIA forum report describes a Whisper profile that kept downloading a Parakeet model ([forum thread](https://forums.developer.nvidia.com/t/riva-speech-1-2-0-and-whisper-large-download-issue/321210)). Confirm the downloaded model after first start.

### TTS

| Model | `CONTAINER_ID` | `NIM_TAGS_SELECTOR` | Notes |
|---|---|---|---|
| Magpie TTS Multilingual | `magpie-tts-multilingual` | `name=magpie-tts-multilingual` (default `batch_size=8`; append `,batch_size=32`) | 12 languages, streaming and offline |
| Magpie TTS Zeroshot | `magpie-tts-zeroshot` | `name=magpie-tts-zeroshot` | voice cloning; access restricted |
| Chatterbox TTS Multilingual | `chatterbox-tts-multilingual` | `name=chatterbox-tts-multilingual` | 23 languages |

FastPitch: the current TTS deploy page does not mention it. An older 1.x Riva TTS doc used `CONTAINER_ID=riva-tts` with `name=fastpitch-hifigan-en-us` (seen in a search snippet only). UNVERIFIED: whether FastPitch is still published. TTS GPU memory figures are not on the deploy page; see the TTS support matrix (UNVERIFIED: values).

### Protocols

- Default: gRPC 50051 and HTTP 9000, set in `docker run` with `-e NIM_HTTP_API_PORT=9000 -e NIM_GRPC_API_PORT=50051`.
- HTTP ASR: `POST /v1/audio/transcriptions` (also `/v1/audio/translations` for Whisper). HTTP TTS: `POST /v1/audio/synthesize` (offline) and `/v1/audio/synthesize_online` (raw LPCM stream), plus `GET /v1/audio/list_voices`.
- There is also a Realtime WebSocket API on 9000 for ASR and TTS.
- The ASR 1.4.0 release notes say the HTTP API accepts only `file`, `model` and `language`, and gRPC supports only offline `Recognize` for Whisper (from a search snippet of the release notes; UNVERIFIED against the latest release).
- Whether `/v1/audio/transcriptions` is a full OpenAI drop-in (response formats, `model` handling, streaming): UNVERIFIED. Treat it as OpenAI-shaped and test the client.

## 2. Does the operator support speech NIMs

Short answer: not by name, but the generic path works and NVIDIA ships a sample. Evidence at tag v3.1.4:

1. **A Riva TTS sample exists.** `config/samples/nim/serving/standalone/routers/grpcroutes/llm.yaml` defines a `NIMCache` with `modelPuller: nvcr.io/nim/nvidia/riva-tts:1.3.0` (50Gi RWO PVC) and a `NIMService` with `storage.nimCache.profile: ''`, `nvidia.com/gpu: 1`, and `expose.service: {port: 9000, grpcPort: 50051}` plus a gateway `grpcRoutesEnabled: true`. `config/samples/nim/README.md` lists "Riva TTS | `nvcr.io/nim/nvidia/riva-tts` | `1.3.0`".
2. **No other speech content.** A grep for riva, parakeet, whisper, magpie and canary across `api/`, `internal/`, `manifests/`, `docs/` and `config/samples/` finds only that sample and the README row. There is no ASR sample and no Whisper sample.
3. **`NIMCache` is not LLM-specific in its schema.** `nimcache_types.go` has `source.ngc.modelPuller`, with the profile selectors (`engine`, `precision`, `tensorParallelism`, `gpus`, `profiles`) all optional. It simply runs the NIM image's own `download-to-cache` as a Job ([08](08-target-state-reference.md) cites `nimcache_controller.go` L1377). The sample uses an empty profile. UNVERIFIED: whether the speech NIM image has the `list-model-profiles` and `download-to-cache` commands the cache Job relies on, and whether it downloads the selector-chosen model. The sample's existence suggests it works for TTS; nothing shows it for ASR.
4. **Ports and probes line up only if you set them.** The `NIMService` container port named `api` is `spec.expose.service.port` (default 8000; `nimservice_types.go` L1351-L1353). Default probes are named-port HTTP GETs: liveness `/v1/health/live`, readiness and startup `/v1/health/ready` (L689-L744). The operator sets `NIM_HTTP_API_PORT` and `NIM_SERVER_PORT` from `port`, and `NIM_GRPC_API_PORT` from `grpcPort` (L327-L363). So `port: 9000` makes the probes, Service and NIM agree. The `grpcPort` field is documented as "only applicable for NIMs that run a Triton GRPC Inference Server" (`common_types.go` L159-L164); Riva speech NIMs run on Triton, so this fits.
5. **Cache path.** The operator mounts the PVC at `/model-store` and sets `NIM_CACHE_PATH=/model-store` (`internal/utils`, `DefaultModelStorePath`). Docs for the speech NIM mention mounting a cache directory but I could not read that page (the Model Caching URL returned 404). UNVERIFIED: that the speech NIM honours `NIM_CACHE_PATH` and not only a default path such as `/opt/nim/.cache`.
6. **Model selection.** `NIM_TAGS_SELECTOR` is not an operator field. Put it in `spec.env`. `storage.nimCache.profile` becomes `NIM_MODEL_PROFILE`, which is an LLM-style profile id; speech NIMs select by tags. Leave `profile` empty as the sample does. UNVERIFIED: whether an empty profile plus `NIM_TAGS_SELECTOR` in `env` is enough for the cache Job to fetch the right model; the Job container may not see `spec.env`.
7. **No-cache options exist.** `NIMService.spec.storage` accepts `pvc` (existing or created), `emptyDir`, or `hostPath` (`nimservice_types.go` around L264), with samples under `config/samples/nim/serving/standalone/no-precaching/` (`llm-emptydir.yaml`, `llm-hostpath.yaml`, `llm.yaml`). For speech, a `pvc.name` pointing at the existing weights PVC is the closest match to the current setup. 08 already names this as the fallback if `NIMCache` does not reach `Ready` on a pre-filled PVC.
8. **Metrics and sizing.** Speech NIM metrics endpoints are UNVERIFIED. Leave `metrics.enabled` off until confirmed. The default `sharedMemorySizeLimit` should be set to at least 8Gi to match the documented `--shm-size=8GB`.

Air-gap: the speech NIM downloads on first start using `NGC_API_KEY`. In an air-gapped cluster the weights must be pre-staged on the PVC; that is the same constraint as the LLM side, and the same UNVERIFIED about offline start-up applies (does a populated cache avoid any NGC call).

## 3. A community Whisper container

If the running model is an open-source Whisper server (for example faster-whisper or whisper.cpp wrapped in a web server, or an OpenAI-compatible wrapper), what follows:

- **It is not a NIM.** It has no `NIM_*` handling, no `download-to-cache` command, no `list-model-profiles`, and probably no `/v1/health/ready`. `NIMCache` cannot be used at all (its Job runs NIM tooling inside the image). Do not try.
- **`NIMService` could in principle run it** (it only needs `image.repository`, `image.tag`, a GPU request and a port), but the operator would inject env it ignores (`NIM_*`), force named-port HTTP probes on `/v1/health/*` that the container may not serve (probes can be overridden in `spec`), set a fixed rolling-update strategy (per 08, `maxSurge: 0`), and run the pod as the operator's user/group (1000/2000 by default; a community image may need root or a specific uid). Each of these is a thing that can silently misbehave. UNVERIFIED: that a non-NIM image runs cleanly under `NIMService`; I did not test it.
- **What you gain by forcing it:** one status shape (`status.state`), one health-check Lua in ArgoCD, and consistent labels. Small gain, new risk.
- **Recommended:** keep the plain `Deployment`, `Service` and weights PVC as ordinary manifests in the same repository and ArgoCD application set, but label them like the NIM objects so NetworkPolicies and dashboards treat them alike. Revisit once the question "why not the Whisper NIM" is answered (licence, GPU memory, features, cost of an NGC entitlement).
- **If replacing with the Whisper NIM:** the API surface changes. `POST /v1/audio/transcriptions` takes `language` values like `en-US` or `multi`, not necessarily the same fields as the community server. Clients need a compatibility test before cut-over. The NIM is offline-mode only for Whisper and requires NVIDIA's licence terms for production (UNVERIFIED: entitlement needed; the NIM images need an NGC key to pull and download).

## 4. Probes, ports and a smoke test

### Health

- HTTP port 9000: `GET /v1/health/ready` returns `{"status":"ready"}` when set-up is done (TTS page). The Riva ASR Helm page lists liveness `/v1/health/live` and readiness and startup `/v1/health/ready` ([Helm page](https://docs.nvidia.com/nim/riva/asr/latest/deploy-helm.html), probe table seen via search snippet; port not shown). The TTS deploy page does not document a liveness path. UNVERIFIED: that `/v1/health/live` exists on all speech NIMs.
- gRPC 50051: no health service is documented. UNVERIFIED: whether `grpc.health.v1.Health` is available. Use HTTP probes.
- First start can take up to 30 minutes (model download plus engine build; Chatterbox may take longer). Keep the operator's default startup probe (about 21 minutes) or raise it to at least 30 to 40 minutes, and use a warm cache so restarts are fast.

### Operator manifest sketch (speech NIM, not applied anywhere)

```yaml
apiVersion: apps.nvidia.com/v1alpha1
kind: NIMService
metadata: {name: whisper-large-v3}
spec:
  image: {repository: registry.example.internal/nim/whisper-large-v3, tag: "<pinned>", pullSecrets: [pull-secret]}
  env:
  - {name: NIM_TAGS_SELECTOR, value: "name=whisper-large-v3,mode=ofl"}
  storage:
    pvc: {name: speech-weights}        # or nimCache: {name: ..., profile: ''}
    sharedMemorySizeLimit: 8Gi
  resources: {limits: {nvidia.com/gpu: 1}}
  expose: {service: {type: ClusterIP, port: 9000, grpcPort: 50051}}
```

Field names are from the v3.1.4 types; the values are placeholders and the whole sketch has not been schema-validated.

### Smoke tests

HTTP (from the Whisper docs):

```bash
kubectl -n <ns> port-forward svc/whisper-large-v3 9000:9000 &
curl -s localhost:9000/v1/health/ready
curl -s http://localhost:9000/v1/audio/transcriptions -F language=en-US -F file="@sample.wav"
```

Use `language=multi` for auto-detect. The expected result is a JSON transcript (response shape UNVERIFIED).

TTS:

```bash
curl -s localhost:9000/v1/audio/list_voices
curl -sS http://localhost:9000/v1/audio/synthesize --fail-with-body \
  -F language=en-US -F text="smoke test" \
  -F voice=Magpie-Multilingual.EN-US.Aria --output out.wav
```

gRPC: the docs use the Riva Python client, not `grpcurl`. For TTS: `python3 python-clients/scripts/tts/talk.py --server <host>:50051 --list-voices`. For ASR the docs copy a sample from `/opt/riva/wav` and run `transcribe_file_offline.py --server <host>:50051`. `grpcurl` needs reflection or the Riva `.proto` files; whether reflection is enabled is UNVERIFIED. For a probe-only check, `grpcurl -plaintext -import-path <riva-protos> -proto riva_asr.proto <host>:50051 list` would work with the protos from the `nvidia-riva/common` repo (UNVERIFIED: proto file name and path).

A NetworkPolicy should allow both 9000 and 50051 from the gateway. The LLM policy in 08 only opens 8000.

## 5. Recommendation

| Case | Operator approach | Effort | Risk |
|---|---|---|---|
| NVIDIA speech NIM already running (Riva ASR or Whisper NIM) | `NIMService` with `port: 9000`, `grpcPort: 50051`, `NIM_TAGS_SELECTOR` in `env`, GPU 1, shm 8Gi. Start with existing PVC via `storage.pvc.name`; try `NIMCache` once it is proven on a staging copy | Low to medium: a day or two, mostly testing offline start | Low to medium: cache Job behaviour with a selector and offline pre-fill are UNVERIFIED |
| Community or open-source Whisper container | Keep a plain `Deployment`, `Service` and PVC in the same GitOps repo; label like NIM objects; do not use `NIMService` or `NIMCache` | Very low (nothing changes) | Low; the cost is two deployment styles to maintain |
| Community Whisper, replacing with Whisper Large v3 NIM | Treat as a migration plus an API compatibility test; then as the first row | Medium: client changes, licence and NGC access, re-test of accuracy and latency | Medium: API differences, offline-only mode, 16 GB VRAM guidance |
| TTS NIM (Magpie, Chatterbox) | Same as the first row; the operator sample (`riva-tts`, port 9000, `grpcPort` 50051) is the closest precedent. Pin the voice and batch size via selector | Low to medium | Low to medium: first start up to 30 minutes; character limits (2,000 Magpie, 500 Chatterbox) |
| TTS that is not a NIM | As the second row | Very low | Low |

Cross-cutting: pin image tags and selectors in git, put `Prune=false,Delete=false` on any `NIMCache` PVC (see 08 key finding 4), and run the smoke test above as an ArgoCD post-sync check or a manual gate.

## Questions to answer from the deployment repo

1. What is the exact image (registry, name, tag or digest) of the speech deployment? Is it under `nvcr.io/nim/...` (a NIM) or a community project?
2. Which model and size is it (Whisper tiny, base, large-v3; `faster-whisper` or `whisper.cpp`), and is there any TTS at all?
3. Which API do clients call (`/v1/audio/transcriptions`, `/asr`, gRPC)? Which request fields and response formats do they depend on?
4. How is the weights PVC filled (init container, out-of-band copy), its size, access mode, storage class, and mount path? Does the container expect a specific path?
5. Which ports, probes and security context (`runAsUser`, `fsGroup`, `readOnlyRootFilesystem`) does the current manifest set?
6. GPU request, node selector, tolerations, `/dev/shm` size, any MIG or time-slicing.
7. Replica count and rollout strategy; is brief downtime acceptable (operator strategy is fixed)?
8. Are there NetworkPolicies, an ingress or gateway route, and metrics scraping for it?
9. How many users and what traffic (concurrency, audio length)? This decides batch size and whether streaming ASR matters.
10. Is there an NGC entitlement and an internal registry mirror for NIM images, and is the cluster air-gapped (then weights must be pre-staged)?

## References

Fetched 2026-11-19.

- Speech NIM docs home and ASR model index: https://docs.nvidia.com/nim/speech/latest/asr/deploy-asr-models/index.html
- Whisper Large v3 deploy page: https://docs.nvidia.com/nim/speech/latest/asr/deploy-asr-models/whisper.html (last updated 2026-11-06)
- ASR support matrix: https://docs.nvidia.com/nim/speech/latest/reference/support-matrix/asr.html
- TTS deploy page: https://docs.nvidia.com/nim/speech/latest/tts/deploy-tts-model.html
- TTS tutorial (Riva Python client examples): https://docs.nvidia.com/nim/speech/latest/get-started/tutorials/tts.html
- Riva ASR NIM docs (older line, ports and Helm): https://docs.nvidia.com/nim/riva/asr/latest/support-matrix.html, https://docs.nvidia.com/nim/riva/asr/latest/deploy-helm.html
- Riva TTS NIM docs: https://docs.nvidia.com/nim/riva/tts/latest/support-matrix.html
- build.nvidia.com Whisper deploy page: https://build.nvidia.com/openai/whisper-large-v3/deploy (seen in search only)
- build.nvidia.com Magpie deploy page: https://build.nvidia.com/nvidia/magpie-tts-multilingual/deploy (seen in search only)
- Forum thread on Whisper profile downloading Parakeet: https://forums.developer.nvidia.com/t/riva-speech-1-2-0-and-whisper-large-download-issue/321210
- Operator at tag v3.1.4: https://github.com/NVIDIA/k8s-nim-operator/tree/v3.1.4. Paths read: `config/samples/nim/serving/standalone/routers/grpcroutes/llm.yaml`, `config/samples/nim/README.md`, `config/samples/nim/serving/standalone/no-precaching/`, `api/apps/v1alpha1/nimservice_types.go`, `api/apps/v1alpha1/nimcache_types.go`, `api/apps/v1alpha1/common_types.go`, `internal/controller/platform/standalone/nimservice.go`, `internal/utils/utils.go`.
- Local: [08-target-state-reference](08-target-state-reference.md)
