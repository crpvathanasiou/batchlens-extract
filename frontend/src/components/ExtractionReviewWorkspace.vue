<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  createExtractionReviewApi,
  type ExtractionFinding,
  type ExtractionJobSummary,
  type ExtractionReviewOptions,
  type OpenedExtractionReview,
  type PageEdit,
} from '../extractionReview'

const props = defineProps<{ options: ExtractionReviewOptions }>()
const api = createExtractionReviewApi(props.options.apiBaseUrl)

const COMPONENT_OPTIONS = [
  ['unit_operations', 'Unit operation'],
  ['process_steps', 'Process step'],
  ['materials', 'Material'],
  ['equipment', 'Equipment'],
  ['parameter_names', 'Parameter'],
  ['units', 'Unit'],
  ['quantity_expressions', 'Quantity'],
  ['parameter_value_expressions', 'Parameter value'],
] as const

const jobs = ref<ExtractionJobSummary[]>([])
const review = ref<OpenedExtractionReview | null>(null)
const activePage = ref<number | null>(null)
const pageHtml = ref('')
const viewMode = ref<'page' | 'all'>('page')
const selectedFindingId = ref<string | null>(null)
const drafts = ref<Record<string, PageEdit>>({})
const errorMessage = ref('')
const busy = ref(false)
const addText = ref('')
const addComponent = ref<string>('materials')
const pageRoot = ref<HTMLElement | null>(null)

const dirty = computed(() => Object.keys(drafts.value).length > 0)
const approvalLabel = computed(() => (review.value?.approval_state === 'approved' ? 'Approved' : 'Not approved'))
const pages = computed(() => review.value?.pages ?? [])
const pageIndex = computed(() => pages.value.indexOf(activePage.value ?? -1))

interface FindingRow {
  finding_id: string
  component: string
  display_text: string
  page_number: number | null
  removed: boolean
  origin_kind: string
  original_matched_text: string | null
  evidence_status: string | null
  added_by_user: boolean
  changed_by_user: boolean
  removed_by_user: boolean
}

const rows = computed<FindingRow[]>(() => {
  const server = review.value?.findings ?? []
  const next = server.map((finding) => rowFromFinding(finding))
  for (const draft of Object.values(drafts.value)) {
    if (draft.op === 'add') {
      next.push({
        finding_id: draft.finding_id,
        component: draft.component,
        display_text: draft.display_text,
        page_number: draft.page_number,
        removed: false,
        origin_kind: 'user_added',
        original_matched_text: null,
        evidence_status: 'no_document_evidence',
        added_by_user: true,
        changed_by_user: false,
        removed_by_user: false,
      })
      continue
    }
    const row = next.find((item) => item.finding_id === draft.finding_id)
    if (!row) continue
    if (draft.op === 'remove') {
      row.removed = true
      row.removed_by_user = true
      continue
    }
    row.display_text = draft.display_text
    row.changed_by_user = true
    if (draft.op === 'replace') row.component = draft.component
  }
  return next
})

const pageRows = computed(() => rows.value.filter((row) => row.page_number === activePage.value))
const visibleRows = computed(() => (viewMode.value === 'all' ? rows.value : pageRows.value))

function rowFromFinding(finding: ExtractionFinding): FindingRow {
  return {
    finding_id: finding.finding_id,
    component: finding.component ?? '',
    display_text: finding.display_text ?? finding.original_matched_text ?? 'Removed finding',
    page_number: finding.page_number,
    removed: finding.removed,
    origin_kind: finding.origin_kind,
    original_matched_text: finding.original_matched_text,
    evidence_status: finding.evidence_status,
    added_by_user: finding.added_by_user,
    changed_by_user: finding.changed_by_user,
    removed_by_user: finding.removed_by_user,
  }
}

function componentLabel(component: string): string {
  return COMPONENT_OPTIONS.find(([value]) => value === component)?.[1] ?? component
}

