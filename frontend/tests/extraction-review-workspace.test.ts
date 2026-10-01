import { createApp, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ExtractionReviewWorkspace from '../src/components/ExtractionReviewWorkspace.vue'
import {
  buildPageClassificationsTsv,
  formatPageClassificationColumn,
  pageClassificationsDownloadFilename,
  type ClassificationStateView,
  type ExtractionFinding,
  type OpenedExtractionReview,
  type PageClassificationView,
} from '../src/extractionReview'

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
    installFetch(async (url, method, init) => {
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
    })

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
    installFetch(async (url, method) => {
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
    })

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
    installFetch(async (url, method) => {
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
    })

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
      const bootstrapped = stage4Bootstrap(url, method)
      if (bootstrapped) return bootstrapped
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
    installFetch(async (url, method, init) => {
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
    })

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
    installFetch(async (url, method, init) => {
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
    })

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

  it('selects an approved document, shows classification, and keeps Extract All usable with needs_review', async () => {
    const classification = {
      job_id: 'job-1',
      review_revision_id: 'rev-doc-1',
      status: 'completed',
      progress: { total_pages: 2, completed_pages: 2, current_page_number: null },
      created_at: '2026-10-01T00:00:00+00:00',
      updated_at: '2026-10-01T00:00:00+00:00',
      finished_at: '2026-10-01T00:00:00+00:00',
      terminal_reason: null,
      source: 'current' as const,
      pages: [
        {
          page_number: 1,
          kind: 'needs_review',
          requires_review: true,
          is_provisional: false,
          applied_other_unclassified: false,
          labels: [{
            label: 'BILL_OF_MATERIALS',
            quote: 'materials',
            reason: 'bom page',
            element_id: 'n1',
            evidence_verification: 'verified',
            evidence_verification_reason: null,
            provenance: 'call',
          }],
          evidence: [],
          source_validation: { has_unverified: false, requires_review: true, items: [] },
          eligibility: {
            eligible_for_extraction: true,
            reason: 'page remains eligible for lexical extraction',
            excluded_by_policy: false,
          },
        },
        {
          page_number: 2,
          kind: 'completed',
          requires_review: false,
          is_provisional: false,
          applied_other_unclassified: false,
          labels: [],
          evidence: [],
          source_validation: { has_unverified: false, requires_review: false, items: [] },
          eligibility: {
            eligible_for_extraction: true,
            reason: 'page remains eligible for lexical extraction',
            excluded_by_policy: false,
          },
        },
      ],
    }

    installFetch(async (url, method) => {
      if (url.endsWith('/jobs') && method === 'GET') return json({ jobs: [] })
      if (url.includes('/approved-documents/') && url.endsWith('/pages') && method === 'GET') {
        return json({ job_id: 'job-1', review_revision_id: 'rev-doc-1', pages: [1, 2] })
      }
      if (url.includes('/approved-documents/') && url.includes('/pages/') && method === 'GET') {
        const pageMatch = url.match(/\/pages\/(\d+)$/)
        return json({
          page_number: Number(pageMatch?.[1] ?? 1),
          html: pageHtml[Number(pageMatch?.[1] ?? 1)] ?? '',
        })
      }
      if (url.includes('/classification') && method === 'GET') {
        return json({ classification })
      }
      if (url.endsWith('/extract-all') && method === 'POST') {
        return json({
          kind: 'no_eligible_pages',
          message: 'No pages are eligible for lexical extraction under the classification policy.',
        })
      }
      return null
    }, { documents: [{ job_id: 'job-1', review_revision_id: 'rev-doc-1' }] })

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

    const docSelect = host.querySelector('[aria-label="Approved document"]')
    if (!(docSelect instanceof HTMLSelectElement)) throw new Error('missing document selector')
    docSelect.value = 'job-1::rev-doc-1'
    docSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => host.textContent?.includes('BILL_OF_MATERIALS') === true, 'classification labels')

    expect(host.textContent).toContain('needs review')
    expect(host.textContent).toContain('eligible')
    expect(host.textContent).toContain('Informational only')
    expect([...host.querySelectorAll('button')].some((item) => item.textContent?.includes('Classify pages'))).toBe(false)
    expect(buttonNamed(host, 'Extract All').disabled).toBe(false)

    setPage(host, 2)
    await flush()
    expect(host.textContent).not.toContain('BILL_OF_MATERIALS')

    buttonNamed(host, 'Extract All').click()
    await flush()
    expect(host.textContent).toContain('No pages are eligible for lexical extraction under the classification policy.')
  })

  it('shows running classification progress and disables conflicting actions', async () => {
    installFetch(async (url, method) => {
      if (url.endsWith('/jobs') && method === 'GET') return json({ jobs: [] })
      if (url.includes('/approved-documents/') && url.endsWith('/pages') && method === 'GET') {
        return json({ job_id: 'job-1', review_revision_id: 'rev-doc-1', pages: [1, 2] })
      }
      if (url.includes('/approved-documents/') && url.includes('/pages/') && method === 'GET') {
        return json({ page_number: 1, html: pageHtml[1] })
      }
      if (url.includes('/classification') && method === 'GET') {
        return json({
          classification: {
            job_id: 'job-1',
            review_revision_id: 'rev-doc-1',
            status: 'running',
            progress: { total_pages: 2, completed_pages: 0, current_page_number: 1 },
            created_at: '2026-10-01T00:00:00+00:00',
            updated_at: '2026-10-01T00:00:00+00:00',
            finished_at: null,
            terminal_reason: null,
            source: 'current',
            pages: [],
          },
        })
      }
      return null
    }, { documents: [{ job_id: 'job-1', review_revision_id: 'rev-doc-1' }] })

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

    const docSelect = host.querySelector('[aria-label="Approved document"]')
    if (!(docSelect instanceof HTMLSelectElement)) throw new Error('missing document selector')
    docSelect.value = 'job-1::rev-doc-1'
    docSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => host.textContent?.includes('Classifying page') === true, 'running progress')

    expect(buttonNamed(host, 'Extract All').disabled).toBe(true)
    expect(docSelect.disabled).toBe(true)
    expect([...host.querySelectorAll('button')].some((item) => item.textContent?.includes('Classify pages'))).toBe(false)
  })

  it('shows lexical progress separately and opens a completed classified run with snapshot labels', async () => {
    let lexicalStatus = 'running'
    const classifiedOpened: OpenedExtractionReview = {
      ...opened,
      classification: {
        job_id: 'job-1',
        review_revision_id: 'rev-doc-1',
        status: 'completed',
        progress: { total_pages: 2, completed_pages: 2, current_page_number: null },
        created_at: '2026-10-01T00:00:00+00:00',
        updated_at: '2026-10-01T00:00:00+00:00',
        finished_at: '2026-10-01T00:00:00+00:00',
        terminal_reason: null,
        source: 'job_snapshot',
        pages: [{
          page_number: 1,
          kind: 'completed',
          requires_review: false,
          is_provisional: false,
          applied_other_unclassified: false,
          labels: [{
            label: 'PROCESS_EXECUTION',
            quote: 'step',
            reason: 'execution',
            element_id: 'n1',
            evidence_verification: 'verified',
            evidence_verification_reason: null,
            provenance: 'call',
          }],
          evidence: [],
          source_validation: { has_unverified: false, requires_review: false, items: [] },
          eligibility: {
            eligible_for_extraction: true,
            reason: 'page remains eligible for lexical extraction',
            excluded_by_policy: false,
          },
        }, {
          page_number: 2,
          kind: 'completed',
          requires_review: false,
          is_provisional: false,
          applied_other_unclassified: false,
          labels: [],
          evidence: [],
          source_validation: { has_unverified: false, requires_review: false, items: [] },
          eligibility: {
            eligible_for_extraction: true,
            reason: 'page remains eligible for lexical extraction',
            excluded_by_policy: false,
          },
        }],
      },
    }

    installFetch(async (url, method) => {
      if (url.endsWith('/jobs') && method === 'GET') {
        return json({
          jobs: lexicalStatus === 'completed'
            ? [{
                local_job_id: JOB_ID,
                job_id: 'job-1',
                review_revision_id: 'rev-doc-1',
                action: 'extract_all',
                extraction_overall: 'completed',
                finished_at: '2026-10-01T00:00:00+00:00',
              }]
            : [],
        })
      }
      if (url.includes('/approved-documents/') && url.endsWith('/pages') && method === 'GET') {
        return json({ job_id: 'job-1', review_revision_id: 'rev-doc-1', pages: [1, 2] })
      }
      if (url.includes('/approved-documents/') && url.includes('/pages/') && method === 'GET') {
        return json({ page_number: 1, html: pageHtml[1] })
      }
      if (url.includes('/classification') && method === 'GET') {
        return json({
          classification: {
            job_id: 'job-1',
            review_revision_id: 'rev-doc-1',
            status: 'completed',
            progress: { total_pages: 2, completed_pages: 2, current_page_number: null },
            created_at: '2026-10-01T00:00:00+00:00',
            updated_at: '2026-10-01T00:00:00+00:00',
            finished_at: '2026-10-01T00:00:00+00:00',
            terminal_reason: null,
            source: 'current',
            pages: classifiedOpened.classification?.pages ?? [],
          },
        })
      }
      if (url.endsWith('/extract-all') && method === 'POST') {
        return json({
          kind: 'submitted',
          job: {
            local_job_id: JOB_ID,
            job_id: 'job-1',
            review_revision_id: 'rev-doc-1',
            status: 'queued',
            phase: 'queued',
            action: 'extract_all',
            submitted_at: '2026-10-01T00:00:00+00:00',
            started_at: null,
            finished_at: null,
            error_code: null,
            error_message: null,
            classified: true,
            selected_page_numbers: [1, 2],
            extraction_overall: null,
            reviewable: false,
          },
        })
      }
      if (url.includes('/local-jobs/') && method === 'GET') {
        const status = lexicalStatus
        if (status === 'running') lexicalStatus = 'completed'
        return json({
          local_job_id: JOB_ID,
          job_id: 'job-1',
          review_revision_id: 'rev-doc-1',
          status,
          phase: status === 'completed' ? 'completed' : 'running_extraction',
          action: 'extract_all',
          submitted_at: '2026-10-01T00:00:00+00:00',
          started_at: '2026-10-01T00:00:01+00:00',
          finished_at: status === 'completed' ? '2026-10-01T00:00:02+00:00' : null,
          error_code: null,
          error_message: null,
          classified: true,
          selected_page_numbers: [1, 2],
          extraction_overall: status === 'completed' ? 'completed' : null,
          reviewable: status === 'completed',
        })
      }
      const pageMatch = url.match(/\/jobs\/[^/]+\/pages\/(\d+)$/)
      if (pageMatch) return json({ page_number: Number(pageMatch[1]), html: pageHtml[Number(pageMatch[1])] })
      if (url.includes(`/jobs/${JOB_ID}`) && method === 'GET') return json(classifiedOpened)
      return null
    }, { documents: [{ job_id: 'job-1', review_revision_id: 'rev-doc-1' }] })

    vi.useFakeTimers()
    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(ExtractionReviewWorkspace, { options: {} })
    app.mount(host)
    mounts.push({
      unmount: () => {
        vi.useRealTimers()
        app.unmount()
        host.remove()
      },
    })
    await flush()

    const docSelect = host.querySelector('[aria-label="Approved document"]')
    if (!(docSelect instanceof HTMLSelectElement)) throw new Error('missing document selector')
    docSelect.value = 'job-1::rev-doc-1'
    docSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => buttonNamed(host, 'Extract All').disabled === false, 'extract enabled')

    buttonNamed(host, 'Extract All').click()
    await flush()
    expect(host.textContent).toContain('Lexical')
    expect(host.textContent).toMatch(/queued|running/)

    lexicalStatus = 'running'
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    await vi.advanceTimersByTimeAsync(1000)
    await flush()

    await waitFor(() => host.textContent?.includes('PROCESS_EXECUTION') === true, 'snapshot label')
    await waitFor(() => host.textContent?.includes('water') === true, 'lexical findings')
    expect(host.textContent).toContain('classification snapshot')
    expect(host.textContent).toContain('water')
    vi.useRealTimers()
  })

  it('shows a terminal non-reviewable classified job without opening Stage 3', async () => {
    let lexicalStatus = 'running'
    const openUrls: string[] = []

    installFetch(async (url, method) => {
      if (url.includes(`/jobs/${JOB_ID}`) && method === 'GET' && !url.includes('/local-jobs/')) {
        openUrls.push(url)
        return json(opened)
      }
      if (url.endsWith('/jobs') && method === 'GET') {
        return json({ jobs: [] })
      }
      if (url.includes('/approved-documents/') && url.endsWith('/pages') && method === 'GET') {
        return json({ job_id: 'job-1', review_revision_id: 'rev-doc-1', pages: [1, 2] })
      }
      if (url.includes('/approved-documents/') && url.includes('/pages/') && method === 'GET') {
        return json({ page_number: 1, html: pageHtml[1] })
      }
      if (url.includes('/classification') && method === 'GET') {
        return json({
          classification: {
            job_id: 'job-1',
            review_revision_id: 'rev-doc-1',
            status: 'completed',
            progress: { total_pages: 2, completed_pages: 2, current_page_number: null },
            created_at: '2026-10-01T00:00:00+00:00',
            updated_at: '2026-10-01T00:00:00+00:00',
            finished_at: '2026-10-01T00:00:00+00:00',
            terminal_reason: null,
            source: 'current',
            pages: [],
          },
        })
      }
      if (url.endsWith('/extract-all') && method === 'POST') {
        return json({
          kind: 'submitted',
          job: {
            local_job_id: JOB_ID,
            job_id: 'job-1',
            review_revision_id: 'rev-doc-1',
            status: 'queued',
            phase: 'queued',
            action: 'extract_all',
            submitted_at: '2026-10-01T00:00:00+00:00',
            started_at: null,
            finished_at: null,
            error_code: null,
            error_message: null,
            classified: true,
            selected_page_numbers: [2, 3],
            extraction_overall: null,
            reviewable: false,
          },
        })
      }
      if (url.includes('/local-jobs/') && method === 'GET') {
        const status = lexicalStatus
        if (status === 'running') lexicalStatus = 'completed'
        return json({
          local_job_id: JOB_ID,
          job_id: 'job-1',
          review_revision_id: 'rev-doc-1',
          status,
          phase: status === 'completed' ? 'completed' : 'running_extraction',
          action: 'extract_all',
          submitted_at: '2026-10-01T00:00:00+00:00',
          started_at: '2026-10-01T00:00:01+00:00',
          finished_at: status === 'completed' ? '2026-10-01T00:00:02+00:00' : null,
          error_code: null,
          error_message: null,
          classified: true,
          selected_page_numbers: [2, 3],
          extraction_overall: status === 'completed' ? 'failed' : null,
          reviewable: false,
        })
      }
      return null
    }, { documents: [{ job_id: 'job-1', review_revision_id: 'rev-doc-1' }] })

    vi.useFakeTimers()
    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(ExtractionReviewWorkspace, { options: {} })
    app.mount(host)
    mounts.push({
      unmount: () => {
        vi.useRealTimers()
        app.unmount()
        host.remove()
      },
    })
    await flush()

    const docSelect = host.querySelector('[aria-label="Approved document"]')
    if (!(docSelect instanceof HTMLSelectElement)) throw new Error('missing document selector')
    docSelect.value = 'job-1::rev-doc-1'
    docSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => buttonNamed(host, 'Extract All').disabled === false, 'extract enabled')

    buttonNamed(host, 'Extract All').click()
    await flush()

    lexicalStatus = 'running'
    await vi.advanceTimersByTimeAsync(1000)
    await flush()
    await vi.advanceTimersByTimeAsync(1000)
    await flush()

    await waitFor(
      () => host.textContent?.includes('no usable completed extraction component') === true,
      'non-reviewable message',
    )
    expect(openUrls).toEqual([])
    expect(host.textContent).not.toContain('JOB_NOT_REVIEWABLE')
    expect(host.textContent).not.toContain('By page')
    expect(host.textContent).not.toContain('All findings')
    expect(buttonNamed(host, 'Save').disabled).toBe(true)
    expect(buttonNamed(host, 'Download TXT').disabled).toBe(true)
    expect(buttonNamed(host, 'Approve extraction result').disabled).toBe(true)
    vi.useRealTimers()
  })

  it('switching approved document after an open run clears prior findings and loads the new document', async () => {
    const otherClassification = {
      job_id: 'job-2',
      review_revision_id: 'rev-doc-2',
      status: 'completed',
      progress: { total_pages: 1, completed_pages: 1, current_page_number: null },
      created_at: '2026-10-01T00:00:00+00:00',
      updated_at: '2026-10-01T00:00:00+00:00',
      finished_at: '2026-10-01T00:00:00+00:00',
      terminal_reason: null,
      source: 'current' as const,
      pages: [{
        page_number: 1,
        kind: 'completed',
        requires_review: false,
        is_provisional: false,
        applied_other_unclassified: false,
        labels: [{
          label: 'COVER_PAGE',
          quote: 'cover',
          reason: 'cover',
          element_id: 'c1',
          evidence_verification: 'verified',
          evidence_verification_reason: null,
          provenance: 'call',
        }],
        evidence: [],
        source_validation: { has_unverified: false, requires_review: false, items: [] },
        eligibility: {
          eligible_for_extraction: false,
          reason: 'every final label belongs to the fixed exclusion set',
          excluded_by_policy: true,
        },
      }],
    }
    const otherHtml = '<section class="page" data-page="1"><p>Other document page</p></section>'

    installFetch(async (url, method) => {
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
      if (url.includes('/approved-documents/job-2/') && url.endsWith('/pages') && method === 'GET') {
        return json({ job_id: 'job-2', review_revision_id: 'rev-doc-2', pages: [1] })
      }
      if (url.includes('/approved-documents/job-1/') && url.endsWith('/pages') && method === 'GET') {
        return json({ job_id: 'job-1', review_revision_id: 'rev-doc-1', pages: [1, 2] })
      }
      if (url.includes('/approved-documents/job-2/') && url.includes('/pages/') && method === 'GET') {
        return json({ page_number: 1, html: otherHtml })
      }
      if (url.includes('/approved-documents/job-1/') && url.includes('/pages/') && method === 'GET') {
        const pageMatch = url.match(/\/pages\/(\d+)$/)
        return json({ page_number: Number(pageMatch?.[1] ?? 1), html: pageHtml[Number(pageMatch?.[1] ?? 1)] })
      }
      if (url.includes('/approved-documents/job-2/') && url.includes('/classification')) {
        return json({ classification: otherClassification })
      }
      if (url.includes('/approved-documents/job-1/') && url.includes('/classification')) {
        return json({ classification: null })
      }
      const pageMatch = url.match(/\/jobs\/[^/]+\/pages\/(\d+)$/)
      if (pageMatch) return json({ page_number: Number(pageMatch[1]), html: pageHtml[Number(pageMatch[1])] })
      if (url.includes(`/jobs/${JOB_ID}`) && method === 'GET') {
        return json({ ...opened, classification: null })
      }
      return null
    }, {
      documents: [
        { job_id: 'job-1', review_revision_id: 'rev-doc-1' },
        { job_id: 'job-2', review_revision_id: 'rev-doc-2' },
      ],
    })

    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(ExtractionReviewWorkspace, { options: { initialLocalJobId: JOB_ID } })
    app.mount(host)
    mounts.push({ unmount: () => { app.unmount(); host.remove() } })
    await flush()
    await waitFor(() => host.textContent?.includes('water') === true, 'initial findings')

    const docSelect = host.querySelector('[aria-label="Approved document"]')
    if (!(docSelect instanceof HTMLSelectElement)) throw new Error('missing document selector')
    docSelect.value = 'job-2::rev-doc-2'
    docSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => host.textContent?.includes('COVER_PAGE') === true, 'new classification')
    expect(host.textContent).toContain('Other document page')
    expect(host.textContent).toContain('COVER_PAGE')
    expect(host.textContent).not.toContain('water')
    expect(host.querySelector('[aria-label="Extraction findings"] .bl-finding-list')).toBeNull()
    const runSelect = host.querySelector('[aria-label="Extraction run"]')
    if (!(runSelect instanceof HTMLSelectElement)) throw new Error('missing run selector')
    expect(runSelect.value).toBe('')
  })

  it('blocks approved-document switch while unsaved edits exist and keeps the current review', async () => {
    installFetch(async (url, method) => {
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
      if (url.includes('/approved-documents/') && url.endsWith('/pages') && method === 'GET') {
        return json({ job_id: 'job-1', review_revision_id: 'rev-doc-1', pages: [1, 2] })
      }
      if (url.includes('/approved-documents/') && url.includes('/pages/') && method === 'GET') {
        return json({ page_number: 1, html: pageHtml[1] })
      }
      const pageMatch = url.match(/\/pages\/(\d+)$/)
      if (pageMatch) return json({ page_number: Number(pageMatch[1]), html: pageHtml[Number(pageMatch[1])] })
      if (url.includes(`/jobs/${JOB_ID}`) && method === 'GET') return json(opened)
      return null
    }, {
      documents: [
        { job_id: 'job-1', review_revision_id: 'rev-doc-1' },
        { job_id: 'job-2', review_revision_id: 'rev-doc-2' },
      ],
    })

    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(ExtractionReviewWorkspace, { options: { initialLocalJobId: JOB_ID } })
    app.mount(host)
    mounts.push({ unmount: () => { app.unmount(); host.remove() } })
    await flush()
    await waitFor(() => Boolean(host.querySelector(`[aria-label="Display text ${WATER_ID}"]`)), 'editable finding')

    const display = host.querySelector(`[aria-label="Display text ${WATER_ID}"]`)
    if (!(display instanceof HTMLInputElement)) throw new Error('missing display text')
    display.value = 'unsaved water'
    display.dispatchEvent(new Event('change'))
    await nextTick()
    expect(host.textContent).toContain('Unsaved')

    const docSelect = host.querySelector('[aria-label="Approved document"]')
    if (!(docSelect instanceof HTMLSelectElement)) throw new Error('missing document selector')
    docSelect.value = 'job-2::rev-doc-2'
    docSelect.dispatchEvent(new Event('change'))
    await flush()

    expect(host.textContent).toContain('Save the current extraction result before switching documents.')
    expect(docSelect.value).toBe('job-1::rev-doc-1')
    expect(host.textContent).toContain('Unsaved')
    expect(host.querySelector(`[aria-label="Display text ${WATER_ID}"]`)).toBeTruthy()
    const runSelect = host.querySelector('[aria-label="Extraction run"]')
    if (!(runSelect instanceof HTMLSelectElement)) throw new Error('missing run selector')
    expect(runSelect.value).toBe(JOB_ID)
  })

  it('selecting a completed classified run restores its immutable snapshot with lexical findings', async () => {
    const snapshotOpened: OpenedExtractionReview = {
      ...opened,
      classification: {
        job_id: 'job-1',
        review_revision_id: 'rev-doc-1',
        status: 'completed',
        progress: { total_pages: 2, completed_pages: 2, current_page_number: null },
        created_at: '2026-10-01T00:00:00+00:00',
        updated_at: '2026-10-01T00:00:00+00:00',
        finished_at: '2026-10-01T00:00:00+00:00',
        terminal_reason: null,
        source: 'job_snapshot',
        pages: [{
          page_number: 1,
          kind: 'completed',
          requires_review: false,
          is_provisional: false,
          applied_other_unclassified: false,
          labels: [{
            label: 'BILL_OF_MATERIALS',
            quote: 'water',
            reason: 'material page',
            element_id: 'n1',
            evidence_verification: 'verified',
            evidence_verification_reason: null,
            provenance: 'call',
          }],
          evidence: [],
          source_validation: { has_unverified: false, requires_review: false, items: [] },
          eligibility: {
            eligible_for_extraction: true,
            reason: 'page remains eligible for lexical extraction',
            excluded_by_policy: false,
          },
        }, {
          page_number: 2,
          kind: 'completed',
          requires_review: false,
          is_provisional: false,
          applied_other_unclassified: false,
          labels: [],
          evidence: [],
          source_validation: { has_unverified: false, requires_review: false, items: [] },
          eligibility: {
            eligible_for_extraction: true,
            reason: 'page remains eligible for lexical extraction',
            excluded_by_policy: false,
          },
        }],
      },
    }

    installFetch(async (url, method) => {
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
      if (url.includes('/classification') && method === 'GET') {
        return json({ classification: null })
      }
      const pageMatch = url.match(/\/pages\/(\d+)$/)
      if (pageMatch) return json({ page_number: Number(pageMatch[1]), html: pageHtml[Number(pageMatch[1])] })
      if (url.includes(`/jobs/${JOB_ID}`) && method === 'GET') return json(snapshotOpened)
      return null
    }, { documents: [{ job_id: 'job-1', review_revision_id: 'rev-doc-1' }] })

    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(ExtractionReviewWorkspace, { options: {} })
    app.mount(host)
    mounts.push({ unmount: () => { app.unmount(); host.remove() } })
    await flush()

    const runSelect = host.querySelector('[aria-label="Extraction run"]')
    if (!(runSelect instanceof HTMLSelectElement)) throw new Error('missing run selector')
    runSelect.value = JOB_ID
    runSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => host.textContent?.includes('BILL_OF_MATERIALS') === true, 'snapshot label')
    expect(host.textContent).toContain('classification snapshot')
    expect(host.textContent).toContain('water')
    expect(host.textContent).toContain('BILL_OF_MATERIALS')
  })

  it('hides Download classifications TXT when no classification is loaded', async () => {
    installFetch(async (url, method) => {
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
      if (url.includes(`/jobs/${JOB_ID}`) && method === 'GET') return json(opened)
      return null
    })

    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(ExtractionReviewWorkspace, { options: {} })
    app.mount(host)
    mounts.push({ unmount: () => { app.unmount(); host.remove() } })
    await flush()

    expect([...host.querySelectorAll('button')].some((item) => item.textContent?.includes('Download classifications TXT'))).toBe(false)
    expect(buttonNamed(host, 'Download TXT').disabled).toBe(true)

    const runSelect = host.querySelector('[aria-label="Extraction run"]')
    if (!(runSelect instanceof HTMLSelectElement)) throw new Error('missing run selector')
    runSelect.value = JOB_ID
    runSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => buttonNamed(host, 'Download TXT').disabled === false, 'stage3 download enabled')
    expect([...host.querySelectorAll('button')].some((item) => item.textContent?.includes('Download classifications TXT'))).toBe(false)
    expect(buttonNamed(host, 'Download TXT').disabled).toBe(false)
  })

  it('exports current classification before extraction and job snapshot after open without mutation routes', async () => {
    const mutationUrls: string[] = []
    const currentPages: PageClassificationView[] = [
      pageView(1, {
        kind: 'completed',
        labels: [{ label: 'COVER_PAGE', quote: 'cover', reason: 'cover', element_id: 'c1', evidence_verification: 'verified', evidence_verification_reason: null }],
      }),
      pageView(2, {
        kind: 'incomplete',
        requires_review: true,
        is_provisional: true,
        labels: [
          { label: 'MANUFACTURING_INSTRUCTIONS', quote: 'a', reason: 'r', element_id: 'n1', evidence_verification: 'verified', evidence_verification_reason: null },
          { label: 'PROCESS_EXECUTION_RECORD', quote: 'b', reason: 'r', element_id: 'n2', evidence_verification: 'unverified', evidence_verification_reason: 'missing' },
        ],
        source_validation: { has_unverified: true, requires_review: true, items: [] },
      }),
    ]
    const snapshotPages: PageClassificationView[] = [
      pageView(1, {
        kind: 'completed',
        labels: [{ label: 'BILL_OF_MATERIALS', quote: 'bom', reason: 'materials', element_id: 'b1', evidence_verification: 'verified', evidence_verification_reason: null }],
      }),
      pageView(2, {
        kind: 'completed',
        labels: [{ label: 'PROCESS_EXECUTION', quote: 'step', reason: 'exec', element_id: 'p2', evidence_verification: 'verified', evidence_verification_reason: null }],
      }),
    ]
    const currentState: ClassificationStateView = {
      job_id: 'job-1',
      review_revision_id: 'rev-doc-1',
      status: 'completed',
      progress: { total_pages: 2, completed_pages: 2, current_page_number: null },
      created_at: '2026-10-01T00:00:00+00:00',
      updated_at: '2026-10-01T00:00:00+00:00',
      finished_at: '2026-10-01T00:00:00+00:00',
      terminal_reason: null,
      source: 'current',
      pages: currentPages,
    }
    const snapshotOpened: OpenedExtractionReview = {
      ...opened,
      classification: {
        ...currentState,
        source: 'job_snapshot',
        pages: snapshotPages,
      },
    }

    const downloads: Array<{ filename: string; body: string }> = []
    let pendingBody: string | null = null
    const OriginalBlob = Blob
    vi.stubGlobal(
      'Blob',
      class MockBlob extends OriginalBlob {
        constructor(parts?: BlobPart[], options?: ConstructorParameters<typeof Blob>[1]) {
          super(parts, options)
          pendingBody = (parts ?? []).map((part) => String(part)).join('')
        }
      },
    )
    const createObjectURL = vi.fn(() => `blob:test-${downloads.length + 1}`)
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })

    const originalClick = HTMLAnchorElement.prototype.click
    HTMLAnchorElement.prototype.click = function click(this: HTMLAnchorElement) {
      if (this.download && pendingBody != null) {
        downloads.push({ filename: this.download, body: pendingBody })
        pendingBody = null
      }
      return originalClick.call(this)
    }

    installFetch(async (url, method) => {
      if (method !== 'GET') {
        mutationUrls.push(`${method} ${url}`)
      }
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
      if (url.includes('/approved-documents/') && url.endsWith('/pages') && method === 'GET') {
        return json({ job_id: 'job-1', review_revision_id: 'rev-doc-1', pages: [1, 2] })
      }
      if (url.includes('/approved-documents/') && url.includes('/pages/') && method === 'GET') {
        return json({ page_number: 1, html: pageHtml[1] })
      }
      if (url.includes('/classification') && method === 'GET' && !url.includes('/jobs/')) {
        return json({ classification: currentState })
      }
      const pageMatch = url.match(/\/jobs\/[^/]+\/pages\/(\d+)$/)
      if (pageMatch) return json({ page_number: Number(pageMatch[1]), html: pageHtml[Number(pageMatch[1])] })
      if (url.includes(`/jobs/${JOB_ID}`) && method === 'GET') return json(snapshotOpened)
      return null
    }, { documents: [{ job_id: 'job-1', review_revision_id: 'rev-doc-1' }] })

    const host = document.createElement('div')
    document.body.append(host)
    const app = createApp(ExtractionReviewWorkspace, { options: {} })
    app.mount(host)
    mounts.push({
      unmount: () => {
        HTMLAnchorElement.prototype.click = originalClick
        app.unmount()
        host.remove()
      },
    })
    await flush()

    const docSelect = host.querySelector('[aria-label="Approved document"]')
    if (!(docSelect instanceof HTMLSelectElement)) throw new Error('missing document selector')
    docSelect.value = 'job-1::rev-doc-1'
    docSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => buttonNamed(host, 'Download classifications TXT').disabled === false, 'classifications download')

    buttonNamed(host, 'Download classifications TXT').click()
    await flush()
    await waitFor(() => downloads.length >= 1, 'current download')
    expect(downloads[0].filename).toContain('page-classifications-current-')
    expect(downloads[0].body).toBe(
      [
        'Page number\tPage classification',
        '1\tCOVER_PAGE',
        '2\tMANUFACTURING_INSTRUCTIONS; PROCESS_EXECUTION_RECORD [incomplete; needs_review; provisional; unverified_evidence]',
        '',
      ].join('\n'),
    )

    const runSelect = host.querySelector('[aria-label="Extraction run"]')
    if (!(runSelect instanceof HTMLSelectElement)) throw new Error('missing run selector')
    runSelect.value = JOB_ID
    runSelect.dispatchEvent(new Event('change'))
    await flush()
    await waitFor(() => host.textContent?.includes('BILL_OF_MATERIALS') === true, 'snapshot open')

    buttonNamed(host, 'Download classifications TXT').click()
    await flush()
    await waitFor(() => downloads.length >= 2, 'snapshot download')
    expect(downloads[1].filename).toContain('page-classifications-job-snapshot-')
    expect(downloads[1].body).toBe(
      [
        'Page number\tPage classification',
        '1\tBILL_OF_MATERIALS',
        '2\tPROCESS_EXECUTION',
        '',
      ].join('\n'),
    )
    expect(downloads[1].body).not.toContain('COVER_PAGE')
    expect(mutationUrls).toEqual([])
    expect(buttonNamed(host, 'Download TXT').disabled).toBe(false)
  })
})

