// Copyright (c) 2026 HongXian0903
// SPDX-License-Identifier: Apache-2.0

// Give the audio receiver room for short scheduling/network jitter. Video
// keeps its adaptive buffer and the browser still owns A/V synchronization.
export function configureReplyPlayout(event) {
  if (event.track?.kind !== 'audio' || !event.receiver || !('jitterBufferTarget' in event.receiver)) return
  try {
    event.receiver.jitterBufferTarget = 160
  } catch {
    // Unsupported setters retain the browser's adaptive playback defaults.
  }
}
