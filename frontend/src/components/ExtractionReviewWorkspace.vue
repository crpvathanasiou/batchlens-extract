<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import {
  STAGE4_POLL_INTERVAL_MS,
  buildPageClassificationsTsv,
  createExtractionReviewApi,
  isTerminalClassificationStatus,
  isTerminalLexicalStatus,
  pageClassificationsDownloadFilename,
  type ApprovedDocumentSummary,
  type ClassificationStateView,
  type ExtractionFinding,
  type ExtractionJobSummary,
  type ExtractionReviewOptions,
  type LexicalJobStatus,
  type OpenedExtractionReview,
  type PageClassificationView,
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

const HIT_CLASS: Record<string, string> = {
  unit_operations: 'bl-hit--unit-operation',
  materials: 'bl-hit--material',
  equipment: 'bl-hit--equipment',
}

type LegendCategory = 'unit_operations' | 'materials' | 'equipment' | 'other'

const LEGEND_CATEGORIES: ReadonlyArray<{
  id: LegendCategory
  short: string
  label: string
  hitClass: string
}> = [
  { id: 'unit_operations', short: 'UO', label: 'Unit operation', hitClass: 'bl-hit--unit-operation' },
  { id: 'materials', short: 'MAT', label: 'Material', hitClass: 'bl-hit--material' },
  { id: 'equipment', short: 'EQ', label: 'Equipment', hitClass: 'bl-hit--equipment' },
  { id: 'other', short: 'Other', label: 'Other lexical category', hitClass: 'bl-hit--other' },
]

const documents = ref<ApprovedDocumentSummary[]>([])
const selectedDocumentKey = ref('')
const documentPages = ref<number[]>([])
const currentClassification = ref<ClassificationStateView | null>(null)
const jobClassification = ref<ClassificationStateView | null>(null)
const lexicalStatus = ref<LexicalJobStatus | null>(null)
const noEligibleMessage = ref('')
const stage4Busy = ref(false)

const jobs = ref<ExtractionJobSummary[]>([])
const review = ref<OpenedExtractionReview | null>(null)
const activePage = ref<number | null>(null)
const pageHtml = ref('')
const viewMode = ref<'page' | 'all'>('page')
const selectedFindingId = ref<string | null>(null)
const drafts = ref<Record<string, PageEdit>>({})
const hiddenCategories = ref<Partial<Record<LegendCategory, true>>>({})
const errorMessage = ref('')
const busy = ref(false)
const pageRoot = ref<HTMLElement | null>(null)
const renderedRoot = ref<HTMLElement | null>(null)
const renderedPageHtml = ref('')

let pollTimer: ReturnType<typeof setInterval> | null = null

const dirty = computed(() => Object.keys(drafts.value).length > 0)
const approvalLabel = computed(() => (review.value?.approval_state === 'approved' ? 'Approved' : 'Not approved'))
const pages = computed(() => {
  if (review.value) return review.value.pages
  return documentPages.value
})
const pageIndex = computed(() => pages.value.indexOf(activePage.value ?? -1))
const downloadDisabledReason = computed(() =>
  dirty.value ? 'Save before approval. Unsaved edits are not included.' : '',
)

const classificationRunning = computed(() => currentClassification.value?.status === 'running')
const classificationTerminal = computed(() =>
  isTerminalClassificationStatus(currentClassification.value?.status),
)
const canClassify = computed(
  () =>
    Boolean(selectedDocumentKey.value)
    && !currentClassification.value
    && !classificationRunning.value
    && !stage4Busy.value
    && !lexicalNonTerminal.value,
)
const canExtractAll = computed(
  () =>
    Boolean(selectedDocumentKey.value)
    && classificationTerminal.value
    && !classificationRunning.value
    && !stage4Busy.value
    && !lexicalNonTerminal.value,
)
const lexicalNonTerminal = computed(() => {
  const status = lexicalStatus.value?.status
  return Boolean(status) && !isTerminalLexicalStatus(status)
})

const displayedClassification = computed<ClassificationStateView | null>(() => {
  if (review.value?.classification) return review.value.classification
  if (jobClassification.value) return jobClassification.value
  return currentClassification.value
})

const canDownloadClassifications = computed(
  () =>
    Boolean(selectedDocumentKey.value)
    && displayedClassification.value != null
    && pages.value.length > 0,
)

const activePageClassification = computed<PageClassificationView | null>(() => {
  const state = displayedClassification.value
  if (!state || activePage.value == null) return null
  return state.pages.find((page) => page.page_number === activePage.value) ?? null
})

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
  isLocalDraft: boolean
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
        isLocalDraft: true,
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
    if (draft.op === 'restore') {
      row.removed = false
      row.removed_by_user = false
      continue
    }
    row.display_text = draft.display_text
    row.changed_by_user = true
    if (draft.op === 'replace') row.component = draft.component
  }
  return next
})

