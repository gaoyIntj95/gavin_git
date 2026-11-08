<template>
  <section class="calc-page">
    <article class="calc-shell">
            <div class="calc-body">
        <div class="toolbar">
          <select v-model.number="projectId" class="field project-select">
            <option v-if="projectOptions.length === 0" :value="projectId">未加载到项目，请检查 API 地址</option>
            <option v-for="item in projectOptions" :key="item.id" :value="item.id">
              {{ item.id }} - {{ item.name }}
            </option>
          </select>
          <button class="secondary" @click="loadProjectAndSources">刷新项目与排放源</button>
          <button class="secondary" @click="validateCurrentProject">数据校验</button>
          <button class="primary" @click="calculateCurrentProject">执行自动核算</button>
        </div>

        <div class="project-card">
          <h3>当前项目：{{ projectInfo ? projectInfo.name : '未加载项目' }}</h3>
          <p v-if="projectInfo">
            核算边界：{{ projectInfo.boundary || '-' }} | 基准年：{{ projectInfo.base_year || '-' }} | 报告年：{{ projectInfo.report_year || '-' }} | 周期：{{ projectPeriodText }}
          </p>
          <p v-else>请先点击“刷新项目与排放源”。</p>
        </div>

        <div class="search-row">
          <input
            v-model.trim="sourceKeyword"
            class="field source-search"
            placeholder="查找排放源（名称/类别）"
          />
          <button v-if="canManage && editingSourceId !== null" class="secondary" @click="cancelEditSource">取消编辑</button>
        </div>

        <div class="table-card">
          <table>
            <thead>
              <tr>
                <th>Scope</th>
                <th>排放类型</th>
                <th>ISO 分类</th>
                <th>排放源类别</th>
                <th>排放源名称</th>
                <th>活动数据</th>
                <th>数据单位</th>
                <th>tCO2e</th>
                <th v-if="canManage">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="filteredSources.length === 0">
                <td :colspan="canManage ? 9 : 8">暂无排放源数据</td>
              </tr>
              <tr v-for="item in filteredSources" :key="item.id">
                <td>{{ scopeText(item.scope) }}</td>
                <td>{{ emissionClassText(item.emission_class) }}</td>
                <td>{{ item.iso_category_code }} {{ item.iso_category_name }}</td>
                <td>{{ item.category }}</td>
                <td>{{ displaySourceName(item) }}</td>
                <td>{{ item.activity_data }}</td>
                <td>{{ item.unit || '-' }}</td>
                <td class="co2e">{{ item.co2e.toFixed(4) }}</td>
                <td v-if="canManage" class="ops">
                  <button class="mini secondary" @click="startEditSource(item)">编辑</button>
                  <button class="mini danger" @click="deleteSource(item.id)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="totals-grid">
          <div class="metric-card"><span>总排放量</span><strong>{{ totalEmissionText }}</strong></div>
          <div class="metric-card"><span>直接排放</span><strong>{{ directEmissionText }}</strong></div>
          <div class="metric-card"><span>间接排放</span><strong>{{ indirectEmissionText }}</strong></div>
          <div class="metric-card"><span>核算口径</span><strong>{{ totals?.calculation_profile || '-' }}</strong></div>
        </div>

        <details ref="sourceFormPanelRef" class="source-form-card">
          <summary>{{ editingSourceId === null ? '新增排放源' : `编辑排放源 ID: ${editingSourceId}` }}</summary>

          <div class="form-grid">
            <label>
              Scope
              <select v-model.number="sourceForm.scope" class="field">
                <option v-for="item in scopeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label>
              排放类型
              <select v-model="sourceForm.emission_class" class="field" disabled>
                <option v-for="item in emissionClassOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label>
              GHG排放或移除类别
              <select v-model="sourceForm.ghg_category" class="field">
                <option value="">请选择</option>
                <option v-for="item in ghgCategoryOptions" :key="item" :value="item">{{ item }}</option>
              </select>
            </label>
            <label>
              排放源类别
              <template v-if="selectedCategory !== 'CUSTOM'">
                <select v-model="selectedCategory" class="field" :disabled="isIndirectScope2LockedCategory">
                  <option value="">请选择</option>
                  <option v-for="item in filteredCategoryOptions" :key="item" :value="item">{{ item }}</option>
                  <option value="CUSTOM">自定义</option>
                </select>
              </template>
              <input
                v-else
                v-model="customCategoryName"
                class="field category-custom-input"
                placeholder="请输入排放源类别"
              />
            </label>
            <label>
              排放源名称
              <select v-if="isFireExtinguisherCategory" v-model="sourceForm.name" class="field">
                <option value="">请选择</option>
                <option v-for="item in fireExtinguisherNameOptions" :key="item" :value="item">{{ item }}</option>
              </select>
              <select v-else-if="isRefrigerantCategory" v-model="sourceForm.name" class="field">
                <option value="">请选择</option>
                <option v-for="item in refrigerantNameOptions" :key="item" :value="item">{{ item }}</option>
              </select>
              <input v-else v-model="sourceForm.name" class="field" />
            </label>

            <label>
              活动数据量
              <input v-model.number="sourceForm.activity_data" type="number" step="0.0001" class="field" />
            </label>
            <label>
              活动数据单位
              <input v-model="sourceForm.unit" class="field" :readonly="isFireExtinguisherCategory" />
            </label>
            <label>
              温室气体
              <input v-if="isScope1FuelCategory" class="field" value="CO2/CH4/N2O" readonly />
              <input v-else-if="isFireExtinguisherCategory" class="field" :value="fireExtinguisherGasText" readonly />
              <select v-else v-model="selectedGas" class="field">
                <option v-for="item in displayGasOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label>
              GWP
              <input v-if="isScope1FuelCategory" class="field" value="1/27/273" readonly />
              <input v-else-if="isFireExtinguisherCategory" class="field" :value="fireExtinguisherGwpText" readonly />
              <input v-else v-model.number="sourceForm.gwp" type="number" min="0.0001" step="0.0001" class="field" />
            </label>

            <label>
              因子类别
              <input v-if="isFireExtinguisherCategory" class="field" value="国际排放因子" readonly />
              <select v-else-if="useManualFactor && selectedCategory !== '外购电力'" v-model="sourceForm.manual_factor_source" class="field">
                <option v-for="item in factorSourceOptions" :key="item || 'blank'" :value="item">
                  {{ item || '请选择' }}
                </option>
              </select>
              <select v-else-if="useManualFactor && selectedCategory === '外购电力'" v-model="electricityFactorLevel" class="field">
                <option value="国家">国家</option>
                <option value="区域">区域</option>
                <option value="省级">省级</option>
              </select>
              <input v-else class="field" value="自动匹配" readonly />
            </label>
            <label v-if="!isFireExtinguisherCategory">
              因子细分
              <select v-if="useManualFactor && selectedCategory === '外购电力'" v-model="electricityFactorDetail" class="field">
                <option v-for="item in electricityFactorDetailOptions" :key="item" :value="item">{{ item }}</option>
              </select>
              <input v-else class="field" value="-" readonly />
            </label>
            <label>
              因子值
              <input v-if="isFireExtinguisherCategory" class="field" :value="fireExtinguisherFactorText" readonly />
              <input v-else-if="isRefrigerantCategory" class="field" :value="refrigerantFactorText" readonly />
              <input v-else-if="isScope1FuelCategory" class="field" value="-" readonly />
              <input
                v-else
                v-model="sourceForm.manual_factor"
                type="number"
                min="0.000001"
                step="0.000001"
                class="field"
                placeholder="手动填写因子值"
                :disabled="!useManualFactor"
                :readonly="selectedCategory === '外购电力'"
              />
            </label>
            <label v-if="!isFireExtinguisherCategory">
              因子单位
              <input :value="factorUnitText" class="field" readonly />
            </label>

            <label v-if="sourceForm.scope === 2 && !isFireExtinguisherCategory">
              能源类型
              <select v-model="sourceForm.energy_type" class="field">
                <option v-for="item in energyTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label v-if="sourceForm.scope === 2 && !isFireExtinguisherCategory">
              消费类型
              <select v-model="sourceForm.consumption_type" class="field">
                <option v-for="item in consumptionTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
          </div>

          <div class="form-grid extra-grid">
            <label v-if="selectedGas === 'CUSTOM'">
              自定义气体名称
              <input v-model="customGasName" class="field" placeholder="例如 C2F6" />
            </label>
          </div>

          <label class="notes-label">
            备注
            <textarea v-model="sourceForm.notes" class="notes-area"></textarea>
          </label>

          <div class="flags-row">
            <label><input v-model="sourceForm.is_green_electricity" type="checkbox" /> 绿电</label>
            <label><input v-model="useManualFactor" type="checkbox" /> 手动输入因子（优先）</label>
            <label><input v-model="sourceForm.is_removal" type="checkbox" /> 是否清除项</label>
            <label><input v-model="sourceForm.is_storage" type="checkbox" /> 是否储存项</label>
            <label><input v-model="enableUncertainty" type="checkbox" /> 同步不确定性分析</label>
          </div>

          <div v-if="enableUncertainty" class="uncertainty-grid">
            <label>
              设施
              <input v-model="uncertaintyForm.facility" class="field" />
            </label>

            <label>
              活动数据类别
              <select v-model="uncertaintyForm.activity_data_category" class="field">
                <option value="">请选择</option>
                <option value="自动连续监测">自动连续监测</option>
                <option value="定期量测/抄表/铭牌">定期量测/抄表/铭牌</option>
                <option value="自行推估">自行推估</option>
              </select>
            </label>

            <label>
              排放因子类别
              <select v-model="uncertaintyForm.factor_category" class="field">
                <option value="">请选择</option>
                <option value="国际排放因子">国际排放因子</option>
                <option value="国家排放因子">国家排放因子</option>
                <option value="区域排放因子">区域排放因子</option>
              </select>
            </label>
          </div>

          <div class="form-action-row">
            <button class="primary" @click="submitSourceForm">
              {{ editingSourceId === null ? '提交新增排放源' : '保存排放源修改' }}
            </button>
          </div>
        </details>

        <div v-if="validation.errors.length || validation.warnings.length" class="warn-box">
          <p v-if="validation.errors.length">错误：{{ validation.errors.join('；') }}</p>
          <p v-if="validation.warnings.length">预警：{{ validation.warnings.join('；') }}</p>
        </div>

        <p class="status">{{ status }}</p>
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { callApi, useApiBase } from '../composables/useApi'
const canManage = computed(() => {
  const token = localStorage.getItem('access_token')
  if (!token) return false
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return String(payload?.role || '').toLowerCase() === 'admin'
  } catch {
    return false
  }
})

