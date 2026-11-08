<template>
  <section class="page-view chat-page">
    <article class="chat-shell">
            <section class="expert-status-bar">
        <div class="status-content">
          <div class="status-main">
            <div class="status-title-wrap">
              <p class="status-kicker">Carbon Expert Brain</p>
              <h3>双碳领域专家智能体在线</h3>
            </div>
            <p class="status-meta">
              已加载行业文档 <strong>{{ knowledgeDocs.length > 0 ? `${knowledgeDocs.length}+` : "10,000+" }}</strong>
              · 涵盖标准 ISO 14064 / GHG Protocol / CBAM / ESG · 最后更新 {{ latestUpdateText }}
            </p>
            <div class="kb-tags">
              <span v-for="tag in knowledgeTags" :key="tag" class="kb-tag">{{ tag }}</span>
            </div>
          </div>
        </div>
      </section>

      <div class="workspace">
        <aside class="core-sidebar">
          <div class="core-sidebar-head">
            <h3>核心功能</h3>
            <p>面向双碳业务全流程：政策洞察、核算落地、报告输出。</p>
          </div>
          <div class="core-feature-list">
            <article class="hero-feature-card">
              <span class="hero-feature-icon">📡</span>
              <h4>双碳政策雷达与红利解读</h4>
              <p>实时追踪国家/地方法规，精准解读补贴机会与合规风险。</p>
              <button
                class="hero-feature-action"
                type="button"
                @click="applyCapabilityTemplate('请解读最新双碳政策红利，并说明对我企业的影响与应对建议。')"
              >
                查看最新政策红利 →
              </button>
            </article>
            <article class="hero-feature-card">
              <span class="hero-feature-icon">🛡️</span>
              <h4>ISO/GHG 核算与可视化报告</h4>
              <p>内置国际标准算法，支持核算结果一键图表化与简版汇报输出。</p>
              <button
                class="hero-feature-action"
                type="button"
                @click="applyCapabilityTemplate('请基于 ISO 14064 与 GHG Protocol，帮我完成当前项目排放核算并生成可视化汇报要点。')"
              >
                开始核算与报告 →
              </button>
            </article>
            <article class="hero-feature-card">
              <span class="hero-feature-icon">💬</span>
              <h4>智能咨询问答</h4>
              <p>面向双碳业务场景进行多轮问答，自动检索依据并输出可执行建议。</p>
              <button
                class="hero-feature-action"
                type="button"
                @click="applyCapabilityTemplate('我想发起一次智能咨询，请根据我的问题给出结论、依据和可执行建议。')"
              >
                开始智能问答 →
              </button>
            </article>
          </div>
          <p class="core-trust-line">数据来源权威，更新及时。</p>
        </aside>

        <section class="consult-main">
        <section class="ask-panel">
          <h3>请开始您的咨询</h3>

          <textarea
            v-model="question"
            class="question-box question-box-primary"
            placeholder="请开始您的咨询（Enter 发送，Shift+Enter 换行）"
            @keydown="handleQuestionKeydown"
            @focus="isInputFocused = true"
            @blur="handleInputBlur"
          ></textarea>

          <div class="top-row">
            <div class="field-group">
              <label class="field-label">会话</label>
              <div ref="sessionDropdownRef" class="session-row">
                <button
                  class="field session-trigger"
                  type="button"
                  @click="toggleSessionMenu"
                  :title="currentSessionLabel"
                >
                  <span class="session-trigger-text">{{ currentSessionLabel }}</span>
                  <span class="session-trigger-arrow">{{
                    sessionMenuOpen ? "▴" : "▾"
                  }}</span>
                </button>
                <div v-if="sessionMenuOpen" class="session-menu">
                  <button
                    class="session-menu-item start-new"
                    type="button"
                    @click="selectSession('')"
                  >
                    开始新对话
                  </button>
                  <div
                    v-for="s in sessionList"
                    :key="s.session_id"
                    class="session-menu-row"
                  >
                    <button
                      class="session-menu-item"
                      type="button"
                      @click="selectSession(s.session_id)"
                    >
                      {{ sessionOptionLabel(s) }}
                    </button>
                    <button
                      v-if="canManage"
                      class="mini danger session-delete-btn"
                      :disabled="isLoading || deletingSessionId === s.session_id"
                      @click.stop="deleteSessionById(s.session_id)"
                    >
                      {{
                        deletingSessionId === s.session_id ? "删除中..." : "删除"
                      }}
                    </button>
                  </div>
                </div>
              </div>
              <p class="mode-hint">
                {{
                  selectedExistingSession
                    ? `当前会话ID：${selectedExistingSession}`
                    : "未选择历史会话，将在首次提问时自动创建会话ID并生成主题"
                }}
              </p>
            </div>
          </div>

          <div class="mode-row">
            <label class="field-label">咨询助手</label>
            <p class="mode-hint">
              单一入口自动路由：系统会根据你的问题自动识别是否需要关联项目并调用对应能力
            </p>
          </div>

          <div class="quick-top-area">
            <div class="quick-header">
              <h4>推荐提问</h4>
              <button
                v-if="quickQuestions.length === 0"
                class="link-btn"
                @click="loadQuickQuestions"
              >
                加载
              </button>
            </div>
            <div class="quick-pills">
              <button
                v-for="q in topQuickQuestions"
                :key="`top-${q.id}`"
                class="quick-pill"
                :class="{ active: question === q.question }"
                @click="pickQuestion(q.question)"
              >
                <span class="quick-category">{{ q.category }}</span>
                {{ q.question }}
              </button>
            </div>
          </div>

          <transition name="fade-slide">
            <div v-if="isInputFocused" class="smart-suggest-panel">
              <p class="smart-suggest-title">你可以这样问我</p>
              <div class="scenario-pills">
                <button
                  v-for="scenario in scenarioOptions"
                  :key="scenario.value"
                  class="scenario-pill"
                  :class="{ active: activeScenario === scenario.value }"
                  type="button"
                  @mousedown.prevent
                  @click="activeScenario = scenario.value"
                >
                  {{ scenario.label }}
                </button>
              </div>
              <div class="ability-pills">
                <button
                  v-for="item in capabilityTemplates"
                  :key="item.title"
                  class="ability-pill"
                  type="button"
                  @mousedown.prevent
                  @click="applyCapabilityTemplate(item.prompt)"
                >
                  {{ item.title }}
                </button>
              </div>
            </div>
          </transition>

          <div class="consult-input-tools">
            <select v-model="expertMode" class="field mode-select">
              <option value="auto">综合专家模式</option>
              <option value="accounting">核算专家模式</option>
              <option value="policy">政策专家模式</option>
              <option value="certification">认证专家模式</option>
            </select>
            <button class="secondary mini" @click="triggerFileUpload">上传资料</button>
          </div>

          <div class="format-row">
            <label class="field-label">输出偏好</label>
            <select v-model="answerStyle" class="field style-select">
              <option value="brief">管理层简版（结论优先）</option>
              <option value="standard">标准业务版（默认）</option>
              <option value="technical">技术详版（含口径说明）</option>
            </select>
          </div>

          <div class="action-row">
            <button class="primary" :disabled="isLoading" @click="ask">
              {{ isLoading ? "分析中..." : "立即咨询" }}
            </button>
            <button class="secondary" @click="loadHistory">查看会话历史</button>
            <button v-if="canManage" class="secondary" @click="deleteCurrentSession">
              删除当前会话
            </button>
          </div>

          <div class="quick-area">
            <div class="quick-header">
              <h4>更多问题</h4>
              <button v-if="restQuickQuestions.length" class="link-btn" @click="showMoreQuick = !showMoreQuick">
                {{ showMoreQuick ? "收起" : `展开更多（${restQuickQuestions.length}）` }}
              </button>
            </div>
            <div v-if="showMoreQuick && restQuickQuestions.length" class="quick-grid">
              <button
                v-for="q in restQuickQuestions"
                :key="q.id"
                class="quick-item"
                :class="{ active: question === q.question }"
                @click="pickQuestion(q.question)"
              >
                <span class="quick-category">{{ q.category }}</span>
                {{ q.question }}
              </button>
            </div>
            <p v-else class="mode-hint">已在上方展示高频推荐问题，可点击“展开更多”查看完整列表。</p>
          </div>
        </section>

        <section class="answer-panel">
          <div class="answer-head">
            <h3>助手输出</h3>
            <span class="answer-state" :class="{ loading: isLoading }">
              {{ isLoading ? "正在分析..." : "已就绪" }}
            </span>
          </div>
          <div ref="answerBoxRef" class="answer-box">
            <div v-if="chatTurns.length === 0" class="welcome-brief">
              <p class="brief-kicker">今日双碳资讯</p>
              <h4>{{ dailyBrief.title }}</h4>
              <p>{{ dailyBrief.summary }}</p>
              <ul>
                <li v-for="item in dailyBrief.topics" :key="item">{{ item }}</li>
              </ul>
              <div class="brief-action">
                <button class="mini secondary" @click="continueWithSuggestion('基于今日双碳资讯，给我3条可落地的管理建议。')">
                  基于资讯生成建议
                </button>
              </div>
            </div>
            <div
              v-for="(turn, idx) in chatTurns"
              :key="idx"
              class="chat-turn"
              :class="`turn-${turn.role}`"
            >
              <div class="turn-label">{{ turnLabel(turn.role) }}</div>
              <template v-if="turn.role === 'assistant'">
                <div class="report-view">
                  <div class="report-toolbar">
                    <button class="mini secondary" @click="copyAnswer(turn.content)">复制结论</button>
                    <button class="mini secondary" @click="continueWithSuggestion('请基于本轮结果，补充3条可执行治理建议。')">
                      继续深化建议
                    </button>
                  </div>
                  <div v-if="parseAnswerSections(turn.content).length" class="report-sections">
                    <article
                      v-for="section in parseAnswerSections(turn.content)"
                      :key="section.title"
                      class="report-card"
                    >
                      <h4>{{ section.title }}</h4>
                      <div class="turn-body compact" v-html="renderTurn(section.content)"></div>
                    </article>
                  </div>
                  <div v-else class="turn-body" v-html="renderTurn(turn.content)"></div>
                </div>
              </template>
              <div v-else class="turn-body" v-html="renderTurn(turn.content)"></div>
              <ChatTurnChart
                v-if="
                  turn.role === 'assistant' &&
                  turn.chart &&
                  Array.isArray((turn.chart as { items?: unknown[] }).items) &&
                  ((turn.chart as { items?: unknown[] }).items?.length || 0) > 0
                "
                :chart="turn.chart"
              />
              <div v-if="turn.references?.length" class="references">
                <span class="ref-label">参考来源：</span>
                <div v-if="turn.role === 'assistant'" class="evidence-tags">
                  <span
                    v-for="tag in buildEvidenceTags(turn)"
                    :key="tag"
                    class="evidence-tag"
                  >
                    #{{ tag }}
                  </span>
                </div>
                <a
                  v-for="(ref, refIdx) in turn.references"
                  :key="refIdx"
                  class="ref-tag"
                  :href="extractRefUrl(ref) || undefined"
                  :target="extractRefUrl(ref) ? '_blank' : undefined"
                  :rel="extractRefUrl(ref) ? 'noopener noreferrer' : undefined"
                >
                  {{ formatRefLabel(ref) }}
                </a>
              </div>
            </div>
          </div>
        </section>
        </section>
      </div>

      <section class="knowledge-section">
        <div class="knowledge-header">
          <h3>知识库管理</h3>
          <span class="doc-count"
            >已入库 {{ knowledgeDocs.length }} 份文档</span
          >
        </div>

        <div class="upload-row">
          <input
            ref="fileInputRef"
            type="file"
            accept=".pdf,.docx,.doc,.txt,.md,.csv,.xls,.xlsx"
            class="file-input"
            @change="handleFileSelect"
          />
          <button class="upload-btn" @click="triggerFileUpload">
            📤 上传文档
          </button>
          <span class="upload-hint">支持 PDF / Word / Excel / TXT</span>
          <button class="secondary mini" @click="loadKnowledgeDocs">
            刷新列表
          </button>
        </div>

        <div v-if="knowledgeDocs.length" class="doc-list">
          <div v-for="doc in knowledgeDocs" :key="doc.id" class="doc-item">
            <span class="doc-icon">{{ docIcon(doc.file_type) }}</span>
            <div class="doc-info">
              <span class="doc-name">{{ doc.filename }}</span>
              <span class="doc-meta"
                >{{ doc.chunk_count }} 个分块 ·
                {{ docStatusText(doc.status) }}</span
              >
            </div>
            <button v-if="canManage" class="mini danger" @click="deleteDoc(doc.id)">删除</button>
          </div>
        </div>
        <p v-else class="empty-hint">暂无文档，请上传专业知识文档构建知识库</p>
      </section>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { callApi } from "../composables/useApi";