function provenanceLabel(row: FindingRow): string {
  const parts: string[] = []
  if (row.removed || row.removed_by_user) parts.push('Removed')
  if (row.added_by_user && !row.removed) parts.push('Added')
  if (row.changed_by_user && !row.removed) parts.push('Changed')
  if (
    row.original_matched_text
    && row.original_matched_text !== row.display_text
    && !row.removed
  ) {
    parts.push(`Source: ${row.original_matched_text}`)
  }
  if (row.evidence_status === 'no_document_evidence') parts.push('No document evidence')
  return parts.join(' · ')
}

function jobLabel(job: ExtractionJobSummary): string {
  return `${job.job_id} · ${job.action.replaceAll('_', ' ')} · ${job.extraction_overall}`
}

async function loadJobs() {
  jobs.value = (await api.listJobs()).jobs
}

async function selectJob(localJobId: string) {
  errorMessage.value = ''
  drafts.value = {}
  selectedFindingId.value = null
  viewMode.value = 'page'
  const opened = await api.openJob(localJobId)
  review.value = opened
  const first = opened.pages[0] ?? null
  if (activePage.value === first) await loadPage()
  else activePage.value = first
}

async function loadPage() {
  if (!review.value || activePage.value == null) {
    pageHtml.value = ''
    return
  }
  const page = await api.page(review.value.local_job_id, activePage.value)
  pageHtml.value = page.html
}

function setPage(page: number) {
  if (pages.value.includes(page)) activePage.value = page
}

function selectFinding(row: FindingRow) {
  selectedFindingId.value = row.finding_id
  if (viewMode.value === 'all') {
    viewMode.value = 'page'
    if (row.page_number != null) activePage.value = row.page_number
  }
}

function updateRow(row: FindingRow, displayText: string, component: string) {
  const server = review.value?.findings.find((finding) => finding.finding_id === row.finding_id)
  if (!server) {
    const draft = drafts.value[row.finding_id]
    if (draft?.op === 'add') {
      drafts.value = {
        ...drafts.value,
        [row.finding_id]: { ...draft, display_text: displayText, component },
      }
    }
    return
  }
  if (row.page_number == null) return
  const textChanged = displayText !== (server.display_text ?? '')
  const componentChanged = component !== (server.component ?? '')
  if (!textChanged && !componentChanged) {
    const rest = { ...drafts.value }
    delete rest[row.finding_id]
    drafts.value = rest
    return
  }
  const edit: PageEdit = componentChanged
    ? {
        op: 'replace',
        finding_id: row.finding_id,
        page_number: row.page_number,
        component,
        display_text: displayText,
      }
    : {
        op: 'patch_text',
        finding_id: row.finding_id,
        page_number: row.page_number,
        display_text: displayText,
      }
  drafts.value = { ...drafts.value, [row.finding_id]: edit }
}

function removeRow(row: FindingRow) {
  if (row.page_number == null) return
  const draft = drafts.value[row.finding_id]
  if (draft?.op === 'add') {
    const rest = { ...drafts.value }
    delete rest[row.finding_id]
    drafts.value = rest
    return
  }
  drafts.value = {
    ...drafts.value,
    [row.finding_id]: { op: 'remove', finding_id: row.finding_id, page_number: row.page_number },
  }
}

function addFinding() {
  const text = addText.value.trim()
  if (!text || activePage.value == null) return
  const findingId = crypto.randomUUID()
  drafts.value = {
    ...drafts.value,
    [findingId]: {
      op: 'add',
      finding_id: findingId,
      page_number: activePage.value,
      component: addComponent.value,
      display_text: text,
    },
  }
  addText.value = ''
}

async function save() {
  if (!review.value || !dirty.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    review.value = await api.save(
      review.value.local_job_id,
      review.value.current_revision_id,
      Object.values(drafts.value),
    )
    drafts.value = {}
    await loadPage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Save failed'
  } finally {
    busy.value = false
  }
}

