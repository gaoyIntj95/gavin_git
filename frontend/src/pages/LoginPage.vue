<template>
  <div
    class="login-wrapper min-h-screen flex items-center justify-center relative overflow-hidden"
  >
    <div
      class="absolute inset-0 opacity-15"
      style="
        background-image: url(&quot;https://images.unsplash.com/photo-1473341304170-971dccb5ac1e?auto=format&fit=crop&w=1920&q=80&quot;);
        background-size: cover;
        background-position: center;
      "
    ></div>

    <div
      class="absolute inset-0 bg-gradient-to-br from-slate-900/95 via-blue-900/90 to-teal-900/95"
    ></div>

    <div class="absolute inset-0">
      <div
        v-for="i in 20"
        :key="i"
        class="tech-line"
        :style="{
          left: `${Math.random() * 100}%`,
          top: `${Math.random() * 100}%`,
          width: `${Math.random() * 300 + 50}px`,
          height: '1px',
          transform: `rotate(${Math.random() * 360}deg)`,
          animationDelay: `${Math.random() * 3}s`,
        }"
      ></div>
    </div>

    <div class="relative z-10 w-full max-w-[420px] px-4">
      <div
        class="login-card rounded-2xl shadow-2xl overflow-hidden border border-white/10 backdrop-blur-sm"
      >
        <div class="login-header p-8 pb-6">
          <p class="login-kicker">AI Carbon Intelligence Platform</p>
          <div class="flex items-center justify-center gap-3 mb-3">
            <div class="logo-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 2L2 7L12 12L22 7L12 2Z"
                  stroke="currentColor"
                  stroke-width="2.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
                <path
                  d="M2 17L12 22L22 17"
                  stroke="currentColor"
                  stroke-width="2.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
                <path
                  d="M2 12L12 17L22 12"
                  stroke="currentColor"
                  stroke-width="2.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </div>
            <h1 class="login-title">AI智碳管家</h1>
          </div>
          <p class="login-subtitle">智能双碳管理中枢 · 统一业务工作台</p>
        </div>

        <div class="login-body p-8 pt-0">
          <form @submit.prevent="handleLogin" class="space-y-5">
            <div>
              <label class="field-label" for="username">用户名</label>
              <div class="input-wrapper">
                <input
                  id="username"
                  v-model="form.username"
                  type="text"
                  class="login-input"
                  placeholder="请输入用户名"
                  autocomplete="username"
                />
                <span class="input-icon">👤</span>
              </div>
            </div>

            <div>
              <label class="field-label" for="password">密码</label>
              <div class="input-wrapper">
                <input
                  id="password"
                  v-model="form.password"
                  type="password"
                  class="login-input"
                  placeholder="请输入密码"
                  autocomplete="current-password"
                />
                <span class="input-icon">🔐</span>
              </div>
            </div>

            <div class="flex items-center gap-2">
              <input
                id="remember"
                v-model="form.remember"
                type="checkbox"
                class="remember-checkbox"
              />
              <label for="remember" class="remember-label">记住我</label>
            </div>

            <div v-if="errorMessage" class="error-message">
              {{ errorMessage }}
            </div>

            <button type="submit" class="login-button" :disabled="isLoading">
              <span v-if="isLoading" class="loading-spinner"></span>
              <span v-else>登录</span>
            </button>
          </form>

        </div>

        <div class="login-footer px-8 pb-6 pt-4">
          <p class="copyright">
            © 2024 智碳管家 · AI Carbon Intelligence Platform
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { callApi } from "../composables/useApi";

interface LoginForm {
  username: string;
  password: string;
  remember: boolean;
}

interface LoginResponse {
  access_token: string;
  token_type: string;
}

const form = reactive<LoginForm>({
  username: "",
  password: "",
  remember: false,
});

const isLoading = ref(false);
const errorMessage = ref("");

async function handleLogin() {
  if (!form.username || !form.password) {
    errorMessage.value = "请输入用户名和密码";
    return;
  }

  isLoading.value = true;
  errorMessage.value = "";

  try {
    const response = await callApi<LoginResponse>("/api/auth/login", "POST", {
      username: form.username,
      password: form.password,
    });

    localStorage.setItem("access_token", response.access_token);
    if (form.remember) {
      localStorage.setItem("remember", "true");
    }

    window.location.href = "/";
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "登录失败，请重试";
  } finally {
    isLoading.value = false;
  }
}

</script>

<style scoped>
.login-wrapper {
  font-family:
    -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
    Arial, sans-serif;
}

.tech-line {
  position: absolute;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(56, 189, 248, 0.3),
    transparent
  );
  animation: float 6s ease-in-out infinite;
}

@keyframes float {
  0%,
  100% {
    opacity: 0;
  }
  50% {
    opacity: 1;
  }
}

.login-card {
  background: linear-gradient(
    135deg,
    rgba(255, 255, 255, 0.98) 0%,
    rgba(255, 255, 255, 0.95) 100%
  );
}

.login-header {
  background: linear-gradient(120deg, #0a2a50 0%, #114a8c 62%, #2b79d8 100%);
  color: white;
}

.login-kicker {
  margin: 0 auto 10px;
  width: fit-content;
  border: 1px solid rgba(191, 219, 254, 0.6);
  border-radius: 999px;
  background: rgba(14, 44, 85, 0.45);
  color: #d6ecff;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 4px 10px;
}

.logo-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, #38bdf8 0%, #14b8a6 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  box-shadow: 0 4px 12px rgba(56, 189, 248, 0.3);
}

.login-title {
  margin: 0;
  font-size: 30px;
  font-weight: 900;
  color: white;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.login-subtitle {
  margin: 6px 0 0 0;
  font-size: 12px;
  font-weight: 600;
  color: rgba(233, 244, 255, 0.92);
  letter-spacing: 0.04em;
  text-align: center;
}

.login-body {
  padding-top: 24px;
}

.field-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 8px;
}

.input-wrapper {
  position: relative;
}

.login-input {
  width: 100%;
  padding: 12px 40px 12px 14px;
  border: 1.5px solid #e2e8f0;
  border-radius: 10px;
  font-size: 14px;
  color: #1f2937;
  background: #f9fafb;
  transition: all 0.2s ease;
}

.login-input:focus {
  outline: none;
  border-color: #38bdf8;
  background: white;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.1);
}

.login-input::placeholder {
  color: #9ca3af;
}

.input-icon {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 16px;
  pointer-events: none;
}

.remember-checkbox {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  border: 2px solid #d1d5db;
  background: white;
  cursor: pointer;
  transition: all 0.2s;
}

.remember-checkbox:checked {
  background: #0ea5e9;
  border-color: #0ea5e9;
}

.remember-label {
  font-size: 13px;
  color: #64748b;
  cursor: pointer;
}

.error-message {
  padding: 10px 14px;
  background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #991b1b;
  font-size: 13px;
  font-weight: 500;
  text-align: center;
}

.login-button {
  width: 100%;
  padding: 14px;
  background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
  border: none;
  border-radius: 10px;
  color: white;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.login-button:hover:not(:disabled) {
  background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(14, 165, 233, 0.35);
}

.login-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
}

.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid transparent;
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}


.login-footer {
  border-top: 1px solid #f1f5f9;
  background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
}

.copyright {
  margin: 0;
  text-align: center;
  font-size: 11px;
  color: #9ca3af;
  line-height: 1.5;
}

</style>


