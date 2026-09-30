import { createApp, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ExtractionReviewWorkspace from '../src/components/ExtractionReviewWorkspace.vue'
import type { ExtractionFinding, OpenedExtractionReview } from '../src/extractionReview'

const JOB_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const WATER_ID = 'finding-water'
const MIXING_ID = 'finding-mixing'

const opened: OpenedExtractionReview = {
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
  for (let step = 0; step < 20; step += 1) {
    await Promise.resolve()
    await nextTick()
  }
}

async function waitFor(predicate: () => boolean, label: string) {
  for (let step = 0; step < 50; step += 1) {
    if (predicate()) return
    await Promise.resolve()
    await nextTick()
  }
  throw new Error(`timeout waiting for ${label}`)
}

function buttonNamed(host: HTMLElement, text: string): HTMLButtonElement {
  const button = [...host.querySelectorAll('button')].find((item) => item.textContent?.includes(text))
  if (!(button instanceof HTMLButtonElement)) throw new Error(`missing button ${text}`)
  return button
}

function categoryToggle(host: HTMLElement, label: string): HTMLButtonElement {
  const button = host.querySelector(`button[aria-label="Toggle ${label} category visibility"]`)
  if (!(button instanceof HTMLButtonElement)) throw new Error(`missing category toggle ${label}`)
  return button
}

function findingSelect(host: HTMLElement, text: string): HTMLButtonElement {
  const button = [...host.querySelectorAll('button.bl-finding-select')].find((item) => item.textContent?.includes(text))
  if (!(button instanceof HTMLButtonElement)) throw new Error(`missing finding select ${text}`)
  return button
}

function setPage(host: HTMLElement, page: number) {
  const pageSelect = host.querySelector('[aria-label="Select page"]')
  if (!(pageSelect instanceof HTMLSelectElement)) throw new Error('missing page selector')
  pageSelect.value = String(page)
  pageSelect.dispatchEvent(new Event('change'))
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

    const jobSelect = host.querySelector('[aria-label="Extraction run"]')
    if (!(jobSelect instanceof HTMLSelectElement)) throw new Error('missing job selector')
    jobSelect.value = JOB_ID
    jobSelect.dispatchEvent(new Event('change'))
    await flush()

    expect(host.textContent).toContain('water')
    expect(host.textContent).not.toContain('mixing')
    expect(host.textContent).toContain('Not approved')
    expect(buttonNamed(host, '+ Add finding')).toBeTruthy()
    expect(buttonNamed(host, 'Download TXT').disabled).toBe(false)

    findingSelect(host, 'water').click()
    await flush()
    const waterMark = host.querySelector(`[data-finding-id="${WATER_ID}"]`)
    expect(waterMark?.classList.contains('bl-hit--focus')).toBe(true)

    const display = host.querySelector(`[aria-label="Display text ${WATER_ID}"]`)
    if (!(display instanceof HTMLInputElement)) throw new Error('missing display text')
    display.value = 'purified water'
    display.dispatchEvent(new Event('change'))
    await nextTick()

    expect(buttonNamed(host, 'Approve extraction result').disabled).toBe(true)
    expect(buttonNamed(host, 'Download TXT').disabled).toBe(true)
    expect(host.textContent).toContain('Save before approval. Unsaved edits are not included.')
    expect(approveCalls).toEqual([])

    buttonNamed(host, 'All findings').click()
    await nextTick()
    expect([...host.querySelectorAll('button')].some((item) => item.textContent?.includes('+ Add finding'))).toBe(false)
    expect(host.querySelector(`[aria-label="Display text ${WATER_ID}"]`)).toBeNull()
    findingSelect(host, 'mixing').click()
    await flush()

    const pageSelect = host.querySelector('[aria-label="Select page"]')
    if (!(pageSelect instanceof HTMLSelectElement)) throw new Error('missing page selector')
    expect(pageSelect.value).toBe('2')
    expect(buttonNamed(host, 'By page').getAttribute('aria-pressed')).toBe('true')
  })

  it('opens the explicit initialLocalJobId from options when present in the jobs list', async () => {
    const otherJob = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    const otherOpened: OpenedExtractionReview = {
      ...opened,
      local_job_id: otherJob,
      findings: [{
        ...opened.findings[0],
        finding_id: 'other-water',
        display_text: 'other water',
      }],
    }
    const openedUrls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.endsWith('/jobs') && method === 'GET') {
        return json({
          jobs: [
            {
              local_job_id: otherJob,
              job_id: 'job-older',
              review_revision_id: 'rev-older',
              action: 'extract_all',
              extraction_overall: 'completed',
              finished_at: '2026-01-01T00:00:00+00:00',
            },
            {
              local_job_id: JOB_ID,
              job_id: 'job-1',
              review_revision_id: 'rev-doc-1',
              action: 'extract_all',
              extraction_overall: 'completed',
              finished_at: '2026-01-02T00:00:00+00:00',
            },
          ],
        })
      }
      const pageMatch = url.match(/\/pages\/(\d+)$/)
      if (pageMatch) return json({ page_number: Number(pageMatch[1]), html: pageHtml[Number(pageMatch[1])] })
      openedUrls.push(url)
      if (url.includes(otherJob)) return json(otherOpened)
      return json(opened)
    }))

    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(ExtractionReviewWorkspace, { options: { initialLocalJobId: JOB_ID } })
    app.mount(host)
    mounts.push({
      unmount: () => {
        app.unmount()
        host.remove()
      },
    })
    await flush()

    const jobSelect = host.querySelector('[aria-label="Extraction run"]')
    if (!(jobSelect instanceof HTMLSelectElement)) throw new Error('missing job selector')
    await waitFor(() => jobSelect.value === JOB_ID, 'initialLocalJobId selection')
    expect(jobSelect.value).toBe(JOB_ID)
    expect(openedUrls.some((url) => url.includes(JOB_ID))).toBe(true)
    expect(openedUrls.some((url) => url.includes(otherJob))).toBe(false)
    expect(host.textContent).toContain('water')
    expect(host.textContent).not.toContain('other water')
  })

  it('labels the selector as Extraction run and distinguishes two similar runs', async () => {
    const otherJob = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    const otherOpened: OpenedExtractionReview = {
      ...opened,
      local_job_id: otherJob,
      findings: [{
        ...opened.findings[0],
        finding_id: 'other-water',
        display_text: 'other water',
      }],
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.endsWith('/jobs') && method === 'GET') {
        return json({
          jobs: [
            {
              local_job_id: JOB_ID,
              job_id: 'job-1',
              review_revision_id: 'rev-doc-1',
              action: 'extract_all',
              extraction_overall: 'completed',
              finished_at: '2026-01-01T10:00:00+00:00',
            },
            {
              local_job_id: otherJob,
              job_id: 'job-1',
              review_revision_id: 'rev-doc-1',
              action: 'extract_all',
              extraction_overall: 'completed',
              finished_at: '2026-01-02T11:00:00+00:00',
            },
          ],
        })
      }
      const pageMatch = url.match(/\/pages\/(\d+)$/)
      if (pageMatch) return json({ page_number: Number(pageMatch[1]), html: pageHtml[Number(pageMatch[1])] })
      if (url.includes(otherJob)) return json(otherOpened)
      return json(opened)
    }))

    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(ExtractionReviewWorkspace, { options: { initialLocalJobId: JOB_ID } })
    app.mount(host)
    mounts.push({
      unmount: () => {
        app.unmount()
        host.remove()
      },
    })
    await flush()

    const jobSelect = host.querySelector('[aria-label="Extraction run"]')
    if (!(jobSelect instanceof HTMLSelectElement)) throw new Error('missing run selector')
    expect(jobSelect.getAttribute('aria-label')).toBe('Extraction run')
    await waitFor(() => jobSelect.options.length >= 3, 'extraction run options')
    const labels = [...jobSelect.options].map((option) => option.textContent ?? '')
    expect(labels.some((label) => label.includes('Select a completed extraction run'))).toBe(true)
    const runLabels = labels.filter((label) => label.includes('extract all'))
    expect(runLabels).toHaveLength(2)
    expect(runLabels[0]).toContain('completed')
    expect(runLabels[0]).toContain('2026-01-01T10:00:00+00:00')
    expect(runLabels[0]).toContain(JOB_ID.slice(-8))
    expect(runLabels[1]).toContain('2026-01-02T11:00:00+00:00')
    expect(runLabels[1]).toContain(otherJob.slice(-8))
    expect(runLabels[0]).not.toBe(runLabels[1])
    await waitFor(() => jobSelect.value === JOB_ID, 'initial run selected')
    expect(jobSelect.value).toBe(JOB_ID)

    jobSelect.value = otherJob
    jobSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => jobSelect.value === otherJob, 'second run selected')
    expect(jobSelect.value).toBe(otherJob)
    expect(host.textContent).toContain('other water')
  })

  it('reopens the same initialLocalJobId after a second mount (browser refresh)', async () => {
    const otherJob = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    const openedUrls: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.endsWith('/jobs') && method === 'GET') {
        return json({
          jobs: [
            {
              local_job_id: otherJob,
              job_id: 'job-1',
              review_revision_id: 'rev-doc-1',
              action: 'extract_all',
              extraction_overall: 'completed',
              finished_at: '2026-01-01T00:00:00+00:00',
            },
            {
              local_job_id: JOB_ID,
              job_id: 'job-1',
              review_revision_id: 'rev-doc-1',
              action: 'extract_all',
              extraction_overall: 'completed',
              finished_at: '2026-01-02T00:00:00+00:00',
            },
          ],
        })
      }
      const pageMatch = url.match(/\/pages\/(\d+)$/)
      if (pageMatch) return json({ page_number: Number(pageMatch[1]), html: pageHtml[Number(pageMatch[1])] })
      openedUrls.push(url)
      return json(opened)
    })
    vi.stubGlobal('fetch', fetchMock)

    for (let mountIndex = 0; mountIndex < 2; mountIndex += 1) {
      openedUrls.length = 0
      const host = document.createElement('div')
      document.body.append(host)
      const app = createApp(ExtractionReviewWorkspace, { options: { initialLocalJobId: JOB_ID } })
      app.mount(host)
      mounts.push({
        unmount: () => {
          app.unmount()
          host.remove()
        },
      })
      await flush()
      const jobSelect = host.querySelector('[aria-label="Extraction run"]')
      if (!(jobSelect instanceof HTMLSelectElement)) throw new Error('missing run selector')
      await waitFor(() => jobSelect.value === JOB_ID, `initialLocalJobId on mount ${mountIndex}`)
      expect(jobSelect.value).toBe(JOB_ID)
      expect(openedUrls.some((url) => url.includes(JOB_ID))).toBe(true)
      expect(openedUrls.some((url) => url.includes(otherJob))).toBe(false)
      app.unmount()
      host.remove()
      mounts.pop()
    }
  })

  it('toggles category visibility for rows and overlays without save or API mutation', async () => {
    const requests: Array<{ url: string; method: string; body?: string }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      const body = typeof init?.body === 'string' ? init.body : undefined
      requests.push({ url, method, body })
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

    const jobSelect = host.querySelector('[aria-label="Extraction run"]')
    if (!(jobSelect instanceof HTMLSelectElement)) throw new Error('missing job selector')
    jobSelect.value = JOB_ID
    jobSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => Boolean(host.querySelector(`[data-finding-id="${WATER_ID}"]`)), 'page marks')
    requests.length = 0

    const material = categoryToggle(host, 'Material')
    const unitOp = categoryToggle(host, 'Unit operation')
    expect(material.getAttribute('aria-pressed')).toBe('true')
    expect(unitOp.getAttribute('aria-pressed')).toBe('true')
    expect(material.classList.contains('is-off')).toBe(false)
    expect(host.textContent).toContain('water')
    expect(host.querySelector(`[data-finding-id="${WATER_ID}"]`)?.classList.contains('bl-hit--hidden')).toBe(false)
    expect(host.querySelector('button[aria-label^="Toggle highlight for "]')).toBeNull()

    material.click()
    await flush()
    expect(material.getAttribute('aria-pressed')).toBe('false')
    expect(material.classList.contains('is-off')).toBe(true)
    expect([...host.querySelectorAll('.bl-finding-select')].some((item) => item.textContent?.includes('water'))).toBe(false)
    expect(host.querySelector(`[data-finding-id="${WATER_ID}"]`)?.classList.contains('bl-hit--hidden')).toBe(true)
    expect(host.textContent).not.toContain('Unsaved')
    expect(requests.filter((item) => item.method !== 'GET')).toEqual([])

    buttonNamed(host, 'All findings').click()
    await nextTick()
    expect([...host.querySelectorAll('.bl-finding-select')].some((item) => item.textContent?.includes('water'))).toBe(false)
    expect(host.textContent).toContain('mixing')

    findingSelect(host, 'mixing').click()
    await flush()
    expect(host.querySelector(`[data-finding-id="${MIXING_ID}"]`)?.classList.contains('bl-hit--hidden')).toBe(false)
    expect(host.querySelector(`[data-finding-id="${MIXING_ID}"]`)?.classList.contains('bl-hit--focus')).toBe(true)

    buttonNamed(host, 'By page').click()
    setPage(host, 1)
    await flush()
    material.click()
    await flush()
    expect(material.getAttribute('aria-pressed')).toBe('true')
    expect(material.classList.contains('is-off')).toBe(false)
    expect([...host.querySelectorAll('.bl-finding-select')].some((item) => item.textContent?.includes('water'))).toBe(true)
    expect(host.querySelector(`[data-finding-id="${WATER_ID}"]`)?.classList.contains('bl-hit--hidden')).toBe(false)
    expect(requests.filter((item) => item.method !== 'GET')).toEqual([])

    findingSelect(host, 'water').click()
    await flush()
    expect(host.querySelector(`[data-finding-id="${WATER_ID}"]`)?.classList.contains('bl-hit--focus')).toBe(true)
    expect(host.querySelector(`[data-finding-id="${WATER_ID}"]`)?.classList.contains('bl-hit--hidden')).toBe(false)
    expect(requests.filter((item) => item.method !== 'GET')).toEqual([])
  })

  it('supports remove/restore, local add drafts, and does not dirty save state for presentation toggles', async () => {
    const requests: Array<{ url: string; method: string; body?: string }> = []
    let current: OpenedExtractionReview = structuredClone(opened)
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      const body = typeof init?.body === 'string' ? init.body : undefined
      requests.push({ url, method, body })
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
      const pageMatch = url.match(/\/pages\/(\d+)$/)
      if (pageMatch) return json({ page_number: Number(pageMatch[1]), html: pageHtml[Number(pageMatch[1])] })
      if (method === 'PUT' && body) {
        const payload = JSON.parse(body) as { edits: Array<Record<string, string>> }
        for (const edit of payload.edits) {
          if (edit.op === 'remove') {
            const finding = current.findings.find((item) => item.finding_id === edit.finding_id)
            if (finding) {
              finding.removed = true
              finding.removed_by_user = true
            }
          }
          if (edit.op === 'restore') {
            const finding = current.findings.find((item) => item.finding_id === edit.finding_id)
            if (finding) {
              finding.removed = false
              finding.removed_by_user = false
            }
          }
          if (edit.op === 'add') {
            const added: ExtractionFinding = {
              finding_id: edit.finding_id,
              component: edit.component,
              display_text: edit.display_text,
              page_number: Number(edit.page_number),
              evidence_status: 'no_document_evidence',
              removed: false,
              origin_kind: 'user_added',
              block_node_id: null,
              start_char: null,
              end_char: null,
              original_matched_text: null,
              added_by_user: true,
              changed_by_user: false,
              removed_by_user: false,
            }
            current = { ...current, findings: [...current.findings, added] }
          }
        }
        current = {
          ...current,
          current_revision_id: '22222222-2222-4222-8222-222222222222',
        }
        return json(current)
      }
      if (url.endsWith('/results.txt')) {
        return new Response('Materials\n- water (page 1)\n', {
          status: 200,
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        })
      }
      return json(current)
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

    const jobSelect = host.querySelector('[aria-label="Extraction run"]')
    if (!(jobSelect instanceof HTMLSelectElement)) throw new Error('missing job selector')
    jobSelect.value = JOB_ID
    jobSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => Boolean(host.querySelector(`[data-finding-id="${WATER_ID}"]`)), 'page marks before edit')
    requests.length = 0

    buttonNamed(host, 'Remove').click()
    await nextTick()
    expect(host.textContent).toContain('Removed')
    expect(buttonNamed(host, 'Restore')).toBeTruthy()
    expect(host.textContent).toContain('Unsaved')

    buttonNamed(host, 'Restore').click()
    await nextTick()
    expect(buttonNamed(host, 'Remove')).toBeTruthy()

    buttonNamed(host, 'Remove').click()
    await nextTick()
    buttonNamed(host, 'Save').click()
    await flush()
    expect(requests.some((item) => item.method === 'PUT' && item.body?.includes('"op":"remove"'))).toBe(true)
    expect(host.textContent).toContain('Removed')
    expect(buttonNamed(host, 'Restore')).toBeTruthy()

    requests.length = 0
    buttonNamed(host, '+ Add finding').click()
    await nextTick()
    expect(requests).toEqual([])
    expect(host.textContent).toContain('Unsaved draft')
    expect(host.textContent).toContain('No document evidence')
    expect(host.textContent).not.toContain('New finding')
    const draftInput = [...host.querySelectorAll('input')].find((item) => item.getAttribute('aria-label')?.startsWith('Display text '))
    if (!(draftInput instanceof HTMLInputElement)) throw new Error('missing draft input')
    expect(draftInput.value).toBe('')
    expect(draftInput.placeholder).toBe('Enter finding text')

    buttonNamed(host, 'Save').click()
    await flush()
    expect(requests.some((item) => item.method === 'PUT')).toBe(false)
    expect(host.textContent).toContain('Added findings need display text before Save.')

    draftInput.value = '   '
    draftInput.dispatchEvent(new Event('change'))
    await nextTick()
    buttonNamed(host, 'Save').click()
    await flush()
    expect(requests.some((item) => item.method === 'PUT')).toBe(false)

    draftInput.value = 'operator note'
    draftInput.dispatchEvent(new Event('change'))
    await nextTick()
    buttonNamed(host, 'Save').click()
    await flush()
    expect(requests.some((item) => item.method === 'PUT' && item.body?.includes('"op":"add"') && item.body.includes('operator note'))).toBe(true)
    expect(host.textContent).toContain('operator note')
  })
})

function json(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}
