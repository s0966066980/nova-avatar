# Share the reply contract across models

Type: task
Status: resolved

## Reproduction

The production generation/parser/TTS-text probe on Qwen3.5-2B-UD-Q4_K_XL
emitted SIMPLE then BOARD for both an installation question and a greeting.
Only LFM requests had grammar constraints; other local models received an
incomplete SIMPLE example. Fixed prompts also duplicated the editable activation
policy. Saving Prompt/Rules used two requests and reused the model-switch action.

## Changes

`src/llm/reply_contract.py` owns shared channel syntax and summary protection.
All llama.cpp AUTO requests receive its grammar; LFM only adds the required
thinking envelope. Identity, restrictions and editable Rules stay in the common
prompt composer. Providers without GBNF use the same prompt and speech guard.
Model selection preserves persona/Rule drafts; `/api/llm/behavior` saves persona
and Rules together with revision checking and rollback on persistence failure.

## Comments

- Regression tests failed before fixes at the real generation/request seams.
- Grammar constrains syntax, not semantic correctness. Live probes also check
  mode choice, requested counts, spoken text and completion markers.
- An initial title-overlap check rejected valid conclusions mentioning two
  comparison themes. The final probe checks full item content and complete
  title-list repetition; sequence-list regressions have dedicated streamed tests.
- Official grammar reference: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

## Answer

Shared contract is active after restarting the backend. Qwen remains selected;
the complete LLM/video settings snapshot matches before and after restart.
Model-only updates also retain a persona saved while model loading is underway.

Final real-model probes: Qwen default Rules 10/10 and custom Rules 5/5;
LFM default Rules 5/5 and custom Rules 5/5. Each checks one mode, expected item
counts, no board payload/title-list repetition in TTS text, and a complete END.
The default activation examples are only included with the unchanged default
Rule; customized activation receives its own policy at the end of the prompt.

Actual browser verification at 1600px and 375px: model request omits persona,
persona/Rule drafts survive model application, atomic behavior save succeeds,
saved settings remain unchanged, no page errors or horizontal overflow.

Validation: focused backend 143 passed, 1 skipped, 13 subtests; full backend
530 passed, 4 skipped, 1 existing failure. The existing native 1080×1920 chroma
performance test measured 35.39ms against its 30ms threshold; its implementation
and threshold were not changed. Frontend 93 passed; production build and project
integration/branding checks passed. See `docs/llm-reply-rules.md` for operation.
