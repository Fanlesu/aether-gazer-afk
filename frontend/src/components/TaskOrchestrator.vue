<template>
  <div class="orch">
    <div class="orch-bar">
      <span class="orch-title">任务编排</span>
      <span class="orch-sub">调整执行顺序，并为每步设置 超时 / 重试 / 前后等待 / 执行条件 / 失败策略</span>
    </div>

    <div class="orch-list">
      <div
        v-for="(task, idx) in editTasks"
        :key="task.id"
        class="orch-row"
        :class="{ 'is-disabled': !task.enabled }"
      >
        <!-- Order control -->
        <div class="orch-move">
          <button
            class="orch-move-btn"
            :disabled="idx === 0"
            title="上移"
            @click="moveUp(idx)"
          >▲</button>
          <span class="orch-pos">{{ idx + 1 }}</span>
          <button
            class="orch-move-btn"
            :disabled="idx === editTasks.length - 1"
            title="下移"
            @click="moveDown(idx)"
          >▼</button>
        </div>

        <!-- Enable checkbox (all tasks freely toggleable) -->
        <div
          class="task-check"
          :class="{ checked: task.enabled }"
          :title="task.safe ? '基础任务：不消耗游戏资源，可自由开关' : '启用 / 禁用'"
          @click="toggleEnabled(task)"
        ></div>

        <span class="orch-icon">{{ taskIcon(task.id) }}</span>

        <div class="orch-body">
          <div class="orch-name-row">
            <span class="orch-name" :class="{ unsafe: task.safe }">{{ task.name }}</span>
            <span v-if="task.safe" class="orch-lock" title="基础任务：不消耗游戏资源">基础</span>
            <span v-if="isCustom(task)" class="orch-custom-badge">自定义</span>
          </div>

          <!-- Built-in tasks: L1 tuning knobs -->
          <div v-if="!isCustom(task)" class="orch-params">
            <label class="orch-field">
              <span>超时(秒)</span>
              <input
                type="number" min="0" step="1"
                v-model="task.params.timeout"
                placeholder="∞"
              >
            </label>
            <label class="orch-field">
              <span>重试</span>
              <input
                type="number" min="0" step="1"
                v-model.number="task.params.retry"
              >
            </label>
            <label class="orch-field">
              <span>前等待(秒)</span>
              <input
                type="number" min="0" step="0.5"
                v-model.number="task.params.wait_before"
              >
            </label>
            <label class="orch-field">
              <span>后等待(秒)</span>
              <input
                type="number" min="0" step="0.5"
                v-model.number="task.params.wait_after"
              >
            </label>
          </div>

          <!-- Custom steps (L3): visual atomic-action editor -->
          <template v-else>
            <label class="orch-field orch-name-edit">
              <span>名称</span>
              <input v-model="task.name" placeholder="自定义步骤名" spellcheck="false">
            </label>
            <div class="orch-actions-editor">
              <div
                v-for="(act, ai) in task.actions"
                :key="ai"
                class="orch-action-row"
              >
                <div class="orch-action-move">
                  <button class="orch-move-btn" :disabled="ai === 0" title="上移" @click="moveActionUp(task, ai)">▲</button>
                  <button class="orch-move-btn" :disabled="ai === task.actions.length - 1" title="下移" @click="moveActionDown(task, ai)">▼</button>
                </div>
                <select class="orch-select orch-action-type" v-model="act.type" @change="onActionTypeChange(task, ai)">
                  <option value="click">点击</option>
                  <option value="wait">等待</option>
                  <option value="swipe">滑动</option>
                  <option value="ocr_wait">OCR 等待</option>
                  <option value="reddot_wait">红点等待</option>
                </select>

                <template v-if="act.type === 'click'">
                  <label class="orch-af">x<input type="number" step="0.01" min="0" max="1" v-model.number="act.x"></label>
                  <label class="orch-af">y<input type="number" step="0.01" min="0" max="1" v-model.number="act.y"></label>
                </template>
                <template v-else-if="act.type === 'wait'">
                  <label class="orch-af">秒<input type="number" step="0.5" min="0" v-model.number="act.seconds"></label>
                </template>
                <template v-else-if="act.type === 'swipe'">
                  <label class="orch-af">x1<input type="number" step="0.01" min="0" max="1" v-model.number="act.x1"></label>
                  <label class="orch-af">y1<input type="number" step="0.01" min="0" max="1" v-model.number="act.y1"></label>
                  <label class="orch-af">x2<input type="number" step="0.01" min="0" max="1" v-model.number="act.x2"></label>
                  <label class="orch-af">y2<input type="number" step="0.01" min="0" max="1" v-model.number="act.y2"></label>
                  <label class="orch-af">ms<input type="number" step="50" min="0" v-model.number="act.duration"></label>
                </template>
                <template v-else-if="act.type === 'ocr_wait'">
                  <label class="orch-af orch-af-wide">文本<input v-model="act.text" placeholder="如 确认" spellcheck="false"></label>
                  <label class="orch-af">x<input type="number" step="0.01" min="0" max="1" v-model.number="act.region[0]"></label>
                  <label class="orch-af">y<input type="number" step="0.01" min="0" max="1" v-model.number="act.region[1]"></label>
                  <label class="orch-af">w<input type="number" step="0.01" min="0" max="1" v-model.number="act.region[2]"></label>
                  <label class="orch-af">h<input type="number" step="0.01" min="0" max="1" v-model.number="act.region[3]"></label>
                  <label class="orch-af">阈值<input type="number" step="0.05" min="0" max="1" v-model.number="act.threshold"></label>
                  <label class="orch-af">超时<input type="number" step="1" min="0" v-model.number="act.timeout"></label>
                </template>
                <template v-else-if="act.type === 'reddot_wait'">
                  <select class="orch-select orch-af" v-model="act.key">
                    <option v-for="k in RED_DOT_KEYS" :key="k" :value="k">{{ k }}</option>
                  </select>
                  <label class="orch-af">超时<input type="number" step="1" min="0" v-model.number="act.timeout"></label>
                </template>

                <button class="orch-action-del" title="删除动作" @click="removeAction(task, ai)">✕</button>
              </div>
              <button class="orch-btn-addact" @click="addAction(task)">+ 添加动作</button>
            </div>
          </template>

          <div class="orch-adv">
            <label class="orch-field">
              <span>失败策略</span>
              <select v-model="task.on_fail" class="orch-select">
                <option value="skip">跳过(默认)</option>
                <option value="abort">中止计划</option>
              </select>
            </label>
            <label class="orch-field orch-cond">
              <span>执行条件 (JSON, 可选)</span>
              <textarea
                v-model="task.condition"
                rows="2"
                spellcheck="false"
                placeholder='如 {"type":"reddot","key":"mail"}'
              ></textarea>
            </label>
          </div>
        </div>

        <!-- Live run status -->
        <div class="orch-status">
          <div v-if="liveStatus(task.id) === 'running'" class="orch-spinner"></div>
          <span class="orch-badge" :class="`badge-${liveStatus(task.id)}`">
            {{ statusText(liveStatus(task.id)) }}
          </span>
        </div>
      </div>

      <div v-if="editTasks.length === 0" class="orch-empty">暂无任务</div>
    </div>

    <div class="orch-actions">
      <button class="orch-btn-addstep" :disabled="saving" @click="addCustomStep">
        + 自定义步骤
      </button>
      <span v-if="dirty" class="orch-dirty">● 未保存的修改</span>
      <button class="orch-btn-reset" :disabled="!dirty || saving" @click="reset">
        重置
      </button>
      <button class="orch-btn-save" :disabled="!dirty || saving" @click="save">
        {{ saving ? '保存中…' : '保存计划' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { state, selectedPipeline, savePlan } from '../composables/useStore'

const saving = ref(false)

// Task ids for the daily routine, mapped to display icons (kept in sync
// with _DAILY_TASKS in processes/daily_routine.py).
const TASK_ICONS = {
  startup: '🚀',
  mail: '📬',
  intel_shards: '🛒',
  stamina_packs: '🔋',
  free_stamina: '🏪',
  mimi_station: '🔭',
  guild_supply: '🏰',
  amusement: '🎡',
  joint_special_ops: '🪖',
  joint_defense: '⚔️',
  medium_seizure: '💠',
  missions: '📋',
  tactics: '📝',
}

// Red-dot anchor keys (mirrors knowledge/red_dots.py RED_DOTS). Used only to
// populate the reddot_wait action dropdown; the backend remains the source of
// truth for the actual coordinates.
const RED_DOT_KEYS = [
  'mail', 'intel_shards_badge', 'free_stamina_supply', 'stamina_pack',
  'guild_supply_door', 'guild_task_entry', 'amusement_park_task',
  'hub_mission', 'daily_tab', 'weekly_tab', 'tactics', 'joint_defense_reward',
]

const STATUS_MAP = {
  pending: '等待',
  running: '运行中',
  success: '✓ 完成',
  failed: '✘ 失败',
  stopped: '■ 已停',
  skipped: '— 跳过',
}

function taskIcon(id) {
  return TASK_ICONS[id] || '📌'
}

function statusText(s) {
  return STATUS_MAP[s] || s
}

// --- Local edit buffer (order + enabled + params) -------------------------
// Cloned from the reactive store so edits are buffered until "保存计划".
function cloneTasks() {
  const p = selectedPipeline.value
  if (!p) return []
  return p.tasks.map(t => ({
    id: t.id,
    name: t.name,
    safe: t.safe,
    enabled: t.enabled,
    on_fail: t.on_fail || 'skip',
    // actions is a structured list (not JSON text) — deep-cloned so edits
    // stay buffered until save; null for built-in tasks.
    actions: t.actions ? JSON.parse(JSON.stringify(t.actions)) : null,
    // condition is edited as a JSON string in the textarea
    condition: t.condition ? JSON.stringify(t.condition, null, 2) : '',
    params: {
      timeout: t.params?.timeout ?? null,
      retry: t.params?.retry ?? 0,
      wait_before: t.params?.wait_before ?? 0,
      wait_after: t.params?.wait_after ?? 0,
    },
  }))
}

const editTasks = ref(cloneTasks())

// Live status is read straight from the store (not the clone), so a running
// routine updates the badge in real time even while edits are buffered.
const liveStatusMap = computed(() => {
  const p = selectedPipeline.value
  const m = {}
  if (p) for (const t of p.tasks) m[t.id] = t.status || 'pending'
  return m
})
function liveStatus(id) {
  return liveStatusMap.value[id] || 'pending'
}

// Re-sync the buffer when the store changes (e.g. after load/save), but only
// when there are no unsaved edits, to avoid clobbering in-progress input.
watch(
  () => selectedPipeline.value && selectedPipeline.value.tasks,
  () => { if (!dirty.value) editTasks.value = cloneTasks() },
  { deep: true },
)

const dirty = computed(() => {
  const p = selectedPipeline.value
  if (!p) return false
  const cur = p.tasks
  if (cur.length !== editTasks.value.length) return true
  for (let i = 0; i < cur.length; i++) {
    const a = cur[i]
    const b = editTasks.value[i]
    if (a.id !== b.id) return true
    if (a.enabled !== b.enabled) return true
    if ((a.on_fail || 'skip') !== (b.on_fail || 'skip')) return true
    // compare condition by canonical JSON (pretty textarea === compact store)
    if (normCondition(a.condition) !== normCondition(b.condition)) return true
    // L3: compare the custom action sequence by canonical JSON
    if (JSON.stringify(a.actions ?? null) !== JSON.stringify(b.actions ?? null)) {
      return true
    }
    if ((a.name ?? '') !== (b.name ?? '')) return true
    const ap = a.params || {}
    const bp = b.params
    if ((ap.timeout ?? null) !== (bp.timeout ?? null)) return true
    if ((ap.retry ?? 0) !== (bp.retry ?? 0)) return true
    if ((ap.wait_before ?? 0) !== (bp.wait_before ?? 0)) return true
    if ((ap.wait_after ?? 0) !== (bp.wait_after ?? 0)) return true
  }
  return false
})

function moveUp(i) { if (i > 0) swap(i, i - 1) }
function moveDown(i) { if (i < editTasks.value.length - 1) swap(i, i + 1) }
function swap(i, j) {
  const arr = editTasks.value
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
}

function toggleEnabled(task) {
  task.enabled = !task.enabled
}

function isCustom(task) {
  return !!(task.actions)
}

// --- L3 custom atomic-step editor ------------------------------------

// Default action template when switching type or adding a new action.
function defaultActionFor(type) {
  switch (type) {
    case 'click': return { type: 'click', x: 0.5, y: 0.5 }
    case 'wait': return { type: 'wait', seconds: 1 }
    case 'swipe': return { type: 'swipe', x1: 0.2, y1: 0.8, x2: 0.2, y2: 0.2, duration: 500 }
    case 'ocr_wait': return { type: 'ocr_wait', text: '', region: [0, 0, 0, 0], threshold: 0.5, timeout: 10 }
    case 'reddot_wait': return { type: 'reddot_wait', key: 'mail', timeout: 10 }
    default: return { type: 'click', x: 0.5, y: 0.5 }
  }
}

function addCustomStep() {
  editTasks.value.push({
    id: `custom_${Date.now()}`,
    name: '自定义步骤',
    safe: false,
    enabled: true,
    on_fail: 'skip',
    condition: '',
    actions: [defaultActionFor('click')],
    params: { timeout: null, retry: 0, wait_before: 0, wait_after: 0 },
  })
}

function addAction(task) {
  task.actions.push(defaultActionFor('click'))
}

function removeAction(task, i) {
  task.actions.splice(i, 1)
}

function moveActionUp(task, i) { if (i > 0) actionSwap(task, i, i - 1) }
function moveActionDown(task, i) {
  if (i < task.actions.length - 1) actionSwap(task, i, i + 1)
}
function actionSwap(task, i, j) {
  const arr = task.actions
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
}

// Switching the type resets the action to that type's default fields, so the
// editor never shows stale parameters from the previous type.
function onActionTypeChange(task, i) {
  task.actions[i] = defaultActionFor(task.actions[i].type)
}

// Coerce inputs into the backend contract: timeout is number|null, the rest
// are non-negative numbers. Empty strings from the inputs become 0/null.
// Canonical-form a condition for dirty comparison. The store holds a dict
// (compact JSON), the textarea holds user-edited text (often pretty-printed).
// Both are normalized to compact JSON so formatting differences don't flag a
// spurious "unsaved" state. Invalid JSON falls through as its raw text — which
// is genuinely dirty and will be caught at save time.
function normCondition(c) {
  if (!c) return ''
  if (typeof c === 'string') {
    const s = c.trim()
    if (!s) return ''
    try {
      return JSON.stringify(JSON.parse(s))
    } catch {
      return s
    }
  }
  return JSON.stringify(c)
}

function normalizeParams(p) {
  const rawTimeout = p.timeout
  const timeout = (
    rawTimeout === '' || rawTimeout === null || rawTimeout === undefined
  ) ? null : Number(rawTimeout)
  return {
    timeout,
    retry: Math.max(0, Math.floor(Number(p.retry) || 0)),
    wait_before: Math.max(0, Number(p.wait_before) || 0),
    wait_after: Math.max(0, Number(p.wait_after) || 0),
  }
}

async function save() {
  const p = selectedPipeline.value
  if (!p) return
  saving.value = true
  try {
    const payload = editTasks.value.map(t => {
      // condition is edited as JSON text; parse it back to a dict here so the
      // backend contract stays clean (dict | null). Abort the whole save if
      // any task's JSON is malformed — partial saves would be confusing.
      let condition = null
      const raw = (t.condition || '').trim()
      if (raw) {
        try {
          const parsed = JSON.parse(raw)
          condition = parsed && typeof parsed === 'object' ? parsed : null
        } catch (e) {
          alert(`任务「${t.name}」的执行条件不是合法 JSON：${e.message}`)
          throw e
        }
      }
      return {
        id: t.id,
        enabled: t.enabled,
        name: t.name,
        on_fail: t.on_fail || 'skip',
        condition,
        // actions is a structured list (null for built-in tasks)
        actions: t.actions ? t.actions : null,
        params: normalizeParams(t.params),
      }
    })
    const result = await savePlan(p.id, payload)
    if (!result || !result.ok) {
      alert(result?.error || '保存失败')
    } else {
      editTasks.value = cloneTasks()
    }
  } finally {
    saving.value = false
  }
}

function reset() {
  editTasks.value = cloneTasks()
}
</script>

<style scoped>
.orch {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.orch-bar {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 4px 20px 8px;
}

.orch-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.orch-sub {
  font-size: 11px;
  color: var(--text-muted);
}

.orch-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 20px 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.orch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
}

.orch-row.is-disabled {
  opacity: 0.55;
}

.orch-move {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  flex-shrink: 0;
}

.orch-move-btn {
  width: 22px;
  height: 16px;
  line-height: 1;
  padding: 0;
  font-size: 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--chip-inactive-border);
  background: var(--chip-inactive-bg);
  color: var(--chip-inactive-text);
  cursor: pointer;
}

.orch-move-btn:hover:not(:disabled) {
  border-color: var(--accent-primary);
  color: var(--text-primary);
}

.orch-move-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.orch-pos {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.orch-icon {
  font-size: 18px;
  width: 24px;
  text-align: center;
  flex-shrink: 0;
}

.orch-body {
  flex: 1;
  min-width: 0;
}

.orch-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.orch-name {
  font-size: 13px;
  color: var(--text-secondary);
}

.orch-name.unsafe {
  color: var(--status-warning-text);
}

.orch-lock {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--accent-tint);
  color: var(--accent-text);
  border: 1px solid var(--accent-border-strong);
  flex-shrink: 0;
}

.orch-params {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 5px;
}

.orch-field {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-muted);
}