import ChatTurnChart from "../components/ChatTurnChart.vue";

function simpleMarkdown(text: string): string {
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  html = html.replace(/^### (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^## (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^# (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/`(.+?)`/g, "<code>$1</code>");
  html = html.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/^\d+\.\s+(.+)$/gm, "<li>$1</li>");
  html = html.replace(/((?:<li>.*<\/li>\s*)+)/gs, "<ul>$1</ul>");
  html = html.replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>',
  );
  html = html.replace(/\n{2,}/g, "</p><p>");
  html = html.replace(/\n/g, "<br>");
  html = `<p>${html}</p>`;
  return html;
}

interface QuickQuestion {
  id: number;
  question: string;
  category: string;
}

interface SessionItem {
  session_id: string;
  name: string;
  mode: string;
  project_id: number | null;
  created_at: string;
  updated_at: string;
}

interface ProjectOption {
  id: number;
  name: string;
}

interface KnowledgeDoc {
  id: number;
  filename: string;
  file_type: string;
  chunk_count: number;
  status: string;
  created_at: string;
}

interface ChatMessage {
  question: string;
  answer: string;
  references: string[];
  chart?: Record<string, unknown> | null;
  mode: string;
  project_id: number | null;
  created_at: string;
}

interface AskResponse {
  answer: string;
  references: string[];
  chart?: Record<string, unknown> | null;
  mode: string;
}

