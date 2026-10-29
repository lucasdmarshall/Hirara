"""A fake Docker client so the runner can be tested without a daemon.

It records what the runner asks for (image, create kwargs, the tar copied in,
whether it was killed/removed) so tests can assert on the *security-relevant*
choices — network disabled, read-only root, non-root user, caps dropped — not
just the happy path.
"""

from __future__ import annotations

import tarfile
import io

import pytest
from docker.errors import ImageNotFound
from requests.exceptions import ReadTimeout


class FakeContainer:
    def __init__(self, spec: "FakeContainerSpec") -> None:
        self._spec = spec
        self.id = "fakecontainer"
        self.started = False
        self.killed = False
        self.removed = False
        self.put_paths: list[str] = []
        self.put_code: str | None = None
        self.stdin_sent: bytes = b""
        self.attrs = {"State": {"OOMKilled": spec.oom_killed}}

    def put_archive(self, path, data):
        self.put_paths.append(path)
        # Unpack the single file so tests can assert the code was copied in.
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            member = tar.getmembers()[0]
            self.put_code = tar.extractfile(member).read().decode("utf-8")
        return True

    def start(self):
        self.started = True

    def attach_socket(self, params=None):
        container = self

        class _Sock:
            def __init__(self):
                self._sock = self

            def sendall(self, data):
                container.stdin_sent += data

            def shutdown(self, how):
                pass

            def close(self):
                pass

        return _Sock()

    def wait(self, timeout=None):
        if self._spec.raise_timeout:
            raise ReadTimeout("timed out")
        return {"StatusCode": self._spec.exit_code}

    def logs(self, stdout=False, stderr=False, stream=False, follow=False):
        if stdout:
            return iter([self._spec.stdout]) if stream else self._spec.stdout
        if stderr:
            return iter([self._spec.stderr]) if stream else self._spec.stderr
        return b""

    def reload(self):
        pass

    def kill(self):
        self.killed = True

    def remove(self, force=False):
        self.removed = True


class FakeContainerSpec:
    def __init__(
        self,
        *,
        exit_code=0,
        stdout=b"",
        stderr=b"",
        raise_timeout=False,
        oom_killed=False,
    ):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.raise_timeout = raise_timeout
        self.oom_killed = oom_killed


class FakeImages:
    def __init__(self, present):
        self.present = set(present)
        self.pulled: list[str] = []

    def get(self, image):
        if image not in self.present:
            raise ImageNotFound(f"no such image: {image}")
        return object()

    def pull(self, image):
        self.pulled.append(image)
        self.present.add(image)
        return object()


class FakeContainers:
    def list(self, **kwargs):
        return []

    def __init__(self, container_spec):
        self.container_spec = container_spec
        self.created_kwargs: dict | None = None
        self.container: FakeContainer | None = None

    def create(self, **kwargs):
        self.created_kwargs = kwargs
        self.container = FakeContainer(self.container_spec)
        return self.container


class FakeDockerClient:
    def __init__(self, *, present_images=(), container_spec=None):
        self.images = FakeImages(present_images)
        self.containers = FakeContainers(container_spec or FakeContainerSpec())

    def version(self):
        return {"Version": "99.9-fake"}


@pytest.fixture
def make_client():
    def _make(*, present_images=("python:3.12-slim",), **spec_kwargs):
        return FakeDockerClient(
            present_images=present_images,
            container_spec=FakeContainerSpec(**spec_kwargs),
        )

    return _make


@pytest.fixture(autouse=True)
def close_job_managers(monkeypatch):
    from hiraracode.jobs import JobManager
    original = JobManager.__init__
    managers = []
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        managers.append(self)
    monkeypatch.setattr(JobManager, '__init__', init)
    yield
    for manager in managers:
        manager.close()


@pytest.fixture(autouse=True)
def close_runners(monkeypatch):
    from hiraracode.runner import DockerRunner
    original = DockerRunner.__init__
    runners = []
    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        runners.append(self)
    monkeypatch.setattr(DockerRunner, '__init__', init)
    yield
    for runner in runners:
        runner.close()
