import { nextTick, reactive, type App } from 'vue'
import { createApp } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import FindingsPanel from '../src/components/FindingsPanel.vue'
import type { DecisionAction, FindingDecisionRequest, ReviewFinding } from '../src/contracts'
import { toleranceReviewFixture } from './fixture'

const ACTION_HELP = {
  KEEP_ORIGINAL: 'Keep the extracted content unchanged and record this finding as reviewed for approval.',
  RESOLVED_AFTER_EDIT: 'Record that your saved edit resolves this finding.',
  ACKNOWLEDGED_LIMITATION:
    'Keep the extracted content unchanged and record that you reviewed this known conversion limitation. This resolves the finding for review approval.',
} as const

interface MountedPanel {
  app: App
  host: HTMLElement
  props: {
    findings: ReviewFinding[]
    pendingDecisions: Record<string, FindingDecisionRequest>
    changedNodeIds: string[]
    activePage: number
  }
  decisions: Array<[string, DecisionAction]>
  selects: Array<[number | null, string | null]>
  replacements: Array<[string, string, string, string]>
}

const mounts: MountedPanel[] = []

function findingWithDecision(
  action: DecisionAction | null = null,
  overrides: Partial<ReviewFinding> = {},
): ReviewFinding {
  const base = toleranceReviewFixture().findings[0]
  return {
    ...base,
    ...overrides,
    decision: action
      ? {
          action,
          note: null,
          actor: 'reviewer',
          at: '2026-01-01T00:00:00Z',
          revision_id: 'revision-1',
          region_hash: overrides.region_hash ?? base.region_hash,
        }
      : null,
  }
}

async function mountPanel(options?: {
  findings?: ReviewFinding[]
  pendingDecisions?: Record<string, FindingDecisionRequest>
  changedNodeIds?: string[]
  activePage?: number
}): Promise<MountedPanel> {
  const props = reactive({
    findings: options?.findings ?? [findingWithDecision()],
    pendingDecisions: options?.pendingDecisions ?? {},
    changedNodeIds: options?.changedNodeIds ?? [],
    activePage: options?.activePage ?? 1,
  })
  const decisions: Array<[string, DecisionAction]> = []
  const selects: Array<[number | null, string | null]> = []
  const replacements: Array<[string, string, string, string]> = []
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp({
    components: { FindingsPanel },
    setup() {
      return {
        props,
        onDecide: (findingId: string, action: DecisionAction) => {
          decisions.push([findingId, action])
          props.pendingDecisions = {
            ...props.pendingDecisions,
            [findingId]: { finding_id: findingId, action, note: null },
          }
        },
        onSelect: (page: number | null, nodeId: string | null) => selects.push([page, nodeId]),
        onReplace: (findingId: string, nodeId: string, text: string, expectedHash: string) =>
          replacements.push([findingId, nodeId, text, expectedHash]),
      }
    },
    template: `
      <FindingsPanel
        :findings="props.findings"
        :active-page="props.activePage"
        :changed-node-ids="props.changedNodeIds"
        :pending-decisions="props.pendingDecisions"
        @decide="onDecide"
        @select="onSelect"
        @replace="onReplace"
      />
    `,
  })
  app.mount(host)
  await nextTick()
  const mounted = { app, host, props, decisions, selects, replacements }
  mounts.push(mounted)
  return mounted
}

afterEach(() => {
  while (mounts.length) {
    const mounted = mounts.pop()
    mounted?.app.unmount()
    mounted?.host.remove()
  }
})

describe('FindingsPanel decision indicators', () => {
  it('shows a pending decision immediately after a click', async () => {
    const mounted = await mountPanel()
    const keep = [...mounted.host.querySelectorAll('.bl-finding__actions button')]
      .find((button) => button.textContent?.trim() === 'Keep original') as HTMLButtonElement
    keep.click()
    await nextTick()

    expect(mounted.host.querySelector('.bl-finding__status')?.textContent).toBe('Pending: Keep original')
    expect(keep.getAttribute('aria-pressed')).toBe('true')
    expect(keep.classList.contains('selected')).toBe(true)
  })

  it('replaces the pending choice when another decision is selected', async () => {
    const mounted = await mountPanel()
    const buttons = [...mounted.host.querySelectorAll('.bl-finding__actions button')] as HTMLButtonElement[]
    const keep = buttons.find((button) => button.textContent?.trim() === 'Keep original')!
    const acknowledge = buttons.find((button) => button.textContent?.trim() === 'Acknowledge limitation')!
    keep.click()
    await nextTick()
    acknowledge.click()
    await nextTick()

    expect(mounted.host.querySelector('.bl-finding__status')?.textContent).toBe('Pending: Acknowledge limitation')
    expect(keep.getAttribute('aria-pressed')).toBe('false')
    expect(acknowledge.getAttribute('aria-pressed')).toBe('true')
    expect(Object.keys(mounted.props.pendingDecisions)).toEqual(['finding-tol'])
    expect(mounted.props.pendingDecisions['finding-tol'].action).toBe('ACKNOWLEDGED_LIMITATION')
  })

  it('shows a recorded decision from server state after pending is cleared', async () => {
    const mounted = await mountPanel({
      findings: [findingWithDecision('KEEP_ORIGINAL')],
      pendingDecisions: {
        'finding-tol': { finding_id: 'finding-tol', action: 'KEEP_ORIGINAL', note: null },
      },
    })
    expect(mounted.host.querySelector('.bl-finding__status')?.textContent).toBe('Pending: Keep original')

    mounted.props.findings = [findingWithDecision('KEEP_ORIGINAL')]
    mounted.props.pendingDecisions = {}
    await nextTick()

    expect(mounted.host.querySelector('.bl-finding__status')?.textContent).toBe('Recorded: Keep original')
    const keep = [...mounted.host.querySelectorAll('.bl-finding__actions button')]
      .find((button) => button.textContent?.trim() === 'Keep original') as HTMLButtonElement
    expect(keep.getAttribute('aria-pressed')).toBe('true')
    expect(mounted.host.querySelectorAll('.bl-finding').length).toBe(1)
  })
})

