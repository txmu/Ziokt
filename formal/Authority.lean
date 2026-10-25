import Init

/-! Abstract authorization algebra. Cryptographic verification, parsers and
operating-system isolation are external premises, not proved by this model. -/
namespace Ziokt.Authority

-- BEGIN GENERATED VERIFIED GUARDS
abbrev before_deadline (now : Nat) (deadline : Nat) : Prop :=
  (now < deadline)

-- END GENERATED VERIFIED GUARDS

def allowed (build grant policy domain : Nat → Prop) (cap : Nat) : Prop :=
  build cap ∧ grant cap ∧ policy cap ∧ domain cap

theorem no_build_privilege (b g p d : Nat → Prop) (c : Nat)
    (missing : ¬ b c) : ¬ allowed b g p d c := by
  intro accepted
  exact missing accepted.1

theorem no_grant_privilege (b g p d : Nat → Prop) (c : Nat)
    (missing : ¬ g c) : ¬ allowed b g p d c := by
  intro accepted
  exact missing accepted.2.1

theorem policy_restriction_monotone (b g p q d : Nat → Prop)
    (restricts : ∀ c, q c → p c) (c : Nat) (h : allowed b g q d c) :
    allowed b g p d c := by
  exact ⟨h.1, h.2.1, restricts c h.2.2.1, h.2.2.2⟩

structure Grant where
  audience : Nat
  network : Nat
  epoch : Nat
  expires : Nat
  deriving DecidableEq

def current (g : Grant) (audience network epoch now : Nat) : Prop :=
  g.audience = audience ∧ g.network = network ∧ epoch ≤ g.epoch ∧ now < g.expires

theorem wrong_network_rejected (g : Grant) (audience network epoch now : Nat)
    (wrong : g.network ≠ network) : ¬ current g audience network epoch now := by
  intro h
  exact wrong h.2.1

theorem revoked_epoch_rejected (g : Grant) (audience network epoch now : Nat)
    (old : g.epoch < epoch) : ¬ current g audience network epoch now := by
  intro h
  have valid := h.2.2.1
  omega

theorem expired_grant_rejected (g : Grant) (audience network epoch now : Nat)
    (expired : g.expires ≤ now) : ¬ current g audience network epoch now := by
  intro h
  have valid := h.2.2.2
  omega

def consume (nonce : Nat) (used : List Nat) : Option (List Nat) :=
  if nonce ∈ used then none else some (nonce :: used)

theorem consumed_nonce_cannot_replay (nonce : Nat) (used : List Nat) :
    consume nonce (nonce :: used) = none := by
  simp [consume]

theorem accepted_nonce_is_recorded (nonce : Nat) (used next : List Nat)
    (accepted : consume nonce used = some next) : nonce ∈ next := by
  unfold consume at accepted
  split at accepted
  · cases accepted
  · cases accepted
    simp

end Ziokt.Authority
