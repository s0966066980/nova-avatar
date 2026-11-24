// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Names used by the training screens, mapped to the console's Bootstrap Icons.
const ICONS = {
  'check-circle': 'bi-check-circle-fill',
  'x-circle': 'bi-x-circle-fill',
  alert: 'bi-exclamation-triangle-fill',
  info: 'bi-info-circle-fill',
  play: 'bi-play-fill',
  pause: 'bi-pause-fill',
  stop: 'bi-stop-fill',
  upload: 'bi-upload',
  mic: 'bi-mic-fill',
  cpu: 'bi-cpu-fill',
  ban: 'bi-slash-circle',
  pencil: 'bi-pencil-fill',
  refresh: 'bi-arrow-clockwise',
  spin: 'bi-arrow-repeat vt-spin',
  dot: 'bi-circle',
  lock: 'bi-lock-fill',
  file: 'bi-file-earmark-text-fill',
  wave: 'bi-soundwave',
  check: 'bi-check-lg',
  next: 'bi-chevron-right',
  prev: 'bi-chevron-left',
  copy: 'bi-clipboard'
}

export const icon = name => `bi ${ICONS[name] || ICONS.dot}`
