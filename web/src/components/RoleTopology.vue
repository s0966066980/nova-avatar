<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<!-- 交接路線：生效中的成員（含主數位人）兩兩相連；點節點選擇要編輯的那一位。 -->
<template>
  <svg class="rc-topo" viewBox="0 0 300 214" role="group" :aria-label="description">
    <line v-for="edge in lines" :key="edge.key" class="rc-edge" :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2" />
    <g v-for="node in placed" :key="node.key" :class="['rc-node', node.state, { sel: node.selected }]" tabindex="0" role="button"
      :aria-label="node.label" :aria-pressed="node.selected" @click="$emit('select', node.target)"
      @keydown.enter.prevent="$emit('select', node.target)" @keydown.space.prevent="$emit('select', node.target)">
      <circle class="rc-ring" :cx="node.x" :cy="node.y" :r="node.r + 4" />
      <circle class="rc-body" :cx="node.x" :cy="node.y" :r="node.r" :fill="node.state === 'live' ? node.color : undefined" />
      <text class="rc-ini" :x="node.x" :y="node.y" aria-hidden="true">{{ node.initial }}</text>
      <text :class="['rc-lbl', { dim: node.state !== 'live' }]" :x="node.lx" :y="node.ly" :text-anchor="node.anchor" aria-hidden="true">{{ node.name }}<tspan v-if="node.main" class="rc-tg" dx="5">開場／兜底</tspan></text>
    </g>
  </svg>
</template>

<script setup>
import { computed } from 'vue'
import { ringLayout } from '../roleComposition.js'

// nodes: [{ key, target (what selecting it opens), name, initial, color, state: live|off|bad|empty|new, selected, main }], first is the main avatar.
const props = defineProps({ nodes: { type: Array, required: true }, live: { type: Array, required: true }, description: { type: String, required: true } })
defineEmits(['select'])
const center = { cx: 150, cy: 112, r: 72 }
const placed = computed(() => {
  const ring = ringLayout(Math.max(props.nodes.length, 2), center)
  return props.nodes.map((node, index) => {
    const at = ring[index], r = node.main ? 20 : node.state === 'empty' ? 11 : 15
    const label = node.main
      ? { lx: at.x, ly: at.y - 31, anchor: 'middle' }
      : { lx: at.x + at.cos * 24, ly: at.y + at.sin * 24 + (at.sin > 0.5 ? 4 : 0), anchor: Math.abs(at.cos) < 0.3 ? 'middle' : at.cos > 0 ? 'start' : 'end' }
    const state = { live: '已啟用', off: '未啟用', bad: '不相容', new: '尚未儲存', empty: '' }[node.state]
    const spoken = node.state === 'empty' ? `${node.name}，加入專門數位人` : `編輯${node.name}${node.main ? '（主數位人，開場／兜底）' : `，${state}`}`
    return { ...node, ...label, x: +at.x.toFixed(1), y: +at.y.toFixed(1), r, label: spoken }
  })
})
const lines = computed(() => {
  const live = placed.value.filter(node => props.live.includes(node.key))
  const result = []
  for (let a = 0; a < live.length; a++) for (let b = a + 1; b < live.length; b++) {
    const [p, q] = [live[a], live[b]]
    const dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy)
    result.push({ key: `${p.key}-${q.key}`, x1: (p.x + dx / d * (p.r + 3)).toFixed(1), y1: (p.y + dy / d * (p.r + 3)).toFixed(1),
      x2: (q.x - dx / d * (q.r + 3)).toFixed(1), y2: (q.y - dy / d * (q.r + 3)).toFixed(1) })
  }
  return result
})
</script>
