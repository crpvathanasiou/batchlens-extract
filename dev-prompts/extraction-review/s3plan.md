**Τελικό διορθωμένο Understanding Report — Gate A**

Διάβασα και τα τέσσερα orientation documents. Τα χρησιμοποιώ συμπληρωματικά προς τον κώδικα, τα tests και τα authoritative handoffs. Οι παρακάτω διατυπώσεις αντικαθιστούν τις προηγούμενες ως προς το approval scope και το `auto_approved`.

**1. Άμεσος στόχος και όρια**

Το **Extraction Review Workspace** θα επιτρέπει επιλογή εγκεκριμένου reviewed HTML, εκτέλεση lexical extraction, επιθεώρηση evidence, προσθήκη/αλλαγή/αφαίρεση findings και εγκρίσεις **μόνο ανά σελίδα ή stage**.

Ο αποδεκτός lexical engine L01–L13 παραμένει η βάση. LLM extraction, associations, graph, πλήρης αυτοματισμός από PDF και production orchestration δεν υλοποιούνται σε αυτό το mini-project.

**2. Τι υπάρχει σήμερα**

| Περιοχή | Κατάσταση και βάση τεκμηρίωσης |
|---|---|
| Document review, immutable revisions, page/document approvals, exports και history projection | **implemented**, από επιθεώρηση κώδικα. Υπάρχουν καταγεγραμμένα automated και manual αποτελέσματα για συγκεκριμένες συμπεριφορές. |
| Lexical L01–L13, callable runner, CLI και publication | **implemented**, από επιθεώρηση κώδικα· **test-verified**, βάσει προηγούμενων καταγεγραμμένων gates· **user-accepted**, σύμφωνα με το handoff. |
| Extraction Review Workspace, extraction-review revisions/approvals, folder registry και τοπικά background jobs | **unimplemented**. |

Ο υφιστάμενος lexical runner εκτελείται ως τοπική συνάρτηση ή foreground CLI process. Δεν διαθέτει background queue ή resume service.

**3. Το ακριβές όριο Stage 1 → Stage 2**

Το Stage 1 παράγει reviewed HTML και downloadable approved JSON μέσω του `Approve & Export`. **Μόνο το reviewed HTML είναι document input του Stage 2**· όχι PDF, original conversion HTML, review JSON ή `history.jsonl`.

Τα πρόσθετα έγγραφα αποσαφηνίζουν επίσης έναν υπάρχοντα τοπικό περιορισμό: το standalone offline conversion και το review harness είναι χωριστές διαδρομές. Το νέο `document.json` του offline CLI δεν συμπληρώνει τα source metadata που απαιτεί το harness. Επομένως, η επιτυχής review διαδικασία ενός ήδη συμβατού συνόλου αρχείων δεν αποδεικνύει αυτόματη συνέχεια από οποιοδήποτε νέο offline conversion. Η διόρθωση αυτής της σύνδεσης παραμένει εκτός του παρόντος scope.

Ο lexical engine ελέγχει HTML v1, producer metadata και τα bytes που διάβασε. **Δεν ελέγχει από μόνος του ότι υπάρχει τρέχουσα ανθρώπινη έγκριση.** Στο νέο workspace, η ένταξη στον ελεγχόμενο `approved-documents/` αποτελεί τον συμφωνημένο κανόνα επιλεξιμότητας, χωρίς δεύτερη approval gate.

**4. Provenance και immutable αποτελέσματα**

Το reviewed HTML συνδέεται με το lexical manifest μέσω του **HTML-byte SHA-256** και των `job_id`, `review_revision_id`, `review_generation`, `conversion_status`.

Το supplied approved JSON έχει matching revision provenance, αλλά `exports: null`. Αυτό είναι συμβατό με τον τρόπο παραγωγής του downloadable JSON: δημιουργείται πριν προστεθούν τα export pointers στο τελικό persisted `review.json`. Συνεπώς, **το supplied JSON δεν αποδεικνύει ανεξάρτητα export-pointer σύνδεση προς τα συγκεκριμένα HTML bytes**.

Παραμένουν διαφορετικά:

- `document_hash`: hash του canonical reviewed Document JSON.
- HTML SHA-256: hash των ακριβών HTML bytes, μετά την ολοκλήρωση της ανάγνωσης.
- Artifact hashes: hashes των επιμέρους lexical component files.

Το L13 γράφει ένα artifact ανά completed component και το final manifest τελευταίο. **Completed publication δεν σημαίνει completed extraction ή ανθρώπινη έγκριση**: μπορεί να δημοσιευθεί partial extraction ή, όταν πληρούνται οι προϋποθέσεις publication, manifest με failed extraction. Αρχεία που απέμειναν χωρίς final manifest δεν αποτελούν ολοκληρωμένο published run.

Οι ανθρώπινες αλλαγές αποθηκεύονται σε ξεχωριστά immutable extraction-review revisions, με source references και parent revision. Raw artifacts και manifest δεν μεταβάλλονται. Κάθε rerun δημιουργεί νέο immutable run.

**5. Findings και αποκλειστικά page/stage approvals**

Τα findings διατηρούν source/origin/edit metadata, όπως `lexical`, `added_by_user`, `changed_by_user`, `removed_by_user`, actor, timestamp, revision και evidence state.

