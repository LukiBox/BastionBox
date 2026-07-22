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
        "chat.you": "You",
        "chat.chip_mode": "Mode",
        "chat.chip_persona": "Persona",
        "chat.chip_library": "Library",
        "chat.chip_model": "Model",
        "chat.chip_trace": "Agent trace",
        "chat.chip_compacted": "Context compacted",
        "chat.chip_attachment": "Attachment",
        "chat.default_title": "Conversation",
        "chat.library_note": ("Reference library attached (read-only): {name}. "
                              "I can search it with keywords and read documents "
                              "from it; I can never write there."),
        "chat.agent_armed": ("Agent armed on workspace “{name}” ({perm}). I can "
                             "read and edit files here — every write is shown "
                             "to you as a diff to approve."),
        "chat.agent_disarmed": "Returned to chat mode. No workspace is mounted.",
        "chat.persona_switched": ("Switched to persona “{name}”. Tone and focus "
                                  "updated; the security posture is unchanged."),
        "chat.persona_switched_custom": ("Switched to custom persona “{name}”. "
                                         "Tone and focus updated; the security "
                                         "posture is unchanged."),
        "chat.compact_nothing": "Not enough earlier context to compact yet.",
        "chat.compact_marker": ("Earlier turns were summarized to free context "
                                "(the model now sees this summary in their "
                                "place, plus the most recent messages):"),
        "chat.history_disabled": "(persistence disabled)",
        "chat.history_empty": "(no saved conversations in this scope)",
        # chat attachments (drag & drop) --------------------------------------
        "chat.attach_clear": "Clear",
        "chat.attach_bar_tooltip": ("These files ride along with your next "
                                    "message — their text is read locally and "
                                    "given to the model."),
        "chat.attach_added": ("Attached “{name}” ({kind}, {chars} characters). "
                              "It rides along with your next message."),
        "chat.attach_dir": ("“{name}” is a folder. Drop individual files, or "
                            "mount the folder as a workspace / attach it as a "
                            "read-only library."),
        "chat.attach_too_big": ("“{name}” is too large to attach ({mb} MB). "
                                "Mount its folder as a workspace and let the "
                                "agent read it with tools instead."),
        "chat.attach_unsupported": ("“{name}” looks binary or is an unsupported "
                                    "type. I can attach PDF, Word, Excel, CSV, "
                                    "and plain-text/code files."),
        "chat.attach_failed": "Could not attach “{name}”: {error}",
        "chat.attach_line": "📎 {name} ({chars} characters)",
        # diff / command approval dialogs --------------------------------------
        "diff.title": "Review change — approval required",
        "diff.new_file": "New file",
        "diff.edit": "Edit",
        "diff.workspace_line": ("Workspace: {name}  ·  review before it is "
                                "written"),
        "diff.note_placeholder": ("Optional note on rejection (fed back to the "
                                  "agent)…"),
        "cmd.title": "Run command — approval required",
        "cmd.body": ("The agent wants to run, jailed to the workspace:\n\n"
                     "    {command}\n\nOutput is captured and logged."),
        # quick-ask palette ----------------------------------------------------
        "qa.title": "Quick Ask",
        "qa.pill": "OFFLINE · SEALED",
        "qa.placeholder": ("Ask anything — Esc to dismiss. Nothing leaves this "
                           "machine."),
        "qa.clipboard": "Use clipboard as context",
        "qa.hint": "↩ ask   ·   Esc close",
        # audit browser --------------------------------------------------------
        "audit.title": "AUDIT TRAIL",
        "audit.verify": "Verify",
        "audit.export": "Export",
        "audit.reload": "Reload",
        "audit.export_tooltip": ("Export the audit log for off-box review "
                                 "(copies the JSONL)"),
        "audit.filter_placeholder": ("Filter by kind or detail (e.g. "
                                     "file_write, command)…"),
        "audit.col_seq": "Seq",
        "audit.col_time": "Time",
        "audit.col_kind": "Kind",
        "audit.col_detail": "Detail",
        "audit.pill_valid": "VALID · {entries}",
        "audit.pill_tampered": "TAMPERED · #{seq}",
        "audit.empty_title": "Nothing to export",
        "audit.empty": "The audit log is empty.",
        "audit.export_dialog": "Export audit log",
        "audit.exported_title": "Audit exported",
        "audit.exported": ("Copied {entries} entries to:\n{dest}\n\nChain "
                           "status at export: {status}"),
        "audit.exported_valid": ("VALID — verify it again off-box with the "
                                 "same tool."),
        "audit.exported_tampered": "TAMPERED at entry {seq}.",
        # onboarding tour ------------------------------------------------------
        "ob.title": "Welcome to BastionBox",
        "ob.s1_head": "NOTHING LEAVES",
        "ob.s1_body": ("BastionBox runs entirely on this machine. An in-process "
                       "network guard is armed before anything else loads and "
                       "blocks every outbound connection — including a sloppy "
                       "dependency's. The Security tab shows a blocked-attempt "
                       "counter that reads 0 in normal use."),
        "ob.s1_pill": "OFFLINE · SEALED",
        "ob.s2_head": "YOU APPROVE EVERY WRITE",
        "ob.s2_body": ("Mount a folder as a workspace and the agent can read "
                       "and edit inside it — and nowhere else, enforced by the "
                       "path jail. Every write is shown to you as a diff to "
                       "Approve or Reject before it touches disk. A rejection "
                       "is fed back to the model so it adapts."),
        "ob.s3_head": "EVERYTHING IS PROVABLE",
        "ob.s3_body": ("Every prompt, tool call, file path, diff, and command "
                       "is recorded in a hash-chained audit log. One click "
                       "re-verifies the whole chain and flags any tampering. "
                       "Data at rest is AES-256-GCM encrypted; secure-delete "
                       "wipes a workspace's entire footprint."),
        "ob.s3_pill": "AUDIT · VERIFIABLE",
        "ob.show_again": "Show this tour next launch",
        "ob.tutorial_tip": ("Step-by-step: load a GGUF, run the agent, edit "
                            "files & docs"),
        "ob.back": "Back",
        "ob.next": "Next",
        "ob.enter": "Enter BastionBox",
        # theme picker ---------------------------------------------------------
        "theme.window": "Choose your display",
        "theme.title": "DISPLAY THEME",
        "theme.hint": ("Pick a look — it applies instantly. You can change it "
                       "any time in Settings."),
        "theme.dark_sub": "Deep forest + sage teal",
        "theme.light_sub": "Soft sage + floating white",
        "theme.remember": "Use this and don't ask at launch again",
        # detailed tutorial ----------------------------------------------------
        "tut.window": "BastionBox — Detailed Tutorial",
        "tut.title": "HOW TO USE BASTIONBOX",
        "tut.sub": ("Load a model · mount a workspace · read datasheets and "
                    "write Word/Excel/PDF — all fully offline."),
        "tut.s1_head": "1 · LOAD A MODEL (GGUF)",
        "tut.s1_pill": "MODELS TAB",
        "tut.s1_1": ("Open the Models tab. BastionBox reads any GGUF file "
                     "straight off disk — models arrive by USB/media, never a "
                     "download."),
        "tut.s1_2": ("Click IMPORT GGUF… and pick your file (e.g. "
                     "qwen2.5-14b-instruct-q4.gguf)."),
        "tut.s1_3": ("Paste the SHA-256 you were given out-of-band. A green "
                     "check means the file is authentic; a red flag means DO "
                     "NOT load it."),
        "tut.s1_4": ("The Hardware Optimizer shows the offload plan and the "
                     "math — how many layers fit on your GPU and the context "
                     "length that fits."),
        "tut.s1_5": ("Prefer a 7–14B Q4 model for an 8 GB GPU; CPU-only works "
                     "with a 3–8B Q4."),
        "tut.s2_head": "2 · MOUNT A WORKSPACE & RUN THE AGENT",
        "tut.s2_pill": "WORKSPACES TAB",
        "tut.s2_1": ("Open Workspaces and click the permission chip to pick a "
                     "tier: Read-only, Ask per write (recommended), or "
                     "Auto-approve."),
        "tut.s2_2": ("Click MOUNT WORKSPACE… and choose a folder. The agent is "
                     "confined to that folder by the path jail and can touch "
                     "nothing outside it."),
        "tut.s2_3": ("You are dropped into Chat in agent mode. Ask it to do "
                     "real work: \"rename check_tok to validate_token "
                     "everywhere and update the docstring\"."),
        "tut.s2_4": ("The agent inspects first (grep/read), then proposes "
                     "edits. Each write shows a DIFF — Approve, or Reject with "
                     "a note it will adapt to."),
        "tut.s2_5": ("Ask it to run a check (e.g. \"run pytest -q\"); "
                     "allowlisted commands run jailed, output captured in the "
                     "transcript."),
        "tut.s3_head": "3 · FILE EDITING & OFFICE DOCS",
        "tut.s3_pill": "THE CORE FLOW",
        "tut.s3_1": ("Drop a datasheet (.pdf), report (.docx) or sheet (.xlsx) "
                     "into the mounted workspace folder — or drag it straight "
                     "into the chat to attach it to your next message."),
        "tut.s3_2": ("Ask: \"read the datasheet spec.pdf and summarize the "
                     "electrical ratings into a Word report\". The agent calls "
                     "read_document (page-aware for long PDFs) then "
                     "write_document."),
        "tut.s3_3": ("For tables/data, ask for Excel: \"extract the pin table "
                     "from spec.pdf into pins.xlsx\" — it writes a real .xlsx "
                     "with a styled header."),
        "tut.s3_4": ("For code, ask it to create or edit files directly "
                     "(write_file / edit_file) — basic scripts, configs, and "
                     "docs, always behind a diff you approve."),
        "tut.s3_5": ("Every written file lands inside the workspace, is shown "
                     "for approval first, and is recorded in the tamper-evident "
                     "audit log."),
        "tut.s4_head": "4 · TEMPLATES & THE REFERENCE LIBRARY",
        "tut.s4_pill": "EA WORKFLOW",
        "tut.s4_1": ("Attach a big folder of datasheets/norms in Knowledge → "
                     "Reference Library. It is READ-ONLY: the agent can search "
                     "and read there, never write."),
        "tut.s4_2": ("Ask: \"find the vibration section of MIL-STD-810 in the "
                     "library and quote the procedure\" — the agent calls "
                     "search_library with keywords, then read_document on the "
                     "hits."),
        "tut.s4_3": ("Put your company .docx template (logo, formatting) in "
                     "the workspace or library, with placeholders: {{TITLE}}, "
                     "{{SUMMARY}}, {{IMG:photo1}}, and a table row containing "
                     "{{TABLE:results}}."),
        "tut.s4_4": ("Ask: \"fill template company.docx with the climatic test "
                     "results into report.docx\" — fill_template keeps your "
                     "branding and swaps in text, photos, and test-data rows. "
                     "Unfilled placeholders are reported, never silently "
                     "dropped."),
        "tut.s4_5": ("Pick the EA Test-Case Writer persona for MIL-STD-810-"
                     "style requirements (REQ-ENV-001, −51 °C to +71 °C) and "
                     "numbered Step 1./Step 2. procedures."),
        "tut.s4_6": ("Reports can carry real charts and photos: the agent "
                     "embeds workspace images with ![caption](photos/rig.png) "
                     "and renders bar/line/pie charts from data it read — "
                     "vector art in PDFs, crisp images in Word. "
                     "write_spreadsheet can add a native, still-editable Excel "
                     "chart."),
        "tut.s5_head": "GOOD TO KNOW",
        "tut.s5_pill": "SECURITY",
        "tut.s5_1": ("Nothing leaves the machine — the network guard blocks "
                     "every outbound connection; the Security tab's blocked "
                     "counter should read 0 forever."),
        "tut.s5_2": ("Everything is encrypted at rest; use Panic Controls to "
                     "secure-delete a workspace's entire footprint or lock the "
                     "key from memory."),
        "tut.s5_3": ("Switch tone with the persona dropdown — or create your "
                     "own persona with a custom system prompt in Settings → "
                     "Assistant Personas."),
        "tut.s5_4": ("The whole interface speaks English and Polish — switch "
                     "live in Settings → Appearance & Language; the choice "
                     "persists across launches."),
        "tut.s5_5": ("Free context with COMPACT; start fresh with NEW. Summon "
                     "quick-ask anywhere with Ctrl+Alt+Space."),
        # misc chrome ----------------------------------------------------------
        "meter.context": "Context",
        "tray.sealed": "{name} · sealed",
        "status.no_model": "no model loaded",
        "app.credit": "Made by LukiBox",
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
        "chat.you": "Ty",
        "chat.chip_mode": "Tryb",
        "chat.chip_persona": "Persona",
        "chat.chip_library": "Biblioteka",
        "chat.chip_model": "Model",
        "chat.chip_trace": "Ślad agenta",
        "chat.chip_compacted": "Kontekst skompaktowany",
        "chat.chip_attachment": "Załącznik",
        "chat.default_title": "Rozmowa",
        "chat.library_note": ("Dołączono bibliotekę referencyjną (tylko "
                              "odczyt): {name}. Mogę ją przeszukiwać słowami "
                              "kluczowymi i czytać z niej dokumenty; nigdy nie "
                              "mogę tam zapisywać."),
        "chat.agent_armed": ("Agent uzbrojony w przestrzeni „{name}” ({perm}). "
                             "Mogę tu czytać i edytować pliki — każdy zapis "
                             "zobaczysz jako różnicę do zatwierdzenia."),
        "chat.agent_disarmed": ("Powrót do trybu czatu. Żadna przestrzeń nie "
                                "jest zamontowana."),
        "chat.persona_switched": ("Przełączono na personę „{name}”. Ton i "
                                  "specjalizacja zaktualizowane; poziom "
                                  "bezpieczeństwa bez zmian."),
        "chat.persona_switched_custom": ("Przełączono na własną personę "
                                         "„{name}”. Ton i specjalizacja "
                                         "zaktualizowane; poziom "
                                         "bezpieczeństwa bez zmian."),
        "chat.compact_nothing": ("Za mało wcześniejszego kontekstu, aby "
                                 "kompaktować."),
        "chat.compact_marker": ("Starsze wypowiedzi streszczono, aby zwolnić "
                                "kontekst (model widzi teraz w ich miejscu to "
                                "streszczenie oraz najnowsze wiadomości):"),
        "chat.history_disabled": "(zapisywanie wyłączone)",
        "chat.history_empty": "(brak zapisanych rozmów w tym zakresie)",
        # załączniki na czacie (przeciągnij i upuść) ---------------------------
        "chat.attach_clear": "Wyczyść",
        "chat.attach_bar_tooltip": ("Te pliki dołączą do Twojej następnej "
                                    "wiadomości — ich tekst jest odczytywany "
                                    "lokalnie i przekazywany modelowi."),
        "chat.attach_added": ("Załączono „{name}” ({kind}, {chars} znaków). "
                              "Dołączy do Twojej następnej wiadomości."),
        "chat.attach_dir": ("„{name}” to folder. Upuść pojedyncze pliki albo "
                            "zamontuj folder jako przestrzeń / dołącz jako "
                            "bibliotekę tylko do odczytu."),
        "chat.attach_too_big": ("„{name}” jest zbyt duży, aby go załączyć "
                                "({mb} MB). Zamontuj jego folder jako "
                                "przestrzeń i pozwól agentowi czytać go "
                                "narzędziami."),
        "chat.attach_unsupported": ("„{name}” wygląda na plik binarny lub "
                                    "nieobsługiwany typ. Mogę załączać PDF, "
                                    "Word, Excel, CSV oraz pliki "
                                    "tekstowe/kod."),
        "chat.attach_failed": "Nie udało się załączyć „{name}”: {error}",
        "chat.attach_line": "📎 {name} ({chars} znaków)",
        # okna zatwierdzania różnic i poleceń ----------------------------------
        "diff.title": "Przegląd zmiany — wymagane zatwierdzenie",
        "diff.new_file": "Nowy plik",
        "diff.edit": "Edycja",
        "diff.workspace_line": "Przestrzeń: {name}  ·  sprawdź przed zapisem",
        "diff.note_placeholder": ("Opcjonalna notatka przy odrzuceniu (wraca "
                                  "do agenta)…"),
        "cmd.title": "Uruchomienie polecenia — wymagane zatwierdzenie",
        "cmd.body": ("Agent chce uruchomić, w więzieniu przestrzeni:\n\n"
                     "    {command}\n\nWynik jest przechwytywany i "
                     "rejestrowany."),
        # szybkie pytanie ------------------------------------------------------
        "qa.title": "Szybkie pytanie",
        "qa.pill": "OFFLINE · ZAPIECZĘTOWANY",
        "qa.placeholder": ("Zapytaj o cokolwiek — Esc zamyka. Nic nie opuszcza "
                           "tego komputera."),
        "qa.clipboard": "Użyj schowka jako kontekstu",
        "qa.hint": "↩ pytaj   ·   Esc zamknij",
        # przeglądarka audytu --------------------------------------------------
        "audit.title": "ŚLAD AUDYTU",
        "audit.verify": "Zweryfikuj",
        "audit.export": "Eksportuj",
        "audit.reload": "Odśwież",
        "audit.export_tooltip": ("Eksportuj dziennik audytu do przeglądu poza "
                                 "maszyną (kopiuje JSONL)"),
        "audit.filter_placeholder": ("Filtruj po rodzaju lub szczegółach (np. "
                                     "file_write, command)…"),
        "audit.col_seq": "Lp.",
        "audit.col_time": "Czas",
        "audit.col_kind": "Rodzaj",
        "audit.col_detail": "Szczegóły",
        "audit.pill_valid": "PRAWIDŁOWY · {entries}",
        "audit.pill_tampered": "NARUSZONY · #{seq}",
        "audit.empty_title": "Nie ma czego eksportować",
        "audit.empty": "Dziennik audytu jest pusty.",
        "audit.export_dialog": "Eksport dziennika audytu",
        "audit.exported_title": "Wyeksportowano audyt",
        "audit.exported": ("Skopiowano {entries} wpisów do:\n{dest}\n\nStan "
                           "łańcucha przy eksporcie: {status}"),
        "audit.exported_valid": ("PRAWIDŁOWY — zweryfikuj ponownie poza "
                                 "maszyną tym samym narzędziem."),
        "audit.exported_tampered": "NARUSZONY przy wpisie {seq}.",
        # wprowadzenie ---------------------------------------------------------
        "ob.title": "Witaj w BastionBox",
        "ob.s1_head": "NIC NIE WYCHODZI",
        "ob.s1_body": ("BastionBox działa w całości na tym komputerze. Straż "
                       "sieciowa w procesie uzbraja się przed załadowaniem "
                       "czegokolwiek innego i blokuje każde połączenie "
                       "wychodzące — także niedbałej zależności. Zakładka "
                       "Bezpieczeństwo pokazuje licznik zablokowanych prób, "
                       "który w normalnym użyciu wskazuje 0."),
        "ob.s1_pill": "OFFLINE · ZAPIECZĘTOWANY",
        "ob.s2_head": "ZATWIERDZASZ KAŻDY ZAPIS",
        "ob.s2_body": ("Zamontuj folder jako przestrzeń roboczą, a agent "
                       "będzie mógł czytać i edytować w nim — i nigdzie "
                       "indziej, co wymusza ścieżkowe więzienie. Każdy zapis "
                       "jest pokazywany jako różnica do zatwierdzenia lub "
                       "odrzucenia, zanim dotknie dysku. Odrzucenie wraca do "
                       "modelu, więc ten się dostosowuje."),
        "ob.s3_head": "WSZYSTKO DA SIĘ UDOWODNIĆ",
        "ob.s3_body": ("Każdy prompt, wywołanie narzędzia, ścieżka pliku, "
                       "różnica i polecenie trafia do dziennika audytu "
                       "łączonego skrótami. Jedno kliknięcie weryfikuje cały "
                       "łańcuch i wskazuje manipulacje. Dane w spoczynku są "
                       "szyfrowane AES-256-GCM; bezpieczne usuwanie kasuje "
                       "cały ślad przestrzeni."),
        "ob.s3_pill": "AUDYT · WERYFIKOWALNY",
        "ob.show_again": "Pokaż ten przewodnik przy następnym uruchomieniu",
        "ob.tutorial_tip": ("Krok po kroku: załaduj GGUF, uruchom agenta, "
                            "edytuj pliki i dokumenty"),
        "ob.back": "Wstecz",
        "ob.next": "Dalej",
        "ob.enter": "Wejdź do BastionBox",
        # wybór motywu ---------------------------------------------------------
        "theme.window": "Wybierz wygląd",
        "theme.title": "MOTYW WYŚWIETLANIA",
        "theme.hint": ("Wybierz wygląd — zastosuje się natychmiast. Możesz go "
                       "zmienić w każdej chwili w Ustawieniach."),
        "theme.dark_sub": "Głęboki las + szałwiowy turkus",
        "theme.light_sub": "Miękka szałwia + unosząca się biel",
        "theme.remember": "Użyj tego i nie pytaj przy uruchomieniu",
        # szczegółowy samouczek ------------------------------------------------
        "tut.window": "BastionBox — szczegółowy samouczek",
        "tut.title": "JAK UŻYWAĆ BASTIONBOX",
        "tut.sub": ("Załaduj model · zamontuj przestrzeń · czytaj karty "
                    "katalogowe i pisz Word/Excel/PDF — wszystko w pełni "
                    "offline."),
        "tut.s1_head": "1 · ZAŁADUJ MODEL (GGUF)",
        "tut.s1_pill": "ZAKŁADKA MODELE",
        "tut.s1_1": ("Otwórz zakładkę Modele. BastionBox czyta dowolny plik "
                     "GGUF prosto z dysku — modele przybywają na USB/nośniku, "
                     "nigdy przez pobieranie."),
        "tut.s1_2": ("Kliknij IMPORTUJ GGUF… i wybierz plik (np. "
                     "qwen2.5-14b-instruct-q4.gguf)."),
        "tut.s1_3": ("Wklej SHA-256 otrzymany poza pasmem. Zielony znacznik "
                     "oznacza plik autentyczny; czerwona flaga — NIE ładuj."),
        "tut.s1_4": ("Optymalizator sprzętu pokazuje plan odciążenia i "
                     "wyliczenia — ile warstw mieści się na Twoim GPU i jaka "
                     "długość kontekstu się zmieści."),
        "tut.s1_5": ("Na GPU 8 GB wybierz model 7–14B Q4; na samym CPU "
                     "sprawdzi się 3–8B Q4."),
        "tut.s2_head": "2 · ZAMONTUJ PRZESTRZEŃ I URUCHOM AGENTA",
        "tut.s2_pill": "ZAKŁADKA PRZESTRZENIE",
        "tut.s2_1": ("Otwórz Przestrzenie i kliknij plakietkę uprawnień, aby "
                     "wybrać poziom: Tylko odczyt, Pytaj przy zapisie "
                     "(zalecane) lub Auto-zatwierdzanie."),
        "tut.s2_2": ("Kliknij ZAMONTUJ PRZESTRZEŃ… i wybierz folder. Agent "
                     "jest ograniczony do tego folderu przez ścieżkowe "
                     "więzienie i nie sięgnie nigdzie indziej."),
        "tut.s2_3": ("Trafiasz do czatu w trybie agenta. Zleć prawdziwą "
                     "pracę: „zmień nazwę check_tok na validate_token wszędzie "
                     "i zaktualizuj docstring”."),
        "tut.s2_4": ("Agent najpierw bada (grep/odczyt), potem proponuje "
                     "zmiany. Każdy zapis pokazuje RÓŻNICĘ — zatwierdź albo "
                     "odrzuć z notatką, do której się dostosuje."),
        "tut.s2_5": ("Poproś o sprawdzenie (np. „uruchom pytest -q”); "
                     "polecenia z białej listy działają w więzieniu, a wynik "
                     "trafia do transkryptu."),
        "tut.s3_head": "3 · EDYCJA PLIKÓW I DOKUMENTY BIUROWE",
        "tut.s3_pill": "GŁÓWNY PRZEPŁYW",
        "tut.s3_1": ("Upuść kartę katalogową (.pdf), raport (.docx) lub "
                     "arkusz (.xlsx) do zamontowanego folderu przestrzeni — "
                     "albo przeciągnij wprost na czat, aby dołączyć do "
                     "następnej wiadomości."),
        "tut.s3_2": ("Poproś: „przeczytaj kartę spec.pdf i streść parametry "
                     "elektryczne do raportu Word”. Agent wywoła "
                     "read_document (strona po stronie dla długich PDF), "
                     "potem write_document."),
        "tut.s3_3": ("Dla tabel/danych poproś o Excel: „wyciągnij tabelę "
                     "pinów ze spec.pdf do pins.xlsx” — powstaje prawdziwy "
                     ".xlsx ze stylizowanym nagłówkiem."),
        "tut.s3_4": ("Dla kodu poproś o tworzenie lub edycję plików wprost "
                     "(write_file / edit_file) — skrypty, konfiguracje i "
                     "dokumenty, zawsze za różnicą, którą zatwierdzasz."),
        "tut.s3_5": ("Każdy zapisany plik ląduje w przestrzeni, najpierw "
                     "trafia do zatwierdzenia i jest odnotowany w odpornym na "
                     "manipulacje dzienniku audytu."),
        "tut.s4_head": "4 · SZABLONY I BIBLIOTEKA REFERENCYJNA",
        "tut.s4_pill": "PRZEPŁYW EA",
        "tut.s4_1": ("Dołącz duży folder kart katalogowych/norm w Wiedza → "
                     "Biblioteka referencyjna. Jest TYLKO DO ODCZYTU: agent "
                     "może tam szukać i czytać, nigdy zapisywać."),
        "tut.s4_2": ("Poproś: „znajdź w bibliotece rozdział o wibracjach w "
                     "MIL-STD-810 i zacytuj procedurę” — agent wywoła "
                     "search_library ze słowami kluczowymi, potem "
                     "read_document na trafieniach."),
        "tut.s4_3": ("Umieść firmowy szablon .docx (logo, formatowanie) w "
                     "przestrzeni lub bibliotece, z symbolami: {{TITLE}}, "
                     "{{SUMMARY}}, {{IMG:photo1}} oraz wierszem tabeli "
                     "zawierającym {{TABLE:results}}."),
        "tut.s4_4": ("Poproś: „wypełnij szablon company.docx wynikami badań "
                     "klimatycznych do report.docx” — fill_template zachowa "
                     "branding i podmieni tekst, zdjęcia i wiersze danych. "
                     "Niewypełnione symbole są raportowane, nigdy nie znikają "
                     "po cichu."),
        "tut.s4_5": ("Wybierz personę EA Test-Case Writer dla wymagań w stylu "
                     "MIL-STD-810 (REQ-ENV-001, −51 °C do +71 °C) i "
                     "numerowanych procedur Krok 1./Krok 2."),
        "tut.s4_6": ("Raporty mogą nieść prawdziwe wykresy i zdjęcia: agent "
                     "osadza obrazy z przestrzeni przez "
                     "![podpis](photos/rig.png) i rysuje wykresy "
                     "słupkowe/liniowe/kołowe z odczytanych danych — "
                     "wektorowe w PDF, ostre obrazy w Wordzie. "
                     "write_spreadsheet potrafi dodać natywny, wciąż "
                     "edytowalny wykres Excela."),
        "tut.s5_head": "WARTO WIEDZIEĆ",
        "tut.s5_pill": "BEZPIECZEŃSTWO",
        "tut.s5_1": ("Nic nie opuszcza komputera — straż sieciowa blokuje "
                     "każde połączenie wychodzące; licznik zablokowanych prób "
                     "w zakładce Bezpieczeństwo powinien zawsze wskazywać 0."),
        "tut.s5_2": ("Wszystko jest szyfrowane w spoczynku; użyj Kontroli "
                     "awaryjnych, aby bezpiecznie usunąć cały ślad "
                     "przestrzeni lub usunąć klucz z pamięci."),
        "tut.s5_3": ("Zmieniaj ton listą person — albo utwórz własną personę "
                     "z własnym promptem systemowym w Ustawienia → Persony "
                     "asystenta."),
        "tut.s5_4": ("Cały interfejs mówi po angielsku i po polsku — przełącz "
                     "na żywo w Ustawienia → Wygląd i język; wybór jest "
                     "zapamiętywany."),
        "tut.s5_5": ("Zwalniaj kontekst przyciskiem KOMPAKTUJ; zaczynaj od "
                     "nowa przyciskiem NOWA. Przywołuj szybkie pytanie "
                     "wszędzie skrótem Ctrl+Alt+Space."),
        # pozostałe elementy interfejsu ----------------------------------------
        "meter.context": "Kontekst",
        "tray.sealed": "{name} · zapieczętowany",
        "status.no_model": "brak załadowanego modelu",
        "app.credit": "Stworzone przez LukiBox",
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
