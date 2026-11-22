import test from 'node:test';
import assert from 'node:assert/strict';
import {buildView, layoutNodes, groupEdges} from '../src/model.mjs';

const data={nodes:['root','question','result','detached'].map(id=>({id,kind:id==='result'?'result':'question'})),edges:[
  {source:'root',target:'question',label:'Описать жалобу'},
  {source:'question',target:'result',label:'Да'},
  {source:'question',target:'result',label:'Не знаю'},
  {source:'question',target:'result',label:'Не знаю'},
  {source:'question',target:'root',label:'Исправить ответ'}
],analysis:{parents:{question:'root',result:'question'},levels:{root:0,question:1,result:2},unreachable:['detached'],longest_path:['root','question','result']}};

test('collapsed overview excludes descendants until their question is expanded',()=>{
  const view=buildView(data,'tree','root',new Set(['root']));
  assert.deepEqual(view.nodes.map(n=>n.id),['root','question']);
  assert.equal(view.edges.length,1);
  assert.equal(buildView(data,'tree','root',new Set(['root','question'])).nodes.length,3);
});

test('longest path excludes return edges, detached nodes stay in separate view',()=>{
  const path=buildView(data,'longest','root',new Set());
  assert.ok(path.edges.every(e=>e.target!=='root'));
  assert.deepEqual(buildView(data,'detached','root',new Set()).nodes.map(n=>n.id),['detached']);
  assert.ok(!buildView(data,'all','root',new Set()).nodes.some(n=>n.id==='detached'));
});

test('parallel answers keep their texts without duplicating fallback labels',()=>{
  const edge=groupEdges(data.edges).find(e=>e.source==='question'&&e.target==='result');
  assert.deepEqual(edge.labels,['Да','Не знаю']);
});

test('Dagre positions children below root without changing source data',()=>{
  const view=buildView(data,'longest','root',new Set());
  const before=JSON.stringify(view);
  const layout=layoutNodes(view.nodes,groupEdges(view.edges));
  assert.ok(layout.find(n=>n.id==='result').position.y>layout.find(n=>n.id==='root').position.y);
  assert.equal(JSON.stringify(view),before);
  for(const node of layout)assert.ok(Number.isFinite(node.position.x)&&Number.isFinite(node.position.y));
});

test('a short branch stays on the same next level as its sibling question',()=>{
  const nodes=['root','short','question','leaf'].map(id=>({id}));
  const edges=[{source:'root',target:'short'},{source:'root',target:'question'},{source:'question',target:'leaf'}];
  const positions=new Map(layoutNodes(nodes,edges).map(n=>[n.id,n.position]));
  assert.equal(positions.get('short').y,positions.get('question').y);
});