**Δεν υπάρχουν individual finding approval/rejection actions, per-finding approval lifecycle ή κατάσταση `confirmed`.** Η αφαίρεση ενός finding είναι καταγεγραμμένη επεξεργασία.

Ο χρήστης μπορεί να προσθέσει finding χωρίς document evidence, με `no_document_evidence`. Αυτό παραμένει επεξεργάσιμο και περιλαμβάνεται στο κατάλληλο review scope, χωρίς επινοημένο page/node/span ή απαίτηση ατομικής έγκρισης.

| Κατάσταση review scope | Σημασία |
|---|---|
| `waiting_for_approval` | Η τρέχουσα σελίδα ή stage revision αναμένει ανθρώπινη έγκριση. |
| `human_approved` | Άνθρωπος ενέκρινε το συγκεκριμένο page/stage scope στο συγκεκριμένο revision. |
| `auto_approved` | Αποκλειστικά επιτυχής ολοκλήρωση stage στο **ρητά επιλεγμένο μελλοντικό full automated workflow**. |

Μια αλλαγή δημιουργεί νέο review revision και κάνει την επηρεαζόμενη τρέχουσα σελίδα `waiting_for_approval`. Οι παλιές εγκρίσεις διατηρούνται ιστορικά και δεν εγκρίνουν αυτομάτως το μεταβλημένο scope.

Το **Stage approval δεν απαιτεί προηγούμενα Page approvals**. Ο σημερινός κανόνας του Stage 1 `Approve & Export`, που απαιτεί εγκρίσεις όλων των σελίδων, παραμένει διαφορετικός και δεν μεταφέρεται αυτούσιος.

**6. Κανονικές lexical ενέργειες και UI**

| UI action | Preset | Review scope μετά από επιτυχή ολοκλήρωση |
|---|---|---|
| `Extract UOs` | `unit_operations_with_steps` | `waiting_for_approval` |
| `Extract Materials` | `materials_with_quantities` | `waiting_for_approval` |
| `Extract Equipment` | `equipment_with_parameters` | `waiting_for_approval` |
| `Extract All` | `full` | `waiting_for_approval` |

**Το `Extract All` εκτελεί όλα τα lexical components· δεν είναι το μελλοντικό full automated workflow και δεν δίνει `auto_approved`.**

Το fuzzy είναι προαιρετικό και αρχικά απενεργοποιημένο. Τα “with” σημαίνουν συνεκτέλεση χωρίς associations.

Αριστερά εμφανίζεται η εγκεκριμένη HTML σελίδα, δεξιά τα findings. Οι προβολές **By page** και **By finding** χρησιμοποιούν το ίδιο current review revision. Η πλοήγηση περιλαμβάνει dots, dropdown και arrows· το occurrence click εντοπίζει ακριβές page/node/span.

Τα highlights χρησιμοποιούν διαφανή category colors από backend-configurable tokens, label και μη χρωματική ένδειξη. Μελλοντικές πολλαπλές πηγές στο ίδιο span θα μοιράζονται ένα highlight με χωριστά source records. Candidates, overlaps και ambiguity διατηρούνται.

**7. Τοπική λειτουργία και όρια δεδομένων**

Το `approved-documents/<job_id>/<review_revision_id>/` περιέχει HTML και προαιρετικό supporting JSON/history. Το `.local-extraction-review-data/` περιέχει registry, jobs, raw runs, review revisions και history.

Και οι δύο φάκελοι χρειάζονται Git-ignore. Το knowledge snapshot παραμένει read-only και τα outputs βρίσκονται εκτός αυτού.

Τα νέα background jobs χρειάζονται persisted `queued/running/completed/failed` και progress που επιβιώνει από UI reload. Processing status, publication status και page/stage approval status παραμένουν χωριστά. Δεν έχει επιλεγεί ακόμη συγκεκριμένος μηχανισμός background execution.

**8. Evidence, εκκρεμότητες και ολοκλήρωση κατανόησης**

Από τους προηγούμενους άμεσους ελέγχους των συνημμένων επιβεβαιώθηκαν **18 σελίδες, 728 blocks, οκτώ artifact hashes/μεγέθη και 1.172 evidence spans**. Δεν επανέτρεξα extraction ή test suite. Το `tests.zip` έχει παραδοθεί, αλλά δεν έχει ακόμη επιθεωρηθεί.

Τα `monitor` / `to` matches δείχνουν γιατί χρειάζεται ανθρώπινο review· δεν εξουσιοδοτούν νέο semantic-confirmation model ή αλλαγή του matcher.

Η μετατροπή code-point offsets σε browser text/DOM positions παραμένει συγκεκριμένος κίνδυνος προς μελλοντικό σχεδιασμό και testing, χωρίς redesign του L13. Παρωχημένα project-document status statements θα συμφιλιωθούν σε εγκεκριμένη εργασία. Το `manifests-files.zip` δεν απαιτείται.

**Η κατανόηση είναι επαρκής για Gate B, μετά τη ρητή αποδοχή σου. Δεν έχει παραχθεί πλάνο υλοποίησης, Cursor prompt ή αλλαγή κώδικα.**