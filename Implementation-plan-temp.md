**Stage 3 — Extraction Review Workspace**  
**Αναθεωρημένο Gate B — Πλάνο υλοποίησης**

Το Stage 3 έχει πλέον μία μόνο ενέργεια έγκρισης: **`Approve extraction result`**, για ολόκληρο το αποθηκευμένο extraction-review αποτέλεσμα που παρουσιάζεται στον χρήστη.

Αφαιρούνται από το προτεινόμενο έργο τα page/stage/component/finding approvals, το `auto_approved`, οι approval dependencies και οι κανόνες διατήρησης εγκρίσεων ανά σελίδα. Παραμένουν immutable revisions, provenance, conflict handling και ιστορικό. **Το Stage 1 approval και ο Stage 2 engine παραμένουν αμετάβλητα.**

Διατηρούνται οκτώ εργασίες, επειδή ο διαχωρισμός contracts, persistence, integration, API και UI εξακολουθεί να είναι χρήσιμος. Το περιεχόμενό τους μειώνεται σύμφωνα με το νέο scope.

**Κοινό λειτουργικό συμβόλαιο**

| Περιοχή | Συμπεριφορά |
|---|---|
| Τρέχουσα ανθρώπινη έγκριση | Μόνο `not_approved` / `approved`. |
| Αντικείμενο έγκρισης | Ολόκληρο το ακριβές saved extraction-review revision, μαζί με unassigned findings και source/run references. |
| Partial execution | Επιτρέπεται έγκριση χωρίς εκτέλεση όλων των κατηγοριών. |
| Published partial result | Επιτρέπονται edits και τελική έγκριση, με εμφανή failed/missing coverage. |
| Unsaved edits | Διακριτό `Unsaved`. Η έγκριση απενεργοποιείται μέχρι να ολοκληρωθεί Save· δεν πραγματοποιείται σιωπηρό autosave. |
| Edit μετά την έγκριση | Το επόμενο committed περιεχόμενο αποτελεί νέο, `not_approved` revision. Η προηγούμενη έγκριση παραμένει ιστορική. |
| Save χωρίς αλλαγή περιεχομένου | Δεν δημιουργεί άσκοπα νέο content revision και δεν ακυρώνει έγκριση. |
| Navigation / αλλαγή view | Δεν αλλάζει revision ή approval. |
| Νέα extraction εκτέλεση | Νέο run και νέο unapproved review. Χωρίς αυτόματη συγχώνευση ή μεταφορά edits. |
| Removal | Καταγεγραμμένη αλλαγή `removed_by_user`, χωρίς rejection workflow. |
| No-evidence finding | Επιτρέπεται με `no_document_evidence`. Χωρίς page assignment εμφανίζεται στο `Unassigned` και περιλαμβάνεται στην τελική έγκριση. |

**Processing, publication και ανθρώπινη έγκριση παραμένουν χωριστά**

| Διάσταση | Τι περιγράφει |
|---|---|
| Local job status | `queued`, `running`, `completed`, `failed`. |
| Stage 2 extraction outcome | Τα πραγματικά `completed`, `partial`, `failed` και component-level `not_requested`. |
| Stage 2 publication outcome | Αν ολοκληρώθηκε η δημοσίευση manifest και artifacts. |
| Result approval | Αν άνθρωπος ενέκρινε το συγκεκριμένο saved review revision. |

Το job μπορεί να ολοκληρωθεί με δημοσιευμένο **partial extraction**. Το UI πρέπει να το εμφανίζει ως τέτοιο, χωρίς γενικό πράσινο μήνυμα πλήρους επιτυχίας. Η ανθρώπινη έγκριση δεν μεταβάλλει κανένα execution/publication outcome.

**Συγκεκριμένος τοπικός μηχανισμός**

Προτείνεται ένας local server με **ένα background worker thread**, που καλεί συγχρονισμένα τον υπάρχοντα Stage 2 runner έξω από το HTTP request. Δεν εισάγεται εξωτερικός queue server.

