"""Use only the dedicated local Docker daemon; never host workloads."""
import os
import time
import uuid
import pytest
from hiraracode.config import ExecConfig
from hiraracode.runner import DockerRunner
from hiraracode.jobs import JobManager

pytestmark = pytest.mark.skipif(os.getenv('HIRARA_INTEGRATION') != '1', reason='integration opt-in')


def runner():
    import docker
    client = docker.DockerClient(base_url='unix:///var/run/docker.sock', timeout=5)
    return DockerRunner(ExecConfig(executor_id='audit-test-' + uuid.uuid4().hex,
                                   auto_pull=False, max_output_bytes=1024), client)


def test_real_docker_isolation_timeout_and_output_cap():
    r = runner()
    try:
        result = r.run(language='python', code='''
import os, socket
assert os.getuid() != 0
assert not os.path.exists('/var/run/docker.sock')
try:
    open('/outside', 'w')
except OSError:
    pass
else:
    raise AssertionError('root filesystem is writable')
try:
    socket.create_connection(('1.1.1.1', 80), timeout=.2)
except OSError:
    pass
else:
    raise AssertionError('network is reachable')
print('isolation-ok')
print('x' * 10000)
''')
        assert result.exit_code == 0, result.stderr
        assert 'isolation-ok' in result.stdout
        assert result.truncated and len(result.stdout.encode()) <= 1024
        timed = r.run(language='python', code='import time; time.sleep(10)', timeout=.2)
        assert timed.timed_out
        assert not r.client.containers.list(all=True, filters={'label': f'hiraracode-owner={r.config.executor_id}'})
    finally:
        r.close()
        r.client.close()


def test_background_deadline_without_polling_and_restart_reconciliation():
    r = runner()
    manager = JobManager(r)
    try:
        job = manager.start(language='python', code='import time; time.sleep(30)', timeout=.2)
        deadline = time.monotonic() + 8
        while job.state == 'running' and time.monotonic() < deadline:
            time.sleep(.05)  # Observe local state only; never call refresh/status.
        assert job.state == 'timed_out'
        assert not job.cleanup_pending
        orphan = r.client.containers.create(**r._create_kwargs(r.config.languages['python'],
                                            'import time; time.sleep(30)', None))
        orphan.start()
        restarted = DockerRunner(r.config, r.client)
        restarted.prepare()
        assert not r.client.containers.list(all=True, filters={'label': f'hiraracode-owner={r.config.executor_id}'})
        restarted.close()
    finally:
        manager.close()
        r.client.close()
