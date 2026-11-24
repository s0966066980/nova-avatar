// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

import { useI18n } from '../composables/useI18n.js'
import { fmt } from './format.js'

// ``tx('home.title')`` reads settings.voiceTraining.home.title in the current
// locale; ``tf`` also fills {placeholders}.
export function useTrainingText() {
  const { t } = useI18n()
  const tx = key => t(`settings.voiceTraining.${key}`)
  const tf = (key, vars) => fmt(tx(key), vars)
  return { tx, tf }
}
