import fs from 'node:fs/promises';
import {randomUUID} from 'node:crypto';

export async function saveCheckpoint(path,data) {
  // Publish only a complete snapshot. A process exit during the temporary
  // write must leave the last published checkpoint readable.
  const temporary=`${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await fs.writeFile(temporary,JSON.stringify(data));
    await fs.rename(temporary,path);
  } finally {
    await fs.rm(temporary,{force:true}).catch(()=>{});
  }
}