interface SessionMessagesResponse {
  messages: ChatMessage[];
}

interface NewsListItem {
  id: number;
  title: string;
  published_at?: string | null;
  summary?: string | null;
  source_name?: string | null;
  source_url?: string | null;
}

interface NewsListResponse {
  data?: NewsListItem[];
}

interface ChatTurn {
  role: "user" | "assistant" | "system";
  content: string;
  references?: string[];
  chart?: Record<string, unknown> | null;
}

interface AnswerSection {
  title: string;
  content: string;
}

const sessionId = ref("");
const selectedExistingSession = ref("");
const question = ref("企业如何界定碳盘查的组织边界？");
const result = ref("等待咨询...");
const isLoading = ref(false);
const chatTurns = ref<ChatTurn[]>([]);

const quickQuestions = ref<QuickQuestion[]>([]);
const sessionList = ref<SessionItem[]>([]);
const projectOptions = ref<ProjectOption[]>([]);
const knowledgeDocs = ref<KnowledgeDoc[]>([]);
const fileInputRef = ref<HTMLInputElement | null>(null);
const answerBoxRef = ref<HTMLElement | null>(null);
const sessionDropdownRef = ref<HTMLElement | null>(null);
const sessionMenuOpen = ref(false);
const isInputFocused = ref(false);
const deletingSessionId = ref("");
const newsRefreshTimer = ref<number | null>(null);
const pendingProjectQuestion = ref("");
const pendingProjectCandidates = ref<ProjectOption[]>([]);
const activeScenario = ref<"auto" | "policy" | "analysis" | "method">("auto");
const answerStyle = ref<"brief" | "standard" | "technical">("standard");
const expertMode = ref<"auto" | "accounting" | "policy" | "certification">("auto");
const showMoreQuick = ref(false);
const knowledgeTags = [
  "ISO 14064",
  "GHG Protocol",
  "CBAM",
  "CCER",
  "ESG",
  "碳足迹",
  "碳盘查",
  "绿色制造",
];

const topQuickQuestions = computed(() => quickQuestions.value.slice(0, 6));
const restQuickQuestions = computed(() => quickQuestions.value.slice(6));
const liveNewsHints = ref([
  { title: "园区零碳建设方案更新", time: "2小时前", url: "" },
  { title: "工业节能降碳行动通知", time: "今日", url: "" },
  { title: "碳市场履约价格波动监测", time: "实时", url: "" },
]);
const recommendedTopics = [
  "帮我解读本周零碳园区政策变化",
  "请基于ISO口径分析项目1排放结构",
  "给我一份碳足迹认证流程清单",
];
const dailyBrief = {
  title: "政策与市场同步走强，园区减排进入精细化阶段",
  summary:
    "今日重点集中在园区低碳改造、碳市场履约优化与企业核算口径统一，建议优先关注数据可追溯与治理闭环。",
  topics: [
    "多地发布零碳园区评价指引，强调实施路径与指标体系。",
    "重点行业履约成本优化成为近期企业咨询高频需求。",
    "核算标准与业务台账一体化是当前落地关键。",
  ],
};
const latestUpdateText = computed(() => {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
});
const scenarioOptions = [
  { value: "auto", label: "智能路由" },
  { value: "policy", label: "政策速览" },
  { value: "analysis", label: "排放分析" },
  { value: "method", label: "方法解读" },
] as const;
const capabilityTemplates = [
  { title: "最新政策解读", prompt: "请检索近30天双碳相关政策，按“核心变化-影响-建议动作”输出。" },
  { title: "项目排放诊断", prompt: "请基于当前项目给出总量、Scope结构、Top排放源及治理优先级建议。" },
  { title: "图表化表达", prompt: "请把关键结果用图表展示，并附一段简洁业务解读。" },
  { title: "报告草稿生成", prompt: "请按“总览-数据-结论-建议”生成可直接汇报的草稿。" },
];
const canManage = computed(() => {
  const token = localStorage.getItem("access_token");
  if (!token) return false;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return String(payload?.role || "").toLowerCase() === "admin";
  } catch {
    return false;
  }
});

const currentSessionLabel = computed(() => {
  if (!selectedExistingSession.value) return "开始新对话";
  const target = sessionList.value.find(
    (s) => s.session_id === selectedExistingSession.value,
  );
  return target ? sessionOptionLabel(target) : selectedExistingSession.value;
});

const selectedSessionProjectId = computed<number | null>(() => {
  if (!selectedExistingSession.value) return null;
  const target = sessionList.value.find(
    (s) => s.session_id === selectedExistingSession.value,
  );
  return target?.project_id ?? null;
});

function parseExplicitProjectId(text: string): number | null {
  const rules = [
    /项目\s*id\s*[:：]?\s*(\d+)/i,
    /project\s*id\s*[:：]?\s*(\d+)/i,
    /项目\s*(\d{1,6})/i,
    /\bID\s*[:：]?\s*(\d{1,6})\b/i,
  ];

  for (const rule of rules) {
    const match = text.match(rule);
    if (!match) continue;
    const id = Number(match[1]);
    if (Number.isInteger(id) && id > 0) return id;
  }
  return null;
}

function hasProjectIntent(text: string): boolean {
  const normalized = text.toLowerCase();
  const keywords = [
    "项目",
    "scope",
    "排放",
    "碳盘查",
    "排放源",
    "核算",
    "活动数据",
    "emission",
  ];
  return keywords.some((keyword) => normalized.includes(keyword));
}

