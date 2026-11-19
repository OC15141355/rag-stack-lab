# Appendix C: Reference: Speech models under the NIM Operator

> **[MACRO: Page Properties]** Status DRAFT · Owner <you> · Checked 2026-11-19

**Purpose:** how the Project's speech model (believed Whisper ASR) fits the operator migration.

## In short

- NVIDIA offers **speech NIMs**:
  - ASR: Whisper Large v3, Parakeet, Canary, Nemotron ASR.
  - TTS: Magpie TTS, Chatterbox.

  The model is selected with `NIM_TAGS_SELECTOR` (e.g. `name=whisper-large-v3,mode=ofl`). Ports are **HTTP 9000** and **gRPC 50051**. Whisper serves `POST /v1/audio/transcriptions` and runs offline only, needing about 12.5 GB of GPU memory.
- The **NIM Operator has no speech-specific code**, but the generic `NIMService` path fits: set `port: 9000`, `grpcPort: 50051`, `NIM_TAGS_SELECTOR` in `env`, and leave `profile` empty. The operator ships a Riva TTS sample (v3.1.4; its NIMService part is commented out). There is no ASR sample.
- A **community Whisper image is not a NIM**: `NIMCache` can't handle it, and `NIMService` assumes NIM behaviour.

## Decision table

| Current speech image | Approach | Effort / risk |
|---|---|---|
| NVIDIA speech NIM (`nvcr.io/nim/...`) | `NIMService` like the LLMs, with speech ports/selector; NetworkPolicy opens 9000/50051 | S, low |
| Community Whisper | Keep as a plain Deployment in the same repo, **or** replace with the Whisper NIM after an API compatibility test | S (keep) / M (replace) |
| TTS NIM as well | Same as the first row | S, low |

## To confirm from the deployment repo

- Image source and tag; ports; GPU request; any env vars; is it ASR, TTS or both?
- Is speech in scope for this ticket?
