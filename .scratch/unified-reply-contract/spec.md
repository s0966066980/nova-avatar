# Unified spoken and board replies

Keep the console's assistant identity, System Prompt, restrictions and editable
Rules independent of the selected language model. One model chooses the mode
and generates both channels. Switching models must retain the same format and
saved behavior, without requiring a model-specific Prompt.

Acceptance: complete SIMPLE and BOARD formats; no late SIMPLE-to-BOARD switch
on constrained local requests; only spoken summaries reach TTS/history;
step lists accidentally emitted in BOARD speech are guarded before playback;
model switching retains saved behavior and unsaved drafts; persona and Rules
save atomically without loading a model. Validate Qwen 3.5 2B and LFM 2.5 with
the same question set and custom activation Rules, plus focused and full checks.