Ένα process-held filesystem lock αποκλείει δεύτερο Stage 3 server στο ίδιο data directory. Η ουρά αποθηκεύεται τοπικά και εκτελεί ένα job κάθε φορά.

Για bounded queries και atomic updates προτείνεται μία μικρή, χωριστή **Stage 3 SQLite** στο `.local-extraction-review-data/registry/workspace.sqlite`, μέσω της standard library:

- Operational registry, jobs και current-head pointers.
- Ανακατασκευάσιμα indexes για findings, candidates, evidence locations και committed history.
- Immutable raw artifacts και review-revision αρχεία παραμένουν χωριστά.
- Καμία αλλαγή στη read-only knowledge SQLite.

Η χρήση αυτού του index εξυπηρετεί τα δύο views και το history χωρίς επαναλαμβανόμενη φόρτωση ολόκληρων artifacts ή revision chains. Δεν αποτελεί νέο knowledge model.

---

**U1 — Review contracts, persistence και μία τελική έγκριση**

**U1.1 — Contracts και κανόνες saved result**

**Παραδοτέο:** Stage 3 contracts για findings, edits, revisions, current head και ένα συγκεκριμένο `ExtractionResultApproval`. Δεν δημιουργείται approval-scope hierarchy.

**Input → output:** source/run references και edit ή final-approval command με `expected_revision` → έγκυρη revision transition ή συγκεκριμένο validation/conflict error.

Η έγκριση καταγράφει actor, server timestamp και το ακριβές saved revision που εγκρίθηκε. Η approval transition καταγράφεται στο immutable revision history χωρίς αλλαγή των findings. Τα υπάρχοντα source/run references διατηρούνται.

Τα findings κρατούν χωριστά:

- Original matched text, evidence και catalogue candidates.
- Τρέχουσα ανθρώπινη διόρθωση.
- `added_by_user`, `changed_by_user`, `removed_by_user`.
- Evidence state, συμπεριλαμβανομένου `no_document_evidence`.

**Εξάρτηση:** αποδοχή αυτού του Gate B.

**Αρχεία:**

- Νέα: `src/app/extraction_review/__init__.py`, `contracts.py`, `transitions.py`.
- Νέα tests: `tests/extraction_review/__init__.py`, `test_contracts.py`, `test_transitions.py`.
- Στοχευμένη ενημέρωση των σχετικών sections στα `AGENTS.md`, `.ai/00_project_reference.md`, `.ai/01_implementation_roadmap.md`, `.ai/03_common_handoff.md`, `.ai/04_code_map.md`, `.ai/05_pipeline_contracts.md`.

Οι ενημερώσεις καταγράφουν το αποδεκτό L13, το Stage 3 και την αντικατάσταση των προηγούμενων approval requirements. Δεν αλλάζουν τους Stage 1 κανόνες.

**Tests / acceptance:** final approval μετά από subset extraction, partial-result approval, unassigned findings, edit μετά από approval, no-op Save, stale revision, διατήρηση original evidence και απουσία intermediate approval fields/actions.

**Definition of Done:** οι κανόνες αποδεικνύονται με focused tests, χωρίς filesystem ή HTTP. Έχουν οριστεί finite request/batch limits για τις επόμενες εργασίες.

**U1.2 — Immutable revisions, current head και bounded history**

**Παραδοτέο:** τοπικό service και persistence με conflict detection και ασφαλές retry.

**Input → output:** Save ή `Approve extraction result` request → committed revision/approval transition και current state, ανακτήσιμα μετά από restart.

Τα revision files γράφονται πριν από την atomic δημοσίευση του head. Head και αντίστοιχα index updates γίνονται στην ίδια Stage 3 SQLite transaction. Uncommitted/orphan αρχεία δεν εμφανίζονται ως ιστορικό.

Τα revisions περιέχουν bounded change records και references, όχι επαναλαμβανόμενα αντίγραφα όλων των raw findings. Τα history queries χρησιμοποιούν keyset pagination πάνω στα committed revision metadata. Rebuild διαβάζει σταδιακά τις revisions, χωρίς συγκέντρωση ολόκληρης της αλυσίδας στη μνήμη.

