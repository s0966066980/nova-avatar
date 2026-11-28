// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// LLM settings: the model endpoint and model, the assistant prompt, and the reply rules.
// The store in composables/useRuntimeSettings.js composes this with the other settings.

import { computed, reactive, ref } from 'vue'
import { parseJson, runtime } from './shared.js'

export const ollama = reactive({
  models: [],
  reachable: false,
  error: '',
  current: '',
  base_url: '',
  endpoint: ''
})

export const llamacpp = reactive({
  models: [],
  reachable: false,
  error: '',
  base_url: '',
  endpoint: '',
  server_running: false,
  binary: ''
})

export const selectedProvider = ref('ollama')

export const loadingModels = ref(false)

export const applyingLlm = ref(false)

export const modelsError = ref('')

export const selectedLlm = ref('')

export const selectedSystemPrompt = ref('')

export const selectedRestrictionPrompt = ref('')

export const selectedAssistantName = ref('')

export const selectedOutputLocale = ref('zh-TW')

export const selectedEnforceOutputLocale = ref(true)

export const selectedForbiddenSelfNames = ref('')

export const selectedResponseMaxChars = ref(120)

export const selectedBoardMaxItems = ref(8)

export const selectedReplyMode = ref('legacy')

export const selectedSemanticWaitSeconds = ref(0.5)

export const rulesDraft = reactive({ activation: '', speech: '', board: '' })

export const rulesApplied = reactive({ revision: 1, activation: '', speech: '', board: '' })

export const rulesDefaults = reactive({ revision: 1, activation: '', speech: '', board: '' })

export const rulesLimits = reactive({ max_rule_chars: 12000, max_total_chars: 24000 })

export const rulesLoading = ref(false)

export const rulesSaving = ref(false)

export const rulesError = ref('')

export const rulesNotice = ref('')

export const rulesDirty = computed(() => JSON.stringify(rulesDraft) !== JSON.stringify({
  activation: rulesApplied.activation,
  speech: rulesApplied.speech,
  board: rulesApplied.board
}))

export const responseLengthError = computed(() => {
  const value = Number(selectedResponseMaxChars.value)
  return !Number.isInteger(value) || value < 20 || value > 2000
})

export const boardItemsError = computed(() => {
  const value = Number(selectedBoardMaxItems.value)
  return !Number.isInteger(value) || value < 1 || value > 12
})

export const currentProviderModels = computed(() => {
  return selectedProvider.value === 'llamacpp' ? llamacpp.models : ollama.models
})

export const promptDirty = computed(() => (
  selectedSystemPrompt.value !== (runtime.llm.system_prompt || '') ||
  selectedRestrictionPrompt.value !== (runtime.llm.assistant_profile?.restriction_prompt || '') ||
  selectedAssistantName.value !== (runtime.llm.assistant_profile?.assistant_name || '') ||
  selectedOutputLocale.value !== (runtime.llm.assistant_profile?.output_locale || 'zh-TW') ||
  Boolean(selectedEnforceOutputLocale.value) !== Boolean(runtime.llm.assistant_profile?.enforce_output_locale ?? true) ||
  selectedForbiddenSelfNames.value !== (runtime.llm.assistant_profile?.forbidden_self_names || []).join('\n')
))

export const llmDirty = computed(() => {
  if (!selectedLlm.value || responseLengthError.value || boardItemsError.value) return false
  return (
    selectedProvider.value !== runtime.llm.provider ||
    selectedLlm.value !== runtime.llm.model ||
    Number(selectedResponseMaxChars.value) !== Number(runtime.llm.response_max_chars || 120) ||
    Number(selectedBoardMaxItems.value) !== Number(runtime.llm.board_max_items || 8) ||
    selectedReplyMode.value !== (runtime.llm.reply_mode || 'legacy') ||
    Number(selectedSemanticWaitSeconds.value) !== Number(runtime.llm.semantic_wait_seconds || 0.5)
  )
})

