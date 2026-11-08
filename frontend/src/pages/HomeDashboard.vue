<template>
  <section class="page-view space-y-4">
    <div class="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
      <span class="flex-shrink-0 whitespace-nowrap text-sm font-medium text-slate-500">项目</span>
      <select v-model.number="dashProjectId" class="field flex-1 max-w-[520px]">
        <option v-for="p in dashProjects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <span v-if="dashLoading" class="flex-shrink-0 text-xs text-slate-400">加载中...</span>
    </div>

    <div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <article class="metric-card">
        <div class="metric-head">
          <span class="icon-dot">●</span>
          <span>企业排放总览</span>
        </div>
        <div v-if="dashLoading" class="p-5 text-sm text-slate-400">加载中...</div>
        <div v-else class="space-y-3 p-5 text-base text-slate-600">
          <div class="flex items-center justify-between">
            <span class="text-slate-500">Scope 1 直接排放</span>
            <span class="font-semibold text-slate-800">{{ dashScope1.toFixed(1) }} t</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-slate-500">Scope 2 间接排放</span>
            <span class="font-semibold text-slate-800">{{ dashScope2.toFixed(1) }} t</span>
          </div>
          <div class="mt-3 flex items-baseline justify-between border-t border-slate-200 pt-4">
            <span class="text-base text-slate-500">合计</span>
            <span class="flex items-baseline gap-1">
              <span class="text-[40px] font-black leading-none text-emerald-600">{{ dashTotal.toFixed(1) }}</span>
              <span class="text-sm font-medium text-slate-400">tCO₂e</span>
            </span>
          </div>
        </div>
      </article>

      <article class="metric-card">
        <div class="metric-head">
          <span class="icon-dot">●</span>
          <span>年度履约状态</span>
        </div>
        <div v-if="dashLoading" class="p-5 text-sm text-slate-400">加载中...</div>
        <div v-else class="space-y-3 p-5 text-base text-slate-600">
          <div class="flex items-center justify-between">
            <span class="text-slate-500">当前持有配额</span>
            <span class="font-semibold text-slate-800">{{ dashQuota.toFixed(1) }} t</span>
          </div>
          <div class="flex items-baseline justify-between border-y border-slate-200 py-4">
            <span class="text-base text-slate-500">配额缺口</span>
            <span class="flex items-baseline gap-1">
              <span class="text-[40px] font-black leading-none" :class="dashQuotaGap > 0 ? 'text-amber-500' : 'text-emerald-500'">{{ Math.abs(dashQuotaGap).toFixed(1) }}</span>
              <span class="text-sm font-medium text-slate-400">t</span>
            </span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-sm text-slate-400">履约截止日期</span>
            <span class="text-sm font-medium text-slate-600">2026-06-30</span>
          </div>
        </div>
      </article>

      <article class="metric-card">
        <div class="metric-head">
          <span class="icon-dot">●</span>
          <span>排放结构速览</span>
        </div>
        <div v-if="dashLoading" class="p-5 text-sm text-slate-400">加载中...</div>
        <div v-else class="flex flex-col gap-3 p-5">
          <div class="flex items-center justify-between">
            <span class="text-sm text-slate-400">盘查年度</span>
            <span class="font-semibold text-slate-800">{{ dashReportYear || '-' }} 年</span>
          </div>
          <div class="flex items-center gap-4">
            <div ref="structureChartRef" class="h-[90px] w-[90px] flex-shrink-0"></div>
            <div class="flex flex-col gap-1.5 text-xs min-w-0 flex-1">
              <div
                v-for="s in structureSlices"
                :key="s.name"
                class="flex items-center gap-1.5"
              >
                <span class="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-full" :style="{ background: s.color }"></span>
                <span class="text-slate-500 truncate">{{ s.name }}</span>
                <span class="ml-auto flex-shrink-0 font-semibold text-slate-700">{{ s.value }}%</span>
              </div>
            </div>
          </div>
          <div class="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-500">
            {{ structureInterpretation }}
          </div>
          <div v-if="dashError" class="text-xs text-amber-500">{{ dashError }}</div>
        </div>
      </article>
    </div>

    <div class="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_1.35fr]">
      <article class="panel-card p-6">
        <div class="flex items-center justify-between">
          <h3 class="text-3xl font-bold text-slate-900">待办事项</h3>
          <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500">3 项</span>
        </div>

        <div class="mt-3 space-y-3">
          <label
            v-for="todo in todos"
            :key="todo.title"
            class="group flex cursor-pointer items-start gap-3 rounded-xl border border-transparent bg-slate-50 px-4 py-3 transition hover:-translate-y-0.5 hover:border-slate-200 hover:bg-white hover:shadow-sm"
          >
            <input type="checkbox" class="mt-1 h-5 w-5 rounded border-slate-300 text-blue-600 focus:ring-blue-300" />
            <div>
              <p class="text-lg font-medium text-slate-800">{{ todo.title }}</p>
              <p class="mt-1 text-sm text-slate-500">截止 {{ todo.deadline }}</p>
            </div>
          </label>
        </div>
      </article>

      <article class="panel-card p-6">
        <h3 class="text-3xl font-bold text-slate-900">近期碳排放趋势</h3>
        <p class="mt-1 text-sm text-slate-500">{{ chartSubtitle }}</p>
        <div ref="chartContainerRef" class="relative mt-3 h-[320px] w-full">
          <div
            v-if="chartEmpty && !chartLoading"
            class="absolute inset-0 z-10 flex items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50"
          >
            <span class="text-sm text-slate-400">暂无该年度趋势数据</span>
          </div>
          <div
            v-else-if="chartError && !chartLoading"
            class="absolute inset-0 z-10 flex items-center justify-center rounded-xl border border-dashed border-amber-300 bg-amber-50"
          >
            <span class="text-sm text-amber-600">{{ chartError }}</span>
          </div>
          <div
            v-else-if="chartLoading"
            class="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-white/70"
          >
            <span class="text-sm text-slate-400">加载图表数据...</span>
          </div>
          <div ref="chartRef" class="h-full w-full" :class="{ invisible: chartEmpty || chartLoading || chartError }"></div>
        </div>
      </article>
    </div>

    <article class="panel-card p-6">
      <div class="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 class="text-3xl font-bold text-slate-900">双碳行业资讯</h3>
          <p class="mt-1 text-sm text-slate-500">
            仅展示公开列表摘要，点击跳转原站阅读全文
          </p>
          <p class="mt-1 text-xs text-slate-400">仅展示最近1000条资讯</p>
        </div>
        <div class="news-actions">
          <select v-model="newsTimeWindow" class="news-window-select">
            <option v-for="opt in newsTimeWindowOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
          <select v-model.number="newsPageSize" class="news-window-select">
            <option :value="10">10条/页</option>
            <option :value="20">20条/页</option>
            <option :value="50">50条/页</option>
          </select>
          <button class="news-refresh-btn" :disabled="newsLoading" @click="refreshNews">
            {{ newsLoading ? "刷新中..." : "刷新资讯" }}
          </button>
          <button class="news-manual-btn" :disabled="manualAddLoading" @click="openManualAddModal">
            {{ manualAddLoading ? "添加中..." : "手动添加资讯" }}
          </button>
        </div>
      </div>

      <p v-if="newsMessage" class="mb-2 text-sm text-slate-500">{{ newsMessage }}</p>
      <div v-if="newsFallbackLayer >= 2" class="mb-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5">
        <span class="text-xs font-semibold text-amber-700">数据来自缓存，点击刷新获取最新资讯</span>
      </div>
      <div v-if="newsSourceDetails.length > 0" class="mb-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
        <div v-for="(detail, i) in newsSourceDetails" :key="i" class="text-xs text-slate-400 leading-relaxed">{{ detail }}</div>
      </div>

      <div v-if="newsItems.length > 0" class="news-list">
        <a
          v-for="item in newsItems"
          :key="item.id"
          :href="item.source_url"
          target="_blank"
          rel="noopener noreferrer"
          class="news-item"
        >
          <div class="news-item-title">{{ item.title }}</div>
          <div class="news-item-summary">{{ item.summary }}</div>
          <div class="news-item-meta">
            <span>{{ item.source_name }}</span>
            <span>{{ formatDate(item.published_at || item.fetched_at) }}</span>
          </div>
        </a>
      </div>
      <div v-if="newsTotalPages > 1" class="news-pagination">
        <button class="news-page-btn" :disabled="newsPage <= 1 || newsLoading" @click="changeNewsPage(newsPage - 1)">
          上一页
        </button>
        <span class="news-page-text">第{{ newsPage }} / {{ newsTotalPages }} 页</span>
        <button class="news-page-btn" :disabled="newsPage >= newsTotalPages || newsLoading" @click="changeNewsPage(newsPage + 1)">
          下一页
        </button>
      </div>
      <div v-else class="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-5 text-sm text-slate-500">
        暂无资讯，点击“刷新资讯”获取最新公开动态。
      </div>
    </article>

    <div v-if="manualAddVisible" class="manual-modal-mask" @click.self="closeManualAddModal">
      <div class="manual-modal-card">
        <div class="manual-modal-head">
          <h4>手动添加资讯</h4>
          <button class="manual-close-btn" @click="closeManualAddModal">关闭</button>
        </div>
        <div class="manual-modal-body">
          <label class="manual-label">新闻链接（URL）</label>
          <input
            v-model.trim="manualAddUrl"
            class="manual-input"
            type="url"
            placeholder="请输入新闻原文链接，例如：https://www.gov.cn/..."
          />
          <p v-if="manualAddTip" class="manual-tip">{{ manualAddTip }}</p>
        </div>
        <div class="manual-modal-foot">
          <button class="manual-secondary-btn" :disabled="manualAddLoading" @click="closeManualAddModal">取消</button>
          <button class="manual-primary-btn" :disabled="manualAddLoading" @click="submitManualAdd">
            {{ manualAddLoading ? "添加中..." : "提交添加" }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { callApi } from '../composables/useApi'

type TodoItem = {
  title: string
  deadline: string
}

const todos: TodoItem[] = [
  { title: '完成 2025 年度碳盘查', deadline: '2026-04-10' },
  { title: '提交正式碳核查报告', deadline: '2026-04-09' },
  { title: '确认基准年选择方案', deadline: '2026-04-08' },
]

// --- Dashboard real data ---
const dashProjectId = ref(1)
const dashProjects = ref<Array<{ id: number; name: string }>>([])
const dashLoading = ref(true)
const dashError = ref('')
const dashProjectName = ref('')
const dashReportYear = ref<number | null>(null)
const dashScope1 = ref(0)
const dashScope2 = ref(0)
const dashTotal = ref(0)
const dashScope1Pct = ref(0)
const dashQuota = ref(0)
const dashQuotaGap = ref(0)

// Emission source breakdown (individual sources from emission_sources table)
interface EmissionSourceItem {
  name: string
  co2e: number
}
const emissionSourceItems = ref<EmissionSourceItem[]>([])

const SOURCE_COLORS = [
  '#3b82f6', '#f59e0b', '#ef4444', '#10b981', '#8b5cf6',
  '#f97316', '#06b6d4', '#ec4899', '#6366f1', '#14b8a6',
  '#e11d48', '#0ea5e9', '#a855f7', '#84cc16', '#64748b',
]

interface SourceSlice {
  name: string
  value: number
  color: string
}

const structureSlices = computed<SourceSlice[]>(() => {
  const items = [...emissionSourceItems.value].filter((s) => s.co2e > 0)
  if (items.length === 0) return []

  items.sort((a, b) => b.co2e - a.co2e)
  const totalCo2e = items.reduce((s, x) => s + x.co2e, 0) || 1

  // Show up to 8 individual sources; group remainder into "其他"
  const maxVisible = 8
  const visible = items.slice(0, maxVisible)
  const rest = items.slice(maxVisible)

  const slices: SourceSlice[] = visible.map((src, i) => ({
    name: src.name,
    value: Math.round((src.co2e / totalCo2e) * 100),
    color: SOURCE_COLORS[i % SOURCE_COLORS.length],
  }))

  if (rest.length > 0) {
    const restPct = Math.round((rest.reduce((s, x) => s + x.co2e, 0) / totalCo2e) * 100)
    if (restPct > 0) {
      slices.push({ name: '其他排放源', value: restPct, color: '#94a3b8' })
    }
  }

  // Renormalize
  const sum = slices.reduce((s, x) => s + x.value, 0)
  if (sum > 0 && sum !== 100) {
    slices[0].value += 100 - sum
  }

  return slices
})

const structureInterpretation = computed(() => {
  const slices = structureSlices.value
  if (slices.length === 0) return '暂无排放源数据'
  const top = slices[0]
  const topName = top.name

  if (topName.includes('电力') || topName.includes('电')) {
    return `"${topName}"排放占比最高（${top.value}%），建议：① 签订绿色电力采购协议（PPA）；② 厂房屋顶光伏自发自用；③ 实施用电侧节能改造（变频/高效电机）。`
  }
  if (topName.includes('热力') || topName.includes('蒸汽') || topName.includes('热')) {
    return `"${topName}"排放占比最高（${top.value}%），建议：① 评估余热回收利用方案；② 推动热源侧清洁化替代；③ 优化蒸汽管网，减少输配损失。`
  }
  if (topName.includes('天然气') || topName.includes('燃气')) {
    return `"${topName}"排放占比最高（${top.value}%），建议：① 优化燃气设备燃烧效率；② 评估生物质气/绿氢替代可行性；③ 加强管道泄漏检测与修复。`
  }
  if (topName.includes('柴油') || topName.includes('汽油') || topName.includes('燃料') || topName.includes('油')) {
    return `"${topName}"排放占比最高（${top.value}%），建议：① 推进车辆/设备电动化替代；② 使用生物柴油等低碳燃料；③ 优化物流调度，减少油品消耗。`
  }
  if (topName.includes('灭火器') || topName.includes('制冷') || topName.includes('空调') || topName.includes('冷媒')) {
    return `"${topName}"排放占比最高（${top.value}%），建议：① 更换低GWP灭火剂/制冷剂；② 加强设备定期检漏与维保；③ 评估自然工质替代方案。`
  }
  return `排放来源较为分散（最高项"${topName}"占${top.value}%），建议实施综合性碳管理策略，覆盖全部主要排放源。`
})

const chartContainerRef = ref<HTMLDivElement | null>(null)
const chartRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let retryTimer = 0

const structureChartRef = ref<HTMLDivElement | null>(null)
let structureChart: echarts.ECharts | null = null

const chartLoading = ref(false)
const chartEmpty = ref(false)
const chartError = ref('')
const chartSubtitle = ref('')

// Reactive chart data (populated by loadDashboard)
const chartMonths = ref<string[]>([])
const chartCo2eValues = ref<number[]>([])
const chartTrendValues = ref<(number | null)[]>([])

type NewsItem = {
  id: number
  title: string
  summary: string
  source_name: string
  source_url: string
  published_at: string | null
  fetched_at: string
}

const newsItems = ref<NewsItem[]>([])
const newsLoading = ref(false)
const newsMessage = ref('')
const newsSourceDetails = ref<string[]>([])
const newsFallbackLayer = ref(-1) // -1=unknown, 0=live, 1=keyword, 2=cache
const newsTimeWindow = ref<'1d' | '1w' | '1m' | '1q' | '1y' | '3y' | '5y' | 'all'>('1w')
const newsPage = ref(1)
const newsPageSize = ref(20)
const newsTotal = ref(0)
const newsTotalPages = ref(0)
const refreshTaskId = ref('')
const manualAddVisible = ref(false)
const manualAddUrl = ref('')
const manualAddLoading = ref(false)
const manualAddTip = ref('')
let refreshPollTimer = 0
let refreshPollCount = 0
const REFRESH_POLL_MAX = 100 // ~200s with 2s interval
const newsTimeWindowOptions = [
  { label: '1天', value: '1d' },
  { label: '1周', value: '1w' },
  { label: '1月', value: '1m' },
  { label: '1季度', value: '1q' },
  { label: '1年', value: '1y' },
  { label: '3年', value: '3y' },
  { label: '5年', value: '5y' },
  { label: '全部', value: 'all' },
] as const

async function loadProjects() {
  try {
    const data = await callApi<Array<{ id: number; name: string }>>('/api/projects')
    dashProjects.value = data || []
    if (dashProjects.value.length > 0 && !dashProjects.value.find((p) => p.id === dashProjectId.value)) {
      dashProjectId.value = dashProjects.value[0].id
    }
  } catch {
    // keep default
  }
}

async function loadDashboard() {
  dashLoading.value = true
  dashError.value = ''
  chartLoading.value = true
  chartError.value = ''
  chartEmpty.value = false
  const pid = dashProjectId.value

  try {
    // Fetch project info first to get report_year for filtering
    const projRes = await callApi<{ name: string; report_year: number | null }>(`/api/projects/${pid}`)
    const reportYear: number | null = projRes.report_year || null
    dashProjectName.value = projRes.name || ''
    dashReportYear.value = reportYear

    // Build timeseries query params with year filter
    const tsParams = new URLSearchParams({ period_type: 'month' })
    if (reportYear) tsParams.set('year', String(reportYear))
    const tsQuery = tsParams.toString()

    // Fetch calculate totals, emission sources, and timeseries in parallel
    const [calcRes, sourcesRes, ngRes, peRes] = await Promise.all([
      callApi<{
        total_emission: number
        scope1_emission: number
        scope2_emission: number
        scope3_emission: number
        calculation_profile: string
        direct_emission: number
        purchased_electricity_emission: number
        purchased_heat_emission: number
        transferred_electricity_emission: number
        transferred_heat_emission: number
      }>(`/api/projects/${pid}/calculate`, 'POST'),
      callApi<Array<{ name: string; co2e: number }>>(`/api/projects/${pid}/emission-sources`),
      callApi<{ items: Array<{ period_start: string; co2e: number }> }>(
        `/api/timeseries/natural-gas/${pid}?${tsQuery}`,
      ),
      callApi<{ items: Array<{ period_start: string; co2e: number }> }>(
        `/api/timeseries/purchased-electricity/${pid}?${tsQuery}`,
      ),
    ])

    emissionSourceItems.value = sourcesRes || []

    // Fallback: if this project has no timeseries rows, try project 1 (seed data lives there)
    let ngItems = ngRes.items || []
    let peItems = peRes.items || []
    if (ngItems.length === 0 && peItems.length === 0 && pid !== 1 && reportYear) {
      const fbQuery = new URLSearchParams({ period_type: 'month', year: String(reportYear) }).toString()
      const [fbNg, fbPe] = await Promise.all([
        callApi<{ items: Array<{ period_start: string; co2e: number }> }>(
          `/api/timeseries/natural-gas/1?${fbQuery}`,
        ),
        callApi<{ items: Array<{ period_start: string; co2e: number }> }>(
          `/api/timeseries/purchased-electricity/1?${fbQuery}`,
        ),
      ])
      ngItems = fbNg.items || []
      peItems = fbPe.items || []
    }

    dashScope1.value = calcRes.scope1_emission || 0
    dashScope2.value = calcRes.scope2_emission || 0
    dashTotal.value = calcRes.total_emission || 0
    const totalForPct = dashTotal.value || 1
    dashScope1Pct.value = Math.round((dashScope1.value / totalForPct) * 100)

    // Try compliance summary (may require auth)
    try {
      const compRes = await callApi<{
        total_emission: number
        free_quota: number
        quota_gap: number
      }>(`/api/carbon-market/summary/${pid}?allocation_method=benchmark`)
      dashQuota.value = compRes.free_quota || 0
      dashQuotaGap.value = compRes.quota_gap || 0
    } catch {
      // Fallback: estimate quota as 92% of average annual emission
      const monthlyAvg = dashTotal.value / Math.max(1, ngItems.length + peItems.length || 12)
      dashQuota.value = Math.round(monthlyAvg * 12 * 0.92 * 100) / 100
      dashQuotaGap.value = Math.round((dashTotal.value - dashQuota.value) * 100) / 100
    }

    // Chart: compute monthly CO₂e, generate full 12 months for project year
    const co2eByMonth: Record<string, number> = {}
    for (const r of ngItems) {
      const d = r.period_start?.slice(0, 7)
      if (d) co2eByMonth[d] = (co2eByMonth[d] || 0) + (r.co2e || 0)
    }
    for (const r of peItems) {
      const d = r.period_start?.slice(0, 7)
      if (d) co2eByMonth[d] = (co2eByMonth[d] || 0) + (r.co2e || 0)
    }

    if (reportYear) {
      const yearMonths: string[] = []
      for (let m = 1; m <= 12; m++) {
        yearMonths.push(`${reportYear}-${String(m).padStart(2, '0')}`)
      }
      const hasAnyData = yearMonths.some((ym) => (co2eByMonth[ym] ?? 0) > 0)
      if (!hasAnyData) {
        chartEmpty.value = true
        chartSubtitle.value = `${reportYear} 年度暂无月度排放数据`
      } else {
        chartEmpty.value = false
        chartMonths.value = yearMonths
        chartCo2eValues.value = yearMonths.map((ym) => Math.round((co2eByMonth[ym] || 0) * 100) / 100)
        chartSubtitle.value = `${reportYear} 年月度碳排放及 3 月移动均线`
      }
    } else {
      const sortedMonths = Object.keys(co2eByMonth).sort().slice(-12)
      if (sortedMonths.length === 0) {
        chartEmpty.value = true
        chartSubtitle.value = '暂无月度排放数据'
      } else {
        chartEmpty.value = false
        chartMonths.value = sortedMonths
        chartCo2eValues.value = sortedMonths.map((m) => Math.round(co2eByMonth[m] * 100) / 100)
        chartSubtitle.value = '近 12 个月碳排放及 3 月移动均线'
      }
    }

    // 3-month moving average with proper boundary handling
    if (!chartEmpty.value) {
      const vals = chartCo2eValues.value
      const trend: (number | null)[] = new Array(vals.length).fill(null)
      for (let i = 0; i < vals.length; i++) {
        if (i === 0) {
          // Month 1: not enough history → use current month value
          trend[i] = vals[i]
        } else if (i === 1) {
          // Month 2: 2-month average
          trend[i] = Math.round(((vals[0] + vals[1]) / 2) * 100) / 100
        } else {
          // Month 3+: full 3-month average
          trend[i] = Math.round(((vals[i - 2] + vals[i - 1] + vals[i]) / 3) * 100) / 100
        }
      }
      chartTrendValues.value = trend
    }

    // Refresh chart if already initialized
    if (!chartEmpty.value) {
      if (chart) {
        chart.clear()
        chart.setOption(getChartOption(), { notMerge: true })
      } else {
        initChart()
      }
    } else if (chart) {
      chart.dispose()
      chart = null
    }

    // Render emission structure donut chart (after DOM flush)
    await nextTick()
    renderStructureChart()
  } catch (err) {
    chartError.value = `趋势数据加载失败: ${err instanceof Error ? err.message : String(err)}`
    chartEmpty.value = true
  } finally {
    dashLoading.value = false
    chartLoading.value = false
  }
}

function formatDate(value: string | null | undefined) {
  if (!value) return '--'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

async function loadNews() {
  try {
    const query = new URLSearchParams({
      page: String(newsPage.value),
      page_size: String(newsPageSize.value),
      time_window: newsTimeWindow.value,
      auto_refresh: 'false',
    }).toString()
    const url = `/api/news/list?${query}`
    console.log('[news] loadNews:', url)
    const res = await callApi<{
      data: NewsItem[]
      total: number
      page: number
      page_size: number
      total_pages: number
    }>(url)
    newsItems.value = res.data || []
    newsTotal.value = res.total || 0
    newsTotalPages.value = res.total_pages || 0
    if (newsItems.value.length > 0) {
      newsMessage.value = `共${res.total} 条资讯`
      console.log(`[news] loadNews OK: ${res.total} items`)
    } else {
      newsMessage.value = '当前时间范围暂无资讯，点击"刷新资讯"获取最新公开动态'
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    console.error('[news] loadNews FAILED:', detail)
    newsMessage.value = `资讯加载失败: ${detail}`
  }
}

async function pollRefreshStatus() {
  if (!refreshTaskId.value) return
  try {
    refreshPollCount += 1
    if (refreshPollCount > REFRESH_POLL_MAX) {
      window.clearTimeout(refreshPollTimer)
      newsMessage.value = '刷新超时，已自动停止轮询并刷新列表'
      refreshTaskId.value = ''
      newsLoading.value = false
      await loadNews()
      return
    }
    const status = await callApi<{
      task_id: string
      status: string
      fetched: number
      inserted: number
      updated: number
      skipped: number
      filtered: number
      pruned: number
      fallback_layer: number
      source: string
      message: string
      source_details: string[]
    }>(`/api/news/refresh-status?task_id=${refreshTaskId.value}`)

    if (status.status === 'completed') {
      window.clearTimeout(refreshPollTimer)
      newsFallbackLayer.value = status.fallback_layer ?? -1
      newsSourceDetails.value = status.source_details || []
      refreshTaskId.value = ''
      newsLoading.value = false

      const layerLabel = status.fallback_layer === 0 ? '实时爬取' : status.fallback_layer === 1 ? '关键词搜索' : '数据库缓存'
      if (status.inserted > 0) {
        newsMessage.value = `刷新完成（${layerLabel}），共新增${status.inserted}条资讯`
      } else {
        newsMessage.value = `刷新完成（${layerLabel}），暂无新资讯`
      }
      console.log(
        `[news] refresh completed: layer=${status.fallback_layer} source=${status.source} inserted=${status.inserted}`,
      )
      await loadNews()
      return
    }

    if (status.status === 'failed' || status.status === 'not_found') {
      window.clearTimeout(refreshPollTimer)
      newsMessage.value = '刷新失败，请稍后重试'
      newsSourceDetails.value = []
      refreshTaskId.value = ''
      newsLoading.value = false
      console.error('[news] refresh failed:', status.message)
      await loadNews()
      return
    }

    newsMessage.value = `资讯刷新中... 已抓取 ${status.fetched} 条`
    refreshPollTimer = window.setTimeout(() => {
      void pollRefreshStatus()
    }, 2000)
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    console.error('[news] pollRefreshStatus FAILED:', detail)
    newsMessage.value = `刷新状态查询失败: ${detail}`
    refreshTaskId.value = ''
    newsLoading.value = false
    await loadNews()
  }
}

async function refreshNews() {
  newsLoading.value = true
  newsSourceDetails.value = []
  try {
    window.clearTimeout(refreshPollTimer)
    refreshPollCount = 0
    const res = await callApi<{
      task_id: string
      status: string
      message: string
    }>(`/api/news/refresh?time_window=${newsTimeWindow.value}`, 'POST')
    refreshTaskId.value = res.task_id
    newsMessage.value = res.message
    await pollRefreshStatus()
  } catch (error) {
    newsMessage.value = `资讯刷新失败: ${error instanceof Error ? error.message : String(error)}`
    newsLoading.value = false
  } finally {
  }
}

function openManualAddModal() {
  manualAddVisible.value = true
  manualAddUrl.value = ''
  manualAddTip.value = ''
}

function closeManualAddModal() {
  if (manualAddLoading.value) return
  manualAddVisible.value = false
}

async function submitManualAdd() {
  if (!manualAddUrl.value) {
    manualAddTip.value = '请先输入新闻链接'
    return
  }
  manualAddLoading.value = true
  manualAddTip.value = '正在添加，请稍候...'
  try {
    const query = new URLSearchParams({ url: manualAddUrl.value }).toString()
    const res = await callApi<{ success: boolean; message: string }>(`/api/news/manual-add?${query}`, 'POST')
    if (!res.success) {
      manualAddTip.value = res.message || '添加失败'
      return
    }
    manualAddTip.value = res.message || '添加成功'
    newsMessage.value = manualAddTip.value
    newsPage.value = 1
    await loadNews()
    manualAddVisible.value = false
  } catch (error) {
    manualAddTip.value = `添加失败: ${error instanceof Error ? error.message : String(error)}`
  } finally {
    manualAddLoading.value = false
  }
}

function changeNewsPage(nextPage: number) {
  if (nextPage < 1) return
  if (newsTotalPages.value > 0 && nextPage > newsTotalPages.value) return
  newsPage.value = nextPage
}

function getChartOption(): echarts.EChartsOption {
  const xData = chartMonths.value
  const co2eData = chartCo2eValues.value
  const trendData = chartTrendValues.value

  return {
    animationDuration: 800,
    animationEasing: 'cubicOut',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      borderWidth: 0,
      textStyle: { color: '#e2e8f0' },
      axisPointer: { type: 'shadow' },
      formatter: (params: any[]) => {
        if (!params || params.length === 0) return ''
        let html = `<b>${params[0].axisValue}</b><br/>`
        for (const p of params) {
          if (p.value == null) continue
          html += `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${p.color};margin-right:6px;"></span>${p.seriesName}: <b>${Number(p.value).toLocaleString(undefined, { maximumFractionDigits: 1 })} tCO₂e</b><br/>`
        }
        return html
      },
    },
    legend: {
      right: 10,
      top: 6,
      textStyle: { color: '#64748b' },
      data: ['月度碳排放', '3月移动均线'],
    },
    grid: { left: 42, right: 16, top: 52, bottom: 28, containLabel: true },
    xAxis: {
      type: 'category',
      data: xData,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#d6deea' } },
      axisLabel: { color: '#64748b', rotate: xData.length > 7 ? 30 : 0, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      name: 'tCO₂e',
      nameTextStyle: { fontSize: 10, color: '#64748b' },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#e5edf7' } },
      axisLabel: { color: '#64748b' },
    },
    series: [
      {
        name: '月度碳排放',
        type: 'bar',
        barWidth: co2eData.length > 12 ? 20 : 36,
        data: co2eData,
        itemStyle: {
          borderRadius: [8, 8, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#19b87a' },
            { offset: 1, color: '#0d9488' },
          ]),
        },
      },
      {
        name: '3月移动均线',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        data: trendData,
        lineStyle: { width: 2.5, color: '#ef4444' },
        itemStyle: { color: '#ef4444', borderColor: '#ffffff', borderWidth: 1.5 },
        z: 5,
      },
    ],
  }
}

function initChart(retry = 0) {
  const el = chartRef.value
  if (!el) return

  if (el.clientWidth === 0 || el.clientHeight === 0) {
    if (retry < 15) {
      retryTimer = window.setTimeout(() => initChart(retry + 1), 60)
    }
    return
  }

  if (!chart) {
    chart = echarts.init(el)
  }

  chart.setOption(getChartOption())

  if (!resizeObserver) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(el)
  }
}

function renderStructureChart() {
  const el = structureChartRef.value
  if (!el || el.clientWidth === 0) return

  if (!structureChart) {
    structureChart = echarts.init(el)
  }

  const slices = structureSlices.value
  const data = slices.map((s) => ({ name: s.name, value: s.value, itemStyle: { color: s.color } }))

  structureChart.setOption(
    {
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(15,23,42,0.92)',
        borderWidth: 0,
        textStyle: { color: '#e2e8f0', fontSize: 12 },
        formatter: (p: any) => `${p.name}: <b>${p.value}%</b>`,
      },
      series: [
        {
          type: 'pie',
          radius: ['58%', '82%'],
          center: ['50%', '50%'],
          emphasis: { scale: false },
          label: { show: false },
          data,
          animation: true,
          animationDuration: 600,
        },
      ],
    },
    { notMerge: true },
  )
}

