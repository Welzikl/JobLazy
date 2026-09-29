import {readdir,readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../vendor/career-ops');
async function walk(dir) {
  const result=[];
  for(const e of await readdir(dir,{withFileTypes:true})) {
    const p=path.join(dir,e.name);
    if(e.isDirectory()) result.push(...await walk(p));
    else result.push({path:path.relative(root,p).replaceAll('\\','/'),sha256:createHash('sha256').update(await readFile(p)).digest('hex')});
  }
  return result;
}
await writeFile(path.resolve(root,'../career-ops-source.json'),JSON.stringify({source:'User-authorized local career-ops-hermes worktree',
  sourceHead:'f9927deb2fd564c32542d785966157adc6d40b25',note:'Dirty worktree; copied-file hashes identify the actual snapshot.',files:await walk(root)},null,2)+'\n');
