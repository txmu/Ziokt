import Init

/-! Bounded content acceptance and monotone revisions. This does not prove AEAD,
hashes, filesystem durability, MIME parsers or distributed convergence. -/
namespace Ziokt.Content

-- BEGIN GENERATED VERIFIED GUARDS
abbrev within_budget (budget : Nat) (used : Nat) (amount : Nat) : Prop :=
  ((used + amount) ≤ budget)

abbrev fresh_revision (previous : Nat) (incoming : Nat) : Prop :=
  (previous < incoming)

-- END GENERATED VERIFIED GUARDS

def appendChunk (budget used size : Nat) : Option Nat :=
  if within_budget budget used size then some (used + size) else none

theorem accepted_chunk_conserves_size (budget used size next : Nat)
    (h : appendChunk budget used size = some next) : next = used + size ∧ next ≤ budget := by
  unfold appendChunk within_budget at h
  split at h
  · cases h
    exact ⟨rfl, by assumption⟩
  · cases h

theorem quota_cannot_be_bypassed (budget used size : Nat) (h : budget < used + size) :
    appendChunk budget used size = none := by
  simp [appendChunk, within_budget, Nat.not_le.mpr h]

def rangeAccepted (start length total budget : Nat) : Prop :=
  0 < length ∧ start + length ≤ total ∧ length ≤ budget

theorem accepted_range_stays_in_object (start length total budget : Nat)
    (h : rangeAccepted start length total budget) : start < total := by
  have positive := h.1
  have bounded := h.2.1
  omega

theorem oversized_range_rejected (start length total budget : Nat) (h : budget < length) :
    ¬ rangeAccepted start length total budget := by
  intro accepted
  have bounded := accepted.2.2
  omega

def nextRevision (previous incoming : Nat) : Option Nat :=
  if fresh_revision previous incoming then some incoming else none

theorem old_revision_rejected (old incoming : Nat) (h : incoming ≤ old) :
    nextRevision old incoming = none := by
  simp [nextRevision, fresh_revision, Nat.not_lt.mpr h]

theorem accepted_revision_strictly_increases (old incoming next : Nat)
    (h : nextRevision old incoming = some next) : old < next := by
  unfold nextRevision fresh_revision at h
  split at h
  · cases h
    assumption
  · cases h

def sameScope (objectOwner objectNetwork owner network : Nat) : Prop :=
  objectOwner = owner ∧ objectNetwork = network

theorem cross_owner_object_rejected (objectOwner objectNetwork owner network : Nat)
    (h : objectOwner ≠ owner) : ¬ sameScope objectOwner objectNetwork owner network := by
  intro accepted
  exact h accepted.1

theorem cross_network_object_rejected (objectOwner objectNetwork owner network : Nat)
    (h : objectNetwork ≠ network) : ¬ sameScope objectOwner objectNetwork owner network := by
  intro accepted
  exact h accepted.2

def privateReadable (revoked : Bool) (now expires keyEpoch grantEpoch : Nat) : Prop :=
  revoked = false ∧ now < expires ∧ keyEpoch = grantEpoch

theorem revoked_private_grant_rejected (now expires keyEpoch grantEpoch : Nat) :
    ¬ privateReadable true now expires keyEpoch grantEpoch := by
  simp [privateReadable]

theorem rotated_private_key_requires_new_grant (now expires keyEpoch grantEpoch : Nat)
    (h : keyEpoch ≠ grantEpoch) : ¬ privateReadable false now expires keyEpoch grantEpoch := by
  intro readable
  exact h readable.2.2

theorem expired_private_grant_rejected (now expires keyEpoch grantEpoch : Nat)
    (h : expires ≤ now) : ¬ privateReadable false now expires keyEpoch grantEpoch := by
  intro readable
  exact Nat.not_lt.mpr h readable.2.1

end Ziokt.Content
