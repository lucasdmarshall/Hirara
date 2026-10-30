#!/usr/bin/env python3
"""Run package suites in separate processes (their test module names overlap)."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = [ROOT, *(p.parent for p in sorted(ROOT.glob('*/pyproject.toml'))
                    if (p.parent / 'tests').is_dir())]


def main():
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT / 'src'), *(str(p / 'src') for p in PACKAGES[1:])])
    failed = []
    for package in PACKAGES:
        print(f'Running {package.name}', flush=True)
        result = subprocess.run([sys.executable, '-m', 'pytest', '-q',
                                 '-o', 'asyncio_default_fixture_loop_scope=function', *sys.argv[1:]],
                                cwd=package, env=env)
        if result.returncode:
            failed.append(package.name)
    if failed:
        print('Failed packages: ' + ', '.join(failed), file=sys.stderr)
    return bool(failed)


if __name__ == '__main__':
    sys.exit(main())