function resolveProjectIdForQuestion(text: string): number | null {
  const explicitId = parseExplicitProjectId(text);
  if (explicitId && projectOptions.value.some((p) => p.id === explicitId)) {
    return explicitId;
  }

  const byName = projectOptions.value.find((p) => text.includes(p.name));
  if (byName) return byName.id;

  if (selectedSessionProjectId.value) {
    return selectedSessionProjectId.value;
  }

  if (hasProjectIntent(text) && projectOptions.value.length === 1) {
    return projectOptions.value[0].id;
  }

  return null;
}

function findProjectCandidates(text: string): ProjectOption[] {
  const normalized = text.trim().toLowerCase();
  if (!normalized) return [];
  return projectOptions.value.filter((project) => {
    const name = project.name.trim().toLowerCase();
    return normalized.includes(name) || name.includes(normalized);
  });
}

function buildProjectDisambiguationMessage(candidates: ProjectOption[]): string {
  const optionsText = candidates
    .slice(0, 8)
    .map((project) => `${project.id} - ${project.name}`)
    .join("\n");
  return [
    "检测到你的问题需要项目数据，但当前无法唯一识别项目。",
    "请回复项目 ID 或项目名称（例如：`项目 1` 或 `示范能源制造有限公司2021年度温室气体盘查`）：",
    optionsText,
  ].join("\n\n");
}

function docIcon(type: string) {
  const icons: Record<string, string> = {
    pdf: "📄",
    docx: "📝",
    doc: "📝",
    txt: "📃",
    md: "📃",
    csv: "📊",
    xls: "📊",
    xlsx: "📊",
  };
  return icons[type] || "📎";
}

function docStatusText(status: string) {
  const map: Record<string, string> = {
    processing: "处理中",
    completed: "已完成",
    failed: "失败",
    empty: "内容为空",
  };
  return map[status] || status;
}

function pickQuestion(value: string) {
  question.value = value;
}

function applyCapabilityTemplate(prompt: string) {
  question.value = prompt;
}

function handleInputBlur() {
  window.setTimeout(() => {
    isInputFocused.value = false;
  }, 120);
}

function turnLabel(role: ChatTurn["role"]) {
  if (role === "user") return "你";
  if (role === "assistant") return "助手";
  return "系统";
}

function renderTurn(text: string) {
  return simpleMarkdown(text);
}

function parseAnswerSections(text: string): AnswerSection[] {
  const normalized = String(text || "").replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const sections: AnswerSection[] = [];
  let currentTitle = "";
  let buffer: string[] = [];

  const flush = () => {
    if (!currentTitle || buffer.length === 0) return;
    sections.push({
      title: currentTitle,
      content: buffer.join("\n").trim(),
    });
    buffer = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    const titleMatch = line.match(/^(?:\d+\.\s*)?(总览|分项|结论|建议)\s*[:：]?$/);
    if (titleMatch) {
      flush();
      currentTitle = titleMatch[1];
      continue;
    }
    if (!currentTitle) continue;
    buffer.push(rawLine);
  }
  flush();
  return sections.filter((s) => s.content.trim().length > 0);
}

async function copyAnswer(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    pushSystemMessage("已复制本轮结论。");
  } catch {
    pushSystemMessage("复制失败，请手动复制。");
  }
}

function continueWithSuggestion(prompt: string) {
  question.value = prompt;
}

function buildEvidenceTags(turn: ChatTurn): string[] {
  const refs = turn.references || [];
  const tags = new Set<string>();
  const text = String(turn.content || "");
  if (/ISO\s*14064/i.test(text)) tags.add("ISO14064");
  if (/GHG\s*Protocol/i.test(text)) tags.add("GHG Protocol");
  if (/CBAM/i.test(text)) tags.add("CBAM");
  if (/CCER/i.test(text)) tags.add("CCER");
  if (/碳价|碳市场/.test(text)) tags.add("实时碳价数据");

  refs.forEach((raw) => {
    const ref = String(raw || "");
    const sourceMatch = ref.match(/资讯来源[:：]\s*([^|]+)/);
    if (sourceMatch?.[1]) {
      tags.add(sourceMatch[1].trim());
    } else if (/ISO\s*14064/i.test(ref)) {
      tags.add("ISO14064");
    } else if (/GHG/i.test(ref)) {
      tags.add("GHG Protocol");
    }
  });
  return Array.from(tags).slice(0, 6);
}

function extractRefUrl(ref: string): string | null {
  const match = String(ref || "").match(/https?:\/\/\S+/);
  return match ? match[0] : null;
}

function formatRefLabel(ref: string): string {
  const raw = String(ref || "").trim();
  const url = extractRefUrl(raw);
  if (!url) return raw;
  return raw.replace(url, "").replace(/\|\s*$/, "").trim() || "点击查看来源";
}

function formatNewsTime(raw?: string | null): string {
  if (!raw) return "最近";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "最近";
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  if (diff < 60 * 60 * 1000) return "1小时内";
  if (diff < 24 * 60 * 60 * 1000) return `${Math.max(1, Math.floor(diff / (60 * 60 * 1000)))}小时前`;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

async function loadLiveNewsRadar() {
  try {
    const res = await callApi<NewsListResponse>("/api/news/list?page=1&page_size=3&time_window=1w");
    const list = Array.isArray(res?.data) ? res.data : [];
    if (list.length === 0) return;
    liveNewsHints.value = list.slice(0, 3).map((item) => ({
      title: item.title || "双碳行业资讯",
      time: formatNewsTime(item.published_at),
      url: item.source_url || "",
    }));
  } catch {
    // keep fallback hints
  }
}

function openLiveNews(url?: string) {
  const target = String(url || "").trim();
  if (!target) return;
  window.open(target, "_blank", "noopener,noreferrer");
}

function pushSystemMessage(content: string) {
  chatTurns.value.push({ role: "system", content });
}

async function scrollToLatestMessage() {
  await nextTick();
  const box = answerBoxRef.value;
  if (!box) return;
  box.scrollTop = box.scrollHeight;
}

function handleQuestionKeydown(event: KeyboardEvent) {
  if (event.isComposing) return;
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (isLoading.value) return;
    void ask();
  }
}

function sessionOptionLabel(session: SessionItem) {
  if (!session.name || session.name.trim() === "") return session.session_id;
  if (session.name === session.session_id) return session.session_id;
  return `${session.name}（${session.session_id}）`;
}

function generateSessionId() {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const datePart = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const timePart = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const randPart = Math.random().toString(36).slice(2, 6);
  return `chat_${datePart}_${timePart}_${randPart}`;
}

