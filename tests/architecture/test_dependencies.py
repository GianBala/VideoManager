"""Protege a regra de dependência, inclusive imports usados só em anotações."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2] / 'src' / 'videomanager'


def test_camadas_internas_nao_conhecem_adaptadores():
    violations = []
    for layer in ('domain', 'application'):
        allowed = {'domain'} if layer == 'domain' else {'domain', 'application'}
        for path in (ROOT / layer).rglob('*.py'):
            module = 'videomanager.' + '.'.join(path.relative_to(ROOT).with_suffix('').parts)
            package = module if path.name == '__init__.py' else module.rpartition('.')[0]
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    base = importlib.util.resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module or ''
                    names = [base] + [base + '.' + a.name for a in node.names]
                for name in names:
                    parts = name.split('.')
                    if parts[0] == 'videomanager':
                        valid = len(parts) == 1 or parts[1] in allowed
                    else:
                        valid = parts[0] in sys.stdlib_module_names and parts[0] not in {'subprocess', 'socket', 'urllib', 'http'}
                    if not valid:
                        violations.append(f'{path.relative_to(ROOT)}:{node.lineno} -> {name}')
    assert not violations, '\n'.join(violations)


def test_importacao_interna_sem_dependencias_desktop():
    # -S remove site-packages: uma dependência transitiva externa também falha.
    script = """
import sys, pkgutil, importlib
sys.path.insert(0, 'src')
for name in ('videomanager.domain', 'videomanager.application'):
    package = importlib.import_module(name)
    for module in pkgutil.walk_packages(package.__path__, name + '.'):
        importlib.import_module(module.name)
assert not any(n.startswith(('PySide6', 'yt_dlp', 'videomanager.core', 'videomanager.infrastructure', 'videomanager.ui')) for n in sys.modules)
"""
    subprocess.run([sys.executable, '-S', '-c', script], cwd=ROOT.parents[1], check=True)


def test_fronteiras_externas_e_ausencia_de_ciclos():
    modules = {}
    for path in ROOT.rglob('*.py'):
        name = 'videomanager.' + '.'.join(path.relative_to(ROOT).with_suffix('').parts)
        modules[name.removesuffix('.__init__')] = path
    graph = {name: set() for name in modules}
    violations = []
    for name, path in modules.items():
        package = name if path.name == '__init__.py' else name.rpartition('.')[0]
        layer = path.relative_to(ROOT).parts[0]
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            targets = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = importlib.util.resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module or ''
                targets = [base] + [base + '.' + a.name for a in node.names]
            for target in targets:
                if layer == 'presentation' and target.startswith(('videomanager.infrastructure', 'videomanager.bootstrap', 'yt_dlp', 'subprocess', 'platformdirs')):
                    violations.append(f'{name}:{node.lineno} -> {target}')
                if layer == 'infrastructure' and target.startswith(('videomanager.presentation', 'videomanager.bootstrap')):
                    violations.append(f'{name}:{node.lineno} -> {target}')
                if target.startswith(('videomanager.core', 'videomanager.workers', 'videomanager.ui')):
                    violations.append(f'Import legado: {name} -> {target}')
                if target in modules and target != name:
                    graph[name].add(target)
    assert not violations, '\n'.join(violations)
    visited = set()
    def visit(name, stack):
        assert name not in stack, 'Ciclo: ' + ' -> '.join((*stack, name))
        if name in visited:
            return
        for child in graph[name]:
            visit(child, (*stack, name))
        visited.add(name)
    for name in graph:
        visit(name, ())
