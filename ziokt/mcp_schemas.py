"""Discoverable application contracts; native validators remain authoritative."""
S={'type':'string','maxLength':32768}
D={'type':'string','pattern':'^sha256:[a-f0-9]{64}$'}
H={'type':'string','pattern':'^[a-f0-9]{64}$'}
O={'type':'object','maxProperties':64}
A={'type':'array','maxItems':128}
I={'type':'integer','minimum':1,'maximum':100000}
def contract(fields,optional=()):
 return {'type':'object','properties':fields,'required':[k for k in fields if k not in optional],'additionalProperties':False}
BRIDGE={
 'naming.publish':contract({'registration':O}),
 'object.begin':contract({'upload':S,'size':{'type':'integer','minimum':0,'maximum':536870912},'digest':D,'ttl':{'type':'integer','minimum':1,'maximum':86400}}),
 'object.status':contract({'upload':S}), 'object.finish':contract({'upload':S}), 'object.abort':contract({'upload':S}),
 'object.chunk.put':contract({'upload':S,'position':{'type':'integer','minimum':0,'maximum':32767},'digest':D,'data_base64':{'type':'string','maxLength':21848}}),
 'object.reference':contract({'object':D}), 'object.release':contract({'object':D,'upload':S}), 'object.gc':contract({}),
 'object.chunk.get':contract({'object':D,'position':{'type':'integer','minimum':0,'maximum':32767}}),
 'component.status':contract({}), 'component.health':contract({'challenge':{'type':'string','pattern':'^[a-f0-9]{32}$'}}), 'ano.laws':contract({}),
 'ano.calculate':contract({'kind':S,'operation':S,'left':O,'right':O}),
 'ano.defence':contract({'evidence':O,'required':A}), 'ano.evaluate':contract({'circuit':O}),
 'tc16.run':contract({'source':S,'syntax':{'type':'string','enum':['assembly','tcc']},'cycles':I}),
 'vault.put':contract({'name':S,'data_base64':S}), 'vault.get':contract({'digest':D}), 'vault.publish':contract({'digest':D}),
 'tri.put':contract({'program':S,'state':O}), 'tri.get':contract({'digest':D}), 'tri.publish':contract({'digest':D}),
 'package.build.references':contract({'name':S,'version':S,'files':{'type':'object','minProperties':1,'maxProperties':128,'additionalProperties':D},'dependencies':A}),
 'package.release.references':contract({'digest':D,'authority':H}),
 'package.verify.references':contract({'digest':D,'authority':H}),
 'package.build':contract({'name':S,'version':S,'files':O,'dependencies':A}),
 'package.verify':contract({'digest':D,'authority':H}), 'package.publish':contract({'digest':D,'authority':H}),
 'sim.reminders.pull':contract({'user':S}), 'sim.reminders.replace':contract({'user':S,'items':A}),
 'component.send':contract({'target':S,'kind':S,'digest':D,'operation':S}), 'component.receive':contract({'event':D,'source':S}),
 'file.publish':contract({'digest':D}), 'file.read':contract({'digest':D}),
 'safefs.publish':contract({'digest':D}), 'safefs.read':contract({'digest':D}),
 'chat.append':contract({'id':S,'from':S,'to':S,'ciphertext':S,'attachments':A,'attachment_digests':A},('attachment_digests',)),
 'chat.pull':contract({'from':S,'to':S}), 'chat.ack':contract({'from':S,'to':S,'event':D})
}
ETP={
 'etp.health':contract({'challenge':{'type':'string','pattern':'^[a-f0-9]{32}$'}}),
 'etp.mailbox.status':contract({}),
 'etp.mailbox.request':contract({'frame_base64':{'type':'string','maxLength':12000}}),
 'etp.stats':contract({}), 'etp.receive':contract({}),
 'etp.onion.send':contract({'hops':{'type':'array','items':S,'minItems':2,'maxItems':4},'ciphertext':{'type':'string','maxLength':90000}}),
 'etp.forum.identity':contract({'name':S}), 'etp.forum.subscribe':contract({'topic':S}),
 'etp.forum.publish':contract({'topic':S,'content':S,'author':{'type':['string','null']},'parent_id':{'type':['string','null']}},('parent_id',)),
 'etp.forum.get':contract({'id':H})
}
