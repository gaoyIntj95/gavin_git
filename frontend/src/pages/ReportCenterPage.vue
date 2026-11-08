<template>
  <section class="page-view report-page">
    <div class="type-row">
      <button
        v-for="item in types"
        :key="item.value"
        class="type-card"
        :class="{ active: activeType === item.value }"
        @click="activeType = item.value"
      >
        <span class="type-icon" :class="`icon-${item.value}`">{{ item.glyph }}</span>
        <span class="type-text">
          <strong>{{ item.label }}</strong>
          <small>{{ item.sub }}</small>
        </span>
      </button>
    </div>

    <div class="check-row">
      <span class="check-item">包含排放源明细清单</span>
      <span class="check-item">包含不确定性分析</span>
      <span class="check-item">包含减排路径建议</span>
    </div>

    <div class="summary-card">
      <div class="summary-block">
        <h4>项目概况（2025年度）</h4>
        <p>组织边界：运营控制法 | 基准年：2021年</p>
        <p>核算标准：ISO 14064-1:2018（GHG Protocol）</p>
      </div>
      <div class="summary-block">
        <h4>温室气体排放总量汇总</h4>
        <p>Scope 1: 107.8 t | Scope 2: 386.2 t</p>
        <p>年度总排放：494.0 tCO2e</p>
      </div>
    </div>

    <div class="action-row">
      <button class="action-btn blue" @click="generate">导出 Word 文档</button>
      <button class="action-btn blue" @click="download">导出 PDF 报告</button>
      <button class="action-btn gray" @click="saveTemplate">保存为常用模板</button>
    </div>

    <p class="status-tip">{{ statusTip }}</p>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { callApi } from '../composables/useApi'

type ReportType = 'inventory' | 'compliance' | 'cbam'

const projectId = ref(1)
const reportId = ref(1)
const activeType = ref<ReportType>('inventory')
const statusTip = ref('准备就绪。')

const types: Array<{ label: string; sub: string; value: ReportType; glyph: string }> = [
  { label: '碳盘查报告', sub: '符合 ISO14064 标准', value: 'inventory', glyph: '▦' },
  { label: '履约分析报告', sub: '配额缺口/盈余测算', value: 'compliance', glyph: '▣' },
  { label: 'CBAM 申报数据', sub: '出口产品碳足迹核算', value: 'cbam', glyph: '◼' },
]

async function generate() {
  const typeLabel = activeType.value === 'inventory'
    ? '碳盘查报告'
    : activeType.value === 'compliance'
      ? '履约分析报告'
      : 'CBAM 申报报告'
  await run(
    () => callApi(`/api/reports/${activeType.value}/${projectId.value}`, 'POST', {}),
    `${typeLabel}已生成。`,
  )
}

async function download() {
  await run(() => callApi(`/api/reports/${reportId.value}/download`), '下载链接已生成。')
}

function saveTemplate() {
  statusTip.value = '模板已保存为常用配置。'
}

async function run(action: () => Promise<unknown>, successMessage: string) {
  try {
    await action()
    statusTip.value = successMessage
  } catch {
    statusTip.value = '操作失败，请检查后端服务状态。'
  }
}
</script>

<style scoped>
.report-page {
  display: grid;
  gap: 12px;
}

.type-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.type-card {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  border: 1px solid #d8e0eb;
  border-radius: 8px;
  background: #f8fafd;
  padding: 14px 16px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.type-card:hover {
  border-color: #9ebce8;
  transform: translateY(-1px);
}

.type-card.active {
  border-color: #0f5ca6;
  background: #ffffff;
  box-shadow: 0 8px 14px rgba(15, 76, 155, 0.08);
}

.type-text strong {
  display: block;
  color: #243b57;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.25;
}

.type-text small {
  display: block;
  margin-top: 4px;
  color: #6a7b90;
  font-size: 14px;
  line-height: 1.2;
}

.type-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
}

.icon-inventory {
  background: #e7f1ff;
  color: #0f5ca6;
}

.icon-compliance {
  background: #f2eefb;
  color: #6d5fb1;
}

.icon-cbam {
  background: #e8f4ef;
  color: #1f7a5a;
}

.check-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafd;
  padding: 12px 14px;
}

.check-item {
  position: relative;
  padding-left: 24px;
  font-size: 16px;
  color: #334155;
  line-height: 1.35;
}

.check-item::before {
  content: "✓";
  position: absolute;
  left: 0;
  top: 0;
  width: 18px;
  height: 18px;
  border-radius: 999px;
  background: #0f5ca6;
  color: #ffffff;
  font-size: 11px;
  display: grid;
  place-items: center;
}

.summary-card {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  border: 1px solid #dce4ef;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.06);
  padding: 12px;
}

.summary-block {
  border-radius: 8px;
  background: #eef4fb;
  padding: 14px;
}

.summary-block h4 {
  margin: 0 0 8px;
  color: #0f4f96;
  font-size: 18px;
  font-weight: 700;
}

.summary-block p {
  margin: 0;
  color: #4a5c73;
  font-size: 16px;
  line-height: 1.5;
}

.action-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.action-btn {
  border: none;
  border-radius: 999px;
  height: 48px;
  color: #ffffff;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, filter 0.2s ease;
}

.action-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 14px rgba(15, 23, 42, 0.14);
  filter: brightness(1.03);
}

.action-btn.blue {
  background: #0f5ca6;
}

.action-btn.gray {
  background: #6b7280;
}

.status-tip {
  margin: 0;
  color: #516e92;
  font-size: 14px;
}

@media (max-width: 1180px) {
  .type-row,
  .check-row,
  .summary-card,
  .action-row {
    grid-template-columns: 1fr;
  }
}
</style>
