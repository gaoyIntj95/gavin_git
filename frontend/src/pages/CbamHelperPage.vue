<template>
  <section class="page-view cbam-page">
    <!-- Real-time EUA Carbon Price -->
    <div class="panel">
      <div class="eua-price-header">
        <span class="eua-price-dot">●</span>
        <span class="eua-price-title">欧盟碳市场行情 (EUA)</span>
        <span class="eua-price-source">数据来源：{{ euaPrice.source || 'investing.com' }}</span>
      </div>

      <!-- Loading -->
      <div v-if="euaLoading" class="eua-price-status">正在获取欧盟碳价数据...</div>

      <!-- Error (after at least one attempt) -->
      <div v-else-if="euaError" class="eua-price-error">
        <p>{{ euaError }}</p>
        <button class="market-refresh-btn" @click="refreshEUAPrice">重试</button>
      </div>

      <!-- Data loaded -->
      <div v-else class="eua-price-grid">
        <div class="eua-price-main">
          <span class="eua-price-label">最新价格（欧元/吨）</span>
          <span class="eua-price-value">€ {{ euaPrice.price.toFixed(2) }}</span>
          <span
            class="eua-price-change"
            :class="euaPrice.change_pct >= 0 ? 'up' : 'down'"
          >
            {{ euaPrice.change_pct >= 0 ? '↑' : '↓' }}
            {{ Math.abs(euaPrice.change_pct).toFixed(2) }}%
          </span>
        </div>
        <div class="eua-price-detail">
          <div class="eua-detail-row">
            <span>开盘价</span>
            <strong>€ {{ euaPrice.open_price > 0 ? euaPrice.open_price.toFixed(2) : '-' }}</strong>
          </div>
          <div class="eua-detail-row">
            <span>最高价</span>
            <strong class="text-emerald-600">€ {{ euaPrice.high_price > 0 ? euaPrice.high_price.toFixed(2) : '-' }}</strong>
          </div>
          <div class="eua-detail-row">
            <span>最低价</span>
            <strong class="text-red-500">€ {{ euaPrice.low_price > 0 ? euaPrice.low_price.toFixed(2) : '-' }}</strong>
          </div>
          <div class="eua-detail-row">
            <span>成交量</span>
            <strong>{{ euaPrice.volume > 0 ? euaPrice.volume.toLocaleString() : '-' }}</strong>
          </div>
          <div class="eua-detail-row">
            <span>结算日</span>
            <strong>{{ euaPrice.settlement_date || '-' }}</strong>
          </div>
          <div class="eua-detail-row">
            <span>交易日</span>
            <strong>{{ euaPrice.price_date || '-' }}</strong>
          </div>
        </div>
      </div>

      <!-- Footer: offline badge / cache note / refresh -->
      <div v-if="!euaLoading && !euaError" class="eua-price-foot">
        <span v-if="isEUAOffline" class="market-offline-badge">参考价（离线数据）</span>
        <span v-else-if="euaPrice.cached" class="market-cache-note">数据来自缓存</span>
        <button class="market-refresh-btn" @click="refreshEUAPrice">刷新碳价</button>
      </div>
    </div>

    <!-- CBAM business panel -->
    <div class="cbam-panel">
      <div class="top-grid">
        <div class="mini-grid">
          <article class="mini-card">
            <span>出口产品类别</span>
            <strong>{{ productName }}</strong>
          </article>

          <article class="mini-card">
            <span>本次出口数量</span>
            <strong>{{ quantity.toLocaleString('zh-CN') }} {{ unit }}</strong>
          </article>

          <article class="mini-card">
            <span>产品碳足迹</span>
            <strong>{{ emissionPerUnit.toFixed(2) }} tCO₂e/{{ unit }}</strong>
          </article>

          <article class="mini-card">
            <span>当期欧盟碳价</span>
            <strong>
              €{{ euCarbonPrice }}/t
              <span v-if="isEUAOffline" class="inline-offline-badge">离线</span>
            </strong>
          </article>
        </div>

        <article class="cost-card">
          <p>预计应缴碳关税 (Total Cost)</p>
          <h3>{{ totalCostEuro }}</h3>
          <small v-if="isEUAOffline" class="cost-offline-note">基于参考价计算，实际关税以当期结算价为准</small>
        </article>
      </div>

      <div class="doc-row">
        <article class="doc-card">
          <span class="ok">✓</span>
          <div>
            <h4>碳足迹数据表</h4>
            <p>自动提取核算结果</p>
          </div>
        </article>

        <article class="doc-card">
          <span class="ok">✓</span>
          <div>
            <h4>排放源数据文件</h4>
            <p>生产过程原始记录</p>
          </div>
        </article>

        <article class="doc-card">
          <span class="ok">✓</span>
          <div>
            <h4>官方申报模板</h4>
            <p>预填关键申报信息</p>
          </div>
        </article>
      </div>
    </div>

    <div class="action-row">
      <button class="action-btn blue" @click="exportPackage">导出申报数据包</button>
      <button class="action-btn line" @click="showRiskHint">查看贸易风险提示</button>
    </div>

    <p class="status">{{ status }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { callApi } from '../composables/useApi'

// =========================================================================
// EUA carbon market price
// =========================================================================
interface EUAPriceData {
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
  fallback_layer: number
  settlement_date: string
}

const euaPrice = ref<EUAPriceData>({
  symbol: 'EUA',
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
  settlement_date: '',
})

// Start in loading state so the user sees a spinner, not empty data
const euaLoading = ref(true)
const euaError = ref('')

const isEUAOffline = computed(() => euaPrice.value.fallback_layer >= 2)
// Live price drives cost calculation; fallback to €82 when price is unavailable
const euCarbonPrice = computed(() => (euaPrice.value.price > 0 ? euaPrice.value.price : 82))

async function loadEUAPrice(force = false) {
  euaLoading.value = true
  euaError.value = ''
  const t0 = performance.now()

  try {
    const qs = force ? '?force=true' : ''
    const url = `/api/cbam/eu-carbon-price${qs}`
    console.log('[eu-carbon-price] calling:', url)

    const data = await callApi<EUAPriceData>(url)
    euaPrice.value = data

    const elapsed = (performance.now() - t0).toFixed(0)
    console.log(
      `[eu-carbon-price] OK in ${elapsed}ms | layer=${data.fallback_layer} | ` +
        `price=€${data.price} | settlement=${data.settlement_date} | ` +
        `O=${data.open_price} H=${data.high_price} L=${data.low_price} V=${data.volume}`,
    )
  } catch (err) {
    const elapsed = (performance.now() - t0).toFixed(0)
    const detail = err instanceof Error ? err.message : String(err)
    console.error(`[eu-carbon-price] FAILED after ${elapsed}ms:`, detail)
    if (err instanceof Error && err.stack) {
      console.error(`[eu-carbon-price] stack:`, err.stack)
    }
    euaError.value = `欧盟碳价获取失败：${detail}`
    // Keep euaPrice at its current values (defaults with price=0)
    // euCarbonPrice computed will fall back to 82
  } finally {
    euaLoading.value = false
  }
}

async function refreshEUAPrice() {
  console.log('[eu-carbon-price] manual refresh')
  await loadEUAPrice(true)
}

// =========================================================================
// CBAM business logic
// =========================================================================
const projectId = ref(1)
const productName = ref('水泥建材')
const quantity = ref(1000)
const unit = ref('吨')
const emissionPerUnit = ref(0.85)
const status = ref('准备就绪。')

// 碳关税 = 出口数量 × 产品碳足迹 × 当期欧盟碳价
const totalCost = computed(
  () => quantity.value * emissionPerUnit.value * euCarbonPrice.value,
)
const totalCostEuro = computed(
  () =>
    `€ ${totalCost.value.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`,
)

async function exportPackage() {
  try {
    const now = new Date()
    const start = new Date(now.getFullYear(), now.getMonth(), 1).toISOString()
    const end = new Date(now.getFullYear(), now.getMonth() + 1, 0, 23, 59, 59).toISOString()

    const batchRes = (await callApi(`/api/cbam/batches/${projectId.value}`, 'POST', {
      batch_name: `${productName.value}-${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}`,
      declaration_period_start: start,
      declaration_period_end: end,
      notes: '页面自动创建批次',
    })) as Record<string, unknown>
    const batchId = Number(batchRes.id)

    await callApi(`/api/cbam/extract/${projectId.value}`, 'POST', {
      batch_id: batchId,
      product_name: productName.value,
      product_category: '建材',
      product_quantity: quantity.value,
      unit: unit.value,
      eu_carbon_price: euCarbonPrice.value,
      footprint_scope: 'direct+indirect',
      notes: '页面自动提取',
    })

    const pkg = (await callApi(`/api/cbam/export-package/${projectId.value}?batch_id=${batchId}`, 'POST')) as Record<
      string,
      unknown
    >
    status.value = `申报数据包已生成：${String(pkg.package_path || '')}`
  } catch (error) {
    status.value = `生成失败：${error instanceof Error ? error.message : '请检查后端服务'}`
  }
}

function showRiskHint() {
  const riskLevel = totalCost.value > 80000 ? '高' : totalCost.value > 50000 ? '中' : '低'
  status.value = `贸易风险提示：当前成本压力等级为${riskLevel}，建议优先优化高碳工序。`
}

onMounted(() => {
  void loadEUAPrice()
})
</script>

<style scoped>
.cbam-page {
  display: grid;
  gap: 12px;
}

.cbam-page h2 {
  margin: 0;
  color: #1f2937;
  font-size: 24px;
  font-weight: 700;
}

.cbam-page > header p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 15px;
}