async function switchSession() {
  if (!selectedExistingSession.value) {
    sessionId.value = "";
    result.value = "等待咨询...";
    chatTurns.value = [];
    return;
  }
  sessionId.value = selectedExistingSession.value;
  await loadHistory();
}

function toggleSessionMenu() {
  sessionMenuOpen.value = !sessionMenuOpen.value;
}

async function selectSession(targetSessionId: string) {
  selectedExistingSession.value = targetSessionId;
  sessionMenuOpen.value = false;
  await switchSession();
}

function handleSessionDropdownOutsideClick(event: MouseEvent) {
  const root = sessionDropdownRef.value;
  const target = event.target as Node | null;
  if (!root || !target) return;
  if (!root.contains(target)) {
    sessionMenuOpen.value = false;
  }
}

async function ask() {
  const askTextRaw = question.value.trim();
  if (!askTextRaw) return;
  const styleHintMap = {
    brief: "请用管理层可读的简洁风格回答，先结论后依据。",
    standard: "请用业务可读风格回答，结构清晰，结论与建议并重。",
    technical: "请用技术详版回答，包含关键口径说明与必要边界条件。",
  } as const;
  const scenarioHintMap = {
    auto: "",
    policy: "优先进行政策/资讯检索，并标注来源与时间。",
    analysis: "优先进行项目数据分析，给出量化结果与图表建议。",
    method: "优先给出标准方法解读，并补充适用边界与实践要点。",
  } as const;
  const expertModeHintMap = {
    auto: "按综合专家模式回答，必要时自动调用资讯与业务数据能力。",
    accounting: "按核算专家模式回答，强调口径、边界与量化结论。",
    policy: "按政策专家模式回答，强调时效、来源与影响解读。",
    certification: "按认证专家模式回答，强调流程、材料与审核要点。",
  } as const;
  const askText = [
    askTextRaw,
    "",
    `【回答风格】${styleHintMap[answerStyle.value]}`,
    `【专家模式】${expertModeHintMap[expertMode.value]}`,
    scenarioHintMap[activeScenario.value]
      ? `【任务模式】${scenarioHintMap[activeScenario.value]}`
      : "",
  ]
    .filter(Boolean)
    .join("\n");
  isLoading.value = true;
  try {
    let activeSessionId = sessionId.value.trim();
    if (selectedExistingSession.value) {
      activeSessionId = selectedExistingSession.value;
    }
    if (!activeSessionId) {
      activeSessionId = generateSessionId();
    }
    sessionId.value = activeSessionId;

    if (pendingProjectQuestion.value) {
      chatTurns.value.push({ role: "user", content: askText });
      const selectedId =
        resolveProjectIdForQuestion(askText) ??
        pendingProjectCandidates.value.find((p) => askText.includes(p.name))?.id ??
        null;
      if (!selectedId) {
        pushSystemMessage(
          "还未识别到有效项目，请直接回复项目 ID 或完整项目名称。",
        );
        question.value = "";
        return;
      }

      const selectedProject = projectOptions.value.find((p) => p.id === selectedId);
      if (selectedProject) {
        pushSystemMessage(`已识别项目：${selectedProject.name}（ID: ${selectedId}），继续分析原问题。`);
      }
      const payload: Record<string, unknown> = {
        session_id: activeSessionId,
        question: pendingProjectQuestion.value,
        mode: "auto",
        project_id: selectedId,
      };

      pendingProjectQuestion.value = "";
      pendingProjectCandidates.value = [];
      const res = await callApi<AskResponse>("/api/chat/ask", "POST", payload);
      result.value = res.answer;
      chatTurns.value.push({
        role: "assistant",
        content: res.answer,
        references: res.references || [],
        chart: res.chart || null,
      });
      await loadSessionList();
      selectedExistingSession.value = activeSessionId;
      question.value = "";
      return;
    }

    const payload: Record<string, unknown> = {
      session_id: activeSessionId,
      question: askText,
      mode: "auto",
    };
    const autoProjectId = resolveProjectIdForQuestion(askText);
    if (autoProjectId) {
      payload.project_id = autoProjectId;
    } else if (hasProjectIntent(askText) && projectOptions.value.length > 1) {
      const matchedCandidates = findProjectCandidates(askText);
      if (matchedCandidates.length === 1) {
        payload.project_id = matchedCandidates[0].id;
      } else {
        const candidates =
          matchedCandidates.length > 1 ? matchedCandidates : projectOptions.value;
        chatTurns.value.push({ role: "user", content: askText });
        pendingProjectQuestion.value = askText;
        pendingProjectCandidates.value = candidates;
        pushSystemMessage(buildProjectDisambiguationMessage(candidates));
        question.value = "";
        return;
      }
    }
    chatTurns.value.push({ role: "user", content: askText });
    const res = await callApi<AskResponse>("/api/chat/ask", "POST", payload);
    result.value = res.answer;
    chatTurns.value.push({
      role: "assistant",
      content: res.answer,
      references: res.references || [],
      chart: res.chart || null,
    });
    await loadSessionList();
    selectedExistingSession.value = activeSessionId;
    question.value = "";
  } catch (error) {
    result.value = `请求失败: ${error instanceof Error ? error.message : String(error)}`;
    pushSystemMessage(result.value);
  } finally {
    isLoading.value = false;
  }
}

async function loadHistory() {
  isLoading.value = true;
  try {
    const res = await callApi<SessionMessagesResponse>(
      `/api/chat/sessions/${sessionId.value}`,
    );
    if (res.messages.length === 0) {
      result.value = "暂无历史消息";
      chatTurns.value = [];
      pushSystemMessage("暂无历史消息");
    } else {
      const last = res.messages[res.messages.length - 1];
      result.value = last.answer;
      chatTurns.value = res.messages.flatMap((m) => [
        { role: "user", content: m.question } as ChatTurn,
        {
          role: "assistant",
          content: m.answer,
          references: m.references || [],
          chart: m.chart || null,
        } as ChatTurn,
      ]);
    }
  } catch (error) {
    result.value = `加载历史失败: ${error instanceof Error ? error.message : String(error)}`;
    pushSystemMessage(result.value);
  } finally {
    isLoading.value = false;
  }
}

async function deleteCurrentSession() {
  const currentSessionId = selectedExistingSession.value || sessionId.value;
  if (!currentSessionId.trim()) {
    result.value = "当前没有可删除的会话";
    pushSystemMessage(result.value);
    return;
  }
  await deleteSessionById(currentSessionId);
}

