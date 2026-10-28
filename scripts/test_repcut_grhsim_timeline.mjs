#!/usr/bin/env node
// Validate the offline report in a real browser without installing npm packages.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const [browser, htmlArg] = process.argv.slice(2);
assert(browser && htmlArg, 'usage: node test_repcut_grhsim_timeline.mjs BROWSER REPORT.html');
const html = path.resolve(htmlArg), output = path.dirname(html);
const profile = await mkdtemp(path.join(tmpdir(), 'grhsim-timeline-browser-'));
const proc = spawn(browser, ['--no-sandbox', '--disable-gpu', '--remote-debugging-port=0',
  '--user-data-dir='+profile, '--window-size=1780,1250', 'about:blank'], {stdio:['ignore','ignore','pipe']});
let socket;
try {
  const endpoint = await new Promise((resolve,reject)=>{
    let text=''; const timeout=setTimeout(()=>reject(Error('browser start timeout')),30000);
    proc.once('error',reject);
    proc.stderr.on('data',chunk=>{text+=chunk;const match=text.match(/DevTools listening on (ws:\/\/\S+)/);
      if(match){clearTimeout(timeout);resolve(match[1]);}});
    proc.once('exit',code=>{clearTimeout(timeout);reject(Error('browser exited '+code+' '+text));});
  });
  socket=new WebSocket(endpoint);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  const pending=new Map(),errors=[];let seq=0,session;
  socket.onmessage=e=>{const msg=JSON.parse(e.data);if(msg.id){const p=pending.get(msg.id);if(p){pending.delete(msg.id);msg.error?p.reject(Error(JSON.stringify(msg.error))):p.resolve(msg.result);}}
    else if(msg.method==='Runtime.exceptionThrown')errors.push(msg.params.exceptionDetails);};
  async function cdp(method,params={},useSession=true){const id=++seq;return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params,...(useSession&&session?{sessionId:session}:{})}));});}
  const target=await cdp('Target.createTarget',{url:'about:blank'},false);
  session=(await cdp('Target.attachToTarget',{targetId:target.targetId,flatten:true},false)).sessionId;
  await cdp('Page.enable');await cdp('Runtime.enable');
  await cdp('Emulation.setDeviceMetricsOverride',{width:1780,height:1250,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:pathToFileURL(html).href});
  async function evaluate(expression){const r=await cdp('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
  await evaluate(`new Promise((resolve,reject)=>{const start=Date.now();const timer=setInterval(()=>{if(window.REPORT){clearInterval(timer);document.fonts.ready.then(()=>resolve(true));}else if(Date.now()-start>30000){clearInterval(timer);reject(Error('report did not load'));}},50);})`);
  assert.equal(await evaluate('REPORT.data.rows.length'),16);
  assert.equal(await evaluate("document.querySelectorAll('.timeline-row').length"),64);
  assert.equal(await evaluate("document.querySelectorAll('[data-kind=part-input]').length"),64);
  const p24=await evaluate("Number(document.querySelector('.timeline-row[data-arm=candidate][data-part="+'"24"'+"] [data-kind=part-eval]').dataset.value)");
  assert(Math.abs(p24-17.140625)<1e-9);
  assert.match(await evaluate("document.getElementById('cards').textContent"),/11\.071/);
  let checks=0;
  const audit=`(()=>{const nodes=[...document.querySelectorAll('.plot svg *')];for(const n of nodes)for(const k of ['x','y','x1','x2','y1','y2','cx','cy','width','height','r'])if(n.hasAttribute(k)){const s=n.getAttribute(k);if(s.endsWith('%'))continue;const v=Number(s);if(!Number.isFinite(v)||(['width','height','r'].includes(k)&&v<0))throw Error('invalid SVG '+k+'='+s);}const timelines=[...document.querySelectorAll('#timeline-panels svg')];if(timelines.length===2){if(timelines[0].dataset.axisMax!==timelines[1].dataset.axisMax)throw Error('axis mismatch');const ids=n=>[...n.querySelectorAll('.timeline-row')].map(g=>g.dataset.part).join(',');if(ids(timelines[0])!==ids(timelines[1]))throw Error('row order mismatch');}return true;})()`;
  async function set(values){await evaluate(`(()=>{const values=${JSON.stringify(values)};for(const [id,v] of Object.entries(values)){const n=document.getElementById(id);if(typeof v==='boolean')n.checked=v;else n.value=v;}REPORT.render();})()`);assert.equal(await evaluate(audit),true);checks++;}
  for(const aggregation of ['mean','median'])for(const pair of ['all','1','2','3','4','5','6','7','8'])await set({aggregation,pair});
  await set({aggregation:'mean',pair:'all'});
  for(const phase of ['all','input','eval','update'])for(const sort of ['part','eval','update','delta'])await set({'timeline-phase':phase,'timeline-sort':sort});
  for(const zoom of ['1','2','4'])await set({'timeline-zoom':zoom});
  for(const [f,g] of [[true,false],[false,true],[false,false],[true,true]])await set({'show-baseline':f,'show-candidate':g});
  for(const delta of ['raw','delta'])for(let mask=0;mask<8;mask++)for(const shared of [false,true])await set({'part-mode':delta,'part-input':Boolean(mask&1),'part-eval':Boolean(mask&2),'part-update':Boolean(mask&4),'shared-axis':shared});
  for(const key of ['elapsed_s','host_s','eval_us','update_us'])await set({'sample-metric':key});
  for(const sort of ['part','eval','update','delta'])await set({'part-sort':sort});
  await set({samples:false,residual:false});
  await evaluate("document.getElementById('reset').click()");
  const pinned=await evaluate(`(()=>{const n=document.querySelector('[data-kind=part-eval]');n.dispatchEvent(new MouseEvent('click',{bubbles:true}));return document.getElementById('selection').textContent;})()`);
  assert.match(pinned,/µs\/step/);
  const csv=await evaluate('REPORT.csvRows()');
  assert.equal(csv.length,1+2*(8+32*3));
  await cdp('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:output},false);
  await evaluate("document.getElementById('csv').click();document.getElementById('svg').click()");
  // Save a stable SVG independent of browser download completion naming.
  await writeFile(path.join(output,'grhsim_f_g_timeline.svg'),await evaluate('REPORT.timelineSVG()'));
  await cdp('Page.captureScreenshot',{format:'png'}).then(r=>writeFile(path.join(output,'overview.png'),Buffer.from(r.data,'base64')));
  const clip=await evaluate(`(()=>{const r=document.getElementById('timeline-section').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()`);
  await cdp('Page.captureScreenshot',{format:'png',clip,captureBeyondViewport:true}).then(r=>writeFile(path.join(output,'grhsim_f_g_timeline.png'),Buffer.from(r.data,'base64')));
  await cdp('Emulation.setDeviceMetricsOverride',{width:900,height:1200,deviceScaleFactor:1,mobile:false});
  assert.equal(await evaluate("document.documentElement.scrollWidth<=innerWidth+1"),true);
  assert.equal(await evaluate(audit),true);
  await cdp('Page.captureScreenshot',{format:'png'}).then(r=>writeFile(path.join(output,'narrow_view.png'),Buffer.from(r.data,'base64')));
  await new Promise(resolve=>setTimeout(resolve,300));
  const downloaded=await readFile(path.join(output,'grhsim_f_g_current.csv'),'utf8');
  assert.match(downloaded,/"partition"/);
  assert.equal(errors.length,0,JSON.stringify(errors));
  const result={status:'pass',interaction_cases:checks,runs:16,partition_rows:64,
    parallel_input_bars:64,svg_finite:true,shared_axes_and_order:true,csv_download:true,
    svg_export:true,narrow_layout:true,console_exceptions:errors,p24_candidate_mean_us:p24,
    browser,html};
  await writeFile(path.join(output,'browser_validation.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result,null,2));
  await cdp('Browser.close',{},false);
} finally {
  if(socket)socket.close();
  if(proc.exitCode===null)proc.kill('SIGTERM');
}
