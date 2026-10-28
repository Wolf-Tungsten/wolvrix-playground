#!/usr/bin/env node
// Real-browser, offline checks. No npm package or web server is required.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const [browser,htmlArg]=process.argv.slice(2);
assert(browser&&htmlArg,'usage: node test_repcut_grhsim_cycle_view.mjs BROWSER REPORT.html');
const html=path.resolve(htmlArg),out=path.dirname(html);
const profile=await mkdtemp(path.join(tmpdir(),'grhsim-cycle-browser-'));
const proc=spawn(browser,['--no-sandbox','--disable-gpu','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
let socket;
try{
 const endpoint=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(Error('browser start timeout')),30000);
  proc.once('error',reject);proc.stderr.on('data',chunk=>{text+=chunk;const match=text.match(/DevTools listening on (ws:\/\/\S+)/);if(match){clearTimeout(timer);resolve(match[1]);}});
  proc.once('exit',code=>{clearTimeout(timer);reject(Error('browser exited '+code+' '+text));});});
 socket=new WebSocket(endpoint);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
 const pending=new Map(),errors=[],network=[];let sequence=0,session,checks=0;
 socket.onmessage=e=>{const msg=JSON.parse(e.data);if(msg.id){const p=pending.get(msg.id);if(p){pending.delete(msg.id);msg.error?p.reject(Error(JSON.stringify(msg.error))):p.resolve(msg.result);}}
  else if(msg.method==='Runtime.exceptionThrown')errors.push(msg.params.exceptionDetails);
  else if(msg.method==='Network.requestWillBeSent'&&/^https?:/.test(msg.params.request.url))network.push(msg.params.request.url);};
 async function cdp(method,params={},useSession=true){const id=++sequence;return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params,...(useSession&&session?{sessionId:session}:{})}));});}
 const target=await cdp('Target.createTarget',{url:'about:blank'},false);session=(await cdp('Target.attachToTarget',{targetId:target.targetId,flatten:true},false)).sessionId;
 await cdp('Page.enable');await cdp('Runtime.enable');await cdp('Network.enable');
 await cdp('Emulation.setDeviceMetricsOverride',{width:1780,height:1150,deviceScaleFactor:1,mobile:false});
 await cdp('Page.navigate',{url:pathToFileURL(html).href});
 async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
 await evaluate(`new Promise((resolve,reject)=>{const start=Date.now(),timer=setInterval(()=>{if(window.REPORT?.ready){clearInterval(timer);document.fonts.ready.then(()=>resolve(true));}else if(window.REPORT?.error||Date.now()-start>60000){clearInterval(timer);reject(Error(window.REPORT?.error||'load timeout'));}},50);})`);
 assert.equal(await evaluate('REPORT.data.cycles'),100001);
 assert.equal(await evaluate("document.querySelectorAll('.bar').length"),32);
 const expected=JSON.parse(await readFile(path.join(out,'spot_checks.json'),'utf8'));
 for(const sample of expected){const actual=await evaluate(`REPORT.cycleRows(${sample.cycle},${sample.pair},${JSON.stringify(sample.variant)},${JSON.stringify(sample.edge)})`);
  assert.equal(actual.length,1);for(const key of ['parts','globals','steps'])assert.deepEqual(actual[0][key],sample[key],JSON.stringify({cycle:sample.cycle,pair:sample.pair,variant:sample.variant,edge:sample.edge,key}));checks++;}
 const audit=`(()=>{for(const n of document.querySelectorAll('.plot svg *'))for(const k of ['x','y','width','height','x1','x2','y1','y2'])if(n.hasAttribute(k)){const v=Number(n.getAttribute(k));if(!Number.isFinite(v)||(['width','height'].includes(k)&&v<0))throw Error('invalid SVG geometry');}return true;})()`;
 async function set(values){await evaluate(`(async()=>{for(const [id,v] of Object.entries(${JSON.stringify(values)})){const n=document.getElementById(id);if(typeof v==='boolean')n.checked=v;else n.value=v;}await REPORT.render();return true;})()`);assert.equal(await evaluate(audit),true);checks++;}
 for(const pair of [1,2])for(const edge of ['rise','fall','both'])for(const variant of ['baseline','candidate','both'])await set({pair,edge,variant});
 for(let mask=0;mask<8;mask++)await set({input:Boolean(mask&1),eval:Boolean(mask&2),update:Boolean(mask&4)});
 for(const sort of ['part','selected','eval','update'])for(const zoom of [1,1.5,2])await set({sort,zoom});
 for(const cycle of [-5,0,1.8,100001,999999]){await set({cycle});assert.equal(await evaluate('REPORT.state.cycle'),Math.min(100001,Math.max(1,Math.trunc(cycle))));}
 await set({cycle:256,edge:'rise',pair:1,variant:'candidate',input:true,eval:true,update:true,sort:'part',zoom:1});
 await evaluate(`document.getElementById('next').click();new Promise(resolve=>setTimeout(resolve,250))`);assert.equal(await evaluate('REPORT.state.cycle'),257);
 await evaluate(`document.getElementById('previous').click();new Promise(resolve=>setTimeout(resolve,250))`);assert.equal(await evaluate('REPORT.state.cycle'),256);
 await evaluate(`document.getElementById('slider').value=50001;document.getElementById('slider').dispatchEvent(new Event('input'));new Promise(resolve=>setTimeout(resolve,250))`);assert.equal(await evaluate('REPORT.state.cycle'),50001);
 await evaluate(`document.querySelector('.bar').dispatchEvent(new MouseEvent('click',{bubbles:true}));`);assert.match(await evaluate("document.getElementById('selection').textContent"),/cycle 50001/);
 // Competing asynchronous block loads must not replace the latest selection.
 await evaluate(`(async()=>{const jobs=[];for(const c of [1,50001,100001]){document.getElementById('cycle').value=c;jobs.push(REPORT.render());}await Promise.all(jobs);})()`);assert.equal(await evaluate('REPORT.state.cycle'),100001);
 await set({cycle:100000,pair:1,edge:'rise',variant:'both'});
 const csv=await evaluate('REPORT.csvRows()');assert.equal(csv.length,65);assert.equal(csv[1].length,15);assert.equal(csv[1][0],100000);
 const golden=expected.find(s=>s.cycle===100000&&s.pair===1&&s.edge==='rise'&&s.variant==='baseline');assert.deepEqual(csv[1].slice(7,10),golden.parts[0]);
 await cdp('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:out},false);await evaluate("document.getElementById('csv').click();document.getElementById('svg').click()");
 await writeFile(path.join(out,'grhsim_cycle_histogram.svg'),await evaluate('REPORT.chartSVG()'));
 await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:true}).then(r=>writeFile(path.join(out,'cycle_overview.png'),Buffer.from(r.data,'base64')));
 const clip=await evaluate(`(()=>{const r=document.getElementById('histogram-section').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()`);
 await cdp('Page.captureScreenshot',{format:'png',clip,captureBeyondViewport:true}).then(r=>writeFile(path.join(out,'grhsim_cycle_histogram.png'),Buffer.from(r.data,'base64')));
 await cdp('Emulation.setDeviceMetricsOverride',{width:900,height:1100,deviceScaleFactor:1,mobile:false});assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth+1'),true);
 await cdp('Page.captureScreenshot',{format:'png'}).then(r=>writeFile(path.join(out,'cycle_narrow.png'),Buffer.from(r.data,'base64')));
 await evaluate("document.getElementById('reset').click();new Promise(resolve=>setTimeout(resolve,250))");assert.equal(await evaluate("document.querySelectorAll('.bar').length"),32);assert.equal(await evaluate('REPORT.state.cycle'),100000);
 assert.deepEqual(errors,[]);assert.deepEqual(network,[]);
 await writeFile(path.join(out,'browser_validation.json'),JSON.stringify({status:'pass',checks,raw_trace_spot_checks:expected.length,offline_network_requests:network,browser_errors:errors,browser:await cdp('Browser.getVersion',{},false)},null,2)+'\n');
 console.log(JSON.stringify({status:'pass',checks,raw_trace_spot_checks:expected.length,output:out}));
}finally{if(socket)socket.close();proc.kill('SIGTERM');}
