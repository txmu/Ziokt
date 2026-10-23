"""Public assurance scope, distinct from live health and deployment identity."""
def snapshot():
    from ._runtime import ZS_MAINNET_ENABLED, ZS_AUDITED, ZS_SELF_REVIEW_REPORT
    return {
        'schema': 'ziokt.assurance-scope.v1',
        'privacy': {'mainnet_feature_enabled': ZS_MAINNET_ENABLED,
                    'independently_audited': ZS_AUDITED,
                    'self_review_report': ZS_SELF_REVIEW_REPORT,
                    'governance_approval': 'not_independently_verified',
                    'complete_cryptographic_proof': False},
        'consensus': {'standalone_target_source': 'branch ancestor timestamps and configured difficulty rules',
                      'standalone_weight_source': 'verified expected target',
                      'native_weight_source': 'active governed work policy schedule',
                      'model_is_native_consensus': False},
        'formal': {'inventory': 'formal/THEOREMS.md', 'gate': 'formal/check_all_formal.sh',
                   'scope': 'conditional models; concrete verifier results and trusted history are premises',
                   'production_refinement_proved': False},
        'history': {'independent_verifier_coverage': 'partial',
                    'full_legacy_and_application_replay_proved': False},
        'survival_experiment': {'scope': 'four local HTTP processes with separate SQLite databases',
                                'public_discovery_tested': False, 'independent_operators_tested': False}
    }