**Εξάρτηση:** U1.1.

**Αρχεία:**

- Νέα: `src/app/extraction_review/storage.py`, `service.py`, `history.py`.
- Νέα tests: `tests/extraction_review/test_storage.py`, `test_service.py`, `test_history.py`.

**Tests / acceptance:**

- Restart με διατήρηση saved content και approval.
- Δύο ανταγωνιστικές saves: μία επιτυχία, μία σύγκρουση.
- Retry ίδιου operation χωρίς δεύτερο commit· διαφορετικό payload με ίδιο ID απορρίπτεται.
- Approval με stale revision απορρίπτεται.
- Failure πριν/μετά τη δημοσίευση του head και ανάκτηση αβέβαιου αποτελέσματος.
- Μεγάλο synthetic history διαβάζεται σε bounded batches.

**Definition of Done:** κανένα conflict ή retry δεν χάνει νεότερη εργασία. Η προηγούμενη approved revision παραμένει ανακτήσιμη μετά από μεταγενέστερο edit. Δεν εισάγονται Stage 1 storage contracts ή imports από `tests/` στον application κώδικα.

---

**U2 — Approved Documents και ανεξάρτητη Stage 2 execution**

**U2.1 — Document registry, run registration και evidence index**

**Παραδοτέο:** επιλογή eligible HTML και ασφαλής καταχώριση L13 results.

**Input → output:**

- Configured `approved-documents/` → entries με opaque document IDs και validated HTML identity.
- Published L13 run → verified run reference, bounded evidence index και νέο `not_approved` review όταν υπάρχουν completed component artifacts.

Επαναχρησιμοποιούνται τα υφιστάμενα HTML reader, manifest/hash verification και streaming component readers.

Η εισαγωγή διαβάζει ένα block κάθε φορά και γράφει μικρές transactional batches στο index. Candidates και supporting references προσπελαύνονται επίσης σε bounded responses. Δεν χρησιμοποιείται whole-artifact `json.loads`.

Το optional approved JSON είναι supporting provenance· `exports: null` δεν αντιμετωπίζεται ως σύνδεση προς συγκεκριμένα HTML bytes.

**Εξαρτήσεις:** U1.1–U1.2.

**Αρχεία:**

- Νέα: `src/app/extraction_review/configuration.py`, `registry.py`, `raw_runs.py`.
- Νέα tests: `tests/extraction_review/test_registry.py`, `test_raw_runs.py`.
- Ενημέρωση: `.gitignore` για `approved-documents/` και `.local-extraction-review-data/`.

**Tests / acceptance:** HTML χωρίς companion JSON, changed HTML hash, διαφορετικό revision, path/symlink escape, artifact tampering, missing manifest, zero-hit completed component, published partial result και repeated registration χωρίς διπλό review.

**Definition of Done:** το supplied bundle καταχωρίζεται χωρίς νέα extraction ή μεγάλη knowledge SQLite. Το evidence index ανακατασκευάζεται από immutable πηγές. Η διαδικασία δεν συγκεντρώνει ολόκληρο run στη μνήμη.

**U2.2 — Persisted jobs και συγκεκριμένος worker**

**Παραδοτέο:** local job queue και ένας worker thread που καλεί τον Stage 2.

**Input → output:** document ID, action και fuzzy flag → persisted job ID, truthful progress και τελικό run/result reference.

| Action | Stage 2 preset |
|---|---|
| `Extract UOs` | `unit_operations_with_steps` |
| `Extract Materials` | `materials_with_quantities` |
| `Extract Equipment` | `equipment_with_parameters` |
| `Extract All` | `full` |

Το Stage 3 χρησιμοποιεί τα υπάρχοντα configuration APIs, `run_lexical_extraction`, `FilesystemEvidenceSink` και `finalize_publication`. Progress καταγράφεται μέσω του υφιστάμενου sink interface, χωρίς αλλαγή του engine.

