"""Started and owned by Q. Private ephemeral loopback port, token-authenticated."""
import os
import socket
import json
import sys
import threading

# Avoid oversubscribing CPU cores when one research run calls several math libraries.
for variable in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(variable,'1')

import uvicorn
from flagship_api import app

if __name__ == '__main__':
    sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    sock.bind(('127.0.0.1',0)); sock.listen(128)
    class OwnedServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                print(json.dumps({'q_engine_port':sock.getsockname()[1], 'q_engine_pid':os.getpid()}),flush=True)

    server = OwnedServer(uvicorn.Config(app,host='127.0.0.1',access_log=False,log_level='warning'))
    def watch_owner():
        # EOF also arrives when Windows terminates the owning Node process.
        # Avoid holding Python's buffered stdin lock while subprocesses inspect it.
        while os.read(0, 1):
            pass
        server.should_exit = True
        # A long compute job must not leave an orphan after Q has closed.
        if not finished.wait(5):
            os._exit(0)
    finished = threading.Event()
    threading.Thread(target=watch_owner,daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        finished.set()
