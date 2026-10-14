"""Presentation-only locale messages; signed protocol identifiers never translate."""
LOCALES=('en','zh-CN')
MESSAGES={
 'en':{'tc16.compiled':'TC-16 program assembled','tc16.executed':'TC-16 execution finished','package.saved':'Signed package saved in encrypted UFS','package.verified':'Package signature and all file hashes verified','safefs.saved':'Encrypted file saved','safefs.opened':'Authenticated file restored','safefs.shared':'Encrypted file published to the federation',
       'ano.allow':'All required claims passed','ano.deny':'A required claim failed','ano.hold':'Evidence is incomplete',
       'SAFEFS_AUTH_FAILED':'File authentication or scope rejected','SAFEFS_LIMIT':'File exceeds the safe budget','INVALID_ANO':'Invalid typed Ano operation'},
 'zh-CN':{'tc16.compiled':'TC-16 程序已汇编','tc16.executed':'TC-16 执行已完成','package.saved':'签名软件包已保存至加密 UFS','package.verified':'软件包签名和全部文件哈希已核验','safefs.saved':'加密文件已保存','safefs.opened':'已恢复通过认证的文件','safefs.shared':'密文文件已发布至联邦',
       'ano.allow':'所需证据全部通过','ano.deny':'所需证据未通过','ano.hold':'证据尚不完整',
       'SAFEFS_AUTH_FAILED':'文件认证或作用域不匹配','SAFEFS_LIMIT':'文件超过安全预算','INVALID_ANO':'Ano 运算类型无效'}
}

def translate(key,locale='en'):
    if locale not in LOCALES:raise ValueError('unsupported locale')
    return MESSAGES[locale].get(key,MESSAGES['en'].get(key,key))