const pageRows = computed(() => rows.value.filter((row) => row.page_number === activePage.value))
const visibleRows = computed(() => {
  const base = viewMode.value === 'all'
    ? rows.value.filter((row) => !row.removed)
    : pageRows.value
  return base.filter((row) => !isCategoryHidden(legendCategory(row.component)))
})

function documentKey(doc: ApprovedDocumentSummary): string {
  return `${doc.job_id}::${doc.review_revision_id}`
}

function parseDocumentKey(key: string): ApprovedDocumentSummary | null {
  const index = key.indexOf('::')
  if (index <= 0) return null
  return {
    job_id: key.slice(0, index),
    review_revision_id: key.slice(index + 2),
  }
}

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
    isLocalDraft: false,
  }
}

function componentLabel(component: string): string {
  return COMPONENT_OPTIONS.find(([value]) => value === component)?.[1] ?? component
}

function hitClass(component: string): string {
  return HIT_CLASS[component] ?? 'bl-hit--other'
}

function legendCategory(component: string): LegendCategory {
  if (component === 'unit_operations' || component === 'materials' || component === 'equipment') {
    return component
  }
  return 'other'
}

function isCategoryHidden(category: LegendCategory): boolean {
  return hiddenCategories.value[category] === true
}

function toggleCategoryVisibility(category: LegendCategory) {
  const next = { ...hiddenCategories.value }
  if (next[category]) delete next[category]
  else next[category] = true
  hiddenCategories.value = next
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
  if (row.isLocalDraft) parts.push('Unsaved draft')
  return parts.join(' · ')
}

function jobLabel(job: ExtractionJobSummary): string {
  const action = job.action.replaceAll('_', ' ')
  const status = job.extraction_overall
  const finished = job.finished_at ? ` · ${job.finished_at}` : ''
  const suffix = job.local_job_id.slice(-8)
  return `${action} · ${status}${finished} · ${suffix}`
}

function documentLabel(doc: ApprovedDocumentSummary): string {
  return `${doc.job_id} / ${doc.review_revision_id}`
}