.orch-field input {
  width: 58px;
  padding: 3px 6px;
  text-align: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.orch-field input:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.orch-adv {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 8px 14px;
  margin-top: 6px;
}

.orch-select {
  padding: 3px 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 12px;
}

.orch-select:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.orch-cond {
  align-items: stretch;
  flex: 1;
  min-width: 220px;
}

.orch-cond textarea {
  flex: 1;
  width: 100%;
  min-height: 40px;
  padding: 4px 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 11px;
  font-family: var(--font-mono, monospace);
  resize: vertical;
  line-height: 1.4;
}

.orch-cond textarea:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.orch-status {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.orch-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-weight: 500;
  min-width: 48px;
  text-align: center;
}

.badge-pending { color: var(--border-hover); }
.badge-running { background: var(--status-running-bg); color: var(--status-running); }
.badge-success { background: var(--status-success-bg); color: var(--status-success-text); }
.badge-failed { background: var(--status-error-bg); color: var(--status-error-text); }
.badge-stopped { background: var(--status-warning-bg); color: var(--status-warning-text); }
.badge-skipped { color: var(--checkbox-border); }

.orch-spinner {
  width: 13px;
  height: 13px;
  border: 2px solid var(--accent-border);
  border-top-color: var(--accent-1);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.orch-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-muted);
}

