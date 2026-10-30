"""Owner-configured primary/DNA pairs, with bounded read-only observations."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlencode, urlsplit

from . import dna_protocol as dna
from .explorer import ChainExplorer, HEX
from .protocol import ProtocolError
from ._verified_guards import different_chain_sources,same_chain_domain

PROTOCOL='ziokt.dna-explorer.v1'
ROLES=('primary','dna')
IDENTIFIER=re.compile('[A-Za-z0-9_-]{1,64}\\Z')


@contextmanager
def readonly(path):
    path=Path(path)
    if not path.is_absolute() or path.resolve()!=path or not path.is_file():
        raise ProtocolError('CHAIN_UNAVAILABLE','regular local observation database required')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
        ticks=[0]
        def budget():
            ticks[0]+=1
            return ticks[0]>1000
        db.set_progress_handler(budget,1000);db.execute('BEGIN')
        yield db
    except sqlite3.Error as error:
        raise ProtocolError('CHAIN_UNAVAILABLE','observation query exceeded its budget or failed') from error
    finally:db.close()


class ExplorerNetworks:
    def __init__(self,state_root,network,profiles=()):
        if not isinstance(profiles,(list,tuple)) or len(profiles)>16:
            raise ProtocolError('INVALID_CONFIG','at most sixteen explorer networks required')
        self.networks={'main':{'id':'main','name':network,'protocol':PROTOCOL,
                             'primary':{'state_root':str(state_root),'network_id':network}}}
        configured=set()
        for profile in profiles:
            if (not isinstance(profile,dict) or not {'id','name','protocol','primary','dna'}<=set(profile)
                    or set(profile)-{'id','name','protocol','primary','dna','business_chain'} or profile['protocol']!=PROTOCOL
                    or not isinstance(profile['id'],str) or not IDENTIFIER.fullmatch(profile['id'])
                    or not isinstance(profile['name'],str) or not 1<=len(profile['name'])<=80):
                raise ProtocolError('INVALID_CONFIG','exact DNA explorer network descriptor required')
            if profile.get('business_chain','primary') not in ROLES:raise ProtocolError('INVALID_CONFIG','primary or DNA business chain required')
            if profile['id'] in configured:
                raise ProtocolError('INVALID_CONFIG','duplicate explorer network')
            configured.add(profile['id'])
            for role in ROLES:
                value=profile[role]
                if (not isinstance(value,dict) or not {'state_root','network_id','genesis_hash'}<=set(value)
                        or set(value)-{'state_root','network_id','genesis_hash','protocol_db','chain_id','policy_id'}
                        or not isinstance(value['network_id'],str) or not IDENTIFIER.fullmatch(value['network_id'])
                        or not isinstance(value['state_root'],str) or not Path(value['state_root']).is_absolute()
                        or not isinstance(value['genesis_hash'],str) or not HEX.fullmatch(value['genesis_hash'])):
                    raise ProtocolError('INVALID_CONFIG','exact pinned local chain descriptor required')
                if 'protocol_db' in value:
                    if (not isinstance(value['protocol_db'],str) or not Path(value['protocol_db']).is_absolute()
                            or any(not isinstance(value.get(key),str) or not HEX.fullmatch(value[key]) for key in ('chain_id','policy_id'))):
                        raise ProtocolError('INVALID_CONFIG','RNA database requires pinned chain and policy domains')
            left,right=profile['primary'],profile['dna']
            if not different_chain_sources(str(Path(left['state_root']).resolve())+'/'+left['network_id'],str(Path(right['state_root']).resolve())+'/'+right['network_id']):
                raise ProtocolError('INVALID_CONFIG','primary and DNA must be independent chain databases')
            self.networks[profile['id']]=profile

    def catalog(self):
        return {'schema':PROTOCOL,'default_network':'main','default_chain':self.networks['main'].get('business_chain','primary'),
                'dna_encoding':'corium.dna.duplex.v1','rna_protocol':'corium.rna.v1',
                'networks':[{'id':p['id'],'name':p['name'],'protocol':PROTOCOL,'business_chain':p.get('business_chain','primary'),
                             'chains':{role:{'network_id':p[role]['network_id'],
                                             'genesis_hash':p[role].get('genesis_hash'),
                                             'configured':True} if role in p else {'configured':False}
                                       for role in ROLES}}
                            for p in self.networks.values()]}

    def select(self,profile,role):
        if profile not in self.networks or role not in ROLES:
            raise ProtocolError('NOT_FOUND','configured explorer network and chain required')
        descriptor=self.networks[profile].get(role)
        if descriptor is None:raise ProtocolError('CHAIN_UNAVAILABLE','DNA sidechain is not configured for this network')
        try:return ChainExplorer(descriptor['state_root'],descriptor['network_id'],descriptor.get('genesis_hash')),descriptor
        except OSError as error:raise ProtocolError('CHAIN_UNAVAILABLE','configured chain database is unavailable') from error

    def query(self,url):
        if not isinstance(url,str) or len(url)>2048:raise ProtocolError('INVALID_REQUEST','bounded explorer path required')
        route=urlsplit(url);args=parse_qs(route.query,keep_blank_values=True)
        if route.scheme or route.netloc or route.fragment or any(len(v)!=1 for v in args.values()):
            raise ProtocolError('INVALID_REQUEST','exact local explorer query required')
        if route.path=='/api/explorer/networks':
            if args:raise ProtocolError('INVALID_REQUEST','catalog takes no query arguments')
            return self.catalog()
        profile=args.pop('network',['main'])[0];role=args.pop('chain',[self.networks.get(profile,{}).get('business_chain','primary')])[0]
        if profile not in self.networks or role not in ROLES:raise ProtocolError('NOT_FOUND','configured network and chain required')
        if route.path=='/api/explorer/duplex':
            if args:raise ProtocolError('INVALID_REQUEST','duplex takes only network and chain selectors')
            result={'schema':'ziokt.explorer-duplex.v1','network':profile,'protocol':PROTOCOL,'chains':{}}
            for selected in ROLES:
                try:
                    reader,_=self.select(profile,selected)
                    result['chains'][selected]={'state':'available',**reader.query('/api/explorer/summary')}
                except ProtocolError as error:
                    result['chains'][selected]={'state':'unavailable' if selected in self.networks[profile] else 'not-configured','error':error.code}
            return result
        reader,descriptor=self.select(profile,role)
        if route.path=='/api/explorer/dna':result=self.encoding(reader,args)
        elif route.path=='/api/explorer/rna':
            if args:raise ProtocolError('INVALID_REQUEST','RNA takes only network and chain selectors')
            result=self.rna(reader,descriptor)
        else:result=reader.query(route.path+('?' +urlencode(args,doseq=True) if args else ''))
        return {**result,'explorer_network':profile,'chain_role':role,'explorer_protocol':PROTOCOL}

    @staticmethod
    def encoding(reader,args):
        if set(args)-{'height'}:raise ProtocolError('INVALID_REQUEST','DNA accepts only a block height')
        height=args.get('height',[None])[0]
        if height is not None and (not height.isascii() or not height.isdecimal() or len(height)>16 or int(height)>=2**53):
            raise ProtocolError('INVALID_REQUEST','bounded DNA block height required')
        summary=reader.query('/api/explorer/summary')
        with readonly(reader.path) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='block_work'").fetchone():
                return {**summary,'encoding':None,'state':'no-dna-proof'}
            row=db.execute('SELECT b.height,b.hash,length(w.proof),substr(w.proof,1,65537) FROM blocks b JOIN block_work w ON w.hash=b.hash WHERE b.height=?',
                           (summary['tip_height'] if height is None else int(height),)).fetchone()
            if row is None:return {**summary,'encoding':None,'state':'no-dna-proof'}
            if row[2]>65536:raise ProtocolError('CHAIN_UNAVAILABLE','stored DNA proof exceeds byte budget')
            proof=dna.loads(row[3]);gene=proof.get('dna') if isinstance(proof,dict) else None
            if gene is None:return {**summary,'height':row[0],'block_hash':row[1],'encoding':None,'state':'no-dna-proof'}
            try:dna.restore(gene,gene['root'])
            except (ValueError,KeyError,TypeError) as error:raise ProtocolError('CHAIN_UNAVAILABLE','stored DNA strands are inconsistent') from error
            return {**summary,'height':row[0],'block_hash':row[1],'state':'available','encoding':gene,
                    'strand_consistency_verified':True,'proof_source':'canonical-block-work',
                    'independent_consensus_verification':False}

    @staticmethod
    def rna(reader,descriptor):
        summary=reader.query('/api/explorer/summary')
        if 'protocol_db' not in descriptor:return {**summary,'state':'not-configured','flows':[]}
        flows=[]
        with readonly(descriptor['protocol_db']) as db:
            rows=db.execute('SELECT substr(domain,1,256),length(document),substr(document,1,65537) FROM records ORDER BY domain LIMIT 33').fetchall()
            for domain,size,raw in rows[:32]:
                if size>65536:raise ProtocolError('CHAIN_UNAVAILABLE','RNA record exceeds byte budget')
                value=dna.loads(raw);frame=value.get('frame',{});header=frame.get('header',{})
                if (not isinstance(header.get('chain'),str) or not isinstance(header.get('policy'),str)
                        or not same_chain_domain(descriptor['chain_id'],header['chain'])
                        or not same_chain_domain(descriptor['policy_id'],header['policy'])):continue
                try:
                    dna.rna_open(frame,value['pem'],descriptor['chain_id'],descriptor['policy_id'],header['sender'],0,header['issued_at'])
                except (ValueError,KeyError,TypeError) as error:raise ProtocolError('CHAIN_UNAVAILABLE','RNA signature or payload binding failed') from error
                flows.append({'domain':domain,**header,'signature_verified_at_issue_time':True,
                              'current_record':True,'payload_disclosed':False})
        return {**summary,'state':'available','flows':flows,'truncated':len(rows)>32,
                'source':'persisted-current-protocol-records','view':'RNA flow observations'}
