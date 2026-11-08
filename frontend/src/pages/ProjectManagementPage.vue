<template>
  <section class="page-view project-page">
    <article class="project-shell">
            <div class="project-body">
        <div class="toolbar">
          <button class="primary" @click="openCreateModal">创建项目</button>
          <button class="secondary" @click="refreshProjects">刷新项目列表</button>
          <input v-model.trim="keyword" class="field keyword-field" placeholder="搜索项目名称/组织" />
          <input v-model.number="queryId" type="number" class="field id-field" placeholder="项目 ID" />
          <button class="secondary" @click="queryAndEditById">查询</button>
        </div>

        <div class="pager-bar">
          <span>共 {{ filteredProjects.length }} 个项目</span>
          <div class="pager-controls">
            <label>
              每页
              <select v-model.number="pageSize" class="field pager-select">
                <option :value="5">5</option>
                <option :value="10">10</option>
                <option :value="20">20</option>
              </select>
              条
            </label>
            <button class="secondary mini" :disabled="currentPage <= 1" @click="currentPage -= 1">上一页</button>
            <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
            <button class="secondary mini" :disabled="currentPage >= totalPages" @click="currentPage += 1">下一页</button>
          </div>
        </div>

        <p class="status">{{ status }}</p>

        <div class="table-card">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>项目名称</th>
                <th>组织</th>
                <th>报告年</th>
                <th>标准</th>
                <th v-if="canManage">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="pagedProjects.length === 0">
                <td :colspan="canManage ? 6 : 5">暂无项目数据</td>
              </tr>
              <tr v-for="item in pagedProjects" :key="item.id">
                <td>{{ item.id }}</td>
                <td>{{ item.name }}</td>
                <td>{{ item.organization }}</td>
                <td>{{ item.report_year }}</td>
                <td>{{ item.standard }}</td>
                <td v-if="canManage" class="ops">
                  <button class="mini secondary" @click="openEditModal(item)">编辑</button>
                  <button class="mini danger" @click="deleteProject(item.id)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </article>

    <div v-if="showEditor" class="modal-mask" @click.self="closeModal">
      <div class="modal-card">
        <header class="modal-head">
          <h3>{{ modalMode === 'create' ? '创建项目' : `编辑项目 ID: ${currentProjectId}` }}</h3>
          <button class="close-btn" @click="closeModal">关闭</button>
        </header>

        <div class="modal-body">
          <div class="form-grid">
            <label class="field-label">
              项目名称：
              <input v-model="form.name" class="field" placeholder="请输入项目名称" />
            </label>
            <label class="field-label">
              组织：
              <input v-model="form.organization" class="field" placeholder="请输入组织名称" />
            </label>
            <label class="field-label">
              组织边界：
              <input v-model="form.boundary" class="field" placeholder="请输入组织边界" />
            </label>
            <label class="field-label">
              边界方法：
              <input v-model="form.boundary_method" class="field" placeholder="请输入边界方法" />
            </label>
            <label class="field-label">
              基准年：
              <input v-model.number="form.base_year" type="number" class="field" placeholder="请输入基准年" />
            </label>
            <label class="field-label">
              报告年：
              <input v-model.number="form.report_year" type="number" class="field" placeholder="请输入报告年" />
            </label>
            <label class="field-label">
              周期开始：
              <input v-model="form.period_start" type="date" class="field" />
            </label>
            <label class="field-label">
              周期结束：
              <input v-model="form.period_end" type="date" class="field" />
            </label>
            <label class="field-label">
              核算标准：
              <input v-model="form.standard" class="field" placeholder="如：ISO 14064-1:2018" />
            </label>
            <label class="field-label">
              所属行业：
              <input v-model="form.industry" class="field" placeholder="请输入所属行业" />
            </label>
          </div>
        </div>

        <footer class="modal-foot">
          <button class="secondary" @click="resetForm">重置</button>
          <button class="primary" @click="saveProject">{{ modalMode === 'create' ? '确认创建' : '确认更新' }}</button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { callApi } from '../composables/useApi'

interface ProjectPayload {
  name: string
  organization: string
  boundary: string
  boundary_method: string
  base_year: number
  report_year: number
  period_start: string
  period_end: string
  standard: string
  industry: string
}

interface ProjectRead extends ProjectPayload {
  id: number
}

const defaultForm: ProjectPayload = {
  name: '示范能源科技有限公司 2025 年度盘查',
  organization: '示范能源科技有限公司',
  boundary: '总部 + 生产基地 A + 生产基地 B',
  boundary_method: '运营控制法',
  base_year: 2021,
  report_year: 2025,
  period_start: '',
  period_end: '',
  standard: 'ISO 14064-1:2018',
  industry: '新能源制造',
}

const form = ref<ProjectPayload>({ ...defaultForm })
const projects = ref<ProjectRead[]>([])
const status = ref('准备就绪。')
const queryId = ref<number | undefined>()
const keyword = ref('')

const showEditor = ref(false)
const modalMode = ref<'create' | 'edit'>('create')
const currentProjectId = ref<number | null>(null)
const canManage = computed(() => {
  const token = localStorage.getItem("access_token")
  if (!token) return false
  try {
    const payload = JSON.parse(atob(token.split(".")[1]))
    return String(payload?.role || "").toLowerCase() === "admin"
  } catch {
    return false
  }
})

const pageSize = ref(10)
const currentPage = ref(1)

const filteredProjects = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return projects.value
  return projects.value.filter((item) => {
    return item.name.toLowerCase().includes(q) || item.organization.toLowerCase().includes(q)
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredProjects.value.length / pageSize.value)))
const pagedProjects = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredProjects.value.slice(start, start + pageSize.value)
})

