# ETP Legacy → TC-16 compatibility

The native ETP compiler now has an explicitly selected Unified backend. Its
existing Legacy backend and wire protocol remain unchanged. Build the
`tc16_legacy_compiler` example with `tc16-tcc` in CI. Each JSONL request contains
`source`; each response explicitly contains `ok`, a result or a structured error.
The generated `TC16PKG1` package identifies Unified ISA/ABI and `pure-v1`.
Source SHA-256, compiler version, semantic profile and function address debug
symbols accompany it. This is a bounded initial compatibility profile, not a
claim that every Legacy feature has migrated.

| Source behavior | `etp-legacy-pure-return-v1` |
| --- | --- |
| Parameterless int/void functions, main entry | Native parser and symbol table reused |
| Decimal u16 constants, `+`, `-`, return | Native Legacy result checked; Unified Python/Rust CI comparison |
| Arithmetic overflow | Wrapping u16 result; runtime flags remain ISA-specific |
| Local declaration/read/assignment | Explicit rejection: Legacy emitted frame encoding is inconsistent with its VM decoder |
| `*`, `&`, `==` in expressions | Explicit rejection: existing parser consumes these without implementing the operation |
| Contract storage intrinsic | Explicit capability rejection; pure package has no persistent storage grant |
| Arguments, calls inside expressions, loops, conditions | Existing native parser errors; no fabricated support |
| Memory, syscalls, concurrency, interrupts | No host capability in this profile; no claim of full Legacy VM equivalence |

Legacy and Unified stack layouts, instruction counts, flags and intermediate
registers differ. The promised cross-ISA observable for this pure profile is the
halting u16 return result; Python versus Rust Unified comparisons also compare
full machine snapshots, output, exceptions and memory hashes. Compilation
executes the accepted native Legacy image only in an ephemeral bounded VM to
check its reference result. It never calls a host provider or writes state.

The CI differential includes rejection cases and true native execution. Its
small source programs are compatibility tests, not real application migration
evidence. Repository/source/example searches found no complete existing Legacy
application source; that sample requirement is skipped under the user's stated
instruction. General application migration and a versioned compatibility layer
for the remaining semantics remain unverified.

A new semantic profile is required before correcting Legacy local encoding or
adding operations. Never silently relabel those changes as v1 compatibility.
