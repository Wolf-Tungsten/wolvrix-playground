// Real Chromium regression; no npm dependencies or network assets.
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [report,chromium,output]=process.argv.slice(2);
if(!report||!chromium||!output)throw new Error('report Chromium output_directory are required');
await mkdir(output,{recursive:true});
const browser=spawn(chromium,['--headless','--no-sandbox','--disable-dev-shm-usage','--remote-debugging-port=0',`--user-data-dir=${path.resolve(output,'profile')}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
let socket;
try {
 const endpoint=await new Promise((resolve,reject)=>{let log='';const timer=setTimeout(()=>reject(Error('startup timeout')),20000);browser.stderr.on('data',b=>{log+=b;const m=log.match(/DevTools listening on (ws:\/\/\S+)/);if(m){clearTimeout(timer);resolve(m[1]);}});browser.once('exit',c=>{clearTimeout(timer);reject(Error('browser exited '+c));});});
 const address=new URL(endpoint),pages=await fetch(`http://${address.host}/json/list`).then(r=>r.json());
 socket=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
 let id=0;const pending=new Map(),errors=[];
 socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params);if(pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(m.error):p.resolve(m.result);}};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>reject(Error('CDP timeout '+method)),30000);pending.set(n,{resolve,reject,timer});socket.send(JSON.stringify({id:n,method,params}));});
 await call('Runtime.enable');await call('Page.enable');
 await call('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
 await call('Page.navigate',{url:pathToFileURL(path.resolve(report)).href});
 let ready=false;
 for(let n=0;n<100;++n){const r=await call('Runtime.evaluate',{expression:'document.querySelectorAll("#results tr").length',returnByValue:true});if(r.result.value>0){ready=true;break;}await new Promise(r=>setTimeout(r,100));}
 if(!ready)throw Error('report did not render');
 const checked=await call('Runtime.evaluate',{returnByValue:true,expression:`(()=>{
 const q=s=>document.querySelector(s),rows=()=>document.querySelectorAll('#results tr').length;
 const select=(id,value)=>{q(id).value=value;q(id).dispatchEvent(new Event('change'));};
 if(document.documentElement.lang!=='zh-CN')throw Error('report language');
 const all=Object.values(D.cases),comb=all.filter(c=>!c.stateful),state=all.filter(c=>c.stateful);
 if(rows()!==comb.length)throw Error('default kernel rows');
 for(const mode of ['random','sparse','dense','toggle1','hold99']){
  select('#distribution',mode);const expected=comb[0].summary.find(s=>s.distribution===mode).compute_slice_ns.toFixed(2);
  if(q('#results tr').children[1].textContent!==expected)throw Error('distribution values '+mode);
 }
 select('#scope','state');if(rows()!==state.length)throw Error('state rows');
 select('#scope','eval');if(rows()!==all.length)throw Error('full eval rows');
 q('#query').value='Gray';q('#query').dispatchEvent(new Event('input'));
 if(rows()!==1||!q('#results').textContent.includes('gray_decode32'))throw Error('search');
 q('#results a').click();if(!q('#case-gray_decode32').open)throw Error('source details');
 if(!q('#case-gray_decode32').textContent.includes('逐对计时'))throw Error('source evidence');
 q('#query').value='';q('#query').dispatchEvent(new Event('input'));select('#scope','kernel');select('#distribution','random');
 if(document.querySelectorAll('#patterns details').length!==D.patterns.length)throw Error('catalog coverage');
 if(D.patterns.some(p=>!p.disposition||!p.reviewed_evidence||!p.next_step))throw Error('missing pattern disposition');
 if(!q('#exports').textContent.includes('双实现')||!q('#exports').textContent.includes('模式处置'))throw Error('missing exports');
 if(!D.frozen||document.querySelectorAll('#frozen tr').length!==3)throw Error('frozen example missing');
 if(!D.crc_control||document.querySelectorAll('#crcRows tr').length!==10||q('#crcControl').classList.contains('hidden'))throw Error('CRC control missing');
 window.scrollTo(0,0);
 return {status:'pass',cases:all.length,kernel_cases:comb.length,stateful_cases:state.length,patterns:D.patterns.length,source_files:D.source_files,verified:D.total_verified,crc_control_verified:D.crc_control.verified_vectors};
 })()`});
 if(checked.exceptionDetails||errors.length)throw Error(JSON.stringify(checked.exceptionDetails||errors));
 await writeFile(path.join(output,'browser.json'),JSON.stringify(checked.result.value,null,2)+'\n');
 const shot=await call('Page.captureScreenshot',{format:'png'});await writeFile(path.join(output,'report.png'),Buffer.from(shot.data,'base64'));
 console.log(JSON.stringify(checked.result.value));
}finally{socket?.close();browser.kill('SIGTERM');}
