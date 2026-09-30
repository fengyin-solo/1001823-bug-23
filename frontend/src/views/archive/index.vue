<template>
  <section class="page" data-module="archive">
    <header class="page-head">
      <div>
        <h2>管网档案管理</h2>
        <p class="page-desc">维护档案记录，围绕档案编号、关联管段、档案类别、资料名称做登记、筛选与归档流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记档案记录</button>
        <button class="btn" type="button" @click="exportRows">导出管网档案清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>档案编号</span>
        <input v-model="keyword" placeholder="按档案编号检索" />
      </label>
      <label class="filter-item">
        <span>档案状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayValue(row, column) }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in actionsFor(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的管网档案数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条管网档案记录</span>
      <span v-if="successMessage" class="success-text">{{ successMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 详情 / 归属变更弹窗 -->
    <div v-if="detailVisible" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <div class="modal-head">
          <h3>档案详情 · {{ detailForm['档案编号'] }}</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <label v-for="field in detailFields" :key="field" class="form-item">
              <span>{{ field === '关联管段' ? '关联管段（归属）' : field }}</span>
              <input v-model="detailForm[field]" :disabled="field === '档案编号'" />
            </label>
          </div>
          <p class="form-tip">
            归档前请补全资料名称与存放位置；归属（关联管段）变更只影响当前档案，
            下方归档历史仍保留在变更前的归属下。
          </p>
          <div class="modal-actions">
            <button class="btn" type="button" :disabled="detailSaving" @click="saveDetail">保存资料 / 变更归属</button>
            <button
              v-for="action in actionsFor(detailRow)"
              :key="action"
              class="btn"
              :class="{ primary: action === '确认归档' }"
              type="button"
              :disabled="detailSaving"
              @click="runDetailAction(action)"
            >
              {{ action }}
            </button>
          </div>

          <h4 class="history-title">归档历史（只增不改）</h4>
          <table v-if="detailRow.history && detailRow.history.length" class="data-table history-table">
            <thead>
              <tr><th>#</th><th>动作</th><th>归档日期</th><th>当时归属</th><th>资料名称</th><th>存放位置</th><th>归档人员</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in detailRow.history" :key="item.seq">
                <td>{{ item.seq }}</td>
                <td>{{ item.action }}</td>
                <td>{{ item['归档日期'] || item.confirmedAt }}</td>
                <td>{{ item['关联管段'] }}</td>
                <td>{{ item['资料名称'] }}</td>
                <td>{{ item['存放位置'] }}</td>
                <td>{{ item['归档人员'] || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty-inline">该资料尚未确认归档，暂无归档历史。</p>
        </div>
      </div>
    </div>

    <!-- 登记弹窗 -->
    <div v-if="createVisible" class="modal-mask" @click.self="closeCreate">
      <div class="modal">
        <div class="modal-head">
          <h3>登记档案记录</h3>
          <button class="link" type="button" @click="closeCreate">关闭</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <label v-for="field in createFields" :key="field" class="form-item">
              <span>{{ field }}<em v-if="requiredFields.includes(field)" class="required">*</em></span>
              <input v-model="createForm[field]" />
            </label>
          </div>
          <p class="form-tip">档案编号已存在时，后登记的一份会覆盖原资料，而不是堆出重复记录。</p>
          <div class="modal-actions">
            <button class="btn primary" type="button" :disabled="createSaving" @click="submitCreate">保存登记</button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

interface HistoryItem {
  seq: number
  action: string
  confirmedAt: string
  关联管段: string
  档案类别?: string
  资料名称: string
  存放位置: string
  归档人员?: string
  归档日期?: string
  [key: string]: string | number | undefined
}

type Row = {
  id: number
  status?: string
  pending?: boolean
  abnormal?: boolean
  history?: HistoryItem[]
  [key: string]: string | number | boolean | HistoryItem[] | undefined | null
}

type ActionResult = {
  ok: boolean
  message: string
  entry: Row | null
}

const ENDPOINT = '/api/archive'
const columns = ['档案编号', '关联管段', '档案类别', '资料名称', '存放位置', '归档人员', '归档日期', '档案状态']
const statuses = ['待归档', '已归档', '待补充', '已作废']
const requiredFields = ['档案编号', '关联管段', '档案类别']
const detailFields = ['档案编号', '关联管段', '档案类别', '资料名称', '存放位置', '归档人员', '归档日期']
const createFields = ['档案编号', '关联管段', '档案类别', '资料名称', '存放位置', '归档人员']
// 已归档 / 已作废不允许在列表里直接推进状态，其余动作在详情弹窗里执行并说明原因。
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  待归档: ['提交归档', '确认归档', '作废档案'],
  待补充: ['提交归档', '确认归档', '作废档案'],
  已归档: [],
  已作废: [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const statCards = ref<{ label: string; value: number }[]>([
  { label: '待归档记录', value: 0 },
  { label: '本月归档数', value: 0 },
  { label: '待补充档案', value: 0 },
  { label: '已归档记录', value: 0 },
])

const detailVisible = ref(false)
const detailSaving = ref(false)
const detailRow = ref<Row>({} as Row)
const detailForm = ref<Record<string, string>>({})

const createVisible = ref(false)
const createSaving = ref(false)
const createForm = ref<Record<string, string>>(emptyCreateForm())

function emptyCreateForm(): Record<string, string> {
  return { 档案编号: '', 关联管段: '', 档案类别: '', 资料名称: '', 存放位置: '', 归档人员: '' }
}

function flash(message: string, ok: boolean) {
  if (ok) {
    successMessage.value = message
    errorMessage.value = ''
  } else {
    errorMessage.value = message
    successMessage.value = ''
  }
}

function displayValue(row: Row, column: string): string {
  const value = row[column]
  if (column === '档案状态') {
    return String(row.status ?? value ?? '—')
  }
  return value === undefined || value === null || value === '' ? '—' : String(value)
}

function actionsFor(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row.status ?? '')] ?? []
}

function formValues(form: Record<string, string>): Record<string, string> {
  const values: Record<string, string> = {}
  for (const field of detailFields) {
    if (form[field] !== undefined) {
      values[field] = form[field]
    }
  }
  return values
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

// ---- 列表与统计：两处同源，刷新后条数对得上 ----
async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value.trim()) {
    params.set('keyword', keyword.value.trim())
  }
  if (statusFilter.value) {
    params.set('status', statusFilter.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('档案记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadStats()
  } catch (error) {
    flash(error instanceof Error ? error.message : '管网档案列表读取失败', false)
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const stats: Record<string, number> = await response.json()
    statCards.value = [
      { label: '待归档记录', value: stats['待归档记录'] ?? 0 },
      { label: '本月归档数', value: stats['本月归档数'] ?? 0 },
      { label: '待补充档案', value: stats['待补充档案'] ?? 0 },
      { label: '已归档记录', value: stats['已归档记录'] ?? 0 },
    ]
  } catch {
    // 统计卡读不到时保留上一次的值，不打断主流程
  }
}

// ---- 动作：以业务返回的 ok 为准，失败时展示原因 ----
async function postAction(id: number, action: string, values: Record<string, string> = {}): Promise<ActionResult> {
  const response = await request(`${ENDPOINT}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action, values }),
  })
  if (!response.ok) {
    throw new Error('管网档案动作请求未送达，请稍后重试')
  }
  return (await response.json()) as ActionResult
}

async function runAction(action: string, row: Row) {
  try {
    const result = await postAction(Number(row.id), action, formValues(row as unknown as Record<string, string>))
    flash(result.message, result.ok)
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '管网档案操作失败', false)
  }
}

// ---- 详情：资料名称 / 存放位置在这里提交，归属变更历史留原处 ----
async function openDetail(row: Row) {
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('档案详情读取失败')
    }
    detailRow.value = (await response.json()) as Row
    syncDetailFromEntry(detailRow.value)
    detailVisible.value = true
  } catch (error) {
    flash(error instanceof Error ? error.message : '档案详情读取失败', false)
  }
}

function closeDetail() {
  detailVisible.value = false
}

function syncDetailFromEntry(entry: Row) {
  detailRow.value = entry
  const form: Record<string, string> = {}
  for (const field of detailFields) {
    const value = entry[field]
    form[field] = typeof value === 'string' ? value : value === undefined || value === null ? '' : String(value)
  }
  detailForm.value = form
}

async function saveDetail() {
  detailSaving.value = true
  try {
    const response = await request(`${ENDPOINT}/${detailRow.value.id}`, {
      method: 'PUT',
      body: JSON.stringify({ values: formValues(detailForm.value) }),
    })
    const result = (await response.json()) as ActionResult
    flash(result.message, result.ok && response.ok)
    if (result.entry) {
      syncDetailFromEntry(result.entry)
    }
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '档案变更保存失败', false)
  } finally {
    detailSaving.value = false
  }
}

async function runDetailAction(action: string) {
  detailSaving.value = true
  try {
    const result = await postAction(Number(detailRow.value.id), action, formValues(detailForm.value))
    flash(result.message, result.ok)
    // 失败也回填：后端已暂存本次填写的内容，用户能直接从失败的那一步接着改。
    if (result.entry) {
      syncDetailFromEntry(result.entry)
    }
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '管网档案操作失败', false)
  } finally {
    detailSaving.value = false
  }
}

// ---- 登记：同编号后到覆盖 ----
function openCreate() {
  createForm.value = emptyCreateForm()
  errorMessage.value = ''
  successMessage.value = ''
  createVisible.value = true
}

function closeCreate() {
  createVisible.value = false
}

async function submitCreate() {
  const missing = requiredFields.filter((field) => !createForm.value[field]?.trim())
  if (missing.length) {
    flash(`缺少必填字段：${missing.join('、')}`, false)
    return
  }
  createSaving.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm.value } }),
    })
    const result = (await response.json()) as ActionResult
    flash(result.message, result.ok && response.ok)
    if (result.ok) {
      closeCreate()
      await reload()
    }
  } catch (error) {
    flash(error instanceof Error ? error.message : '档案登记失败', false)
  } finally {
    createSaving.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions {
  display: flex;
  gap: 8px;
}
.filter-item select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 13px;
  min-width: 120px;
}
.success-text {
  color: #067647;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  background: #fff;
  border-radius: 10px;
  width: 760px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 48px);
  overflow: auto;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.2);
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}
.modal-head h3 {
  margin: 0;
  font-size: 15px;
}
.modal-body {
  padding: 16px 18px;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 16px;
}
.form-item span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 3px;
}
.form-item input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}
.form-item input:disabled {
  background: #f1f5f9;
  color: var(--muted);
}
.required {
  color: #b42318;
  font-style: normal;
  margin-left: 2px;
}
.form-tip {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--muted);
}
.modal-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}
.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.history-title {
  margin: 18px 0 8px;
  font-size: 13px;
}
.history-table {
  font-size: 12px;
}
.empty-inline {
  color: var(--muted);
  font-size: 12px;
}
</style>