async function approve() {
  if (!review.value) return
  if (dirty.value) {
    errorMessage.value = 'Save the current extraction result before approval.'
    return
  }
  busy.value = true
  errorMessage.value = ''
  try {
    review.value = await api.approve(review.value.local_job_id, review.value.current_revision_id)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Approval failed'
  } finally {
    busy.value = false
  }
}

let renderedRoot: HTMLElement | null = null
let renderedPageHtml = ''

function focusSelected() {
  const root = pageRoot.value
  if (!root) return
  if (root !== renderedRoot || renderedPageHtml !== pageHtml.value) {
    root.innerHTML = pageHtml.value
    renderedRoot = root
    renderedPageHtml = pageHtml.value
  }
  root.querySelectorAll('.bl-hit--focus').forEach((mark) => mark.classList.remove('bl-hit--focus'))
  const removed = new Set(
    Object.values(drafts.value)
      .filter((draft) => draft.op === 'remove')
      .map((draft) => draft.finding_id),
  )
  root.querySelectorAll<HTMLElement>('.bl-hit').forEach((mark) => {
    const ids = (mark.dataset.findingId ?? '').split(' ').filter(Boolean)
    mark.classList.toggle('bl-hit--hidden', ids.length > 0 && ids.every((id) => removed.has(id)))
  })
  const findingId = selectedFindingId.value
  if (!findingId) return
  const escaped = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(findingId) : findingId
  const marks = root.querySelectorAll<HTMLElement>(`[data-finding-id~="${escaped}"]`)
  marks.forEach((mark) => mark.classList.add('bl-hit--focus'))
  const target = marks[0]
  if (target && typeof target.scrollIntoView === 'function') {
    target.scrollIntoView({ block: 'center', inline: 'nearest' })
  }
  target?.focus()
}

watch(activePage, (page, previous) => {
  if (page !== previous) void loadPage()
})
watch([selectedFindingId, drafts, pageHtml], () => {
  void focusSelected()
}, { flush: 'post' })

void loadJobs().catch((error: unknown) => {
  errorMessage.value = error instanceof Error ? error.message : 'Extraction jobs could not be loaded'
})
</script>

