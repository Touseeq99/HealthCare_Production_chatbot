import multiprocessing
import os

# Server Socket
bind = '0.0.0.0:8000'
backlog = 2048  
# Worker Processes
workers = (multiprocessing.cpu_count() * 2) + 1 
worker_class = 'uvicorn.workers.UvicornWorker'  
worker_connections = 1000
max_requests = 1000  
max_requests_jitter = 50  
# Timeouts
timeout = 120  
graceful_timeout = 30  
keepalive = 2  

# Debugging
reload = False  # Don't use auto-reload in production
spew = False  # Server-wide traceback dump on errors

# Server Mechanics
pidfile = None  # Path to a pid file to write
umask = 0  # File mode (permissions) for the socket
user = None  # Drop privileges to this user if running as root
group = None  # Drop privileges to this group if running as root
tmp_upload_dir = None  # Directory to store temporary uploads

# Logging
accesslog = 'logs/gunicorn_access.log'  
errorlog = 'logs/gunicorn_error.log'  
loglevel = 'info'  
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'  

# Process Naming
proc_name = 'metamed_backend'  

def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def pre_fork(server, worker):
    pass

def pre_exec(server):
    server.log.info("Forked child, re-executing.")

def when_ready(server):
    server.log.info("Server is ready. Spawning workers")

def worker_int(worker):
    worker.log.info("Worker received INT or QUIT signal")
    # Get traceback info
    import threading, sys, traceback
    id2name = {th.ident: th.name for th in threading.enumerate()}
    code = []
    for threadId, stack in sys._current_frames().items():
        code.append("\n# Thread: %s(%d)" % (id2name.get(threadId, ""), threadId))
        for filename, lineno, name, line in traceback.extract_stack(stack):
            code.append('File: "%s", line %d, in %s' % (filename, lineno, name))
            if line:
                code.append('  %s' % (line.strip()))
    worker.log.debug("\n".join(code))

def worker_abort(worker):
    worker.log.info("Worker received SIGABRT signal")
