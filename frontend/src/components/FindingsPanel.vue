<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DecisionAction, FindingDecisionRequest, ReviewFinding } from '../contracts'

const ACTION_LABELS: Record<DecisionAction, string> = {
  KEEP_ORIGINAL: 'Keep original',
  ACKNOWLEDGED_LIMITATION: 'Acknowledge limitation',
  RESOLVED_AFTER_EDIT: 'Resolved after edit',
}

const ACTION_HELP: Record<DecisionAction, string> = {
  KEEP_ORIGINAL: 'Keep the extracted content unchanged and record this finding as reviewed for approval.',
  RESOLVED_AFTER_EDIT: 'Record that your saved edit resolves this finding.',
  ACKNOWLEDGED_LIMITATION:
    'Keep the extracted content unchanged and record that you reviewed this known conversion limitation. This resolves the finding for review approval.',
}

const props = defineProps<{
  findings: ReviewFinding[]
  activePage: number
  changedNodeIds: string[]
  pendingDecisions?: Record<string, FindingDecisionRequest>
  staleFindingIds?: string[]
  disabled?: boolean
}>()
const emit = defineEmits<{
  select: [page: number | null, nodeId: string | null]
  decide: [findingId: string, action: DecisionAction]
  replace: [findingId: string, nodeId: string, text: string, expectedHash: string]
}>()
const scope = ref<'all' | 'page'>('all')
const collapsed = ref(false)

const documentFindingsCount = computed(() => props.findings.length)
const pageFindingsCount = computed(
  () => props.findings.filter((finding) => finding.pages.includes(props.activePage)).length,
)

const visible = computed(() =>
  scope.value === 'all' ? props.findings : props.findings.filter((finding) => finding.pages.includes(props.activePage)),
)

function recordedAction(finding: ReviewFinding): DecisionAction | null {
  return finding.decision?.region_hash === finding.region_hash ? finding.decision.action : null
}

function selectedAction(finding: ReviewFinding): DecisionAction | null {
  return props.pendingDecisions?.[finding.finding_id]?.action ?? recordedAction(finding)
}

function decisionStatus(finding: ReviewFinding): string | null {
  const pending = props.pendingDecisions?.[finding.finding_id]
  if (pending) return `Pending: ${ACTION_LABELS[pending.action]}`
  const recorded = recordedAction(finding)
  return recorded ? `Recorded: ${ACTION_LABELS[recorded]}` : null
}

function findingTitle(code: string): string {
  return `Finding: ${code.replaceAll('_', ' ')}`
}
</script>

<template>
  <aside class="bl-findings" aria-label="Findings">
    <header>
      <button type="button" class="bl-findings__toggle" :aria-expanded="!collapsed" @click="collapsed = !collapsed">
        <span class="bl-findings__counts">
          <span>Document findings <span class="bl-findings__count">{{ documentFindingsCount }}</span></span>
          <span>Page findings <span class="bl-findings__count">{{ pageFindingsCount }}</span></span>
        </span>
      </button>
      <select v-if="!collapsed" v-model="scope" aria-label="Finding scope">
          <option value="all">All warnings</option>
          <option value="page">This page</option>
        </select>
    </header>
    <div class="bl-sr-only">
      <span id="bl-help-keep-original">{{ ACTION_HELP.KEEP_ORIGINAL }}</span>
      <span id="bl-help-resolved-after-edit">{{ ACTION_HELP.RESOLVED_AFTER_EDIT }}</span>
      <span id="bl-help-acknowledge-limitation">{{ ACTION_HELP.ACKNOWLEDGED_LIMITATION }}</span>
    </div>
    <div v-if="!collapsed && visible.length" class="bl-findings__list">
      <article
        v-for="finding in visible"
        :key="finding.finding_id"
        class="bl-finding"
        :class="{ resolved: Boolean(selectedAction(finding)) }"
      >
        <button
          type="button"
          class="bl-finding__target"
          @click="emit('select', finding.pages[0] ?? null, finding.node_ids[0] ?? null)"
        >
          <span class="bl-finding__code">{{ findingTitle(finding.code) }}</span>
          <span>{{ finding.pages.length ? `Page ${finding.pages.join(', ')}` : 'Document finding' }}</span>
        </button>
        <p v-if="decisionStatus(finding)" class="bl-finding__status">{{ decisionStatus(finding) }}</p>
        <div class="bl-finding__actions">
          <button
            type="button"
            :class="{ selected: selectedAction(finding) === 'KEEP_ORIGINAL' }"
            :aria-pressed="selectedAction(finding) === 'KEEP_ORIGINAL'"
            :title="ACTION_HELP.KEEP_ORIGINAL"
            aria-describedby="bl-help-keep-original"
            :disabled="disabled"
            @click="emit('decide', finding.finding_id, 'KEEP_ORIGINAL')"
          >
            Keep original
          </button>
          <button
            type="button"
            :class="{ selected: selectedAction(finding) === 'RESOLVED_AFTER_EDIT' }"
            :aria-pressed="selectedAction(finding) === 'RESOLVED_AFTER_EDIT'"
            :title="ACTION_HELP.RESOLVED_AFTER_EDIT"
            aria-describedby="bl-help-resolved-after-edit"
            :disabled="disabled || !finding.node_ids.some((nodeId) => changedNodeIds.includes(nodeId))"
            @click="emit('decide', finding.finding_id, 'RESOLVED_AFTER_EDIT')"
          >
            Mark resolved after edit
          </button>
          <button
            type="button"
            :class="{ selected: selectedAction(finding) === 'ACKNOWLEDGED_LIMITATION' }"
            :aria-pressed="selectedAction(finding) === 'ACKNOWLEDGED_LIMITATION'"
            :title="ACTION_HELP.ACKNOWLEDGED_LIMITATION"
            aria-describedby="bl-help-acknowledge-limitation"
            :disabled="disabled"
            @click="emit('decide', finding.finding_id, 'ACKNOWLEDGED_LIMITATION')"
          >
            Acknowledge limitation
          </button>
          <button
            v-if="finding.suggested_replacement?.eligible && finding.suggested_replacement.expected_region_hash === finding.region_hash"
            type="button"
            :disabled="disabled || staleFindingIds?.includes(finding.finding_id)"
            :title="staleFindingIds?.includes(finding.finding_id) ? 'Save your edits and re-evaluate before applying this suggestion.' : undefined"
            @click="emit(
              'replace',
              finding.finding_id,
              finding.suggested_replacement!.node_id,
              finding.suggested_replacement!.text,
              finding.suggested_replacement!.expected_region_hash,
            )"
          >
            Apply suggested ±
          </button>
        </div>
      </article>
    </div>
    <p v-else-if="!collapsed" class="bl-muted">No findings in this view.</p>
  </aside>
</template>
