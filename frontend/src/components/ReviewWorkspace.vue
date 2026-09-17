<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createReviewApi } from '../api'
import type { ReviewWorkspaceOptions } from '../contracts'
import { editableTextMap } from '../mapping'
import { createReviewState, unresolvedToleranceNodeIds } from '../state'
import DocumentEditor from './DocumentEditor.vue'
import FindingsPanel from './FindingsPanel.vue'
import PdfPane from './PdfPane.vue'

const props = defineProps<{ options: ReviewWorkspaceOptions }>()
const api = createReviewApi(
  props.options.jobId,
  props.options.getAccessToken,
  props.options.onAuthenticationRequired,
  props.options.apiBaseUrl,
)
const review = createReviewState(api)
const pdfPages = ref(0)
const pageMismatch = ref<string | null>(null)
const editor = ref<InstanceType<typeof DocumentEditor>>()
const pages = computed(() => review.state.server?.document.pages.map((page) => page.number).sort((a, b) => a - b) ?? [])
const pageIndex = computed(() => pages.value.indexOf(review.state.activePage))
const expectedPageCount = computed(
  () => review.state.server?.source_page_count ?? review.state.server?.document.declared_pages ?? pages.value.length,
)
const displayReviewStatus = computed(() => {
  if (review.dirty.value) return 'In review'
  const value = review.state.server?.status
  return value === 'APPROVED' ? 'Approved' : value === 'IN_REVIEW' ? 'In review' : 'Not reviewed'
})
const saveLabel = computed(() => {
  if (review.state.saveStatus === 'SAVING') return 'Saving'
  if (review.state.saveStatus === 'SAVE_FAILED') return 'Save failed'
  return review.dirty.value ? 'Unsaved' : 'Saved'
})
const editedNodeIds = computed(() => {
  const server = review.state.server
  if (!server) return []
  const ids = new Set(review.changes.value.map((change) => change.node_id))
  for (const node of server.catalogue.nodes) {
    if (review.state.baselines[node.page_number]?.get(node.node_id) !== node.baseline_text) {
      ids.add(node.node_id)
    }
  }
  return [...ids]
})
const approvalBlocked = computed(() => Boolean(pageMismatch.value || review.unsupported.value.length || review.state.contentError))
const toleranceMarkerNodeIds = computed(() => unresolvedToleranceNodeIds(review.state.server?.findings ?? []))
const staleFindingIds = computed(() => {
  const server = review.state.server
  if (!server) return []
  return server.findings
    .filter((finding) => {
      const suggestion = finding.suggested_replacement
      if (!suggestion?.eligible) return false
      const node = server.catalogue.nodes.find((item) => item.node_id === suggestion.node_id)
      if (!node) return true
      const current = editableTextMap(review.state.drafts[node.page_number] ?? { type: 'doc' }).get(suggestion.node_id)
      const baseline = review.state.baselines[node.page_number]?.get(suggestion.node_id)
      return current !== baseline && current !== suggestion.text
    })
    .map((finding) => finding.finding_id)
})

function setPage(page: number) {
  if (pages.value.includes(page)) review.state.activePage = page
}

async function download(format: 'html' | 'json') {
  const revision = review.state.server?.revision_id
  if (!revision) return
  try {
    window.location.assign(await api.exportUrl(revision, format))
  } catch {
    // The server returns safe errors and the approved state remains available.
  }
}

async function selectFinding(page: number | null, nodeId: string | null) {
  if (page) setPage(page)
  if (nodeId) {
    await nextTick()
    await editor.value?.focusNode(nodeId)
  }
}

async function reloadAfterConflict() {
  if (window.confirm('Reloading discards this browser draft. Reconcile or copy your changes before continuing.')) {
    await review.reloadServer()
  }
}

const beforeUnload = (event: BeforeUnloadEvent) => {
  if (!review.dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}
watch(review.dirty, (dirty) => props.options.onDirtyChange?.(dirty), { immediate: true })
onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload)
  void review.load()
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  props.options.onDirtyChange?.(false)
})
</script>

