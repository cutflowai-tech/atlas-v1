import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {loadProfile, renderProfile} from '../app.mjs';
const fixture = JSON.parse(await readFile(new URL('../fixtures/editor-profile.json',import.meta.url),'utf8'));
const copy = () => structuredClone(fixture);
const root = () => ({innerHTML:'', attributes:{}, setAttribute(k,v){this.attributes[k]=v;}});

test('fixture fetch-to-render flow produces evidence artifact', async () => {
  const target = root();
  await loadProfile(target,'editor-42', async (url,options) => {
    assert.equal(url,'/api/editors/editor-42');
    assert.equal(options.headers.Accept,'application/json');
    assert.match(target.innerHTML,/Loading/);
    assert.equal(target.attributes['aria-busy'],'true');
    return {ok:true,json:async()=>copy()};
  });
  for (const expected of ['Fixture Editor','Meets Expectations','7200','7500','on_time','quality-label-v1','identity-v1','Revision context','event-100','event-101','event-102','source_values','rule_version','calculated_at']) assert.ok(target.innerHTML.includes(expected),expected);
  assert.equal((target.innerHTML.match(/<details>/g)||[]).length,3);
  assert.equal(target.attributes['aria-busy'],'false');
  await writeFile(new URL('../evidence/fixture-e2e.html',import.meta.url),`<!doctype html><html lang="en"><meta charset="utf-8"><title>Fixture flow artifact</title><link rel="stylesheet" href="../style.css"><body><div class="banner">FIXTURE · fetch-to-render harness artifact</div><main>${target.innerHTML}</main></body></html>\n`);
});
test('no metric calculation: API values pass through unchanged',()=>{
  const p=copy(); p.metrics.speed[0].duration_seconds=123; p.metrics.speed[0].cohort_median_seconds=987;
  p.metrics.deadline[0].result='late'; p.metrics.quality[0].revision_context={count:999};
  const html=renderProfile(p,'editor-42');
  for(const supplied of ['123','987','late','999','Meets Expectations']) assert.ok(html.includes(supplied));
  assert.ok(!html.includes('on_time'));
});
test('empty metrics and unknown context remain honest',()=>{
  const p=copy(); p.metrics={speed:[],deadline:[],quality:[]}; p.work_cycles[0].requested_eta=null;p.work_cycles[0].revision_context=null;
  const html=renderProfile(p,'editor-42');
  assert.match(html,/No metrics supplied/);assert.match(html,/No speed metrics supplied/);assert.match(html,/Unknown \/ not supplied/);assert.match(html,/Missing ETA has no metric/);
});
test('canonical Video Type groups, null benchmark and invalid cohort',()=>{
  const p=copy();const m=structuredClone(p.metrics.speed[0]);m.video_type=m.cohort_video_type='long-form';m.cohort_median_seconds=null;p.metrics.speed.push(m);
  let html=renderProfile(p,'editor-42');assert.match(html,/Video Type · short-form/);assert.match(html,/Video Type · long-form/);assert.match(html,/Unknown \/ not supplied/);
  p.metrics.speed[0].cohort_video_type='other';html=renderProfile(p,'editor-42');assert.match(html,/cohort mismatch/);assert.ok(!html.includes('7500'));
});
test('missing evidence, mapping, ETA and mismatched editor fail closed',()=>{
  for(const mutate of [p=>delete p.metrics.quality[0].evidence,p=>p.metrics.quality[0].editor_id='other',p=>p.metrics.quality[0].label_mapping_version='']) {
    const p=copy();mutate(p);const html=renderProfile(p,'editor-42');assert.ok(!html.includes('Meets Expectations'));assert.match(html,/unavailable/);
  }
  const p=copy();p.metrics.deadline[0].requested_eta=null;assert.ok(!renderProfile(p,'editor-42').includes('on_time'));
});
test('all request and contract errors clear stale metrics',async()=>{
  for(const fetcher of [async()=>{throw Error('offline')},async()=>({ok:false,status:404}),async()=>({ok:true,json:async()=>{throw Error('JSON')}}),async()=>({ok:true,json:async()=>({...copy(),contract_version:'2'})})]){
    const target=root();target.innerHTML='stale';await loadProfile(target,'editor-42',fetcher);assert.match(target.innerHTML,/role="alert"/);assert.ok(!target.innerHTML.includes('stale'));assert.equal(target.attributes['aria-busy'],'false');
  }
});
test('untrusted strings escaped and AI omitted',()=>{
  const p=copy();p.editor.display_name='<img src=x onerror=alert(1)>';p.ai_annotation='UNTRUSTED_AI_FACT';p.metrics.quality[0].revision_context={note:'</dd><script>bad()</script>'};
  const html=renderProfile(p,'editor-42');assert.ok(!html.includes('<img'));assert.ok(!html.includes('<script>'));assert.ok(!html.includes('UNTRUSTED_AI_FACT'));assert.match(html,/&lt;img/);
});
test('editor ID is encoded and identity mismatch rejected',async()=>{
  const target=root();await loadProfile(target,'a/b',async url=>{assert.equal(url,'/api/editors/a%2Fb');return {ok:true,json:async()=>copy()}});assert.match(target.innerHTML,/unavailable/);
});
test('reload keeps latest response when requests finish out of order',async()=>{
  const target=root();let finish;
  const slow=loadProfile(target,'editor-42',()=>new Promise(resolve=>{finish=resolve}));
  await loadProfile(target,'editor-42',async()=>({ok:false,status:500}));
  finish({ok:true,json:async()=>copy()});await slow;
  assert.match(target.innerHTML,/unavailable/);
});
