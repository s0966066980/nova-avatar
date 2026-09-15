import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const panel = readFileSync(
  new URL('../src/components/SettingsPanel.vue', import.meta.url),
  'utf8'
)
const settings = readFileSync(
  new URL('../src/composables/useRuntimeSettings.js', import.meta.url),
  'utf8'
)
const app = readFileSync(
  new URL('../src/App.vue', import.meta.url),
  'utf8'
)
const standaloneStage = readFileSync(
  new URL('../stage.html', import.meta.url),
  'utf8'
)
const consoleCss = readFileSync(
  new URL('../src/console-prototype.css', import.meta.url),
  'utf8'
)

test('設定面板提供有標籤與說明的預設 Prompt 欄位', () => {
  assert.match(panel, /for="llm-system-prompt"/)
  assert.match(panel, /<textarea[\s\S]*id="llm-system-prompt"/)
  assert.match(panel, /aria-describedby="llm-system-prompt-hint llm-system-prompt-count"/)
  assert.match(panel, /maxlength="8000"/)
})

test('套用 LLM 設定時會送出並同步預設 Prompt', () => {
  assert.match(settings, /system_prompt:\s*systemPrompt/)
  assert.match(settings, /runtime\.llm\.system_prompt\s*=\s*data\.system_prompt/)
})

test('設定面板提供可存取且有範圍限制的約略回覆字數欄位', () => {
  assert.match(panel, /for="llm-response-max-chars"/)
  assert.match(panel, /id="llm-response-max-chars"[\s\S]*type="number"/)
  assert.match(panel, /min="20"/)
  assert.match(panel, /max="2000"/)
  assert.match(panel, /aria-describedby="llm-response-max-chars-hint llm-response-max-chars-meta"/)
})

test('設定面板可調整看板項目上限並說明系統固定規則', () => {
  assert.match(panel, /for="llm-board-max-items"/)
  assert.match(panel, /id="llm-board-max-items"[\s\S]*type="number"/)
  assert.match(panel, /min="1"/)
  assert.match(panel, /max="12"/)
  assert.match(panel, /系統固定規則/)
  assert.match(panel, /JSON 不會送入語音/)
  assert.match(settings, /board_max_items:\s*Number\(boardMaxItems\)/)
  assert.match(settings, /runtime\.llm\.board_max_items\s*=\s*Number/)
})