type GasType =
  | 'CO2'
  | 'CH4'
  | 'CH4_BIOGENIC'
  | 'CH4_FOSSIL_COMB'
  | 'CH4_FOSSIL_FUG'
  | 'N2O'
  | 'HFC32'
  | 'HFC143A'
  | 'HFC134A'
  | 'FM200'
  | 'PFCs'
  | 'SF6'
  | 'NF3'
type GasSelectType = GasType | 'CUSTOM'
type EmissionClass = 'direct' | 'indirect'
type EnergyType = 'fuel' | 'electricity' | 'heat'
type ConsumptionType = 'purchased' | 'transferred'
type ActivityDataCategory = '自动连续监测' | '定期量测/抄表/铭牌' | '自行推估'
type FactorCategory = '国际排放因子' | '国家排放因子' | '区域排放因子'
type CategorySelectType = string | 'CUSTOM'

interface ProjectRead {
  id: number
  name: string
  boundary?: string | null
  base_year?: number | null
  report_year?: number | null
  period_start?: string | null
  period_end?: string | null
}

interface ProjectOption {
  id: number
  name: string
}

interface EmissionSourceRead {
  id: number
  scope: number
  category: string
  name: string
  activity_data: number
  unit: string
  gas: string
  gwp: number
  factor: number
  factor_source: string
  ghg_category: string
  co2e: number
  emission_class: EmissionClass
  energy_type: EnergyType
  consumption_type: ConsumptionType
  is_green_electricity: boolean
  is_removal: boolean
  is_storage: boolean
  period_start?: string | null
  period_end?: string | null
  notes?: string | null
  iso_category_code: string
  iso_category_name: string
  uncertainties?: Array<{
    facility?: string | null
    activity_data_category: ActivityDataCategory
    factor_category: FactorCategory
  }>
}

interface CalculationResult {
  total_emission: number
  direct_emission: number
  indirect_emission: number
  calculation_profile: string
}

interface ValidationResult {
  warnings: string[]
  errors: string[]
}

interface SourceForm {
  scope: number
  category: string
  name: string
  activity_data: number | null
  unit: string
  gas: string
  gwp: number | null
  emission_class: EmissionClass | ''
  ghg_category: string
  energy_type: EnergyType | ''
  consumption_type: ConsumptionType | ''
  is_green_electricity: boolean
  is_removal: boolean
  is_storage: boolean
  notes: string
  manual_factor: string
  manual_factor_source: string
}

interface UncertaintyForm {
  facility: string
  activity_data_category: ActivityDataCategory | ''
  factor_category: FactorCategory | ''
}