onMounted(async () => {
  await nextTick()
  await loadProjects()
  await loadDashboard()
  initChart()
  await loadNews()
})

watch(dashProjectId, async () => {
  await loadDashboard()
})

watch(newsTimeWindow, async () => {
  newsPage.value = 1
  await loadNews()
})

watch(newsPageSize, async () => {
  newsPage.value = 1
  await loadNews()
})

watch(newsPage, async () => {
  await loadNews()
})

onBeforeUnmount(() => {
  window.clearTimeout(retryTimer)
  window.clearTimeout(refreshPollTimer)
  refreshPollCount = 0
  resizeObserver?.disconnect()
  resizeObserver = null
  chart?.dispose()
  chart = null
  structureChart?.dispose()
  structureChart = null
})
</script>

<style scoped>
.metric-card,
.panel-card {
  min-width: 0;
  border-radius: 16px;
  border: 1px solid #dbe5f3;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.metric-card:hover,
.panel-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.12);
}

@media (max-width: 640px) {
  .metric-card .text-\[40px\] {
    font-size: 2rem !important;
  }
}

.metric-head {
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 15px 15px 0 0;
  background: linear-gradient(90deg, #0f4ea2 0%, #1567c8 100%);
  padding: 14px 18px;
  font-size: 20px;
  font-weight: 700;
  color: #ffffff;
}

.icon-dot {
  display: inline-grid;
  height: 24px;
  width: 24px;
  place-items: center;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.18);
  font-size: 12px;
}