async function deleteSessionById(targetSessionId: string) {
  if (!window.confirm(`确认删除会话 ${targetSessionId} 吗？`)) return;
  deletingSessionId.value = targetSessionId;
  try {
    await callApi(`/api/chat/sessions/${targetSessionId}`, "DELETE");

    if (
      sessionId.value === targetSessionId ||
      selectedExistingSession.value === targetSessionId
    ) {
      sessionId.value = "";
      selectedExistingSession.value = "";
      sessionMenuOpen.value = false;
      result.value = "等待咨询...";
      chatTurns.value = [];
    }

    await loadSessionList();
    pushSystemMessage(`会话已删除：${targetSessionId}`);
  } catch (error) {
    result.value = `删除失败: ${error instanceof Error ? error.message : String(error)}`;
    pushSystemMessage(result.value);
  } finally {
    deletingSessionId.value = "";
  }
}

async function loadQuickQuestions() {
  try {
    const res = await callApi<{ questions: QuickQuestion[] }>(
      "/api/chat/quick-questions",
    );
    quickQuestions.value = res.questions || [];
  } catch {
    quickQuestions.value = [
      {
        id: 1,
        question: "企业如何界定碳盘查的组织边界？",
        category: "核算标准",
      },
      { id: 2, question: "Scope 1/2/3 的定义和区别？", category: "基础概念" },
      { id: 3, question: "CBAM 申报需要准备哪些材料？", category: "CBAM" },
    ];
  }
}

async function loadSessionList() {
  try {
    const res = await callApi<{ sessions: SessionItem[] }>(
      "/api/chat/sessions",
    );
    sessionList.value = res.sessions || [];
  } catch {
    sessionList.value = [];
  }
}

async function loadProjectOptions() {
  try {
    const projects =
      await callApi<Array<{ id: number; name: string }>>("/api/projects");
    projectOptions.value = projects.map((p) => ({ id: p.id, name: p.name }));
  } catch {
    projectOptions.value = [];
  }
}

async function loadKnowledgeDocs() {
  try {
    const res = await callApi<{ documents: KnowledgeDoc[] }>(
      "/api/chat/knowledge/documents",
    );
    knowledgeDocs.value = res.documents || [];
  } catch {
    knowledgeDocs.value = [];
  }
}

function triggerFileUpload() {
  fileInputRef.value?.click();
}

async function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);

  isLoading.value = true;
  try {
    const res = await callApi<KnowledgeUploadResponse>(
      "/api/chat/knowledge/upload",
      "POST",
      formData,
    );
    result.value = `文档上传成功！\n\n文件名: ${res.filename}\n分块数: ${res.chunk_count}\n状态: ${docStatusText(res.status)}`;
    pushSystemMessage(result.value);
    await loadKnowledgeDocs();
  } catch (error) {
    result.value = `上传失败: ${error instanceof Error ? error.message : String(error)}`;
    pushSystemMessage(result.value);
  } finally {
    isLoading.value = false;
    target.value = "";
  }
}

async function deleteDoc(docId: number) {
  if (!window.confirm("确认删除此文档？")) return;
  try {
    await callApi(`/api/chat/knowledge/documents/${docId}`, "DELETE");
    await loadKnowledgeDocs();
    pushSystemMessage("文档已删除并刷新列表");
  } catch (error) {
    result.value = `删除失败: ${error instanceof Error ? error.message : String(error)}`;
    pushSystemMessage(result.value);
  }
}

interface KnowledgeUploadResponse {
  document_id: number;
  filename: string;
  chunk_count: number;
  status: string;
}

onMounted(async () => {
  document.addEventListener("click", handleSessionDropdownOutsideClick);
  await Promise.all([
    loadQuickQuestions(),
    loadSessionList(),
    loadProjectOptions(),
    loadKnowledgeDocs(),
    loadLiveNewsRadar(),
  ]);
  newsRefreshTimer.value = window.setInterval(() => {
    void loadLiveNewsRadar();
  }, 120000);
});

onBeforeUnmount(() => {
  document.removeEventListener("click", handleSessionDropdownOutsideClick);
  if (newsRefreshTimer.value !== null) {
    window.clearInterval(newsRefreshTimer.value);
    newsRefreshTimer.value = null;
  }
});

watch(
  () => chatTurns.value.length,
  () => {
    void scrollToLatestMessage();
  },
);
</script>

<style scoped>
.chat-shell {
  border: 1px solid #d5deec;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}

.chat-head {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  background: linear-gradient(100deg, #0a4da6 0%, #0e63c4 48%, #338dff 100%);
  color: #ffffff;
  padding: 14px 18px;
}

.chat-head::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(
    180deg,
    rgba(255, 255, 255, 0.18) 0%,
    rgba(255, 255, 255, 0) 45%
  );
  pointer-events: none;
}

.chat-head h2 {
  position: relative;
  z-index: 1;
  margin: 0;
  font-size: 24px;
  font-weight: 800;
}

.chat-head p {
  position: relative;
  z-index: 1;
  margin: 2px 0 0;
  font-size: 12px;
  color: rgba(224, 239, 255, 0.95);
}

.head-icon {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.25);
  box-shadow: 0 0 18px rgba(147, 197, 253, 0.55);
  font-size: 12px;
}

.workspace {
  display: grid;
  grid-template-columns: minmax(280px, 0.3fr) minmax(0, 0.7fr);
  gap: 14px;
  padding: 14px;
  align-items: stretch;
}

.expert-status-bar {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border-bottom: 1px solid #e2eaf6;
  background:
    radial-gradient(circle at 90% 10%, rgba(59, 130, 246, 0.2), transparent 35%),
    linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
}

.status-content {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  align-items: start;
}

.consult-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  grid-template-rows: 1fr;
  gap: 12px;
  min-width: 0;
  align-items: stretch;
}

.core-sidebar {
  border: 1px solid #d2dced;
  border-radius: 8px;
  background: #ffffff;
  padding: 12px;
  display: grid;
  align-content: start;
  gap: 10px;
}

.core-sidebar-head h3 {
  margin: 0;
  font-size: 16px;
  color: #0f172a;
}

.core-sidebar-head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: #64748b;
}

.core-feature-list {
  display: grid;
  gap: 8px;
}

.core-trust-line {
  margin: 2px 0 0;
  font-size: 12px;
  color: #4b6285;
}

.status-main h3 {
  margin: 0;
  color: #0f2f66;
  font-size: 17px;
}

.status-kicker {
  margin: 0 0 4px;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #4f77ad;
}

.status-meta {
  margin: 4px 0 8px;
  font-size: 12px;
  color: #4b6285;
}