const { apiBase, saveApiBase } = useApiBase()
const projectId = ref(1)
const projectInfo = ref<ProjectRead | null>(null)
const projectOptions = ref<ProjectOption[]>([])
const sources = ref<EmissionSourceRead[]>([])
const sourceKeyword = ref('')
const editingSourceId = ref<number | null>(null)
const sourceFormPanelRef = ref<HTMLDetailsElement | null>(null)
const totals = ref<CalculationResult | null>(null)
const validation = ref<ValidationResult>({ warnings: [], errors: [] })
const status = ref('准备就绪。')
const totalsCachePrefix = 'carbon_calc_totals_'

function getTotalsCacheKey(project: number) {
  return `${totalsCachePrefix}${project}`
}

function saveTotalsCache(project: number, value: CalculationResult | null) {
  const key = getTotalsCacheKey(project)
  if (!value) {
    localStorage.removeItem(key)
    return
  }
  localStorage.setItem(key, JSON.stringify(value))
}

function loadTotalsCache(project: number): CalculationResult | null {
  const raw = localStorage.getItem(getTotalsCacheKey(project))
  if (!raw) return null
  try {
    return JSON.parse(raw) as CalculationResult
  } catch {
    return null
  }
}

const sourceForm = ref<SourceForm>({
  scope: 0,
  category: '',
  name: '',
  activity_data: null,
  unit: '',
  gas: '',
  gwp: null,
  emission_class: '',
  ghg_category: '',
  energy_type: '',
  consumption_type: '',
  is_green_electricity: false,
  is_removal: false,
  is_storage: false,
  notes: '',
  manual_factor: '',
  manual_factor_source: '',
})

const selectedGas = ref<GasSelectType | ''>('')
const customGasName = ref('')
const selectedCategory = ref<CategorySelectType>('')
const customCategoryName = ref('')
const useManualFactor = ref(false)
const electricityFactorLevel = ref<'国家' | '区域' | '省级'>('国家')
const electricityFactorDetail = ref('全国平均')
const enableUncertainty = ref(false)
const uncertaintyForm = ref<UncertaintyForm>({
  facility: '',
  activity_data_category: '',
  factor_category: '',
})

const gasDefaultGwp: Record<GasType, number | undefined> = {
  CO2: 1,
  CH4: 27,
  CH4_BIOGENIC: 27,
  CH4_FOSSIL_COMB: 27,
  CH4_FOSSIL_FUG: 29.8,
  N2O: 273,
  HFC32: 770,
  HFC143A: 5807,
  HFC134A: 1526,
  FM200: 2050,
  SF6: 25184,
  NF3: 17423,
  PFCs: undefined,
}

const gasOptions: Array<{ label: string; value: GasSelectType | '' }> = [
  { label: '请选择', value: '' },
  { label: 'CO2', value: 'CO2' },
  { label: 'CH4', value: 'CH4' },
  { label: 'CH4（生物源）', value: 'CH4_BIOGENIC' },
  { label: 'CH4（化石源-燃烧）', value: 'CH4_FOSSIL_COMB' },
  { label: 'CH4（化石源-无组织/工艺）', value: 'CH4_FOSSIL_FUG' },
  { label: 'N2O', value: 'N2O' },
  { label: 'HFC-32', value: 'HFC32' },
  { label: 'HFC-143a', value: 'HFC143A' },
  { label: 'HFC-134a', value: 'HFC134A' },
  { label: 'FM200（七氟丙烷）', value: 'FM200' },
  { label: 'PFCs', value: 'PFCs' },
  { label: 'SF6', value: 'SF6' },
  { label: 'NF3', value: 'NF3' },
  { label: '自定义气体', value: 'CUSTOM' },
]

const scopeOptions = [
  { label: '请选择', value: 0 },
  { label: '范围一（Scope 1）', value: 1 },
  { label: '范围二（Scope 2）', value: 2 },
  { label: '范围三（Scope 3）', value: 3 },
]
const scope1FuelCategories = ['汽油', '柴油', '天然气']

function getAvailableCategoryOptions(scope: number, emissionClass: EmissionClass | '', ghgCategory: string): string[] {
  if (!ghgCategory) {
    return []
  }

  if (scope === 2 && emissionClass === 'indirect') {
    if (ghgCategory === '2.1电力产生的间接排放') return ['外购电力']
    if (ghgCategory === '2.2热力产生的间接排放') return ['外购热力']
    return []
  }

  if (emissionClass === 'direct') {
    if (ghgCategory === '1.1固定燃烧') return ['柴油', '天然气']
    if (ghgCategory === '1.2工艺排放') return []
    if (ghgCategory === '1.3移动燃烧') return ['汽油', '柴油', '天然气']
    if (ghgCategory === '1.4无组织排放') return ['制冷剂逸散', '灭火器逸散', 'WD-40除锈剂', '化粪池']
    if (ghgCategory === '1.5生物质燃烧') return []
    return []
  }
  return []
}

const filteredCategoryOptions = computed(() =>
  getAvailableCategoryOptions(sourceForm.value.scope, sourceForm.value.emission_class, sourceForm.value.ghg_category),
)
const isScope1FuelCategory = computed(() => scope1FuelCategories.includes(sourceForm.value.category))
const isFireExtinguisherCategory = computed(() => sourceForm.value.category === '灭火器逸散')
const isRefrigerantCategory = computed(() => sourceForm.value.category === '制冷剂逸散')
const fireExtinguisherNameOptions = ['便携式灭火器', '中央灭火系统']
const fireExtinguisherFactorMap: Record<string, number> = {
  便携式灭火器: 0.04,
  中央灭火系统: 0.02,
}
const refrigerantNameOptions = ['冰箱', '空调', '汽车空调', '冷冻机', '恒温恒湿机']
const refrigerantFactorMap: Record<string, number> = {
  冰箱: 0.003,
  空调: 0.055,
  汽车空调: 0.15,
  冷冻机: 0.085,
  恒温恒湿机: 0.08,
}
const fireExtinguisherFactorText = computed(() => {
  const factor = fireExtinguisherFactorMap[sourceForm.value.name]
  if (typeof factor !== 'number') return '-'
  return `${factor * 100}%`
})
const fireExtinguisherGasText = computed(() => {
  if (sourceForm.value.name === '中央灭火系统') return 'FM200'
  return 'CO2'
})
const fireExtinguisherGwpText = computed(() => {
  if (sourceForm.value.name === '中央灭火系统') return '2050'
  return '1'
})
const refrigerantFactorText = computed(() => {
  const factor = refrigerantFactorMap[sourceForm.value.name]
  if (typeof factor !== 'number') return '-'
  return `${(factor * 100).toFixed(2)}%`
})
const isIndirectScope2LockedCategory = computed(
  () =>
    sourceForm.value.scope === 2 &&
    sourceForm.value.emission_class === 'indirect' &&
    ['2.1电力产生的间接排放', '2.2热力产生的间接排放'].includes(sourceForm.value.ghg_category),
)
const ghgCategoryOptions = computed(() =>
  sourceForm.value.emission_class ? ghgCategoryOptionsByClass[sourceForm.value.emission_class as EmissionClass] || [] : [],
)
const displayGasOptions = computed(() => {
  if (scope1FuelCategories.includes(sourceForm.value.category)) {
    return gasOptions.filter((item) => item.value === '' || ['CO2', 'CH4', 'N2O'].includes(String(item.value)))
  }
  return gasOptions
})