describe('FindingsPanel counts and decision help', () => {
  function countLabels(host: HTMLElement): string[] {
    return [...host.querySelectorAll('.bl-findings__counts > span')].map(
      (el) => el.textContent?.replace(/\s+/g, ' ').trim() ?? '',
    )
  }

  it('renders document and page finding counts independently of the list filter', async () => {
    const findings = [
      findingWithDecision(null, { finding_id: 'f1', pages: [1] }),
      findingWithDecision(null, { finding_id: 'f2', pages: [1, 2] }),
      findingWithDecision(null, { finding_id: 'f3', pages: [2] }),
    ]
    const mounted = await mountPanel({ findings, activePage: 1 })

    expect(countLabels(mounted.host)).toEqual(['Document findings 3', 'Page findings 2'])

    const scope = mounted.host.querySelector('select[aria-label="Finding scope"]') as HTMLSelectElement
    scope.value = 'page'
    scope.dispatchEvent(new Event('change'))
    await nextTick()

    expect(countLabels(mounted.host)).toEqual(['Document findings 3', 'Page findings 2'])
    expect(mounted.host.querySelectorAll('.bl-finding')).toHaveLength(2)
  })

  it('updates the page findings count when the active page changes', async () => {
    const findings = [
      findingWithDecision(null, { finding_id: 'f1', pages: [1] }),
      findingWithDecision(null, { finding_id: 'f2', pages: [2] }),
      findingWithDecision(null, { finding_id: 'f3', pages: [2] }),
    ]
    const mounted = await mountPanel({ findings, activePage: 1 })
    expect(countLabels(mounted.host)).toEqual(['Document findings 3', 'Page findings 1'])

    mounted.props.activePage = 2
    await nextTick()

    expect(countLabels(mounted.host)).toEqual(['Document findings 3', 'Page findings 2'])
  })

  it('exposes concise tooltips and accessible explanations on decision buttons', async () => {
    const mounted = await mountPanel()
    const byLabel = (label: string) =>
      [...mounted.host.querySelectorAll('.bl-finding__actions button')].find(
        (button) => button.textContent?.trim() === label,
      ) as HTMLButtonElement

    const keep = byLabel('Keep original')
    const resolved = byLabel('Mark resolved after edit')
    const acknowledge = byLabel('Acknowledge limitation')

    expect(keep.getAttribute('title')).toBe(ACTION_HELP.KEEP_ORIGINAL)
    expect(resolved.getAttribute('title')).toBe(ACTION_HELP.RESOLVED_AFTER_EDIT)
    expect(acknowledge.getAttribute('title')).toBe(ACTION_HELP.ACKNOWLEDGED_LIMITATION)

    expect(keep.getAttribute('aria-describedby')).toBe('bl-help-keep-original')
    expect(resolved.getAttribute('aria-describedby')).toBe('bl-help-resolved-after-edit')
    expect(acknowledge.getAttribute('aria-describedby')).toBe('bl-help-acknowledge-limitation')

    expect(mounted.host.querySelector('#bl-help-keep-original')?.textContent).toBe(ACTION_HELP.KEEP_ORIGINAL)
    expect(mounted.host.querySelector('#bl-help-resolved-after-edit')?.textContent).toBe(ACTION_HELP.RESOLVED_AFTER_EDIT)
    expect(mounted.host.querySelector('#bl-help-acknowledge-limitation')?.textContent).toBe(
      ACTION_HELP.ACKNOWLEDGED_LIMITATION,
    )
  })
})

describe('FindingsPanel finding title', () => {
  it('displays Finding: prefix with spaces and keeps the raw code in the model', async () => {
    const findings = [
      findingWithDecision(null, {
        finding_id: 'f-figure',
        code: 'UNINTERPRETED_LAYOUT_FIGURE',
      }),
      findingWithDecision(null, {
        finding_id: 'f-tolerance',
        code: 'POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY',
      }),
    ]
    const mounted = await mountPanel({ findings })
    const labels = [...mounted.host.querySelectorAll('.bl-finding__code')].map(
      (el) => el.textContent?.trim() ?? '',
    )

    expect(labels).toEqual([
      'Finding: UNINTERPRETED LAYOUT FIGURE',
      'Finding: POSSIBLE TOLERANCE SYMBOL AMBIGUITY',
    ])
    expect(mounted.props.findings.map((finding) => finding.code)).toEqual([
      'UNINTERPRETED_LAYOUT_FIGURE',
      'POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY',
    ])
  })
})

describe('FindingsPanel selection and suggested replacement', () => {
  it('emits the finding page and mapped node id when the finding is selected', async () => {
    const mounted = await mountPanel()
    const target = mounted.host.querySelector('.bl-finding__target') as HTMLButtonElement
    target.click()
    expect(mounted.selects).toEqual([[1, 'n-cell-3']])
  })

  it('shows Apply suggested ± only when the backend supplied an eligible replacement', async () => {
    const eligible = await mountPanel()
    expect(
      [...eligible.host.querySelectorAll('button')].some((button) => button.textContent?.trim() === 'Apply suggested ±'),
    ).toBe(true)

    const finding = findingWithDecision()
    finding.suggested_replacement = null
    const ineligible = await mountPanel({ findings: [finding] })
    expect(
      [...ineligible.host.querySelectorAll('button')].some((button) => button.textContent?.trim() === 'Apply suggested ±'),
    ).toBe(false)
  })
})
