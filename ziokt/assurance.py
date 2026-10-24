"""Public assurance scope, distinct from live health and deployment identity."""
def public_hold(config):
    """Expose an allowlist; private backup/configuration paths never leave the host."""
    from .protocol import secure_read, strict_json
    path=config.get('consensus_safety_hold')
    if not path:
        return None
    value=strict_json(secure_read(path,8192),8192)
    if (type(value) is not dict or value.get('schema')!='ziokt.consensus-safety-hold.v1'
            or type(value.get('active')) is not bool):
        raise ValueError('Invalid consensus safety hold; cannot infer healthy consensus')
    return {key:value[key] for key in ('schema','active','at','reason_code','first_unverified_height','history_rewritten') if key in value}


def snapshot(hold=None):
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
                      'model_is_native_consensus': False,
                      'operational_state': 'safety_hold' if hold and hold.get('active') else 'not_assessed',
                      'safety_hold': hold},
        'formal': {'inventory': 'formal/THEOREMS.md', 'gate': 'formal/check_all_formal.sh',
                   'scope': 'conditional models; concrete verifier results and trusted history are premises',
                   'production_refinement_proved': False},
        'history': {'independent_verifier_coverage': 'partial',
                    'full_legacy_and_application_replay_proved': False},
        'survival_experiment': {'scope': 'four local HTTP processes with separate SQLite databases',
                                'native_transport': 'three native TLS handler processes: signed STORE, known-block announcements and survivor exchange',
                                'new_native_branch_acceptance_proved': False,
                                'public_discovery_tested': False, 'independent_operators_tested': False}
    }