/* ---- shared panel ---- */
.panel {
  border: 1px solid #d9e1ec;
  border-radius: 8px;
  background: #ffffff;
  padding: 14px;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
}

.cbam-panel {
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 8px 16px rgba(15, 23, 42, 0.08);
  padding: 12px;
}

/* ---- EUA price card ---- */
.eua-price-header {
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 7px 7px 0 0;
  background: linear-gradient(90deg, #1e40af 0%, #2563eb 100%);
  padding: 14px 18px;
  margin: -14px -14px 0;
  font-size: 16px;
  font-weight: 700;
  color: #ffffff;
}

.eua-price-dot {
  display: inline-grid;
  height: 20px;
  width: 20px;
  place-items: center;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.18);
  font-size: 11px;
}

.eua-price-title {
  font-size: 16px;
}

.eua-price-source {
  margin-left: auto;
  font-size: 11px;
  font-weight: 400;
  opacity: 0.8;
}

.eua-price-status {
  padding: 24px 0;
  text-align: center;
  font-size: 14px;
  color: #64748b;
}

.eua-price-error {
  padding: 20px 0;
  text-align: center;
}

.eua-price-error p {
  margin: 0 0 10px;
  font-size: 14px;
  color: #d97706;
}

.eua-price-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 24px;
  padding: 20px 0 0;
  align-items: start;
}