const emissionClassOptions = [
  { label: '请选择', value: '' as const },
  { label: '直接排放', value: 'direct' as const },
  { label: '间接排放', value: 'indirect' as const },
]

const ghgCategoryOptionsByClass: Record<EmissionClass, string[]> = {
  direct: ['1.1固定燃烧', '1.2工艺排放', '1.3移动燃烧', '1.4无组织排放', '1.5生物质燃烧'],
  indirect: ['2.1电力产生的间接排放', '2.2热力产生的间接排放'],
}

const energyTypeOptions = [
  { label: '请选择', value: '' as const },
  { label: '燃料', value: 'fuel' as const },
  { label: '电力', value: 'electricity' as const },
  { label: '热力/蒸汽', value: 'heat' as const },
]

const consumptionTypeOptions = [
  { label: '请选择', value: '' as const },
  { label: '购入', value: 'purchased' as const },
  { label: '转供', value: 'transferred' as const },
]
const factorSourceOptions = ['', '国际排放因子', '国家排放因子', '区域排放因子', '省级排放因子', '企业自定义']
const electricityFactorMap: Record<'国家' | '区域' | '省级', Record<string, number>> = {
  国家: { 全国平均: 0.5306 },
  区域: {
    华北: 0.6361,
    东北: 0.5122,
    华东: 0.55,
    华中: 0.5271,
    西北: 0.5543,
    南方: 0.4042,
    西南: 0.2472,
  },
  省级: {
    北京: 0.5554,
    天津: 0.6796,
    河北: 0.6516,
    山西: 0.6634,
    内蒙古: 0.6479,
    辽宁: 0.4878,
    吉林: 0.4671,
    黑龙江: 0.5229,
    上海: 0.5737,
    江苏: 0.5827,
  },
}
const electricityFactorDetailOptions = computed(() => Object.keys(electricityFactorMap[electricityFactorLevel.value]))
const factorUnitText = computed(() => {
  if (selectedCategory.value === '外购电力') return 'tCO2/MWh'
  if (selectedCategory.value === '外购热力') return 'tCO2/GJ'
  if (selectedCategory.value === '制冷剂逸散') return '%'
  return '-'
})

function getDefaultGhgCategory(emissionClass: EmissionClass | '', category: string) {
  if (!emissionClass) return ''
  if (emissionClass === 'indirect') {
    return category === '外购热力'
      ? '2.2热力产生的间接排放'
      : '2.1电力产生的间接排放'
  }
  if (category === '汽油' || category === '柴油') return '1.3移动燃烧'
  if (category === '制冷剂逸散' || category === '灭火器逸散' || category === 'WD-40除锈剂' || category === '化粪池') {
    return '1.4无组织排放'
  }
  if (category === '生物质燃烧') return '1.5生物质燃烧'
  if (category === '工艺排放') return '1.2工艺排放'
  return '1.1固定燃烧'
}

function applyGhgCategoryLock() {
  if (sourceForm.value.scope !== 2 || sourceForm.value.emission_class !== 'indirect') {
    return
  }
  if (sourceForm.value.ghg_category === '2.2热力产生的间接排放') {
    selectedCategory.value = '外购热力'
    sourceForm.value.category = '外购热力'
    sourceForm.value.unit = 'GJ'
    sourceForm.value.energy_type = 'heat'
    sourceForm.value.consumption_type = 'purchased'
    return
  }
  if (sourceForm.value.ghg_category === '2.1电力产生的间接排放') {
    selectedCategory.value = '外购电力'
    sourceForm.value.category = '外购电力'
    sourceForm.value.unit = 'MWh'
    sourceForm.value.energy_type = 'electricity'
    sourceForm.value.consumption_type = 'purchased'
    electricityFactorLevel.value = '国家'
    electricityFactorDetail.value = '全国平均'
    applyElectricityFactorBySelection()
  }
}

function syncCategorySelectionToGhGRule(forceExitCustom = false) {
  const allowed = getAvailableCategoryOptions(
    sourceForm.value.scope,
    sourceForm.value.emission_class,
    sourceForm.value.ghg_category,
  )

  if (!sourceForm.value.ghg_category) {
    if (selectedCategory.value !== 'CUSTOM') {
      selectedCategory.value = ''
      sourceForm.value.category = ''
    }
    return
  }

  if (allowed.length === 0) {
    if (selectedCategory.value !== 'CUSTOM') {
      selectedCategory.value = 'CUSTOM'
    }
    sourceForm.value.category = customCategoryName.value.trim() || sourceForm.value.category || ''
    return
  }

  if (selectedCategory.value === 'CUSTOM') {
    if (forceExitCustom) {
      selectedCategory.value = ''
      sourceForm.value.category = ''
    }
    return
  }

  const current = String(selectedCategory.value || '')
  if (!current || !allowed.includes(current)) {
    selectedCategory.value = ''
    sourceForm.value.category = ''
  }
}

const totalEmissionText = computed(() => formatNumber(totals.value?.total_emission))
const directEmissionText = computed(() => formatNumber(totals.value?.direct_emission))
const indirectEmissionText = computed(() => formatNumber(totals.value?.indirect_emission))
const projectPeriodText = computed(() => {
  if (!projectInfo.value) return '-'
  const start = projectInfo.value.period_start ? String(projectInfo.value.period_start).slice(0, 10) : ''
  const end = projectInfo.value.period_end ? String(projectInfo.value.period_end).slice(0, 10) : ''
  if (!start && !end) return '-'
  return `${start || '-'} ~ ${end || '-'}`
})

function compareIsoCode(a: string, b: string) {
  const parse = (value: string) =>
    String(value || '')
      .split('.')
      .map((part) => Number.parseInt(part, 10))
      .map((part) => (Number.isFinite(part) ? part : Number.MAX_SAFE_INTEGER))

  const aParts = parse(a)
  const bParts = parse(b)
  const maxLength = Math.max(aParts.length, bParts.length)

  for (let index = 0; index < maxLength; index += 1) {
    const aPart = aParts[index] ?? -1
    const bPart = bParts[index] ?? -1
    if (aPart !== bPart) {
      return aPart - bPart
    }
  }
  return 0
}