.field {
  border: 1px solid #cdd8e5;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 14px;
  color: #0f172a;
  background: #fff;
}

.news-refresh-btn {
  border-radius: 10px;
  border: 1px solid #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
  padding: 8px 14px;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.2s ease;
}

.news-manual-btn {
  border-radius: 10px;
  border: 1px solid #86efac;
  background: #f0fdf4;
  color: #166534;
  padding: 8px 14px;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.2s ease;
}

.news-manual-btn:hover:not(:disabled) {
  background: #dcfce7;
  border-color: #4ade80;
}

.news-manual-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.news-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.news-window-select {
  border-radius: 10px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #334155;
  padding: 8px 10px;
  font-size: 14px;
}

.news-refresh-btn:hover:not(:disabled) {
  background: #dbeafe;
  border-color: #60a5fa;
}

.news-refresh-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.news-list {
  display: grid;
  gap: 10px;
}

.news-item {
  display: block;
  border: 1px solid #dbe5f3;
  border-radius: 12px;
  background: #f8fbff;
  padding: 12px 14px;
  transition: all 0.2s ease;
}

.news-item:hover {
  transform: translateY(-1px);
  background: #ffffff;
  border-color: #bfdbfe;
  box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
}

.news-item-title {
  font-size: 17px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.4;
}

