import React,{memo,useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {ReactFlow,Background,Controls,MiniMap,Handle,Position,MarkerType,BaseEdge,EdgeLabelRenderer,getBezierPath,useNodesState,useEdgesState} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './style.css';
import {buildView,layoutNodes,groupEdges} from './model.mjs';

const tree=JSON.parse(document.getElementById('tree-data').textContent);
const byId=new Map(tree.nodes.map(n=>[n.id,n]));
const serviceById=new Map(tree.services.map(n=>[n.id,n]));
const analysis=tree.analysis;
const childMap=new Map(tree.nodes.map(n=>[n.id,[]]));
for(const[id,parent]of Object.entries(analysis.parents))childMap.get(parent).push(id);
const names={question:'Вопрос',rule:'Правило маршрутизации',result:'Конечный результат',reference:'Ссылка'};
const colors={question:'#2563a5',rule:'#b97721',result:'#217c65',reference:'#8b7c98'};

const QuestionNode=memo(function QuestionNode({id,data,selected}){
  return <div className={`question-node kind-${data.kind} ${selected?'is-selected':''} ${id==='root'?'is-root':''}`}>
    <Handle type="target" position={Position.Top}/>
    <div className="node-kicker"><span className="node-dot"/>{id==='root'?'КОРЕНЬ · СТАРТ':names[data.kind]}<span>{data.level===undefined?'Вне корня':`${data.levelLabel} ${data.level}`}</span></div>
    <div className="node-title" title={data.title}>{data.title}</div>
    <code>{id}</code>
    {data.childCount>0&&data.canExpand?<button className="node-toggle nodrag nopan" onClick={event=>{event.stopPropagation();data.toggle(id);}}>{data.expanded?'− Свернуть':'+ Раскрыть'}<span>Следующий уровень: {data.childCount}</span></button>:<div className="node-footer">{data.kind==='result'?'■ Лист · подбор завершён':data.kind==='rule'?'Применяется без вопроса владельцу':'Нажмите для просмотра вариантов ответа'}</div>}
    <Handle type="source" position={Position.Bottom}/>
  </div>;
});

const AnswerEdge=memo(function AnswerEdge(props){
  const {data,selected}=props;
  const [path,x,y]=getBezierPath(props);
  const active=selected||data.highlight;
  const label=data.labels.length===1?data.labels[0]:`${data.labels.length} варианта ответа`;
  return <><BaseEdge id={props.id} path={path} markerEnd={props.markerEnd} style={{stroke:active?'#ec7849':'#8da5b4',strokeWidth:active?3:1.7,strokeDasharray:data.returnEdge?'7 5':undefined}}/>
    <EdgeLabelRenderer><button className={`answer-label nodrag nopan ${active?'active':''}`} style={{transform:`translate(-50%,-50%) translate(${x}px,${y}px)`}} title={data.labels.join('\n')} onClick={event=>{event.stopPropagation();data.inspect();}}>{label}</button></EdgeLabelRenderer></>;
});
const nodeTypes={question:QuestionNode},edgeTypes={answer:AnswerEdge};
const scopes=[['tree','От корня'],['all','Всё дерево'],['focus','Ветка узла'],['longest','Длинный путь'],['detached','Вне корня']];

function App(){
  const initial=decodeURIComponent(location.hash.slice(1));
  const [selected,setSelected]=useState(byId.has(initial)?initial:'root');
  const [scope,setScope]=useState(initial&&initial!=='root'&&byId.has(initial)?'focus':'tree');
  const [expanded,setExpanded]=useState(new Set(['root','unknown']));
  const [query,setQuery]=useState(''),[edgeDetails,setEdgeDetails]=useState(null),[inspector,setInspector]=useState(false);
  const [direction,setDirection]=useState('TB');
  const [nodes,setNodes,onNodesChange]=useNodesState([]),[edges,setEdges,onEdgesChange]=useEdgesState([]);
  const [flow,setFlow]=useState(null),[zoom,setZoom]=useState(1);
  const canvas=useRef(null),lastLayout=useRef(null);
  const viewSelection=scope==='focus'?selected:'root';
  const view=useMemo(()=>buildView(tree,scope,viewSelection,expanded),[scope,viewSelection,expanded]);
  const grouped=useMemo(()=>groupEdges(view.edges),[view]);
  const placed=useMemo(()=>layoutNodes(view.nodes,grouped,direction),[view,grouped,direction]);
  const toggle=useCallback(id=>setExpanded(previous=>{const next=new Set(previous);if(next.has(id))next.delete(id);else next.add(id);return next;}),[]);
  const center=useCallback(id=>{
    const node=flow?.getNode(id);if(!node)return;
    flow.setCenter(node.position.x+160,node.position.y+90,{zoom:.85,duration:300});
  },[flow]);
  function choose(id,show=true){
    setSelected(id);setEdgeDetails(null);setInspector(show);location.hash=encodeURIComponent(id);
    if(!view.nodes.some(n=>n.id===id))setScope(analysis.unreachable.includes(id)?'detached':'focus');
    else center(id);
  }
  useEffect(()=>{
    const sameLayout=lastLayout.current===placed;
    setNodes(previous=>placed.map(node=>({id:node.id,type:'question',position:sameLayout?(previous.find(n=>n.id===node.id)?.position||node.position):node.position,selected:node.id===selected,data:{...node,level:scope==='longest'?analysis.longest_path.indexOf(node.id):analysis.levels[node.id],levelLabel:scope==='longest'?'Шаг':'Ур.',canExpand:scope==='tree',childCount:childMap.get(node.id).length,expanded:expanded.has(node.id),toggle}})));
    lastLayout.current=placed;
    setEdges(grouped.map(edge=>({id:edge.id,source:edge.source,target:edge.target,type:'answer',markerEnd:{type:MarkerType.ArrowClosed,color:'#8da5b4'},data:{...edge,highlight:scope==='longest',returnEdge:scope!=='longest'&&analysis.levels[edge.target]<=analysis.levels[edge.source],inspect:()=>{setEdgeDetails(edge);setInspector(true);}}})));
  },[placed,grouped,selected,scope,expanded,toggle,setNodes,setEdges]);
  // Wait for React Flow to measure the custom cards before positioning the viewport.
  useEffect(()=>{
    if(!flow||!placed.length)return;
    const first=requestAnimationFrame(()=>{
      const target=placed.find(n=>n.id===(scope==='longest'||scope==='tree'?'root':selected))||placed[0];
      if(scope==='all'||scope==='detached')flow.fitView({nodes:placed.map(n=>({id:n.id})),padding:.15,duration:250,minZoom:.02,maxZoom:.85});
      else flow.setViewport({x:(canvas.current.clientWidth-320*.85)/2-target.position.x*.85,y:70-target.position.y*.85,zoom:.85},{duration:250});
    });
    return()=>cancelAnimationFrame(first);
  },[flow,placed,scope]);
  const selectedNode=byId.get(selected);
  const list=(scope==='longest'?analysis.longest_path.map(id=>byId.get(id)):tree.nodes).filter(n=>(scope!=='detached'||analysis.unreachable.includes(n.id))&&JSON.stringify(n).toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const activeMode=scopes.find(([value])=>value===scope)?.[1];
  return <div className="app">
    <header className="app-header"><div className="brand-icon">↳</div><div><h1>Дерево вопросов</h1><p>Подбор автомастерской <span> / </span> React Flow + Dagre</p></div><div className="header-status"><i/>Спецификация · {tree.nodes.length} узлов</div></header>
    <div className="metrics"><span><b>root</b>корень</span><span><b>{Math.max(...Object.values(analysis.levels))+1}</b>уровней от корня</span><span><b>{analysis.leaves.length}</b>конечных результатов</span><button onClick={()=>setScope('longest')}><b>{analysis.longest_path.length-1}</b>переходов · длинный путь</button><span><b>{analysis.max_questions}</b>узлов вопросов на пути, максимум</span><button onClick={()=>setScope('detached')}><b>{analysis.unreachable.length}</b>без явного пути от root</button><details><summary>Как считаем</summary><p>Уровень — минимальное число переходов от root. Длинный путь — путь до листа без повторов узлов. Циклы допускают неограниченный обход без правил остановки. Число вопросов диалога может быть меньше: известные ответы пропускаются. Показатели относятся ко всему графу явных связей.</p></details></div>
    <div className="workspace"><aside className="sidebar"><div className="sidebar-head"><h2>{scope==='longest'?'Шаги длинного пути':'Навигатор'}</h2><span>{list.length}</span></div><input aria-label="Поиск узлов" type="search" placeholder="Найти вопрос или услугу…" value={query} onChange={e=>setQuery(e.target.value)}/><div className="node-list">{list.map((n,i)=><button key={n.id} className={n.id===selected?'active':''} onClick={()=>choose(n.id)}><span className={`list-dot kind-${n.kind}`}/><div><small>{scope==='longest'?`Шаг ${i}`:analysis.levels[n.id]===undefined?'Вне корня':`Уровень ${analysis.levels[n.id]}`} · {n.id==='root'?'Корень':names[n.kind]}</small><strong>{n.title}</strong><code>{n.id}</code></div></button>)}{!list.length&&<p className="empty">Совпадений нет</p>}</div><div className="sidebar-note">Раскладка сверху вниз.<br/>Узлы можно перетаскивать.<br/>Колесо — масштаб, фон — перемещение.</div></aside>
    <section className="graph-area"><div className="toolbar"><nav aria-label="Режим графа">{scopes.map(([value,label])=><button className={scope===value?'active':''} key={value} onClick={()=>{setEdgeDetails(null);setScope(value);if(value==='tree'){setExpanded(new Set(['root','unknown']));setSelected('root');location.hash='root';}}}>{label}</button>)}</nav><div className="toolbar-actions"><button title="Изменить направление раскладки" aria-label="Направление раскладки" onClick={()=>setDirection(d=>d==='TB'?'LR':'TB')}>{direction==='TB'?'↓':'→'}</button><button onClick={()=>flow?.fitView({padding:.15,minZoom:.02,maxZoom:1,duration:300})}>Вписать</button><button onClick={()=>center(selected)}>К узлу</button></div></div>
    <div className="canvas" ref={canvas}><ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onInit={setFlow} onNodeClick={(_,n)=>choose(n.id)} onPaneClick={()=>setInspector(false)} onMove={(_,v)=>setZoom(v.zoom)} minZoom={.02} maxZoom={2.5} nodesConnectable={false} deleteKeyCode={null} attributionPosition="bottom-right"><Background color="#cbd8df" gap={24} size={1.2}/><Controls showInteractive={false}/><MiniMap nodeColor={n=>n.id==='root'?'#e87e52':colors[n.data.kind]} maskColor="rgba(238,243,246,.72)" pannable zoomable ariaLabel="Мини-карта дерева"/></ReactFlow><div className="canvas-label"><i/>{activeMode}<span>Узлы: {nodes.length} · связи: {edges.length}</span></div><div className="legend"><span><i style={{background:'#e87e52'}}/>Корень</span><span><i style={{background:colors.question}}/>Вопрос</span><span><i style={{background:colors.rule}}/>Правило</span><span><i style={{background:colors.result}}/>Результат</span></div></div>
    <footer><span>{scope==='tree'?'Раскрывайте следующие уровни кнопкой «+» в узле. Дополнительные связи и возвраты — в «Всё дерево».':scope==='longest'?'Путь без повторов. Шаги перечислены слева; нажмите шаг, чтобы перейти к нему.':scope==='detached'?'Нет явного пути от root; условия вызова могут быть описаны текстом.':'Нажмите узел или подпись ребра для подробностей.'}</span><strong>{Math.round(zoom*100)}%</strong></footer></section>
    {inspector&&<aside className="inspector"><div className="sidebar-head"><h2>{edgeDetails?'Переход':'Выбранный узел'}</h2><button aria-label="Закрыть подробности" onClick={()=>setInspector(false)}>×</button></div>{edgeDetails?<><h3>{byId.get(edgeDetails.source).title}</h3><div className="inspector-caption">Варианты ответа / условия перехода</div><ul>{edgeDetails.labels.map(label=><li key={label}>{label}</li>)}</ul><div className="inspector-caption">Следующий узел</div><button className="target-button" onClick={()=>choose(edgeDetails.target)}>{byId.get(edgeDetails.target).title} →</button><p className="muted">У вопроса это варианты ответа; у правила — условия маршрутизации из спецификации.</p></>:<><span className={`detail-badge kind-${selectedNode.kind}`}>{selected==='root'?'Корень':names[selectedNode.kind]}</span><h3>{selectedNode.title}</h3><code className="detail-id">{selected}</code><button className="target-button" onClick={()=>setScope('focus')}>Показать путь и продолжения →</button>{['applies_when','decision_changed','stop','note'].map(key=>selectedNode.data[key]&&<section key={key}><h4>{{applies_when:'Когда появляется',decision_changed:'Что меняет ответ',stop:'Остановка',note:'Примечание'}[key]}</h4><p>{String(selectedNode.data[key])}</p></section>)}{(selectedNode.data.service_ids||[]).map(id=><details key={id}><summary>{serviceById.get(id)?.source_title||id}</summary><pre>{JSON.stringify(serviceById.get(id),null,2)}</pre></details>)}<h4>Исходящие переходы</h4>{groupEdges(tree.edges.filter(e=>e.source===selected)).map(edge=><button className="transition-button" key={edge.id} onClick={()=>setEdgeDetails(edge)}>{edge.labels.join(' / ')}<small>{byId.get(edge.target).title} →</small></button>)}<details><summary>Исходные данные</summary><pre>{JSON.stringify(selectedNode.data,null,2)}</pre></details></>}</aside>}
    </div></div>;
}
createRoot(document.getElementById('root')).render(<App/>);