describe('page classification TXT helpers', () => {
  it('builds UTF-8 TSV with locked label order, markers, and missing-page fallback', () => {
    const classification: ClassificationStateView = {
      job_id: 'job-1',
      review_revision_id: 'rev-1',
      status: 'completed',
      progress: { total_pages: 3, completed_pages: 2, current_page_number: null },
      created_at: '2026-10-01T00:00:00+00:00',
      updated_at: '2026-10-01T00:00:00+00:00',
      finished_at: '2026-10-01T00:00:00+00:00',
      terminal_reason: null,
      source: 'current',
      pages: [
        pageView(1, {
          kind: 'completed',
          labels: [
            { label: 'BILL_OF_MATERIALS', quote: null, reason: null, element_id: null, evidence_verification: null, evidence_verification_reason: null },
            { label: 'EQUIPMENT_LIST', quote: null, reason: null, element_id: null, evidence_verification: null, evidence_verification_reason: null },
          ],
        }),
        pageView(2, {
          kind: 'incomplete',
          requires_review: true,
          labels: [
            { label: 'MANUFACTURING_INSTRUCTIONS', quote: null, reason: null, element_id: null, evidence_verification: null, evidence_verification_reason: null },
            { label: 'PROCESS_EXECUTION_RECORD', quote: null, reason: null, element_id: null, evidence_verification: null, evidence_verification_reason: null },
          ],
        }),
      ],
    }
    const text = buildPageClassificationsTsv([1, 2, 3], classification)
    expect(text).toBe(
      [
        'Page number\tPage classification',
        '1\tBILL_OF_MATERIALS; EQUIPMENT_LIST',
        '2\tMANUFACTURING_INSTRUCTIONS; PROCESS_EXECUTION_RECORD [incomplete; needs_review]',
        '3\t[no completed classification result]',
        '',
      ].join('\n'),
    )
    expect(formatPageClassificationColumn(pageView(1, {
      kind: 'completed',
      applied_other_unclassified: true,
      labels: [],
    }))).toBe('OTHER_UNCLASSIFIED')
    expect(pageClassificationsDownloadFilename({
      source: 'current',
      jobId: 'job/1',
      reviewRevisionId: 'rev 1',
    })).toBe('page-classifications-current-job_1-rev_1.txt')
    expect(pageClassificationsDownloadFilename({
      source: 'job_snapshot',
      jobId: 'job-1',
      reviewRevisionId: 'rev-1',
      localJobId: JOB_ID,
    })).toBe(`page-classifications-job-snapshot-${JOB_ID}.txt`)
  })
})

