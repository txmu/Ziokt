import Init

namespace Ziokt.Browsers

-- BEGIN GENERATED VERIFIED GUARDS
abbrev detail_permitted (requested : Bool) (granted : Bool) : Prop :=
  (¬ (requested = true) ∨ (granted = true))

abbrev same_chain_domain (expected : String) (observed : String) : Prop :=
  (expected = observed)

abbrev different_chain_sources (primary : String) (dna : String) : Prop :=
  ¬ (primary = dna)

-- END GENERATED VERIFIED GUARDS

theorem private_detail_requires_grant (granted : Bool)
    (h : detail_permitted true granted) : granted = true := by
  simpa [detail_permitted] using h

theorem ungranted_detail_rejected : ¬ detail_permitted true false := by
  simp [detail_permitted]

theorem minimal_view_does_not_request_details (granted : Bool) : detail_permitted false granted := by
  simp [detail_permitted]

theorem accepted_chain_has_expected_genesis (expected observed : String)
    (h : same_chain_domain expected observed) : expected = observed := h

theorem crossed_chain_domain_rejected (expected observed : String)
    (h : expected ≠ observed) : ¬ same_chain_domain expected observed := h

theorem primary_and_dna_sources_distinct (primary dna : String)
    (h : different_chain_sources primary dna) : primary ≠ dna := h

theorem duplicate_chain_source_rejected (source : String) : ¬ different_chain_sources source source := by
  simp [different_chain_sources]

end Ziokt.Browsers