.orch-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 10px 20px;
  border-top: 1px solid var(--border-subtle);
}

.orch-dirty {
  margin-right: auto;
  font-size: 11px;
  color: var(--status-warning-text);
}

.orch-btn-reset,
.orch-btn-save {
  padding: 6px 16px;
  border-radius: var(--radius-md);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.orch-btn-reset {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
}

.orch-btn-reset:hover:not(:disabled) {
  color: var(--text-primary);
  border-color: var(--border-hover);
}

.orch-btn-save {
  background: var(--accent-1);
  border: 1px solid var(--accent-1);
  color: var(--text-on-accent);
  font-weight: 600;
}

.orch-btn-save:hover:not(:disabled) {
  filter: brightness(1.08);
}

.orch-btn-reset:disabled,
.orch-btn-save:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Custom checkbox (mirrors TaskList) */
.task-check {
  width: 18px;
  height: 18px;
  border: 2px solid var(--checkbox-border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.task-check.checked {
  background: var(--accent-1);
  border-color: var(--accent-1);
}

.task-check.checked::after {
  content: '✓';
  color: var(--text-on-accent);
  font-size: 11px;
  font-weight: 700;
}

/* L3 custom-step editor */
.orch-custom-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  background: var(--accent-tint);
  color: var(--accent-text);
  border: 1px solid var(--accent-border-strong);
}

.orch-name-edit {
  margin-top: 5px;
}

.orch-name-edit input {
  width: 150px;
  padding: 3px 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 12px;
}

.orch-name-edit input:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.orch-actions-editor {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 8px;
  border: 1px dashed var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--bg-canvas, var(--bg-surface));
}

.orch-action-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 8px;
}

