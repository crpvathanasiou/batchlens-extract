import { createApp, type App } from 'vue'
import ReviewWorkspace from './components/ReviewWorkspace.vue'
import type { ReviewWorkspaceOptions } from './contracts'
import './review.css'

const mounted = new WeakMap<Element, App>()

export function mountReviewWorkspace(
  target: Element | string,
  options: ReviewWorkspaceOptions,
): { unmount: () => void } {
  const element = typeof target === 'string' ? document.querySelector(target) : target
  if (!element) throw new Error('Review workspace mount target was not found.')
  unmountReviewWorkspace(element)
  const app = createApp(ReviewWorkspace, { options })
  app.mount(element)
  mounted.set(element, app)
  return { unmount: () => unmountReviewWorkspace(element) }
}

export function unmountReviewWorkspace(target: Element | string): void {
  const element = typeof target === 'string' ? document.querySelector(target) : target
  if (!element) return
  mounted.get(element)?.unmount()
  mounted.delete(element)
}

export type { ReviewWorkspaceOptions } from './contracts'
