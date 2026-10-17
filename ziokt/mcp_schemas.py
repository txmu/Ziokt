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
 'component.status':contract({}), 'ano.laws':contract({}),
 'ano.calculate':contract({'kind':S,'operation':S,'left':O,'right':O}),
 'ano.defence':contract({'evidence':O,'required':A}), 'ano.evaluate':contract({'circuit':O}),
 'tc16.run':contract({'source':S,'syntax':{'type':'string','enum':['assembly','tcc']},'cycles':I}),
 'vault.put':contract({'name':S,'data_base64':S}), 'vault.get':contract({'digest':D}), 'vault.publish':contract({'digest':D}),
 'tri.put':contract({'program':S,'state':O}), 'tri.get':contract({'digest':D}), 'tri.publish':contract({'digest':D}),
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
 'etp.stats':contract({}), 'etp.receive':contract({}),
 'etp.onion.send':contract({'hops':{'type':'array','items':S,'minItems':2,'maxItems':4},'ciphertext':{'type':'string','maxLength':90000}}),
 'etp.forum.identity':contract({'name':S}), 'etp.forum.subscribe':contract({'topic':S}),
 'etp.forum.publish':contract({'topic':S,'content':S,'author':{'type':['string','null']},'parent_id':{'type':['string','null']}},('parent_id',)),
 'etp.forum.get':contract({'id':H})
}
