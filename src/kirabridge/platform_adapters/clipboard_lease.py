"""Memory-only macOS clipboard ownership, independent of the killable GUI worker.

The caller must hold the shared ClipboardManager lock for the whole lease. No
terminal, Apple event or paste action runs here. EOF asks the owner to restore;
original formats and generations never leave the owner process.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from contextlib import asynccontextmanager

from kirabridge.bridge_core.models import BridgeError

# This source is static. User text travels only through the child's stdin.
OWNER_SCRIPT = r"""
ObjC.import('Foundation'); ObjC.import('AppKit');
function run() {
 const input=$.NSFileHandle.fileHandleWithStandardInput;
 const output=$.NSFileHandle.fileHandleWithStandardOutput;
 const pb=$.NSPasteboard.generalPasteboard;
 let pending='', saved=[], generation=null, modified=false, restore='not_modified';
 function number(value) {
  const n=Number(value);
  if(!Number.isSafeInteger(n) || n<0) throw Error('clipboard_invalid_value');
  return n;
 }
 function emit(value) {
  output.writeData($(JSON.stringify(value)+'\n').dataUsingEncoding($.NSUTF8StringEncoding));
 }
 function line() {
  while(pending.indexOf('\n')<0) {
   const data=input.availableData;
   if(number(data.length)===0) return null;
   const part=ObjC.unwrap($.NSString.alloc.initWithDataEncoding(data,$.NSUTF8StringEncoding));
   if(typeof part!=='string') throw Error('clipboard_protocol');
   pending+=part;
   if(pending.length>1500000) throw Error('clipboard_protocol');
  }
  const end=pending.indexOf('\n'), value=pending.slice(0,end);
  pending=pending.slice(end+1); return JSON.parse(value);
 }
 try {
  const command=line();
  if(!command || command.op!=='begin' || typeof command.text_b64!=='string')
   throw Error('clipboard_protocol');
  const payload=$.NSData.alloc.initWithBase64EncodedStringOptions($(command.text_b64),0);
  if(!payload || number(payload.length)>1048576) throw Error('clipboard_size_limit');
  const text=$.NSString.alloc.initWithDataEncoding(payload,$.NSUTF8StringEncoding);
  if(!text) throw Error('clipboard_protocol');
  const before=number(pb.changeCount), items=pb.pasteboardItems;
  const count=items ? number(items.count) : 0; let total=0;
  if(count>32) throw Error('clipboard_size_limit');
  for(let i=0;i<count;i++) {
   const item=items.objectAtIndex(i), types=item.types, formats=[];
   const formatsCount=number(types.count);
   if(formatsCount>64) throw Error('clipboard_size_limit');
   for(let j=0;j<formatsCount;j++) {
    const type=types.objectAtIndex(j), data=item.dataForType(type);
    if(!data) throw Error('clipboard_snapshot_unavailable');
    const bytes=number(data.length); total+=bytes;
    if(bytes>1048576 || total>4194304) throw Error('clipboard_size_limit');
    formats.push([type,data]);
   }
   saved.push(formats);
  }
  if(number(pb.changeCount)!==before) throw Error('clipboard_changed');
  // Record ownership immediately after clear, before any fallible set operation.
  generation=number(pb.clearContents); modified=true;
  if(!pb.setStringForType(text,$.NSPasteboardTypeString)) throw Error('clipboard_write_failed');
  if(number(pb.changeCount)!==generation) throw Error('clipboard_changed');
  emit({status:'ready',generation:generation});
  const finish=line();
  if(finish!==null && finish.op!=='restore') throw Error('clipboard_protocol');
 } catch(error) {
  const allowed=['clipboard_invalid_value','clipboard_protocol','clipboard_size_limit',
    'clipboard_snapshot_unavailable','clipboard_changed','clipboard_write_failed'];
  const code=allowed.includes(error.message) ? error.message : 'clipboard_owner_failed';
  emit({status:'failed',code:code});
 } finally {
  if(modified) {
   try {
    if(number(pb.changeCount)!==generation) restore='user_changed';
    else {
     const restored=$.NSMutableArray.alloc.init;
     for(const formats of saved) {
      const item=$.NSPasteboardItem.alloc.init;
      for(const pair of formats)
       if(!item.setDataForType(pair[1],pair[0])) throw Error('restore');
      restored.addObject(item);
     }
     // Materialize restoration objects before the last generation check.
     if(number(pb.changeCount)!==generation) restore='user_changed';
     else {
      pb.clearContents;
      if(number(restored.count)>0 && !pb.writeObjects(restored)) throw Error('restore');
      restore='restored';
     }
    }
   } catch(error) { restore='restore_failed'; }
  }
  emit({status:restore});
 }
 return '';
}
"""


class ClipboardLease:
    """One clipboard owner's bounded protocol; no original bytes enter Python."""

    def __init__(self, text, *, process_factory=None, startup_timeout=10, cleanup_timeout=5):
        self.payload = text.encode("utf-8")
        if len(self.payload) > 1048576:
            raise BridgeError("clipboard_size_limit", "Clipboard input exceeds 1 MiB")
        self.process_factory = process_factory or asyncio.create_subprocess_exec
        self.startup_timeout, self.cleanup_timeout = startup_timeout, cleanup_timeout
        self.process = self.spawn_task = None
        self.restore_status = None
        self.generation: int | None = None

    async def start(self):
        if sys.platform != "darwin":
            raise BridgeError("clipboard_unavailable", "Clipboard leases require macOS")
        self.spawn_task = asyncio.create_task(
            self.process_factory(
                "/usr/bin/osascript",
                "-l",
                "JavaScript",
                "-e",
                OWNER_SCRIPT,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=4096,
            )
        )
        try:
            async with asyncio.timeout(self.startup_timeout):
                self.process = await asyncio.shield(self.spawn_task)
        except TimeoutError:
            raise BridgeError(
                "clipboard_unavailable", "Clipboard owner startup timed out"
            ) from None
        packet = json.dumps(
            {"op": "begin", "text_b64": base64.b64encode(self.payload).decode("ascii")}
        )
        self.payload = b""
        try:
            async with asyncio.timeout(self.startup_timeout):
                self.process.stdin.write((packet + "\n").encode("ascii"))
                await self.process.stdin.drain()
                value = await self._message()
            generation = value.get("generation")
            if (
                value.get("status") != "ready"
                or type(generation) is not int
                or not 0 <= generation <= 2**53 - 1
            ):
                raise BridgeError("clipboard_unavailable", "Clipboard owner did not grant a lease")
            self.generation = generation
        except (TimeoutError, ValueError, OSError):
            raise BridgeError(
                "clipboard_unavailable", "Clipboard owner readiness unconfirmed"
            ) from None

    async def _message(self):
        line = await self.process.stdout.readline()
        if not line or len(line) > 4096:
            raise ValueError("Invalid owner receipt")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("Invalid owner receipt")
        return value

    async def close(self):
        if self.process is None:
            if self.spawn_task is None:
                return
            try:
                async with asyncio.timeout(self.cleanup_timeout):
                    self.process = await self.spawn_task
            except Exception:
                return  # No owner was created, so no clipboard mutation was possible.
        try:
            self.process.stdin.close()  # EOF restores even when READY was lost/cancelled.
            async with asyncio.timeout(self.cleanup_timeout):
                statuses = []
                while True:
                    line = await self.process.stdout.readline()
                    if not line:
                        break
                    if len(line) > 4096 or len(statuses) >= 4:
                        raise ValueError("Invalid owner receipt")
                    if line.strip():
                        value = json.loads(line)
                        if not isinstance(value, dict):
                            raise ValueError("Invalid owner receipt")
                        statuses.append(value.get("status"))
                await self.process.wait()
            final = statuses[-1] if statuses else None
            if self.process.returncode != 0 or final not in {
                "restored",
                "user_changed",
                "not_modified",
            }:
                raise ValueError("No restoration receipt")
            self.restore_status = final
        except (TimeoutError, ValueError, OSError):
            # EOF has already requested cleanup. A wedged owner must not become an
            # unbounded child; killing it is explicitly an UNCONFIRMED restoration.
            if self.process.returncode is None:
                self.process.kill()
                try:
                    async with asyncio.timeout(1):
                        await self.process.wait()
                except TimeoutError:
                    pass
            self.restore_status = "unknown"
            raise BridgeError(
                "clipboard_restore_unknown",
                "Clipboard restoration unconfirmed; do not resend input",
            ) from None


@asynccontextmanager
async def clipboard_lease(text, **options):
    """Caller holds clipboard_lock; cleanup survives GUI timeout and task cancellation.

    A whole-process/OS crash cannot guarantee restoration. User-changed generations
    are deliberately preserved. This function never sends terminal input or retries.
    """
    lease = ClipboardLease(text, **options)
    try:
        await lease.start()
        yield lease
    finally:
        cleanup = asyncio.create_task(lease.close())
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()  # An unconfirmed restoration takes precedence over cancellation.
        if cancelled:
            raise asyncio.CancelledError