function pageView(
  pageNumber: number,
  overrides: Partial<PageClassificationView> & {
    labels?: PageClassificationView['labels']
    source_validation?: PageClassificationView['source_validation']
  } = {},
): PageClassificationView {
  return {
    page_number: pageNumber,
    kind: overrides.kind ?? 'completed',
    requires_review: overrides.requires_review ?? false,
    is_provisional: overrides.is_provisional ?? false,
    applied_other_unclassified: overrides.applied_other_unclassified ?? false,
    labels: overrides.labels ?? [],
    evidence: overrides.evidence ?? [],
    source_validation: overrides.source_validation ?? {
      has_unverified: false,
      requires_review: false,
      items: [],
    },
    eligibility: overrides.eligibility ?? {
      eligible_for_extraction: true,
      reason: 'page remains eligible for lexical extraction',
      excluded_by_policy: false,
    },
  }
}

function json(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stage4Bootstrap(url: string, method: string): Response | null {
  if (url.includes('/classification') && method === 'GET') {
    return json({ classification: null })
  }
  return null
}

function installFetch(
  handler: (
    url: string,
    method: string,
    init?: RequestInit,
  ) => Response | Promise<Response | null> | null,
  options?: { documents?: Array<{ job_id: string; review_revision_id: string }> },
) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.endsWith('/approved-documents') && method === 'GET') {
      return json({ documents: options?.documents ?? [] })
    }
    const handled = await handler(url, method, init)
    if (handled) return handled
    const bootstrapped = stage4Bootstrap(url, method)
    if (bootstrapped) return bootstrapped
    return json({ jobs: [] })
  }))
}