watch(pageSize, () => {
  currentPage.value = 1
})
watch(keyword, () => {
  currentPage.value = 1
})
watch(totalPages, (value) => {
  if (currentPage.value > value) currentPage.value = value
})

function resetForm() {
  form.value = { ...defaultForm }
}

function closeModal() {
  showEditor.value = false
}

function openCreateModal() {
  modalMode.value = 'create'
  currentProjectId.value = null
  resetForm()
  showEditor.value = true
}

function applyProjectToForm(project: ProjectRead) {
  form.value = {
    name: project.name,
    organization: project.organization,
    boundary: project.boundary,
    boundary_method: project.boundary_method,
    base_year: project.base_year,
    report_year: project.report_year,
    period_start: project.period_start || '',
    period_end: project.period_end || '',
    standard: project.standard,
    industry: project.industry,
  }
}

function openEditModal(project: ProjectRead) {
  if (!canManage.value) {
    status.value = '当前账号无权限执行该操作。'
    return
  }
  modalMode.value = 'edit'
  currentProjectId.value = project.id
  applyProjectToForm(project)
  showEditor.value = true
}

function buildProjectPayload() {
  return {
    ...form.value,
    period_start: form.value.period_start || null,
    period_end: form.value.period_end || null,
  }
}

async function saveProject() {
  if (modalMode.value === 'edit' && !canManage.value) {
    status.value = '当前账号无权限执行该操作。'
    return
  }
  if (modalMode.value === 'create') {
    await run(async () => {
      await callApi<ProjectRead>('/api/projects', 'POST', buildProjectPayload())
      await listProjects(true)
      closeModal()
    }, '项目创建成功。')
    return
  }

  if (!currentProjectId.value) {
    status.value = '未找到要更新的项目ID。'
    return
  }
  await run(async () => {
    await callApi<ProjectRead>(`/api/projects/${currentProjectId.value}`, 'PUT', buildProjectPayload())
    await listProjects(true)
    closeModal()
  }, '项目更新成功。')
}

async function listProjects(silent = false) {
  const data = await callApi<ProjectRead[]>('/api/projects')
  projects.value = data
  if (!silent) status.value = `项目列表已更新，共 ${data.length} 条。`
}

async function refreshProjects() {
  await run(async () => {
    await listProjects(true)
  }, '项目列表刷新成功。')
}

async function queryAndEditById() {
  if (!queryId.value) {
    status.value = '请先输入项目 ID。'
    return
  }
  await run(async () => {
    const data = await callApi<ProjectRead>(`/api/projects/${queryId.value}`)
    openEditModal(data)
  }, '项目详情已加载，可编辑。')
}

async function deleteProject(projectId: number) {
  if (!canManage.value) {
    status.value = '当前账号无权限执行该操作。'
    return
  }
  if (!window.confirm(`确认删除项目 ID=${projectId} 吗？`)) return
  await run(async () => {
    await callApi(`/api/projects/${projectId}`, 'DELETE')
    await listProjects(true)
    if (currentProjectId.value === projectId) {
      closeModal()
      currentProjectId.value = null
    }
  }, '项目删除成功。')
}

async function run(action: () => Promise<void>, successText: string) {
  try {
    await action()
    status.value = successText
  } catch (error) {
    status.value = '操作失败，请检查后端服务。'
    console.error(error)
  }
}

onMounted(async () => {
  await run(async () => {
    await listProjects(true)
  }, '项目列表加载完成。')
})
</script>

<style scoped>
.project-page {
  display: grid;
}

.project-shell {
  border: 1px solid #d6deeb;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}

.project-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 26px;
  background: linear-gradient(100deg, #0a4da6 0%, #0e63c4 55%, #338dff 100%);
  color: #fff;
}

.head-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.22);
  font-size: 14px;
}

.project-head h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
}

.project-head p {
  margin: 4px 0 0;
  font-size: 14px;
  color: #d8e8ff;
}

.project-body {
  padding: 16px 20px 20px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.keyword-field {
  width: 220px;
}

.id-field {
  width: 160px;
}

.pager-bar {
  margin-top: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  color: #334155;
  font-size: 13px;
}

.pager-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pager-select {
  width: 72px;
  display: inline-block;
}

.status {
  margin: 10px 0;
  font-size: 13px;
  color: #4b6790;
}

.table-card {
  border: 1px solid #d8e1ee;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}

table {
  width: 100%;
  border-collapse: collapse;
}

thead {
  background: #0f5ca6;
  color: #fff;
}

th,
td {
  padding: 10px 12px;
  border-bottom: 1px solid #e6ebf2;
  text-align: left;
  font-size: 13px;
}

.ops {
  display: flex;
  gap: 8px;
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

.danger.ghost {
  background: #fff;
  color: #dc2626;
  border-radius: 0.75rem;
  height: 2.5rem;
  padding: 0 1rem;
}

.danger.ghost:hover {
  background: #fef2f2;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: grid;
  place-items: center;
  z-index: 1200;
  padding: 20px;
}

.modal-card {
  width: min(1000px, 100%);
  border-radius: 12px;
  background: #fff;
  border: 1px solid #d8e1ee;
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.2);
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid #e2e8f0;
}

.modal-head h3 {
  margin: 0;
  font-size: 18px;
  color: #1f2937;
}

.close-btn {
  border: 1px solid #94a3b8;
  background: #fff;
  color: #334155;
  border-radius: 8px;
  height: 32px;
  padding: 0 10px;
}

.modal-body {
  padding: 14px 16px;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
}

.field-label {
  display: grid;
  gap: 6px;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.modal-foot {
  padding: 12px 16px 16px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 980px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>




