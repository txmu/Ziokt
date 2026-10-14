import React,{useEffect,useState} from 'react';
import english from './en.json';
export type Locale='en'|'zh-CN';
export function t(text:string):string {
 const locale=document.documentElement.lang;
 if(locale==='zh-CN')return text;
 return (english as Record<string,string>)[text]??text;
}
export function setLocale(locale:Locale):void{document.documentElement.lang=locale;localStorage.setItem('ziokt.sim.locale',locale);window.dispatchEvent(new Event('ziokt-locale'))}
export function useLocale():Locale{const [locale,set]=useState<Locale>((localStorage.getItem('ziokt.sim.locale') as Locale)||'en');useEffect(()=>{const update=()=>set(document.documentElement.lang as Locale);setLocale(locale);window.addEventListener('ziokt-locale',update);return()=>window.removeEventListener('ziokt-locale',update)},[]);return locale}
export function LocaleMenu(){return <label>Language / 语言 <select aria-label="Language / 语言" value={document.documentElement.lang} onChange={event=>setLocale(event.target.value as Locale)}><option value="en">English</option><option value="zh-CN">简体中文</option></select></label>}
