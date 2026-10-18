"""Explicit node-owner NNS/IBC transaction plans. Never fabricates confirmation."""

def naming_preflight(root,network,params,config):
    if params['expected_revision'] is not None or params['resource']!='naming:'+network or set(params['arguments'])!={'transaction_type','payload'}:
        fail('INVALID_PARAMS','fixed native naming transaction plan required')
    kind=params['arguments']['transaction_type'];payload=params['arguments']['payload']
    allowed={'nns_register','nns_update','nns_transfer','nns_renew','ibc_dispatch','ibc_receive'}
    if kind not in allowed or not isinstance(payload,dict) or len(encoded(payload))>65536:
        fail('INVALID_PARAMS','bounded NNS or naming IBC payload required')
    issuer=corium_identity(root,network)
    def label(value):
        if not isinstance(value,str) or not re.fullmatch('[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?',value):fail('INVALID_PARAMS','suffix-free NNS root required')
    def hex32(value):
        if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):fail('INVALID_PARAMS','exact content or identity digest required')
    def owned(name):
        label(name)
        with closing(corium_db(root,network,'forum/forum.db')) as db:
            record=db.execute('SELECT owner_id FROM nns_records WHERE domain_name=?',(name,)).fetchone()
        if not record or record[0]!=issuer:fail('POLICY_DENIED','this explicit native action requires the configured node to own the NNS root')
    if kind=='nns_register':
        if not {'domain_name','target_hash'}<=set(payload) or set(payload)-{'domain_name','target_hash','proof_of_genesis_contribution','proof_of_contribution'}:
            fail('INVALID_PARAMS','native contribution proof registration required')
        label(payload['domain_name']);hex32(payload['target_hash'])
        if not any(isinstance(payload.get(k),dict) for k in ('proof_of_genesis_contribution','proof_of_contribution')):fail('INVALID_PARAMS','native contribution evidence required; not synthesized by MCP')
        with closing(corium_db(root,network,'forum/forum.db')) as db:
            if db.execute('SELECT 1 FROM nns_records WHERE domain_name=?',(payload['domain_name'],)).fetchone():fail('POLICY_DENIED','registered roots must use owner-authorized updates')
    elif kind=='nns_update':
        if set(payload)!={'records'} or not isinstance(payload['records'],list) or not 1<=len(payload['records'])<=32:fail('INVALID_PARAMS','bounded native NNS updates required')
        seen=set()
        for record in payload['records']:
            if not isinstance(record,dict) or set(record)!={'domain_name','target_hash'}:fail('INVALID_PARAMS','exact NNS update record required')
            owned(record['domain_name']);hex32(record['target_hash'])
            if record['domain_name'] in seen:fail('INVALID_PARAMS','duplicate NNS update')
            seen.add(record['domain_name'])
    elif kind=='nns_transfer':
        if set(payload)!={'domain_name','new_owner_id','contribution_tax'} or not isinstance(payload['contribution_tax'],dict):fail('INVALID_PARAMS','native transfer with contribution evidence required')
        owned(payload['domain_name']);hex32(payload['new_owner_id'])
    elif kind=='nns_renew':
        if set(payload)!={'domain_name'}:fail('INVALID_PARAMS','exact native renewal required')
        owned(payload['domain_name'])
    elif kind=='ibc_dispatch':
        if set(payload)!={'target_chain_id','message_type','message_payload'} or payload['message_type']!='ZIOKT_NAME_BINDING_V1':fail('INVALID_PARAMS','naming-only native IBC dispatch required')
        identifier(payload['target_chain_id'],'destination network')
        binding=payload['message_payload']
        if not isinstance(binding,dict) or set(binding)!={'namespace','root','source_chain_id','epoch','expires_at','record'} or binding['source_chain_id']!=network:fail('INVALID_PARAMS','exact source-bound naming lease required')
        owned(binding['root']);identifier(binding['namespace'],'shared namespace')
        if type(binding['epoch']) is not int or not 1<=binding['epoch']<=2**53-1 or type(binding['expires_at']) is not int or not int(time.time())<binding['expires_at']<=int(time.time())+600:fail('INVALID_PARAMS','bounded monotonic naming lease required')
        if not isinstance(binding['record'],dict) or binding['record'].get('network_id')!=binding['namespace']:fail('INVALID_PARAMS','shared namespace registration required')
    else:
        if set(payload)!={'source_chain_id','payload_and_proof'}:fail('INVALID_PARAMS','exact native IBC receive required')
        identifier(payload['source_chain_id'],'source chain')
        try:proof=strict_json(base64.b64decode(payload['payload_and_proof'],validate=True),65536)
        except (ValueError,TypeError):fail('INVALID_PARAMS','bounded native naming proof required')
        if not isinstance(proof,dict) or proof.get('message_type')!='ZIOKT_NAME_BINDING_V1':fail('INVALID_PARAMS','naming-only IBC receive required')
        with closing(corium_db(root,network,'blockchain/chain.db')) as db:
            if not db.execute('SELECT 1 FROM ibc_verifiers WHERE target_chain_id=? AND is_active=1',(payload['source_chain_id'],)).fetchone():fail('POLICY_DENIED','native governance-approved IBC verifier required')
    return {'transaction_type':kind,'payload':payload,'issuer':issuer}
