# Contributing to Noxen

Thank you for your interest in contributing to Noxen.

## License

Noxen is licensed under the Business Source License 1.1 (BSL-1.1). By contributing, you agree that your contributions will be licensed under the same terms. See [LICENSE](LICENSE) for details.

## What we accept

- **Bug fixes** — with test coverage
- **New LLM providers** — OpenAI-compatible or custom integrations
- **New tree-sitter language grammars** — for code analysis
- **Documentation** — improvements, translations, tutorials
- **Tests** — additional coverage for existing features
- **Performance** — optimizations with benchmarks

## How to contribute

1. **Fork** the repository
2. **Create a branch** from `main`: `git checkout -b fix/your-fix-name`
3. **Write tests** for your changes
4. **Run the test suite**: `.venv/bin/python -m pytest tests/ -q`
5. **Run pre-push checks**: `./scripts/pre_push_check.sh`
6. **Submit a Pull Request** with a clear description

## Requirements

- All tests must pass before submitting a PR
- No hardcoded API keys or secrets
- Follow existing code style and patterns
- Add SPDX headers to new core files:
  ```python
  # SPDX-License-Identifier: BSL-1.1
  # Copyright (c) 2026 Noxen. See LICENSE for details.
  ```

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q
```

## Contact

- Development: dev@noxen.ai
- Security issues: security@noxen.ai
