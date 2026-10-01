<template>
  <section class="page" data-module="archive">
    <header class="page-head">
      <div>
        <h2>管网档案管理</h2>
        <p class="page-desc">围绕档案编号、关联管段、资料名称做登记、提交归档与确认归档；归档结果直接入库，重开页面与再进系统保持一致。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记档案记录</button>
        <button class="btn" type="button" @click="exportRows">导出管网档案清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键词</span>
        <input v-model="keyword" placeholder="按档案编号 / 资料名称 / 关联管段检索" />
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
          <td v-for="column in columns" :key="column">{{ display(row, column) }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in availableActions(String(row.status))"
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
          <td :colspan="columns.length + 1" class="empty-state">暂无管网档案数据，可先登记档案记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条管网档案记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记档案（同编号后到一份直接覆盖，不新增堆积） -->
    <div v-if="modal === 'create'" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <h3>登记档案记录</h3>
        <p class="modal-hint">档案编号已存在时，后到的一份会覆盖既有资料，不会产生重复记录。</p>
        <label v-for="field in createFields" :key="field.key" class="modal-field">
          <span>{{ field.label }}<i v-if="field.required">*</i></span>
          <input v-model="createForm[field.key]" :placeholder="field.placeholder" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">保存</button>
        </div>
      </div>
    </div>

    <!-- 提交归档：把资料名称、存放位置一并提交入库 -->
    <div v-if="modal === 'submit'" class="modal-mask" @click.self="closeModal">
      <div class="modal">
        <h3>提交归档：{{ activeRow?.['档案编号'] }}</h3>
        <p class="modal-hint">资料名称、存放位置为归档必填项；不全会停在「待补充」，补齐后可从这一步继续。</p>
        <label v-for="field in submitFields" :key="field.key" class="modal-field">
          <span>{{ field.label }}<i>*</i></span>
          <input v-model="submitForm[field.key]" :placeholder="field.placeholder" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="button" @click="confirmSubmit">提交归档</button>
        </div>
      </div>
    </div>

    <!-- 详情：字段 + 归属/状态历史 -->
    <div v-if="modal === 'detail'" class="modal-mask" @click.self="closeModal">
      <div class="modal modal-wide">
        <h3>档案详情：{{ detail?.['档案编号'] }}</h3>
        <table class="data-table detail-table">
          <tbody>
            <tr v-for="field in detailFields" :key="field">
              <th>{{ field }}</th>
              <td>{{ display(detail, field) }}</td>
            </tr>
          </tbody>
        </table>
        <h4 class="detail-history-title">流转历史（归属变更后，历史记录仍保留当时的关联管段）</h4>
        <table class="data-table">
          <thead>
            <tr><th>时间</th><th>操作</th><th>操作后状态</th><th>当时关联管段</th><th>当时资料名称</th><th>当时存放位置</th></tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in historyRows" :key="idx">
              <td>{{ item.at }}</td>
              <td>{{ item.action }}</td>
              <td>{{ item.status }}</td>
              <td>{{ item.snapshot?.['关联管段'] || '—' }}</td>
              <td>{{ item.snapshot?.['资料名称'] || '—' }}</td>
              <td>{{ item.snapshot?.['存放位置'] || '—' }}</td>
            </tr>
            <tr v-if="!historyRows.length">
              <td colspan="6" class="empty-state">暂无流转记录</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="closeModal">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type HistoryItem = {
  at: string
  action: string
  status: string
  snapshot?: Record<string, string | null>
}

const ENDPOINT = '/api/archive'
const columns = ['档案编号', '关联管段', '档案类别', '资料名称', '存放位置', '归档人员', '归档日期', '档案状态']
const statuses = ['待归档', '待补充', '待确认', '已归档', '已作废']
// 每种状态下页面上允许发起的动作；服务端会再校验一遍，重复操作会被幂等拦下
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  待归档: ['提交归档', '作废档案'],
  待补充: ['提交归档', '作废档案'],
  待确认: ['确认归档', '作废档案'],
  已归档: [],
  已作废: [],
}

const STAT_LABELS = ['待归档记录', '本月归档数', '待补充档案', '已归档记录', '已作废记录']

