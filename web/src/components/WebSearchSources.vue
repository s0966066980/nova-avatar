<!-- Copyright (c) 2026 HongXian0903; SPDX-License-Identifier: Apache-2.0 -->
<template>
  <section v-if="phase || result" class="web-search-sources" :aria-label="tr('網頁搜尋', 'Web search')">
    <p v-if="phase" role="status" aria-live="polite">{{ phase === 'search_planning' ? tr('正在判斷是否需要搜尋…', 'Checking whether search is needed…') : phase === 'summarizing' ? tr('正在整理資料…', 'Organizing sources…') : tr('正在搜尋資料…', 'Searching the web…') }}</p>
    <template v-if="result">
      <p role="status">{{ statusText }}<span v-if="result.reused"> · {{ tr('沿用五分鐘內的資料', 'Using sources from the last five minutes') }}</span></p>
      <details v-if="result.sources?.length" :key="result.turn_id">
        <summary>{{ tr('網頁來源', 'Web sources') }} · {{ result.sources.length }}</summary>
        <p v-if="result.fetched_at"><small>{{ tr('查詢時間', 'Retrieved') }}: {{ result.fetched_at }}</small></p>
        <ol>
          <li v-for="source in result.sources" :key="source.id">
            <a v-if="safeWebLink(source.url)" :href="safeWebLink(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }}</a>
            <span v-else>{{ source.title }}</span>
            <small> · {{ source.kind === 'page' ? tr('已讀取網頁', 'Page read') : tr('搜尋摘要，未核對全文', 'Search snippet; full page not checked') }}</small>
            <p>{{ source.snippet }}</p>
          </li>
        </ol>
      </details>
    </template>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { safeWebLink } from '../webSearchState.js'
const props = defineProps({ result: { type: Object, default: null }, phase: { type: String, default: '' }, locale: { type: String, default: 'zh-TW' } })
const tr = (zh, en) => props.locale === 'en-US' ? en : zh
const statusText = computed(() => {
  if (props.result?.status === 'available') return tr('已取得網頁參考資料', 'Web references retrieved')
  if (props.result?.status === 'partial') return tr('部分網頁已讀取，其餘未能完成', 'Some pages were read; others could not be completed')
  if (props.result?.status === 'snippets') return tr('只有搜尋摘要，未能核對網頁全文', 'Only search snippets available; full pages not checked')
  return tr('本輪未能取得可用網路資料，最新資訊尚未查證', 'No usable web sources this turn; current information is unverified')
})
</script>
<style scoped>
.web-search-sources { font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.web-search-sources p { margin: .4em 0; }
.web-search-sources summary { cursor: pointer; min-height: 44px; display: list-item; align-content: center; }
.web-search-sources a { display: block; min-height: 44px; align-content: center; color: inherit; text-decoration: underline; }
.web-search-sources a:focus-visible, .web-search-sources summary:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
.web-search-sources ol { padding-left: 1.6em; }
.web-search-sources small { opacity: .85; }
</style>
