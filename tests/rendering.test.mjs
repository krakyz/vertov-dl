import test from 'node:test';
import assert from 'node:assert/strict';
import { reconcileChildren, frameScheduler } from '../apps/web/src/rendering.ts';

class Parent {
  children = []; moves = 0;
  insertBefore(child, before) {
    child.parent?.children.splice(child.parent.children.indexOf(child),1);
    const index = before ? this.children.indexOf(before) : this.children.length;
    this.children.splice(index,0,child);child.parent=this;this.moves++;
  }
}
function child() { return {parent:null,remove(){this.parent.children.splice(this.parent.children.indexOf(this),1);this.parent=null;}}; }

test('unchanged list never detaches children; insertion does not move existing cards',()=>{
 const parent=new Parent(), a=child(), b=child(), c=child();
 reconcileChildren(parent,[a,b]);parent.moves=0;
 reconcileChildren(parent,[a,b]);assert.equal(parent.moves,0);
 reconcileChildren(parent,[c,a,b]);assert.equal(parent.moves,1);
 assert.deepEqual(parent.children,[c,a,b]);
});
test('reordering and removal retain the same card instances',()=>{
 const parent=new Parent(), a=child(), b=child(), c=child();
 reconcileChildren(parent,[a,b,c]);parent.moves=0;
 reconcileChildren(parent,[c,a]);assert.deepEqual(parent.children,[c,a]);
 assert.equal(parent.moves,1);assert.equal(b.parent,null);
});
test('render requests coalesce per frame and a later frame can render again',()=>{
 const frames=[];let draws=0;
 const render=frameScheduler(()=>draws++, callback=>frames.push(callback));
 render();render();render();assert.equal(frames.length,1);assert.equal(draws,0);
 frames.shift()();assert.equal(draws,1);
 render();frames.shift()();assert.equal(draws,2);
});