function compareSourceDisplayOrder(a: EmissionSourceRead, b: EmissionSourceRead) {
  const isoCompare = compareIsoCode(a.iso_category_code, b.iso_category_code)
  if (isoCompare !== 0) return isoCompare

  const nameCompare = String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN')
  if (nameCompare !== 0) return nameCompare

  return String(a.category || '').localeCompare(String(b.category || ''), 'zh-CN')
}

const filteredSources = computed(() => {
  const q = sourceKeyword.value.trim().toLowerCase()
  const matched = !q
    ? [...sources.value]
    : sources.value.filter((s) => s.name.toLowerCase().includes(q) || s.category.toLowerCase().includes(q))

  return matched.sort(compareSourceDisplayOrder)
})

function formatNumber(value?: number) {
  return typeof value === 'number' ? `${value.toFixed(4)} tCO2e` : '-'
}

function parseOptionalText(value: string) {
  const t = value.trim()
  return t || undefined
}

function scopeText(scope: number) {
  return scopeOptions.find((s) => s.value === scope)?.label || String(scope)
}

function emissionClassText(value: string) {
  if (value === 'direct') return '直接排放'
  if (value === 'indirect') return '间接排放'
  return value || '-'
}

function gasText(value: string) {
  const text = String(value || '').trim()
  const map: Record<string, string> = {
    CO2: 'CO2',
    CH4: 'CH4',
    CH4_BIOGENIC: 'CH4（生物源）',
    CH4_FOSSIL_COMB: 'CH4（化石源-燃烧）',
    CH4_FOSSIL_FUG: 'CH4（化石源-无组织/工艺）',
    N2O: 'N2O',
    HFC32: 'HFC-32',
    HFC143A: 'HFC-143a',
    HFC134A: 'HFC-134a',
    PFCs: 'PFCs',
    SF6: 'SF6',
    NF3: 'NF3',
    OTHER: '其他',
  }
  return map[text] || text || '-'
}

function displaySourceName(item: EmissionSourceRead) {
  if (item.category === '制冷剂逸散' && item.gas) {
    return item.name + '（' + gasText(item.gas) + '）'
  }
  return item.name || '-'
}
function normalizeActivityCategory(value?: string): ActivityDataCategory {
  const text = String(value || '').trim()
  if (!text) return '自动连续监测'
  if (text.includes('自动') || text.toLowerCase().includes('continuous')) return '自动连续监测'
  if (text.includes('定期') || text.includes('抄表') || text.includes('铭牌') || text.toLowerCase().includes('meter')) {
    return '定期量测/抄表/铭牌'
  }
  return '自行推估'
}

function normalizeFactorCategory(value?: string): FactorCategory {
  const text = String(value || '').trim()
  if (!text) return '国家排放因子'
  if (text.includes('国际') || text.toLowerCase().includes('international')) return '国际排放因子'
  if (text.includes('区域') || text.toLowerCase().includes('regional')) return '区域排放因子'
  return '国家排放因子'
}

function toApiActivityCategory(value: ActivityDataCategory): string {
  if (value === '自动连续监测') return 'continuous_monitoring'
  if (value === '定期量测/抄表/铭牌') return 'meter_reading'
  return 'estimate'
}

function toApiFactorCategory(value: FactorCategory): string {
  if (value === '国际排放因子') return 'international_factor'
  if (value === '区域排放因子') return 'regional_factor'
  return 'national_factor'
}

function syncGwpByGas(gas: GasType) {
  const v = gasDefaultGwp[gas]
  if (typeof v === 'number') {
    sourceForm.value.gwp = v
    return
  }
  sourceForm.value.gwp = null
}

function syncEmissionClassByScope(scope: number) {
  if (scope === 1) {
    sourceForm.value.emission_class = 'direct'
    return
  }
  if (scope === 2 || scope === 3) {
    sourceForm.value.emission_class = 'indirect'
    return
  }
  sourceForm.value.emission_class = ''
}

function resetCategoryDerivedFields() {
  sourceForm.value.unit = ''
  sourceForm.value.energy_type = '' as EnergyType
  sourceForm.value.consumption_type = '' as ConsumptionType
  sourceForm.value.manual_factor = ''
  sourceForm.value.manual_factor_source = ''
  selectedGas.value = ''
  sourceForm.value.gas = ''
  sourceForm.value.gwp = null
}

function syncFireExtinguisherFactorByName() {
  const factor = fireExtinguisherFactorMap[sourceForm.value.name]
  if (typeof factor !== 'number') {
    sourceForm.value.manual_factor = ''
    return
  }
  sourceForm.value.manual_factor = String(factor)
  sourceForm.value.manual_factor_source = '国际排放因子'
  useManualFactor.value = true
  if (sourceForm.value.name === '中央灭火系统') {
    selectedGas.value = 'FM200'
    sourceForm.value.gas = 'FM200'
    sourceForm.value.gwp = 2050
  } else if (sourceForm.value.name === '便携式灭火器') {
    selectedGas.value = 'CO2'
    sourceForm.value.gas = 'CO2'
    sourceForm.value.gwp = 1
  }
}

function syncRefrigerantFactorByName() {
  const factor = refrigerantFactorMap[sourceForm.value.name]
  if (typeof factor !== 'number') {
    sourceForm.value.manual_factor = ''
    return
  }
  sourceForm.value.manual_factor = String(factor)
  sourceForm.value.manual_factor_source = '国际排放因子'
  useManualFactor.value = true
}

function applyElectricityFactorBySelection() {
  const level = electricityFactorLevel.value
  const detail = electricityFactorDetail.value
  const factor = electricityFactorMap[level][detail]
  if (typeof factor === 'number') {
    useManualFactor.value = true
    sourceForm.value.manual_factor = String(factor)
    sourceForm.value.manual_factor_source = `${level}-${detail}`
  }
}

function restoreElectricityFactorSelectionFromSource(sourceText: string) {
  const text = sourceText || ''
  const [rawLevel, rawDetail] = text.split('-')
  const level = rawLevel as '国家' | '区域' | '省级'
  if (level && electricityFactorMap[level]) {
    electricityFactorLevel.value = level
    const details = Object.keys(electricityFactorMap[level])
    electricityFactorDetail.value = details.includes(rawDetail) ? rawDetail : details[0]
    applyElectricityFactorBySelection()
    return
  }
  electricityFactorLevel.value = '国家'
  electricityFactorDetail.value = '全国平均'
  applyElectricityFactorBySelection()
}

function resetSourceForm() {
  editingSourceId.value = null
  sourceForm.value = {
    scope: 0,
    category: '',
    name: '',
    activity_data: null,
    unit: '',
    gas: '',
    gwp: null,
    emission_class: '',
    ghg_category: '',
    energy_type: '',
    consumption_type: '',
    is_green_electricity: false,
    is_removal: false,
    is_storage: false,
    notes: '',
    manual_factor: '',
    manual_factor_source: '',
  }
  syncEmissionClassByScope(sourceForm.value.scope)
  selectedGas.value = ''
  customGasName.value = ''
  selectedCategory.value = ''
  customCategoryName.value = ''
  useManualFactor.value = false
  electricityFactorLevel.value = '国家'
  electricityFactorDetail.value = '全国平均'
  uncertaintyForm.value = {
    facility: '',
    activity_data_category: '',
    factor_category: '',
  }
  enableUncertainty.value = false
}

