<template>
  <div class="orch">
    <div class="orch-bar">
      <span class="orch-title">任务编排</span>
      <span class="orch-sub">调整执行顺序，并为每步设置 超时 / 重试 / 前后等待</span>
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

        <!-- Enable checkbox (safe tasks locked on) -->
        <div
          class="task-check"
          :class="{ checked: task.enabled, locked: task.safe }"
          :title="task.safe ? '安全任务：涉及资源/货币，无法禁用' : '启用 / 禁用'"
          @click="toggleEnabled(task)"
        ></div>

        <span class="orch-icon">{{ taskIcon(task.id) }}</span>

        <div class="orch-body">
          <div class="orch-name-row">
            <span class="orch-name" :class="{ unsafe: task.safe }">{{ task.name }}</span>
            <span v-if="task.safe" class="orch-lock">🔒 保护</span>
          </div>
          <div class="orch-params">
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
  if (task.safe) return  // safe tasks are always on
  task.enabled = !task.enabled
}

// Coerce inputs into the backend contract: timeout is number|null, the rest
// are non-negative numbers. Empty strings from the inputs become 0/null.
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
    const payload = editTasks.value.map(t => ({
      id: t.id,
      enabled: t.enabled,
      params: normalizeParams(t.params),
    }))
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

.task-check.locked {
  cursor: not-allowed;
  opacity: 0.8;
}
</style>
