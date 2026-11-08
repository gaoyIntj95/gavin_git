<template>
  <LoginPage v-if="!isLoggedIn" />

  <div v-else class="app-bg min-h-screen text-slate-900">
    <div
      class="mx-auto grid max-w-[1780px] grid-cols-1 gap-6 px-4 py-6 md:px-6 lg:grid-cols-[300px_1fr] lg:py-8"
    >
      <aside class="sidebar-shell relative overflow-hidden rounded-2xl p-4">
        <div
          class="pointer-events-none absolute inset-0 opacity-20"
          style="
            background-image: url(&quot;https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=700&q=80&quot;);
            background-size: cover;
            background-position: center;
          "
        ></div>
        <div class="pointer-events-none absolute inset-0 bg-slate-900/20"></div>

        <div class="relative z-10">
          <div class="sidebar-brand">
            <span class="brand-accent" aria-hidden="true"></span>
            <div>
              <p class="brand-name">智碳管家</p>
              <p class="brand-en">CARBON AI SYSTEM</p>
            </div>
          </div>

          <div class="mt-4 space-y-2">
            <button
              v-for="item in navItems"
              :key="item.key"
              class="group relative flex w-full items-center gap-3 rounded-xl border px-3 py-3 text-left text-[15px] font-medium transition-all duration-200"
              :class="
                activePage === item.key
                  ? 'border-cyan-300/70 bg-blue-500/50 text-white shadow-[0_0_18px_rgba(56,189,248,0.35)]'
                  : 'border-transparent bg-blue-900/45 text-blue-50/90 hover:border-cyan-200/40 hover:bg-blue-800/55'
              "
              @click="activePage = item.key"
            >
              <span
                class="absolute left-0 top-1/2 h-7 w-1 -translate-y-1/2 rounded-r bg-cyan-200 transition-opacity duration-200"
                :class="
                  activePage === item.key
                    ? 'opacity-100'
                    : 'opacity-0 group-hover:opacity-60'
                "
              ></span>
              <span
                class="grid h-8 w-8 place-items-center rounded-lg bg-white/15 text-sm"
                >{{ item.icon }}</span
              >
              <span>{{ item.label }}</span>
            </button>
          </div>

        </div>
      </aside>

      <main class="min-w-0 space-y-3">
        <header class="top-banner">
          <div class="info-block">
            <p class="page-title">{{ pageIntro.title }}</p>
            <p class="page-subtitle">{{ pageIntro.subtitle }}</p>
          </div>

          <div class="brand-block">
            <p class="brand-kicker">AI Carbon Intelligence Platform</p>
            <h1 class="brand-title">AI智碳管家</h1>
            <p class="brand-sub">智能双碳管理中枢</p>
          </div>

          <div class="tag-block">
            <div ref="userMenuRef" class="user-menu-wrap">
              <button class="user-card" type="button" @click="toggleUserMenu">
              <span class="user-icon">{{ roleMeta.icon }}</span>
              <div class="user-meta">
                <p class="user-name">{{ currentUser.username }}</p>
                <p class="user-role">{{ roleMeta.label }}</p>
              </div>
              <span class="user-caret">{{ userMenuOpen ? "▴" : "▾" }}</span>
              </button>
              <div v-if="userMenuOpen" class="user-dropdown">
                <button class="user-menu-item" @click="openProfile">个人中心</button>
                <button class="user-menu-item" @click="openPassword">修改密码</button>
                <button
                  v-if="currentUser.role === 'admin'"
                  class="user-menu-item"
                  @click="openUserCreate"
                >
                  注册账号
                </button>
                <button
                  v-if="currentUser.role === 'admin'"
                  class="user-menu-item"
                  @click="openResetPassword"
                >
                  重置用户密码
                </button>
                <button class="user-menu-item danger" @click="logout">退出登录</button>
              </div>
            </div>
            <div class="highlight-group">
              <span
                v-for="tag in pageIntro.highlights"
                :key="tag"
                class="highlight-pill"
                >{{ tag }}</span
              >
            </div>
          </div>
        </header>

        <component :is="currentPage" />
      </main>
    </div>

    <div v-if="profileModalOpen" class="modal-mask" @click.self="profileModalOpen = false">
      <div class="modal-card">
        <div class="modal-head">
          <h3>个人中心</h3>
          <button class="modal-close" @click="profileModalOpen = false">关闭</button>
        </div>
        <div class="modal-body">
          <p><strong>用户名：</strong>{{ currentUser.username }}</p>
          <p><strong>角色：</strong>{{ roleMeta.label }}</p>
          <p><strong>权限标识：</strong>{{ currentUser.role }}</p>
          <hr class="modal-divider" />
          <form @submit.prevent="submitUsernameChange">
            <label class="modal-label">
              新用户名
              <input v-model="usernameForm.newUsername" type="text" class="modal-input" />
            </label>
            <label class="modal-label">
              当前密码确认
              <input v-model="usernameForm.currentPassword" type="password" class="modal-input" />
            </label>
            <p v-if="usernameError" class="modal-error">{{ usernameError }}</p>
            <div class="modal-actions">
              <button type="submit" class="modal-btn primary" :disabled="usernameSubmitting">
                {{ usernameSubmitting ? "提交中..." : "修改用户名" }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <div
      v-if="passwordModalOpen"
      class="modal-mask"
      @click.self="closePasswordModal"
    >
      <div class="modal-card">
        <div class="modal-head">
          <h3>修改密码</h3>
          <button class="modal-close" @click="closePasswordModal">关闭</button>
        </div>
        <form class="modal-body" @submit.prevent="submitPasswordChange">
          <label class="modal-label">
            当前密码
            <input v-model="passwordForm.current" type="password" class="modal-input" />
          </label>
          <label class="modal-label">
            新密码
            <input v-model="passwordForm.next" type="password" class="modal-input" />
          </label>
          <label class="modal-label">
            确认新密码
            <input v-model="passwordForm.confirm" type="password" class="modal-input" />
          </label>
          <p v-if="passwordError" class="modal-error">{{ passwordError }}</p>
          <div class="modal-actions">
            <button type="button" class="modal-btn ghost" @click="closePasswordModal">取消</button>
            <button type="submit" class="modal-btn primary" :disabled="passwordSubmitting">
              {{ passwordSubmitting ? "提交中..." : "确认修改" }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <div v-if="createUserModalOpen" class="modal-mask" @click.self="closeUserCreate">
      <div class="modal-card">
        <div class="modal-head">
          <h3>管理员注册账号</h3>
          <button class="modal-close" @click="closeUserCreate">关闭</button>
        </div>
        <form class="modal-body" @submit.prevent="submitUserCreate">
          <label class="modal-label">
            用户名
            <input v-model="createUserForm.username" type="text" class="modal-input" />
          </label>
          <label class="modal-label">
            密码
            <input v-model="createUserForm.password" type="password" class="modal-input" />
          </label>
          <label class="modal-label">
            角色
            <select v-model="createUserForm.role" class="modal-input">
              <option value="user">业务用户</option>
              <option value="auditor">审计人员</option>
              <option value="admin">系统管理员</option>
            </select>
          </label>
          <label class="modal-label">
            昵称（可选）
            <input v-model="createUserForm.nickname" type="text" class="modal-input" />
          </label>
          <p v-if="createUserError" class="modal-error">{{ createUserError }}</p>
          <div class="modal-actions">
            <button type="button" class="modal-btn ghost" @click="closeUserCreate">取消</button>
            <button type="submit" class="modal-btn primary" :disabled="createUserSubmitting">
              {{ createUserSubmitting ? "创建中..." : "创建账号" }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <div v-if="resetPasswordModalOpen" class="modal-mask" @click.self="closeResetPassword">
      <div class="modal-card">
        <div class="modal-head">
          <h3>管理员重置密码</h3>
          <button class="modal-close" @click="closeResetPassword">关闭</button>
        </div>
        <form class="modal-body" @submit.prevent="submitResetPassword">
          <label class="modal-label">
            目标用户名
            <input v-model="resetPasswordForm.username" type="text" class="modal-input" />
          </label>
          <label class="modal-label">
            新密码
            <input v-model="resetPasswordForm.newPassword" type="password" class="modal-input" />
          </label>
          <p v-if="resetPasswordError" class="modal-error">{{ resetPasswordError }}</p>
          <div class="modal-actions">
            <button type="button" class="modal-btn ghost" @click="closeResetPassword">取消</button>
            <button type="submit" class="modal-btn primary" :disabled="resetPasswordSubmitting">
              {{ resetPasswordSubmitting ? "提交中..." : "确认重置" }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { callApi } from "./composables/useApi";
import LoginPage from "./pages/LoginPage.vue";
import CarbonCalculationPage from "./pages/CarbonCalculationPage.vue";
import CarbonMarketPage from "./pages/CarbonMarketPage.vue";
import CbamHelperPage from "./pages/CbamHelperPage.vue";
import ChatAssistantPage from "./pages/ChatAssistantPage.vue";
import HomeDashboard from "./pages/HomeDashboard.vue";
import ProjectManagementPage from "./pages/ProjectManagementPage.vue";
import ReportCenterPage from "./pages/ReportCenterPage.vue";
import TimeseriesForecastPage from "./pages/TimeseriesForecastPage.vue";

interface CurrentUser {
  username: string;
  role: string;
}

const pages = {
  home: HomeDashboard,
  projects: ProjectManagementPage,
  calculation: CarbonCalculationPage,
  chat: ChatAssistantPage,
  reports: ReportCenterPage,
  market: CarbonMarketPage,
  cbam: CbamHelperPage,
  timeseries: TimeseriesForecastPage,
};

type PageKey = keyof typeof pages;

const navItems: Array<{ key: PageKey; icon: string; label: string }> = [
  { key: "home", icon: "H", label: "首页工作台" },
  { key: "projects", icon: "P", label: "项目管理" },
  { key: "calculation", icon: "C", label: "碳盘查核算" },
  { key: "chat", icon: "Q", label: "智碳咨询" },
  { key: "reports", icon: "R", label: "报告管理" },
  { key: "market", icon: "M", label: "碳市场履约" },
  { key: "cbam", icon: "E", label: "CBAM 申报" },
  { key: "timeseries", icon: "T", label: "时序情景预测" },
];

const pageIntroMap: Record<
  PageKey,
  { title: string; subtitle: string; highlights: string[] }
> = {
  home: {
    title: "首页工作台",
    subtitle: "关键排放指标、履约风险与近期任务一屏掌控",
    highlights: ["总览数据", "任务提醒", "趋势分析"],
  },
  projects: {
    title: "项目管理",
    subtitle: "统一维护组织边界、基准年与核算标准，保障数据可追溯",
    highlights: ["项目建档", "边界管理", "标准统一"],
  },
  calculation: {
    title: "碳盘查核算",
    subtitle: "批量导入排放源并自动核算，快速完成盘查结果汇总",
    highlights: ["数据校验", "自动核算", "报告输出"],
  },
  chat: {
    title: "智碳咨询助手",
    subtitle: "围绕双碳业务场景提供问答支持，提升决策效率",
    highlights: ["快捷问答", "会话历史", "结果追踪"],
  },
  reports: {
    title: "报告管理",
    subtitle: "生成、导出、沉淀各类合规报告，形成标准化报告资产",
    highlights: ["多报告类型", "导出模板", "归档复用"],
  },
  market: {
    title: "碳市场履约",
    subtitle: "测算配额缺口并优化履约路径，辅助控制年度履约成本",
    highlights: ["成本测算", "方案对比", "履约建议"],
  },
  cbam: {
    title: "CBAM 申报",
    subtitle: "聚焦出口产品碳足迹与申报资料，降低跨境贸易风险",
    highlights: ["税费预估", "资料检查", "风险提示"],
  },
  timeseries: {
    title: "时序情景预测",
    subtitle: "录入天然气与外购电能耗数据，执行6/12个月碳排放预测与履约预警",
    highlights: ["能耗录入", "趋势预测", "履约缺口预判"],
  },
};

const activePage = ref<PageKey>("home");
const currentPage = computed(() => pages[activePage.value]);
const pageIntro = computed(() => pageIntroMap[activePage.value]);
const isLoggedIn = ref(false);
const currentUser = ref<CurrentUser>({ username: "", role: "user" });
const userMenuOpen = ref(false);
const userMenuRef = ref<HTMLElement | null>(null);
const profileModalOpen = ref(false);
const passwordModalOpen = ref(false);
const createUserModalOpen = ref(false);
const resetPasswordModalOpen = ref(false);
const passwordSubmitting = ref(false);
const passwordError = ref("");
const passwordForm = ref({ current: "", next: "", confirm: "" });
const usernameSubmitting = ref(false);
const usernameError = ref("");
const usernameForm = ref({ newUsername: "", currentPassword: "" });
const createUserSubmitting = ref(false);
const createUserError = ref("");
const createUserForm = ref({
  username: "",
  password: "",
  role: "user",
  nickname: "",
});
const resetPasswordSubmitting = ref(false);
const resetPasswordError = ref("");
const resetPasswordForm = ref({ username: "", newPassword: "" });
const roleMeta = computed(() => {
  const role = (currentUser.value.role || "").toLowerCase();
  if (role === "admin") return { icon: "A", label: "系统管理员" };
  if (role === "auditor") return { icon: "U", label: "审计人员" };
  return { icon: "B", label: "业务用户" };
});

function checkAuth() {
  const token = localStorage.getItem("access_token");
  if (token) {
    try {
      const payload = JSON.parse(atob(token.split(".")[1]));
      currentUser.value = {
        username: payload.sub,
        role: payload.role,
      };
      isLoggedIn.value = true;
    } catch {
      logout();
    }
  }
}

function logout() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("remember");
  isLoggedIn.value = false;
  currentUser.value = { username: "", role: "user" };
  activePage.value = "home";
  userMenuOpen.value = false;
}

function toggleUserMenu() {
  userMenuOpen.value = !userMenuOpen.value;
}

function closeUserMenuOnOutsideClick(event: MouseEvent) {
  const root = userMenuRef.value;
  const target = event.target as Node | null;
  if (!root || !target) return;
  if (!root.contains(target)) userMenuOpen.value = false;
}

function openProfile() {
  userMenuOpen.value = false;
  profileModalOpen.value = true;
  usernameError.value = "";
  usernameForm.value = { newUsername: currentUser.value.username, currentPassword: "" };
}

function openPassword() {
  userMenuOpen.value = false;
  passwordModalOpen.value = true;
  passwordError.value = "";
}

function openUserCreate() {
  userMenuOpen.value = false;
  createUserModalOpen.value = true;
  createUserError.value = "";
}

function openResetPassword() {
  userMenuOpen.value = false;
  resetPasswordModalOpen.value = true;
  resetPasswordError.value = "";
}

function closePasswordModal() {
  passwordModalOpen.value = false;
  passwordError.value = "";
  passwordForm.value = { current: "", next: "", confirm: "" };
}

function closeUserCreate() {
  createUserModalOpen.value = false;
  createUserError.value = "";
  createUserForm.value = { username: "", password: "", role: "user", nickname: "" };
}

function closeResetPassword() {
  resetPasswordModalOpen.value = false;
  resetPasswordError.value = "";
  resetPasswordForm.value = { username: "", newPassword: "" };
}

async function submitPasswordChange() {
  passwordError.value = "";
  const { current, next, confirm } = passwordForm.value;
  if (!current || !next || !confirm) {
    passwordError.value = "请完整填写密码信息";
    return;
  }
  if (next.length < 6) {
    passwordError.value = "新密码至少 6 位";
    return;
  }
  if (next !== confirm) {
    passwordError.value = "两次输入的新密码不一致";
    return;
  }
  passwordSubmitting.value = true;
  try {
    await callApi<{ message: string }>("/api/auth/change-password", "POST", {
      current_password: current,
      new_password: next,
    });
    closePasswordModal();
    window.alert("密码修改成功，请重新登录");
    logout();
  } catch (error) {
    passwordError.value =
      error instanceof Error ? error.message : "修改失败，请稍后重试";
  } finally {
    passwordSubmitting.value = false;
  }
}

async function submitUsernameChange() {
  usernameError.value = "";
  const { newUsername, currentPassword } = usernameForm.value;
  if (!newUsername.trim() || !currentPassword) {
    usernameError.value = "请填写新用户名和当前密码";
    return;
  }
  usernameSubmitting.value = true;
  try {
    await callApi<{ message: string; username: string }>("/api/auth/change-username", "POST", {
      new_username: newUsername.trim(),
      current_password: currentPassword,
    });
    profileModalOpen.value = false;
    window.alert("用户名修改成功，请重新登录");
    logout();
  } catch (error) {
    usernameError.value = error instanceof Error ? error.message : "修改失败，请稍后重试";
  } finally {
    usernameSubmitting.value = false;
  }
}

async function submitUserCreate() {
  createUserError.value = "";
  const { username, password, role, nickname } = createUserForm.value;
  if (!username.trim() || !password) {
    createUserError.value = "请填写用户名和密码";
    return;
  }
  if (password.length < 6) {
    createUserError.value = "密码至少 6 位";
    return;
  }
  createUserSubmitting.value = true;
  try {
    await callApi("/api/auth/admin/users", "POST", {
      username: username.trim(),
      password,
      role,
      nickname: nickname.trim() || null,
    });
    closeUserCreate();
    window.alert("账号创建成功");
  } catch (error) {
    createUserError.value = error instanceof Error ? error.message : "创建失败，请稍后重试";
  } finally {
    createUserSubmitting.value = false;
  }
}

async function submitResetPassword() {
  resetPasswordError.value = "";
  const { username, newPassword } = resetPasswordForm.value;
  if (!username.trim() || !newPassword) {
    resetPasswordError.value = "请填写用户名和新密码";
    return;
  }
  if (newPassword.length < 6) {
    resetPasswordError.value = "新密码至少 6 位";
    return;
  }
  resetPasswordSubmitting.value = true;
  try {
    await callApi<{ message: string; username: string }>("/api/auth/admin/reset-password", "POST", {
      username: username.trim(),
      new_password: newPassword,
    });
    closeResetPassword();
    window.alert("密码重置成功");
  } catch (error) {
    resetPasswordError.value = error instanceof Error ? error.message : "重置失败，请稍后重试";
  } finally {
    resetPasswordSubmitting.value = false;
  }
}

onMounted(() => {
  checkAuth();
  document.addEventListener("click", closeUserMenuOnOutsideClick);
});

onBeforeUnmount(() => {
  document.removeEventListener("click", closeUserMenuOnOutsideClick);
});

defineExpose({
  currentUser,
});
</script>

<style scoped>
.app-bg {
  background: linear-gradient(135deg, #e8f3ff 0%, #f4f9ff 45%, #edf6ff 100%);
}

.sidebar-shell {
  background: linear-gradient(180deg, #0b2340 0%, #0d365f 58%, #0b2b4b 100%);
  border: 1px solid rgba(56, 189, 248, 0.24);
  box-shadow:
    0 18px 38px rgba(6, 30, 58, 0.3),
    inset 0 0 0 1px rgba(56, 189, 248, 0.18);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 8px;
  background: linear-gradient(
    135deg,
    rgba(16, 39, 71, 0.66) 0%,
    rgba(17, 44, 78, 0.54) 100%
  );
  box-shadow: 0 8px 16px rgba(5, 20, 44, 0.22);
  backdrop-filter: blur(2px);
  padding: 12px 12px 12px 10px;
}

.brand-accent {
  width: 3px;
  height: 30px;
  border-radius: 99px;
  background: linear-gradient(180deg, #8de7ff 0%, #42bddf 100%);
  box-shadow: 0 0 10px rgba(80, 204, 240, 0.32);
}

.brand-name {
  margin: 0;
  color: #d9f4ff;
  font-size: 25px;
  font-weight: 700;
  line-height: 1.08;
}

.brand-en {
  margin: 4px 0 0;
  color: rgba(168, 219, 238, 0.72);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.14em;
}

.top-banner {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  border: 1px solid #cfe0f5;
  border-radius: 8px;
  background: linear-gradient(
    90deg,
    rgba(255, 255, 255, 0.95) 0%,
    rgba(238, 246, 255, 0.96) 55%,
    rgba(255, 255, 255, 0.96) 100%
  );
  box-shadow:
    0 8px 18px rgba(15, 23, 42, 0.08),
    inset 0 0 0 1px rgba(255, 255, 255, 0.75);
  padding: 10px 14px;
}

.info-block {
  width: min(100%, 520px);
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 3px;
  padding: 4px 0 4px 12px;
  border-left: 3px solid #a9c7ef;
  justify-self: center;
}

.page-title {
  margin: 0;
  color: #174988;
  font-size: 28px;
  font-weight: 800;
  line-height: 1.15;
}

.page-subtitle {
  margin: 0;
  font-size: 14px;
  color: #365781;
  line-height: 1.4;
  max-width: 520px;
}

.brand-block {
  padding: 6px 12px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  justify-self: center;
}

.brand-kicker {
  margin: 0 auto 4px;
  width: fit-content;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  background: #eff6ff;
  color: #1e5da8;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 3px 9px;
}

.brand-title {
  margin: 0;
  font-size: 44px;
  line-height: 1.02;
  font-weight: 900;
  letter-spacing: 0;
  color: #0f2242;
  text-shadow:
    0 1px 0 rgba(255, 255, 255, 0.5),
    0 8px 20px rgba(33, 86, 156, 0.16);
}

.brand-sub {
  margin: 4px 0 0;
  font-size: 13px;
  color: #50729b;
  text-align: center;
}

.tag-block {
  min-width: 300px;
  max-width: 340px;
  display: grid;
  align-content: start;
  justify-self: end;
  width: 100%;
  gap: 8px;
  border: 1px solid #d2e1f7;
  border-radius: 10px;
  background: linear-gradient(180deg, #f8fbff 0%, #f1f6ff 100%);
  padding: 8px;
}

.highlight-pill {
  border: 1px solid #c8ddfb;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  color: #335e97;
  font-size: 11px;
  font-weight: 700;
  min-width: 86px;
  text-align: center;
  padding: 3px 8px;
  line-height: 1.2;
}

.highlight-group {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.user-menu-wrap {
  position: relative;
  width: 100%;
  max-width: none;
}

.user-card {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: 1px solid #c9dcf6;
  border-radius: 10px;
  background: linear-gradient(135deg, #f4f9ff 0%, #e9f2ff 100%);
  padding: 7px 10px;
  box-shadow: 0 4px 10px rgba(18, 66, 122, 0.08);
  text-align: left;
  cursor: pointer;
  border: 1px solid #c9dcf6;
}

.user-card:hover {
  border-color: #9ec2f0;
}

.user-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: #dcecff;
  font-size: 16px;
}

.user-meta {
  min-width: 0;
  flex: 1;
}

.user-name {
  margin: 0;
  color: #174988;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  margin: 2px 0 0;
  color: #4d6f9b;
  font-size: 11px;
  line-height: 1.2;
}

.user-caret {
  color: #5b7fa9;
  font-size: 11px;
  margin-left: 2px;
}

.user-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  width: 180px;
  border: 1px solid #c8dbf5;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 12px 20px rgba(13, 43, 80, 0.14);
  overflow: hidden;
  z-index: 50;
}

.user-menu-item {
  width: 100%;
  height: 38px;
  border: none;
  border-bottom: 1px solid #eef4fd;
  background: #ffffff;
  color: #2c588c;
  font-size: 13px;
  font-weight: 600;
  text-align: left;
  padding: 0 12px;
}

.user-menu-item:last-child {
  border-bottom: none;
}

.user-menu-item:hover {
  background: #f3f8ff;
}

.user-menu-item.danger {
  color: #b42318;
}

.user-menu-item.danger:hover {
  background: #fff1f0;
}

.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(8, 20, 38, 0.4);
  display: grid;
  place-items: center;
  padding: 16px;
}

.modal-card {
  width: min(100%, 440px);
  border: 1px solid #c9dcf5;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 18px 32px rgba(12, 40, 75, 0.2);
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid #e3eefb;
}

.modal-head h3 {
  margin: 0;
  color: #173f72;
  font-size: 16px;
  font-weight: 800;
}

.modal-close {
  border: 1px solid #c8daf3;
  background: #f6faff;
  color: #28588f;
  height: 30px;
  padding: 0 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
}

.modal-body {
  padding: 14px;
  color: #1f3d61;
  font-size: 14px;
}

.modal-divider {
  border: none;
  border-top: 1px solid #e8f1fc;
  margin: 10px 0 12px;
}

.modal-label {
  display: grid;
  gap: 6px;
  margin-bottom: 10px;
  color: #2a4e7d;
  font-size: 13px;
  font-weight: 600;
}

.modal-input {
  border: 1px solid #c9dcf5;
  border-radius: 8px;
  height: 38px;
  padding: 0 10px;
  font-size: 14px;
  color: #1b3553;
  background: #fafdff;
}

.modal-error {
  margin: 4px 0 0;
  color: #b42318;
  font-size: 13px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}

.modal-btn {
  height: 34px;
  border-radius: 8px;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 700;
}

.modal-btn.ghost {
  border: 1px solid #c4d8f2;
  background: #f6faff;
  color: #2d5f98;
}

.modal-btn.primary {
  border: 1px solid #1f66bd;
  background: #2b79d8;
  color: #fff;
}

@media (max-width: 1280px) {
  .brand-title {
    font-size: 38px;
  }

  .page-title {
    font-size: 24px;
  }
}

@media (max-width: 980px) {
  .top-banner {
    grid-template-columns: 1fr;
    gap: 10px;
    padding: 10px 12px;
  }

  .brand-block,
  .info-block,
  .tag-block {
    text-align: center;
  }

  .info-block {
    border-left: none;
    padding-left: 0;
    align-items: center;
  }

  .brand-kicker {
    margin-left: auto;
    margin-right: auto;
  }

  .tag-block {
    justify-items: center;
    max-width: 100%;
    min-width: 0;
  }

  .highlight-group {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    width: 100%;
  }
}
</style>