.news-item-summary {
  margin-top: 6px;
  font-size: 14px;
  color: #475569;
  line-height: 1.6;
}

.news-item-meta {
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #64748b;
}

.news-pagination {
  margin-top: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.news-page-btn {
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #1e293b;
  padding: 6px 10px;
  font-size: 13px;
}

.news-page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.news-page-text {
  font-size: 13px;
  color: #64748b;
}

.manual-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  background: rgba(15, 23, 42, 0.45);
}

.manual-modal-card {
  width: min(620px, calc(100vw - 32px));
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid #dbe5f3;
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.25);
}

.manual-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #e2e8f0;
}

.manual-modal-head h4 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.manual-close-btn {
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  background: #fff;
  padding: 6px 10px;
  font-size: 13px;
}

.manual-modal-body {
  padding: 16px;
}

.manual-label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  color: #334155;
}

.manual-input {
  width: 100%;
  border-radius: 10px;
  border: 1px solid #cbd5e1;
  padding: 10px 12px;
  font-size: 14px;
  color: #0f172a;
}

.manual-tip {
  margin-top: 10px;
  font-size: 13px;
  color: #475569;
}

.manual-modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 16px 16px;
}

.manual-secondary-btn,
.manual-primary-btn {
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 600;
}

.manual-secondary-btn {
  border: 1px solid #cbd5e1;
  background: #fff;
  color: #334155;
}

.manual-primary-btn {
  border: 1px solid #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
}

.manual-secondary-btn:disabled,
.manual-primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

</style>

