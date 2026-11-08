<template>
  <section class="page-view market-page">
    <!-- Real-time Carbon Market Price -->
    <div class="panel">
      <div class="market-price-header">
        <span class="market-price-dot">●</span>
        <span class="market-price-title">全国碳市场行情</span>
        <span class="market-price-source">{{ marketPrice.symbol === 'CEA' ? '全国碳市场(CEA)' : marketPrice.symbol + '试点' }} · 数据来源：{{ marketPrice.source }}</span>
      </div>
      <div v-if="marketLoading" class="market-price-loading">正在获取碳价数据...</div>
      <div v-else-if="marketError" class="market-price-error">{{ marketError }}</div>
      <div v-else class="market-price-grid">
        <div class="market-price-main">
          <span class="market-price-label">收盘价（元/吨）</span>
          <span class="market-price-value">¥ {{ marketPrice.price.toFixed(2) }}</span>
          <span class="market-price-change" :class="marketPrice.change_pct >= 0 ? 'up' : 'down'">
            {{ marketPrice.change_pct >= 0 ? '↑' : '↓' }} {{ Math.abs(marketPrice.change_pct).toFixed(2) }}%
          </span>
        </div>
        <div class="market-price-detail">
          <div class="market-detail-row">
            <span>开盘价</span>
            <strong>¥ {{ marketPrice.open_price.toFixed(2) || '-' }}</strong>
          </div>
          <div class="market-detail-row">
            <span>最高价</span>
            <strong class="text-emerald-600">¥ {{ marketPrice.high_price.toFixed(2) || '-' }}</strong>
          </div>
          <div class="market-detail-row">
            <span>最低价</span>
            <strong class="text-red-500">¥ {{ marketPrice.low_price.toFixed(2) || '-' }}</strong>
          </div>
          <div class="market-detail-row">
            <span>成交量</span>
            <strong>{{ marketPrice.volume.toLocaleString() || '-' }} 吨</strong>
          </div>
          <div class="market-detail-row">
            <span>成交额</span>
            <strong>¥ {{ marketPrice.turnover.toLocaleString() || '-' }}</strong>
          </div>
          <div class="market-detail-row">
            <span>交易日</span>
            <strong>{{ marketPrice.price_date || '-' }}</strong>
          </div>
        </div>
      </div>
      <div v-if="!marketLoading && !marketError" class="market-price-foot">
        <span v-if="isOfflinePrice" class="market-offline-badge">参考价（离线数据）</span>
        <span v-else-if="marketPrice.cached" class="market-cache-note">数据来自缓存</span>
        <button class="market-refresh-btn" @click="refreshMarketPrice">刷新碳价</button>
      </div>
    </div>

    <div class="panel">
      <div class="kpi-grid">
        <article class="kpi-card">
          <h3>企业年度总排放量</h3>
          <p>
            <strong>{{ totalEmission.toFixed(1) }}</strong>
            <span>tCO₂e</span>
          </p>
        </article>

        <article class="kpi-card">
          <h3>发放免费配额量</h3>
          <p>
            <strong>{{ freeQuota.toFixed(1) }}</strong>
            <span>t</span>
          </p>
        </article>

        <article class="kpi-card kpi-highlight">
          <h3>当前履约配额缺口</h3>
          <p>
            <strong>{{ gap.toFixed(1) }}</strong>
            <span>t</span>
          </p>
        </article>
      </div>

      <div class="plan-grid">
        <article class="plan-card">
          <h3>方案 A：全额购买</h3>
          <p class="price">{{ formatYuan(planA) }}</p>
          <small>按{{ isOfflinePrice ? '参考' : '当期' }}碳价 {{ carbonPrice.toFixed(2) }} 元/吨 计算</small>
        </article>

        <article class="plan-card best">
          <h3>方案 B：配额 + CCER</h3>
          <p class="price">{{ formatYuan(planB) }}</p>
          <small>使用 {{ ccerUse }} 吨 CCER 抵消缺口</small>
        </article>

        <article class="plan-card">
          <h3>方案 C：绿电抵扣</h3>
          <p class="price">{{ formatYuan(planC) }}</p>
          <small>基于年度绿电使用比例核算</small>
        </article>
      </div>

      <div class="action-grid">
        <div class="recommend">
          <p class="title">AI 推荐最优方案：{{ recommendedPlan }}</p>
          <p class="desc">合规前提下成本最低，预计节省约 {{ saveRatio }}%</p>
        </div>

        <button class="action-btn blue" @click="generateComplianceReport">生成履约报告</button>
        <button class="action-btn dark" @click="exportMaterials">导出申报材料</button>
      </div>
    </div>

    <p class="status">{{ status }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { callApi } from '../composables/useApi'

// --- carbon market price ---
interface MarketPriceData {
  symbol: string
  price: number
  price_date: string
  open_price: number
  high_price: number
  low_price: number
  close_price: number
  volume: number
  turnover: number
  change_pct: number
  source: string
  fetched_at: string
  cached: boolean
  fallback_layer: number  // 0=live, 1=AKShare, 2=offline benchmark
}
const marketPrice = ref<MarketPriceData>({
  symbol: '',
  price: 0,
  price_date: '',
  open_price: 0,
  high_price: 0,
  low_price: 0,
  close_price: 0,
  volume: 0,
  turnover: 0,
  change_pct: 0,
  source: '',
  fetched_at: '',
  cached: false,
  fallback_layer: 2,
})
const marketLoading = ref(false)
const marketError = ref('')

const isOfflinePrice = computed(() => marketPrice.value.fallback_layer >= 2)

async function loadMarketPrice(force = false) {
  marketLoading.value = true
  marketError.value = ''
  const t0 = performance.now()
  try {
    const qs = force ? '?force=true' : ''
    const data = await callApi<MarketPriceData>(`/api/carbon-market/market-price${qs}`)
    marketPrice.value = data
    const elapsed = (performance.now() - t0).toFixed(0)
    console.log(
      `[carbon-market] loadMarketPrice OK in ${elapsed}ms:`,
      `layer=${data.fallback_layer}`,
      `price=${data.price}`,
      `date=${data.price_date}`,
      `source=${data.source}`,
      data,
    )
  } catch (err) {
    const elapsed = (performance.now() - t0).toFixed(0)
    const detail = err instanceof Error ? err.message : String(err)
    console.error(`[carbon-market] loadMarketPrice FAILED after ${elapsed}ms:`, detail, err)
    marketError.value = `碳价获取失败：${detail}`
  } finally {
    marketLoading.value = false
  }
}

async function refreshMarketPrice() {
  console.log('[carbon-market] manual refresh triggered')
  await loadMarketPrice(true)
}

const projectId = ref(1)
const totalEmission = ref(544.7)
const freeQuota = ref(450.0)
const ccerUse = ref(50)
// carbonPrice tracks the live market price; falls back to 85 if market data unavailable
const carbonPrice = computed(() => marketPrice.value.price > 0 ? marketPrice.value.price : 85)
const ccerPrice = ref(58)
const greenDiscountRate = ref(0.03)
const status = ref('准备就绪。')
const recommendedPlan = ref('方案 B')

const gap = computed(() => Math.max(totalEmission.value - freeQuota.value, 0))
const planA = computed(() => gap.value * carbonPrice.value)
const planB = computed(() => Math.max(gap.value - ccerUse.value, 0) * carbonPrice.value + ccerUse.value * ccerPrice.value)
const planC = computed(() => Math.max(planA.value * (1 - greenDiscountRate.value), 0))
const saveRatio = computed(() => {
  if (planA.value <= 0) return 0
  return Math.max(0, Math.round(((planA.value - planB.value) / planA.value) * 100))
})

function formatYuan(value: number) {
  return `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`
}

async function generateComplianceReport() {
  try {
    const payload = await callApi(`/api/carbon-market/simulate/${projectId.value}`, 'POST', {
      allocation_method: 'benchmark',
      carbon_price: carbonPrice.value,
      ccer_price: ccerPrice.value,
      green_electricity_price: 70,
      ccer_max_ratio: 0.3,
      green_power_max_ratio: 0.2,
    })

    updateFromPayload(payload)
    const p = payload as Record<string, unknown>
    const rp = String(p.recommended_plan || '')
    if (rp) recommendedPlan.value = rp
    status.value = '履约测算已完成，报告数据已更新。'
  } catch (error) {
    status.value = `测算失败：${error instanceof Error ? error.message : '请检查后端服务'}`
  }
}

async function exportMaterials() {
  try {
    const payload = await callApi(`/api/carbon-market/report/${projectId.value}`, 'POST', {
      allocation_method: 'benchmark',
      carbon_price: carbonPrice.value,
      ccer_price: ccerPrice.value,
      green_electricity_price: 70,
      ccer_max_ratio: 0.3,
      green_power_max_ratio: 0.2,
    })
    const data = payload as Record<string, unknown>
    status.value = `履约报告已生成：${String(data.file_path || '')}`
  } catch (error) {
    status.value = `导出失败：${error instanceof Error ? error.message : '请稍后重试'}`
  }
}

function updateFromPayload(payload: unknown) {
  if (!payload || typeof payload !== 'object') return

  const data = payload as Record<string, unknown>
  const summary = (data.summary as Record<string, unknown> | undefined) || data
  const emission = toNumber(summary.total_emission ?? summary.emission ?? summary.total)
  const quota = toNumber(summary.allowance ?? summary.free_quota ?? summary.quota)
  const qgap = toNumber(summary.quota_gap)

  if (emission !== null) totalEmission.value = emission
  if (quota !== null) freeQuota.value = quota
  if (qgap !== null) {
    const ccer = Math.min(ccerUse.value, qgap)
    ccerUse.value = Math.max(ccer, 0)
  }
}

function toNumber(value: unknown): number | null {
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

async function loadSummary() {
  try {
    const payload = await callApi(`/api/carbon-market/summary/${projectId.value}?allocation_method=benchmark`)
    updateFromPayload(payload)
  } catch {
    // ignore
  }
}

onMounted(() => {
  void loadSummary()
  void loadMarketPrice()
})
</script>

<style scoped>
.market-page {
  display: grid;
  gap: 12px;
}

.market-page h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: #1f2937;
}

.market-page > header p {
  margin: 4px 0 0;
  font-size: 15px;
  color: #607288;
}

.panel {
  border: 1px solid #d9e1ec;
  border-radius: 8px;
  background: #ffffff;
  padding: 14px;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
}

.kpi-grid,
.plan-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.kpi-card,
.plan-card {
  border: 1px solid #d8e0eb;
  border-radius: 8px;
  background: #f9fbfe;
  padding: 12px;
}

.kpi-card h3,
.plan-card h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #5b6d83;
}

