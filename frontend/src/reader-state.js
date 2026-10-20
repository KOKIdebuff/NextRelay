// Reader records never contain business state. Key is project + document + version.
export const readerKey=(project,id,version)=>JSON.stringify([project,id,version]);
export const snapMode=(height,total)=>height<total*.25?'collapsed':height>total*.77?'full':'half';
export class ReaderRecords {
  records=new Map();
  get(key){if(!this.records.has(key))this.records.set(key,{top:0,anchor:null,offset:0,open:[]});return this.records.get(key);}
  capture(key,scroller){
    const r=this.get(key);r.top=scroller.scrollTop;
    r.open=[...scroller.querySelectorAll('details[open]')].map(e=>e.dataset.detail);
    const bounds=scroller.getBoundingClientRect();
    const anchors=[...scroller.querySelectorAll('[data-anchor]')];
    const anchor=anchors.find(e=>e.getBoundingClientRect().bottom>bounds.top+2);
    r.anchor=anchor?.dataset.anchor??null;r.offset=anchor?anchor.getBoundingClientRect().top-bounds.top:0;
  }
  restore(key,scroller){
    const r=this.get(key);
    scroller.querySelectorAll('details').forEach(e=>e.open=r.open.includes(e.dataset.detail));
    const anchor=[...scroller.querySelectorAll('[data-anchor]')].find(e=>e.dataset.anchor===r.anchor);
    scroller.scrollTop=r.top;
    if(anchor)scroller.scrollTop+=anchor.getBoundingClientRect().top-scroller.getBoundingClientRect().top-r.offset;
  }
}
