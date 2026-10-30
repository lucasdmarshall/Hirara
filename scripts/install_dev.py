#!/usr/bin/env python3
"""Install matching source packages together, before their versions reach PyPI."""
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    projects = {}
    for file in [ROOT / 'pyproject.toml', *sorted(ROOT.glob('*/pyproject.toml'))]:
        project = tomllib.loads(file.read_text())['project']
        projects[project['name']] = (file.parent, project)
    selected = set(projects)
    if '--sdk' in sys.argv[1:]:
        selected = {'hirara', 'hirara-core', 'hirara-hub', 'hirara-native'}
        selected.update(re.split(r'[<>=!~\[]', dependency, maxsplit=1)[0]
                        for dependency in projects['hirara'][1]['optional-dependencies']['local'])
    args = [sys.executable, '-m', 'pip', 'install', '-c', str(ROOT / 'constraints-release.txt')]
    for name in sorted(selected):
        path, project = projects[name]
        extras = sorted({'dev', 'service', 'mcp'} & set(project.get('optional-dependencies', {})))
        spec = str(path) + ('[' + ','.join(extras) + ']' if extras else '')
        args.extend(['-e', spec])
    subprocess.run(args, check=True)


if __name__ == '__main__':
    main()
