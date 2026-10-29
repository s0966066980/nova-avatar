<!--
Copyright (c) 2026 HongXian0903
SPDX-License-Identifier: Apache-2.0
-->

# Source Attribution Audit

Updated: 2026-10-29

This is the maintained classification record for Nova Avatar source roots. It
does not relicense code, models, weights, voices, datasets, or services. The
root [LICENSE](../LICENSE), [NOTICE](../NOTICE), and
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) remain controlling where
applicable.

## Classification

| Source root | Classification | Required treatment | Current action |
| --- | --- | --- | --- |
| `src/server/`, `src/config/`, `src/llm/`, `src/tts/`, `src/vad/`, `src/asr/`, `web/`, `scripts/` | Inherited and substantially modified Nova Avatar application code | Retain applicable Linly-Talker-Stream / LiveTalking attribution and an explicit modification notice. | Audit headers individually before changing them; do not bulk replace. |
| `src/avatars/musetalk/` | MuseTalk-derived integration plus Nova Avatar orchestration | Retain Tencent Music Entertainment Group copyright and MIT attribution for derived code. Models and dependencies need their own review. | Local MuseTalk license copy is retained. Individual-file origin review remains open. |
| `src/avatars/wav2lip/` | Wav2Lip-derived integration | Retain upstream restriction and label the integration **Research / Non-commercial**. | Excluded from `config/config_commercial.yaml`; no commercial distribution claim. |
| `src/avatars/ernerf/`, `src/avatars/talkinggaussian/`, `src/avatars/ultralight/` | Bundled optional engines and third-party/vendor trees | Preserve embedded notices and verify code, submodules, models, datasets, and assets independently. | Not selected by the commercial review profile; per-component license review is open. |
| `third_party/licenses/` | Third-party license notices | Keep without rebranding. | MuseTalk MIT and Wav2Lip non-commercial notices are present. |
| `src/scene/`, `src/ragflow/`, `integrations/ragflow/` | Nova Avatar-authored integration code | Nova Avatar Apache-2.0 SPDX header; RAGFlow itself is an external service, not bundled source. | Files carry the Nova Avatar header. |
| `docs/`, `tests/` and new Nova Avatar-only files | Nova Avatar-authored unless a file identifies another source | Use the Nova Avatar Apache-2.0 SPDX header only after confirming no copied third-party source. | New audit, workflow, stack, and profile files use Nova Avatar attribution. |

## Evidence and boundaries

- `NOTICE` retains Kedreamix, Linly-Talker-Stream, and LiveTalking attribution.
- `THIRD_PARTY_NOTICES.md` records the MuseTalk MIT boundary and Wav2Lip's
  non-commercial restriction.
- Runtime catalog and settings label Wav2Lip as `Research / Non-commercial`.
- `config/config_commercial.yaml` uses MuseTalk, not Wav2Lip. It is a
  deployment starting point, not an entitlement to distribute any artifact.

## Follow-up source work

Do not add identical headers across vendor trees. For each source file changed
in future work, first classify it as inherited/modified, Nova Avatar-authored,
MuseTalk-derived, Wav2Lip-derived, or other third-party/generated code. Then
retain or add the source-specific notice required by that classification.

The remaining per-file provenance review is intentionally tracked as ongoing
maintenance, not represented as complete by this root-level audit.

## 2026-10-29: Independent conversations

The conversation coordinators, presentation module, deferred resource settings,
related tests and domain documents are Nova Avatar-authored Apache-2.0 files.
Changes to inherited voice/WebRTC lifecycle, server state, LLM service and web
application files retain their existing upstream and modification notices.
No bundled third-party source or license was modified by this change.

The pending-submission interruption fix retains the inherited App and voice
session notices. The shared composer, regression tests and conversation docs
are Nova Avatar-authored Apache-2.0 files; no third-party source was changed.

The reverse role handoff change updates Nova Avatar-authored profile routing,
coordination, persistence, default content, settings UI and regression tests.
The inherited voice session retains its existing upstream and modification
notice. No bundled third-party code, model or license notice was changed.

The console idle-reset update retains the inherited voice session and settings
panel notices, and updates Nova Avatar-authored conversation coordination,
session metadata, memory UI, tests and documentation. No third-party code or
license notice was changed.

The weather-context capacity fix changes Nova Avatar-authored weather prompt
transport and regression coverage. Source facts in validation fixtures retain
CWA source metadata; no model weights, third-party implementation or license
notice was changed.

The console layout update retains the inherited App and settings-panel notices.
The console stylesheet carries an explicit modification notice and points to
the root LICENSE and NOTICE. The conversation and voice-test panels, behavioral
regression tests, design notes and layout preview retain Nova Avatar Apache-2.0
headers. No third-party implementation, model, weight or license was changed;
the Wav2Lip Research / Non-commercial label is retained.