.kpi-card p,
.plan-card .price {
  margin: 10px 0 0;
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.kpi-card strong,
.plan-card .price {
  font-size: 43px;
  font-weight: 700;
  color: #1f2937;
}

.kpi-card span {
  font-size: 15px;
  color: #64748b;
}

.kpi-highlight {
  background: #0f5ca6;
  border-color: #0f5ca6;
}

.kpi-highlight h3,
.kpi-highlight strong,
.kpi-highlight span {
  color: #ffffff;
}

.plan-grid {
  margin-top: 10px;
}

.plan-card .price {
  color: #6b7280;
}

.plan-card small {
  display: block;
  margin-top: 8px;
  font-size: 12px;
  color: #8090a4;
}

.plan-card.best {
  border-color: #71c289;
  background: #f3fbf5;
  box-shadow: 0 8px 16px rgba(41, 148, 77, 0.12);
}

.plan-card.best h3,
.plan-card.best .price {
  color: #26984f;
}

.action-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: 1.35fr 1fr 1fr;
  gap: 10px;
}

.recommend {
  border-radius: 8px;
  background: #e7f4ec;
  border: 1px solid #cce6d5;
  padding: 12px;
}

.recommend .title {
  margin: 0;
  color: #1e7d43;
  font-size: 15px;
  font-weight: 700;
}

