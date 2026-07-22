# BastionBox — Threat Model, Guarantees, and Non-Guarantees

> One honest paragraph beats ten marketing pages. This document says exactly what
> BastionBox guarantees and exactly what it does not. If you are accrediting an
> environment, the technical controls here are meant to make your answers easy —
> but **formal accreditation of any classified environment is your
> organization's responsibility, not a property of this software.**

## Design stance

BastionBox provides **technical controls**. Its job is to make three answers
trivially demonstrable:

1. **Nothing leaves.** Every outbound connection attempt is blocked and recorded.
2. **Everything is logged.** Every tool call, file path, diff, command, and
   approval is in a tamper-evident chain.
3. **Everything is encrypted.** Data at rest is sealed with authenticated
   encryption; the key never lives in a file the user didn't unlock.

Security is treated as architecture, not a feature list. The path jail, the
offline guard, and the audit log are load-bearing walls: a convenience that
weakens any of them gets cut, not the wall. Each wall is covered by tests that
**gate every milestone** (`tests/test_jail.py`, `test_netguard.py`,
`test_audit.py`, `test_crypto.py`, `test_agent_loop.py`).

## Assets we protect

- The contents of mounted workspaces (source code, documents).
- The conversation history, indexes, and extracted document text.
- The record of what the assistant did (the audit trail's integrity).

## Adversaries we consider

| Adversary | Example | Primary control |
|---|---|---|
| A weak/confused local model | emits a path outside the workspace, or invents a tool call | **Path jail** + grammar-constrained tool calls |
| A malicious document or prompt injection | tricks the model into "read `../../secrets`" or "run `curl …`" | **Path jail** + **command approval** + **network guard** |
| A sloppy or hostile dependency | a library tries to phone home at import | **In-process network guard** installed before any other import |
| Someone who alters the record | edits/truncates the audit log to hide activity | **Hash-chained audit** + one-click verify |
| Physical access / disk seizure | copies the data directory | **AES-256-GCM at rest** + secure-delete |
| A curious insider | reads another workspace's context | **Per-workspace isolation** (chats/index/audit scoped by workspace key) |

---

## Guarantees (what the technical controls actually do)

### 1. The path jail confines every file operation
Every read, write, edit, list, glob, grep, and command cwd is resolved through
`PathJail.resolve` (`core/security/jail.py`) — the single chokepoint. It
canonicalizes with `os.path.realpath` (following symlinks/junctions to their real
target) **before** checking containment, so a reparse point inside a workspace
that points outside lands outside a root and is rejected. Rejected escapes,
proven by the test suite: `..` traversal (lexical and post-symlink), absolute
paths outside every root, UNC (`\\server\share`), Win32 device/namespace paths
(`\\?\`, `\\.\`), drive-relative (`C:foo`), embedded NUL bytes, empty paths, and
paths on a different drive than any workspace. This includes the search tools:
both the `ripgrep` and the pure-Python fallback path of `grep` re-resolve every
matching file through the jail before its contents are returned, so a reparse
point inside a workspace cannot leak an outside file into the model's context via
a search. **There is deliberately no second file API** — nothing reads or writes
disk except through the jail.

### 2. The network guard blocks outbound traffic in-process
`NetworkGuard` (`core/security/netguard.py`) monkeypatches the socket primitives
every networking library funnels through — `connect`, `connect_ex`,
`create_connection`, `getaddrinfo`, the legacy name resolvers `gethostbyname` /
`gethostbyname_ex` / `gethostbyaddr`, and the **connectionless `sendto` /
`sendmsg`** (a UDP datagram needs no `connect()`, so leaving those open would be a
DNS-tunnel-style exfiltration path) — **before Qt or any dependency is imported**
(see the top of `app.py`). Name resolution is guarded through *both* the modern
`getaddrinfo` and the older `gethostbyname*` family, so a public hostname cannot be
resolved (the DNS query itself is a byte leaving the box) by either route.
Non-loopback connections and datagrams fail closed and increment an audited
counter. `AF_UNIX` sockets are exempt (filesystem-local IPC that cannot leave the
machine). The only network whitelist is loopback (for an optional local Ollama);
the Air-Gap build removes even that. Verified by actual `socket.create_connection`,
`sendto`, **and `gethostbyname`** attempts in the tests.

### 3. The audit log is tamper-evident
`AuditLog` (`core/security/audit.py`) is append-only JSONL where each entry
carries the previous entry's hash. `verify()` recomputes the whole chain and
reports the first entry that fails — detecting content mutation, hash forgery
(without the key), reordering, insertion, and mid-file deletion, with the exact
sequence number. Deleting the *newest* entries would leave a shorter chain that is
internally valid, so the log is anchored by a **signed side-checkpoint** recording
the last sequence number, hash, and count; `verify()` compares the chain against it
and flags a lopped-off tail (or a wholesale deletion) that chain-only checking would
miss. With a secret key the chain and the checkpoint both use HMAC-SHA256, so an
attacker who can rewrite the files and recompute plain SHA-256 still cannot forge
either. (The checkpoint is a sidecar on the same machine; for the strongest
guarantee against an attacker who can also delete it, keep the periodic off-box
export in the checklist below.) Prompt and file **contents are never stored** — only
SHA-256 fingerprints, sizes, and paths.

### 4. Data at rest is authenticated-encrypted
`crypto.py` seals every sensitive column with **AES-256-GCM**; keys are derived
with **Argon2id** (memory-hard) or high-iteration **PBKDF2** from an app
passphrase, or from a **Windows DPAPI machine key** (no third-party dependency).
The passphrase KDF uses a **random, per-install salt** persisted next to the data
(never a hardcoded salt — that would let one precomputed table attack every
install), and on Windows without a passphrase a random key is generated once and
wrapped with DPAPI so the store is unreadable off that account. GCM's tag makes
each row tamper-evident, and additional-authenticated-data binds a row to its
workspace so ciphertext cannot be transplanted between scopes.
**Secure-delete** removes a workspace's entire footprint and `VACUUM`s the
database so freed pages are rewritten.

### 5. No silent memory; writes require consent
Anything the assistant "remembers" across chats lives in a visible, editable,
per-workspace `memory.md` (stored in the encrypted store, surfaced in the UI) —
never hidden state. Every write/edit shows a unified diff and is Approve/Reject;
a rejection returns to the model as an observation so it adapts. Commands always
ask unless the exact string is on a user-defined allowlist.

---

## Non-guarantees (read this part twice)

BastionBox does **not** claim any of the following, and you should not represent
that it does:

- **A local model can still be wrong.** Grounding, citations, and verify steps
  reduce hallucination; they do not eliminate it. Treat outputs as a capable
  assistant's, not as ground truth.
- **The in-process network guard is not a kernel firewall.** It patches Python's
  socket layer. A native extension or a spawned child process calling the OS
  socket API directly is **outside** its reach. Use it *with* an OS firewall rule
  and, for classified work, an actual air gap — defense in depth. The Air-Gap
  build additionally omits networking dependencies so the capability is *absent*.
- **The command sandbox is bounded, not hermetic.** `run_command` gives a jailed
  cwd, a stripped environment, a wall-clock timeout, an output cap, and an
  approval gate — real and useful. It does **not** provide OS-level isolation:
  a command you approve can do what your user account can do. Network isolation
  for child processes is an OS concern (Windows Job Objects / firewall rules),
  not something Python can enforce from inside the parent. We say so rather than
  claiming magic.
- **Encryption protects data at rest, not a running process.** While BastionBox
  is unlocked, keys are in memory. "Lock now" wipes the key; a memory-scraping
  adversary with code execution on an unlocked machine is out of scope.
- **Reading an untrusted document is native-code parsing.** PDF/Word/Excel
  extraction relies on libraries with native components (PyMuPDF, Pillow, and the
  like). A malicious file that triggers a memory-safety bug in one of them runs
  code that the path jail and network guard cannot stop — the parser is *inside*
  the trusted process. Treat "read this datasheet from an unknown source" as
  elevated risk: pin and monitor those library versions, keep an out-of-band patch
  path in your SLA (air-gapped boxes do not self-update), and for the highest
  assurance isolate extraction in a reduced-privilege child (Windows Job Object /
  AppContainer).
- **Accreditation is your organization's job.** BastionBox supplies technical
  controls and evidence (logs, verifiers, encryption). It cannot grant an ATO.

## Defense-in-depth checklist for high-assurance sites

- [ ] Deploy the **Air-Gap build** (no networking dependencies compiled in).
- [ ] Add an **OS firewall rule** denying the BastionBox process (and its
      children) all outbound network access.
- [ ] Run on an **actually air-gapped** machine; deliver models by verified media.
- [ ] Set a strong **store passphrase** (Argon2id) or enforce DPAPI machine keys.
- [ ] Periodically **export and verify** the audit chain off-box.
- [ ] Restrict the **command allowlist** to the minimum (ideally empty).
