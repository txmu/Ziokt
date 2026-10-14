const fs=require('fs'),path=require('path');const ts=require('../companions/sim-manager/src/node_modules/typescript');
const root=path.resolve(__dirname,'../companions/sim-manager/src');const strings=new Set();
for(const file of [path.join(root,'App.tsx'),...fs.readdirSync(path.join(root,'components')).filter(n=>n.endsWith('.tsx')).map(n=>path.join(root,'components',n))]){
 const source=fs.readFileSync(file,'utf8'),ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 function visit(node){if(ts.isJsxText(node)&&node.text.trim()&&/[\u4e00-\u9fff]/.test(node.text))strings.add(node.text.trim().replace(/\s+/g,' '));else if(ts.isJsxAttribute(node)&&['title','placeholder','aria-label','alt'].includes(node.name.text)&&node.initializer&&ts.isStringLiteral(node.initializer)&&/[\u4e00-\u9fff]/.test(node.initializer.text))strings.add(node.initializer.text);ts.forEachChild(node,visit)}visit(ast)
}
fs.writeFileSync(path.resolve(__dirname,'../.runtime/sim-i18n-strings.json'),JSON.stringify([...strings],null,2));console.log('Presentation strings:',strings.size);console.log([...strings].slice(0,100).join('\n'));
