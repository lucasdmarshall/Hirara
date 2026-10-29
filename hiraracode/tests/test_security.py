import concurrent.futures
import threading
import time
import pytest
from hiraracode.config import ExecConfig
from hiraracode.jobs import JobManager
from hiraracode.runner import DockerRunner, RunnerError, read_logs


class Container:
    def __init__(self):
        self.status = 'created'
        self.attrs = {'State': {'ExitCode': 0, 'OOMKilled': False}}
        self.removed = False
        self.fail_reload = False
        self.fail_remove = False
    def start(self): self.status = 'running'
    def reload(self):
        if self.fail_reload: raise RuntimeError('daemon temporarily unavailable')
    def kill(self): self.status = 'exited'
    def logs(self, **kwargs): return iter([b'output'])
    def remove(self, **kwargs):
        if self.fail_remove: raise RuntimeError('temporary failure')
        self.removed = True


class Client:
    def __init__(self):
        self.containers = self
        self.images = self
        self.orphans = []
        self.factory = Container
    def list(self, **kwargs): return self.orphans
    def get(self, image): return object()
    def create(self, **kwargs): return self.factory()


def manager(**cfg):
    client = Client()
    runner = DockerRunner(ExecConfig(**cfg), client)
    return JobManager(runner), client


def test_atomic_job_admission_includes_inflight_creation():
    jobs, client = manager(max_jobs=1)
    entered, release = threading.Event(), threading.Event()
    def create():
        entered.set()
        assert release.wait(3)
        return Container()
    client.factory = create
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(jobs.start, language='python', code='pass')
        assert entered.wait(2)
        try:
            with pytest.raises(RunnerError, match='CCODE_MAX_JOBS'):
                jobs.start(language='python', code='pass')
        finally:
            release.set()
        assert first.result().state == 'running'


def test_deadline_runs_without_status_polling():
    jobs, client = manager()
    job = jobs.start(language='python', code='pass', timeout=.05)
    deadline = time.monotonic() + 3
    while job.state == 'running' and time.monotonic() < deadline:
        time.sleep(.02)
    assert job.state == 'timed_out'
    assert job.container.removed


def test_transient_daemon_failure_retains_ownership_and_retries_cleanup():
    jobs, client = manager()
    job = jobs.start(language='python', code='pass')
    job.container.fail_reload = True
    jobs.refresh(job)
    assert job.state == 'running' and job.error
    job.container.fail_reload = False
    job.container.fail_remove = True
    job.deadline = time.monotonic() - 1
    jobs.refresh(job)
    assert job.cleanup_pending
    job.container.fail_remove = False
    jobs.refresh(job)
    assert not job.cleanup_pending and job.container.removed


def test_restart_removes_only_containers_selected_by_owner():
    jobs, client = manager(executor_id='isolated-test')
    orphan = Container()
    client.orphans = [orphan]
    jobs.runner.prepare()
    assert orphan.removed


def test_log_reader_stops_before_consuming_entire_stream():
    consumed, closed = [], []
    class Verbose:
        def logs(self, **kwargs):
            assert kwargs['stream'] and not kwargs['follow']
            def chunks():
                try:
                    for _ in range(1000):
                        consumed.append(True)
                        yield b'0123456789'
                finally:
                    closed.append(True)
            return chunks()
    assert read_logs(Verbose(), stdout=True, limit=15) == b'012345678901234'
    assert len(consumed) == 2 and closed


@pytest.mark.parametrize('kwargs', [{'max_runs': 0}, {'pids_limit': 0}, {'cpus': float('nan')},
                                     {'max_jobs': -1}, {'user': '0:0'}])
def test_invalid_security_limits_fail_closed(kwargs):
    with pytest.raises(ValueError): ExecConfig(**kwargs)


def test_http_auth_and_tool_policy_run_before_docker(monkeypatch):
    from fastapi.testclient import TestClient
    from hiraracode.service import app
    monkeypatch.setenv('HIRARA_BACKEND_TOKEN', 'synthetic-token')
    monkeypatch.setenv('HIRARA_ALLOWED_TOOLS', '')
    with TestClient(app) as client:
        denied = client.post('/execute_code', json={'language': 'python', 'code': 'pass'})
        assert denied.status_code == 401
        allowed = client.post('/execute_code', headers={'Authorization': 'Bearer synthetic-token'},
                              json={'language': 'python', 'code': 'pass'})
        assert allowed.status_code == 200 and 'disabled' in allowed.json()['error']