<template>
  <main class="bl-review">
    <header class="bl-topbar">
      <button type="button" class="bl-button bl-button--quiet" @click="options.onBack?.()">← Back</button>
      <div class="bl-title">
        <strong>{{ options.filename }}</strong>
        <span v-if="options.demoLabel" class="bl-demo-label">{{ options.demoLabel }}</span>
        <span v-if="review.state.server" class="bl-statuses">
          <span class="bl-chip bl-chip--document-status">Document status · {{ displayReviewStatus }}</span>
          <span class="bl-chip" :class="{ 'bl-chip--changed': review.dirty.value || review.state.saveStatus === 'SAVE_FAILED' }">{{ saveLabel }}</span>
        </span>
      </div>
      <div class="bl-actions">
        <button type="button" class="bl-button" :disabled="review.state.pending || !review.dirty.value" @click="review.save()">
          Save draft
        </button>
        <button
          type="button"
          class="bl-button"
          :disabled="review.state.pending || approvalBlocked"
          @click="review.approvePage"
        >
          Approve page
        </button>
        <button type="button" class="bl-button bl-button--primary" :disabled="review.state.pending || approvalBlocked" @click="review.approveDocument">
          Approve &amp; Export
        </button>
        <button v-if="review.state.server?.status === 'APPROVED'" type="button" class="bl-button" @click="download('html')">Download HTML</button>
        <button v-if="review.state.server?.status === 'APPROVED'" type="button" class="bl-button" @click="download('json')">Download JSON</button>
      </div>
    </header>

    <div v-if="review.state.error" class="bl-banner bl-banner--error" role="alert">{{ review.state.error }}</div>
    <div v-if="review.state.contentError" class="bl-banner bl-banner--error" role="alert">
      Editor content error: {{ review.state.contentError }}
    </div>
    <div v-if="pageMismatch" class="bl-banner bl-banner--error" role="alert">{{ pageMismatch }} Approval is blocked.</div>
    <div v-if="review.unsupported.value.length" class="bl-banner bl-banner--error" role="alert">
      Unsupported review content is read-only and approval is blocked: {{ review.unsupported.value[0] }}
    </div>
    <div v-if="review.state.conflict" class="bl-banner bl-banner--conflict" role="alert">
      Server revision conflict. Your browser draft is intact.
      <button type="button" class="bl-button" @click="reloadAfterConflict">Reload server state</button>
    </div>

    <div v-if="review.state.loading" class="bl-loading">Loading review workspace…</div>
    <template v-else-if="review.state.server && review.state.drafts[review.state.activePage]">
      <nav class="bl-pagebar" aria-label="Page navigation">
        <button type="button" aria-label="Previous page" :disabled="pageIndex <= 0" @click="setPage(pages[pageIndex - 1])">‹</button>
        <label>
          <span class="bl-sr-only">Select page</span>
          <select :value="review.state.activePage" @change="setPage(Number(($event.target as HTMLSelectElement).value))">
            <option v-for="page in pages" :key="page" :value="page">Page {{ page }}</option>
          </select>
        </label>
        <span>of {{ pages.length }}</span>
        <button type="button" aria-label="Next page" :disabled="pageIndex >= pages.length - 1" @click="setPage(pages[pageIndex + 1])">›</button>
        <span class="bl-page-dots" aria-hidden="true">
          <i
            v-for="page in pages"
            :key="page"
            :class="{
              active: page === review.state.activePage,
              approved: review.state.server.pages.find((item) => item.page_number === page)?.approval,
            }"
            @click="setPage(page)"
          />
        </span>
      </nav>

      <div class="bl-workspace-grid">
        <PdfPane
          :api="api"
          :page="review.state.activePage"
          :expected-page-count="expectedPageCount"
          @page-count="pdfPages = $event"
          @mismatch="pageMismatch = $event"
        />
        <section class="bl-review-panel">
          <DocumentEditor
            ref="editor"
            :content="review.state.drafts[review.state.activePage]"
            :disabled="review.state.pending"
            :tolerance-node-ids="toleranceMarkerNodeIds"
            @update="review.setDraft"
            @content-error="review.setContentError"
          />
          <FindingsPanel
            :findings="review.state.server.findings"
            :active-page="review.state.activePage"
            :changed-node-ids="editedNodeIds"
            :pending-decisions="review.state.decisions"
            :stale-finding-ids="staleFindingIds"
            :disabled="review.state.pending"
            @select="selectFinding"
            @decide="review.decide"
            @replace="review.applyTolerance"
          />
        </section>
      </div>
    </template>
  </main>
</template>
