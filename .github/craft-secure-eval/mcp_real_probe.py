"""Real Craft MCP probe. Run only as an unprivileged user in a disconnected network namespace."""
import json, os, selectors, signal, socket, subprocess, sys, time

binary = sys.argv[1]
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.connect(('1.1.1.1', 53))
except OSError as exc:
    if exc.errno not in (101,):
        raise RuntimeError('Network isolation could not be verified') from exc
else:
    raise RuntimeError('Network route exists; refusing to run')
finally:
    sock.close()

env = {'PATH': '/usr/bin:/bin', 'HOME': '/tmp', 'CRAFT_ANYTHING_CONFIG_DIR': '/tmp/craft-eval-config', 'RUST_LOG': 'error'}
proc = subprocess.Popen([binary, '--clean-room', 'mcp', '--restricted'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, env=env, start_new_session=True, bufsize=0)
selector = selectors.DefaultSelector()
selector.register(proc.stdout, selectors.EVENT_READ)
buf = bytearray()
def send(msg):
    proc.stdin.write((json.dumps(msg, separators=(',', ':')) + '\n').encode())
    proc.stdin.flush()
def request(number, method, params):
    send({'jsonrpc':'2.0','id':number,'method':method,'params':params})
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        events=selector.select(deadline-time.monotonic())
        if not events: break
        chunk=os.read(proc.stdout.fileno(),8192)
        if not chunk: raise RuntimeError('MCP disconnected')
        buf.extend(chunk)
        if len(buf)>1024*1024: raise RuntimeError('Response exceeds limit')
        while b'\n' in buf:
            line,_,tail=buf.partition(b'\n');buf[:]=tail
            msg=json.loads(line)
            if msg.get('id')==number: return msg
    raise TimeoutError('MCP request timed out')
try:
    init=request(1,'initialize',{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'offline-probe','version':'1'}})
    assert init['result']['serverInfo']['name']=='craft-anything'
    send({'jsonrpc':'2.0','method':'notifications/initialized'})
    listing=request(2,'tools/list',{})
    assert any(x['name']=='core_session_show' for x in listing['result']['tools'])
    result=request(3,'tools/call',{'name':'core_session_show','arguments':{}})
    assert not result['result'].get('isError',False)
    refused=request(4,'tools/call',{'name':'build_command_run','arguments':{'command':'echo synthetic'}})
    assert refused['result'].get('isError') is True
    print('PASS: no route; real MCP initialize, list, session read and restricted build refusal')
finally:
    try: os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError: pass
    proc.wait(timeout=5)
