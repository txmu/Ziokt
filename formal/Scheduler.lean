import Init

/-! Exact cache context equality and finite worker leases. Hash collision
resistance and atomic SQLite transactions remain implementation assumptions. -/
namespace Ziokt.Scheduler

-- BEGIN GENERATED VERIFIED GUARDS
abbrev within_budget (budget : Nat) (used : Nat) (amount : Nat) : Prop :=
  ((used + amount) ≤ budget)

abbrev before_deadline (now : Nat) (deadline : Nat) : Prop :=
  (now < deadline)

abbrev cache_restores (mode : String) : Prop :=
  ((mode = "read-write") ∨ (mode = "read-only"))

abbrev cache_saves (mode : String) : Prop :=
  ((mode = "read-write") ∨ (mode = "write-only"))

-- END GENERATED VERIFIED GUARDS

structure CacheContext where
  source : Nat
  image : Nat
  architecture : Nat
  command : List Nat
  paths : List Nat
  deriving DecidableEq

def cacheAccepted (expected observed : CacheContext) : Prop := expected = observed

theorem other_source_rejected (a b : CacheContext) (h : a.source ≠ b.source) :
    ¬ cacheAccepted a b := by
  intro equal
  exact h (congrArg CacheContext.source equal)

theorem other_image_rejected (a b : CacheContext) (h : a.image ≠ b.image) :
    ¬ cacheAccepted a b := by
  intro equal
  exact h (congrArg CacheContext.image equal)

theorem other_architecture_rejected (a b : CacheContext) (h : a.architecture ≠ b.architecture) :
    ¬ cacheAccepted a b := by
  intro equal
  exact h (congrArg CacheContext.architecture equal)

theorem other_command_rejected (a b : CacheContext) (h : a.command ≠ b.command) :
    ¬ cacheAccepted a b := by
  intro equal
  exact h (congrArg CacheContext.command equal)

theorem other_paths_rejected (a b : CacheContext) (h : a.paths ≠ b.paths) :
    ¬ cacheAccepted a b := by
  intro equal
  exact h (congrArg CacheContext.paths equal)

inductive CacheMode where
  | readWrite | readOnly | writeOnly
  deriving DecidableEq

def restores : CacheMode → Bool | .writeOnly => false | _ => true
def saves : CacheMode → Bool | .readOnly => false | _ => true

theorem write_only_never_restores : restores .writeOnly = false := rfl
theorem read_only_never_publishes : saves .readOnly = false := rfl

def reserve (budget used requested : Nat) : Option Nat :=
  if within_budget budget used requested then some (used + requested) else none

theorem reservation_preserves_budget (budget used requested next : Nat)
    (accepted : reserve budget used requested = some next) : next ≤ budget := by
  unfold reserve within_budget at accepted
  split at accepted
  · cases accepted
    assumption
  · cases accepted

theorem overbooking_rejected (budget used requested : Nat)
    (over : budget < used + requested) : reserve budget used requested = none := by
  simp [reserve, within_budget, Nat.not_le.mpr over]

def receiptAccepted (leaseEpoch currentEpoch deadline now : Nat) : Prop :=
  leaseEpoch = currentEpoch ∧ before_deadline now deadline

theorem old_lease_rejected (old current deadline now : Nat) (h : old ≠ current) :
    ¬ receiptAccepted old current deadline now := by
  intro accepted
  exact h accepted.1

theorem expired_lease_rejected (epoch deadline now : Nat) (h : deadline ≤ now) :
    ¬ receiptAccepted epoch epoch deadline now := by
  intro accepted
  have valid := accepted.2
  unfold before_deadline at valid
  omega

theorem generated_write_only_never_restores : ¬ cache_restores "write-only" := by decide
theorem generated_read_only_never_saves : ¬ cache_saves "read-only" := by decide

end Ziokt.Scheduler
