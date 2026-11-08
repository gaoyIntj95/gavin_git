<template>
  <div class="chat-chart-wrap">
    <div ref="chartRef" class="chat-chart-canvas"></div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts";

interface ChartItem {
  name: string;
  value: number;
}

interface ChartPayload {
  type?: string;
  chart_type?: string;
  title?: string;
  unit?: string;
  items?: ChartItem[];
}

const props = defineProps<{
  chart: ChartPayload;
}>();

const chartRef = ref<HTMLDivElement | null>(null);
let chartInstance: echarts.ECharts | null = null;

function buildOption(payload: ChartPayload): echarts.EChartsOption {
  const data = Array.isArray(payload.items) ? payload.items : [];
  const title = payload.title || "图表";
  const chartType = (payload.type || payload.chart_type || "pie").toLowerCase();

  if (chartType === "bar") {
    return {
      title: {
        text: title,
        left: "center",
        textStyle: { fontSize: 14, fontWeight: 600 },
      },
      tooltip: { trigger: "axis" },
      grid: { left: 40, right: 20, bottom: 30, top: 50, containLabel: true },
      xAxis: {
        type: "category",
        data: data.map((d) => d.name),
        axisLabel: { interval: 0, rotate: 25 },
      },
      yAxis: { type: "value", name: payload.unit || "值" },
      series: [
        {
          type: "bar",
          data: data.map((d) => d.value),
          barMaxWidth: 48,
        },
      ],
    };
  }

  if (chartType === "line") {
    return {
      title: {
        text: title,
        left: "center",
        textStyle: { fontSize: 14, fontWeight: 600 },
      },
      tooltip: { trigger: "axis" },
      grid: { left: 40, right: 20, bottom: 30, top: 50, containLabel: true },
      xAxis: {
        type: "category",
        data: data.map((d) => d.name),
        axisLabel: { interval: 0, rotate: 25 },
      },
      yAxis: { type: "value", name: payload.unit || "值" },
      series: [
        {
          type: "line",
          data: data.map((d) => d.value),
          smooth: true,
        },
      ],
    };
  }

  return {
    title: {
      text: title,
      left: "center",
      textStyle: { fontSize: 14, fontWeight: 600 },
    },
    tooltip: {
      trigger: "item",
      formatter: "{b}: {c} ({d}%)",
    },
    legend: {
      type: "scroll",
      orient: "vertical",
      right: 8,
      top: 24,
      bottom: 8,
    },
    series: [
      {
        name: payload.unit || "值",
        type: "pie",
        radius: ["35%", "65%"],
        center: ["38%", "55%"],
        avoidLabelOverlap: true,
        label: {
          show: true,
          formatter: "{b}\n{d}%",
          fontSize: 11,
        },
        labelLine: { show: true },
        data,
      },
    ],
  };
}

async function renderChart() {
  await nextTick();
  const el = chartRef.value;
  if (!el) return;
  if (!chartInstance) {
    chartInstance = echarts.init(el);
  }
  chartInstance.setOption(buildOption(props.chart), true);
  chartInstance.resize();
}

onMounted(() => {
  void renderChart();
});

watch(
  () => props.chart,
  () => {
    void renderChart();
  },
  { deep: true },
);

onBeforeUnmount(() => {
  if (chartInstance) {
    chartInstance.dispose();
    chartInstance = null;
  }
});
</script>

<style scoped>
.chat-chart-wrap {
  margin-top: 10px;
  border: 1px solid #dbe4f3;
  border-radius: 10px;
  background: #fff;
}

.chat-chart-canvas {
  width: 100%;
  height: 280px;
}
</style>