.orch-action-move {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.orch-action-type {
  min-width: 92px;
}

.orch-af {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  color: var(--text-muted);
}

.orch-af input {
  width: 46px;
  padding: 2px 4px;
  text-align: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.orch-af input:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.orch-af-wide input {
  width: 92px;
}

.orch-action-del {
  width: 20px;
  height: 20px;
  line-height: 1;
  padding: 0;
  font-size: 11px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--chip-inactive-border);
  background: var(--chip-inactive-bg);
  color: var(--status-error-text);
  cursor: pointer;
}

.orch-action-del:hover {
  border-color: var(--status-error-text);
}

.orch-btn-addact {
  align-self: flex-start;
  padding: 3px 12px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  cursor: pointer;
  background: var(--bg-surface);
  border: 1px solid var(--accent-border);
  color: var(--accent-text);
  transition: all 0.15s ease;
}

.orch-btn-addact:hover {
  border-color: var(--accent-primary);
}

.orch-btn-addstep {
  padding: 6px 14px;
  border-radius: var(--radius-md);
  font-size: 12px;
  cursor: pointer;
  background: var(--accent-tint);
  border: 1px solid var(--accent-border-strong);
  color: var(--accent-text);
  transition: all 0.15s ease;
}

.orch-btn-addstep:hover:not(:disabled) {
  filter: brightness(1.05);
}

.orch-btn-addstep:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