export async function loadReplyRules() {
  rulesLoading.value = true
  rulesError.value = ''
  try {
    const data = await parseJson(await fetch('/api/llm/rules'))
    Object.assign(rulesApplied, data.rules || {})
    runtime.llm.reply_rules = { ...rulesApplied }
    Object.assign(rulesDraft, {
      activation: data.rules?.activation || '',
      speech: data.rules?.speech || '',
      board: data.rules?.board || ''
    })
    Object.assign(rulesDefaults, data.defaults || {})
    Object.assign(rulesLimits, data.limits || {})
    return data
  } catch (error) {
    rulesError.value = error.message
    throw error
  } finally {
    rulesLoading.value = false
  }
}

export function restoreDefaultRules() {
  rulesDraft.activation = rulesDefaults.activation || ''
  rulesDraft.speech = rulesDefaults.speech || ''
  rulesDraft.board = rulesDefaults.board || ''
  rulesNotice.value = '已回填預設規則，請按儲存並套用。'
}

export async function applyReplyRules() {
  if (!rulesDirty.value) return rulesApplied
  rulesSaving.value = true
  rulesError.value = ''
  rulesNotice.value = ''
  try {
    const data = await parseJson(await fetch('/api/llm/rules', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: rulesApplied.revision,
        rules: { ...rulesDraft }
      })
    }))
    Object.assign(rulesApplied, data.rules || {})
    runtime.llm.reply_rules = { ...rulesApplied }
    rulesNotice.value = '已套用，從下一輪生效。'
    return data
  } catch (error) {
    rulesError.value = error.message
    throw error
  } finally {
    rulesSaving.value = false
  }
}

export async function applyLlmBehavior() {
  rulesSaving.value = true
  rulesError.value = ''
  rulesNotice.value = ''
  try {
    const data = await parseJson(await fetch('/api/llm/behavior', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_revision: rulesApplied.revision,
        assistant_profile: {
          assistant_name: selectedAssistantName.value,
          system_prompt: selectedSystemPrompt.value,
          restriction_prompt: selectedRestrictionPrompt.value,
          output_locale: selectedOutputLocale.value,
          enforce_output_locale: Boolean(selectedEnforceOutputLocale.value),
          forbidden_self_names: selectedForbiddenSelfNames.value.split('\n').map((value) => value.trim()).filter(Boolean)
        },
        rules: { ...rulesDraft }
      })
    }))
    runtime.llm.system_prompt = data.system_prompt
    runtime.llm.assistant_profile = data.assistant_profile
    Object.assign(rulesApplied, data.rules)
    runtime.llm.reply_rules = { ...rulesApplied }
    rulesNotice.value = '角色與規則已儲存，切換模型後繼續共用。'
    return data
  } catch (error) {
    rulesError.value = error.message
    throw error
  } finally {
    rulesSaving.value = false
  }
}

export function applyProviderBlock(target, block) {
  target.models = block.models || []
  target.reachable = Boolean(block.reachable)
  target.error = block.error || ''
  target.base_url = block.base_url || ''
  target.endpoint = block.name || ''
}

export const PROVIDER_LABELS = { ollama: 'Ollama', llamacpp: 'llama.cpp' }

// The console picks a provider; the server only accepts a configured endpoint name.
export function endpointForProvider(provider) {
  if (provider === runtime.llm.provider && runtime.llm.endpoint) return runtime.llm.endpoint
  const endpoint = (provider === 'llamacpp' ? llamacpp : ollama).endpoint
  if (!endpoint) {
    throw new Error(`伺服器設定檔 llm.endpoints 沒有 ${PROVIDER_LABELS[provider] || provider} 端點`)
  }
  return endpoint
}

export async function loadOllamaModels() {
  loadingModels.value = true
  modelsError.value = ''
  try {
    const data = await parseJson(await fetch('/api/llm/models'))
    const current = data.current || {}
    const providers = data.providers || {}

    if (providers.ollama) {
      applyProviderBlock(ollama, providers.ollama)
    } else {
      applyProviderBlock(ollama, data)
    }
    ollama.current = current.model || runtime.llm.model

    if (providers.llamacpp) {
      applyProviderBlock(llamacpp, providers.llamacpp)
      llamacpp.server_running = Boolean(providers.llamacpp.server_running)
      llamacpp.binary = providers.llamacpp.binary || ''
    }

    if (current.provider) {
      selectedProvider.value = current.provider
    }
    if (current.model) {
      selectedLlm.value = current.model
    }

    const active = selectedProvider.value === 'llamacpp' ? llamacpp : ollama
    modelsError.value = active.reachable ? '' : (active.error || '')
    return data
  } catch (error) {
    ollama.reachable = false
    ollama.models = []
    modelsError.value = error.message
    throw error
  } finally {
    loadingModels.value = false
  }
}