<template>
  <main class="bl-review">
    <header class="bl-topbar">
      <div class="bl-title">
        <strong>Extraction review</strong>
        <span v-if="options.demoLabel" class="bl-demo-label">{{ options.demoLabel }}</span>
        <span v-if="review" class="bl-statuses">
          <span class="bl-chip">{{ approvalLabel }}</span>
          <span v-if="dirty" class="bl-chip bl-chip--changed">Unsaved</span>
          <span class="bl-chip">Extraction: {{ review.extraction_overall }}</span>
        </span>
      </div>
      <label class="bl-job-picker">
        <span class="bl-sr-only">Extraction job</span>
        <select
          aria-label="Extraction job"
          :value="review?.local_job_id ?? ''"
          @change="selectJob(($event.target as HTMLSelectElement).value)"
        >
          <option value="" disabled>Select a completed extraction job</option>
          <option v-for="job in jobs" :key="job.local_job_id" :value="job.local_job_id">
            {{ jobLabel(job) }}
          </option>
        </select>
      </label>
      <div class="bl-actions">
        <button type="button" class="bl-button" :disabled="busy || !dirty" @click="save">Save</button>
        <button
          type="button"
          class="bl-button bl-button--primary"
          :disabled="busy || !review || dirty"
          @click="approve"
        >
          Approve extraction result
        </button>
      </div>
    </header>

    <p v-if="dirty" class="bl-banner">Save before approval. Unsaved edits are not included.</p>
    <p v-if="errorMessage" class="bl-banner bl-banner--error" role="alert">{{ errorMessage }}</p>
    <p v-if="jobs.length === 0" class="bl-loading">No completed extraction jobs.</p>

    <template v-if="review && activePage != null">
      <nav class="bl-pagebar" aria-label="Page navigation">
        <button type="button" aria-label="Previous page" :disabled="pageIndex <= 0" @click="setPage(pages[pageIndex - 1])">‹</button>
        <label>
          <span class="bl-sr-only">Select page</span>
          <select aria-label="Select page" :value="activePage" @change="setPage(Number(($event.target as HTMLSelectElement).value))">
            <option v-for="page in pages" :key="page" :value="page">Page {{ page }}</option>
          </select>
        </label>
        <span>of {{ pages.length }}</span>
        <button type="button" aria-label="Next page" :disabled="pageIndex >= pages.length - 1" @click="setPage(pages[pageIndex + 1])">›</button>
        <span class="bl-page-dots">
          <i
            v-for="page in pages"
            :key="page"
            :class="{ active: page === activePage }"
            @click="setPage(page)"
          />
        </span>
      </nav>

      <div class="bl-workspace-grid">
        <section class="bl-html-page" aria-label="Reviewed page" ref="pageRoot" />
        <aside class="bl-findings" aria-label="Extraction findings">
          <header class="bl-findings__toolbar">
            <button type="button" :aria-pressed="viewMode === 'page'" @click="viewMode = 'page'">By page</button>
            <button type="button" :aria-pressed="viewMode === 'all'" @click="viewMode = 'all'">All findings</button>
          </header>
          <ul class="bl-hit-legend">
            <li><span class="bl-swatch bl-hit--unit-operation">UO</span> Unit operation</li>
            <li><span class="bl-swatch bl-hit--material">MAT</span> Material</li>
            <li><span class="bl-swatch bl-hit--equipment">EQ</span> Equipment</li>
            <li><span class="bl-swatch bl-hit--other">Other</span> Other lexical category</li>
          </ul>
          <form v-if="viewMode === 'page'" class="bl-add-finding" @submit.prevent="addFinding">
            <label>
              New finding text
              <input v-model="addText" aria-label="New finding text" />
            </label>
            <label>
              Category
              <select v-model="addComponent" aria-label="New finding category">
                <option v-for="[value, label] in COMPONENT_OPTIONS" :key="value" :value="value">{{ label }}</option>
              </select>
            </label>
            <button type="submit" class="bl-button">Add finding</button>
          </form>
          <ol class="bl-finding-list">
            <li v-for="row in visibleRows" :key="row.finding_id" :class="{ 'is-removed': row.removed }">
              <button
                type="button"
                class="bl-finding-select"
                :aria-current="selectedFindingId === row.finding_id ? 'true' : undefined"
                @click="selectFinding(row)"
              >
                <span class="bl-finding-label">{{ componentLabel(row.component) || 'Finding' }}</span>
                <span>{{ row.display_text }}</span>
                <small v-if="viewMode === 'all' && row.page_number">Page {{ row.page_number }}</small>
              </button>
              <p v-if="provenanceLabel(row)" class="bl-muted">{{ provenanceLabel(row) }}</p>
              <div v-if="viewMode === 'page' && !row.removed" class="bl-finding-edit">
                <label>
                  Display text
                  <input
                    :aria-label="`Display text ${row.finding_id}`"
                    :value="row.display_text"
                    @change="updateRow(row, ($event.target as HTMLInputElement).value, row.component)"
                  />
                </label>
                <label>
                  Category
                  <select
                    :aria-label="`Category ${row.finding_id}`"
                    :value="row.component"
                    @change="updateRow(row, row.display_text, ($event.target as HTMLSelectElement).value)"
                  >
                    <option v-for="[value, label] in COMPONENT_OPTIONS" :key="value" :value="value">{{ label }}</option>
                  </select>
                </label>
                <button type="button" class="bl-button" @click="removeRow(row)">Remove</button>
              </div>
            </li>
          </ol>
        </aside>
      </div>
    </template>
  </main>
</template>