.kb-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.kb-tag {
  border: 1px solid #cfe0fb;
  border-radius: 999px;
  background: #f6faff;
  color: #1d4e89;
  font-size: 11px;
  padding: 3px 8px;
}


.ask-panel,
.answer-panel {
  border: 1px solid #d2dced;
  border-radius: 8px;
  background: #ffffff;
  padding: 14px;
}

.ask-panel {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.ask-panel h3,
.answer-head h3 {
  margin: 0 0 10px;
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.hero-feature-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  align-self: start;
}

.hero-feature-card {
  border: 1px solid #cfe0fb;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.82);
  padding: 8px 10px;
  display: grid;
  gap: 4px;
}

.hero-feature-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #edf4ff;
  display: grid;
  place-items: center;
  font-size: 13px;
}

.hero-feature-card h4 {
  margin: 0;
  color: #1d2129;
  font-size: 14px;
  line-height: 1.35;
}

.hero-feature-card p {
  margin: 0;
  color: #6b7280;
  font-size: 11px;
  line-height: 1.4;
  min-height: 30px;
}

.hero-feature-action {
  border: 1px solid #d3e1f8;
  border-radius: 8px;
  background: #ffffff;
  color: #1f4f90;
  font-size: 12px;
  padding: 5px 8px;
  text-align: left;
  cursor: pointer;
}

.hero-feature-action:hover {
  background: #f4f8ff;
  border-color: #afc9ee;
}

.format-row {
  margin-bottom: 10px;
}

.scenario-pills,
.ability-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.scenario-pill,
.ability-pill {
  border: 1px solid #cfe0fb;
  background: #f8fbff;
  color: #1b4f9c;
  border-radius: 999px;
  font-size: 12px;
  padding: 5px 10px;
  cursor: pointer;
}

.scenario-pill.active {
  background: #1f66d1;
  border-color: #1f66d1;
  color: #fff;
}

.style-select {
  width: 100%;
}