Καταγράφονται παρατηρήσιμα phases/component events και διαθέσιμα counts. Δεν εμφανίζεται επινοημένο ποσοστό ή ETA.

**Εξάρτηση:** U2.1.

**Αρχεία:**

- Νέα: `src/app/extraction_review/jobs.py`, `stage2_adapter.py`.
- Νέα tests: `tests/extraction_review/test_jobs.py`, `test_stage2_adapter.py`, `fixtures.py`.
- Στοχευμένες επεκτάσεις των Stage 3 storage/configuration modules.

**Restart / shutdown:**

- Ο server σταματά να αναλαμβάνει νέα jobs κατά το shutdown.
- Queued jobs παραμένουν αποθηκευμένα.
- Running job με έγκυρο published manifest συμφιλιώνεται με το πραγματικό αποτέλεσμα.
- Χωρίς ολοκληρωμένη publication καταγράφεται interrupted failure. Νέα προσπάθεια σημαίνει νέο job/run.
- Publication που ολοκληρώθηκε πριν διακοπεί η registration καταχωρίζεται χωρίς επανάληψη extraction.
- Το process lock απελευθερώνεται όταν κλείσει ο owning process.

**Tests / acceptance:** αποκλεισμός δεύτερου server/worker, τέσσερα mappings, fuzzy default, duplicate submission retry, responsiveness κατά την εκτέλεση, reload/restart, partial/failed/publication-failed outcomes και απουσία AWS calls.

**Definition of Done:** πραγματική synthetic extraction μέσω του αμετάβλητου Stage 2, με durable progress και νέο unapproved review. Stage 3 registration failure δεν αλλοιώνει τα αποθηκευμένα Stage 2 outcomes.

---

**U3 — Evidence views, editing και final approval UI**

**U3.1 — API και local application**

**Παραδοτέο:** thin Stage 3 API και ξεχωριστό localhost entry point.

**Input → output:** opaque IDs, pagination cursors και bounded mutation requests → typed projections, job responses, saved state ή safe errors.

Το API καλύπτει document selection, jobs, runs, current review, page/finding views, Save, μία final-approval action και history. **Δεν περιλαμβάνει page/component/stage/finding approval endpoints.**

Το submission επιστρέφει `202` μετά τη durable αποθήκευση του job. Actor/time παρέχονται από τον server.

**Εξαρτήσεις:** U1.2, U2.1–U2.2.

**Αρχεία:**

- Νέα: `src/app/api/extraction_reviews.py`.
- Νέα: `src/app/extraction_review/views.py`, `local_app.py`, `__main__.py`.
- Νέα tests: `tests/extraction_review/test_api.py`, `test_views.py`, `test_local_app.py`.

**Tests / acceptance:** bounded SQL queries και responses, stable pagination δεμένη με revision, stale revision conflicts, nonblocking job submission/polling, path restrictions και ασφαλής προβολή HTML χωρίς scripts/event handlers ή εξωτερικά requests.

**Definition of Done:** πλήρες HTTP flow μέσω synthetic inputs. Καμία pagination διαδρομή δεν φορτώνει προηγουμένως όλο το artifact/history. Το production wiring και το Stage 1 API παραμένουν αμετάβλητα.

**U3.2 — Read-only workspace και ακριβή highlights**

**Παραδοτέο:** document selection, extraction actions, progress και δύο synchronized evidence views.

**Input → output:** paginated API projections → HTML αριστερά και findings δεξιά.

Διατηρούνται `By page`, `By finding`, dots, dropdown και arrows. Τα dots δείχνουν navigation/active page μόνο. Δεν σημαίνουν visited-as-reviewed ή approved.

Το `By finding` διατηρεί catalogue identity και ambiguity· δεν συγχωνεύει διαφορετικές ουσίες λόγω ίδιου ονόματος. Το `Unassigned` είναι προσβάσιμο και δεν εξαφανίζεται από page filtering.

**Εξάρτηση:** U3.1.

**Αρχεία:**