const createFields = [
  { key: '档案编号', label: '档案编号', required: true, placeholder: '如 ARCH-0100' },
  { key: '关联管段', label: '关联管段', required: true, placeholder: '如 PIPE-0001' },
  { key: '档案类别', label: '档案类别', required: true, placeholder: '如 竣工验收 / 竣工图' },
  { key: '资料名称', label: '资料名称', required: false, placeholder: '可先不填，提交归档时补齐' },
  { key: '存放位置', label: '存放位置', required: false, placeholder: '如 A 库 3 排 2 架' },
] as const

const submitFields = [
  { key: '资料名称', label: '资料名称', placeholder: '如 PIPE-0001 段竣工图' },
  { key: '存放位置', label: '存放位置', placeholder: '如 A 库 3 排 2 架' },
  { key: '归档人员', label: '归档人员（可选）', placeholder: '提交人，不填则沿用已登记人员' },
] as const

const detailFields = ['档案编号', '关联管段', '档案类别', '资料名称', '存放位置', '归档人员', '归档日期', '档案状态']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const stats = ref(STAT_LABELS.map((label) => ({ label, value: 0 })))

const modal = ref<'' | 'create' | 'submit' | 'detail'>('')
const activeRow = ref<Row | null>(null)
const detail = ref<Row | null>(null)
const historyRows = ref<HistoryItem[]>([])
const createForm = reactive<Record<string, string>>({})
const submitForm = reactive<Record<string, string>>({})

function display(row: Row | null, column: string): string | number | null {
  if (!row) return '—'
  const value = row[column]
  return value === '' || value === null || value === undefined ? '—' : value
}

function availableActions(status: string): string[] {
  return ACTIONS_BY_STATUS[status] ?? []
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function closeModal() {
  modal.value = ''
  activeRow.value = null
  detail.value = null
  historyRows.value = []
}

// ---------- 登记 ----------

function openCreate() {
  for (const field of createFields) {
    createForm[field.key] = ''
  }
  errorMessage.value = ''
  modal.value = 'create'
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const values: Record<string, string> = {}
    for (const field of createFields) {
      values[field.key] = createForm[field.key]?.trim() ?? ''
    }
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '档案登记未生效，请稍后重试')
    }
    noticeMessage.value = payload.message
    closeModal()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '档案登记失败'
  }
}

// ---------- 动作 ----------

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  if (action === '提交归档') {
    activeRow.value = row
    for (const field of submitFields) {
      submitForm[field.key] = String(row[field.key] ?? '')
    }
    modal.value = 'submit'
    return
  }
  if (action === '作废档案' && !window.confirm(`确认作废档案 ${row['档案编号']}？作废后不可再提交归档。`)) {
    return
  }
  await postAction(row, action, {})
}

async function confirmSubmit() {
  if (!activeRow.value) return
  const row = activeRow.value
  const values: Record<string, string> = {}
  for (const field of submitFields) {
    values[field.key] = submitForm[field.key]?.trim() ?? ''
  }
  await postAction(row, '提交归档', values)
}

async function postAction(row: Row, action: string, values: Record<string, string>) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...values } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      // 失败原因直接展示（资料不全 / 状态不允许 / 已归档重复提交等），数据停在失败那一步
      throw new Error(payload?.message || '管网档案动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message
    closeModal()
    await reload()
  } catch (error) {
    // 失败原因直接显示在页脚；提交弹窗保持打开，用户补齐资料后可从这一步继续
    errorMessage.value = error instanceof Error ? error.message : '管网档案操作失败'
    await reload()
  }
}

// ---------- 详情 ----------

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('档案详情读取失败')
    }
    const payload = await response.json()
    detail.value = payload
    historyRows.value = Array.isArray(payload.history) ? [...payload.history].reverse() : []
    modal.value = 'detail'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '档案详情读取失败'
  }
}

// ---------- 列表 ----------

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('档案记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 概览数字与列表同一次响应返回，保证刷新后卡片条数与列表条数对得上
    if (payload.stats) {
      stats.value = STAT_LABELS.map((label) => ({ label, value: Number(payload.stats[label] ?? 0) }))
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '管网档案列表读取失败'
  }
}

onMounted(reload)
</script>
