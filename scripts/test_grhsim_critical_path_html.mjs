// Optional real-browser integration check: node THIS REPORT.html CHROMIUM OUTPUT_DIR
import {spawn} from 'node:child_process';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const [report, chromium, output] = process.argv.slice(2);
if (!report || !chromium || !output) throw new Error('report, Chromium binary and artifact directory are required');
await mkdir(output, {recursive:true});
const browser=spawn(chromium,['--headless','--no-sandbox','--disable-dev-shm-usage',
    '--remote-debugging-port=0',`--user-data-dir=${path.resolve(output,'profile')}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
let socket;
try {
    const endpoint=await new Promise((resolve,reject)=>{
        let text='';const timer=setTimeout(()=>reject(new Error('browser startup timeout')),20000);
        browser.stderr.on('data',chunk=>{text+=chunk;const m=text.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(m){clearTimeout(timer);resolve(m[1]);}});
        browser.once('exit',code=>{clearTimeout(timer);reject(new Error(`browser exited ${code}`));});
    });
    const address=new URL(endpoint);
    const pages=await fetch(`http://${address.host}/json/list`).then(r=>r.json());
    socket=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
    await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
    let seq=0;const pending=new Map();const errors=[];
    socket.onmessage=event=>{const m=JSON.parse(event.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails);
        if(pending.has(m.id)){const {resolve,reject,timer}=pending.get(m.id);pending.delete(m.id);clearTimeout(timer);m.error?reject(m.error):resolve(m.result);}};
    const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;const timer=setTimeout(()=>reject(new Error('CDP timeout: '+method)),30000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});
    await call('Runtime.enable');await call('Page.enable');
    await call('Emulation.setDeviceMetricsOverride',{width:1360,height:1000,deviceScaleFactor:1,mobile:false});
    await call('Page.navigate',{url:pathToFileURL(path.resolve(report)).href});
    let ready=false;
    for(let i=0;i<120;++i){
        const r=await call('Runtime.evaluate',{expression:'document.querySelectorAll("#batches tr").length',returnByValue:true});
        if(r.result.value>1){ready=true;break;}
        await new Promise(resolve=>setTimeout(resolve,250));
    }
    if(!ready)throw new Error('report did not render');
    const check=await call('Runtime.evaluate',{returnByValue:true,expression:`(()=>{
      const q=s=>document.querySelector(s);
      const rows=()=>[...document.querySelectorAll('#parts tr')].slice(1);
      q('#clock').value='1';q('#clock').dispatchEvent(new Event('change'));
      if(!rows().length||rows().some(r=>r.children[1].textContent!=='1'))throw new Error('clock filter');
      q('#phase').value='update';q('#phase').dispatchEvent(new Event('change'));
      if(!rows().length)throw new Error('update phase');
      const data=JSON.parse(q('#payload').textContent);
      if(!data.dynamic_top1?.rows.length)throw new Error('no dynamic top-1 data');
      q('#dynamic-scope').value='all_sampled';q('#dynamic-scope').dispatchEvent(new Event('change'));
      let dynamicRows=[...document.querySelectorAll('#dynamic-top tr')].slice(1);
      if(dynamicRows.length!==data.dynamic_top1.parts.length*2)throw new Error('missing dynamic partition/clock');
      q('#dynamic-clock').value='1';q('#dynamic-clock').dispatchEvent(new Event('change'));
      dynamicRows=[...document.querySelectorAll('#dynamic-top tr')].slice(1);
      if(dynamicRows.length!==data.dynamic_top1.parts.length||dynamicRows.some(r=>r.dataset.clock!=='1'))throw new Error('dynamic clock filter');
      const mapped=data.dynamic_top1.rows.find(r=>r.scope==='all_sampled'&&r.clock===1&&r.chisel.length&&r.signals.length);
      if(!mapped)throw new Error('no mapped dynamic winner');
      const dynamicRow=document.querySelector('#dynamic-top tr[data-batch="'+mapped.batch_key+'"]');
      if(!dynamicRow)throw new Error('dynamic winner missing from table');dynamicRow.click();
      const details=q('#dynamic-detail').textContent;
      if(!details.includes('.sv:')||!details.includes('.scala:')||!details.includes('重复'))throw new Error('dynamic RTL/Chisel/repeat details');
      if(!details.includes((mapped.ns/1000).toFixed(3)))throw new Error('dynamic scope time not displayed');
      q('#dynamic-scope').value='stable_last';q('#dynamic-scope').dispatchEvent(new Event('change'));
      const missing=data.dynamic_top1.rows.find(r=>r.scope==='stable_last'&&r.clock===1&&!r.batch_key);
      if(missing&&!q('#dynamic-top').textContent.includes(missing.status_label))throw new Error('missing critical evidence not explicit');
      q('#filter').value=data.hotspots[0].batch_key;q('#filter').dispatchEvent(new Event('input'));
      const selected=document.querySelector('#batches tr.pick');if(!selected)throw new Error('batch filter');selected.click();
      if(!q('#batch-detail').textContent.includes('.sv:')||!q('#batch-detail').textContent.includes('ASC'))throw new Error('source expansion');
      const mappedPath=data.paths.find(p=>p.nodes.some(n=>n.source_span_id));
      if(!mappedPath)throw new Error('no mapped static path');
      if(!q('#paths').textContent.includes('clock='+mappedPath.clock)||!q('#paths').textContent.includes('.sv:'))throw new Error('static path');
      return {status:'pass',summary:q('#summary').textContent,runtime:q('#runtime').textContent,
          dynamic:q('#dynamic-summary').textContent,dynamicPreview:details.slice(0,600),sourcePreview:q('#batch-detail').textContent.slice(0,300)};
    })()`});
    if(check.exceptionDetails||errors.length)throw new Error(JSON.stringify(check.exceptionDetails||errors));
    await writeFile(path.join(output,'browser.json'),JSON.stringify(check.result.value,null,2)+'\n');
    await call('Runtime.evaluate',{expression:`document.querySelector('#filter').value='';document.querySelector('#filter').dispatchEvent(new Event('input'));document.querySelector('#phase').value='eval';document.querySelector('#phase').dispatchEvent(new Event('change'));document.querySelector('#clock').value='';document.querySelector('#clock').dispatchEvent(new Event('change'));document.querySelector('#dynamic-clock').value='';document.querySelector('#dynamic-clock').dispatchEvent(new Event('change'));window.scrollTo(0,0)`});
    const screenshot=await call('Page.captureScreenshot',{format:'png'});
    await writeFile(path.join(output,'report.png'),Buffer.from(screenshot.data,'base64'));
    console.log(JSON.stringify(check.result.value));
} finally {
    socket?.close();browser.kill('SIGTERM');
}
