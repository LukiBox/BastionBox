"""Lightweight internationalization — English default, Polish one click away.

Deliberately dependency-free: a nested dict of translations and a tiny ``t()``
lookup with ``{}`` formatting. No gettext toolchain, no .po compilation, no
network — appropriate for an air-gapped app where every added dependency is
attack surface. Adding a language is: add its key to :data:`TRANSLATIONS`.

Keys are dotted, namespaced by area (``nav.chat``, ``library.blurb``) so the
strings a screen needs are easy to find and translate as a group. A missing key
falls back to English, then to the raw key — the UI degrades to something
readable rather than crashing.

One shared translator (module-level :func:`t` / :func:`set_language`) drives
the whole UI; widgets re-read their strings when the language changes via each
window's ``retranslate()``.
"""
from __future__ import annotations

from typing import Any

__all__ = ["Translator", "AVAILABLE_LANGUAGES", "t", "set_language",
           "current_language"]

AVAILABLE_LANGUAGES = {"en": "English", "pl": "Polski"}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "app.tagline": "The AI that never phones home.",
        # navigation ---------------------------------------------------------
        "nav.chat": "Chat",
        "nav.workspaces": "Workspaces",
        "nav.models": "Models",
        "nav.knowledge": "Knowledge",
        "nav.security": "Security",
        "nav.audit": "Audit",
        "nav.settings": "Settings",
        # window chrome ------------------------------------------------------
        "titlebar.minimize": "Minimize",
        "titlebar.maximize": "Maximize",
        "titlebar.restore": "Restore",
        "titlebar.close": "Close",
        # page headings ------------------------------------------------------
        "page.workspaces": "WORKSPACES",
        "page.models": "MODELS",
        "page.knowledge": "KNOWLEDGE",
        "page.settings": "SETTINGS",
        # workspaces ----------------------------------------------------------
        "card.mounted": "Mounted Folders",
        "card.tiers": "Permission Tiers",
        "ws.none": ("No workspace mounted. Mount a folder to let the agent read "
                    "and edit inside it — and nowhere else. Every mount is "
                    "confined by the path jail; two workspaces never share "
                    "context."),
        "ws.mounted": ("MOUNTED: {path}\nPermission: {perm}. The agent is "
                       "confined here by the path jail and will show a diff "
                       "before any write."),
        "ws.mount_dialog": "Mount a workspace folder",
        "ws.mount_refused": "Mount refused",
        "ws.no_workspace_title": "No workspace",
        "ws.no_workspace_msg": "Mount a workspace first (Workspaces tab).",
        "btn.mount": "MOUNT WORKSPACE…",
        "perm.tooltip": "Click to cycle the permission tier for the next mount",
        "perm.read_only": "READ-ONLY",
        "perm.ask": "ASK PER WRITE",
        "perm.auto": "AUTO-APPROVE",
        "perm.read_only.desc": "The agent may read, never write or run commands.",
        "perm.ask.desc": "Default. Every write/edit shows a diff to approve.",
        "perm.auto.desc": "Session-scoped; a loud indicator stays visible.",
        # models ---------------------------------------------------------------
        "card.hardware": "Detected Hardware",
        "card.registry": "Model Registry",
        "card.ollama": "Local Ollama (optional)",
        "models.recommendation": "Recommendation: ",
        "models.registry_blurb": ("Import a GGUF from disk — SHA-256 verified "
                                  "against a hash you supply (supply-chain "
                                  "hygiene for air-gapped sites). Models arrive "
                                  "by sneakernet, never a download."),
        "btn.import": "IMPORT GGUF…",
        "models.import_dialog": "Select a GGUF model file",
        "models.gguf_filter": "GGUF models (*.gguf);;All files (*)",
        "models.hash_title": "Verify integrity (recommended)",
        "models.hash_prompt": ("Paste the expected SHA-256 for this model "
                               "(from the vendor, out-of-band). Leave blank to "
                               "record the file's first-seen hash instead."),
        "models.import_failed_title": "Import refused",
        "models.hash_mismatch": ("HASH MISMATCH — the file's SHA-256 does not "
                                 "match what you supplied. Do NOT load this "
                                 "model; it may be corrupted or tampered with."),
        "models.no_models": "No models imported yet.",
        "models.imported_ok": ("Imported {name} ({fam}, {quant}, {size} GB). "
                               "{verify}"),
        "models.registered_list": "Registered: {names}",
        "models.load_into_chat": "LOAD INTO CHAT",
        "models.load_after_import_title": "Load model now?",
        "models.load_after_import": ("{name} is registered. Load it into the "
                                     "chat now so replies come from it?"),
        "models.pick_title": "Load a model into the chat",
        "models.pick_prompt": "Registered model:",
        "models.loaded_ok": "“{name}” is loaded. Chat now answers from it.",
        "models.loading": ("Loading {name} — a large model can take several "
                           "minutes on first load. The app stays responsive; "
                           "you will be told when it is live."),
        "models.loading_btn": "LOADING…",
        "models.busy": ("A reply is still streaming — stop it or let it finish, "
                        "then load the model again."),
        "models.load_failed_title": "Could not load model",
        "models.llama_missing": ("Loading a GGUF directly needs the embedded "
                                 "llama.cpp runtime (llama-cpp-python), which is "
                                 "not installed in this build. Use “Local "
                                 "Ollama” below to run this model through a "
                                 "local Ollama server instead — still fully "
                                 "offline, loopback only."),
        "models.ollama_btn": "USE LOCAL OLLAMA…",
        "models.ollama_blurb": ("Already running Ollama on this machine? "
                                "Connect to it (loopback only, never a remote "
                                "host) and load one of its models into the "
                                "chat."),
        "models.ollama_none_title": "No local Ollama",
        "models.ollama_none": ("Could not reach a local Ollama server at "
                               "127.0.0.1:11434, or it has no models. Start "
                               "Ollama and pull a model, then try again."),
        "models.ollama_pick_title": "Load an Ollama model",
        "models.ollama_pick_prompt": "Local Ollama model:",
        # knowledge ------------------------------------------------------------
        "card.retrieval": "Local Retrieval",
        "card.search": "Search",
        "card.library": "Reference Library",
        "knowledge.blurb": ("Index the mounted workspace fully locally: "
                            "code-aware chunking by function/class, hybrid BM25 "
                            "+ vector search fused with RRF, and cited results "
                            "(file:line-range). Grounded — a miss says 'not "
                            "found', never invents."),
        "btn.build_index": "BUILD / REFRESH INDEX",
        "knowledge.no_index": "No index yet. Mount a workspace, then build.",
        "knowledge.indexed": ("Indexed {indexed} file(s), {chunks} chunks "
                              "(skipped {skipped}, removed {removed}). "
                              "Retrieval is live and cited."),
        "knowledge.search_placeholder": ("Search the indexed workspace "
                                         "(e.g. validate_token)…"),
        "knowledge.mount_first": "Mount and index a workspace first.",
        "knowledge.not_found": "Not found in the indexed workspace.",
        "library.blurb": ("Attach a big folder of datasheets, norms, and "
                          "archives as a READ-ONLY library. The agent can then "
                          "search_library by keywords and read the hits "
                          "(PDF/Word/Excel/text) — it can never write there."),
        "btn.attach_library": "ATTACH LIBRARY…",
        "btn.index_library": "INDEX LIBRARY TEXT",
        "library.index_tooltip": ("Optional: index the library's text files so "
                                  "search_library also matches file CONTENTS, "
                                  "not just names"),
        "library.attached": ("LIBRARY: {path}  (read-only)\nThe agent can "
                             "search it by keyword and read documents from it. "
                             "Index the text content below to enable content "
                             "search too."),
        "library.indexed": ("LIBRARY: {path}  (read-only)\nIndexed {indexed} "
                            "text file(s), {chunks} chunks — search_library now "
                            "matches contents as well as names. (PDF/Office "
                            "files are searched by name and read on demand.)"),
        "library.attach_dialog": "Attach a reference library (read-only)",
        "library.attach_refused": "Attach refused",
        # settings --------------------------------------------------------------
        "card.appearance": "Appearance & Language",
        "card.engine": "Engine",
        "card.security": "Security",
        "card.personas": "Assistant Personas",
        "card.about": "About",
        "settings.summary": ("Theme: {theme}   ·   Language: {language}   ·   "
                             "Reduced motion: {rm}"),
        "settings.engine_summary": ("Backend: {backend}   ·   context {ctx}   "
                                    "·   temp {temp}"),
        "settings.security_summary": ("Network guard: {ng}   ·   Encrypt at "
                                      "rest: {enc}   ·   Audit: {audit}   ·   "
                                      "Air-gap build: {ag}"),
        "btn.change_theme": "CHANGE THEME",
        "personas.blurb": ("Create your own system prompts — e.g. a "
                           "company-specific report style. Custom personas "
                           "appear in the Chat persona picker and always keep "
                           "the local-only safety footer."),
        "btn.new_persona": "NEW PERSONA…",
        "btn.edit_persona": "EDIT / DELETE…",
        "personas.none": "No custom personas yet.",
        "personas.custom": "Custom: ",
        "persona.dialog_title": "Custom persona",
        "persona.name_label": "Name (shown in the Chat persona picker)",
        "persona.prompt_label": "System prompt (how the assistant should behave)",
        "persona.prompt_placeholder": ("e.g. You write test reports for ACME "
                                       "Defense. Always structure: Purpose, "
                                       "Setup, Procedure, Results, Verdict…"),
        "persona.delete": "DELETE",
        "persona.none_title": "No custom personas",
        "persona.none_msg": "Create one with NEW PERSONA… first.",
        "persona.pick_title": "Edit persona",
        "persona.pick_label": "Custom persona:",
        "about.blurb": ("{app} v{version} — a fully local, air-gap-capable AI "
                        "workstation assistant. MIT licensed. Zero telemetry."),
        "about.credit": "Created by LukiBox — github.com/LukiBox",
        "btn.onboarding": "REPLAY ONBOARDING",
        "btn.tutorial": "DETAILED TUTORIAL",
        # chat -------------------------------------------------------------------
        "chat.secure_channel": "Secure Channel",
        "chat.placeholder": "Ask BastionBox… nothing leaves this machine.",
        "chat.send": "Send",
        "chat.stop": "Stop",
        "chat.new": "New",
        "chat.new_tooltip": "Start a fresh conversation",
        "chat.compact_tooltip": ("Compact — summarize older turns to free "
                                 "context"),
        "chat.history_tooltip": "History — reopen a saved conversation",
        "chat.persona_tooltip": "Persona — sets the assistant's tone and focus",
        "chat.greeting": ("Secure channel open. I run entirely on this machine "
                          "— no cloud, no telemetry, no network. Mount a "
                          "workspace to let me read and edit files with your "
                          "approval, or just ask me anything."),
        "chat.compact": "Compact context",
        "chat.thinking": "Reasoning…",
        "chat.empty_reply": ("(The model returned no text — it may have used its "
                             "whole token budget reasoning. Try again or raise "
                             "the token limit.)"),
        "chat.agent_reading": "⋯ step {step}: reading the context…",
        "chat.agent_writing": "⋯ step {step}: writing… ({chars} chars)",
        "chat.agent_question_title": "THE AGENT HAS A QUESTION",
        "chat.agent_question_hint": ("Answer to unblock the agent, or Skip to let "
                                     "it proceed on its best judgment."),
        "chat.agent_answer": "Answer",
        "chat.agent_skip": "Skip",
        "chat.model_loaded": ("Model “{name}” is now live. Replies come from it, "
                              "still fully on this machine."),
        "chat.model_loaded_generic": ("A local model is now live. Replies come "
                                      "from it, still fully on this machine."),
        "chat.context_is": "Context window: {n} tokens.",
        # security page ---------------------------------------------------------
        "sec.title": "SECURITY POSTURE",
        "sec.netguard": "Network Guard",
        "sec.blocked_label": "Outbound attempts blocked",
        "sec.netguard_note": ("In-process socket guard. Blocks every "
                              "non-loopback connection — sloppy dependencies "
                              "included. This counter reads 0 in normal "
                              "operation."),
        "sec.encryption": "Encryption at Rest",
        "sec.enc_sealed": ("Conversations, indexes, extracted text and settings "
                           "are sealed with AES-256-GCM; the key is derived "
                           "with Argon2id or a DPAPI machine key."),
        "sec.enc_unsealed": ("No key is loaded — the store is running UNSEALED. "
                             "Set a passphrase in Settings to encrypt data at "
                             "rest."),
        "sec.audit": "Audit Chain",
        "sec.verify_btn": "VERIFY CHAIN",
        "sec.audit_note": ("Append-only, hash-chained JSONL. Every tool call, "
                           "file path, diff, command, and approval is recorded. "
                           "Verify re-hashes the whole chain and flags any "
                           "altered or truncated entry."),
        "sec.panic": "Panic Controls",
        "sec.panic_pill": "USE WITH CARE",
        "sec.panic_note": ("Irreversible. Secure-delete removes a workspace's "
                           "entire footprint — chats, index, extracted text — "
                           "and rewrites the freed database pages. Lock now "
                           "wipes the key from memory until you re-unlock."),
        "sec.lock": "LOCK NOW",
        "sec.locked": "LOCKED",
        "sec.wipe": "SECURE-DELETE WORKSPACE",
        "sec.no_ws_msg": "Mount a workspace first; there is nothing to delete.",
        "sec.wipe_title": "Secure-delete workspace",
        "sec.wipe_confirm": ("Permanently delete ALL BastionBox data for:\n\n"
                             "{path}\n\nChats, index, and extracted text will "
                             "be unrecoverable. Continue?"),
        "sec.wipe_done_title": "Secure-delete complete",
        "sec.wipe_done": ("Removed {removed} conversation(s) and cleared the "
                          "index for this workspace. Freed database pages were "
                          "rewritten."),
        "sec.chain_valid": "Chain valid — {entries} entries, unbroken from genesis.",
        "sec.tamper_detected": "TAMPER DETECTED: {detail}",
        "sec.whitelisted": "Whitelisted: {eps}",
        "sec.eps_none": "none (air-gap)",
        "sec.airgap_suffix": "   ·   AIR-GAP BUILD",
        "sec.pill_armed": "ARMED",
        "sec.pill_down": "DOWN",
        "sec.pill_secure": "SECURE",
        "sec.pill_unsealed": "UNSEALED",
        "sec.pill_breach": "BREACH ATTEMPT",
        "sec.pill_locked": "LOCKED",
        "sec.pill_not_verified": "NOT VERIFIED",
        "sec.pill_valid": "VALID",
        "sec.pill_tampered": "TAMPERED",
        # legacy/status keys kept for compatibility --------------------------------
        "status.secure": "SECURE",
        "status.armed": "ARMED",
        "status.offline": "OFFLINE",
        "status.blocked": "BLOCKED",
        "security.netguard": "Network Guard",
        "security.blocked_count": "Outbound attempts blocked",
        "security.encryption": "Encryption at rest",
        "security.audit_chain": "Audit chain",
        "security.verify": "Verify chain",
        "security.verified_valid": "VALID — {count} entries",
        "security.verified_broken": "TAMPERED — entry {seq}",
        "agent.approve": "Approve",
        "agent.reject": "Reject",
        "agent.approve_all": "Auto-approve (session)",
        "agent.diff_preview": "Proposed change — review before it is written",
        "workspace.mount": "Mount workspace…",
        "workspace.read_only": "Read-only",
        "workspace.ask": "Ask per write",
        "workspace.auto": "Auto-approve writes",
        "model.import": "Import GGUF…",
        "model.verify_hash": "SHA-256 verified",
        "model.hash_mismatch": "HASH MISMATCH — do not load",
        "common.cancel": "Cancel",
        "common.confirm": "Confirm",
        "common.close": "Close",
    },
    "pl": {
        "app.tagline": "Sztuczna inteligencja, która nigdy nie dzwoni do domu.",
        # nawigacja ------------------------------------------------------------
        "nav.chat": "Czat",
        "nav.workspaces": "Przestrzenie",
        "nav.models": "Modele",
        "nav.knowledge": "Wiedza",
        "nav.security": "Bezpieczeństwo",
        "nav.audit": "Audyt",
        "nav.settings": "Ustawienia",
        # pasek okna ------------------------------------------------------------
        "titlebar.minimize": "Minimalizuj",
        "titlebar.maximize": "Maksymalizuj",
        "titlebar.restore": "Przywróć",
        "titlebar.close": "Zamknij",
        # nagłówki stron ---------------------------------------------------------
        "page.workspaces": "PRZESTRZENIE ROBOCZE",
        "page.models": "MODELE",
        "page.knowledge": "WIEDZA",
        "page.settings": "USTAWIENIA",
        # przestrzenie ------------------------------------------------------------
        "card.mounted": "Zamontowane foldery",
        "card.tiers": "Poziomy uprawnień",
        "ws.none": ("Brak zamontowanej przestrzeni roboczej. Zamontuj folder, "
                    "aby agent mógł czytać i edytować pliki w nim — i nigdzie "
                    "indziej. Każdy montaż jest ograniczony przez ścieżkowe "
                    "więzienie; dwie przestrzenie nigdy nie współdzielą "
                    "kontekstu."),
        "ws.mounted": ("ZAMONTOWANO: {path}\nUprawnienia: {perm}. Agent jest tu "
                       "ograniczony przez ścieżkowe więzienie i pokaże różnice "
                       "przed każdym zapisem."),
        "ws.mount_dialog": "Zamontuj folder przestrzeni roboczej",
        "ws.mount_refused": "Odmowa montażu",
        "ws.no_workspace_title": "Brak przestrzeni",
        "ws.no_workspace_msg": ("Najpierw zamontuj przestrzeń (zakładka "
                                "Przestrzenie)."),
        "btn.mount": "ZAMONTUJ PRZESTRZEŃ…",
        "perm.tooltip": ("Kliknij, aby przełączyć poziom uprawnień następnego "
                         "montażu"),
        "perm.read_only": "TYLKO ODCZYT",
        "perm.ask": "PYTAJ PRZY ZAPISIE",
        "perm.auto": "AUTO-ZATWIERDZANIE",
        "perm.read_only.desc": ("Agent może czytać — nigdy zapisywać ani "
                                "uruchamiać poleceń."),
        "perm.ask.desc": ("Domyślne. Każdy zapis/edycja pokazuje różnice do "
                          "zatwierdzenia."),
        "perm.auto.desc": ("Na czas sesji; wyraźny wskaźnik pozostaje "
                           "widoczny."),
        # modele -------------------------------------------------------------------
        "card.hardware": "Wykryty sprzęt",
        "card.registry": "Rejestr modeli",
        "card.ollama": "Lokalny Ollama (opcjonalnie)",
        "models.recommendation": "Rekomendacja: ",
        "models.registry_blurb": ("Importuj GGUF z dysku — SHA-256 weryfikowany "
                                  "względem skrótu, który podasz (higiena "
                                  "łańcucha dostaw dla instalacji odciętych od "
                                  "sieci). Modele przybywają na nośniku, nigdy "
                                  "przez pobieranie."),
        "btn.import": "IMPORTUJ GGUF…",
        "models.import_dialog": "Wybierz plik modelu GGUF",
        "models.gguf_filter": "Modele GGUF (*.gguf);;Wszystkie pliki (*)",
        "models.hash_title": "Zweryfikuj integralność (zalecane)",
        "models.hash_prompt": ("Wklej oczekiwany SHA-256 dla tego modelu (od "
                               "dostawcy, poza pasmem). Pozostaw puste, aby "
                               "zapisać skrót pliku przy pierwszym widzeniu."),
        "models.import_failed_title": "Odmowa importu",
        "models.hash_mismatch": ("NIEZGODNOŚĆ SKRÓTU — SHA-256 pliku nie "
                                 "odpowiada podanemu. NIE ładuj tego modelu; "
                                 "może być uszkodzony lub zmanipulowany."),
        "models.no_models": "Nie zaimportowano jeszcze modeli.",
        "models.imported_ok": ("Zaimportowano {name} ({fam}, {quant}, {size} "
                               "GB). {verify}"),
        "models.registered_list": "Zarejestrowane: {names}",
        "models.load_into_chat": "ZAŁADUJ DO CZATU",
        "models.load_after_import_title": "Załadować model teraz?",
        "models.load_after_import": ("{name} został zarejestrowany. Załadować "
                                     "go teraz do czatu, aby odpowiedzi "
                                     "pochodziły od niego?"),
        "models.pick_title": "Załaduj model do czatu",
        "models.pick_prompt": "Zarejestrowany model:",
        "models.loaded_ok": ("„{name}” został załadowany. Czat odpowiada teraz "
                             "z jego użyciem."),
        "models.loading": ("Ładowanie {name} — duży model może zająć kilka "
                           "minut przy pierwszym ładowaniu. Aplikacja pozostaje "
                           "responsywna; dostaniesz informację, gdy będzie "
                           "aktywny."),
        "models.loading_btn": "ŁADOWANIE…",
        "models.busy": ("Odpowiedź wciąż jest przesyłana — zatrzymaj ją lub "
                        "poczekaj na koniec, potem załaduj model ponownie."),
        "models.load_failed_title": "Nie można załadować modelu",
        "models.llama_missing": ("Bezpośrednie ładowanie GGUF wymaga "
                                 "wbudowanego środowiska llama.cpp "
                                 "(llama-cpp-python), którego nie ma w tej "
                                 "wersji. Użyj poniżej „Lokalny Ollama”, aby "
                                 "uruchomić ten model przez lokalny serwer "
                                 "Ollama — wciąż w pełni offline, tylko pętla "
                                 "zwrotna."),
        "models.ollama_btn": "UŻYJ LOKALNEGO OLLAMA…",
        "models.ollama_blurb": ("Masz już uruchomioną Ollamę na tym "
                                "komputerze? Połącz się z nią (tylko pętla "
                                "zwrotna, nigdy zdalny host) i załaduj jeden z "
                                "jej modeli do czatu."),
        "models.ollama_none_title": "Brak lokalnej Ollamy",
        "models.ollama_none": ("Nie można połączyć się z lokalnym serwerem "
                               "Ollama pod 127.0.0.1:11434 lub nie ma on "
                               "modeli. Uruchom Ollamę i pobierz model, a "
                               "następnie spróbuj ponownie."),
        "models.ollama_pick_title": "Załaduj model Ollama",
        "models.ollama_pick_prompt": "Lokalny model Ollama:",
        # wiedza --------------------------------------------------------------------
        "card.retrieval": "Lokalne wyszukiwanie",
        "card.search": "Szukaj",
        "card.library": "Biblioteka referencyjna",
        "knowledge.blurb": ("Indeksuj zamontowaną przestrzeń w pełni lokalnie: "
                            "dzielenie kodu według funkcji/klas, hybrydowe "
                            "wyszukiwanie BM25 + wektorowe łączone przez RRF, "
                            "wyniki z cytowaniami (plik:zakres-linii). "
                            "Ugruntowane — brak trafienia zwraca „nie "
                            "znaleziono”, nigdy nie zmyśla."),
        "btn.build_index": "ZBUDUJ / ODŚWIEŻ INDEKS",
        "knowledge.no_index": ("Brak indeksu. Zamontuj przestrzeń, a następnie "
                               "zbuduj."),
        "knowledge.indexed": ("Zaindeksowano {indexed} plik(ów), {chunks} "
                              "fragmentów (pominięto {skipped}, usunięto "
                              "{removed}). Wyszukiwanie działa i cytuje "
                              "źródła."),
        "knowledge.search_placeholder": ("Przeszukaj zaindeksowaną przestrzeń "
                                         "(np. validate_token)…"),
        "knowledge.mount_first": ("Najpierw zamontuj i zaindeksuj "
                                  "przestrzeń."),
        "knowledge.not_found": "Nie znaleziono w zaindeksowanej przestrzeni.",
        "library.blurb": ("Dołącz duży folder z kartami katalogowymi, normami "
                          "i archiwami jako bibliotekę TYLKO DO ODCZYTU. Agent "
                          "może ją przeszukiwać słowami kluczowymi "
                          "(search_library) i czytać trafienia "
                          "(PDF/Word/Excel/tekst) — nigdy nie może tam "
                          "zapisywać."),
        "btn.attach_library": "DOŁĄCZ BIBLIOTEKĘ…",
        "btn.index_library": "INDEKSUJ TEKST BIBLIOTEKI",
        "library.index_tooltip": ("Opcjonalnie: zaindeksuj pliki tekstowe "
                                  "biblioteki, aby search_library dopasowywał "
                                  "też TREŚĆ plików, nie tylko nazwy"),
        "library.attached": ("BIBLIOTEKA: {path}  (tylko odczyt)\nAgent może ją "
                             "przeszukiwać słowami kluczowymi i czytać z niej "
                             "dokumenty. Zaindeksuj poniżej treść tekstową, aby "
                             "włączyć też wyszukiwanie po zawartości."),
        "library.indexed": ("BIBLIOTEKA: {path}  (tylko odczyt)\nZaindeksowano "
                            "{indexed} plik(ów) tekstowych, {chunks} fragmentów "
                            "— search_library dopasowuje teraz zawartość, nie "
                            "tylko nazwy. (Pliki PDF/Office są wyszukiwane po "
                            "nazwie i czytane na żądanie.)"),
        "library.attach_dialog": ("Dołącz bibliotekę referencyjną (tylko "
                                  "odczyt)"),
        "library.attach_refused": "Odmowa dołączenia",
        # ustawienia -----------------------------------------------------------------
        "card.appearance": "Wygląd i język",
        "card.engine": "Silnik",
        "card.security": "Bezpieczeństwo",
        "card.personas": "Persony asystenta",
        "card.about": "O programie",
        "settings.summary": ("Motyw: {theme}   ·   Język: {language}   ·   "
                             "Ograniczenie animacji: {rm}"),
        "settings.engine_summary": ("Backend: {backend}   ·   kontekst {ctx}   "
                                    "·   temp. {temp}"),
        "settings.security_summary": ("Straż sieciowa: {ng}   ·   Szyfrowanie "
                                      "danych: {enc}   ·   Audyt: {audit}   ·   "
                                      "Wersja air-gap: {ag}"),
        "btn.change_theme": "ZMIEŃ MOTYW",
        "personas.blurb": ("Twórz własne prompty systemowe — np. firmowy styl "
                           "raportów. Własne persony pojawiają się w wyborze "
                           "person na czacie i zawsze zachowują stopkę "
                           "bezpieczeństwa „tylko lokalnie”."),
        "btn.new_persona": "NOWA PERSONA…",
        "btn.edit_persona": "EDYTUJ / USUŃ…",
        "personas.none": "Brak własnych person.",
        "personas.custom": "Własne: ",
        "persona.dialog_title": "Własna persona",
        "persona.name_label": "Nazwa (widoczna w wyborze person na czacie)",
        "persona.prompt_label": ("Prompt systemowy (jak asystent ma się "
                                 "zachowywać)"),
        "persona.prompt_placeholder": ("np. Piszesz raporty z badań dla ACME "
                                       "Defense. Zawsze struktura: Cel, "
                                       "Konfiguracja, Procedura, Wyniki, "
                                       "Werdykt…"),
        "persona.delete": "USUŃ",
        "persona.none_title": "Brak własnych person",
        "persona.none_msg": "Najpierw utwórz personę przyciskiem NOWA PERSONA…",
        "persona.pick_title": "Edytuj personę",
        "persona.pick_label": "Własna persona:",
        "about.blurb": ("{app} v{version} — w pełni lokalny asystent AI zdolny "
                        "do pracy w izolacji od sieci. Licencja MIT. Zero "
                        "telemetrii."),
        "about.credit": "Stworzony przez LukiBox — github.com/LukiBox",
        "btn.onboarding": "POWTÓRZ WPROWADZENIE",
        "btn.tutorial": "SZCZEGÓŁOWY SAMOUCZEK",
        # czat -------------------------------------------------------------------------
        "chat.secure_channel": "Bezpieczny kanał",
        "chat.placeholder": "Zapytaj BastionBox… nic nie opuszcza tego komputera.",
        "chat.send": "Wyślij",
        "chat.stop": "Zatrzymaj",
        "chat.new": "Nowa",
        "chat.new_tooltip": "Rozpocznij nową rozmowę",
        "chat.compact_tooltip": ("Kompaktuj — streść starsze wypowiedzi, aby "
                                 "zwolnić kontekst"),
        "chat.history_tooltip": "Historia — otwórz zapisaną rozmowę",
        "chat.persona_tooltip": "Persona — określa ton i specjalizację asystenta",
        "chat.greeting": ("Bezpieczny kanał otwarty. Działam wyłącznie na tym "
                          "komputerze — bez chmury, bez telemetrii, bez sieci. "
                          "Zamontuj przestrzeń roboczą, abym mógł czytać i "
                          "edytować pliki za Twoją zgodą, albo po prostu "
                          "zapytaj o cokolwiek."),
        "chat.compact": "Skompaktuj kontekst",
        "chat.thinking": "Rozumowanie…",
        "chat.empty_reply": ("(Model nie zwrócił tekstu — mógł zużyć cały limit "
                             "tokenów na rozumowanie. Spróbuj ponownie lub "
                             "zwiększ limit tokenów.)"),
        "chat.agent_reading": "⋯ krok {step}: czytanie kontekstu…",
        "chat.agent_writing": "⋯ krok {step}: pisanie… ({chars} znaków)",
        "chat.agent_question_title": "AGENT MA PYTANIE",
        "chat.agent_question_hint": ("Odpowiedz, aby odblokować agenta, albo "
                                     "Pomiń, aby kontynuował według własnej "
                                     "oceny."),
        "chat.agent_answer": "Odpowiedz",
        "chat.agent_skip": "Pomiń",
        "chat.model_loaded": ("Model „{name}” jest teraz aktywny. Odpowiedzi "
                              "pochodzą od niego, wciąż w całości na tym "
                              "komputerze."),
        "chat.model_loaded_generic": ("Lokalny model jest teraz aktywny. "
                                      "Odpowiedzi pochodzą od niego, wciąż w "
                                      "całości na tym komputerze."),
        "chat.context_is": "Okno kontekstu: {n} tokenów.",
        # strona bezpieczeństwa ---------------------------------------------------
        "sec.title": "STAN BEZPIECZEŃSTWA",
        "sec.netguard": "Straż sieciowa",
        "sec.blocked_label": "Zablokowane próby wyjścia",
        "sec.netguard_note": ("Strażnik gniazd w procesie. Blokuje każde "
                              "połączenie poza pętlą zwrotną — łącznie z "
                              "niedbałymi zależnościami. W normalnej pracy "
                              "licznik wskazuje 0."),
        "sec.encryption": "Szyfrowanie danych",
        "sec.enc_sealed": ("Rozmowy, indeksy, wyodrębniony tekst i ustawienia "
                           "są zapieczętowane AES-256-GCM; klucz pochodzi z "
                           "Argon2id lub klucza maszynowego DPAPI."),
        "sec.enc_unsealed": ("Brak załadowanego klucza — magazyn działa "
                             "NIEZAPIECZĘTOWANY. Ustaw hasło w Ustawieniach, "
                             "aby szyfrować dane."),
        "sec.audit": "Łańcuch audytu",
        "sec.verify_btn": "ZWERYFIKUJ ŁAŃCUCH",
        "sec.audit_note": ("Tylko-dopisywalny dziennik JSONL łączony skrótami. "
                           "Każde wywołanie narzędzia, ścieżka pliku, różnica, "
                           "polecenie i zatwierdzenie jest rejestrowane. "
                           "Weryfikacja ponownie hashuje cały łańcuch i "
                           "wskazuje każdy zmieniony lub ucięty wpis."),
        "sec.panic": "Kontrole awaryjne",
        "sec.panic_pill": "UŻYWAJ OSTROŻNIE",
        "sec.panic_note": ("Nieodwracalne. Bezpieczne usunięcie kasuje cały "
                           "ślad przestrzeni — rozmowy, indeks, wyodrębniony "
                           "tekst — i nadpisuje zwolnione strony bazy danych. "
                           "Zablokuj teraz usuwa klucz z pamięci do ponownego "
                           "odblokowania."),
        "sec.lock": "ZABLOKUJ TERAZ",
        "sec.locked": "ZABLOKOWANO",
        "sec.wipe": "BEZPIECZNIE USUŃ PRZESTRZEŃ",
        "sec.no_ws_msg": ("Najpierw zamontuj przestrzeń; nie ma nic do "
                          "usunięcia."),
        "sec.wipe_title": "Bezpieczne usuwanie przestrzeni",
        "sec.wipe_confirm": ("Trwale usunąć WSZYSTKIE dane BastionBox dla:\n\n"
                             "{path}\n\nRozmowy, indeks i wyodrębniony tekst "
                             "będą nie do odzyskania. Kontynuować?"),
        "sec.wipe_done_title": "Bezpieczne usuwanie zakończone",
        "sec.wipe_done": ("Usunięto {removed} rozmów i wyczyszczono indeks tej "
                          "przestrzeni. Zwolnione strony bazy zostały "
                          "nadpisane."),
        "sec.chain_valid": ("Łańcuch prawidłowy — {entries} wpisów, "
                            "nieprzerwany od początku."),
        "sec.tamper_detected": "WYKRYTO MANIPULACJĘ: {detail}",
        "sec.whitelisted": "Biała lista: {eps}",
        "sec.eps_none": "brak (air-gap)",
        "sec.airgap_suffix": "   ·   WERSJA AIR-GAP",
        "sec.pill_armed": "UZBROJONA",
        "sec.pill_down": "WYŁĄCZONA",
        "sec.pill_secure": "BEZPIECZNY",
        "sec.pill_unsealed": "NIEZAPIECZĘTOWANY",
        "sec.pill_breach": "PRÓBA WYCIEKU",
        "sec.pill_locked": "ZABLOKOWANY",
        "sec.pill_not_verified": "NIEZWERYFIKOWANY",
        "sec.pill_valid": "PRAWIDŁOWY",
        "sec.pill_tampered": "NARUSZONY",
        # klucze statusowe (zgodność) -----------------------------------------------------
        "status.secure": "BEZPIECZNY",
        "status.armed": "UZBROJONY",
        "status.offline": "OFFLINE",
        "status.blocked": "ZABLOKOWANO",
        "security.netguard": "Straż sieciowa",
        "security.blocked_count": "Zablokowane próby wyjścia",
        "security.encryption": "Szyfrowanie danych",
        "security.audit_chain": "Łańcuch audytu",
        "security.verify": "Zweryfikuj łańcuch",
        "security.verified_valid": "PRAWIDŁOWY — {count} wpisów",
        "security.verified_broken": "NARUSZONY — wpis {seq}",
        "agent.approve": "Zatwierdź",
        "agent.reject": "Odrzuć",
        "agent.approve_all": "Auto-zatwierdzanie (sesja)",
        "agent.diff_preview": "Proponowana zmiana — sprawdź przed zapisem",
        "workspace.mount": "Zamontuj przestrzeń…",
        "workspace.read_only": "Tylko odczyt",
        "workspace.ask": "Pytaj przy zapisie",
        "workspace.auto": "Auto-zatwierdzanie zapisów",
        "model.import": "Importuj GGUF…",
        "model.verify_hash": "SHA-256 zweryfikowany",
        "model.hash_mismatch": "NIEZGODNOŚĆ HASH — nie ładuj",
        "common.cancel": "Anuluj",
        "common.confirm": "Potwierdź",
        "common.close": "Zamknij",
    },
}


class Translator:
    """Holds the active language and resolves dotted keys with ``{}`` formatting.

    One instance is created at startup and shared; ``set_language`` flips every
    subsequent lookup. Widgets that want live language switching re-read their
    strings when the app calls their ``retranslate()``.
    """

    def __init__(self, language: str = "en"):
        self.language = language if language in TRANSLATIONS else "en"

    def set_language(self, language: str) -> None:
        if language in TRANSLATIONS:
            self.language = language

    def t(self, key: str, **fmt: Any) -> str:
        table = TRANSLATIONS.get(self.language, TRANSLATIONS["en"])
        text = table.get(key) or TRANSLATIONS["en"].get(key) or key
        try:
            return text.format(**fmt) if fmt else text
        except (KeyError, IndexError):
            return text


#: The one translator the UI shares. app.py sets its language at startup from
#: the persisted setting; the Settings page flips it live.
_shared = Translator("en")


def t(key: str, **fmt: Any) -> str:
    """Translate *key* in the app-wide language."""
    return _shared.t(key, **fmt)


def set_language(language: str) -> None:
    _shared.set_language(language)


def current_language() -> str:
    return _shared.language
