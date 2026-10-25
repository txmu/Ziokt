import Init

/-! Direct-route admission after canonical anonymous-name classification. IDNA,
Tor/I2P, TLS, operating systems and traffic analysis are outside this proof. -/
namespace Ziokt.Privacy

-- BEGIN GENERATED VERIFIED GUARDS
abbrev direct_carrier_permitted (anonymous : Bool) : Prop :=
  ¬ (anonymous = true)

abbrev public_publication_permitted (explicit_public : Bool) : Prop :=
  (explicit_public = true)

-- END GENERATED VERIFIED GUARDS

theorem anonymous_destination_never_direct : ¬ direct_carrier_permitted true := by
  simp [direct_carrier_permitted]

theorem direct_admission_requires_nonanonymous (anonymous : Bool)
    (h : direct_carrier_permitted anonymous) : anonymous = false := by
  cases anonymous <;> simp_all [direct_carrier_permitted]

theorem explicit_publication_requires_consent (explicitPublic : Bool)
    (h : public_publication_permitted explicitPublic) : explicitPublic = true := by
  exact h

theorem default_publication_is_private : ¬ public_publication_permitted false := by
  simp [public_publication_permitted]

end Ziokt.Privacy