function clearPolling() {
  if (pollTimer != null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function syncPolling() {
  clearPolling()
  const needsClassificationPoll = currentClassification.value?.status === 'running'
  const needsLexicalPoll = lexicalNonTerminal.value
  if (!needsClassificationPoll && !needsLexicalPoll) return
  pollTimer = setInterval(() => {
    void pollStage4()
  }, STAGE4_POLL_INTERVAL_MS)
}

async function pollStage4() {
  try {
    if (currentClassification.value?.status === 'running') {
      const selected = parseDocumentKey(selectedDocumentKey.value)
      if (selected) {
        const envelope = await api.getClassification(selected.job_id, selected.review_revision_id)
        currentClassification.value = envelope.classification
        if (isTerminalClassificationStatus(envelope.classification?.status)) {
          // Keep terminal state visible; Extract All becomes available.
        }
      }
    }
    if (lexicalStatus.value && !isTerminalLexicalStatus(lexicalStatus.value.status)) {
      const status = await api.localJobStatus(lexicalStatus.value.local_job_id)
      lexicalStatus.value = status
      if (isTerminalLexicalStatus(status.status) && status.reviewable) {
        await loadJobs()
        await selectJob(status.local_job_id)
      }
    }
  } catch (error) {
    clearPolling()
    errorMessage.value = error instanceof Error ? error.message : 'Status refresh failed'
  } finally {
    syncPolling()
  }
}

async function loadJobs() {
  jobs.value = (await api.listJobs()).jobs
  const initial = props.options.initialLocalJobId
  if (initial && jobs.value.some((job) => job.local_job_id === initial)) {
    await selectJob(initial)
  }
}

async function loadDocuments() {
  try {
    documents.value = (await api.listApprovedDocuments()).documents
  } catch {
    documents.value = []
  }
}

async function selectDocument(key: string) {
  const previousKey = selectedDocumentKey.value
  if (
    dirty.value
    && review.value
    && key !== previousKey
  ) {
    errorMessage.value = 'Save the current extraction result before switching documents.'
    return
  }

  clearPolling()
  noEligibleMessage.value = ''

  const selected = parseDocumentKey(key)
  if (!selected) {
    selectedDocumentKey.value = key
    review.value = null
    jobClassification.value = null
    drafts.value = {}
    selectedFindingId.value = null
    lexicalStatus.value = null
    currentClassification.value = null
    documentPages.value = []
    activePage.value = null
    pageHtml.value = ''
    return
  }

  const leavingOpenReview = Boolean(
    review.value
    && key !== documentKey({
      job_id: review.value.job_id,
      review_revision_id: review.value.review_revision_id,
    }),
  )
  if (leavingOpenReview) {
    review.value = null
    jobClassification.value = null
    drafts.value = {}
    selectedFindingId.value = null
    lexicalStatus.value = null
    viewMode.value = 'page'
  }

  selectedDocumentKey.value = key
  currentClassification.value = null
  stage4Busy.value = true
  errorMessage.value = ''
  try {
    const pagesResponse = await api.approvedDocumentPages(selected.job_id, selected.review_revision_id)
    documentPages.value = pagesResponse.pages
    activePage.value = pagesResponse.pages[0] ?? null
    const envelope = await api.getClassification(selected.job_id, selected.review_revision_id)
    currentClassification.value = envelope.classification
    await loadPage()
    syncPolling()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Approved document could not be loaded'
  } finally {
    stage4Busy.value = false
  }
}

async function selectJob(localJobId: string) {
  errorMessage.value = ''
  drafts.value = {}
  selectedFindingId.value = null
  viewMode.value = 'page'
  noEligibleMessage.value = ''
  clearPolling()
  const opened = await api.openJob(localJobId)
  review.value = opened
  jobClassification.value = opened.classification ?? null
  selectedDocumentKey.value = documentKey({
    job_id: opened.job_id,
    review_revision_id: opened.review_revision_id,
  })
  documentPages.value = opened.pages
  activePage.value = opened.pages[0] ?? null
  try {
    const envelope = await api.getClassification(opened.job_id, opened.review_revision_id)
    currentClassification.value = envelope.classification
  } catch {
    currentClassification.value = null
  }
  await loadPage()
  syncPolling()
}

async function loadPage() {
  if (activePage.value == null) {
    pageHtml.value = ''
    return
  }
  if (review.value) {
    const page = await api.page(review.value.local_job_id, activePage.value)
    pageHtml.value = page.html
    return
  }
  const selected = parseDocumentKey(selectedDocumentKey.value)
  if (!selected) {
    pageHtml.value = ''
    return
  }
  const page = await api.approvedDocumentPage(
    selected.job_id,
    selected.review_revision_id,
    activePage.value,
  )
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
  if (row.page_number == null || row.removed) return
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
  if (draft?.op === 'restore') {
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

function restoreRow(row: FindingRow) {
  if (row.page_number == null) return
  const draft = drafts.value[row.finding_id]
  if (draft?.op === 'remove') {
    const rest = { ...drafts.value }
    delete rest[row.finding_id]
    drafts.value = rest
    return
  }
  drafts.value = {
    ...drafts.value,
    [row.finding_id]: { op: 'restore', finding_id: row.finding_id, page_number: row.page_number },
  }
}

function startAddFinding() {
  if (activePage.value == null) return
  const findingId = crypto.randomUUID()
  drafts.value = {
    ...drafts.value,
    [findingId]: {
      op: 'add',
      finding_id: findingId,
      page_number: activePage.value,
      component: 'materials',
      display_text: '',
    },
  }
  selectedFindingId.value = findingId
}

function cancelDraft(row: FindingRow) {
  if (!row.isLocalDraft) return
  const rest = { ...drafts.value }
  delete rest[row.finding_id]
  drafts.value = rest
  if (selectedFindingId.value === row.finding_id) selectedFindingId.value = null
}

async function save() {
  if (!review.value || !dirty.value) return
  const pendingAdds = Object.values(drafts.value).filter((draft) => draft.op === 'add')
  if (pendingAdds.some((draft) => !draft.display_text.trim())) {
    errorMessage.value = 'Added findings need display text before Save.'
    return
  }
  busy.value = true
  errorMessage.value = ''
  try {
    review.value = await api.save(
      review.value.local_job_id,
      review.value.current_revision_id,
      Object.values(drafts.value),
    )
    jobClassification.value = review.value.classification ?? jobClassification.value
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
    jobClassification.value = review.value.classification ?? jobClassification.value
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Approval failed'
  } finally {
    busy.value = false
  }
}

function downloadTxt() {
  if (!review.value || dirty.value) {
    errorMessage.value = 'Save before approval. Unsaved edits are not included.'
    return
  }
  const anchor = document.createElement('a')
  anchor.href = api.resultsTxtUrl(review.value.local_job_id)
  anchor.download = `extraction-results-${review.value.local_job_id}.txt`
  anchor.rel = 'noopener'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
}

function downloadClassificationsTxt() {
  const classification = displayedClassification.value
  if (!canDownloadClassifications.value || !classification) return
  const body = buildPageClassificationsTsv(pages.value, classification)
  const filename = pageClassificationsDownloadFilename({
    source: classification.source,
    jobId: classification.job_id,
    reviewRevisionId: classification.review_revision_id,
    localJobId: review.value?.local_job_id ?? null,
  })
  const blob = new Blob([body], { type: 'text/plain;charset=utf-8' })
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = filename
  anchor.rel = 'noopener'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(objectUrl)
}

async function classifyPages() {
  const selected = parseDocumentKey(selectedDocumentKey.value)
  if (!selected || !canClassify.value) return
  stage4Busy.value = true
  errorMessage.value = ''
  noEligibleMessage.value = ''
  try {
    const envelope = await api.startClassification(selected.job_id, selected.review_revision_id)
    currentClassification.value = envelope.classification
    syncPolling()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Classification could not be started'
  } finally {
    stage4Busy.value = false
  }
}

async function extractAll() {
  const selected = parseDocumentKey(selectedDocumentKey.value)
  if (!selected || !canExtractAll.value) return
  stage4Busy.value = true
  errorMessage.value = ''
  noEligibleMessage.value = ''
  try {
    const result = await api.extractAll(selected.job_id, selected.review_revision_id)
    if (result.kind === 'no_eligible_pages') {
      lexicalStatus.value = null
      noEligibleMessage.value = result.message
      return
    }
    lexicalStatus.value = result.job
    syncPolling()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Extract All could not be submitted'
  } finally {
    stage4Busy.value = false
  }
}

function focusSelected() {
  const root = pageRoot.value
  if (!root) return
  if (root !== renderedRoot.value || renderedPageHtml.value !== pageHtml.value) {
    root.innerHTML = pageHtml.value
    renderedRoot.value = root
    renderedPageHtml.value = pageHtml.value
  }
  root.querySelectorAll('.bl-hit--focus').forEach((mark) => mark.classList.remove('bl-hit--focus'))
  const removed = new Set(
    Object.values(drafts.value)
      .filter((draft) => draft.op === 'remove')
      .map((draft) => draft.finding_id),
  )
  const restored = new Set(
    Object.values(drafts.value)
      .filter((draft) => draft.op === 'restore')
      .map((draft) => draft.finding_id),
  )
  root.querySelectorAll<HTMLElement>('.bl-hit').forEach((mark) => {
    const ids = (mark.dataset.findingId ?? '').split(' ').filter(Boolean)
    const removedNow = ids.length > 0 && ids.every((id) => removed.has(id) && !restored.has(id))
    const categoryHidden = LEGEND_CATEGORIES.some(
      (category) => isCategoryHidden(category.id) && mark.classList.contains(category.hitClass),
    )
    mark.classList.toggle('bl-hit--hidden', removedNow || categoryHidden)
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

function classificationStatusLabel(state: ClassificationStateView | null): string {
  if (!state) return 'Not classified'
  if (state.status === 'running') {
    const current = state.progress.current_page_number
    return `Classifying page ${current ?? '?'} (${state.progress.completed_pages}/${state.progress.total_pages})`
  }
  if (state.status === 'completed') return 'Classification completed'
  if (state.status === 'failed') return `Classification failed${state.terminal_reason ? `: ${state.terminal_reason}` : ''}`
  if (state.status === 'interrupted') {
    return `Classification interrupted${state.terminal_reason ? `: ${state.terminal_reason}` : ''}`
  }
  return state.status
}

function lexicalStatusLabel(status: LexicalJobStatus | null): string {
  if (!status) return ''
  if (isTerminalLexicalStatus(status.status) && !status.reviewable) {
    const overall = status.extraction_overall ? ` (extraction ${status.extraction_overall})` : ''
    return (
      `Lexical processing/publication completed${overall}, but no usable completed ` +
      'extraction component is available for review'
    )
  }
  const phase = status.phase.replaceAll('_', ' ')
  const overall = status.extraction_overall ? ` · extraction ${status.extraction_overall}` : ''
  return `Lexical ${status.status} · ${phase}${overall}`
}

watch(activePage, (page, previous) => {
  if (page !== previous) void loadPage()
})
watch([selectedFindingId, drafts, pageHtml, hiddenCategories], () => {
  void focusSelected()
}, { flush: 'post' })
watch(selectedDocumentKey, () => {
  clearPolling()
})

onUnmounted(() => {
  clearPolling()
})

void Promise.all([loadJobs(), loadDocuments()]).catch((error: unknown) => {
  errorMessage.value = error instanceof Error ? error.message : 'Extraction workspace could not be loaded'
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
        <span class="bl-sr-only">Approved document</span>
        <select
          aria-label="Approved document"
          :value="selectedDocumentKey"
          :disabled="classificationRunning || lexicalNonTerminal || stage4Busy"
          @change="selectDocument(($event.target as HTMLSelectElement).value)"
        >
          <option value="">Select an approved document</option>
          <option
            v-for="doc in documents"
            :key="documentKey(doc)"
            :value="documentKey(doc)"
          >
            {{ documentLabel(doc) }}
          </option>
        </select>
      </label>
      <label class="bl-job-picker">
        <span class="bl-sr-only">Extraction run</span>
        <select
          aria-label="Extraction run"
          :value="review?.local_job_id ?? ''"
          :disabled="classificationRunning || lexicalNonTerminal || stage4Busy"
          @change="selectJob(($event.target as HTMLSelectElement).value)"
        >
          <option value="" disabled>Select a completed extraction run</option>
          <option v-for="job in jobs" :key="job.local_job_id" :value="job.local_job_id">
            {{ jobLabel(job) }}
          </option>
        </select>
      </label>
      <div class="bl-actions">
        <button
          v-if="canClassify"
          type="button"
          class="bl-button"
          :disabled="busy || stage4Busy"
          @click="classifyPages"
        >
          Classify pages
        </button>
        <button
          type="button"
          class="bl-button"
          :disabled="busy || stage4Busy || !canExtractAll"
          @click="extractAll"
        >
          Extract All
        </button>
        <button
          type="button"
          class="bl-button"
          :disabled="busy || !review || dirty"
          :title="downloadDisabledReason || undefined"
          @click="downloadTxt"
        >
          Download TXT
        </button>
        <button
          v-if="canDownloadClassifications"
          type="button"
          class="bl-button"
          :disabled="busy || stage4Busy"
          @click="downloadClassificationsTxt"
        >
          Download classifications TXT
        </button>
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
    <p v-if="noEligibleMessage" class="bl-banner" role="status">{{ noEligibleMessage }}</p>
    <p v-if="displayedClassification" class="bl-banner bl-banner--info" role="status">
      {{ classificationStatusLabel(displayedClassification) }}
      <span v-if="displayedClassification.source === 'job_snapshot'">
        · Labels from this extraction run’s classification snapshot (informational; not Stage 3 approval)
      </span>
      <span v-else>
        · Classification labels are informational and do not change Stage 3 final approval
      </span>
    </p>
    <p v-if="lexicalStatus" class="bl-banner bl-banner--info" role="status">
      {{ lexicalStatusLabel(lexicalStatus) }}
    </p>
    <p v-if="jobs.length === 0 && !selectedDocumentKey" class="bl-loading">
      No completed extraction runs. Select an approved document to classify and Extract All.
    </p>

    <template v-if="(review || selectedDocumentKey) && activePage != null">
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
          <section
            v-if="displayedClassification"
            class="bl-classification-panel"
            aria-label="Page classification"
          >
            <header class="bl-classification-panel__head">
              <strong>Page classification</strong>
              <span class="bl-muted">Informational only</span>
            </header>
            <template v-if="activePageClassification">
              <p class="bl-classification-meta">
                Kind: {{ activePageClassification.kind }}
                <span v-if="activePageClassification.requires_review"> · needs review</span>
                <span v-if="activePageClassification.is_provisional"> · provisional</span>
              </p>
              <p class="bl-classification-meta">
                Eligibility:
                {{ activePageClassification.eligibility.eligible_for_extraction ? 'eligible' : 'excluded' }}
                — {{ activePageClassification.eligibility.reason }}
              </p>
              <p class="bl-classification-meta">
                Source validation:
                {{ activePageClassification.source_validation.requires_review ? 'needs review' : 'ok' }}
                <span v-if="activePageClassification.source_validation.has_unverified">
                  · unverified evidence present
                </span>
              </p>
              <ul class="bl-classification-labels">
                <li v-for="(item, index) in activePageClassification.labels" :key="`${item.label}-${index}`">
                  <strong>{{ item.label }}</strong>
                  <span v-if="item.quote" class="bl-muted"> “{{ item.quote }}”</span>
                  <span v-if="item.reason" class="bl-muted"> — {{ item.reason }}</span>
                  <span v-if="item.element_id" class="bl-muted"> · {{ item.element_id }}</span>
                </li>
              </ul>
            </template>
            <p v-else class="bl-muted">No completed classification result for this page yet.</p>
          </section>

          <template v-if="review">
            <header class="bl-findings__toolbar">
              <button type="button" :aria-pressed="viewMode === 'page'" @click="viewMode = 'page'">By page</button>
              <button type="button" :aria-pressed="viewMode === 'all'" @click="viewMode = 'all'">All findings</button>
              <button
                v-if="viewMode === 'page'"
                type="button"
                class="bl-button"
                aria-label="Add finding"
                @click="startAddFinding"
              >
                + Add finding
              </button>
            </header>
            <ul class="bl-hit-legend" aria-label="Highlight category visibility">
              <li v-for="category in LEGEND_CATEGORIES" :key="category.id">
                <button
                  type="button"
                  class="bl-legend-toggle"
                  :class="{ 'is-off': isCategoryHidden(category.id) }"
                  :aria-label="`Toggle ${category.label} category visibility`"
                  :aria-pressed="!isCategoryHidden(category.id)"
                  @click="toggleCategoryVisibility(category.id)"
                >
                  <span class="bl-swatch" :class="category.hitClass">{{ category.short }}</span>
                  {{ category.label }}
                </button>
              </li>
            </ul>
            <ol class="bl-finding-list">
              <li
                v-for="row in visibleRows"
                :key="row.finding_id"
                :class="{ 'is-removed': row.removed, 'is-draft': row.isLocalDraft }"
              >
                <div class="bl-finding-head">
                  <button
                    type="button"
                    class="bl-finding-select"
                    :aria-current="selectedFindingId === row.finding_id ? 'true' : undefined"
                    @click="selectFinding(row)"
                  >
                    <span class="bl-finding-label">{{ componentLabel(row.component) || 'Finding' }}</span>
                    <span
                      v-if="viewMode === 'page'"
                      class="bl-finding-text"
                      :class="hitClass(row.component)"
                    >{{ row.display_text }}</span>
                    <span v-if="viewMode === 'all'" class="bl-finding-text-plain">{{ row.display_text }}</span>
                    <small v-if="viewMode === 'all' && row.page_number">Page {{ row.page_number }}</small>
                  </button>
                </div>
                <p v-if="provenanceLabel(row)" class="bl-muted">{{ provenanceLabel(row) }}</p>
                <div v-if="viewMode === 'page' && row.isLocalDraft" class="bl-finding-edit">
                  <label>
                    Display text
                    <input
                      :aria-label="`Display text ${row.finding_id}`"
                      placeholder="Enter finding text"
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
                  <button type="button" class="bl-button" @click="cancelDraft(row)">Cancel</button>
                </div>
                <div v-else-if="viewMode === 'page' && row.removed" class="bl-finding-edit">
                  <button type="button" class="bl-button" @click="restoreRow(row)">Restore</button>
                </div>
                <div v-else-if="viewMode === 'page'" class="bl-finding-edit">
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
          </template>
        </aside>
      </div>
    </template>
  </main>
</template>