function startEditSource(item: EmissionSourceRead) {
  if (!canManage.value) {
    status.value = '当前账号无权限执行该操作。'
    return
  }
  editingSourceId.value = item.id
  sourceForm.value = {
    scope: item.scope,
    category: item.category,
    name: item.name,
    activity_data: item.activity_data,
    unit: item.unit,
    gas: item.gas,
    gwp: item.gwp,
    emission_class: item.emission_class,
    ghg_category: item.ghg_category || getDefaultGhgCategory(item.emission_class, item.category),
    energy_type: item.energy_type,
    consumption_type: item.consumption_type,
    is_green_electricity: item.is_green_electricity,
    is_removal: item.is_removal,
    is_storage: item.is_storage,
    notes: item.notes ?? '',
    manual_factor: '',
    manual_factor_source: '国家排放因子',
  }
  syncEmissionClassByScope(sourceForm.value.scope)

  if (gasOptions.some((g) => g.value === item.gas)) {
    selectedGas.value = item.gas as GasSelectType
    customGasName.value = ''
  } else {
    selectedGas.value = 'CUSTOM'
    customGasName.value = item.gas
  }
  const allowedForScope = getAvailableCategoryOptions(
    item.scope,
    item.emission_class,
    item.ghg_category || getDefaultGhgCategory(item.emission_class, item.category),
  )
  if (allowedForScope.includes(item.category)) {
    selectedCategory.value = item.category
    customCategoryName.value = ''
  } else {
    selectedCategory.value = 'CUSTOM'
    customCategoryName.value = item.category
  }

  if (item.uncertainties?.length) {
    uncertaintyForm.value = {
      facility: item.uncertainties[0].facility || item.name,
      activity_data_category: normalizeActivityCategory(item.uncertainties[0].activity_data_category),
      factor_category: normalizeFactorCategory(item.uncertainties[0].factor_category),
    }
    enableUncertainty.value = true
  } else {
    enableUncertainty.value = false
  }
  const factorSourceText = item.factor_source || ''
  if (factorSourceText.includes('自动匹配') || factorSourceText.includes('未匹配排放因子')) {
    useManualFactor.value = false
    sourceForm.value.manual_factor = ''
    sourceForm.value.manual_factor_source = ''
  } else {
    useManualFactor.value = true
    sourceForm.value.manual_factor = String(item.factor)
    sourceForm.value.manual_factor_source = factorSourceText || '手动输入'
    if (item.category === '外购电力') {
      restoreElectricityFactorSelectionFromSource(factorSourceText)
    }
  }
  status.value = `已加载排放源 ID=${item.id}，请在上方表单编辑后保存。`
  nextTick(() => {
    if (sourceFormPanelRef.value) {
      sourceFormPanelRef.value.open = true
      sourceFormPanelRef.value.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  })
}

function cancelEditSource() {
  resetSourceForm()
}

async function loadProjectOptions() {
  const projects = await callApi<ProjectRead[]>('/api/projects')

  projectOptions.value = projects.map((i) => ({ id: i.id, name: i.name }))

  if (projectOptions.value.length > 0 && !projectOptions.value.some((i) => i.id === projectId.value)) {
    projectId.value = projectOptions.value[0].id
  }
}

async function loadProjectAndSources() {
  if (!projectId.value) {
    status.value = '请先输入项目 ID。'
    return
  }

  await run(async () => {
    const [project, sourceList] = await Promise.all([
      callApi<ProjectRead>(`/api/projects/${projectId.value}`),
      callApi<EmissionSourceRead[]>(`/api/projects/${projectId.value}/emission-sources`),
    ])
    projectInfo.value = project
    sources.value = sourceList
    totals.value = loadTotalsCache(projectId.value)
  }, '项目与排放源已刷新。')
}

async function submitSourceForm() {
  if (editingSourceId.value !== null && !canManage.value) {
    status.value = '当前账号无权限执行该操作。'
    return
  }
  if (!projectId.value) {
    status.value = '请先输入项目 ID。'
    return
  }
  if (![1, 2, 3].includes(sourceForm.value.scope)) {
    status.value = '请选择 Scope。'
    return
  }
  if (!sourceForm.value.emission_class) {
    status.value = '请选择排放类型。'
    return
  }
  if (!sourceForm.value.ghg_category) {
    status.value = '请选择 GHG排放或移除类别。'
    return
  }
  if (!sourceForm.value.category.trim()) {
    status.value = '请选择或填写排放源类别。'
    return
  }
  if (!sourceForm.value.name.trim()) {
    status.value = '请填写排放源名称。'
    return
  }
  if (!sourceForm.value.unit.trim()) {
    status.value = '请填写活动数据单位。'
    return
  }
  if (sourceForm.value.activity_data === null || sourceForm.value.activity_data <= 0) {
    status.value = '活动数据量必须大于 0。'
    return
  }
  if (!sourceForm.value.gas.trim()) {
    status.value = '请选择温室气体。'
    return
  }
  if (!isScope1FuelCategory.value && sourceForm.value.gwp === null) {
    status.value = '请填写或选择 GWP。'
    return
  }
  if (selectedGas.value === 'CUSTOM' && !customGasName.value.trim()) {
    status.value = '请填写自定义气体名称。'
    return
  }
  if (useManualFactor.value && !isScope1FuelCategory.value) {
    const manualFactor = Number(sourceForm.value.manual_factor)
    if (!Number.isFinite(manualFactor) || manualFactor <= 0) {
      status.value = '手动因子值必须大于 0。'
      return
    }
  }

  const payload: Record<string, unknown> = {
    scope: sourceForm.value.scope,
    category: sourceForm.value.category.trim(),
    name: sourceForm.value.name.trim(),
    activity_data: sourceForm.value.activity_data,
    unit: sourceForm.value.unit.trim(),
    gas: sourceForm.value.gas,
    gwp: sourceForm.value.gwp ?? 1,
    emission_class: sourceForm.value.emission_class,
    ghg_category: sourceForm.value.ghg_category || getDefaultGhgCategory(sourceForm.value.emission_class, sourceForm.value.category),
    is_green_electricity: sourceForm.value.is_green_electricity,
    is_removal: sourceForm.value.is_removal,
    is_storage: sourceForm.value.is_storage,
  }

  if (sourceForm.value.energy_type) payload.energy_type = sourceForm.value.energy_type
  if (sourceForm.value.consumption_type) payload.consumption_type = sourceForm.value.consumption_type

  const notes = parseOptionalText(sourceForm.value.notes)
  if (notes) payload.notes = notes
  if (useManualFactor.value && !isScope1FuelCategory.value) {
    payload.factor = Number(sourceForm.value.manual_factor)
    payload.factor_source = parseOptionalText(sourceForm.value.manual_factor_source) || '手动输入'
  }

  if (enableUncertainty.value) {
    const normalizedActivity = normalizeActivityCategory(uncertaintyForm.value.activity_data_category)
    const normalizedFactor = normalizeFactorCategory(uncertaintyForm.value.factor_category)
    payload.uncertainties = [
      {
        facility: parseOptionalText(uncertaintyForm.value.facility),
        activity_data_category: toApiActivityCategory(normalizedActivity),
        factor_category: toApiFactorCategory(normalizedFactor),
        notes: '前端录入',
      },
    ]
  }

  await run(
    async () => {
      if (editingSourceId.value === null) {
        await callApi(`/api/projects/${projectId.value}/emission-sources`, 'POST', payload)
      } else {
        await callApi(`/api/projects/${projectId.value}/emission-sources/${editingSourceId.value}`, 'PUT', payload)
      }
      sources.value = await callApi<EmissionSourceRead[]>(`/api/projects/${projectId.value}/emission-sources`)
      if (editingSourceId.value !== null) {
        resetSourceForm()
      }
    },
    editingSourceId.value === null ? '新增排放源成功。' : '排放源修改成功。',
  )
}

async function deleteSource(sourceId: number) {
  if (!canManage.value) {
    status.value = '当前账号无权限执行该操作。'
    return
  }
  if (!window.confirm(`确认删除排放源 ID=${sourceId} 吗？`)) {
    return
  }

  await run(async () => {
    await callApi(`/api/projects/${projectId.value}/emission-sources/${sourceId}`, 'DELETE')
    sources.value = await callApi<EmissionSourceRead[]>(`/api/projects/${projectId.value}/emission-sources`)
    if (editingSourceId.value === sourceId) {
      resetSourceForm()
    }
  }, '排放源已删除。')
}

async function validateCurrentProject() {
  if (!projectId.value) {
    status.value = '请先输入项目 ID。'
    return
  }

  await run(async () => {
    validation.value = await callApi<ValidationResult>(`/api/projects/${projectId.value}/validate`, 'POST')
  }, '数据校验已完成。')
}

async function calculateCurrentProject() {
  if (!projectId.value) {
    status.value = '请先输入项目 ID。'
    return
  }

  await run(async () => {
    totals.value = await callApi<CalculationResult>(`/api/projects/${projectId.value}/calculate`, 'POST')
    saveTotalsCache(projectId.value, totals.value)
    sources.value = await callApi<EmissionSourceRead[]>(`/api/projects/${projectId.value}/emission-sources`)
  }, '自动核算已完成。')
}

async function run(action: () => Promise<void>, successText: string) {
  try {
    await action()
    status.value = successText
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    status.value = `操作失败：${message}`
    console.error(error)
  }
}

onMounted(() => {
  run(async () => {
    await loadProjectOptions()
    await loadProjectAndSources()
  }, '项目列表加载完成。')
})

watch(
  () => projectId.value,
  async (project) => {
    totals.value = loadTotalsCache(project)
    await loadProjectAndSources()
  },
)

watch(
  () => selectedGas.value,
  (gas) => {
    if (gas === 'CUSTOM') {
      sourceForm.value.gas = customGasName.value.trim() || 'OTHER'
      return
    }
    if (!gas) {
      sourceForm.value.gas = ''
      sourceForm.value.gwp = null
      return
    }
    sourceForm.value.gas = gas
    syncGwpByGas(gas)
  },
)

watch(
  () => customGasName.value,
  (name) => {
    if (selectedGas.value === 'CUSTOM') {
      sourceForm.value.gas = name.trim() || 'OTHER'
    }
  },
)

watch(
  () => selectedCategory.value,
  (category) => {
    if (!category) {
      sourceForm.value.category = ''
      resetCategoryDerivedFields()
      syncCategorySelectionToGhGRule()
      return
    }
    if (category === 'CUSTOM') {
      resetCategoryDerivedFields()
      sourceForm.value.category = customCategoryName.value.trim() || ''
      return
    }

    resetCategoryDerivedFields()
    sourceForm.value.category = category

    if (category === '外购电力') {
      sourceForm.value.unit = 'MWh'
      sourceForm.value.energy_type = 'electricity'
      sourceForm.value.consumption_type = 'purchased'
      selectedGas.value = 'CO2'
      sourceForm.value.gas = 'CO2'
      sourceForm.value.gwp = 1
      electricityFactorLevel.value = '国家'
      electricityFactorDetail.value = '全国平均'
      applyElectricityFactorBySelection()
      return
    }
    if (category === '外购热力') {
      sourceForm.value.unit = 'GJ'
      sourceForm.value.energy_type = 'heat'
      sourceForm.value.consumption_type = 'purchased'
      selectedGas.value = 'CO2'
      sourceForm.value.gas = 'CO2'
      sourceForm.value.gwp = 1
      useManualFactor.value = true
      sourceForm.value.manual_factor_source = '国家排放因子'
      sourceForm.value.manual_factor = '0.11'
      return
    }
    if (scope1FuelCategories.includes(category)) {
      sourceForm.value.energy_type = 'fuel'
      sourceForm.value.consumption_type = 'purchased'
      selectedGas.value = 'CO2'
      sourceForm.value.gas = 'CO2'
      sourceForm.value.gwp = 1
      sourceForm.value.manual_factor = '-'
      if (category === '汽油' || category === '柴油') {
        sourceForm.value.unit = 'kg'
      }
      if (category === '天然气') {
        sourceForm.value.unit = 'm³'
      }
      return
    }
    if (category === '灭火器逸散') {
      sourceForm.value.unit = 'kg'
      sourceForm.value.name = ''
      selectedGas.value = 'CO2'
      sourceForm.value.gas = 'CO2'
      sourceForm.value.gwp = 1
      sourceForm.value.manual_factor_source = '国际排放因子'
      useManualFactor.value = true
      sourceForm.value.manual_factor = ''
      return
    }
    if (category === '制冷剂逸散') {
      sourceForm.value.unit = 'kg'
      sourceForm.value.name = ''
      sourceForm.value.manual_factor_source = '国际排放因子'
      useManualFactor.value = true
      sourceForm.value.manual_factor = ''
      return
    }
  },
)

watch(
  () => sourceForm.value.name,
  () => {
    if (isFireExtinguisherCategory.value) {
      syncFireExtinguisherFactorByName()
      return
    }
    if (isRefrigerantCategory.value) {
      syncRefrigerantFactorByName()
    }
  },
)

watch(
  () => sourceForm.value.ghg_category,
  () => {
    applyGhgCategoryLock()
    syncCategorySelectionToGhGRule(true)
  },
)

watch(
  () => customCategoryName.value,
  (name) => {
    if (selectedCategory.value === 'CUSTOM') {
      sourceForm.value.category = name.trim()
    }
  },
)

watch(
  () => useManualFactor.value,
  (enabled) => {
    if (!enabled) {
      sourceForm.value.manual_factor = ''
      sourceForm.value.manual_factor_source = '国家排放因子'
    }
  },
)

watch(
  () => electricityFactorLevel.value,
  () => {
    const details = Object.keys(electricityFactorMap[electricityFactorLevel.value])
    if (!details.includes(electricityFactorDetail.value)) {
      electricityFactorDetail.value = details[0]
    }
    if (selectedCategory.value === '外购电力') {
      applyElectricityFactorBySelection()
    }
  },
)

watch(
  () => electricityFactorDetail.value,
  () => {
    if (selectedCategory.value === '外购电力') {
      applyElectricityFactorBySelection()
    }
  },
)

watch(
  () => sourceForm.value.scope,
  (scope) => {
    syncEmissionClassByScope(scope)
    sourceForm.value.ghg_category = ''
    if (editingSourceId.value === null) {
      sourceForm.value.activity_data = null
      selectedCategory.value = ''
      sourceForm.value.category = ''
      sourceForm.value.unit = ''
      sourceForm.value.energy_type = '' as EnergyType
      sourceForm.value.consumption_type = '' as ConsumptionType
      sourceForm.value.manual_factor_source = ''
      sourceForm.value.manual_factor = ''
    }
    if (selectedCategory.value === 'CUSTOM') {
      syncCategorySelectionToGhGRule(true)
      return
    }
    const current = String(selectedCategory.value || '')
    if (current === '') {
      return
    }
    const allowed = getAvailableCategoryOptions(scope, sourceForm.value.emission_class, sourceForm.value.ghg_category)
    if (!allowed.includes(current)) {
      selectedCategory.value = ''
      sourceForm.value.category = ''
    }
  },
)
</script>

<style scoped>
.calc-page {
  display: grid;
}

.calc-shell {
  border: 1px solid #d6deeb;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 10px 22px rgb(15 23 42 / 8%);
  overflow: hidden;
}

.calc-head {
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
  background: rgb(255 255 255 / 22%);
  font-size: 14px;
  font-weight: 700;
}

.calc-head h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
}