.eua-price-main {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  min-width: 160px;
}

.eua-price-label {
  font-size: 12px;
  color: #94a3b8;
}

.eua-price-value {
  font-size: 32px;
  font-weight: 900;
  color: #0f172a;
  line-height: 1.1;
}

.eua-price-change {
  font-size: 15px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 6px;
}

.eua-price-change.up {
  color: #059669;
  background: #d1fae5;
}

.eua-price-change.down {
  color: #dc2626;
  background: #fee2e2;
}

.eua-price-detail {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 24px;
}

.eua-detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  min-width: 120px;
  font-size: 13px;
  color: #64748b;
}

.eua-detail-row strong {
  color: #1e293b;
}

.text-emerald-600 {
  color: #059669 !important;
}

.text-red-500 {
  color: #ef4444 !important;
}

.eua-price-foot {
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
  border: 1px solid #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.market-refresh-btn:hover {
  background: #dbeafe;
  border-color: #60a5fa;
}

/* ---- CBAM top grid ---- */
.top-grid {
  border-radius: 8px;
  background: #0f5ca6;
  padding: 12px;
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  gap: 12px;
}

.mini-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.mini-card {
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.12);
  padding: 12px 14px;
  color: #e6f1ff;
}

.mini-card span {
  display: block;
  font-size: 12px;
  opacity: 0.95;
}

.mini-card strong {
  display: block;
  margin-top: 4px;
  font-size: 18px;
  font-weight: 600;
}

.inline-offline-badge {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  color: #fbbf24;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 4px;
  padding: 1px 6px;
  margin-left: 6px;
  vertical-align: middle;
}

.cost-card {
  border-radius: 8px;
  background: #f9fbff;
  color: #0f4f96;
  padding: 16px;
  display: grid;
  place-content: center;
  text-align: center;
}

.cost-card p {
  margin: 0;
  font-size: 14px;
  color: #5f7288;
}

.cost-card h3 {
  margin: 10px 0 0;
  font-size: 44px;
  font-weight: 400;
  line-height: 1;
}

.cost-card small.cost-offline-note {
  display: block;
  margin-top: 8px;
  font-size: 11px;
  color: #b45309;
  font-weight: 500;
}

/* ---- doc row ---- */
.doc-row {
  margin-top: 12px;
  border: 1px solid #e4e9f2;
  border-radius: 8px;
  background: #f7f9fc;
  padding: 10px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.doc-card {
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #edf1f7;
  padding: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.ok {
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: #28a745;
  color: #ffffff;
  font-size: 14px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
}

.doc-card h4 {
  margin: 0;
  color: #334155;
  font-size: 16px;
  font-weight: 700;
}

.doc-card p {
  margin: 4px 0 0;
  color: #7a8798;
  font-size: 13px;
}

/* ---- actions ---- */
.action-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.action-btn {
  border-radius: 8px;
  height: 50px;
  border: 1px solid transparent;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.action-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 16px rgba(15, 23, 42, 0.12);
}

.action-btn.blue {
  color: #ffffff;
  background: #0f5ca6;
}

.action-btn.line {
  color: #0f5ca6;
  border-color: #0f5ca6;
  background: #ffffff;
}

.status {
  margin: 0;
  color: #4f698c;
  font-size: 14px;
}

/* ---- responsive ---- */
@media (max-width: 1200px) {
  .top-grid {
    grid-template-columns: 1fr;
  }
  .doc-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .mini-grid,
  .action-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .eua-price-grid {
    grid-template-columns: 1fr;
    gap: 14px;
  }
  .eua-price-detail {
    grid-template-columns: 1fr;
  }
  .eua-price-value {
    font-size: 26px;
  }
}
</style>
