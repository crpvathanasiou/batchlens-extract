<script setup lang="ts">
import {
  GlobalWorkerOptions,
  getDocument,
  type PDFDocumentLoadingTask,
  type PDFPageProxy,
  type PDFDocumentProxy,
  type RenderTask,
} from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url&no-inline'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ReviewApi } from '../api'

GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps<{
  api: ReviewApi
  page: number
  expectedPageCount: number
}>()
const emit = defineEmits<{ pageCount: [count: number]; mismatch: [message: string | null] }>()

const canvas = ref<HTMLCanvasElement>()
const viewportElement = ref<HTMLElement>()
const loading = ref(true)
const error = ref<string | null>(null)
const scale = ref(1)
let loadingTask: PDFDocumentLoadingTask | null = null
let pdf: PDFDocumentProxy | null = null
let activePdfPage: PDFPageProxy | null = null
let renderTask: RenderTask | null = null
let abortController: AbortController | null = null
let generation = 0

async function renderPage() {
  if (!pdf || !canvas.value) return
  const ownGeneration = ++generation
  const obsoleteTask = renderTask
  obsoleteTask?.cancel()
  try {
    await obsoleteTask?.promise
  } catch {
    // Cancellation is expected when navigation or zoom supersedes a render.
  }
  activePdfPage?.cleanup()
  const page = await pdf.getPage(props.page)
  if (ownGeneration !== generation) {
    page.cleanup()
    return
  }
  activePdfPage = page
  const viewport = page.getViewport({ scale: scale.value })
  const context = canvas.value.getContext('2d')
  if (!context) throw new Error('Canvas rendering is unavailable.')
  canvas.value.width = Math.floor(viewport.width)
  canvas.value.height = Math.floor(viewport.height)
  renderTask = page.render({
    canvas: canvas.value,
    canvasContext: context,
    viewport,
  })
  try {
    await renderTask.promise
  } catch (reason) {
    if (!(reason instanceof Error) || reason.name !== 'RenderingCancelledException') throw reason
  } finally {
    if (ownGeneration === generation) renderTask = null
  }
}

async function load() {
  loading.value = true
  error.value = null
  try {
    abortController = new AbortController()
    const response = await props.api.fetchSource(abortController.signal)
    loadingTask = getDocument({
      data: await response.arrayBuffer(),
      disableRange: true,
      disableStream: true,
      disableAutoFetch: true,
      withCredentials: false,
    })
    pdf = await loadingTask.promise
    emit('pageCount', pdf.numPages)
    emit(
      'mismatch',
      pdf.numPages === props.expectedPageCount
        ? null
        : `Source PDF has ${pdf.numPages} pages but review data expects ${props.expectedPageCount}.`,
    )
    await nextTick()
    await renderPage()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Unable to display the PDF.'
  } finally {
    loading.value = false
  }
}

watch(() => props.page, renderPage)
watch(scale, renderPage)

async function fitWidth() {
  if (!pdf || !viewportElement.value) return
  const page = await pdf.getPage(props.page)
  const viewport = page.getViewport({ scale: 1 })
  scale.value = Math.max(0.5, Math.min(2.5, (viewportElement.value.clientWidth - 36) / viewport.width))
  page.cleanup()
}

const resize = () => void fitWidth()
onMounted(() => window.addEventListener('resize', resize))

onBeforeUnmount(async () => {
  generation += 1
  abortController?.abort()
  renderTask?.cancel()
  activePdfPage?.cleanup()
  activePdfPage = null
  window.removeEventListener('resize', resize)
  if (loadingTask) await loadingTask.destroy()
  else if (pdf) await pdf.destroy()
  loadingTask = null
  pdf = null
})

void load()
</script>

<template>
  <section class="bl-pdf" aria-label="Source PDF">
    <div class="bl-pdf__toolbar">
      <button type="button" aria-label="Zoom out" @click="scale = Math.max(0.5, scale - 0.15)">−</button>
      <span>{{ Math.round(scale * 100) }}%</span>
      <button type="button" aria-label="Zoom in" @click="scale = Math.min(2.5, scale + 0.15)">+</button>
      <button type="button" @click="fitWidth">Fit width</button>
    </div>
    <div ref="viewportElement" class="bl-pdf__viewport">
      <p v-if="loading" class="bl-muted">Loading source…</p>
      <p v-else-if="error" class="bl-error" role="alert">{{ error }}</p>
      <canvas v-show="!loading && !error" ref="canvas" />
    </div>
  </section>
</template>