.consult-input-tools {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.smart-suggest-panel {
  margin-top: 8px;
  border: 1px solid #d8e5f8;
  border-radius: 10px;
  background: linear-gradient(180deg, #f8fbff 0%, #f0f6ff 100%);
  padding: 10px;
  display: grid;
  gap: 8px;
}

.smart-suggest-title {
  margin: 0;
  font-size: 12px;
  color: #4a6286;
  font-weight: 600;
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.18s ease;
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.mode-select {
  flex: 1;
}

.field-group {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.field-label {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.session-row {
  position: relative;
  min-width: 0;
  width: 100%;
  max-width: 100%;
  overflow: visible;
}

.session-trigger {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  overflow: hidden;
  box-sizing: border-box;
}

.session-trigger-text {
  flex: 1;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.session-trigger-arrow {
  color: #64748b;
  font-size: 12px;
}

.session-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  width: 100%;
  max-width: 100%;
  z-index: 30;
  max-height: 300px;
  overflow-y: auto;
  border: 1px solid #cfd9ea;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.14);
  padding: 6px;
}

.session-menu-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
}

.session-menu-item {
  width: 100%;
  border: 1px solid #d7e1f0;
  border-radius: 6px;
  background: #ffffff;
  text-align: left;
  color: #0f172a;
  font-size: 13px;
  line-height: 1.35;
  padding: 7px 9px;
  cursor: pointer;
  white-space: normal;
  word-break: break-word;
}

.session-menu-item:hover {
  border-color: #9fbfee;
  background: #f5f9ff;
}

.session-menu-item.start-new {
  margin-bottom: 6px;
  font-weight: 600;
}

.session-delete-btn {
  min-width: 52px;
}

.mode-row {
  margin-top: 10px;
  display: grid;
  gap: 6px;
}

.mode-hint {
  margin: 0;
  font-size: 12px;
  color: #94a3b8;
}

.top-row {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.question-box {
  width: 100%;
  min-height: 100px;
  margin-top: 10px;
  border: 1px solid #cfd9ea;
  border-radius: 8px;
  background: #ffffff;
  color: #0f172a;
  padding: 12px;
  font-size: 15px;
  outline: none;
  resize: vertical;
}

.question-box:focus {
  border-color: #6ea2eb;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.14);
}

.question-box-primary {
  min-height: 132px;
  margin-top: 0;
  border-color: #9ebbe8;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

.quick-top-area {
  margin-top: 10px;
  border: 1px solid #d2dced;
  border-radius: 8px;
  background: linear-gradient(180deg, #fbfdff 0%, #f4f8ff 100%);
  padding: 10px;
}

.quick-pills {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.quick-pill {
  width: 100%;
  border: 1px solid #d2dced;
  border-radius: 999px;
  background: #ffffff;
  text-align: left;
  color: #1e293b;
  padding: 7px 10px;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.quick-pill:hover {
  border-color: #96baf0;
  background: #f3f8ff;
}

.quick-pill.active {
  border-color: #7ea9ea;
  background: #edf5ff;
}

.action-row {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.quick-area {
  margin-top: 12px;
  border: 1px solid #d2dced;
  border-radius: 8px;
  background: linear-gradient(180deg, #fbfdff 0%, #f4f8ff 100%);
  padding: 12px;
}

.quick-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.quick-area h4 {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
}

.link-btn {
  border: none;
  background: none;
  color: #2563eb;
  cursor: pointer;
  font-size: 13px;
}

.quick-grid {
  display: grid;
  gap: 6px;
}

.quick-item {
  width: 100%;
  border: 1px solid #d2dced;
  border-radius: 8px;
  background: #ffffff;
  text-align: left;
  color: #1e293b;
  padding: 8px 11px;
  font-size: 14px;
  transition: all 0.2s ease;
}

.quick-item:hover {
  border-color: #96baf0;
  background: #f3f8ff;
}

.quick-item.active {
  border-color: #7ea9ea;
  background: #edf5ff;
  box-shadow: inset 0 0 0 1px rgba(126, 169, 234, 0.2);
}

.quick-category {
  display: inline-block;
  border-radius: 4px;
  background: #eef4fb;
  color: #3b6ea5;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  margin-right: 6px;
}

.answer-panel {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.answer-head {
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.answer-state {
  border: 1px solid #d4deec;
  border-radius: 999px;
  background: #f0f6ff;
  color: #3e6fae;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
}

.answer-state.loading {
  background: #fef3c7;
  color: #92400e;
  border-color: #fcd34d;
}

.answer-box {
  flex: 1;
  min-height: 460px;
  border: 1px solid #d5deec;
  border-radius: 8px;
  background: #fcfdff;
  color: #334155;
  font-size: 14px;
  line-height: 1.7;
  padding: 14px;
  overflow-y: auto;
  max-height: 620px;
}

.report-view {
  display: grid;
  gap: 8px;
}

.report-toolbar {
  display: flex;
  gap: 8px;
}

.report-sections {
  display: grid;
  gap: 8px;
}

.report-card {
  border: 1px solid #d7e5f8;
  border-radius: 8px;
  background: #f8fbff;
  padding: 8px 10px;
}

.report-card h4 {
  margin: 0 0 4px;
  font-size: 13px;
  color: #0b4ca8;
}

.turn-body.compact :deep(p) {
  margin: 4px 0;
}

.answer-box :deep(p) {
  margin: 0 0 8px;
}

.answer-box :deep(.placeholder) {
  color: #94a3b8;
  font-style: italic;
}

.welcome-brief {
  border: 1px solid #d7e5f8;
  border-radius: 10px;
  background: linear-gradient(180deg, #f7fbff 0%, #edf5ff 100%);
  padding: 12px;
  margin-bottom: 10px;
}

.welcome-brief h4 {
  margin: 4px 0;
  color: #0f3d80;
}

.brief-kicker {
  margin: 0;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #4d6f9e;
}

.welcome-brief p {
  margin: 4px 0;
  font-size: 13px;
  color: #27466f;
}

.welcome-brief ul {
  margin: 6px 0 0;
  padding-left: 18px;
  color: #315780;
  font-size: 12px;
}

.brief-action {
  margin-top: 10px;
}

.chat-turn {
  margin-bottom: 12px;
  border-radius: 8px;
  padding: 10px 12px;
}

.turn-user {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.turn-assistant {
  background: #f8fafc;
  border: 1px solid #dbe7f7;
}

.turn-system {
  background: #fff7ed;
  border: 1px solid #fed7aa;
}

.turn-label {
  font-size: 12px;
  font-weight: 700;
  color: #475569;
  margin-bottom: 6px;
}

.turn-body :deep(p) {
  margin: 0 0 6px;
}

.references {
  margin-top: 8px;
  display: grid;
  gap: 8px;
}

.insight-panel {
  display: grid;
  gap: 10px;
  align-content: start;
}

.insight-card {
  border: 1px solid #d2dced;
  border-radius: 8px;
  background: #fff;
  padding: 12px;
}

.insight-card h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #0f2f66;
}

.insight-card ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}

.insight-card li {
  border: 1px solid #deebfb;
  border-radius: 8px;
  background: #f7fbff;
  padding: 8px;
  display: grid;
  gap: 2px;
}

.insight-card li.clickable {
  cursor: pointer;
  transition: all 0.18s ease;
}

.insight-card li.clickable:hover {
  background: #edf5ff;
  border-color: #b5d1f5;
  transform: translateY(-1px);
}

.insight-card li strong {
  font-size: 12px;
  color: #1e3f70;
}

.insight-card li span {
  font-size: 11px;
  color: #6b7f9b;
}

.topic-list {
  display: grid;
  gap: 8px;
}

.topic-pill {
  border: 1px solid #d3e2f7;
  border-radius: 8px;
  background: #f8fbff;
  color: #1f4f90;
  text-align: left;
  font-size: 12px;
  padding: 8px;
  cursor: pointer;
}

.topic-pill:hover {
  background: #eef5ff;
  border-color: #a9c6ef;
}

.ref-label {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 2px;
}

.evidence-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.evidence-tag {
  border: 1px solid #cfe0fb;
  border-radius: 999px;
  background: #f5f9ff;
  color: #1f4e91;
  font-size: 11px;
  padding: 2px 8px;
}

.ref-tag {
  display: block;
  border: 1px solid #c7d8ef;
  border-radius: 10px;
  background: linear-gradient(180deg, #f8fbff 0%, #edf4ff 100%);
  color: #245a97;
  font-size: 12px;
  line-height: 1.5;
  padding: 8px 10px;
  text-decoration: none;
  transition: all 0.18s ease;
}

.ref-tag:hover {
  border-color: #8cb4ea;
  background: linear-gradient(180deg, #f1f7ff 0%, #e8f1ff 100%);
  color: #1e4d83;
  transform: translateY(-1px);
}

.knowledge-section {
  border-top: 1px solid #e2e8f0;
  padding: 14px;
}

.knowledge-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.knowledge-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.doc-count {
  font-size: 13px;
  color: #64748b;
}

.upload-row {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.file-input {
  display: none;
}

.upload-btn {
  border: 1px solid #2563eb;
  border-radius: 8px;
  background: #2563eb;
  color: #ffffff;
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.upload-btn:hover {
  background: #1d4ed8;
}

.upload-hint {
  font-size: 12px;
  color: #94a3b8;
}

.doc-list {
  margin-top: 10px;
  display: grid;
  gap: 6px;
}

.doc-item {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
  padding: 10px 12px;
}

.doc-icon {
  font-size: 20px;
}

.doc-info {
  flex: 1;
  min-width: 0;
}

.doc-name {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-meta {
  display: block;
  font-size: 12px;
  color: #64748b;
}

.empty-hint {
  margin: 10px 0 0;
  font-size: 13px;
  color: #94a3b8;
}

button {
  border-radius: 0.75rem;
  height: 2.5rem;
  padding: 0 1rem;
  font-size: 0.875rem;
  cursor: pointer;
}

.field {
  border: 1px solid #cfd7e3;
  border-radius: 8px;
  min-height: 40px;
  padding: 8px 10px;
}

.primary {
  border: 1px solid #1d4ed8;
  background: #2563eb;
  color: #fff;
}

.primary:hover {
  background: #1d4ed8;
}

.primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.secondary {
  border: 1px solid #93c5fd;
  background: #f8fbff;
  color: #1d4ed8;
}

.secondary:hover {
  background: #eff6ff;
}

.mini {
  height: 1.9rem;
  padding: 0 0.7rem;
  font-size: 12px;
  border-radius: 0.5rem;
}

.danger {
  border: 1px solid #dc2626;
  background: #dc2626;
  color: #fff;
}

.danger:hover {
  background: #b91c1c;
}

@media (max-width: 1180px) {
  .workspace {
    grid-template-columns: 1fr;
  }

  .consult-main {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
  }

  .status-content {
    grid-template-columns: 1fr;
  }

  .answer-box {
    min-height: 360px;
    max-height: 70vh;
  }

  .insight-panel {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 860px) {
  .top-row,
  .session-row {
    grid-template-columns: 1fr;
  }

  .hero-feature-grid {
    grid-template-columns: 1fr;
  }

  .quick-pills {
    grid-template-columns: 1fr;
  }
}
</style>