- Νέα στο `frontend/src/extraction-review/`: `contracts.ts`, `api.ts`, `state.ts`, `highlights.ts`, `review.css`.
- Νέα components: `ExtractionReviewWorkspace.vue`, `ApprovedDocumentPicker.vue`, `ReviewedHtmlPane.vue`, `ExtractionFindingsPanel.vue`.
- Ενημέρωση: `frontend/src/index.ts` με πρόσθετο Stage 3 mount export.
- Νέα frontend tests για views, navigation και highlights.

Το υπάρχον Vue/Vite build επαναχρησιμοποιείται. Stage 1 components και mount function διατηρούνται.

**Tests / manual acceptance:**

- Code-point → DOM mapping για non-BMP χαρακτήρες, combining marks, entities, `<br>`, whitespace και table cells.
- Repeated/overlapping spans και πολλαπλά source records στο ίδιο highlight.
- Backend-configurable transparent colors, labels και non-color cues.
- Late responses άλλου run/revision δεν αντικαθιστούν την τρέχουσα προβολή.
- Πλοήγηση στο supplied 18-page sample και σωστό occurrence highlight.

**Definition of Done:** τα δύο views παρουσιάζουν το ίδιο revision, με ακριβές evidence navigation και χωρίς approval indicators ανά σελίδα.

**U3.3 — Editing, Save και `Approve extraction result`**

**Παραδοτέο:** πλήρης ανθρώπινη επεξεργασία και μία τελική έγκριση.

**Input → output:** explicit add/edit/remove ή final approval request → νέο committed state, current-result status και history.

Το UI εμφανίζει χωριστά:

- Saved / Unsaved / Save outcome unknown.
- Current-result `Not approved` / `Approved`.
- Requested/completed/failed/not-requested components.

Όταν υπάρχουν unsaved edits, το UI δηλώνει ότι η παλιά έγκριση αφορά την τελευταία saved revision και δεν παρουσιάζει το draft ως εγκεκριμένο. Το approval button παραμένει disabled μέχρι successful Save.

**Εξάρτηση:** U3.2.

**Αρχεία:**

- Ενημέρωση των Stage 3 contracts, API/state και workspace/findings components.
- Νέα: `FindingEditor.vue`, `ExtractionResultActions.vue`, `ReviewHistoryPanel.vue`.
- Νέα tests: `frontend/tests/extraction-review-editing.test.ts`, `extraction-review-state.test.ts`, `extraction-review-approval.test.ts`.

Δεν προβλέπεται `ReviewApprovalControls` με πολλαπλά scopes ούτε αλλαγή της Stage 1 pending-save state machine.

**Tests / acceptance:**

- Add/edit/remove, no-evidence και unassigned findings.
- Save → reload → restart.
- Approval subset/partial result με coverage ορατή.
- Απόπειρα approval με dirty draft ή αβέβαιη Save δεν υποβάλλεται.
- Edit μετά από approval → νέο unapproved saved revision.
- Navigation/view switching/no-op Save διατηρούν την έγκριση.
- Δύο tabs και lost-response retry χωρίς διπλό commit.
- Πρόσβαση στην παλιά approved revision και στα αρχικά evidence.

**Definition of Done:** ο χρήστης ολοκληρώνει όλη τη διαδρομή με ένα Save και ένα final approval control, χωρίς ενδιάμεσα approval steps ή mandatory page checklists.

---

**U4 — Ολοκληρωμένο local acceptance**

**U4.1 — End-to-end verification και Stage 3 runbook**

**Παραδοτέο:** πραγματικά επαληθευμένη local διαδρομή, automated integration checks και οδηγός λειτουργίας.

**Εξαρτήσεις:** όλα τα προηγούμενα.

**Αρχεία:**

- Νέο: `tests/extraction_review/test_local_workflow.py`.
- Νέο: `docs/BatchLens-Stage3-Detailed-Local-Guide-EN.md`.
- Στοχευμένες ενημερώσεις των owner sections στα `.ai/03`, `.ai/04`, `.ai/05`, `.ai/06`, `.ai/07`.
- Δεν ξαναδημιουργούνται τα υπάρχοντα Stage 1/Stage 2 documents.

