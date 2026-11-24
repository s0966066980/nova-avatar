// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Locale strings carry {name} placeholders (the console's translate function does not interpolate).
export function fmt(template, vars = {}) {
  return String(template).replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match))
}

// Whole minutes, at least 1 once there is any audio.
export const roundMinutes = seconds => (Number.isFinite(seconds) && seconds > 0 ? Math.max(1, Math.round(seconds / 60)) : 0)
