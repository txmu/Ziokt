import Init

/-! Abstract F2F admission and acceptance boundaries. Native RetroShare, SHA,
TLS, operating systems and network liveness are outside these proofs. Source
hash correspondence is manually reviewed, not full implementation refinement. -/
namespace Ziokt.RetroShare

def requestAllowed (configured isScoped allowlisted nativeFriend bounded : Prop) : Prop :=
  configured ∧ isScoped ∧ allowlisted ∧ nativeFriend ∧ bounded

def bytesAccepted (complete exactSize sha256Matches nativeHashMatches : Prop) : Prop :=
  complete ∧ exactSize ∧ sha256Matches ∧ nativeHashMatches

theorem request_requires_configuration (c s a f b : Prop)
    (h : requestAllowed c s a f b) : c := h.1

theorem request_requires_scope (c s a f b : Prop)
    (h : requestAllowed c s a f b) : s := h.2.1

theorem request_requires_allowlist (c s a f b : Prop)
    (h : requestAllowed c s a f b) : a := h.2.2.1

theorem request_requires_native_friend (c s a f b : Prop)
    (h : requestAllowed c s a f b) : f := h.2.2.2.1

theorem incomplete_transfer_not_accepted (size sha native : Prop) :
    ¬ bytesAccepted False size sha native := by
  intro h
  exact h.1

theorem acceptance_requires_sha256 (complete size sha native : Prop)
    (h : bytesAccepted complete size sha native) : sha := h.2.2.1

theorem native_hash_alone_is_insufficient : ¬ bytesAccepted True True False True := by
  intro h
  exact h.2.2.1

theorem wrong_size_not_accepted (complete sha native : Prop) :
    ¬ bytesAccepted complete False sha native := by
  intro h
  exact h.2.1

end Ziokt.RetroShare
