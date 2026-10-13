const { chromium } = require('playwright');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve('frontend');
const server = http.createServer((req,res) => {
 const file = path.join(root,req.url === '/' ? 'index.html' : req.url.split('?')[0]);
 if(!file.startsWith(root+path.sep)) return res.writeHead(403).end();
 fs.readFile(file,(err,data)=>{if(err)return res.writeHead(404).end();
  if(file.endsWith('app.js')) data=data.toString().replace('  initialize();','  renderDashboard = async () => {}; bindEvents(); window.openDispatchForTest = showAdminDeliveryAssignment;');
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html');res.end(data);
 });
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const base='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({channel:'msedge'});
 try {
  for(const width of [360,768,1440]) {
   const page=await browser.newPage({viewport:{width,height:900}});
   let mode='normal',assigned=0;
   await page.route('**/*',async route=>{
    const u=new URL(route.request().url());
    if(u.pathname.startsWith('/api/v1/')) {
     if(u.pathname.endsWith('/assign')) {assigned++;assert.deepEqual(route.request().postDataJSON(),{agent_user_id:'a1'});if(mode==='success')return route.fulfill({contentType:'application/json',body:JSON.stringify({status:'ACCEPTED'})});return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:{message:'This rider is no longer available. Refresh riders.'}})});}
     if(mode==='error')return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:{message:'Unable to load riders.'}})});
     return route.fulfill({contentType:'application/json',body:JSON.stringify(mode==='empty'?[]:[
      {user_id:'a1',name:'Alex Kato',phone:'0700000001',transport_mode:'Motorcycle',availability_status:'AVAILABLE',user_status:'ACTIVE'},
      {user_id:'a2',name:'Nabirye Sarah Namutebi',phone:'0700000002',transport_mode:'Bicycle',availability_status:'AVAILABLE',user_status:'ACTIVE'},
      {user_id:'a3',name:'Suspended Rider',availability_status:'AVAILABLE',user_status:'SUSPENDED'},
      {user_id:'a4',name:'Busy Rider',availability_status:'BUSY',user_status:'ACTIVE'}])});
    }
    if(u.origin!==base)return route.abort();return route.continue();
   });
   await page.goto(base);await page.evaluate(()=>window.openDispatchForTest('delivery-test'));
   await page.locator('.dispatch-rider').first().waitFor();
   assert.equal(await page.locator('.dispatch-rider').count(),2);
   assert.ok(await page.locator('#modalContent').evaluate(e=>e.scrollWidth<=e.clientWidth+2));
   await page.locator('#dispatchRiderSearch').fill('sarah');assert.equal(await page.locator('.dispatch-rider:visible').count(),1);
   await page.locator('#dispatchRiderSearch').fill('missing');assert.equal(await page.locator('#dispatchNoMatches').isVisible(),true);
   await page.locator('#dispatchRiderSearch').fill('');
   await page.locator('.dispatch-rider').first().click();await page.locator('#dispatchFeedback').getByText('This rider is no longer available. Refresh riders.').waitFor();
   assert.equal(assigned,1);assert.equal(await page.locator('.dispatch-rider').first().isEnabled(),true);
   fs.mkdirSync('artifacts/dispatch',{recursive:true});await page.screenshot({path:`artifacts/dispatch/riders-${width}.png`});
   mode='empty';await page.getByRole('button',{name:'Refresh riders'}).click();await page.getByRole('heading',{name:'No riders available right now'}).waitFor();
   mode='error';await page.getByRole('button',{name:'Refresh riders'}).click();await page.getByRole('button',{name:'Try again'}).waitFor();
   mode='normal';await page.getByRole('button',{name:'Try again'}).click();await page.locator('.dispatch-rider').first().waitFor();
   mode='success';await page.locator('.dispatch-rider').first().click();await page.waitForFunction(()=>!document.querySelector('#modalBackdrop').classList.contains('open'));assert.equal(assigned,2);
   console.log('PASS rider picker '+width+': eligible riders, search, no matches, assignment conflict, empty, load failure, retry, overflow');await page.close();
  }
 } finally {await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