.calc-head p {
  margin: 4px 0 0;
  font-size: 14px;
  color: #d8e8ff;
}

.calc-body {
  padding: 18px 26px 22px;
  display: grid;
  gap: 12px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.field {
  border: 1px solid #cfd7e3;
  border-radius: 8px;
  min-height: 40px;
  padding: 8px 10px;
}

.category-custom-input {
  padding-right: 36px;
  background-color: #fff;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'%3E%3Cpath fill='%236b7280' d='M4.47 6.97a.75.75 0 0 1 1.06 0L8 9.44l2.47-2.47a.75.75 0 1 1 1.06 1.06l-3 3a.75.75 0 0 1-1.06 0l-3-3a.75.75 0 0 1 0-1.06Z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  background-size: 14px 14px;
}

button {
  border-radius: 0.75rem;
  height: 2.5rem;
  padding: 0 1rem;
  font-size: 0.875rem;
  cursor: pointer;
}

.primary {
  border: 1px solid #1d4ed8;
  background: #2563eb;
  color: #fff;
}

.primary:hover {
  background: #1d4ed8;
}

.secondary {
  border: 1px solid #93c5fd;
  background: #f8fbff;
  color: #1d4ed8;
}

.secondary:hover {
  background: #eff6ff;
}

.report-btn {
  border: 1px solid #16a34a;
  background: #16a34a;
  color: #fff;
}

.report-btn:hover {
  background: #15803d;
}

.project-select {
  width: 340px;
  max-width: 100%;
}

.search-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.source-search {
  width: 360px;
  max-width: 100%;
}

.project-card {
  border: 1px solid #d8e1ee;
  border-radius: 8px;
  background: #f8fafc;
  padding: 12px 14px;
}

.project-card h3 {
  margin: 0;
  color: #0f4f96;
  font-size: 18px;
}

.project-card p {
  margin: 6px 0 0;
  color: #4a5c73;
  font-size: 14px;
}

.source-form-card {
  border: 1px solid #d8e1ee;
  border-radius: 8px;
  background: #fff;
  padding: 10px 12px 12px;
}

.source-form-card summary {
  cursor: pointer;
  color: #1d4f91;
  font-size: 14px;
  font-weight: 600;
}

.form-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px 12px;
}

