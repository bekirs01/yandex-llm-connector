import {defineConfig} from 'vite';
export default defineConfig({
  build:{
    lib:{entry:'src/main.jsx',name:'QuestionTreeViewer',formats:['iife'],fileName:()=> 'viewer.js',cssFileName:'viewer'},
    sourcemap:false,
    emptyOutDir:true,
  },
  define:{'process.env.NODE_ENV':JSON.stringify('production')},
});
