import Init

namespace Ziokt.Distribution

-- BEGIN GENERATED VERIFIED GUARDS
abbrev target_matches (expected : String) (actual : String) : Prop :=
  (expected = actual)

abbrev package_member_admitted (expected : Nat) (actual : Nat) (digest : Bool) : Prop :=
  ((expected = actual) ∧ (digest = true))

-- END GENERATED VERIFIED GUARDS

theorem accepted_program_has_requested_backend (expected actual : String)
    (h : target_matches expected actual) : expected = actual := h

theorem backend_mismatch_rejected (expected actual : String)
    (h : expected ≠ actual) : ¬ target_matches expected actual := h

theorem admitted_member_has_declared_size (expected actual : Nat) (digest : Bool)
    (h : package_member_admitted expected actual digest) : expected = actual := h.1

theorem admitted_member_has_verified_digest (expected actual : Nat) (digest : Bool)
    (h : package_member_admitted expected actual digest) : digest = true := h.2

theorem changed_member_digest_rejected (expected actual : Nat) :
    ¬ package_member_admitted expected actual false := by
  simp [package_member_admitted]

theorem changed_member_size_rejected (expected actual : Nat) (digest : Bool)
    (h : expected ≠ actual) : ¬ package_member_admitted expected actual digest := by
  simp [package_member_admitted, h]

end Ziokt.Distribution
