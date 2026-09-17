# BatchLens review workspace

Embeddable Vue review UI for the source PDF, protected extracted content, and findings.

## Runtime and commands

- Required runtime: Node.js `>=22.12`
- Verified runtime: Node.js `22.12.0`
- Install: `npm install`
- Type-check: `npm run typecheck`
- Test: `npm test`
- Production build: `npm run build`

The production library build writes `review.js`, `review.css`, the local PDF.js worker, and
supporting assets to `../src/app/document_review/static`. Its public asset base is
`/documents/review-assets/`. To verify without touching application static files, use
`npm run build -- --outDir dist-verify`.

## Host integration

```ts
import { mountReviewWorkspace } from './review.js'

const workspace = mountReviewWorkspace('#review', {
  jobId: 'job-id',
  filename: 'batch-record.pdf',
  getAccessToken: () => session.accessToken,
  onAuthenticationRequired: () => signInWithoutReloadingThePage(),
  onDirtyChange: (dirty) => updateHostNavigationGuard(dirty),
  onBack: () => history.back(),
})

workspace.unmount()
```

The token is requested immediately before each API or PDF request and is never persisted by
the workspace. A `401` calls `onAuthenticationRequired`; unsaved editor state remains in
memory so the host can reauthenticate and retry.

The exact API root is `/api/v1/documents/jobs/{jobId}`. The workspace uses `GET /review`,
`PUT /review` with sparse node changes and separate finding decisions,
`POST /review/pages/{page}/approve`, `POST /review/approve`,
`GET /review/revisions/{revisionId}/exports/{html|json}`, and `GET /source`.
