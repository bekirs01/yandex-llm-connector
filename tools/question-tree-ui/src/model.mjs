import dagre from 'dagre';

export function buildView(data,mode,selected,expanded){
  const {parents,unreachable,longest_path}=data.analysis;
  let ids;
  if(mode==='detached')ids=new Set(unreachable);
  else if(mode==='longest')ids=new Set(longest_path);
  else if(mode==='all')ids=new Set(data.nodes.filter(n=>!unreachable.includes(n.id)).map(n=>n.id));
  else if(mode==='focus'){
    ids=new Set([selected]);let id=selected;
    while(id in parents){id=parents[id];ids.add(id);}
    for(const edge of data.edges)if(edge.source===selected)ids.add(edge.target);
  }else{
    ids=new Set(['root']);
    for(const n of data.nodes){let id=n.id;let visible=true;
      if(!(id in parents))continue;
      while(id in parents){id=parents[id];if(!expanded.has(id)){visible=false;break;}}
      if(visible&&id==='root')ids.add(n.id);
    }
  }
  let edges=data.edges.filter(e=>ids.has(e.source)&&ids.has(e.target));
  if(mode==='tree')edges=edges.filter(e=>parents[e.target]===e.source);
  if(mode==='longest')edges=edges.filter(e=>longest_path.indexOf(e.target)===longest_path.indexOf(e.source)+1);
  return{nodes:data.nodes.filter(n=>ids.has(n.id)),edges};
}

export function groupEdges(edges){
  const groups=new Map();
  for(const edge of edges){
    const id=JSON.stringify([edge.source,edge.target]);
    if(!groups.has(id))groups.set(id,{id,source:edge.source,target:edge.target,labels:[]});
    const group=groups.get(id);if(!group.labels.includes(edge.label))group.labels.push(edge.label);
  }
  return[...groups.values()];
}

export function layoutNodes(nodes,edges,direction='TB'){
  const graph=new dagre.graphlib.Graph();
  graph.setGraph({rankdir:direction,ranker:'network-simplex',nodesep:120,ranksep:120,edgesep:40,marginx:60,marginy:60});
  graph.setDefaultEdgeLabel(()=>({}));
  for(const node of nodes)graph.setNode(node.id,{width:320,height:180});
  for(const edge of edges)graph.setEdge(edge.source,edge.target,{width:180,height:50});
  dagre.layout(graph);
  return nodes.map(node=>{
    const p=graph.node(node.id);return{...node,position:{x:p.x-160,y:p.y-90}};
  });
}
