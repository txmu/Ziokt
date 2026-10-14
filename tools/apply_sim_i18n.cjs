const fs=require('fs'),path=require('path'),ts=require('../companions/sim-manager/src/node_modules/typescript');
const root=path.resolve(__dirname,'../companions/sim-manager/src');
for(const file of [path.join(root,'App.tsx'),...fs.readdirSync(path.join(root,'components')).filter(n=>n.endsWith('.tsx')).map(n=>path.join(root,'components',n))]){
 const source=fs.readFileSync(file,'utf8');if(source.includes("from '../locales'" )||source.includes("from './locales'"))continue;
 const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX),edits=[];
 function visit(node){
  if(ts.isJsxText(node)&&node.text.trim()&&/[\u4e00-\u9fff]/.test(node.text)){const text=node.text.trim().replace(/\s+/g,' ');edits.push([node.pos,node.end,'{t('+JSON.stringify(text)+')}']);}
  else if(ts.isJsxAttribute(node)&&['title','placeholder','aria-label','alt'].includes(node.name.text)&&node.initializer&&ts.isStringLiteral(node.initializer)&&/[\u4e00-\u9fff]/.test(node.initializer.text))edits.push([node.initializer.getStart(ast),node.initializer.end,'{t('+JSON.stringify(node.initializer.text)+')}']);
  ts.forEachChild(node,visit);
 }visit(ast);let changed=source;for(const [start,end,text]of edits.sort((a,b)=>b[0]-a[0]))changed=changed.slice(0,start)+text+changed.slice(end);if(edits.length){changed="import { t"+(file.endsWith('App.tsx')?', useLocale, LocaleMenu':'')+" } from '"+(file.endsWith('App.tsx')?'./locales':'../locales')+"';\n"+changed;if(file.endsWith('App.tsx'))changed=changed.replace('const App: React.FC = () => {','const App: React.FC = () => {\n  useLocale();').replace('{renderThemeElements()}','{renderThemeElements()}\n      <LocaleMenu />');fs.writeFileSync(file,changed)}
}
