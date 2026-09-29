import { createApp, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ExtractionReviewWorkspace from '../src/components/ExtractionReviewWorkspace.vue'

const JOB_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const WATER_ID = 'finding-water'
const MIXING_ID = 'finding-mixing'

const opened = {
  local_job_id: JOB_ID,
  job_id: 'job-1',
  review_revision_id: 'rev-doc-1',
  action: 'extract_all',
  extraction_overall: 'completed',
  current_revision_id: '11111111-1111-4111-8111-111111111111',
  approval_state: 'not_approved',
  pages: [1, 2],
  findings: [
    {
      finding_id: WATER_ID,
      component: 'materials',
      display_text: 'water',
      page_number: 1,
      evidence_status: 'document_evidence',
      removed: false,
      origin_kind: 'lexical',
      block_node_id: 'n1',
      start_char: 4,
      end_char: 9,
      original_matched_text: 'water',
      added_by_user: false,
      changed_by_user: false,
      removed_by_user: false,
    },
    {
      finding_id: MIXING_ID,
      component: 'unit_operations',
      display_text: 'mixing',
      page_number: 2,
      evidence_status: 'document_evidence',
      removed: false,
      origin_kind: 'lexical',
      block_node_id: 'n3',
      start_char: 6,
      end_char: 12,
      original_matched_text: 'mixing',
      added_by_user: false,
      changed_by_user: false,
      removed_by_user: false,
    },
  ],
}

const pageHtml: Record<number, string> = {
  1: `<section class="page" data-page="1"><p data-node-id="n1"><mark class="bl-hit bl-hit--material" data-finding-id="${WATER_ID}" tabindex="-1">water</mark></p></section>`,
  2: `<section class="page" data-page="2"><p data-node-id="n3"><mark class="bl-hit bl-hit--unit-operation" data-finding-id="${MIXING_ID}" tabindex="-1">mixing</mark></p></section>`,
}

async function flush() {
  for (let step = 0; step < 5; step += 1) {
    await Promise.resolve()
    await nextTick()
  }
}

function buttonNamed(host: HTMLElement, text: string): HTMLButtonElement {
  const button = [...host.querySelectorAll('button')].find((item) => item.textContent?.includes(text))
  if (!(button instanceof HTMLButtonElement)) throw new Error(`missing button ${text}`)
  return button
}

describe('extraction review workspace', () => {
  const mounts: Array<{ unmount: () => void }> = []

  afterEach(() => {
    for (const mount of mounts) mount.unmount()
    mounts.length = 0
    vi.unstubAllGlobals()
  })

  it('focuses evidence, blocks approval while unsaved, and opens the selected finding page', async () => {
    const approveCalls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.endsWith('/jobs') && method === 'GET') {
        return json({ jobs: [{
          local_job_id: JOB_ID,
          job_id: 'job-1',
          review_revision_id: 'rev-doc-1',
          action: 'extract_all',
          extraction_overall: 'completed',
          finished_at: null,
        }] })
      }
      if (url.endsWith('/approve')) {
        approveCalls.push(url)
        return json(opened)
      }
      const pageMatch = url.match(/\/pages\/(\d+)$/)
      if (pageMatch) return json({ page_number: Number(pageMatch[1]), html: pageHtml[Number(pageMatch[1])] })
      return json(opened)
    }))

    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(ExtractionReviewWorkspace, { options: {} })
    app.mount(host)
    mounts.push({
      unmount: () => {
        app.unmount()
        host.remove()
      },
    })
    await flush()

    const jobSelect = host.querySelector('[aria-label="Extraction job"]')
    if (!(jobSelect instanceof HTMLSelectElement)) throw new Error('missing job selector')
    jobSelect.value = JOB_ID
    jobSelect.dispatchEvent(new Event('change'))
    await flush()

    expect(host.textContent).toContain('water')
    expect(host.textContent).not.toContain('mixing')
    expect(host.textContent).toContain('Not approved')

    buttonNamed(host, 'water').click()
    await flush()
    const waterMark = host.querySelector(`[data-finding-id="${WATER_ID}"]`)
    expect(waterMark?.classList.contains('bl-hit--focus')).toBe(true)

    const display = host.querySelector(`[aria-label="Display text ${WATER_ID}"]`)
    if (!(display instanceof HTMLInputElement)) throw new Error('missing display text')
    display.value = 'purified water'
    display.dispatchEvent(new Event('change'))
    await nextTick()

    expect(buttonNamed(host, 'Approve extraction result').disabled).toBe(true)
    expect(host.textContent).toContain('Save before approval. Unsaved edits are not included.')
    expect(approveCalls).toEqual([])

    buttonNamed(host, 'All findings').click()
    await nextTick()
    buttonNamed(host, 'mixing').click()
    await flush()

    const pageSelect = host.querySelector('[aria-label="Select page"]')
    if (!(pageSelect instanceof HTMLSelectElement)) throw new Error('missing page selector')
    expect(pageSelect.value).toBe('2')
    expect(buttonNamed(host, 'By page').getAttribute('aria-pressed')).toBe('true')
    expect(host.querySelector('[aria-label="New finding text"]')).toBeTruthy()
    const mixingMark = host.querySelector(`[data-finding-id="${MIXING_ID}"]`)
    expect(mixingMark?.classList.contains('bl-hit--focus')).toBe(true)
  })
})

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