export async function applyLlmModel(
  model = selectedLlm.value,
  provider = selectedProvider.value,
  systemPrompt = selectedSystemPrompt.value,
  responseMaxChars = selectedResponseMaxChars.value,
  replyMode = selectedReplyMode.value,
  boardMaxItems = selectedBoardMaxItems.value
) {
  applyingLlm.value = true
  try {
    const endpoint = endpointForProvider(provider)
    const data = await parseJson(await fetch('/api/llm/model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        endpoint,
        system_prompt: systemPrompt,
        response_max_chars: Number(responseMaxChars),
        reply_mode: replyMode,
        board_max_items: Number(boardMaxItems),
        semantic_wait_seconds: Number(selectedSemanticWaitSeconds.value),
        assistant_profile: {
          assistant_name: selectedAssistantName.value,
          system_prompt: systemPrompt,
          restriction_prompt: selectedRestrictionPrompt.value,
          output_locale: selectedOutputLocale.value,
          enforce_output_locale: Boolean(selectedEnforceOutputLocale.value),
          forbidden_self_names: selectedForbiddenSelfNames.value.split('\n').map((value) => value.trim()).filter(Boolean)
        }
      })
    }))
    if (data.pending) return data
    runtime.llm.model = data.model
    runtime.llm.endpoint = data.endpoint || runtime.llm.endpoint
    runtime.llm.provider = data.provider || provider
    runtime.llm.base_url = data.base_url || runtime.llm.base_url
    runtime.llm.system_prompt = data.system_prompt || systemPrompt
    runtime.llm.assistant_profile = data.assistant_profile || runtime.llm.assistant_profile
    runtime.llm.response_max_chars = Number(data.response_max_chars || responseMaxChars)
    runtime.llm.board_max_items = Number(data.board_max_items || boardMaxItems)
    runtime.llm.reply_mode = data.reply_mode || replyMode
    runtime.llm.semantic_wait_seconds = Number(data.semantic_wait_seconds || selectedSemanticWaitSeconds.value)
    ollama.current = data.model
    selectedLlm.value = data.model
    selectedProvider.value = data.provider || provider
    selectedSystemPrompt.value = runtime.llm.system_prompt
    selectedRestrictionPrompt.value = runtime.llm.assistant_profile?.restriction_prompt || ''
    selectedAssistantName.value = runtime.llm.assistant_profile?.assistant_name || ''
    selectedOutputLocale.value = runtime.llm.assistant_profile?.output_locale || 'zh-TW'
    selectedEnforceOutputLocale.value = Boolean(runtime.llm.assistant_profile?.enforce_output_locale ?? true)
    selectedForbiddenSelfNames.value = (runtime.llm.assistant_profile?.forbidden_self_names || []).join('\n')
    selectedResponseMaxChars.value = runtime.llm.response_max_chars
    selectedBoardMaxItems.value = runtime.llm.board_max_items
    selectedReplyMode.value = runtime.llm.reply_mode
    selectedSemanticWaitSeconds.value = runtime.llm.semantic_wait_seconds
    return data
  } finally {
    applyingLlm.value = false
  }
}

export function selectProvider(id) {
  selectedProvider.value = id
  const models = id === 'llamacpp' ? llamacpp.models : ollama.models
  if (runtime.llm.provider === id && runtime.llm.model) {
    selectedLlm.value = runtime.llm.model
  } else if (models.length) {
    selectedLlm.value = models[0].name
  } else {
    selectedLlm.value = ''
  }
  const active = id === 'llamacpp' ? llamacpp : ollama
  modelsError.value = active.reachable ? '' : (active.error || '')
}