.extra-grid {
  margin-top: 8px;
}

.form-grid label,
.uncertainty-grid label {
  display: grid;
  gap: 5px;
  font-size: 12px;
  color: #475569;
}

.notes-label {
  margin-top: 10px;
  display: grid;
  gap: 5px;
  font-size: 12px;
  color: #475569;
}

.notes-area {
  min-height: 72px;
  border: 1px solid #cfd7e3;
  border-radius: 8px;
  padding: 8px 10px;
  resize: vertical;
}

.flags-row {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  color: #334155;
  font-size: 13px;
}

.uncertainty-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px 12px;
}

.form-action-row {
  margin-top: 12px;
  display: flex;
  gap: 10px;
}

.table-card {
  border: 1px solid #d8e0ea;
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

tbody tr:hover {
  background: #f8fbff;
}

.co2e {
  color: #0b4ea2;
  font-weight: 700;
}

.muted {
  color: #64748b;
}

.factor-line + .factor-line {
  margin-top: 2px;
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

.mini.danger {
  border: 1px solid #dc2626;
  background: #dc2626;
  color: #fff;
}

.mini.danger:hover {
  background: #b91c1c;
}

.totals-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.metric-card {
  border: 1px solid #d8e1ee;
  border-radius: 8px;
  background: #f8fafc;
  padding: 10px 12px;
}

.metric-card span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.metric-card strong {
  display: block;
  margin-top: 6px;
  color: #1e3a5f;
  font-size: 16px;
}

.warn-box {
  border: 1px solid #f1c490;
  border-radius: 8px;
  background: #fff6ec;
  color: #cf612b;
  padding: 10px 12px;
  font-size: 13px;
}

.warn-box p {
  margin: 0;
}

.status {
  margin: 0;
  font-size: 13px;
  color: #4b6790;
}

@media (max-width: 1280px) {
  .form-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .totals-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 980px) {
  .form-grid,
  .uncertainty-grid,
  .totals-grid {
    grid-template-columns: 1fr;
  }
}
</style>