test('設定面板可調整嘴型銳化、貼回插值與 MuseTalk 製作參數', () => {
  assert.match(panel, /for="mouth-sharpen"/)
  assert.match(panel, /id="mouth-sharpen"[\s\S]*type="range"/)
  assert.match(panel, /for="paste-interpolation"/)
  assert.match(panel, /for="bbox-shift"/)
  assert.match(panel, /for="extra-margin"/)
  assert.match(panel, /settings\.quality\.rebuildHint/)
  assert.match(settings, /\/api\/avatar\/quality/)
  assert.match(settings, /form\.append\('quality'/)
})

test('CosyVoice 設定提供合成語言與額外指令', () => {
  assert.match(panel, /isCosyVoiceFamily/)
  assert.match(panel, /fun-cosyvoice3/)
  assert.match(panel, /settings\.speech\.cosyvoiceLanguage/)
  assert.match(panel, /settings\.speech\.cosyvoiceInstruct/)
  assert.match(panel, /settings\.speech\.cosyvoiceModel/)
  assert.match(settings, /ttsDraft\.language = 'zh'/)
  assert.match(settings, /type === 'fun-cosyvoice3'/)
})

test('Zero-shot 顯示並檢核參考語音逐字稿', () => {
  assert.match(panel, /參考語音逐字稿/)
  assert.match(panel, /ttsDraft\.ref_text/)
  assert.match(settings, /Zero-shot 需要填寫「參考語音逐字稿」/)
})

test('從 Edge 切到本機 TTS 時會清掉聲線名稱並要求音訊路徑', () => {
  assert.match(settings, /EDGE_VOICE_ID/)
  assert.match(settings, /previous === 'edgetts'/)
  assert.match(panel, /settings\.speech\.referencePathDesc/)
  assert.match(panel, /settings\.speech\.referencePathPlaceholder/)
})

test('套用舞台設定時會送出看板視窗樣式', () => {
  assert.match(settings, /board_style:\s*selectedBoardStyle\.value/)
  assert.match(settings, /board_preview:\s*Boolean\(selectedBoardPreview\.value\)/)
  assert.match(settings, /mic_x:\s*Number\(selectedMicX\.value\)/)
  assert.match(panel, /selectedBoardStyle = style\.id/)
})

test('舞台預覽共用看板、麥克風與展開看板按鈕的位置，控制台右側不重複顯示麥克風', () => {
  assert.match(app, /:style="consoleBoardStyle"/)
  assert.match(app, /:style="consoleBoardOpenPresentation\.style"/)
  assert.doesNotMatch(app, /class="stage-mic-control"/)
  assert.doesNotMatch(app, /const consoleMicStyle/)
  assert.match(panel, /:style="stagePreviewBoardStyle"/)
  assert.match(panel, /:style="stagePreviewMicStyle"/)
  assert.match(panel, /:style="stagePreviewBoardOpenPresentation\.style"/)
  assert.match(panel, /startStageDirectEdit\('board-open'/)
  assert.match(settings, /board_open_x:\s*Number\(selectedBoardOpenX\.value\)/)
  assert.match(settings, /board_open_y:\s*Number\(selectedBoardOpenY\.value\)/)
})

test('舞台預覽麥克風尺寸與 stage.html 一致', () => {
  assert.match(consoleCss, /\.stage-preview-mic\s*\{[\s\S]*?width:\s*104px;[\s\S]*?height:\s*104px;/)
  assert.match(consoleCss, /\.stage-preview-ring\s*\{[\s\S]*?inset:\s*-14px;/)
  assert.match(standaloneStage, /\.mic\{[\s\S]*?width:\s*104px;\s*height:\s*104px;/)
})

test('展開看板按鈕在預覽與 stage.html 都會依左右邊緣切換圖示', () => {
  assert.match(app, /consoleBoardOpenPresentation\.icon/)
  assert.match(panel, /stagePreviewBoardOpenPresentation\.icon/)
  assert.match(panel, /stagePreviewBoardOpenPresentation\.style/)
  assert.match(standaloneStage, /boardOpenPresentation/)
  assert.match(standaloneStage, /boardReopenIcon\.textContent/)
})

test('展開看板按鈕在各舞台位置都維持單行且不被壓縮', () => {
  assert.match(consoleCss, /\.board-open-pill\s*\{[\s\S]*?display:\s*inline-flex;[\s\S]*?flex:\s*0 0 auto;[\s\S]*?white-space:\s*nowrap;/)
  assert.match(consoleCss, /\.stage-preview-board-open\s*\{[\s\S]*?display:\s*inline-flex;[\s\S]*?flex:\s*0 0 auto;[\s\S]*?white-space:\s*nowrap;/)
  assert.match(standaloneStage, /\.board-reopen\s*\{[\s\S]*?display:inline-flex;[\s\S]*?flex:0 0 auto;[\s\S]*?white-space:nowrap;/)
})

test('展開看板按鈕可在開啟與關閉間切換，並宣告目前狀態', () => {
  assert.match(app, /v-if="visibleBoard\.items\.length"/)
  assert.match(app, /:aria-pressed="!stageBoard\.hidden"/)
  assert.match(app, /@click="stageBoard\.hidden = !stageBoard\.hidden"/)
  assert.match(app, /stageBoard\.hidden \? '展開看板' : '收合看板'/)
  assert.match(standaloneStage, /boardReopen\.hidden=!hasItems/)
  assert.match(standaloneStage, /boardReopen\.setAttribute\('aria-pressed', String\(!liveBoard\.hidden\)\)/)
  assert.match(standaloneStage, /liveBoard\.hidden=!liveBoard\.hidden; applyBoardLayout\(\);/)
})

test('即時字幕帶可用滑桿或直接拖曳調整展示區域並持久化', () => {
  assert.match(panel, /id="stage-caption-x"/)
  assert.match(panel, /id="stage-caption-y"/)
  assert.match(panel, /id="stage-caption-width"/)
  assert.match(panel, /startStageDirectEdit\('caption'/)
  assert.match(panel, /target === 'caption'/)
  assert.match(settings, /caption_x:\s*Number\(selectedCaptionX\.value\)/)
  assert.match(settings, /caption_y:\s*Number\(selectedCaptionY\.value\)/)
  assert.match(settings, /caption_width:\s*Number\(selectedCaptionWidth\.value\)/)
  assert.match(standaloneStage, /data\.caption_x/)
  assert.match(standaloneStage, /data\.caption_y/)
  assert.match(standaloneStage, /data\.caption_width/)
})

test('舞台直接編輯提供拖曳與滑桿兩種調整方式', () => {
  assert.match(panel, /拖曳調整看板位置/)
  assert.match(panel, /拖曳調整展開看板按鈕位置/)
  assert.match(panel, /id="stage-board-open-x"/)
  assert.match(panel, /id="stage-board-open-y"/)
  assert.match(panel, /target === 'board-open'/)
  assert.match(panel, /await applyStageSettings\(\)/)
})

test('所見即所得預覽以獨立 stage.html 的舞台結構呈現', () => {
  assert.match(panel, /class="interactive-large-stage stage-direct-editor standalone-stage-preview"/)
  assert.match(panel, /class="stage-preview-mode"/)
  assert.match(panel, /class="stage-preview-mic-wrap"/)
  assert.match(panel, /class="stage-preview-captions"/)
  assert.match(panel, /class="mini-board-rect stage-preview-float-board"/)
  assert.match(panel, /stagePreviewSize/)
  assert.match(panel, /STAGE_CAPTION_RATIO/)
  assert.match(panel, /previewScale\(stageWidth, stageHeight\)/)
  assert.match(panel, /width: `\$\{box\.width\}px`/)
  assert.match(standaloneStage, /class="stage" id="stage"/)
  assert.match(standaloneStage, /class="mic-wrap" id="micWrap"/)
  assert.match(standaloneStage, /class="float-board" id="board"/)
  assert.match(standaloneStage, /previewScale\(stage\.clientWidth, stage\.clientHeight\)/)
})

test('獨立 stage.html 套用展開看板按鈕位置', () => {
  assert.match(standaloneStage, /boardOpenLayout=\{x:50, y:8\}/)
  assert.match(standaloneStage, /data\.board_open_x/)
  assert.match(standaloneStage, /data\.board_open_y/)
  assert.match(standaloneStage, /boardReopenPresentation\(boardOpenLayout\.x, boardOpenLayout\.y\)/)
  assert.match(standaloneStage, /Object\.assign\(boardReopen\.style, boardOpenPresentation\.style\)/)
})

test('套用 LLM 設定時會送出並同步回覆字數', () => {
  assert.match(settings, /response_max_chars:\s*Number\(responseMaxChars\)/)
  assert.match(settings, /runtime\.llm\.response_max_chars\s*=\s*Number/)
  assert.match(settings, /value < 20 \|\| value > 2000/)
})

test('設定面板可選擇舊有或串流回覆模式並持久化', () => {
  assert.match(panel, /for="llm-reply-mode"/)
  assert.match(panel, /id="llm-reply-mode"[\s\S]*value="legacy"[\s\S]*value="streaming"/)
  assert.match(settings, /reply_mode:\s*replyMode/)
  assert.match(settings, /runtime\.llm\.reply_mode\s*=\s*data\.reply_mode/)
})

test('設定面板提供三區可編輯 Rule 並使用版本套用 API', () => {
  assert.match(panel, /key: 'activation'/)
  assert.match(panel, /key: 'speech'/)
  assert.match(panel, /key: 'board'/)
  assert.match(panel, /儲存並套用/)
  assert.match(settings, /fetch\('\/api\/llm\/rules'/)
  assert.match(settings, /expected_revision:/)
  assert.match(settings, /restoreDefaultRules/)
})

test('新版設定中心沿用實際 Rule 欄位並顯示載入與角色空狀態', () => {
  assert.match(panel, /v-model="rulesDraft\[rule\.key\]"/)
  assert.match(panel, /handleApplyPromptAndRules/)
  assert.match(panel, /await applyLlmModel\(\)[\s\S]*await applyReplyRules\(\)/)
  assert.match(panel, /v-if="loadingSettings"[\s\S]*載入/)
  assert.match(panel, /v-else-if="settingsError"[\s\S]*role="alert"/)
  assert.match(panel, /v-else-if="!filteredCharacters\.length && !loadingSettings"/)
})

test('語音設定保留目前 STT 引擎與 Edge-TTS 音色', () => {
  assert.match(panel, /v-for="engine in sttEngineOptions"/)
  assert.match(panel, /v-model="ttsDraft\.ref_file"/)
  assert.match(panel, /v-for="voice in edgeVoiceOptions"/)
  assert.match(settings, /ref_file: data\.tts\.ref_file \|\| ''/)
  assert.match(settings, /const sttEngineOptions = computed/)
})

test('舞台設定保留麥克風定位並以真實數位人預覽 9:16 對照畫面', () => {
  assert.match(panel, /id="stage-mic-x"[\s\S]*type="range"/)
  assert.match(panel, /id="stage-mic-y"[\s\S]*type="range"/)
  assert.match(panel, /@click="selectMicPreset\(preset\.id\)"/)
  assert.match(panel, /@input="markMicPositionCustom"/)
  assert.match(panel, /class="stage-preview-avatar"/)
  assert.match(panel, /class="stage-preview-mic"/)
  assert.match(panel, /placeStageBoard/)
})

test('放大的 9:16 舞台可直接拖曳看板與麥克風並保存位置', () => {
  assert.match(panel, /class="interactive-large-stage stage-direct-editor standalone-stage-preview"/)
  assert.match(panel, /@pointerdown\.stop\.prevent="startStageDirectEdit\('board', \$event\)"/)
  assert.match(panel, /@pointerdown\.stop\.prevent="startStageDirectEdit\('mic', \$event\)"/)
  assert.match(panel, /const moveStageDirectEdit = \(event\)/)
  assert.match(panel, /await applyStageSettings\(\)/)
  assert.match(panel, /舞台位置已套用/)
})

test('全域儲存會處理 Prompt、Rule，且 Prompt 編輯器有足夠高度', () => {
  assert.match(panel, /rows="8"/)
  assert.match(panel, /const promptDirty = computed/)
  assert.match(panel, /if \(llmDirty\.value \|\| promptDirty\.value\) promises\.push\(applyLlmModel\(\)\)/)
  assert.doesNotMatch(panel, /\{ key: 'speech'[\s\S]*\{ key: 'speech'/)
})

test('主題選擇會將執行中的 dark 或 white 狀態對應至可見樣式', () => {
  assert.match(panel, /const normalizeThemeValue = \(theme\)/)
  assert.match(panel, /normalizeThemeValue\(props\.currentTheme\)/)
  assert.match(panel, /@click="selectTheme\(theme\.id\)"/)
})

test('主題只保留卡片選擇，並持久化 Prompt 與 Rule 編輯器高度', () => {
  assert.doesNotMatch(panel, /themeSelectDropdown/)
  assert.match(panel, /const EDITOR_HEIGHT_STORAGE_KEY/)
  assert.match(panel, /const rememberEditorHeight = \(event\)/)
  assert.match(panel, /@pointerup="rememberEditorHeight"/)
  assert.match(panel, /localStorage\.setItem\(EDITOR_HEIGHT_STORAGE_KEY/)
  assert.match(panel, /:style="\{ height: `\$\{editorHeights\.prompt\}px` \}"/)
  assert.match(panel, /:style="\{ height: `\$\{editorHeights\[rule\.key\]\}px` \}"/)
})

test('控制台空狀態不以固定示範對話與看板冒充即時資料', () => {
  assert.doesNotMatch(app, /return \{\s*title:\s*'核心優勢看板',[\s\S]*全雙工打斷機制/)
  assert.doesNotMatch(app, /chatMessages = ref\(\[[\s\S]*boardItems:/)
  assert.match(app, /return \{ title: '', items: \[\], preview: false \}/)
})

test('正式控制台不顯示原型展示列、假延遲，且可預覽目前數位人', () => {
  assert.doesNotMatch(app, /UI\/UX 滿板架構重構/)
  assert.doesNotMatch(app, /42ms/)
  assert.match(app, /const currentAvatar = computed/)
  assert.match(app, /class="stage-avatar-preview"/)
  assert.match(app, /currentAvatar\.preview_url \|\| currentAvatar\.thumbnail/)
  assert.match(panel, /char\.preview_url \|\| char\.thumbnail/)
})

test('文字回覆由事件模式呈現而非 HTTP 完整 response', () => {
  assert.match(app, /assistant_response/)
  assert.match(app, /assistant_fragment/)
  assert.match(app, /assistant_response_delta/)
  assert.match(app, /streamingPreview/)
  assert.doesNotMatch(app, /if \(data\.response \|\| data\.text\) \{[\s\S]*addMessage\(data\.response/)
})

test('文字 delta 拒絕重複、逆序與完成後的舊事件', () => {
  assert.match(app, /assistantStreamState = new Map\(\)/)
  assert.match(app, /sequence <= stream\.lastSequence \|\| stream\.done/)
  assert.match(app, /stream\.done = true/)
})

test('輪次提交後控制台對齊已播回覆', () => {
  assert.match(app, /applyTurnCommitted/)
  assert.match(app, /event\.type === 'turn_committed'/)
  assert.match(app, /tts_error_before_commit/)
  assert.match(app, /tts_error_after_commit/)
})