.recommend .desc {
  margin: 6px 0 0;
  color: #4f8f68;
  font-size: 13px;
}

.action-btn {
  border: none;
  border-radius: 8px;
  color: #ffffff;
  font-size: 14px;
  font-weight: 700;
  height: 50px;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.action-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 14px rgba(15, 23, 42, 0.16);
}

.action-btn.blue {
  background: #0f5ca6;
}

.action-btn.dark {
  background: #2f3742;
}

.status {
  margin: 0;
  color: #4a6387;
  font-size: 14px;
}

/* Market price card */
.market-price-header {
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 7px 7px 0 0;
  background: linear-gradient(90deg, #0d7c4b 0%, #0ea16a 100%);
  padding: 14px 18px;
  margin: -14px -14px 0;
  font-size: 16px;
  font-weight: 700;
  color: #ffffff;
}

.market-price-dot {
  display: inline-grid;
  height: 20px;
  width: 20px;
  place-items: center;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.18);
  font-size: 11px;
}

.market-price-title {
  font-size: 16px;
}

.market-price-source {
  margin-left: auto;
  font-size: 11px;
  font-weight: 400;
  opacity: 0.8;
}

.market-price-loading,
.market-price-error {
  padding: 20px 0;
  font-size: 14px;
  color: #64748b;
}

.market-price-error {
  color: #d97706;
}

.market-price-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 24px;
  padding: 20px 0 0;
  align-items: start;
}

.market-price-main {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 160px;
}

.market-price-label {
  font-size: 12px;
  color: #94a3b8;
}

.market-price-value {
  font-size: 32px;
  font-weight: 900;
  color: #0f172a;
  line-height: 1.1;
}

.market-price-change {
  font-size: 15px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 6px;
}

.market-price-change.up {
  color: #059669;
  background: #d1fae5;
}

.market-price-change.down {
  color: #dc2626;
  background: #fee2e2;
}

.market-price-detail {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 24px;
}

.market-detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  min-width: 120px;
  font-size: 13px;
  color: #64748b;
}

.market-detail-row strong {
  color: #1e293b;
}

.market-price-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 12px 0 2px;
}

.market-cache-note {
  font-size: 12px;
  color: #94a3b8;
}

.market-offline-badge {
  font-size: 12px;
  font-weight: 600;
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fcd34d;
  border-radius: 6px;
  padding: 2px 10px;
}

.market-refresh-btn {
  border-radius: 8px;
  border: 1px solid #86efac;
  background: #f0fdf4;
  color: #047857;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.market-refresh-btn:hover {
  background: #d1fae5;
  border-color: #4ade80;
}

@media (max-width: 640px) {
  .market-price-grid {
    grid-template-columns: 1fr;
    gap: 14px;
  }
  .market-price-detail {
    grid-template-columns: 1fr;
  }
  .market-price-value {
    font-size: 26px;
  }
}

@media (max-width: 1200px) {
  .kpi-grid,
  .plan-grid,
  .action-grid {
    grid-template-columns: 1fr;
  }
}
</style>