**Input → output:** eligible HTML, read-only snapshot, isolated data directory και ελεύθερο port → νέο raw run, saved review, final approval και ιστορικές revisions που επιβιώνουν από restart.

**Manual acceptance flow**

1. **Επιλογή εγγράφου και `Extract Materials`, fuzzy off.**  
   Το job εκτελείται στο background. Reload διατηρεί την πρόσβαση στο progress.

2. **Έλεγχος partial selection.**  
   Materials/quantity/units εμφανίζονται με τα πραγματικά outcomes. Οι υπόλοιπες κατηγορίες παραμένουν `not_requested`. Το αποτέλεσμα είναι `Not approved`.

3. **Evidence inspection.**  
   `By page` και `By finding` εντοπίζουν το ίδιο evidence. Navigation δεν αποτελεί review ή approval.

4. **Μερική επεξεργασία.**  
   Αλλαγή ενός finding, αφαίρεση άλλου και προσθήκη ενός `no_document_evidence` χωρίς page assignment.

5. **Save, reload και restart.**  
   Οι αλλαγές και το `Unassigned` finding διατηρούνται. Τα source HTML και raw artifact hashes παραμένουν ίδια.

6. **`Approve extraction result`.**  
   Η έγκριση επιτρέπεται χωρίς εκτέλεση άλλων κατηγοριών ή έλεγχο κάθε σελίδας. Καταγράφονται actor/time/target revision. Τα component outcomes δεν αλλάζουν.

7. **Navigation και αλλαγή view.**  
   Η έγκριση παραμένει ενεργή.

8. **Edit μετά την έγκριση.**  
   Το draft φαίνεται unsaved. Με Save δημιουργείται νέο `Not approved` revision. Στο history παραμένει η προηγούμενη approved έκδοση.

9. **Νέο `Extract UOs`.**  
   Δημιουργείται νέο run/review, χωρίς accumulation των materials ή μεταφορά των edits. Το προηγούμενο run και η approved ιστορική revision παραμένουν διαθέσιμα.

10. **Published partial result με αποτυχία component.**  
    Σε ελεγχόμενο synthetic fixture, το διαθέσιμο αποτέλεσμα μπορεί να αποθηκευτεί και να εγκριθεί, ενώ το failed component και το `partial` παραμένουν εμφανή.

11. **Recovery και regression.**  
    Δύο tabs, αβέβαιη Save απάντηση, interrupted job/restart και αποκλεισμός δεύτερου server. Ξεχωριστός έλεγχος ότι το Stage 1 review συνεχίζει να λειτουργεί.

Μία νέα πραγματική `Extract All` εκτέλεση θα ελέγξει και τη συνολική Stage 2 integration. Το ιστορικό runtime δεν θεωρείται νέα verification evidence.

**Definition of Done:** καταγεγραμμένα automated αποτελέσματα και ανθρώπινη αποδοχή της πραγματικής local διαδρομής. Τα partial/failure tests χρησιμοποιούν synthetic inputs, χωρίς αλλοίωση πραγματικών εγγράφων ή knowledge snapshot.

**Κοινά quality gates**

Κάθε task περνά τα σχετικά focused tests και Ruff/Pyright ή frontend typecheck/tests/build. Πριν από το τελικό acceptance εκτελούνται οι σχετικές Stage 1/Stage 2 regressions. Τα μεγάλα fixtures ελέγχουν πραγματική bounded ανάγνωση και queries, όχι μόνο μικρό response size.

Το αναθεωρημένο πλάνο αφορά αποκλειστικά **επιλογή → extraction → inspection/edit → Save → μία τελική ανθρώπινη έγκριση**, με persistence και ιστορικό.

**Σταματώ εδώ για τη ρητή έγκριση του αναθεωρημένου Gate B. Δεν έχει γίνει υλοποίηση ή παραγωγή Cursor prompt.**